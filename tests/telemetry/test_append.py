"""Mirror test for src/telemetry/append.py on in-memory DuckDB (core MERGE, no extension, no network).

pytest.importorskip at MODULE level: the fast tier installs no duckdb (requirements-fast.txt).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb")

from src.telemetry.append import AppendResult, EventTableSpec, append_events  # noqa: E402
from src.telemetry.gate import AppendError  # noqa: E402

TENANT = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
PROJECT = "01BRZ3NDEKTSV4RRFFQ69G5FBW"

_COLUMNS = {
    "event_id": "VARCHAR",
    "event_kind": "VARCHAR",
    "event_timestamp": "TIMESTAMP WITH TIME ZONE",
    "session_started_at": "TIMESTAMP WITH TIME ZONE",
    "external_ref": "VARCHAR",
    "entity_ref": "VARCHAR",
    "parser_version": "BIGINT",
    "created_timestamp": "TIMESTAMP WITH TIME ZONE",
    "tenant_id": "VARCHAR",
    "project_id": "VARCHAR",
    "session_id": "VARCHAR",
    "parent_session_id": "VARCHAR",
    "workflow": "VARCHAR",
}
_NOT_NULL = frozenset({"event_id", "parser_version", "session_started_at", "created_timestamp", "session_id"})


def _spec() -> EventTableSpec:
    return EventTableSpec(table="telemetry_sessions", columns=dict(_COLUMNS), not_null=_NOT_NULL)


@pytest.fixture
def con() -> Any:
    connection = duckdb.connect()
    connection.execute("SET TimeZone='UTC'")
    col_ddl = ", ".join(f"{c} {t}" for c, t in _COLUMNS.items())
    connection.execute(f"CREATE TABLE telemetry_sessions ({col_ddl})")
    return connection


def _row(**overrides: Any) -> dict[str, Any]:
    t = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)
    base = {
        "event_kind": "open",
        "event_timestamp": t,
        "session_started_at": t,
        "external_ref": "src#0/open",
        "entity_ref": "sess-ref-1",
        "parser_version": 1,
        "workflow": "implement",
    }
    base.update(overrides)
    return base


def test_append_events_replay_is_noop(con: Any) -> None:
    """Module-level (rec-4024's acceptance cites this exact node_id; the graduated VP step 4 keystone)."""
    row = _row()
    first = append_events(con, _spec(), [row], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
    assert first.inserted == 1
    second = append_events(con, _spec(), [row], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
    assert second.inserted == 0
    assert con.execute("SELECT count(*) FROM telemetry_sessions").fetchone()[0] == 1


class TestAppendEventsCore:
    def test_single_row_inserts_and_derives_ids(self, con: Any) -> None:
        result = append_events(con, _spec(), [_row()], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert result == AppendResult(submitted=1, collapsed=0, inserted=1)
        stored = con.execute("SELECT event_id, session_id, workflow FROM telemetry_sessions").fetchall()
        assert len(stored) == 1
        assert stored[0][2] == "implement"
        assert len(stored[0][0]) == 26
        assert len(stored[0][1]) == 26

    def test_empty_batch_returns_zero_without_transaction(self, con: Any) -> None:
        result = append_events(con, _spec(), [], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert result == AppendResult(submitted=0, collapsed=0, inserted=0)
        assert con.execute("SELECT count(*) FROM telemetry_sessions").fetchone()[0] == 0

    def test_higher_parser_version_inserts_a_new_row(self, con: Any) -> None:
        row = _row()
        append_events(con, _spec(), [row], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        row2 = _row(parser_version=2)
        result = append_events(con, _spec(), [row2], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert result.inserted == 1
        assert con.execute("SELECT count(*) FROM telemetry_sessions").fetchone()[0] == 2

    def test_created_timestamp_identical_across_batch(self, con: Any) -> None:
        rows = [_row(external_ref="src#0/open"), _row(external_ref="src#1/open", entity_ref="sess-ref-2")]
        append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        timestamps = {r[0] for r in con.execute("SELECT created_timestamp FROM telemetry_sessions").fetchall()}
        assert len(timestamps) == 1

    def test_injected_now_is_used_and_truncated(self, con: Any) -> None:
        now = datetime(2026, 9, 25, 12, 0, 0, 123456, tzinfo=timezone.utc)
        append_events(con, _spec(), [_row()], tenant_id=TENANT, project_id=PROJECT, catalog="memory", now=now)
        stored = con.execute("SELECT created_timestamp FROM telemetry_sessions").fetchone()[0]
        assert stored == now.replace(microsecond=123000)


class TestAppendEventsRejections:
    def test_non_utc_connection_rejected_before_transaction(self) -> None:
        conn = duckdb.connect()
        conn.execute("SET TimeZone='America/New_York'")
        col_ddl = ", ".join(f"{c} {t}" for c, t in _COLUMNS.items())
        conn.execute(f"CREATE TABLE telemetry_sessions ({col_ddl})")
        with pytest.raises(AppendError):
            append_events(conn, _spec(), [_row()], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert conn.execute("SELECT count(*) FROM telemetry_sessions").fetchone()[0] == 0

    def test_caller_supplied_derived_column_rejected(self, con: Any) -> None:
        with pytest.raises(AppendError):
            append_events(con, _spec(), [_row(session_id="nope")], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_caller_supplied_event_id_rejected(self, con: Any) -> None:
        with pytest.raises(AppendError):
            append_events(con, _spec(), [_row(event_id="nope")], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_unknown_column_rejected(self, con: Any) -> None:
        with pytest.raises(AppendError):
            append_events(con, _spec(), [_row(bogus="x")], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_missing_required_ref_field_rejected(self, con: Any) -> None:
        row = _row()
        del row["entity_ref"]
        with pytest.raises(AppendError):
            append_events(con, _spec(), [row], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_missing_session_started_at_rejected(self, con: Any) -> None:
        row = _row()
        del row["session_started_at"]
        with pytest.raises(AppendError):
            append_events(con, _spec(), [row], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_missing_event_timestamp_rejected(self, con: Any) -> None:
        row = _row()
        del row["event_timestamp"]
        with pytest.raises(AppendError):
            append_events(con, _spec(), [row], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_strict_type_rejection_bool_as_bigint(self, con: Any) -> None:
        with pytest.raises(AppendError):
            append_events(con, _spec(), [_row(parser_version=True)], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_conflicting_intra_batch_duplicates_rejected(self, con: Any) -> None:
        rows = [_row(workflow="implement"), _row(workflow="plan")]
        with pytest.raises(AppendError):
            append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert con.execute("SELECT count(*) FROM telemetry_sessions").fetchone()[0] == 0

    def test_identical_intra_batch_duplicates_collapse(self, con: Any) -> None:
        rows = [_row(), _row()]
        result = append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert result.submitted == 2
        assert result.collapsed == 1
        assert result.inserted == 1

    def test_sql_failure_rolls_back_and_connection_stays_usable(self, con: Any) -> None:
        # A column the spec declares but the real table does not have: passes the pure Python
        # gate (which never consults the DB schema) but fails DuckDB's own binder inside the
        # MERGE -- the genuine "SQL failure mid-batch" path (not a gate rejection).
        bad_columns = {**_COLUMNS, "column_absent_from_table": "VARCHAR"}
        bad_spec = EventTableSpec(table="telemetry_sessions", columns=bad_columns, not_null=_NOT_NULL)
        with pytest.raises(Exception):
            append_events(con, bad_spec, [_row()], tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert con.execute("SELECT count(*) FROM telemetry_sessions").fetchone()[0] == 0
        # connection still usable after rollback
        con.execute("SELECT 1").fetchone()


class _RecordingConnection:
    """Wraps a real DuckDB connection, recording every MERGE statement's SQL text."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.merge_statements: list[str] = []

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if sql.strip().upper().startswith("MERGE"):
            self.merge_statements.append(sql)
        return self._real.execute(sql, *args, **kwargs)


class TestMergeShapeAndBounds:
    def test_merge_is_single_statement_insert_only_with_day_bounds(self, con: Any) -> None:
        recorder = _RecordingConnection(con)
        append_events(recorder, _spec(), [_row()], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

        captured = recorder.merge_statements
        assert len(captured) == 1
        sql = captured[0]
        assert sql.count("MERGE INTO") == 1
        assert "WHEN NOT MATCHED THEN INSERT" in sql
        assert "WHEN MATCHED" not in sql
        assert "ON t.event_id = s.event_id AND t.parser_version = s.parser_version" in sql
        assert "t.session_started_at >= ?" in sql
        assert "t.session_started_at < ?" in sql

    def test_day_bounds_span_the_batch_calendar_day(self, con: Any) -> None:
        t1 = datetime(2026, 9, 25, 1, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 25, 23, 0, 0, tzinfo=timezone.utc)
        rows = [
            _row(external_ref="src#0/open", session_started_at=t1, event_timestamp=t1),
            _row(external_ref="src#1/open", entity_ref="sess-ref-2", session_started_at=t2, event_timestamp=t2),
        ]
        result = append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        assert result.inserted == 2

    def test_values_use_multi_row_source_never_string_interpolation(self, con: Any) -> None:
        recorder = _RecordingConnection(con)
        rows = [_row(external_ref="src#0/open"), _row(external_ref="src#1/open", entity_ref="sess-ref-2")]
        append_events(recorder, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="memory")
        sql = recorder.merge_statements[0]
        assert "sess-ref-1" not in sql
        assert "sess-ref-2" not in sql
        assert sql.count("CAST(?") >= len(_COLUMNS) * 2


class TestEventTableSpecFromProjection:
    def _base_entry(self) -> dict[str, Any]:
        return {
            "status": "target",
            "write_mode": "append_only",
            "history_table": "telemetry_sessions",
            "partition": {"history": "year(session_started_at), month(session_started_at), day(session_started_at)"},
            "partition_column": "session_started_at",
            "dedupe_key": ["event_id", "parser_version"],
            "entity_key": "session_id",
            "columns": {
                "event_id": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
                "parser_version": {"role": "input", "sql_type": "BIGINT", "nullable": False},
                "session_started_at": {"role": "input", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
                "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
                "tenant_id": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
                "project_id": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
                "session_id": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
                "parent_session_id": {"role": "derived", "sql_type": "VARCHAR", "nullable": True},
            },
        }

    def test_accepts_a_valid_event_projection(self) -> None:
        spec = EventTableSpec.from_projection("telemetry_sessions", self._base_entry())
        assert spec.table == "telemetry_sessions"
        assert "session_id" in spec.not_null

    def test_rejects_merge_key_present(self) -> None:
        entry = self._base_entry()
        entry["merge_key"] = "session_id"
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_current_table_present(self) -> None:
        entry = self._base_entry()
        entry["current_table"] = "telemetry_sessions_current"
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_non_append_only_write_mode(self) -> None:
        entry = self._base_entry()
        entry["write_mode"] = "scd2"
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_wrong_dedupe_key(self) -> None:
        entry = self._base_entry()
        entry["dedupe_key"] = ["event_id"]
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_wrong_partition_column(self) -> None:
        entry = self._base_entry()
        entry["partition_column"] = "event_timestamp"
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_non_triple_history_partition(self) -> None:
        entry = self._base_entry()
        entry["partition"] = {"history": "day(session_started_at)"}
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_missing_required_column(self) -> None:
        entry = self._base_entry()
        del entry["columns"]["created_timestamp"]
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_wrong_derived_role_set(self) -> None:
        entry = self._base_entry()
        entry["columns"]["parser_version"]["role"] = "derived"
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("telemetry_sessions", entry)

    def test_rejects_unregistered_table(self) -> None:
        with pytest.raises(AppendError):
            EventTableSpec.from_projection("not_a_telemetry_table", self._base_entry())


class TestIdentifierValidation:
    def test_rejects_unsafe_table_identifier(self, con: Any) -> None:
        bad_spec = EventTableSpec(table="telemetry_sessions; DROP TABLE x", columns=dict(_COLUMNS), not_null=_NOT_NULL)
        with pytest.raises(AppendError):
            append_events(con, bad_spec, [_row()], tenant_id=TENANT, project_id=PROJECT, catalog="memory")

    def test_rejects_now_without_timezone(self, con: Any) -> None:
        with pytest.raises(AppendError):
            append_events(
                con,
                _spec(),
                [_row()],
                tenant_id=TENANT,
                project_id=PROJECT,
                catalog="memory",
                now=datetime(2026, 9, 25),
            )
