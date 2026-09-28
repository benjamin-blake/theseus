"""append_events' pre-SQL row gate (Decision 199): unknown/derived column rejection, a strict
per-sql_type Python type gate, NOT NULL checks, and intra-batch duplicate collapse/conflict.

Split out from append.py to keep it well under the 500-SLOC budget (Decision 128). Pure;
stdlib only (Decision 184 cl.2 plane-neutral rule) -- duckdb is never imported here.

DuckDB's own casts coerce silently (1.5 -> 2, True -> 1, a naive datetime assumed UTC), which is
exactly the failure mode this gate exists to close: every check below is a REJECTION, never a
lossy coercion.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


class AppendError(ValueError):
    """Raised by every rejection this module (and src/telemetry/append.py) performs."""


def reject_unknown_or_derived_columns(
    row: dict[str, Any],
    known_columns: frozenset[str],
    derived_columns: frozenset[str],
) -> None:
    """Raise if *row* carries a key outside known_columns, or a caller-supplied derived one.

    Derived columns (event_id, created_timestamp, tenant_id, project_id, and every table's own
    KEY_PLANS entity/FK columns) are computed by the write boundary and must never be supplied
    directly by the caller.
    """
    for key in row:
        if key in derived_columns:
            raise AppendError(f"column {key!r} is derived by the write boundary and must not be caller-supplied")
        if key not in known_columns:
            raise AppendError(f"unknown column {key!r} is not declared on this table's spec")


def check_not_null(row: dict[str, Any], not_null_columns: frozenset[str]) -> None:
    """Raise on the first NOT NULL column that is missing or explicitly None in *row*."""
    for col in not_null_columns:
        if row.get(col) is None:
            raise AppendError(f"column {col!r} is NOT NULL but missing or None")


def check_and_normalize_value(column: str, value: Any, sql_type: str) -> Any:
    """Strictly validate *value* against *sql_type* and return its normalised bind form.

    Rejections DuckDB's own CAST would otherwise silently coerce: bool is never accepted as
    BIGINT/DOUBLE; a float VARCHAR/BOOLEAN is rejected outright; NaN/inf DOUBLE is rejected; a
    naive datetime is rejected (never assumed UTC); an out-of-int64-range BIGINT is rejected.
    """
    if sql_type == "VARCHAR":
        if not isinstance(value, str):
            raise AppendError(f"column {column!r}: VARCHAR requires str, got {type(value).__name__}")
        return value
    if sql_type == "BIGINT":
        if isinstance(value, bool) or not isinstance(value, int):
            raise AppendError(f"column {column!r}: BIGINT requires int (not bool), got {type(value).__name__}")
        if not (-(2**63) <= value <= 2**63 - 1):
            raise AppendError(f"column {column!r}: BIGINT value {value} is out of int64 range")
        return value
    if sql_type == "DOUBLE":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AppendError(f"column {column!r}: DOUBLE requires int or float (not bool), got {type(value).__name__}")
        as_float = float(value)
        if not math.isfinite(as_float):
            raise AppendError(f"column {column!r}: DOUBLE requires a finite value, got {as_float}")
        return as_float
    if sql_type == "BOOLEAN":
        if not isinstance(value, bool):
            raise AppendError(f"column {column!r}: BOOLEAN requires bool, got {type(value).__name__}")
        return value
    if sql_type == "VARCHAR[]":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise AppendError(f"column {column!r}: VARCHAR[] requires list[str]")
        return value
    if sql_type == "TIMESTAMP WITH TIME ZONE":
        if not isinstance(value, datetime):
            raise AppendError(f"column {column!r}: TIMESTAMP WITH TIME ZONE requires a datetime, got {type(value).__name__}")
        offset = value.utcoffset()
        if offset is None:
            raise AppendError(f"column {column!r}: naive datetime is not accepted (a timezone is required)")
        utc_value = value.astimezone(timezone.utc)
        floored_micro = (utc_value.microsecond // 1000) * 1000
        return utc_value.replace(microsecond=floored_micro)
    raise AppendError(f"column {column!r}: unsupported sql_type {sql_type!r}")


_COLLAPSE_IGNORED_COLUMNS = frozenset({"created_timestamp", "producer_version"})


def differing_columns(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    ignore: frozenset[str] = _COLLAPSE_IGNORED_COLUMNS,
) -> list[str]:
    """Return the sorted column names where *a* and *b* differ, excluding *ignore*.

    *ignore* excludes the write-time stamp (created_timestamp) and declared provenance-only
    columns (producer_version) -- the grain-enforced-at-write compared-content definition
    (Decision-cited in data-modeling-standard.yaml's grain-enforced-at-write rule).
    """
    keys = (set(a) | set(b)) - ignore
    return sorted(k for k in keys if a.get(k) != b.get(k))


def collapse_or_reject_duplicates(
    rows: list[dict[str, Any]],
    dedupe_key: tuple[str, ...],
) -> tuple[list[dict[str, Any]], int]:
    """Collapse intra-batch rows sharing *dedupe_key* whose content is identical outside the
    ignored columns; reject conflicting ones. Rejects a NULL in any grain-key column.

    Returns (deduped_rows, collapsed_count). Preserves first-seen order. Raises AppendError
    naming the event_id (never first-wins) when two rows share the dedupe key but differ in any
    other stored column.
    """
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    collapsed = 0
    for row in rows:
        for col in dedupe_key:
            if row.get(col) is None:
                raise AppendError(f"grain-key column {col!r} is NULL (grain key={dedupe_key})")
        key = tuple(row[k] for k in dedupe_key)
        prior = seen.get(key)
        if prior is None:
            seen[key] = row
            deduped.append(row)
            continue
        diff = differing_columns(prior, row)
        if not diff:
            collapsed += 1
            continue
        raise AppendError(
            f"conflicting duplicate rows for event_id={row.get('event_id')!r} "
            f"(dedupe_key={dedupe_key}): differing columns {diff}"
        )
    return deduped, collapsed
