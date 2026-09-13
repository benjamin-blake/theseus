"""Tests for src/common/ducklake_control_health.py (T2.26
control-table-class-and-counter-conformance): control_health's row-count, counter-floor and
live-file-ceiling invariants, each a FAILING condition (Decision 55) rather than a report.

Relocated here from tests/test_ducklake_maintenance.py so this module has its own dedicated
coverage home (Decision 131 mirror convention) independent of the maintenance-handler dispatch
integration tests, which stay in tests/test_ducklake_maintenance.py.
"""

from __future__ import annotations

from typing import Any

import pytest

import src.common.ducklake_control_health as ch
from src.common.ducklake_maintenance import DuckLakeMaintenanceError

pytestmark = pytest.mark.unit


class FakeCon:
    """Minimal connection double: records SQL; returns configurable results per substring."""

    def __init__(self, fetchall_map: dict[str, list[Any]] | None = None, fetchone_map: dict[str, Any] | None = None):
        self.executed: list[str] = []
        self._fetchall_map: dict[str, list[Any]] = fetchall_map or {}
        self._fetchone_map: dict[str, Any] = fetchone_map or {}
        self._last = ""

    def execute(self, sql: str, params: Any = None) -> "FakeCon":
        self.executed.append(sql)
        self._last = sql
        return self

    def fetchone(self) -> tuple[Any, ...]:
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self) -> list[Any]:
        for sub, val in self._fetchall_map.items():
            if sub in self._last:
                return val
        return []


def test_control_health_asserts_counter_invariants():
    """Each invariant (row count, counter floor, live-file ceiling) is a FAILING condition -- a
    violation RAISES DuckLakeMaintenanceError, never merely a reported field."""
    healthy = FakeCon(
        fetchall_map={"SELECT counter_name, current_value": [("ops_recommendations", 5000)]},
        fetchone_map={"coalesce(max(": (5000,), "ducklake_list_files": (10,)},
    )
    result = ch.control_health(healthy)
    assert result["ok"] is True
    assert result["violations"] == []

    wrong_row_count = FakeCon(
        fetchall_map={"SELECT counter_name, current_value": []},
        fetchone_map={"coalesce(max(": (0,), "ducklake_list_files": (0,)},
    )
    with pytest.raises(DuckLakeMaintenanceError, match="row count"):
        ch.control_health(wrong_row_count)

    stranded_counter = FakeCon(
        fetchall_map={"SELECT counter_name, current_value": [("ops_recommendations", 100)]},
        fetchone_map={"coalesce(max(": (5000,), "ducklake_list_files": (10,)},
    )
    with pytest.raises(DuckLakeMaintenanceError, match="below max allocated id"):
        ch.control_health(stranded_counter)

    too_many_files = FakeCon(
        fetchall_map={"SELECT counter_name, current_value": [("ops_recommendations", 5000)]},
        fetchone_map={"coalesce(max(": (5000,), "ducklake_list_files": (999,)},
    )
    with pytest.raises(DuckLakeMaintenanceError, match="live file count"):
        ch.control_health(too_many_files)


def test_control_health_metric_sink_receives_violation_count_before_raise():
    """metric_sink ALWAYS receives ControlTableInvariantViolation -- even on a violation that then
    raises -- so the metric/alarm signal survives the exception."""
    con = FakeCon(
        fetchall_map={"SELECT counter_name, current_value": []},
        fetchone_map={"coalesce(max(": (0,), "ducklake_list_files": (0,)},
    )
    emitted: list[tuple[str, float]] = []
    with pytest.raises(DuckLakeMaintenanceError):
        ch.control_health(con, metric_sink=lambda name, value: emitted.append((name, value)))
    assert emitted == [("ControlTableInvariantViolation", 1.0)]


def test_writer_keyspace_tables_excludes_control_class_tables():
    """_writer_keyspace_tables scans ops_table_names but skips control-class tables (T2.26) --
    resolve_table_spec would raise a directed error for one, so the scan must not reach it."""
    tables = ch._writer_keyspace_tables()
    assert "ops_entity_counters" not in tables
    assert "ops_recommendations" in tables
