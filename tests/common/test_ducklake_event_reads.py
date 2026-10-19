"""Pure mechanism and routing tests for src/common/ducklake_event_reads.py (no duckdb at module scope, fast-tier safe)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.common import ducklake_event_read_verbs as verbs
from src.common import ducklake_event_reads as ev
from src.common import ducklake_runtime as rt
from src.common.ducklake_event_read_sql import AGENTS, OBSERVATIONS, SESSIONS, TRANSCRIPTS
from src.common.ducklake_scd2_schema import NAMED_READS
from src.telemetry.append import EventTableSpec
from src.telemetry.identity import derive_entity_key

_SESSION = derive_entity_key(
    "telemetry_sessions:session_id",
    "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    "01BRZ3NDEKTSV4RRFFQ69G5FBW",
    "ref",
    datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc),
)
_AS_OF = "2026-09-26T12:00:00+00:00"
_STATE = verbs.EVENT_READS["session_state_and_duration"]
_WINDOW = verbs.EVENT_READS["sessions_window"]


@pytest.fixture
def smoke_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", rt.SMOKE_META_SCHEMA)
    monkeypatch.setenv("TELEMETRY_DATA_PATH", rt.SMOKE_DATA_PATH)


@pytest.fixture(autouse=True)
def _reset_slots() -> Any:
    rt.reset_warm_connection()
    ev._INTERRUPTED_SLOTS.clear()
    yield
    rt.reset_warm_connection()
    ev._INTERRUPTED_SLOTS.clear()


class FakeCursor:
    description = [("x",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [(1,)]


class RecordingCon:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.calls.append((sql, params))
        return FakeCursor()


def test_session_id_must_be_a_canonical_ulid() -> None:
    for bad in (_SESSION.lower(), _SESSION[:-1], _SESSION + "0", "", 17, None, "ILOU" + _SESSION[4:]):
        with pytest.raises(ev.EventReadInputError):
            ev.bind_values(_STATE, {"session_id": bad, "as_of": _AS_OF})
    assert ev.bind_values(_STATE, {"session_id": _SESSION, "as_of": _AS_OF})["session_id"] == _SESSION


def test_as_of_must_be_tz_aware() -> None:
    for bad in ("2026-09-26T12:00:00", "2026-09-26", "yesterday", 17, None, "2026-13-40T00:00:00Z"):
        with pytest.raises(ev.EventReadInputError):
            ev.bind_values(_STATE, {"session_id": _SESSION, "as_of": bad})
    assert ev.bind_values(_STATE, {"session_id": _SESSION, "as_of": "2026-09-26T14:00:00+02:00"})["as_of"] == datetime(
        2026, 9, 26, 12, tzinfo=timezone.utc
    )


def test_window_span_is_capped_per_verb() -> None:
    base = {"as_of": _AS_OF}
    ok = ev.bind_values(_WINDOW, {"day_from": "2026-09-25", "day_to": "2026-10-01", **base})
    assert (ok["part_to"] - ok["part_from"]).days == _WINDOW.max_window_days
    for first, last in (
        ("2026-09-25", "2026-10-02"),
        ("2026-09-26", "2026-09-25"),
        ("2026-09-25", "2026-9-26"),
        ("2026-02-30", "2026-03-01"),
        ("x", "y"),
    ):
        with pytest.raises(ev.EventReadInputError):
            ev.bind_values(_WINDOW, {"day_from": first, "day_to": last, **base})
    tighter = dataclasses.replace(_WINDOW, max_window_days=2)
    with pytest.raises(ev.EventReadInputError):
        ev.bind_values(tighter, {"day_from": "2026-09-25", "day_to": "2026-09-27", **base})


def test_errors_name_the_param_never_the_value() -> None:
    bad_value = "NOT-A-ULID-" + "Z" * 9
    with pytest.raises(ev.EventReadInputError) as caught:
        ev.bind_values(_STATE, {"session_id": bad_value, "as_of": _AS_OF})
    assert "session_id" in str(caught.value) and bad_value not in str(caught.value)
    assert caught.value.verb == "session_state_and_duration" and caught.value.error_class == "EventReadInputError"
    with pytest.raises(ev.EventReadInputError) as caught:
        ev.bind_values(_STATE, {"session_id": _SESSION, "as_of": "private-value"})
    assert "as_of" in str(caught.value) and "private-value" not in str(caught.value)
    with pytest.raises(ev.EventReadInputError) as caught:
        ev.bind_values(_STATE, {"session_id": _SESSION, "as_of": _AS_OF, "extra": "leak"})
    assert "leak" not in str(caught.value)
    with pytest.raises(ev.EventReadInputError):
        ev.bind_values(_STATE, ["not", "an", "object"])


def test_partition_bounds_decode_from_the_session_id() -> None:
    values = ev.bind_values(_STATE, {"session_id": _SESSION, "as_of": _AS_OF})
    assert values["part_from"] == datetime(2026, 9, 25, tzinfo=timezone.utc)
    assert values["part_to"] == datetime(2026, 9, 26, tzinfo=timezone.utc)
    window = ev.bind_values(_WINDOW, {"day_from": "2026-09-25", "day_to": "2026-09-26", "as_of": _AS_OF})
    assert (window["part_from"], window["part_to"]) == (
        datetime(2026, 9, 25, tzinfo=timezone.utc),
        datetime(2026, 9, 27, tzinfo=timezone.utc),
    )
    sql = ev.render_sql(_STATE)
    assert "session_started_at >= $part_from AND session_started_at < $part_to AND session_id = $session_id" in sql
    assert "day(" not in sql


def test_values_are_bound_never_interpolated() -> None:
    con = RecordingCon()
    ev.execute(con, verb="session_state_and_duration", params={"session_id": _SESSION, "as_of": _AS_OF})
    sql, bound = con.calls[0]
    assert _SESSION not in sql and "2026-09-26" not in sql and "2026-09-25" not in sql
    assert set(bound) == {"session_id", "as_of", "part_from", "part_to"}
    assert bound["session_id"] == _SESSION
    con = RecordingCon()
    ev.execute(con, verb="model_call_cost_estimate", params={"session_id": _SESSION}, limit="5")
    assert con.calls[0][0].endswith(" LIMIT 5")
    with pytest.raises(rt.DuckLakeRuntimeError, match="not paginable"):
        ev.execute(con, verb="session_state_and_duration", params={"session_id": _SESSION, "as_of": _AS_OF}, limit=1)


def test_refuses_unless_the_pin_is_the_smoke_catalog(monkeypatch: pytest.MonkeyPatch, smoke_pin: None) -> None:
    assert ev.require_smoke_pin() == (rt.SMOKE_META_SCHEMA, rt.SMOKE_DATA_PATH)
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", "ducklake_ops")
    with pytest.raises(rt.DuckLakeRuntimeError, match="rec-4292"):
        ev.require_smoke_pin()
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", rt.SMOKE_META_SCHEMA)
    monkeypatch.setenv("TELEMETRY_DATA_PATH", "s3://elsewhere/telemetry/")
    with pytest.raises(rt.DuckLakeRuntimeError, match="rec-4292"):
        ev.require_smoke_pin()
    monkeypatch.delenv("TELEMETRY_META_SCHEMA")
    with pytest.raises(rt.DuckLakeRuntimeError):
        ev.require_smoke_pin()


def test_read_version_moves_with_every_datum_sql_and_column(monkeypatch: pytest.MonkeyPatch) -> None:
    base = ev.event_read_version("session_friction_rollup")
    assert base == ev.event_read_version("session_friction_rollup")
    assert len(base) == 16
    entry = verbs.EVENT_READS["session_friction_rollup"]

    def changed(**overrides: Any) -> str:
        patched = dict(verbs.EVENT_READS) | {"session_friction_rollup": dataclasses.replace(entry, **overrides)}
        monkeypatch.setattr(verbs, "EVENT_READS", patched)
        return ev.event_read_version("session_friction_rollup")

    seen = {base}
    data = dict(entry.data)
    for key, value in (("repeat_threshold", 4), ("classifier_version", 2), ("run_label", "other_label")):
        seen.add(changed(data=data | {key: value}))
    seen.add(changed(data=data | {"rules": data["rules"][:-1]}))
    assert changed(sql=entry.sql + "   ") == base, "whitespace-only SQL edits must not re-version"
    seen.add(changed(sql=entry.sql + " -- edit"))
    seen.add(changed(params=("session_id", "x")))
    seen.add(changed(paginable=True))
    seen.add(changed(max_window_days=3))
    assert len(seen) == 9, "every datum, the SQL, params, paginable flag and window cap must each re-version the verb"
    semantics = ev.rt.load_field_semantics()
    narrowed = {**semantics, "ops_tables": {**semantics["ops_tables"]}}
    narrowed["ops_tables"][OBSERVATIONS] = {
        **semantics["ops_tables"][OBSERVATIONS],
        "columns": {k: v for k, v in semantics["ops_tables"][OBSERVATIONS]["columns"].items() if k != "metadata"},
    }
    monkeypatch.setattr(verbs, "EVENT_READS", dict(verbs.EVENT_READS))
    assert ev.event_read_version("session_friction_rollup", narrowed) != ev.event_read_version("session_friction_rollup")


@pytest.mark.parametrize("table", [SESSIONS, OBSERVATIONS, TRANSCRIPTS, AGENTS])
def test_compared_columns_match_the_writer_compare_set(table: str) -> None:
    entry = ev.rt.load_field_semantics()["ops_tables"][table]
    spec = EventTableSpec.from_projection(table, entry)
    assert set(ev.compared_columns(table)) == set(spec.columns) - spec.compare_excluded
    assert {"created_timestamp", "producer_version"}.isdisjoint(ev.compared_columns(table))


def test_acquirer_routes_only_event_verbs_to_the_telemetry_slot(smoke_pin: None) -> None:
    def ops(force_reopen: bool = False) -> tuple[Any, dict[str, Any]]:
        return "ops-con", {}

    for action, payload in (
        ("named_read", {"verb": "open_recs_tally", "params": {}}),
        ("query_ops", {"table": "ops_recommendations", "sql": "SELECT 1", "verb": "session_state_and_duration"}),
        ("read_ops_current", {"table": "ops_recommendations"}),
        ("attach_check", {}),
    ):
        assert ev.acquirer_for(action, payload, ops, "/ext") is ops
    event = ev.acquirer_for("named_read", {"verb": "telemetry_health_count", "params": {}}, ops, "/ext")
    assert event is not ops


def test_a_non_string_verb_routes_to_ops(smoke_pin: None) -> None:
    def ops() -> tuple[Any, dict[str, Any]]:
        return "ops-con", {}

    for verb in (["session_state_and_duration"], {"a": 1}, 7, None, "", "unknown_verb"):
        assert ev.acquirer_for("named_read", {"verb": verb}, ops, "/ext") is ops
    assert ev.acquirer_for("named_read", {}, ops, "/ext") is ops


def test_validation_and_pin_refusal_precede_any_acquire(monkeypatch: pytest.MonkeyPatch, smoke_pin: None) -> None:
    opened: list[str] = []
    monkeypatch.setattr(rt, "open_connection", lambda **kw: opened.append("open") or RecordingCon())
    monkeypatch.setattr(rt, "fetch_dsn", lambda *a, **k: {})
    with pytest.raises(ev.EventReadInputError):
        ev.acquirer_for(
            "named_read", {"verb": "session_state_and_duration", "params": {"session_id": "bad", "as_of": _AS_OF}}, None, "/e"
        )
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", "ducklake_ops")
    with pytest.raises(rt.DuckLakeRuntimeError):
        ev.acquirer_for(
            "named_read",
            {"verb": "session_state_and_duration", "params": {"session_id": _SESSION, "as_of": _AS_OF}},
            None,
            "/e",
        )
    assert opened == []
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", rt.SMOKE_META_SCHEMA)
    acquire = ev.acquirer_for(
        "named_read", {"verb": "session_state_and_duration", "params": {"session_id": _SESSION, "as_of": _AS_OF}}, None, "/e"
    )
    assert opened == []  # lazily opened: acquiring the callable pays no ATTACH
    con, meta = acquire()
    assert opened == ["open"] and meta["reused"] is False
    assert con.calls[0][0].startswith("SET memory_limit='300MB'")
    assert acquire()[1]["reused"] is True and opened == ["open"]


def _telemetry_payload(**extra: Any) -> dict[str, Any]:
    return {"verb": "telemetry_health_count", "params": {}, **extra}


def test_telemetry_opener_sets_threads_and_serial_catalog_scans(monkeypatch: pytest.MonkeyPatch, smoke_pin: None) -> None:
    con = RecordingCon()
    monkeypatch.setattr(rt, "open_connection", lambda **kw: con)
    monkeypatch.setattr(rt, "fetch_dsn", lambda *a, **k: {})
    ev._telemetry_opener(rt.SMOKE_META_SCHEMA, rt.SMOKE_DATA_PATH, "/e")()
    statements = [sql for sql, _ in con.calls]
    assert statements[0].startswith("SET memory_limit=") and statements[1:] == [
        f"SET threads={ev.TELEMETRY_THREADS}",
        "SET pg_use_ctid_scan=false",
    ]
    assert ev.TELEMETRY_THREADS == 8


def test_deadline_ms_is_refused_before_any_attach(monkeypatch: pytest.MonkeyPatch, smoke_pin: None) -> None:
    opened: list[str] = []
    monkeypatch.setattr(rt, "open_connection", lambda **kw: opened.append("open") or RecordingCon())
    for bad in (0, -1, True, "5", 1.5):
        with pytest.raises(ev.EventReadInputError) as info:
            ev.acquirer_for("named_read", _telemetry_payload(deadline_ms=bad), None, "/e")
        assert info.value.param == "deadline_ms"
    assert opened == []
    assert callable(ev.acquirer_for("named_read", _telemetry_payload(deadline_ms=5000), None, "/e"))


def test_deadline_ms_on_an_ops_verb_is_refused(smoke_pin: None) -> None:
    with pytest.raises(rt.DuckLakeRuntimeError, match="deadline_ms"):
        ev.acquirer_for("named_read", {"verb": "open_recs_tally", "params": {}, "deadline_ms": 5000}, None, "/e")


def test_deadline_guard_is_identity_off_event_verbs(smoke_pin: None) -> None:
    for action, payload in (
        ("named_read", {"verb": "open_recs_tally", "params": {}}),
        ("query_ops", {"verb": "telemetry_health_count"}),
        ("read_ops_current", {}),
    ):
        guard = ev.deadline_guard(action, payload, lambda: 0.0)
        assert guard(object(), lambda: "ran") == "ran"
    assert ev._INTERRUPTED_SLOTS == set()


def test_deadline_guard_marks_the_slot_on_a_spent_deadline(smoke_pin: None) -> None:
    guard = ev.deadline_guard("named_read", _telemetry_payload(), lambda: 5_000.0)
    ran: list[int] = []
    with pytest.raises(ev.deadline.TypedFault) as info:
        guard(object(), lambda: ran.append(1))
    assert info.value.status == 504 and ran == [] and ev.TELEMETRY_SLOT in ev._INTERRUPTED_SLOTS
    ev._INTERRUPTED_SLOTS.clear()


def test_interrupted_slot_probes_the_catalog_once(monkeypatch: pytest.MonkeyPatch, smoke_pin: None) -> None:
    probes: list[str] = []

    class ProbeCon(RecordingCon):
        def __init__(self, fail: bool = False) -> None:
            super().__init__()
            self.fail = fail

        def execute(self, sql: str, params: Any = None) -> FakeCursor:
            if sql.startswith("SELECT"):
                probes.append(sql)
                if self.fail:
                    raise RuntimeError("catalog connection is broken")
            return super().execute(sql, params)

        def close(self) -> None:
            pass

    cons = [ProbeCon(fail=False)]
    monkeypatch.setattr(rt, "open_connection", lambda **kw: cons[-1])
    monkeypatch.setattr(rt, "fetch_dsn", lambda *a, **k: {})
    acquire = ev.acquirer_for("named_read", _telemetry_payload(), None, "/e")
    acquire()
    assert probes == []
    ev._INTERRUPTED_SLOTS.add(ev.TELEMETRY_SLOT)
    assert acquire()[1]["reused"] is True
    assert len(probes) == 1 and "__ducklake_metadata_" in probes[0] and "ducklake_metadata" in probes[0]
    assert acquire()[1]["reused"] is True and probes[1:] == ["SELECT 1"]
    cons[0].fail = True
    cons.append(ProbeCon())
    ev._INTERRUPTED_SLOTS.add(ev.TELEMETRY_SLOT)
    con, meta = acquire()
    assert meta["reopened"] is True and con is cons[1]


def test_event_verbs_are_described_with_their_class_bounds_and_audience() -> None:
    described = ev.describe_all()
    event = {v: described[v] for v in verbs.EVENT_READS}
    assert all(row["kind"] == "event_journal" and row["catalog"] == "telemetry" for row in event.values())
    assert event["sessions_window"]["max_window_days"] == verbs.MAX_WINDOW_DAYS
    assert event["sessions_window"]["binding"] == "window" and event["telemetry_health_count"]["binding"] == "none"
    assert {v for v, row in event.items() if not row["agent_facing"]} == {
        "session_tree_rows",
        "sessions_window_all_purposes",
        "telemetry_health_count",
        "telemetry_orphan_counts",
        "telemetry_root_sessions",
        "transcript_content",
    }
    assert all("smoke catalog" in verbs.EVENT_READS[v].description for v in verbs.EVENT_READS)
    assert all(row["read_version"] == ev.event_read_version(v) for v, row in event.items())
    assert event["session_state_and_duration"]["tables"][0] == SESSIONS


def test_event_and_ops_verb_names_are_disjoint() -> None:
    assert not set(verbs.EVENT_READS) & set(NAMED_READS)
    assert all(entry.verb == name for name, entry in verbs.EVENT_READS.items())


def test_event_describe_rows_carry_every_ops_describe_key() -> None:
    described = ev.describe_all()
    ops_keys = set(next(iter(rt.describe_named_reads().values())))
    for verb in verbs.EVENT_READS:
        assert ops_keys <= set(described[verb]), verb
    assert {"kind", "tables", "catalog", "binding", "max_window_days"} <= set(described["sessions_window"])


def test_mcp_tool_registry_builds_from_describe_all_and_projects_only_agent_facing() -> None:
    from scripts.agent_sdk.mcp_server import build_tool_registry  # noqa: PLC0415

    described = ev.describe_all()
    names = {tool.name for tool in build_tool_registry(described)}
    event_agent_facing = {v for v, e in verbs.EVENT_READS.items() if e.agent_facing}
    assert event_agent_facing <= names
    assert not names & {"sessions_window_all_purposes", "telemetry_health_count"}
    assert names == {v for v, meta in described.items() if meta["agent_facing"]}


def test_serve_named_read_routes_ops_verbs_through_the_unchanged_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "named_read", lambda con, **kw: [{"n": 1}])
    rows, version = ev.serve_named_read(object(), verb="count_by_status", params={}, limit=None)
    assert rows == [{"n": 1}] and version == rt.read_version("count_by_status")
    rows, version = ev.serve_named_read(RecordingCon(), verb="telemetry_health_count", params={}, limit=None)
    assert version == ev.event_read_version("telemetry_health_count") and rows == [{"x": 1}]


def test_render_refuses_an_unbound_placeholder() -> None:
    broken = dataclasses.replace(_STATE, sql=_STATE.sql + " {nope}")
    with pytest.raises(rt.DuckLakeRuntimeError, match="unbound"):
        ev.render_sql(broken)


def test_falsy_non_object_params_are_refused_before_any_acquire(smoke_pin: None) -> None:
    for params in ([], "", 0):
        with pytest.raises(ev.EventReadInputError):
            ev.acquirer_for("named_read", {"verb": "telemetry_health_count", "params": params}, None, "/e")
    assert callable(ev.acquirer_for("named_read", {"verb": "telemetry_health_count"}, None, "/e"))


_CONTENT = verbs.EVENT_READS["transcript_content"]
_EVENT = "01CRZ3NDEKTSV4RRFFQ69G5FAV"


def _content_params(**over: Any) -> dict[str, Any]:
    base = {
        "session_id": _SESSION,
        "producer": "claude_code",
        "event_id": _EVENT,
        "parser_version": 3,
        "offset": 0,
        "max_bytes": 1024,
    }
    return {**base, **over}


def test_transcript_content_is_registered_not_agent_facing() -> None:
    assert _CONTENT.binding == "session" and _CONTENT.agent_facing is False and _CONTENT.tables == (TRANSCRIPTS,)
    assert _CONTENT.params == ("session_id", "producer", "event_id", "parser_version", "offset", "max_bytes")
    assert _CONTENT.int_params == ("parser_version", "offset", "max_bytes") and not _CONTENT.paginable
    sql = " ".join(ev.render_sql(_CONTENT).split())
    assert "producer = $producer AND event_id = $event_id AND parser_version = $parser_version" in sql
    assert "as_of" not in sql and "v_star" not in sql and "QUALIFY" not in sql and "compared_versions" in sql
    row = ev.describe_all()["transcript_content"]
    props = row["params_schema"]["properties"]
    assert [p for p, t in props.items() if t == {"type": "integer"}] == ["parser_version", "offset", "max_bytes"]
    assert props["producer"] == {"type": "string"} and row["agent_facing"] is False
    assert ev.event_read_version("transcript_content") == row["read_version"]
    others = {v: ev.event_read_version(v) for v in verbs.EVENT_READS if v != "transcript_content"}
    assert len(set(others.values())) == len(others)


def test_content_params_are_validated_without_echo() -> None:
    assert ev.bind_values(_CONTENT, _content_params())["parser_version"] == 3
    refusals = [
        ("producer", 7),
        ("producer", ""),
        ("producer", "x" * 201),
        ("producer", "bad\x00name"),
        ("event_id", "not-a-ulid"),
        ("event_id", 5),
        ("parser_version", "3"),
        ("parser_version", True),
        ("parser_version", 0),
        ("offset", "0"),
        ("offset", False),
        ("offset", -1),
        ("max_bytes", "9"),
        ("max_bytes", 0),
        ("max_bytes", 1.5),
    ]
    for name, value in refusals:
        with pytest.raises(ev.EventReadInputError) as caught:
            ev.bind_values(_CONTENT, _content_params(**{name: value}))
        assert f"'{name}'" in str(caught.value)
        assert str(value) not in str(caught.value) or str(value) in {"", "0", "True", "False"}
    with pytest.raises(ev.EventReadInputError):
        ev.bind_values(_CONTENT, {k: v for k, v in _content_params().items() if k != "offset"})


def test_content_verb_hands_resolved_rows_to_the_content_module(monkeypatch: pytest.MonkeyPatch, smoke_pin: None) -> None:
    from src.common import ducklake_event_content as content

    class Cursor:
        description = [("content",), ("compared_versions",)]

        def fetchall(self) -> list[tuple[Any, ...]]:
            return [("hello", 1)]

    class Con:
        def execute(self, sql: str, params: Any = None) -> Cursor:
            self.params = params
            return Cursor()

    seen: list[Any] = []
    monkeypatch.setattr(content, "serve_content", lambda rows, values: seen.append((rows, values)) or [{"ok": 1}])
    con = Con()
    assert ev.execute(con, verb="transcript_content", params=_content_params()) == [{"ok": 1}]
    rows, values = seen[0]
    assert rows == [{"content": "hello", "compared_versions": 1}] and values["offset"] == 0
    assert sorted(con.params) == ["event_id", "parser_version", "part_from", "part_to", "producer", "session_id"]


_TREE = verbs.EVENT_READS["session_tree_rows"]
_ORPHANS = verbs.EVENT_READS["telemetry_orphan_counts"]
_ROOT = "01M3C03V80C6ZZ53H4MAGFS7Z4"


def test_tree_binding_validates_and_clamps_max_rows() -> None:
    values = ev.bind_values(_TREE, {"session_id": _ROOT, "offset": 0, "max_rows": 999999})
    assert values["max_rows"] == verbs.MAX_TREE_ROWS == 2000 and values["offset"] == 0
    assert values["part_to"] - values["part_from"] == timedelta(days=1) and values["session_id"] == _ROOT
    assert ev.bind_values(_TREE, {"session_id": _ROOT, "offset": 40, "max_rows": 7})["max_rows"] == 7
    for bad in (
        {"session_id": _ROOT, "offset": 0, "max_rows": 0},
        {"session_id": _ROOT, "offset": 0, "max_rows": True},
        {"session_id": _ROOT, "offset": -1, "max_rows": 5},
        {"session_id": _ROOT, "offset": "9", "max_rows": 5},
        {"session_id": "not-a-ulid-SECRET", "offset": 0, "max_rows": 5},
        {"session_id": _ROOT, "offset": 0},
    ):
        with pytest.raises(ev.EventReadInputError) as raised:
            ev.bind_values(_TREE, bad)
        assert "SECRET" not in str(raised.value)


def test_telemetry_joins_come_from_the_projection() -> None:
    projected = rt.load_field_semantics()["telemetry_joins"]
    assert ev.telemetry_joins() == projected and projected
    sql = ev.render_sql(_ORPHANS)
    assert all(join["join_id"] in sql for join in projected) and "{telemetry_joins}" not in sql
    with pytest.raises(rt.DuckLakeRuntimeError, match="telemetry_joins"):
        ev.telemetry_joins({"ops_tables": {}})
    hostile = [dict(projected[0], child_column="x; DROP TABLE t")]
    with pytest.raises(rt.DuckLakeRuntimeError, match="unsupported"):
        ev.render_sql(_ORPHANS, {**rt.load_field_semantics(), "telemetry_joins": hostile})


def test_orphan_read_version_moves_with_a_projected_join() -> None:
    semantics = rt.load_field_semantics()
    changed = {**semantics, "telemetry_joins": [dict(semantics["telemetry_joins"][0], parent_column="session_id")]}
    changed["telemetry_joins"] += semantics["telemetry_joins"][1:]
    assert ev.event_read_version("telemetry_orphan_counts", changed) != ev.event_read_version(
        "telemetry_orphan_counts", semantics
    )
    for verb in verbs.EVENT_READS:
        if verb != "telemetry_orphan_counts":
            assert ev.event_read_version(verb, changed) == ev.event_read_version(verb, semantics), verb


_SEAM = """
import builtins, io, pathlib
def _refuse(name):
    if "field_semantics.yaml" in str(name):
        raise RuntimeError("field_semantics.yaml read at import")
_open = builtins.open
def guarded(file, *a, **k):
    _refuse(file)
    return _open(file, *a, **k)
builtins.open = io.open = guarded
_read_text, _path_open = pathlib.Path.read_text, pathlib.Path.open
pathlib.Path.read_text = lambda self, *a, **k: (_refuse(self), _read_text(self, *a, **k))[1]
pathlib.Path.open = lambda self, *a, **k: (_refuse(self), _path_open(self, *a, **k))[1]
"""
_IMPORT = """
from src.common import ducklake_runtime as rt
def refuse(*a, **k):
    raise RuntimeError("load_field_semantics called at import")
rt.load_field_semantics = refuse
import src.common.ducklake_event_read_verbs, src.common.ducklake_event_reads as ev
try:
    ev.telemetry_joins()
except RuntimeError:
    print("IMPORT_READS_NO_FILE")
"""


def test_registry_import_reads_no_file(tmp_path: Any) -> None:
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    (tmp_path / "sitecustomize.py").write_text(_SEAM, encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), str(root)])}
    done = subprocess.run(
        [sys.executable, "-c", _IMPORT], cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert done.returncode == 0 and "IMPORT_READS_NO_FILE" in done.stdout, done.stderr[-400:]
