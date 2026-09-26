"""MIRROR for src/common/ducklake_partition_layout.py (Decision 204,
PLAN-ducklake-partition-layout-remediation).

FakeCon-driven read / classify / compare branches: IS DISTINCT FROM legacy counting incl. NULL
partition_id, table_class carried per table, PartitionDrift field shapes (declared_spec text;
declared/live pairs), unclassified tables collected then ONE PartitionLayoutError, a registry
scope error re-raised as PartitionLayoutError, and a wrapped duckdb.Error whose str() still
carries the original message with __cause__ set.
"""

from __future__ import annotations

import pytest

from src.common import ducklake_maintenance_scope as scope
from src.common.ducklake_partition_layout import (
    PartitionDrift,
    PartitionLayoutError,
    TableLayout,
    compare_to_declared,
    read_partition_layout,
)

pytestmark = pytest.mark.unit


_COLUMNS = {
    "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
    "rec_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
    "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
    "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
}


def _semantics() -> dict:
    return {
        "ops_tables": {
            "ops_recommendations": {
                "status": "live",
                "write_mode": "scd2",
                "history_table": "ops_recommendations_history",
                "current_table": "ops_recommendations_current",
                "merge_key": "rec_id",
                "columns": _COLUMNS,
                "partition": {
                    "history": "year(created_timestamp), month(created_timestamp), day(created_timestamp)",
                    "current": "bucket(8, rec_id)",
                },
            },
            "ops_smoke_events": {
                "status": "smoke",
                "write_mode": "append_only",
                "history_table": "ops_smoke_events_history",
                "merge_key": "rec_id",
                "columns": _COLUMNS,
                "partition": {"history": "year(created_timestamp), month(created_timestamp), day(created_timestamp)"},
            },
            "ops_entity_counters": {
                "status": "live",
                "write_mode": "control",
            },
        }
    }


class FakeMetaCon:
    """Fake DuckDB connection double matching ducklake_partition_layout's catalog-metadata SQL
    shape. `catalog` maps physical table name -> {table_id, active_scheme_id, live_transforms,
    live_files, legacy_files}."""

    def __init__(self, catalog: dict, *, raise_on: str | None = None):
        self._catalog = catalog
        self._raise_on = raise_on
        self._last_sql = ""
        self._last_params: list | None = None

    def _entry_by_table_id(self, table_id: int) -> dict:
        return next(v for v in self._catalog.values() if v["table_id"] == table_id)

    def execute(self, sql: str, params: list | None = None):
        self._last_sql = sql
        self._last_params = params or []
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("dead connection: server closed the connection unexpectedly")
        return self

    def fetchall(self):
        sql, params = self._last_sql, self._last_params or []
        if "table_name FROM" in sql and "ducklake_table" in sql:
            return [(name,) for name in self._catalog]
        if "ducklake_partition_column" in sql:
            table_id = params[1]
            entry = self._entry_by_table_id(table_id)
            return list(entry["live_transforms"])
        return []

    def fetchone(self):
        sql, params = self._last_sql, self._last_params or []
        if "table_id FROM" in sql and "ducklake_table" in sql:
            name = params[0]
            return (self._catalog[name]["table_id"],)
        if "partition_id FROM" in sql and "ducklake_partition_info" in sql:
            entry = self._entry_by_table_id(params[0])
            return (entry["active_scheme_id"],) if entry["active_scheme_id"] is not None else None
        if "count(*)" in sql and "ducklake_data_file" in sql:
            entry = self._entry_by_table_id(params[0])
            if "partition_id IS DISTINCT FROM" in sql:
                return (entry["legacy_files"],)
            return (entry["live_files"],)
        return None


_CATALOG = {
    "ops_recommendations_history": {
        "table_id": 1,
        "active_scheme_id": 10,
        "live_transforms": [("year", "created_timestamp"), ("month", "created_timestamp"), ("day", "created_timestamp")],
        "live_files": 93,
        "legacy_files": 40,
    },
    "ops_recommendations_current": {
        "table_id": 2,
        "active_scheme_id": 20,
        "live_transforms": [("bucket(8)", "rec_id")],
        "live_files": 8,
        "legacy_files": 0,
    },
    "ops_smoke_events_history": {
        "table_id": 3,
        "active_scheme_id": 30,
        "live_transforms": [("day", "created_timestamp")],  # drifted: day-of-month, not calendar day
        "live_files": 3,
        "legacy_files": 3,
    },
    "ops_entity_counters": {
        "table_id": 4,
        "active_scheme_id": None,  # never partitioned yet -- pre-partition = legacy
        "live_transforms": (),
        "live_files": 1,
        "legacy_files": 1,
    },
}


