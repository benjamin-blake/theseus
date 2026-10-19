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
from src.common import ducklake_dq_checks as dq
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


def test_dq_check_runs_on_the_ops_slot_only(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(dq, "run_check", lambda con, check: seen.append(con) or 0)
    status, body = _call(
        {"action": "dq_check", "check": "row_count_min", "table": "ops_recommendations", "params": {"min": 1}}
    )
    assert status == 200 and body["violation_count"] == 0
    assert seen == [wiring["ops_con"]] and wiring["telemetry_opened"] == 0


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


_CONTENT_COLUMNS = ("content", "content_uri", "content_sha256", "content_bytes", "content_omitted_reason", "compared_versions")
_BLOB_URI = "01ARZ3NDEKTSV4RRFFQ69G5FAV/01ARZ3NDEKTSV4RRFFQ69G5FAW/01ARZ3NDEKTSV4RRFFQ69G5FAX/" + "cd" * 32
_BLOB_BYTES = b"transcript bytes " * 4


class _ContentCon(FakeCon):
    rows: list[tuple[Any, ...]] = []

    def __init__(self, label: str, fail_first: bool = False) -> None:
        super().__init__(label, fail_first)
        self.description = [(name,) for name in _CONTENT_COLUMNS]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _BlobFake:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def get_blob(self, uri: str, sha: str, size: int, *, offset: int, length: int) -> bytes:
        if self.error is not None:
            raise self.error
        return _BLOB_BYTES[offset : offset + length]


def _content_wiring(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch, rows: list[tuple[Any, ...]], store: Any) -> None:
    from src.common import ducklake_event_content as content

    _ContentCon.rows = rows
    monkeypatch.setattr(rt, "open_connection", lambda **kw: _ContentCon("telemetry"))
    monkeypatch.setattr(content, "BLOB_STORE", store)


def _content_request(**over: Any) -> dict[str, Any]:
    params = {
        "session_id": _SESSION,
        "producer": "claude_code",
        "event_id": "01CRZ3NDEKTSV4RRFFQ69G5FAV",
        "parser_version": 3,
        "offset": 0,
        "max_bytes": 1000,
    }
    return {"action": "named_read", "verb": "transcript_content", "params": {**params, **over}}


def _object_row(versions: int = 1) -> tuple[Any, ...]:
    import hashlib

    return (None, _BLOB_URI, hashlib.sha256(_BLOB_BYTES).hexdigest(), len(_BLOB_BYTES), None, versions)


def test_transcript_content_through_the_handler(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    _content_wiring(wiring, monkeypatch, [_object_row()], _BlobFake())
    status, body = _call(_content_request())
    assert status == 200 and body["verb"] == "transcript_content" and body["row_count"] == 1
    (row,) = body["rows"]
    assert row["storage"] == "object" and base64.b64decode(row["data"]) == _BLOB_BYTES
    assert row["length"] == row["content_bytes"] == len(_BLOB_BYTES) and "content_uri" not in row
    assert _BLOB_URI not in json.dumps(body)
    _content_wiring(wiring, monkeypatch, [], _BlobFake())
    status, body = _call(_content_request())
    assert status == 200 and body["rows"] == [] and body["row_count"] == 0


def test_blob_faults_answer_typed_through_the_handler(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from src.common import ducklake_event_content as content
    from src.common.ducklake_telemetry_blobstore import (
        BlobIntegrityError,
        BlobStoreAccessError,
        BlobStoreUnavailableError,
        LazyBlobStore,
    )

    arn = "arn:aws:iam::" + "1" * 12 + ":role/reader"
    cases: list[tuple[int, str, str]] = [
        (500, "blob_integrity", "length_mismatch"),
        (500, "blob_integrity", "forbidden_or_missing"),
        (503, "blob_unavailable", "store_unavailable"),
        (500, "blob_misconfigured", "store_access"),
    ]
    errors: list[Exception] = [
        BlobIntegrityError(arn, reason="length_mismatch"),
        BlobIntegrityError(arn, reason="forbidden_or_missing"),
        BlobStoreUnavailableError(arn),
        BlobStoreAccessError(arn),
    ]
    for error, (want_status, want_type, want_reason) in zip(errors, cases):
        _content_wiring(wiring, monkeypatch, [_object_row()], _BlobFake(error))
        status, body = _call(_content_request())
        assert status == want_status
        assert set(body) == {"ok", "error_type", "reason", "request_id", "action"}
        assert (body["error_type"], body["reason"], body["ok"]) == (want_type, want_reason, False)
        assert arn not in json.dumps(body) and _BLOB_URI not in json.dumps(body)
    _content_wiring(wiring, monkeypatch, [_object_row(versions=2)], _BlobFake())
    status, body = _call(_content_request())
    assert (status, body["error_type"], body["reason"]) == (500, "grain_conflict", "differing_rows")
    monkeypatch.delenv("TELEMETRY_BLOB_ROOT", raising=False)
    _content_wiring(wiring, monkeypatch, [_object_row()], LazyBlobStore(content._build_store))
    status, body = _call(_content_request())
    assert (status, body["error_type"], body["reason"]) == (500, "blob_misconfigured", "not_configured")
    _content_wiring(wiring, monkeypatch, [_object_row()], _BlobFake())
    status, body = _call(_content_request(offset=len(_BLOB_BYTES)))
    assert status == 400 and body["error_type"] == "named_read_input" and str(len(_BLOB_BYTES)) not in body["error"]


class _Context:
    aws_request_id = "req-deadline"

    def __init__(self, remaining: Any) -> None:
        self._remaining = remaining

    def get_remaining_time_in_millis(self) -> float:
        return self._remaining() if callable(self._remaining) else self._remaining


def _call_with(payload: dict[str, Any], context: Any) -> tuple[int, dict[str, Any]]:
    response = h.handler({"body": json.dumps(payload)}, context)
    return response["statusCode"], json.loads(response["body"])


_EVENT_READ = {"action": "named_read", "verb": "telemetry_health_count", "params": {}}


def test_event_verb_past_its_deadline_answers_504(wiring: dict[str, Any]) -> None:
    status, body = _call_with(_EVENT_READ, _Context(5_000))
    assert status == 504
    assert body == {
        "ok": False,
        "error_type": "read_deadline_exceeded",
        "reason": "reader_deadline",
        "request_id": "req-deadline",
        "action": "named_read",
    }
    assert wiring["ops_opened"] == 0 and wiring["ops_con"].executed == []
    assert _call_with(_EVENT_READ, _Context(600_000))[0] == 200


def test_ops_verbs_run_without_a_deadline(wiring: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "named_read", lambda con, **kw: [{"n": 1}])
    status, body = _call_with({"action": "named_read", "verb": "count_by_status", "params": {}}, _Context(5_000))
    assert status == 200 and body["row_count"] == 1


def test_reopen_once_runs_under_the_deadline(wiring: dict[str, Any]) -> None:
    remaining = iter([600_000, 5_000])
    wiring["telemetry_fail_first"] = True
    status, body = _call_with(_EVENT_READ, _Context(lambda: next(remaining)))
    assert status == 504 and body["error_type"] == "read_deadline_exceeded"
    assert wiring["telemetry_opened"] == 2
