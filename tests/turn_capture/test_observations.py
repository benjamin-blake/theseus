"""Observation rows: one assertion per column rule, outcome precedence, hook signature and severity."""

from __future__ import annotations

import json
from collections import Counter

from src.turn_capture import observations
from src.turn_capture.observations import build_observations, hook_name, outcome_of
from src.turn_capture.streams import ROOT
from tests.fixtures.turn_capture_corpus import (
    SID,
    assistant,
    attachment,
    hook,
    make_ctx,
    parse_records,
    prompt,
    rows_of,
    text_block,
    tool_result,
    tool_use_block,
)


def build(root, children=None, final=True):
    diag: Counter[str] = Counter()
    rows = build_observations(parse_records(root, children, final), make_ctx(), diag)
    return rows_of(rows), diag


def by(rows, **match):
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def test_model_call_owned_by_last_record_one_per_response() -> None:
    usage = {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3}
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})], usage=usage, api_block=0),
        tool_result("r1", 3, "t1", "ok", pid="p1"),
        assistant("a2", 4, "m1", [text_block("done")], usage=usage, api_block=1, stop_reason=None),
        assistant("a3", 5, "m2", [text_block("second")], usage={"input_tokens": "9", "output_tokens": True}),
    ]
    rows, diag = build(root)
    calls = by(rows, observation_type="model_call")
    assert [c["external_ref"] for c in calls] == ["m1/model_call", "m2/model_call"]
    first = calls[0]
    assert first["source_ordinal"] == 3 and first["event_timestamp"].isoformat().startswith("2026-01-01T00:00:04")
    assert (first["tokens_input"], first["tokens_output"], first["tokens_cache_read"], first["tokens_cache_creation"]) == (
        1,
        2,
        3,
        0,
    )
    assert first["entity_ref"] == "m1" and first["parent_observation_ref"] == f"{SID}/p1"
    assert (
        first["billing_shape"] == "fixed_non_rollover_allowance"
        and first["provider"] is None
        and first["persona_backend"] is None
    )
    assert first["name"] == "agent_turn" and first["model"] == "claude-test-1" and first["event_kind"] == "point"
    meta = json.loads(first["metadata"])
    assert meta["block_count"] == 2 and meta["request_id"] == "req_m1" and meta["thinking_tokens"] is None
    assert (calls[1]["tokens_input"], calls[1]["tokens_output"]) == (0, 0) and diag["non_int_usage"] == 2


def test_thinking_tokens_and_metadata_shapes() -> None:
    usage = {"input_tokens": 1, "output_tokens": 1, "output_tokens_details": {"thinking_tokens": 7}}
    rows, _ = build(
        [
            prompt("u1", 1, "p1", "go", promptSource="sdk", turnOrigin="human"),
            assistant("a1", 2, "m1", [text_block("x")], usage=usage),
        ]
    )
    assert json.loads(by(rows, observation_type="model_call")[0]["metadata"])["thinking_tokens"] == 7
    turn_open = by(rows, observation_type="turn", event_kind="open")[0]
    assert json.loads(turn_open["metadata"]) == {"is_meta": False, "prompt_source": "sdk", "turn_origin": "human"}
    turn_close = by(rows, observation_type="turn", event_kind="close")[0]
    assert json.loads(turn_close["metadata"]) == {"response_count": 1, "tool_call_count": 0}
    assert turn_open["sequence"] == turn_close["sequence"] == 1 and turn_open["entity_ref"] == f"{SID}/p1"
    assert turn_open["external_ref"] == "u1#0/turn_open" and turn_close["external_ref"] == "a1#0/turn_close"


def _outcome_root():
    return [
        prompt("u1", 1, "p1", "go"),
        assistant(
            "a1",
            2,
            "m1",
            [
                tool_use_block("tb", "Bash", {}),
                tool_use_block("tp", "Bash", {}),
                tool_use_block("ti", "Bash", {}),
                tool_use_block("te", "Bash", {}),
                tool_use_block("ts", "Bash", {}),
                tool_use_block("tx", "Bash", {}),
            ],
        ),  # fmt: skip
        hook("h1", 2.1, "PreToolUse:Bash", tool_use_id="tb", exit_code=2),
        tool_result("rb", 2.2, "tb", "denied", pid="p1", is_error=True, tur={"interrupted": True}),
        tool_result("rp", 2.3, "tp", "fine", pid="p1", tur={"stdout": "fine", "interrupted": False}),
        hook("h2", 2.4, "PostToolUse:Bash", tool_use_id="tp", exit_code=2),
        tool_result("ri", 2.5, "ti", "", pid="p1", tur={"interrupted": True}),
        tool_result("re", 2.6, "te", "boom", pid="p1", is_error=True),
        tool_result("rs", 2.7, "ts", "ok", pid="p1", tur=["not", "a", "dict"]),
        prompt("u2", 5, "p2", "next"),
    ]


def test_tool_call_outcome_precedence() -> None:
    rows, _ = build(_outcome_root())
    closes = {r["entity_ref"]: r for r in by(rows, observation_type="tool_call", event_kind="close")}
    assert {t: c["outcome"] for t, c in closes.items()} == {
        "tb": "blocked", "tp": "success", "ti": "interrupted", "te": "error", "ts": "success", "tx": "interrupted",
    }  # fmt: skip
    assert json.loads(closes["tx"]["metadata"]) == {"synthetic": True}
    assert closes["tx"]["external_ref"] == "a1#5/tool_call_close" and closes["tx"]["source_ordinal"] == 1
    assert json.loads(closes["tb"]["metadata"])["is_error"] is True


