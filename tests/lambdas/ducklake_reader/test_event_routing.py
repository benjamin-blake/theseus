"""End-to-end reader handler routing for event-journal verbs, with fake connections (rec-4291).

Event verbs bind the lazily opened telemetry slot; every other action, query_ops included, binds the ops slot and never
opens or reaches the telemetry slot; the smoke-pin refusal and parameter validation both precede any connect.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

import src.lambdas.ducklake_reader.handler as h
from src.common import ducklake_runtime as rt
from src.telemetry.identity import derive_entity_key

pytestmark = pytest.mark.unit

_SESSION = derive_entity_key(
    "telemetry_sessions:session_id",
    "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    "01BRZ3NDEKTSV4RRFFQ69G5FBW",
    "ref",
    datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc),
)
_PARAMS = {"session_id": _SESSION, "as_of": "2026-09-26T12:00:00+00:00"}


class FakeCon:
    def __init__(self, label: str, fail_first: bool = False) -> None:
        self.label = label
        self.executed: list[tuple[str, Any]] = []
        self.description = [("table_name",), ("record_count",)]
        self._fail_first = fail_first

    def execute(self, sql: str, params: Any = None) -> FakeCon:
        self.executed.append((sql, params))
        if self._fail_first and sql.lstrip().startswith(("WITH", "SELECT t.table_name")):
            self._fail_first = False
            raise Exception("server closed the connection unexpectedly")
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [("telemetry_sessions", 3)]

    def close(self) -> None:
        pass


@pytest.fixture
def wiring(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    rt.reset_warm_connection()
    state: dict[str, Any] = {"ops_opened": 0, "telemetry_opened": 0, "telemetry_fail_first": False}
    ops_con = FakeCon("ops")
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", rt.SMOKE_META_SCHEMA)
    monkeypatch.setenv("TELEMETRY_DATA_PATH", rt.SMOKE_DATA_PATH)

    def open_ops() -> FakeCon:
        state["ops_opened"] += 1
        return ops_con

    def open_connection(**kwargs: Any) -> FakeCon:
        assert kwargs["alias"] == rt.TELEMETRY_CATALOG_ALIAS
        state["telemetry_opened"] += 1
        con = FakeCon("telemetry", fail_first=state["telemetry_fail_first"])
        state["telemetry_fail_first"] = False
        state.setdefault("telemetry_cons", []).append(con)
        return con

    monkeypatch.setattr(h, "_open_reader_connection", open_ops)
    monkeypatch.setattr(rt, "open_connection", open_connection)
    monkeypatch.setattr(rt, "fetch_dsn", lambda *a, **k: {})
    state["ops_con"] = ops_con
    yield state
    rt.reset_warm_connection()


def _call(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    response = h.handler({"body": json.dumps(payload)})
    return response["statusCode"], json.loads(response["body"])


def test_event_read_binds_the_telemetry_slot(wiring: dict[str, Any]) -> None:
    status, body = _call({"action": "named_read", "verb": "telemetry_health_count", "params": {}})
    assert status == 200 and body["rows"] == [{"table_name": "telemetry_sessions", "record_count": 3}]
    assert wiring["telemetry_opened"] == 1 and wiring["ops_opened"] == 0
    assert body["registry_version"] == rt.NAMED_READS_VERSION and body["verb"] == "telemetry_health_count"
    assert len(body["read_version"]) == 16
    status, _ = _call({"action": "named_read", "verb": "telemetry_health_count", "params": {}})
    assert status == 200 and wiring["telemetry_opened"] == 1  # warm reuse of the telemetry slot
    assert wiring["ops_con"].executed == []


def test_ops_actions_never_open_the_telemetry_slot(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "named_read", lambda con, **kw: [{"n": 1}])
    monkeypatch.setattr(rt, "read_current", lambda con, **kw: [])
    assert _call({"action": "named_read", "verb": "count_by_status", "params": {}})[0] == 200
    assert _call({"action": "read_current"})[0] == 200
    assert wiring["telemetry_opened"] == 0 and wiring["ops_opened"] == 1
    assert rt._named_slots.get("telemetry", {}) == {}


def test_query_ops_runs_on_the_ops_slot_only(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(rt, "query_current", lambda con, **kw: seen.append(con) or [])
    status, _ = _call(
        {
            "action": "query_ops",
            "table": "ops_recommendations",
            "sql": "SELECT count(*) FROM telemetry_catalog.telemetry_sessions",
        }
    )
    assert status == 200 and seen == [wiring["ops_con"]]
    assert wiring["telemetry_opened"] == 0


def test_smoke_pin_refusal_happens_before_any_connect(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", "ducklake_ops")
    status, body = _call({"action": "named_read", "verb": "session_state_and_duration", "params": _PARAMS})
    assert status == 500 and body["error_type"] == "runtime" and "rec-4292" in body["error"]
    assert wiring["telemetry_opened"] == 0 and wiring["ops_opened"] == 0


def test_event_input_refusal_is_400_without_the_value(wiring: dict[str, Any]) -> None:
    bad_value = "private-session-value"
    status, body = _call(
        {
            "action": "named_read",
            "verb": "session_state_and_duration",
            "params": {"session_id": bad_value, "as_of": _PARAMS["as_of"]},
        }
    )
    assert status == 400 and body["error_type"] == "named_read_input"
    assert body["verb"] == "session_state_and_duration" and body["error_class"] == "EventReadInputError"
    assert "session_id" in body["error"] and bad_value not in json.dumps(body)
    assert wiring["telemetry_opened"] == 0 and wiring["ops_opened"] == 0


def test_dead_telemetry_session_reopens_only_its_own_slot(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "read_current", lambda con, **kw: [])
    assert _call({"action": "read_current"})[0] == 200
    wiring["telemetry_fail_first"] = True
    status, body = _call({"action": "named_read", "verb": "telemetry_health_count", "params": {}})
    assert status == 200 and wiring["telemetry_opened"] == 2 and wiring["ops_opened"] == 1
    assert rt._warm_connection["con"] is wiring["ops_con"]
    assert body["row_count"] == 1


def test_describe_returns_both_registries(wiring: dict[str, Any]) -> None:
    status, body = _call({"action": "describe"})
    assert status == 200
    assert set(rt.NAMED_READS) <= set(body["verbs"]) and "sessions_window" in body["verbs"]
    assert body["verbs"]["sessions_window"]["kind"] == "event_journal"
    assert wiring["telemetry_opened"] == 0 and wiring["ops_opened"] == 0
