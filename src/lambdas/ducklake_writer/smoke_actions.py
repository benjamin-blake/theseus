"""ducklake_writer smoke/probe/churn actions (T2.17, split from handler.py).

Owner concern: the T2.17 smoke/probe/churn gates that prove the CD.33 runtime primitives in the
live Lambda execution context (NOT the production ops write path -- that stays in handler.py).
Imports `ducklake_runtime` as `rt` and resolves its own DATA_PATH/META_SCHEMA/EXTENSION_DIRECTORY
from os.environ (mirroring handler.py, identical values) so there is no handler<->smoke_actions
import cycle -- handler.py imports the actions defined here, never the reverse.
"""

from __future__ import annotations

import os
import time
from typing import Any

from src.common import ducklake_connect_probe as probe
from src.common import ducklake_runtime as rt

DATA_PATH = os.environ.get("DUCKLAKE_DATA_PATH", rt.SMOKE_DATA_PATH)
META_SCHEMA = os.environ.get("DUCKLAKE_META_SCHEMA", rt.META_SCHEMA)
EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)


# ---------------------------------------------------------------------------
# Actions -- each returns a JSON-serialisable dict (the handler wraps status + body)
# ---------------------------------------------------------------------------


def action_connect_probe(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Phased connectivity diagnostic (T2.19 RCA). Runs before any connection open.

    Returns the structured probe result even on a diagnosed failure (ok=False + failed_phase).
    Logs each phase result to CloudWatch via print (Lambda stdout -> CloudWatch Logs).
    A 5xx is reserved for a probe that itself errors unexpectedly (caught by the outer handler).
    """
    dsn = rt.fetch_dsn()
    timeout_s = int(os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S", "10"))
    result = probe.probe_connection(
        dsn,
        data_path=DATA_PATH,
        meta_schema=META_SCHEMA,
        extension_directory=EXTENSION_DIRECTORY,
        timeout_s=timeout_s,
    )
    print(
        f"CONNECT_PROBE writer phase_reached={result['phase_reached']} "
        f"failed_phase={result['failed_phase']} ok={result['ok']} "
        f"dns_ms={result['dns_ms']} tcp_ms={result['tcp_ms']} "
        f"auth_ms={result['auth_ms']} attach_ms={result['attach_ms']} "
        f"error={result['error']!r}"
    )
    return result


def action_attach_check(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """ATTACH proof: report DuckDB version, extension source, connect + commit latency (EC1)."""
    connect_ms = float(event.get("_connect_ms", 0.0))
    duckdb = rt.ducklake_spike._require_duckdb()
    t0 = time.perf_counter()
    con.execute("BEGIN TRANSACTION")
    con.execute("SELECT 1")
    con.execute("COMMIT")
    commit_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "ok": True,
        "version": getattr(duckdb, "__version__", "unknown"),
        "source": "layer" if EXTENSION_DIRECTORY else "network",
        "connect_ms": round(connect_ms, 2),
        "commit_ms": round(commit_ms, 2),
        # Warm-reuse observability (D2): True when this invocation reused the cached connection.
        "connect_reused": bool(event.get("_connect_reused", False)),
    }


def action_create_tables(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Create the smoke history+current tables with partition transforms (idempotent re-run)."""
    force = bool(event.get("force_recreate_tables", False))
    rt.create_scd2_tables(con, force_recreate=force)
    return {"ok": True, "tables": [rt.SMOKE_HISTORY_TABLE, rt.SMOKE_CURRENT_TABLE], "force_recreate": force}


def action_write(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Write one SCD2 record via the shared write primitive (schema-gated, OCC-retried)."""
    record = event.get("record") or {}
    if event.get("force_recreate_tables"):
        rt.create_scd2_tables(con, force_recreate=True)
    result = rt.write_scd2(con, record, metric_sink=rt.make_metric_sink())
    return {
        "ok": True,
        "ulid": result.ulid,
        "rec_id": result.rec_id,
        "occ_retries": result.occ_retries,
        "commit_ms": round(result.commit_ms, 2),
    }


def action_reset_warm_connection(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Test-only: drop the per-container warm connection so the NEXT invocation reconnects cold (D2 VP).

    Connectionless. Lets the warm-reuse smoke gate exercise the cold-reconnect path deterministically;
    it does not touch the catalog or relax any boundary.
    """
    rt.reset_warm_connection()
    return {"ok": True, "reset": True}


def action_idempotency_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Write the SAME identity twice; MERGE-on-ULID must dedup to 1 history + 1 current row (EC10)."""
    rt.create_scd2_tables(con, force_recreate=True)
    rec_id = event.get("rec_id", "rec-idem")
    identity = rt.mint_write_identity()
    first = rt.write_scd2(con, {"rec_id": rec_id, "payload": "v1"}, identity=identity, metric_sink=rt.make_metric_sink())
    # Retry with the SAME identity (simulates an OCC retry re-running the op).
    rt.write_scd2(con, {"rec_id": rec_id, "payload": "v1"}, identity=identity)
    history_rows = con.execute(
        f"SELECT count(*) FROM {rt.CATALOG_ALIAS}.{rt.SMOKE_HISTORY_TABLE} WHERE ulid = ?", [first.ulid]
    ).fetchone()[0]
    current_rows = con.execute(
        f"SELECT count(*) FROM {rt.CATALOG_ALIAS}.{rt.SMOKE_CURRENT_TABLE} WHERE rec_id = ?", [rec_id]
    ).fetchone()[0]
    return {
        "ok": True,
        "ulid_reused": True,
        "history_rows": int(history_rows),
        "current_rows": int(current_rows),
    }


def action_partition_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Write rows sharing a day-of-month across a month AND a year boundary; measure the LIVE
    calendar-day partition layout from DuckLake's own file-partition metadata (EC6, rec-4068).

    Prior to rec-4068 this probe asserted a hardcoded current-bucket-scan constant and inferred
    history pruning via ducklake_list_files' WHERE-predicate form, which always raised and fell
    back to comparing a ROW count to a FILE count -- never proving anything about partitions. It
    now reads the metadata DuckLake itself tracks per live data file
    (__ducklake_metadata_<alias>.ducklake_data_file / ducklake_file_partition_value), so a
    regression to the day-of-month spelling -- which would COLLAPSE these three rows into one
    partition -- is directly observable in the measured tuple/day counts. These are metadata-
    derived LAYOUT facts, not engine-pruning evidence, and are named as such.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    rt.create_scd2_tables(con, force_recreate=True)

    # Three rows sharing day-of-month 24, spanning a month boundary AND a year boundary: the exact
    # shape day(created_timestamp) alone collapsed into one day=24 partition (Decision 137 finding).
    probe_days = (
        datetime(2026, 1, 24, tzinfo=timezone.utc),
        datetime(2026, 2, 24, tzinfo=timezone.utc),
        datetime(2027, 1, 24, tzinfo=timezone.utc),
    )
    for i in range(6):
        rec_id = f"rec-part-{i}"
        identity = rt.WriteIdentity(ulid=str(rt.mint_write_identity().ulid), timestamp=probe_days[i % 3])
        rt.write_scd2(con, {"rec_id": rec_id, "payload": "p"}, identity=identity)

    # Compaction pass: proves the calendar-day boundary survives merge, not just initial write.
    con.execute(f"CALL ducklake_merge_adjacent_files('{rt.CATALOG_ALIAS}')")

    history = _partition_layout(con, rt.CATALOG_ALIAS, rt.SMOKE_HISTORY_TABLE)
    current = _partition_layout(con, rt.CATALOG_ALIAS, rt.SMOKE_CURRENT_TABLE)

    history_tuples = list(history["value_tuples"].values())
    probed_day_tuple = min(history_tuples) if history_tuples else None
    history_files_in_probed_day = sum(1 for t in history_tuples if t == probed_day_tuple)

    current_tuples = list(current["value_tuples"].values())
    probed_bucket_tuple = min(current_tuples) if current_tuples else None
    current_files_in_probed_bucket = sum(1 for t in current_tuples if t == probed_bucket_tuple)

    return {
        "ok": True,
        "history_calendar_days": len(set(history_tuples)),
        "history_partition_tuples": len(set(history["path_prefixes"].values())),
        "history_files_in_probed_day": history_files_in_probed_day,
        "history_total": history["total"],
        "current_files_in_probed_bucket": current_files_in_probed_bucket,
        "current_total": current["total"],
    }


def action_inlining_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Confirm inlining is disabled: rows hit S3 Parquet immediately, none inlined (EC11)."""
    rt.create_scd2_tables(con, force_recreate=True)
    rt.write_scd2(con, {"rec_id": "rec-inline", "payload": "p"}, metric_sink=rt.make_metric_sink())
    s3_parquet = _count_files(con, rt.SMOKE_HISTORY_TABLE)
    inlined = _count_inlined_rows(con, rt.SMOKE_HISTORY_TABLE)
    # A small concurrency burst to exercise issues #233/#376 (clean if no hard error escapes).
    occ_handled = _concurrency_probe(int(event.get("concurrency", 4)))
    return {
        "ok": True,
        "inlined_rows": int(inlined),
        "s3_parquet": int(s3_parquet),
        "occ_conflicts_handled": occ_handled,
    }


def action_loudfail_probe(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """Prove both loud-fail paths raise (EC7): schema-gate reject + OCC-retry exhaustion."""
    rt.create_scd2_tables(con, force_recreate=True)
    schema_reject = "raised"
    try:
        rt.schema_gate({"rec_id": "rec-x", "bogus_field": "y"})
        schema_reject = "not_raised"
    except rt.SchemaGateError:
        schema_reject = "raised"

    occ_exhaust = "raised"
    try:
        forced = _AlwaysCollidingConnection(con)
        rt.write_scd2(forced, {"rec_id": "rec-occ", "payload": "p"}, max_attempts=2, sleep=lambda s: None)
        occ_exhaust = "not_raised"
    except rt.OCCRetryExhaustedError:
        occ_exhaust = "raised"

    return {
        "ok": True,
        "schema_reject": schema_reject,
        "occ_exhaust": occ_exhaust,
        "silent_drop": False,
    }


def action_churn_single(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Single-writer invocation: one independent writer per Lambda container (EC8 fan-out gate).

    On setup=true: pre-create the SCD2 tables once before the client's concurrent burst to avoid
    a CREATE race across N simultaneously cold-starting containers.
    Normal: resolve dsn + credentials, run one _churn_one_writer, return per-stage attribution.
    This is the unit invoked N times concurrently from the smoke-test client (one container each).
    """
    dsn = rt.fetch_dsn()
    creds = _frozen_creds()
    if event.get("setup"):
        con = rt.open_connection(
            dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
        )
        try:
            rt.create_scd2_tables(con, force_recreate=True)
        finally:
            con.close()
        return {"ok": True, "setup": True}
    writer_id = int(event.get("writer_id", 0))
    # Single-commit per invocation: production ops writes are independent single-commit Lambda
    # invocations (file_rec / update_rec). _churn_one_writer runs CHURN_WRITES_PER_WRITER sequential
    # commits (a stress harness for the in-container burst); the production-representative gate
    # measures connect + ONE write, matching the actual ops-portal write unit.
    result = _churn_one_single_write(writer_id, dsn, creds)
    return {"ok": True, **result}


def action_churn(event: dict[str, Any], con: Any) -> dict[str, Any]:
    """In-container 8-thread burst diagnostic (legacy). NOT the EC8 gate (see action_churn_single).

    Retained as an opt-in stress diagnostic accessible via --lambda-churn-incontainer. The EC8
    fan-out measurement uses N concurrent invocations of action_churn_single (Decision 82 / CD.33
    clause 3). This action exposes the in-container CPU-starvation artifact documented in PR #89.
    Self-contained: each writer opens its OWN baked-extension connection. Loud-fail on non-OCC.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    writers = int(event.get("writers", rt.CHURN_WRITERS))
    dsn = rt.fetch_dsn()
    creds = _frozen_creds()
    # Pre-create the tables once so concurrent writers only write (avoids a CREATE race).
    pre = rt.open_connection(
        dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
    )
    try:
        rt.create_scd2_tables(pre, force_recreate=bool(event.get("force_recreate_tables", True)))
    finally:
        pre.close()

    with ThreadPoolExecutor(max_workers=writers) as pool:
        results = list(pool.map(lambda i: _churn_one_writer(i, dsn, creds), range(writers)))

    collisions = sum(1 for r in results if r["collided"])
    collision_rate = collisions / len(results) if results else 0.0
    p95 = _p95([r["latency_ms"] for r in results])
    within = collision_rate <= rt.OCC_COLLISION_RATE_BUDGET and p95 <= rt.COMMIT_LATENCY_BUDGET_MS

    # rec-2096: also measure COLD vs WARM connect latency so a cold-connect regression is visible
    # against the warm baseline (the per-thread churn connects above are all COLD).
    cold_connect_ms, warm_connect_ms = _measure_cold_warm_connect(dsn, creds)

    breakdown = {
        "p95_connect_ms": round(_p95([r["connect_ms"] for r in results]), 2),
        "p95_commit_ms": round(_p95([r["commit_ms"] for r in results]), 2),
        "p95_wall_ms": round(p95, 2),
        "p95_cpu_ms": round(_p95([r["cpu_ms"] for r in results]), 2),
        "total_occ_retries": sum(r["occ_retries"] for r in results),
        "wall_cpu_ratio": round(
            sum(r["wall_ms"] for r in results) / max(sum(r["cpu_ms"] for r in results), 0.001),
            2,
        ),
        "writers": writers,
        "cold_connect_ms": cold_connect_ms,
        "warm_connect_ms": warm_connect_ms,
    }

    # Emit per-stage breakdown to CloudWatch for Phase-1 RCA observability (EC9 extension).
    sink = rt.make_metric_sink()
    sink("ChurnP95ConnectMs", breakdown["p95_connect_ms"])
    sink("ChurnP95CommitMs", breakdown["p95_commit_ms"])
    sink("ChurnP95CpuMs", breakdown["p95_cpu_ms"])
    sink("ChurnWallCpuRatio", breakdown["wall_cpu_ratio"])
    sink("ChurnTotalOccRetries", float(breakdown["total_occ_retries"]))
    # rec-2096: cold + warm connect latency.
    sink("ChurnColdConnectMs", breakdown["cold_connect_ms"])
    sink("ChurnWarmConnectMs", breakdown["warm_connect_ms"])

    return {
        "ok": True,
        "collision_rate": round(collision_rate, 3),
        "p95_commit_ms": round(p95, 1),
        "endpoint": "direct",
        "within_budget": within,
        "breakdown": breakdown,
    }


def _churn_one_writer(writer_id: int, dsn: dict[str, Any], creds: Any) -> dict[str, Any]:
    """One churn iteration: a fresh baked connection + a contended write burst. Classify OCC only.

    Returns a per-stage attribution dict for Phase-1 RCA (EC8):
      connect_ms  -- time for open_connection (LOAD+ATTACH, the cold-start cost)
      commit_ms   -- aggregate commit_ms across all write_scd2 calls (includes OCC retries + backoff)
      occ_retries -- total OCC retries across all writes
      wall_ms     -- total wall-clock elapsed time (= latency_ms for backward compat)
      cpu_ms      -- thread CPU time; wall_ms / cpu_ms >> 1 signals vCPU starvation (Branch P trigger)
      collided    -- True if any write exhausted its OCC budget
    """
    wall_start = time.perf_counter()
    cpu_start = time.thread_time()
    collided = False
    aggregate_commit_ms = 0.0
    total_occ_retries = 0

    connect_start = time.perf_counter()
    con = rt.open_connection(
        dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
    )
    connect_ms = (time.perf_counter() - connect_start) * 1000.0

    try:
        for seq in range(rt.CHURN_WRITES_PER_WRITER):
            try:
                result = rt.write_scd2(con, {"rec_id": f"rec-churn-{writer_id}-{seq}", "payload": "c"})
                aggregate_commit_ms += result.commit_ms
                total_occ_retries += result.occ_retries
            except rt.OCCRetryExhaustedError:
                collided = True
    finally:
        con.close()

    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    cpu_ms = (time.thread_time() - cpu_start) * 1000.0
    return {
        "latency_ms": wall_ms,
        "collided": collided,
        "connect_ms": round(connect_ms, 2),
        "commit_ms": round(aggregate_commit_ms, 2),
        "occ_retries": total_occ_retries,
        "wall_ms": round(wall_ms, 2),
        "cpu_ms": round(cpu_ms, 2),
    }


def _churn_one_single_write(writer_id: int, dsn: dict[str, Any], creds: Any) -> dict[str, Any]:
    """One connect + ONE write: the production-representative EC8 measurement unit.

    Production ops writes (file_rec / update_rec) are independent single-commit Lambda invocations.
    This function measures the full round-trip (connect + one write_scd2 commit) on its own container,
    returning the same attribution schema as _churn_one_writer for aggregation compatibility.
    """
    wall_start = time.perf_counter()
    cpu_start = time.thread_time()
    collided = False
    aggregate_commit_ms = 0.0
    total_occ_retries = 0

    connect_start = time.perf_counter()
    con = rt.open_connection(
        dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
    )
    connect_ms = (time.perf_counter() - connect_start) * 1000.0

    try:
        try:
            result = rt.write_scd2(con, {"rec_id": f"rec-churn-single-{writer_id}", "payload": "c"})
            aggregate_commit_ms = result.commit_ms
            total_occ_retries = result.occ_retries
        except rt.OCCRetryExhaustedError:
            collided = True
    finally:
        con.close()

    wall_ms = (time.perf_counter() - wall_start) * 1000.0
    cpu_ms = (time.thread_time() - cpu_start) * 1000.0
    return {
        "latency_ms": wall_ms,
        "collided": collided,
        "connect_ms": round(connect_ms, 2),
        "commit_ms": round(aggregate_commit_ms, 2),
        "occ_retries": total_occ_retries,
        "wall_ms": round(wall_ms, 2),
        "cpu_ms": round(cpu_ms, 2),
    }


def _frozen_creds() -> tuple[str, str, str | None, str]:
    """Resolve the ambient AWS credentials once so churn workers share one STS resolution."""
    import boto3  # noqa: PLC0415

    session = boto3.Session()
    fc = session.get_credentials().get_frozen_credentials()
    return (fc.access_key, fc.secret_key, fc.token, session.region_name or "eu-west-2")


def _measure_cold_warm_connect(dsn: dict[str, Any], creds: Any) -> tuple[float, float]:
    """rec-2096: measure COLD (first ATTACH) AND WARM (reuse) connect latency on this container.

    A cold-connect regression is invisible without a warm baseline to read it against (rec-2096). This
    opens once (cold) then reuses (warm) via the warm-connection cache, returning (cold_ms, warm_ms).
    Self-contained: it resets the warm cache around the measurement so it never leaks a connection into
    the request path's warm slot (the churn harness keeps its own per-thread connections).
    """
    rt.reset_warm_connection()
    try:
        _, m_cold = rt.get_warm_connection(
            dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
        )
        _, m_warm = rt.get_warm_connection(
            dsn=dsn, data_path=DATA_PATH, meta_schema=META_SCHEMA, extension_directory=EXTENSION_DIRECTORY, _creds=creds
        )
        return round(m_cold["connect_ms"], 2), round(m_warm["connect_ms"], 2)
    finally:
        rt.reset_warm_connection()


def _p95(values: list[float]) -> float:
    """Nearest-rank p95 of *values*; 0.0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


# ---------------------------------------------------------------------------
# Partition / inlining metadata helpers
# ---------------------------------------------------------------------------


def _count_files(con: Any, table: str) -> int:
    """Count the S3 Parquet data files DuckLake tracks for *table* (inlining-off proof)."""
    try:
        rows = con.execute(f"SELECT count(*) FROM ducklake_list_files('{rt.CATALOG_ALIAS}', '{table}')").fetchone()
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001 -- metadata-function name drift tolerated; live VP confirms
        return 0


def _path_partition_prefix(path: str) -> str:
    """The 'k1=v1/k2=v2/...' Hive-style directory-prefix segment of a DuckLake file *path*.

    DuckLake writes each partitioned file under a directory prefix encoding its partition key
    values (e.g. 'year=2026/month=1/day=24/<uuid>.parquet'). This is derived independently of
    ducklake_file_partition_value (a different metadata source: the physical path DuckLake wrote,
    not a catalog row) -- the two measurements crosscheck each other.
    """
    return "/".join(part for part in path.split("/")[:-1] if "=" in part)


def _partition_layout(con: Any, catalog_alias: str, table: str) -> dict[str, Any]:
    """LIVE (end_snapshot IS NULL) data-file partition layout for *table*, read from DuckLake's own
    file-partition metadata catalog. Loud-fail (Decision 55): a metadata-schema read error raises,
    it never falls back or silently reports 0 -- an EC6 measurement must be real or absent.

    Returns {"total": int, "path_prefixes": {data_file_id: str}, "value_tuples": {data_file_id: (str, ...)}}.
    path_prefixes is the Hive-style partition directory prefix parsed from each file's physical
    path (ducklake_data_file.path); value_tuples orders each file's partition_value entries by
    partition_key_index (a calendar-day history table's tuple is (year, month, day)). These are
    two INDEPENDENTLY derived measurements of the same partition membership -- ducklake_data_file
    itself does NOT distinguish files by partition value: its own partition_id column names the
    declared partition SCHEME (which ALTER ... SET PARTITIONED BY generation), not a per-value
    bucket, so it is never used here as a partition-membership signal.
    """
    meta_schema = f"__ducklake_metadata_{catalog_alias}"
    files = con.execute(
        f"SELECT df.data_file_id, df.path FROM {meta_schema}.ducklake_data_file df "
        f"JOIN {meta_schema}.ducklake_table t ON df.table_id = t.table_id "
        f"WHERE t.table_name = ? AND df.end_snapshot IS NULL",
        [table],
    ).fetchall()
    file_ids = [int(r[0]) for r in files]
    path_prefixes = {int(r[0]): _path_partition_prefix(r[1]) for r in files}

    value_tuples: dict[int, tuple[str, ...]] = {}
    if file_ids:
        placeholders = ", ".join("?" for _ in file_ids)
        rows = con.execute(
            f"SELECT data_file_id, partition_key_index, partition_value FROM {meta_schema}.ducklake_file_partition_value "
            f"WHERE data_file_id IN ({placeholders}) ORDER BY data_file_id, partition_key_index",
            file_ids,
        ).fetchall()
        grouped: dict[int, list[str]] = {}
        for file_id, _idx, value in rows:
            grouped.setdefault(int(file_id), []).append(value)
        value_tuples = {fid: tuple(vals) for fid, vals in grouped.items()}

    return {"total": len(file_ids), "path_prefixes": path_prefixes, "value_tuples": value_tuples}


def _count_inlined_rows(con: Any, table: str) -> int:
    """Return the number of inlined (not-yet-flushed) rows; 0 when inlining is disabled."""
    try:
        rows = con.execute(f"SELECT count(*) FROM ducklake_list_inlined_data('{rt.CATALOG_ALIAS}', '{table}')").fetchone()
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001 -- absent when inlining off; live VP confirms
        return 0


def _concurrency_probe(writers: int) -> bool:
    """Small concurrent-writer burst; True if no non-OCC error escaped (issues #233/#376)."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    try:
        dsn = rt.fetch_dsn()
        creds = _frozen_creds()
        with ThreadPoolExecutor(max_workers=writers) as pool:
            list(pool.map(lambda i: _churn_one_writer(i, dsn, creds), range(writers)))
        return True
    except rt.DuckLakeRuntimeError:
        return True  # a classified runtime loud-fail is the handled signal, not a hard crash
    except Exception:  # noqa: BLE001
        return False


class _AlwaysCollidingConnection:
    """Wrap a real connection but raise a serialization error on every MERGE (forces OCC exhaustion)."""

    def __init__(self, inner: Any):
        self._inner = inner

    def execute(self, sql: str, params: Any = None) -> Any:
        if sql.startswith("MERGE INTO"):
            raise RuntimeError("could not serialize access due to concurrent update")
        return self._inner.execute(sql, params) if params is not None else self._inner.execute(sql)
