"""Create-only provisioning of the telemetry catalog tables (T2.36, slice 2a-2, plan 3 part 1).

provision_telemetry_catalog is the body of ONE run_telemetry_txn transaction (DuckLake commits CREATE, SET PARTITIONED BY
and row DML together). It creates and partitions only the tables that are absent, so an existing table is never
re-ALTERed (no per-deploy snapshot or conflict with in-flight writers, Decision 88; re-laying a live partition spec stays
an admin verb, Decision 204). Every pre-existing target table is checked read-only (partitions and columns) before anything
is written; a half-present SCD2 pair, a partition drift or a column drift fails loud and writes nothing. The counter seed
never lowers a value. There is no drop, truncate or force-recreate path on this function (Decision 55).

It never sets inlining: the connection already carries ducklake_default_data_inlining_row_limit = 0 (Decision 107).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.common import ducklake_maintenance_scope as scope
from src.common.ducklake_control_tables import ENTITY_COUNTERS_TABLE, resolve_control_spec
from src.common.ducklake_partition_layout import PartitionDrift, TableLayout, compare_to_declared
from src.common.ducklake_scd2_schema import (
    CATALOG_ALIAS,
    DuckLakeRuntimeError,
    ScdTableSpec,
    is_event_table,
    resolve_table_spec,
)
from src.common.ducklake_tables import create_control_table, create_scd2_tables
from src.telemetry.append import EventTableSpec

DIMENSIONS = ("ops_tenants", "ops_projects")
SEEDED_COUNTERS = DIMENSIONS
_ALWAYS_NOT_NULL = frozenset({"tenant_id", "project_id"})
_META_SCHEMA = f"__ducklake_metadata_{CATALOG_ALIAS}"


@dataclass(frozen=True)
class ProvisionResult:
    tables: tuple[str, ...]
    counters: dict[str, int]
    created: tuple[str, ...] = ()


def event_table_names(semantics: dict[str, Any]) -> tuple[str, ...]:
    return tuple(t for t in semantics.get("ops_tables", {}) if is_event_table(t, semantics))


def _event_ddl(spec: EventTableSpec) -> str:
    not_null = spec.not_null | _ALWAYS_NOT_NULL
    return ", ".join(
        f"{name} {sql_type}" + (" NOT NULL" if name in not_null else "") for name, sql_type in spec.columns.items()
    )


def _declared_columns(semantics: dict[str, Any]) -> dict[str, set[str]]:
    """physical table -> declared column names, for every table this function provisions."""
    declared: dict[str, set[str]] = {}
    for name in event_table_names(semantics):
        declared[name] = set(EventTableSpec.from_projection(name, semantics["ops_tables"][name]).columns)
    for name in DIMENSIONS:
        spec: ScdTableSpec = resolve_table_spec(name, semantics)
        cols = {c for c, _ in spec.ordered_columns}
        declared[spec.history_table] = cols
        declared[str(spec.current_table)] = cols
    declared[ENTITY_COUNTERS_TABLE] = {c for c, _ in resolve_control_spec(ENTITY_COUNTERS_TABLE).ordered_columns}
    return declared


def target_tables(semantics: dict[str, Any]) -> tuple[str, ...]:
    """The nine physical tables this function provisions, sorted."""
    return tuple(sorted(_declared_columns(semantics)))


def existing_tables(con: Any) -> set[str]:
    rows = con.execute(f"SELECT table_name FROM duckdb_tables() WHERE database_name = '{CATALOG_ALIAS}'").fetchall()
    return {str(r[0]) for r in rows}


def _live_layout(con: Any, physical: str, table_class: str) -> TableLayout:
    table_id_row = con.execute(
        f"SELECT table_id FROM {_META_SCHEMA}.ducklake_table WHERE table_name = ? AND end_snapshot IS NULL", [physical]
    ).fetchone()
    table_id = int(table_id_row[0])
    active = con.execute(
        f"SELECT partition_id FROM {_META_SCHEMA}.ducklake_partition_info WHERE table_id = ? AND end_snapshot IS NULL",
        [table_id],
    ).fetchone()
    partition_id = int(active[0]) if active else None
    transforms: tuple[tuple[str, str], ...] = ()
    if partition_id is not None:
        rows = con.execute(
            f"SELECT pc.transform, col.column_name FROM {_META_SCHEMA}.ducklake_partition_column pc "
            f"JOIN {_META_SCHEMA}.ducklake_column col ON col.column_id = pc.column_id AND col.table_id = pc.table_id "
            "WHERE pc.partition_id = ? AND pc.table_id = ? ORDER BY pc.partition_key_index",
            [partition_id, table_id],
        ).fetchall()
        transforms = tuple((str(r[0]), str(r[1])) for r in rows)
    return TableLayout(physical, table_class, transforms, partition_id, 0, 0)


def _live_columns(con: Any, physical: str) -> set[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog = ? AND table_name = ?",
        [CATALOG_ALIAS, physical],
    ).fetchall()
    return {str(r[0]) for r in rows}


def _partition_drifts(con: Any, present: list[str], semantics: dict[str, Any]) -> list[PartitionDrift]:
    registry = scope.build_registry(semantics)
    layouts = {t: _live_layout(con, t, registry[t].table_class) for t in present}
    return compare_to_declared(layouts, semantics=semantics) if layouts else []


def inspect_partitions(con: Any, existing: set[str], semantics: dict[str, Any]) -> dict[str, bool]:
    """Read-only: PRESENT target table -> live partitions equal the declared spec.

    Restricted to the nine target tables, so an unrelated catalog table never fails provisioning or the probe.
    """
    present = sorted(t for t in _declared_columns(semantics) if t in existing)
    drifted = {d.physical for d in _partition_drifts(con, present, semantics)}
    return {t: t not in drifted for t in present}


def check_existing_tables(con: Any, existing: set[str], semantics: dict[str, Any]) -> tuple[str, ...]:
    """Read-only: every pre-existing target table's live partitions and columns equal its declared spec.

    Raises a loud DuckLakeRuntimeError naming the table and the drift, never a value, before anything is written.
    """
    declared = _declared_columns(semantics)
    present = sorted(t for t in declared if t in existing)
    problems = [
        f"{d.physical}: partitions declared {list(d.declared)} live {list(d.live)}"
        for d in _partition_drifts(con, present, semantics)
    ]
    for physical in present:
        live = _live_columns(con, physical)
        if live != declared[physical]:
            problems.append(
                f"{physical}: columns missing {sorted(declared[physical] - live)} extra {sorted(live - declared[physical])}"
            )
    if problems:
        raise DuckLakeRuntimeError(
            "provision_telemetry refuses pre-existing tables that drift from their declared spec "
            f"(admin repair under Decision 204; nothing was written): {'; '.join(problems)}"
        )
    return tuple(present)


def _seed_counter(con: Any, name: str, floor: int) -> None:
    rows = [
        int(r[0])
        for r in con.execute(
            f"SELECT current_value FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?", [name]
        ).fetchall()
    ]
    if len(rows) == 1 and rows[0] >= floor:
        return
    value = max([floor, *rows])
    con.execute(f"DELETE FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?", [name])
    con.execute(f"INSERT INTO {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} VALUES (?, ?)", [name, value])


def provision_telemetry_catalog(con: Any, *, semantics: dict[str, Any]) -> ProvisionResult:
    """Provision the seven telemetry tables plus the counter table in the connection's pinned catalog (create-only)."""
    existing = existing_tables(con)
    for name in DIMENSIONS:
        spec = resolve_table_spec(name, semantics)
        halves = {spec.history_table in existing, str(spec.current_table) in existing}
        if len(halves) == 2:
            raise DuckLakeRuntimeError(
                f"{name}: exactly one of {spec.history_table}/{spec.current_table} exists -- a half-present SCD2 pair "
                "is an admin repair (Decision 55); provisioning would re-ALTER the existing half"
            )
    check_existing_tables(con, existing, semantics)

    created: list[str] = []
    for name in event_table_names(semantics):
        if name in existing:
            continue
        entry = semantics["ops_tables"][name]
        event = EventTableSpec.from_projection(name, entry)
        con.execute(f"CREATE TABLE {CATALOG_ALIAS}.{event.table} ({_event_ddl(event)})")
        con.execute(f"ALTER TABLE {CATALOG_ALIAS}.{event.table} SET PARTITIONED BY ({entry['partition']['history']})")
        created.append(name)
    for name in DIMENSIONS:
        spec = resolve_table_spec(name, semantics)
        if spec.history_table not in existing:
            create_scd2_tables(con, table=name)
            created.extend([spec.history_table, str(spec.current_table)])
    if ENTITY_COUNTERS_TABLE not in existing:
        create_control_table(con, table=ENTITY_COUNTERS_TABLE)
        created.append(ENTITY_COUNTERS_TABLE)

    for name in SEEDED_COUNTERS:
        current = str(resolve_table_spec(name, semantics).current_table)
        floor = int(con.execute(f"SELECT count(*) FROM {CATALOG_ALIAS}.{current}").fetchone()[0])
        _seed_counter(con, name, floor)
    counters = {
        name: int(
            con.execute(
                f"SELECT current_value FROM {CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE} WHERE counter_name = ?", [name]
            ).fetchone()[0]
        )
        for name in SEEDED_COUNTERS
    }
    return ProvisionResult(target_tables(semantics), counters, tuple(created))
