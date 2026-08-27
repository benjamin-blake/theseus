"""Data quality execution + aggregation over the DuckLake closed reader."""

from __future__ import annotations

import logging
import time
from typing import Any

import yaml

from scripts.data_quality_compile import build_clause8_checks, to_ducklake_sql
from scripts.data_quality_models import _DQ_DIR, Check, CheckResult, RunResult
from scripts.ops_portal.reader_transient import is_reader_unavailable as _is_reader_unavailable

logger = logging.getLogger(__name__)

# Ops governance tables on the DuckLake closed boundary (Decision 84 I-1): their checks route
# to the reader, which is the sole backend.
_OPS_TABLES: frozenset[str] = frozenset({"ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_execution_plans"})


def _ops_backend() -> str:
    """DuckLake is the sole ops backend (Decision 84 I-1; the rollback flag is retired)."""
    return "ducklake"


def _verdict_for(check: Check, violation_count: int, duration: float) -> CheckResult:
    """Map a violation count to a verdict."""
    if violation_count == 0:
        return CheckResult(check=check, verdict="PASS", violation_count=0, duration_seconds=duration)
    # Tombstone resurrection is always HARD_GATE regardless of severity.
    if check.test_type == "tombstone_resurrection":
        return CheckResult(
            check=check,
            verdict="HARD_GATE",
            violation_count=violation_count,
            detail=f"resurrected tombstoned record ({violation_count} row(s))",
            duration_seconds=duration,
        )
    if not check.enforced:
        verdict = "UNENFORCED_FAIL" if check.severity == "error" else "WARN"
    else:
        verdict = "FAIL" if check.severity == "error" else "WARN"
    return CheckResult(
        check=check,
        verdict=verdict,
        violation_count=violation_count,
        detail=f"{violation_count} violation(s)",
        duration_seconds=duration,
    )


def _query_ops_rows(reader: Any, table: str, sql: str) -> list[dict]:
    """Call the reader's raising _invoke surface and return the rows list."""
    body = reader._invoke({"action": "query_ops", "table": table, "sql": sql, "params": []})
    return list(body.get("rows", []))


def _execute_check_ducklake(check: Check, reader: Any) -> CheckResult:
    """Execute a single ops-table check against DuckLake via the closed reader. DuckDB dialect.

    `ulid_history_unique` runs entirely over the history table (its whole SQL uses `{tbl}`, resolved
    here to the history table via read_ops_history's naming). Any OTHER check's SQL may additionally
    reference `{hist}` for a genuine cross-table current-vs-history expression (e.g. a composite
    history-uniqueness check, or a current-regressed-behind-history guard): `{hist}` is resolved
    client-side to the physical history table name before the query reaches query_ops, while `{tbl}`
    (if also present) is left for query_ops/query_current's own server-side current-table
    substitution -- so a single query can reference both tables at once. A cross-table `relationships`
    check cannot be expressed even with this and is SKIPPED on this backend (priority_queue FK is
    dormant + unenforced).
    """
    start = time.time()
    if check.test_type == "relationships":
        return CheckResult(
            check=check,
            verdict="SKIP",
            detail="cross-table FK not run on ducklake backend (dormant/unenforced)",
            duration_seconds=0.0,
        )
    table = check.table
    is_history = check.test_type == "ulid_history_unique"
    sql = to_ducklake_sql(check.sql, table, "agent_platform")
    if "{hist}" in sql:
        from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

        sql = sql.replace("{hist}", f"ops_catalog.{resolve_table_spec(table).history_table}")
    try:
        if is_history:
            from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

            hist = resolve_table_spec(table).history_table
            rows = _query_ops_rows(reader, table, sql.replace("{tbl}", f"ops_catalog.{hist}"))
        else:
            rows = _query_ops_rows(reader, table, sql)
        if rows is None:
            return CheckResult(
                check=check, verdict="ERROR", detail="ducklake reader returned None", duration_seconds=time.time() - start
            )
        violation_count = int(next(iter(rows[0].values()))) if rows else 0
    except Exception as exc:  # noqa: BLE001
        verdict = "UNAVAILABLE" if _is_reader_unavailable(exc) else "ERROR"
        return CheckResult(
            check=check, verdict=verdict, detail=f"ducklake query failed: {exc}", duration_seconds=time.time() - start
        )
    return _verdict_for(check, violation_count, time.time() - start)


def apply_backend_routing(all_checks: list[Check], database: str, *, table_filter: str | None = None) -> list[Check]:
    """Rewrite the ops-table checks for the DuckLake reader (sole backend, Decision 84 I-1).

    Translates each ops-table check's SQL to the DuckDB dialect over the `current` TABLE and appends
    the CD.33 clause-8 checks. Shared by main() and the DQ scaffold route so both go through the
    closed reader. Mutates and returns *all_checks*.
    """
    for c in all_checks:
        if c.table in _OPS_TABLES:
            c.sql = to_ducklake_sql(c.sql, c.table, database)
            c.backend = "ducklake"
    ops_spec_yaml = yaml.safe_load((_DQ_DIR / "ops.yaml").read_text(encoding="utf-8")) or {}
    all_checks.extend(build_clause8_checks(ops_spec_yaml, database, table_filter=table_filter))
    return all_checks


def run_checks(
    checks: list[Check],
    *,
    dry_run: bool = False,
    profile_name: str | None = None,
) -> RunResult:
    """Execute all checks against the DuckLake reader and return the aggregate result."""
    run_start = time.time()

    if dry_run:
        results = [CheckResult(check=c, verdict="SKIP", detail="dry-run") for c in checks]
        return RunResult(
            results=results,
            verdict="SKIP",
            duration_seconds=time.time() - run_start,
        )

    reader = None
    if checks:
        try:
            from src.common.ducklake_reader_client import DuckLakeReader  # noqa: PLC0415

            reader = DuckLakeReader(profile=profile_name)
        except ImportError:
            logger.error("DuckLake reader client unavailable")
            return RunResult(
                results=[CheckResult(check=c, verdict="SKIP", detail="ducklake reader unavailable") for c in checks],
                verdict="SKIP",
                duration_seconds=0.0,
            )

    results: list[CheckResult] = []
    for check in checks:
        result = _execute_check_ducklake(check, reader)
        results.append(result)
        # Log as we go
        symbol = {
            "PASS": ".",
            "FAIL": "F",
            "UNENFORCED_FAIL": "U",
            "WARN": "W",
            "ERROR": "E",
            "SKIP": "S",
            "HARD_GATE": "G",
            "UNAVAILABLE": "A",
        }
        print(symbol.get(result.verdict, "?"), end="", flush=True)

    print()  # newline after progress dots

    # Aggregate verdict
    if not results:
        verdict = "ERROR"
    else:
        has_hard_gate = any(r.verdict == "HARD_GATE" for r in results)
        has_fail = any(r.verdict == "FAIL" and r.check.enforced for r in results)
        has_error = any(r.verdict == "ERROR" for r in results)
        has_unavailable = any(r.verdict == "UNAVAILABLE" for r in results)
        verdict = (
            "HARD_GATE" if has_hard_gate else "FAIL" if (has_fail or has_error) else "DEGRADED" if has_unavailable else "PASS"
        )

    return RunResult(
        results=results,
        verdict=verdict,
        duration_seconds=time.time() - run_start,
    )