def test_read_partition_layout_classifies_and_counts_every_table():
    con = FakeMetaCon(dict(_CATALOG))
    layouts = read_partition_layout(con, catalog_alias="cat", semantics=_semantics())

    assert set(layouts) == set(_CATALOG)
    history = layouts["ops_recommendations_history"]
    assert isinstance(history, TableLayout)
    assert history.table_class == "scd2"
    assert history.live_transforms == (
        ("year", "created_timestamp"),
        ("month", "created_timestamp"),
        ("day", "created_timestamp"),
    )
    assert history.active_scheme_id == 10
    assert history.live_files == 93
    assert history.legacy_scheme_files == 40

    control = layouts["ops_entity_counters"]
    assert control.table_class == "control"
    assert control.active_scheme_id is None
    assert control.legacy_scheme_files == 1  # NULL active scheme -- pre-partition, every live file is legacy


def test_read_partition_layout_unclassified_tables_collected_into_one_error():
    catalog = dict(_CATALOG)
    catalog["a_stray_table"] = {
        "table_id": 99,
        "active_scheme_id": None,
        "live_transforms": (),
        "live_files": 0,
        "legacy_files": 0,
    }
    catalog["another_stray"] = {
        "table_id": 98,
        "active_scheme_id": None,
        "live_transforms": (),
        "live_files": 0,
        "legacy_files": 0,
    }
    con = FakeMetaCon(catalog)

    with pytest.raises(PartitionLayoutError) as exc_info:
        read_partition_layout(con, catalog_alias="cat", semantics=_semantics())
    assert "a_stray_table" in str(exc_info.value)
    assert "another_stray" in str(exc_info.value)


def test_read_partition_layout_wraps_raw_error_preserving_message_and_cause():
    con = FakeMetaCon(dict(_CATALOG), raise_on="ducklake_table")
    original_text = "dead connection: server closed the connection unexpectedly"

    with pytest.raises(PartitionLayoutError) as exc_info:
        read_partition_layout(con, catalog_alias="cat", semantics=_semantics())
    assert original_text in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert original_text in str(exc_info.value.__cause__)


def test_read_partition_layout_wraps_maintenance_scope_error(monkeypatch):
    def _boom(_semantics):
        raise scope.DuckLakeMaintenanceScopeError("registry is broken")

    monkeypatch.setattr(scope, "build_registry", _boom)
    con = FakeMetaCon(dict(_CATALOG))

    with pytest.raises(PartitionLayoutError) as exc_info:
        read_partition_layout(con, catalog_alias="cat", semantics=_semantics())
    assert "registry is broken" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, scope.DuckLakeMaintenanceScopeError)


def test_compare_to_declared_reports_drift_and_agreement():
    con = FakeMetaCon(dict(_CATALOG))
    layouts = read_partition_layout(con, catalog_alias="cat", semantics=_semantics())

    drifts = compare_to_declared(layouts, semantics=_semantics())
    drifted_physical = {d.physical for d in drifts}

    # ops_smoke_events_history: live is bare day(), declared is the calendar-day triple -- drifted.
    assert "ops_smoke_events_history" in drifted_physical
    # ops_entity_counters: NULL live transforms vs its declared identity spec -- drifted.
    assert "ops_entity_counters" in drifted_physical
    # ops_recommendations_history/current: live already matches declared -- no drift reported.
    assert "ops_recommendations_history" not in drifted_physical
    assert "ops_recommendations_current" not in drifted_physical

    smoke_drift = next(d for d in drifts if d.physical == "ops_smoke_events_history")
    assert isinstance(smoke_drift, PartitionDrift)
    assert smoke_drift.table_class == "append_only"
    assert smoke_drift.declared_spec == "year(created_timestamp), month(created_timestamp), day(created_timestamp)"
    assert smoke_drift.declared == (
        ("year", "created_timestamp"),
        ("month", "created_timestamp"),
        ("day", "created_timestamp"),
    )
    assert smoke_drift.live == (("day", "created_timestamp"),)
    assert smoke_drift.legacy_scheme_files == 3

    counters_drift = next(d for d in drifts if d.physical == "ops_entity_counters")
    assert counters_drift.declared_spec == "counter_name"
    assert counters_drift.declared == (("identity", "counter_name"),)
    assert counters_drift.live == ()


def test_compare_to_declared_rejects_a_layout_for_an_unclassified_physical_table():
    """Defensive check (public API misuse guard): compare_to_declared refuses a hand-built layout
    dict naming a physical table absent from the registry -- it must never silently no-op-compare
    a table it cannot resolve a declared spec for."""
    bogus_layout = TableLayout(
        physical="a_stray_table",
        table_class="scd2",
        live_transforms=(),
        active_scheme_id=None,
        live_files=0,
        legacy_scheme_files=0,
    )
    with pytest.raises(PartitionLayoutError, match="a_stray_table"):
        compare_to_declared({"a_stray_table": bogus_layout}, semantics=_semantics())
