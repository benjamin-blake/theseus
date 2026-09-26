"""Calendar-prefix partition-spec validator for DuckLake tables (rec-4068, Decision 137).

DuckLake's day()/month()/year() partition transforms are day-of-month / month-of-year /
calendar-year components -- NOT the Iceberg-v2 days-since-epoch semantics the day() spelling was
carried over from (Decision 137, Decision 81 cl.7). A bare day(created_timestamp) collapses rows
that share a day-of-month across a month or year boundary into one partition. The only accepted
temporal spelling is a full calendar PREFIX per column: year(c); year(c), month(c);
year(c), month(c), day(c); or year(c), month(c), day(c), hour(c) -- always in that order, with no
gap and no split across columns.

STDLIB-ONLY (re only): imported by scripts/schema_to_field_semantics.py, which
deploy-ducklake-lambdas.yml's reconcile-gate job runs with only pyyaml + pydantic installed, so a
third-party import here would block deploy-serving. Imports no other ducklake_* module (Decision
80 acyclic-import discipline).
"""

from __future__ import annotations

import re
from typing import Any

_TEMPORAL_ORDER = ("year", "month", "day", "hour")
_TEMPORAL_RE = re.compile(r"^(year|month|day|hour)\((\w+)\)$")
_BUCKET_RE = re.compile(r"^bucket\(\d+,\s*\w+\)$")
_IDENTITY_RE = re.compile(r"^\w+$")


class PartitionSpecError(ValueError):
    """Raised when a partition spec is not accepted (Decision 55 loud-fail)."""


def _split_top_level_entries(spec: str) -> list[str]:
    """Split *spec* on top-level commas only -- a comma inside bucket(N, col) is NOT a separator."""
    entries: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in spec:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            entries.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    entries.append("".join(current).strip())
    return entries


def validate_partition_spec(spec: str) -> None:
    """Raise PartitionSpecError unless *spec* is a comma-separated list of accepted transforms.

    Accepted per entry: an identity column name, bucket(N, col), or a temporal transform
    (year/month/day/hour) that, per column, forms an exact calendar PREFIX -- year; year,month;
    year,month,day; or year,month,day,hour -- in that order. Rejects an empty spec, an unknown
    transform, and any month/day/hour lacking its coarser components (including a prefix split
    across two different columns).
    """
    if not isinstance(spec, str) or not spec.strip():
        raise PartitionSpecError(f"empty or non-string partition spec: {spec!r}")

    entries = _split_top_level_entries(spec)
    if not all(entries):
        raise PartitionSpecError(f"empty partition-spec entry in: {spec!r}")

    temporal_by_column: dict[str, list[str]] = {}
    for entry in entries:
        m = _TEMPORAL_RE.match(entry)
        if m:
            unit, col = m.group(1), m.group(2)
            temporal_by_column.setdefault(col, []).append(unit)
            continue
        if _BUCKET_RE.match(entry) or _IDENTITY_RE.match(entry):
            continue
        raise PartitionSpecError(f"unknown partition transform {entry!r} (spec: {spec!r})")

    for col, units in temporal_by_column.items():
        expected_prefix = list(_TEMPORAL_ORDER[: len(units)])
        if units != expected_prefix:
            raise PartitionSpecError(
                f"column {col!r}: temporal transforms {units} are not an exact calendar prefix of "
                f"{_TEMPORAL_ORDER} in order (spec: {spec!r}) -- DuckLake day()/month()/hour() are "
                "day-of-month/month-of-year/hour-of-day, not Iceberg's days-since-epoch semantics; a "
                "bare day() or month() alone collapses rows across month/year boundaries "
                "(Decision 137)"
            )


def parse_partition_by(value: str) -> dict[str, str]:
    """Parse a contract governance.partition_by string into a {role: spec} mapping.

    Roles are separated by ';' -- the calendar prefix's own commas are not role separators, e.g.
    'history=year(c), month(c), day(c); current=bucket(8, id)'. Raises PartitionSpecError on a
    malformed segment.
    """
    if not isinstance(value, str) or not value.strip():
        raise PartitionSpecError(f"empty or non-string partition_by: {value!r}")

    result: dict[str, str] = {}
    for segment in value.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        if "=" not in segment:
            raise PartitionSpecError(f"malformed partition_by segment (expected role=spec): {segment!r}")
        role, spec = (part.strip() for part in segment.split("=", 1))
        if not role or not spec:
            raise PartitionSpecError(f"malformed partition_by segment (empty role or spec): {segment!r}")
        result[role] = spec
    return result


def resolve_partition_block(block: dict[str, Any], write_mode: str) -> tuple[str, str | None]:
    """Resolve a {role: spec} partition block for *write_mode* ('scd2' | 'append_only').

    Validates every present spec via validate_partition_spec. Raises PartitionSpecError if
    'history' is missing, or if 'current' is missing while write_mode == 'scd2'. An append_only
    table needs no 'current' entry -- ScdTableSpec.current_table is None for it, so there is no
    write-through projection to partition.
    """
    history = block.get("history")
    if not history:
        raise PartitionSpecError(f"partition block is missing required 'history' spec: {block!r}")
    validate_partition_spec(history)

    current = block.get("current")
    if write_mode == "scd2":
        if not current:
            raise PartitionSpecError(f"partition block is missing required 'current' spec for write_mode=scd2: {block!r}")
        validate_partition_spec(current)
        return history, current

    if current:
        validate_partition_spec(current)
    return history, current or None


def validate_projection_partitions(doc: dict[str, Any]) -> None:
    """Validate every partition spec a field_semantics-shaped *doc* emits (Decision 55 defense in depth).

    Covers partition_transforms.{history,current}, every tables.<name>.partition (smoke tables),
    and every ops_tables[*].partition.<role> (history/current, or the control-class 'table' role).
    Raises PartitionSpecError naming the failing site.
    """
    for role, spec in doc.get("partition_transforms", {}).items():
        try:
            validate_partition_spec(spec)
        except PartitionSpecError as exc:
            raise PartitionSpecError(f"partition_transforms.{role}: {exc}") from exc

    for table_name, table_spec in doc.get("tables", {}).items():
        spec = table_spec.get("partition")
        if spec is None:
            continue
        try:
            validate_partition_spec(spec)
        except PartitionSpecError as exc:
            raise PartitionSpecError(f"tables.{table_name}.partition: {exc}") from exc

    for table_name, entry in doc.get("ops_tables", {}).items():
        partition = entry.get("partition") or {}
        for role, spec in partition.items():
            try:
                validate_partition_spec(spec)
            except PartitionSpecError as exc:
                raise PartitionSpecError(f"ops_tables.{table_name}.partition.{role}: {exc}") from exc
