"""DuckLake partition-layout MUTATE half (Decision 204, PLAN-ducklake-partition-layout-remediation).

MUTATE half, maintenance bundle only -- never the reader, writer, or smoke bundles (the reader
holds the same owner-privileged Neon credential as the writer, so mutating code must never ship
where the reader ships; see ducklake_partition_layout.py's READ half, which this module imports but
which never imports back, Decision 80 acyclic-import discipline).

Two verbs:
  - alter_to_declared: no-op-free ALTER TABLE ... SET PARTITIONED BY, one table per transaction,
    only where the live spec differs from declared.
  - rewrite_legacy_layout: re-lays a HISTORY table's legacy-scheme files onto the (already-ALTERed)
    declared scheme in one row-preserving, digest-proven transaction, refusing a non-history table,
    a table with no legacy files, or a table whose live spec still drifts from declared.

Both share the writer's own bounded OCC-retry policy (is_occ_collision / OCC_MAX_ATTEMPTS /
_occ_backoff imported from ducklake_writes, Decision 81 cl.3 -- never a second retry policy).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from src.common import ducklake_maintenance_scope as maintenance_scope
from src.common.ducklake_partition_layout import (
    PartitionDrift,
    compare_to_declared,
    read_partition_layout,
)
from src.common.ducklake_scd2_schema import CATALOG_ALIAS, DuckLakeRuntimeError, load_field_semantics
from src.common.ducklake_writes import OCC_MAX_ATTEMPTS, _occ_backoff, is_occ_collision

_SNAPSHOT_TABLE = "_partition_rewrite_snap"


class PartitionRewriteError(DuckLakeRuntimeError):
    """Loud-fail for the mutate half: a refused precondition, an exhausted OCC retry budget, a
    pre-commit digest mismatch, or a post-commit proof failure. A non-OCC duckdb error is wrapped
    here with its original message preserved and chained (structured 500, never a raw FunctionError)."""


def _safe_rollback(con: Any) -> None:
    """Roll back the current transaction, swallowing a 'no active transaction' error only.

    Kept as this module's own tiny copy rather than importing ducklake_writes._safe_rollback --
    each maintenance-concern module owns its rollback primitive (mirrors ducklake_control_tables'
    ENTITY_COUNTERS_TABLE / _safe_rollback precedent, Decision 80)."""
    try:
        con.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- rollback failure must not mask the original error
        pass


def _row_proof(con: Any, table_ref: str) -> tuple[int, str]:
    """(row_count, digest) for *table_ref* -- a full-row, NULL-explicit, order-independent digest.

    Each row is cast AS A WHOLE to VARCHAR (a struct rendering, e.g. "{'a': x, 'b': NULL}") so a
    NULL column value renders explicitly and a column shift cannot collapse into a false match;
    per-row hashes are sorted before aggregation so row ORDER never affects the digest.
    """
    row = con.execute(
        f"SELECT count(*), md5(coalesce(string_agg(row_hash, '|' ORDER BY row_hash), '')) "
        f"FROM (SELECT md5(t::VARCHAR) AS row_hash FROM (SELECT * FROM {table_ref}) AS t) AS hashed"
    ).fetchone()
    return int(row[0]), str(row[1])


def alter_to_declared(
    con: Any,
    drifts: list[PartitionDrift],
    *,
    catalog_alias: str = CATALOG_ALIAS,
    max_attempts: int = OCC_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Issue ALTER TABLE ... SET PARTITIONED BY <declared_spec> for every drifted table (no-op-free:
    a table whose live spec already matches declared is never named in *drifts* by compare_to_declared).

    One table per transaction, under the writer's own bounded OCC-retry policy: a serialization
    conflict retries with backoff+jitter up to *max_attempts*; the ceiling raises PartitionRewriteError.
    Returns the list of physical table names altered, in *drifts* order.
    """
    altered: list[str] = []
    for drift in drifts:
        fq = f"{catalog_alias}.{drift.physical}"
        attempt = 0
        while True:
            attempt += 1
            try:
                con.execute("BEGIN TRANSACTION")
                con.execute(f"ALTER TABLE {fq} SET PARTITIONED BY ({drift.declared_spec})")
                con.execute("COMMIT")
                break
            except Exception as exc:  # noqa: BLE001 -- classify, then retry-or-raise
                _safe_rollback(con)
                if is_occ_collision(exc):
                    if attempt < max_attempts:
                        _occ_backoff(attempt, sleep=sleep)
                        continue
                    raise PartitionRewriteError(
                        f"{drift.physical!r}: ALTER TABLE SET PARTITIONED BY OCC retry budget exhausted "
                        f"after {attempt} attempts: {exc}"
                    ) from exc
                raise PartitionRewriteError(
                    f"{drift.physical!r}: ALTER TABLE SET PARTITIONED BY ({drift.declared_spec}) failed: {exc}"
                ) from exc
        altered.append(drift.physical)
    return altered


