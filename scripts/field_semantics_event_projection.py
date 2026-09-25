"""Generator projection for table_class: event Class A contracts (Decision 199, telemetry kernel).

Split out from scripts/schema_to_field_semantics.py (Decision 128 decompose-by-default: the
generator's mapped test file, tests/test_schema_to_field_semantics.py, is at 479/500 SLOC, and
per-file coverage runs only a source's own mapped test file). schema_to_field_semantics.py imports
this module INSIDE its event dispatch branch only (function scope), so validate_field_semantics_drift's
module-scope import of the generator gains no new edge and this module's own KEY_PLANS/identity
import (src.telemetry.identity) never appears at that module's top level.

Projects a table_class: event Class A contract to the history-only append_only shape: no
merge_key/current_table/entity_id_prefix/id_keyspace, history_table = the contract id, partition
from governance.partition_by (the calendar-day triple), dedupe_key [event_id, parser_version], and
entity_key = the table's own KEY_PLANS entity column. Fail-closed on a missing envelope column, a
non-triple partition_by, or a migration_columns entry (an SCD2-only concept never valid for an
append-only event table).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from src.telemetry.identity import KEY_PLANS

_ENVELOPE_REQUIRED_FIELDS = (
    "event_id",
    "event_timestamp",
    "session_started_at",
    "external_ref",
    "entity_ref",
    "parser_version",
    "created_timestamp",
    "tenant_id",
    "project_id",
)

_PARTITION_TRIPLE_RE = re.compile(r"^year\((?P<col>\w+)\), month\((?P=col)\), day\((?P=col)\)$")


def _entity_key_column(table_id: str) -> str:
    for column, plan in KEY_PLANS[table_id].items():
        if plan.ref_field == "entity_ref":
            return column
    raise ValueError(f"{table_id}: KEY_PLANS has no entity-key column (no plan with ref_field='entity_ref')")


def _validate_partition_by(table_id: str, partition_by: str | None, columns: dict[str, Any]) -> None:
    if not partition_by:
        raise ValueError(f"{table_id}: governance.partition_by is required for a table_class: event contract")
    match = _PARTITION_TRIPLE_RE.match(partition_by)
    if match is None:
        raise ValueError(
            f"{table_id}: governance.partition_by must be the calendar-day triple "
            "'year(C), month(C), day(C)' over one column -- a bare day(C) alone is DuckLake "
            f"DAY-OF-MONTH, not a calendar-day partition. Got: {partition_by!r}"
        )
    col = match.group("col")
    if columns.get(col, {}).get("sql_type") != "TIMESTAMP WITH TIME ZONE":
        raise ValueError(f"{table_id}: partition column {col!r} must project to TIMESTAMP WITH TIME ZONE")


def _event_role(name: str, derived_columns: frozenset[str]) -> str:
    return "derived" if name in derived_columns else "input"


def _is_not_null(dq_intent: dict[str, Any] | None, nullable: bool | None) -> tuple[bool, Any]:
    dq_intent = dq_intent or {}
    required_when = dq_intent.get("required_when")
    enforced = bool((dq_intent.get("not_null") or {}).get("enforced"))
    is_not_null = (nullable is False or enforced) and not required_when
    return is_not_null, required_when


def project_event_table(
    table_id: str,
    resolved_fields: dict[str, Any],
    ops_config: dict[str, Any],
    partition_by: str | None,
    *,
    map_iceberg_type: Callable[[str | None, str], str],
    include_prose: bool = False,
) -> dict[str, Any]:
    """Project a table_class: event contract's resolved fields into a history-only ops entry."""
    if ops_config.get("migration_columns"):
        raise ValueError(f"{table_id}: migration_columns is an SCD2-only concept, invalid for a table_class: event contract")

    for required in _ENVELOPE_REQUIRED_FIELDS:
        if required not in resolved_fields:
            raise ValueError(f"{table_id}: missing required envelope column {required!r}")

    entity_key = _entity_key_column(table_id)
    derived_columns = frozenset({"event_id", "created_timestamp", "tenant_id", "project_id"}) | frozenset(KEY_PLANS[table_id])

    columns: dict[str, Any] = {}
    for fname, fspec in resolved_fields.items():
        derivation = fspec.derivation if hasattr(fspec, "derivation") else fspec.get("derivation")
        if derivation and derivation.get("timing") == "read":
            if derivation.get("realized") is True:
                raise ValueError(f"{table_id}.{fname}: a derivation.timing=read field must never have realized=true")
            continue  # derived-at-read fields have no physical column

        iceberg_type = fspec.iceberg_type if hasattr(fspec, "iceberg_type") else fspec.get("iceberg_type")
        sql_type = map_iceberg_type(iceberg_type, fname)
        nullable = fspec.nullable if hasattr(fspec, "nullable") else fspec.get("nullable")
        dq_intent = fspec.dq_intent if hasattr(fspec, "dq_intent") else fspec.get("dq_intent")

        is_not_null, required_when = _is_not_null(dq_intent, nullable)
        col: dict[str, Any] = {
            "role": _event_role(fname, derived_columns),
            "sql_type": sql_type,
            "nullable": not is_not_null,
        }
        if required_when:
            col["required_when"] = required_when
        if include_prose:
            desc = fspec.description if hasattr(fspec, "description") else fspec.get("description")
            sem = fspec.semantics if hasattr(fspec, "semantics") else fspec.get("semantics")
            if desc is not None:
                col["description"] = desc
            if sem is not None:
                col["semantics"] = sem
        columns[fname] = col

    _validate_partition_by(table_id, partition_by, columns)

    return {
        "status": ops_config.get("status", "target"),
        "write_mode": "append_only",
        "history_table": table_id,
        "partition": {"history": partition_by},
        "partition_column": "session_started_at",
        "dedupe_key": ["event_id", "parser_version"],
        "entity_key": entity_key,
        "columns": columns,
    }


__all__ = ["project_event_table"]