def test_sentinels_are_used_when_pinned(monkeypatch) -> None:
    monkeypatch.setattr(observations, "HARNESS_DENIAL_PREFIXES", ("DENIED:",))
    monkeypatch.setattr(observations, "HARNESS_INTERRUPT_SENTINELS", ("STOPPED",))
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {}), tool_use_block("t2", "Bash", {})]),
        tool_result("r1", 3, "t1", "DENIED: by policy", pid="p1", is_error=True),
        tool_result("r2", 3.1, "t2", "STOPPED", pid="p1", is_error=True),
    ]
    stream = parse_records(root).streams[ROOT]
    turn = stream.turns[0]
    assert [outcome_of(use.result, stream) for use in turn.tool_uses] == ["blocked", "interrupted"]


def test_every_hook_attachment_is_one_process_event() -> None:
    root = [
        hook("h0", 0.5, "SessionStart:startup", exit_code=None, command="bash .claude/hooks/session_start.sh --x"),
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})]),
        hook(
            "h1",
            2.1,
            "PostToolUse:Bash",
            tool_use_id="t1",
            command="python /abs/path/never_on_main.py",
            stderr="e" * 600,
            durationMs=12,
        ),
        hook("h2", 2.2, "PreToolUse:Bash", tool_use_id="unknown-tool", exit_code=1, a_type="hook_additional_context"),
        {**hook("h3", 2.3, "Stop", command="echo no script"), "attachment": {"type": "hook_success", "exitCode": "two"}},
        prompt("u2", 4, "p2", "next"),
        hook("h4", 5, "UserPromptSubmit"),
    ]
    rows, _ = build(root)
    events = {r["external_ref"]: r for r in by(rows, observation_type="process_event")}
    assert sorted(events) == [f"h{n}#0/process_event" for n in range(5)]
    first = events["h0#0/process_event"]
    assert (first["name"], first["severity"], first["parent_observation_ref"], first["entity_ref"]) == (
        "hook:session_start", "info", None, "h0#0/process_event",
    )  # fmt: skip
    post = events["h1#0/process_event"]
    assert (post["name"], post["parent_observation_ref"]) == ("hook:never_on_main", "t1")
    meta = json.loads(post["metadata"])
    assert (
        len(meta["stderr_head"]) == 512
        and meta["duration_ms"] == 12
        and meta["exit_code"] == 0
        and meta["hook_event"] == "PostToolUse"
    )
    other = events["h2#0/process_event"]
    assert (other["name"], other["severity"], other["parent_observation_ref"]) == (
        "hook:PreToolUse.Bash",
        "warning",
        f"{SID}/p1",
    )
    odd = events["h3#0/process_event"]
    assert odd["name"] == "hook:unknown" and odd["severity"] == "warning" and json.loads(odd["metadata"])["exit_code"] is None
    assert events["h4#0/process_event"]["parent_observation_ref"] == f"{SID}/p2"
    live, _ = build(root, final=False)
    assert not by(live, external_ref="h4#0/process_event") and by(live, external_ref="h0#0/process_event")


def test_hook_name_fallbacks() -> None:
    assert hook_name({"command": "python -m tool.mod", "hookName": "Stop"}) == "hook:Stop"
    assert hook_name({"command": "run /x/y/gate.sh now", "hookName": "Stop"}) == "hook:gate"
    assert hook_name({"hookName": "SessionStart:resume"}) == "hook:SessionStart.resume"
    assert hook_name({}) == "hook:unknown" and hook_name({"hookName": ""}) == "hook:unknown"


def test_tool_call_open_and_close_columns() -> None:
    block = {**tool_use_block("t1", "mcp__x__y", {"a": 1}), "caller": {"type": "direct"}}
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [block], attributionMcpServer="x"),
        tool_result(
            "r1",
            3,
            "t1",
            "ok",
            pid="p1",
            tur={
                "persistedOutputPath": "C:\\tmp\\tool-results\\o.txt",
                "persistedOutputSize": 9,
                "agentId": "ag",
                "isAsync": True,
                "status": "s",
            },
        ),
    ]
    rows, _ = build(root)
    opened = by(rows, observation_type="tool_call", event_kind="open")[0]
    assert (opened["name"], opened["sequence"], opened["model"], opened["parent_observation_ref"]) == (
        "mcp__x__y",
        1,
        "claude-test-1",
        f"{SID}/p1",
    )
    assert json.loads(opened["metadata"]) == {"attribution_mcp_server": "x", "caller_type": "direct"}
    closed = by(rows, observation_type="tool_call", event_kind="close")[0]
    assert json.loads(closed["metadata"]) == {
        "agent_id": "ag", "interrupted": None, "is_async": True, "is_error": False,
        "persisted_output": "o.txt", "persisted_output_size": 9, "status": "s",
    }  # fmt: skip


def test_open_turns_emit_nothing_and_orphans_and_late_results_are_handled() -> None:
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})]),
        tool_result("r0", 2.5, "ghost", "orphan", pid="p1", is_error=True),
        prompt("u2", 3, "p2", "next"),
        assistant("a2", 4, "m2", [tool_use_block("t2", "Bash", {})]),
        attachment("q", 4.5, "date"),
        hook("h9", 4.6, "PostToolUse:Bash", tool_use_id="t2"),
    ]
    rows, diag = build(root, final=False)
    assert not by(rows, external_ref="a2#0/tool_call_open") and not by(rows, external_ref="h9#0/process_event")
    orphan = by(rows, entity_ref="ghost")[0]
    assert orphan["name"] is None and orphan["sequence"] is None and orphan["outcome"] == "error"
    assert diag["orphan_tool_results"] == 0  # counted at parse time, not by the builder
    closed_all, _ = build(root, final=True)
    assert by(closed_all, external_ref="a2#0/tool_call_close")[0]["outcome"] == "interrupted"
    assert by(closed_all, external_ref="h9#0/process_event")[0]["parent_observation_ref"] == "t2"