def rewrite_legacy_layout(
    con: Any,
    physical: str,
    *,
    catalog_alias: str = CATALOG_ALIAS,
    semantics: dict[str, Any] | None = None,
    max_attempts: int = OCC_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    uuid_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> dict[str, Any]:
    """Re-lay *physical*'s legacy-scheme files onto its (already-declared) calendar-day scheme.

    Refuses: a non-history table (current projections rebuild from history, Decision 81 cl.8, and
    are never re-laid; control is refused by its own policy-matrix cell before this is even
    reached); a table with zero legacy-scheme files; a table whose live spec still differs from
    declared (alter_to_declared must run first).

    Per attempt, inside one transaction: captures pre_snapshot_id from <alias>.current_snapshot()
    (re-captured on every retry -- snapshot ids are catalog-global), tags the commit with a unique
    per-attempt token via <alias>.set_commit_message so one recovered snapshot row yields both ids,
    snapshots the table into a TEMP table, DELETEs + re-INSERTs from the snapshot, and proves row
    count + full-row digest equality BEFORE COMMIT -- a mismatch ROLLS BACK and raises, never
    committing an unproven rewrite. A DuckLake transaction conflict retries with the writer's own
    bounded OCC policy; a non-OCC error raises immediately.

    After commit, commit_snapshot_id is resolved by the commit_message token (never "the latest
    snapshot", which a concurrent writer commit could be), and the proof is RE-PROVEN independently
    at AT (VERSION => commit) against AT (VERSION => pre), plus zero remaining legacy-scheme files.
    A post-commit proof failure RAISES with both snapshot ids and NEVER auto-restores -- restoration
    is a separately planned operation (docs/contracts/ducklake-partition-remediation.yaml's
    non-lossy formula), never improvised in-session.
    """
    semantics = semantics if semantics is not None else load_field_semantics()
    layouts = read_partition_layout(con, catalog_alias=catalog_alias, semantics=semantics)
    layout = layouts.get(physical)
    if layout is None:
        raise PartitionRewriteError(f"{physical!r} is not a live, classified table in this catalog")

    registry = maintenance_scope.build_registry(semantics)
    classified = registry.get(physical)
    if classified is None or classified.side != "history":
        side = classified.side if classified is not None else "unclassified"
        raise PartitionRewriteError(
            f"{physical!r} refuses rewrite_partition_layout: only a HISTORY-side table may be re-laid "
            f"(current projections rebuild from history, Decision 81 cl.8) -- side={side!r}"
        )

    if layout.legacy_scheme_files == 0:
        raise PartitionRewriteError(f"{physical!r} refuses rewrite_partition_layout: no legacy-scheme files to re-lay")

    drifts = compare_to_declared({physical: layout}, semantics=semantics)
    if drifts:
        raise PartitionRewriteError(
            f"{physical!r} refuses rewrite_partition_layout: live spec still differs from declared "
            f"(live={drifts[0].live} declared={drifts[0].declared}) -- run alter_to_declared first"
        )

    fq = f"{catalog_alias}.{physical}"
    files_before = layout.live_files
    attempts = 0
    pre_snapshot_id: int | None = None
    token: str | None = None

    while True:
        attempts += 1
        try:
            con.execute("BEGIN TRANSACTION")
            con.execute(f"DROP TABLE IF EXISTS {_SNAPSHOT_TABLE}")
            pre_snapshot_id = int(con.execute(f"SELECT id FROM {catalog_alias}.current_snapshot()").fetchone()[0])
            token = f"{uuid_factory()}:pre={pre_snapshot_id}"
            con.execute(f"CALL {catalog_alias}.set_commit_message(?, ?)", ["rewrite_partition_layout", token])
            con.execute(f"CREATE TEMP TABLE {_SNAPSHOT_TABLE} AS SELECT * FROM {fq}")
            rows_pre, digest_pre = _row_proof(con, _SNAPSHOT_TABLE)
            con.execute(f"DELETE FROM {fq}")
            con.execute(f"INSERT INTO {fq} SELECT * FROM {_SNAPSHOT_TABLE}")
            rows_commit, digest_commit = _row_proof(con, fq)
            if rows_pre != rows_commit or digest_pre != digest_commit:
                raise PartitionRewriteError(
                    f"{physical!r}: pre-commit proof mismatch (rows_pre={rows_pre} rows_commit={rows_commit} "
                    f"digest_pre={digest_pre!r} digest_commit={digest_commit!r}) -- rolling back, never "
                    "committing an unproven rewrite"
                )
            con.execute("COMMIT")
            con.execute(f"DROP TABLE IF EXISTS {_SNAPSHOT_TABLE}")
            break
        except PartitionRewriteError:
            _safe_rollback(con)
            raise
        except Exception as exc:  # noqa: BLE001 -- classify, then retry-or-raise
            _safe_rollback(con)
            if is_occ_collision(exc):
                if attempts < max_attempts:
                    _occ_backoff(attempts, sleep=sleep)
                    continue
                raise PartitionRewriteError(
                    f"{physical!r}: rewrite OCC retry budget exhausted after {attempts} attempts: {exc}"
                ) from exc
            raise PartitionRewriteError(f"{physical!r}: rewrite transaction failed: {exc}") from exc

    commit_row = con.execute(
        f"SELECT snapshot_id FROM ducklake_snapshots('{catalog_alias}') WHERE commit_message = ?", [token]
    ).fetchone()
    if commit_row is None:
        raise PartitionRewriteError(
            f"{physical!r}: committed but could not resolve commit_snapshot_id via commit_message token "
            f"{token!r} (pre_snapshot_id={pre_snapshot_id}) -- STOP, file a Critical rec with both ids"
        )
    commit_snapshot_id = int(commit_row[0])

    # Post-commit proof: independently re-read AT both snapshot versions -- never trust the
    # in-transaction proof alone (Decision 55).
    rows_pre_reproof, digest_pre_reproof = _row_proof(con, f"{fq} AT (VERSION => {pre_snapshot_id})")
    rows_commit_reproof, digest_commit_reproof = _row_proof(con, f"{fq} AT (VERSION => {commit_snapshot_id})")
    post_layout = read_partition_layout(con, catalog_alias=catalog_alias, semantics=semantics)[physical]

    if (
        rows_pre_reproof != rows_commit_reproof
        or digest_pre_reproof != digest_commit_reproof
        or post_layout.legacy_scheme_files != 0
    ):
        raise PartitionRewriteError(
            f"{physical!r}: POST-COMMIT proof failed (pre_snapshot_id={pre_snapshot_id}, "
            f"commit_snapshot_id={commit_snapshot_id}, rows_pre={rows_pre_reproof}, rows_commit={rows_commit_reproof}, "
            f"legacy_scheme_files_after={post_layout.legacy_scheme_files}) -- STOP: no further tables; "
            "restoration is a separately planned operation, never improvised in-session"
        )

    return {
        "physical": physical,
        "pre_snapshot_id": pre_snapshot_id,
        "commit_snapshot_id": commit_snapshot_id,
        "rows_pre": rows_pre_reproof,
        "rows_commit": rows_commit_reproof,
        "digest_pre": digest_pre_reproof,
        "digest_commit": digest_commit_reproof,
        "files_before": files_before,
        "files_after": post_layout.live_files,
        "attempts": attempts,
    }
