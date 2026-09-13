"""DuckLake control-class table primitives (T2.26 control-table-class-and-counter-conformance).

Owner concern: writer-internal control state -- physical bookkeeping tables that exist to support
the writer's own operation (today: the entity-id allocation counter, Decision 84 I-2) rather than
to serve application reads or writes. A control-class table:
  - is a SINGLE physical table, partitioned on its own key column -- no history/current SCD2 pair
    (ScdTableSpec is never widened to accommodate it; ControlTableSpec is its own type);
  - carries write_boundary=writer_internal and read_boundary=none
    (docs/contracts/ops_entity_counters.yaml): it is never reachable through the generic write
    verbs (write_ops/file_ops/update_ops -- refused via ducklake_scd2_schema.resolve_table_spec's
    directed raise) or any reader verb (refused at src/lambdas/ducklake_reader/handler.py's
    _require_ops_table call sites and src/common/ducklake_reads.py's named_read) -- provisioned
    only via create_ops_tables (src/common/ducklake_tables.create_control_table) and mutated only
    by the writer's own intra-transaction calls (ducklake_writes._allocate_entity_id /
    _advance_entity_counter);
  - is read in-transaction by its owning writer code, or via the admin ducklake_maintenance
    control_health verb -- the periodic substitute for DQ-runner coverage that the contract's
    dq_scope exemption names as the health binding.

Dependency is strictly one-directional: this module imports shared schema symbols FROM
ducklake_scd2_schema (+ stdlib) only, and NEVER from the ducklake_runtime facade (Decision 80
acyclic-import discipline) or from ducklake_writes -- there is no control_tables<->writes call in
either direction; each keeps its own copy of the tiny table-name/rollback primitives it needs
(ENTITY_COUNTERS_TABLE / _safe_rollback) rather than importing the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.common.ducklake_scd2_schema import CATALOG_ALIAS, DuckLakeRuntimeError

# ---------------------------------------------------------------------------
# Control spec -- the single resolved shape for a control-class table. Deliberately its OWN type,
# never ScdTableSpec: a control table has no history_table/current_table pair, so widening
# ScdTableSpec to accommodate it would make history_table optional on every SCD2 caller too
# (ducklake_scd2_schema.py stays SHIMS ONLY -- _order_columns and ScdTableSpec are never widened).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlTableSpec:
    """Resolved control-class table shape: one physical table, partitioned on its own key column."""

    table: str
    ordered_columns: tuple[tuple[str, str], ...]  # (name, sql_type) in physical (DDL) order
    fields: dict[str, Any]  # column name -> {role, sql_type, nullable}; mirrors ScdTableSpec.fields
    partition_key: str  # the column control_health/create_control_table partition on


# Registry of control-class tables -- WHOLLY contained here, never in field_semantics' SCD2
# ops_tables shape. docs/contracts/ops_entity_counters.yaml is the governance source of truth for
# ITS invariants; this literal registry is the runtime DDL/dispatch source of truth. Kept in sync
# by hand -- by design there are very few control-class tables (writer-internal bookkeeping is the
# narrow exception, not a growing table family).
_CONTROL_TABLES: dict[str, ControlTableSpec] = {
    "ops_entity_counters": ControlTableSpec(
        table="ops_entity_counters",
        ordered_columns=(("counter_name", "VARCHAR"), ("current_value", "BIGINT")),
        fields={
            "counter_name": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
            "current_value": {"role": "input", "sql_type": "BIGINT", "nullable": False},
        },
        partition_key="counter_name",
    ),
}


def control_table_names() -> tuple[str, ...]:
    """Return the configured control-class table names."""
    return tuple(_CONTROL_TABLES)


def is_control_table(table: Any) -> bool:
    """True iff *table* names a registered control-class table."""
    return isinstance(table, str) and table in _CONTROL_TABLES


def resolve_control_spec(table: str) -> ControlTableSpec:
    """Resolve the control spec for *table*. Loud-fail on an unknown control table name."""
    spec = _CONTROL_TABLES.get(table)
    if spec is None:
        raise DuckLakeRuntimeError(
            f"unknown control table {table!r}: not in the control-class registry (have {sorted(_CONTROL_TABLES)})"
        )
    return spec


def _column_ddl(spec: ControlTableSpec) -> str:
    """Compose the CREATE-TABLE column list from the spec (NOT NULL on non-nullable columns).

    Mirrors ducklake_scd2_schema._column_ddl's shape for the SCD2 family -- kept as a separate
    function (not a shared import) because ControlTableSpec.ordered_columns/fields is its own type,
    not ScdTableSpec.
    """
    parts: list[str] = []
    for name, sql_type in spec.ordered_columns:
        nullable = bool(spec.fields[name].get("nullable", True))
        parts.append(f"{name} {sql_type}" + ("" if nullable else " NOT NULL"))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Writer-owned entity-id allocation counter bookkeeping (relocated from ducklake_writes.py so the
# ungoverned ad-hoc creation helper leaves that module entirely). Decision 84 I-2 is PRESERVED:
# allocation stays writer-owned, inside the write transaction -- this relocation changes the
# counter table's SHAPE, GOVERNANCE and EXPOSURE, never its substrate.
# ---------------------------------------------------------------------------

ENTITY_COUNTERS_TABLE = "ops_entity_counters"


def ensure_entity_counters_table(con: Any) -> None:
    """Idempotently create the entity-counters bookkeeping table (legacy ad-hoc safety net).

    The real provisioning path is create_control_table (src/common/ducklake_tables.py, invoked via
    create_ops_tables), which also partitions the table; this CREATE TABLE IF NOT EXISTS is a
    no-op once that has run. The sole caller is bootstrap_entity_counter below -- no other src/ or
    scripts/ module may reach it (VP step 13 admission sweep: `rg -l
    'ensure_entity_counters_table\\(' src/ scripts/ --glob '!*control_tables*'` must be empty).
    """
    columns = _column_ddl(resolve_control_spec(ENTITY_COUNTERS_TABLE))
    con.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} ({columns})")


def _safe_rollback(con: Any) -> None:
    """Roll back the current transaction, swallowing a 'no active transaction' error only.

    A private copy of ducklake_writes._safe_rollback: this module never imports from
    ducklake_writes (Decision 80 acyclic-import discipline stays one-directional in both
    directions), and the helper is a few lines, not worth a shared-utils module for one caller.
    """
    try:
        con.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- rollback failure must not mask the original error
        pass


def bootstrap_entity_counter(con: Any, spec: Any) -> int:
    """Serially (re)seed the counter row for *spec* from the history-table numeric max.

    MUST run as a one-time serial bootstrap (create_ops_tables), never on the allocation hot
    path: a concurrent self-seed INSERT race under snapshot isolation creates duplicate counter
    rows that each transaction increments privately -- observed live 2026-06-11 as four
    concurrent file_ops all allocating the same id. DELETE + single INSERT here is idempotent
    and also repairs that duplicate-row state. Returns the seeded value.

    `spec` is an ScdTableSpec (the SCD2 table whose keyspace is being seeded, e.g.
    ops_recommendations) -- NOT a ControlTableSpec; only entity_id_prefix/id_keyspace/merge_key/
    history_table/table are read, so a duck-typed object with those attributes also works (tests).
    """
    if not spec.entity_id_prefix or spec.id_keyspace != "writer":
        raise DuckLakeRuntimeError(
            f"table {spec.table!r} has no writer-owned keyspace (id_keyspace={spec.id_keyspace!r}): "
            "it has no allocation counter to seed"
        )
    prefix = spec.entity_id_prefix
    ensure_entity_counters_table(con)
    con.execute("BEGIN TRANSACTION")
    try:
        seed_row = con.execute(
            f"SELECT coalesce(max(CAST(regexp_extract({spec.merge_key}, '^{prefix}([0-9]+)$', 1) AS BIGINT)), 0) "
            f"FROM {CATALOG_ALIAS}.{spec.history_table} "
            f"WHERE {spec.merge_key} LIKE '{prefix}%' AND regexp_matches({spec.merge_key}, '^{prefix}[0-9]+$')"
        ).fetchone()
        seed = int(seed_row[0]) if seed_row and seed_row[0] is not None else 0
        con.execute(f"DELETE FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?", [spec.table])
        con.execute(f"INSERT INTO {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} VALUES (?, ?)", [spec.table, seed])
        con.execute("COMMIT")
    except Exception:
        _safe_rollback(con)
        raise
    return seed
