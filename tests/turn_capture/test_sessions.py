"""Session and agent rows: open marker, workflow, sub-agent completeness, registered agent_type, no meta.json reads."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.turn_capture.record_turn import record_turn
from src.turn_capture.sessions import AGENT_TYPE, WORKFLOWS, build_agents, build_sessions
from src.turn_capture.transcript import MemTree
from tests.fixtures.turn_capture_corpus import (
    PROJECT_REF,
    SID,
    assistant,
    attachment,
    build_secret,
    child,
    hook,
    make_ctx,
    make_files,
    parse_records,
    prompt,
    rows_of,
    text_block,
    tool_result,
    tool_use_block,
)

REGISTRY = Path(__file__).resolve().parents[2] / "config" / "agent" / "data_quality" / "source_registry.yaml"


def sessions(root, children=None, final=True):
    return rows_of(build_sessions(parse_records(root, children, final), make_ctx()))


def agents(root, children=None, final=True):
    return rows_of(build_agents(parse_records(root, children, final), make_ctx()))


def by(rows, **match):
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def cmd(name: str) -> str:
    return f"<command-name>/{name}</command-name>\n<command-message>{name}</command-message>"


def test_open_marker_workflow_branch_and_model() -> None:
    for name in WORKFLOWS:
        rows = sessions([prompt("u1", 1, "p1", cmd(name)), assistant("a1", 2, "m1", [text_block("x")])])
        assert by(rows, event_kind="open")[0]["workflow"] == name
    rows = sessions(
        [
            {"type": "last-prompt"},
            prompt("u1", 1, "p1", [text_block("/plan is not markup")], gitBranch=""),
            assistant("a1", 2, "m1", [text_block("x")], model="claude-a", gitBranch="claude/first"),
            prompt("u2", 3, "p2", "next", gitBranch="claude/later"),
            assistant("a2", 4, "m2", [text_block("y")], model="claude-b"),
        ]
    )
    marker = by(rows, event_kind="open")[0]
    assert marker["workflow"] == "claude_code" and marker["branch"] == "claude/first" and marker["model_primary"] == "claude-a"
    assert (marker["external_ref"], marker["entity_ref"], marker["execution_attempt"]) == (f"{SID}#0/open", SID, 1)
    assert (
        marker["source_ordinal"] == 1
        and marker["parent_session_ref"] is None
        and marker["event_timestamp"] == marker["session_started_at"]
    )
    assert (
        by(sessions([prompt("u1", 1, "p1", cmd("model")), assistant("a1", 2, "m1", [text_block("x")])]), event_kind="open")[0][
            "workflow"
        ]
        == "claude_code"
    )


def test_open_waits_for_a_closed_turn_with_an_assistant() -> None:
    lone = [prompt("u1", 1, "p1", "a"), assistant("a1", 2, "m1", [text_block("x")])]
    assert sessions(lone, final=False) == []
    assert [r["event_kind"] for r in sessions(lone, final=True)] == ["open", "close"]
    two = lone + [prompt("u2", 3, "p2", "b")]
    assert [r["event_kind"] for r in sessions(two, final=False)] == ["open"]
    no_reply = [prompt("u1", 1, "p1", "a", gitBranch="claude/only"), prompt("u2", 3, "p2", "b")]
    assert sessions(no_reply, final=False) == [] and sessions(no_reply, final=True) == []
    assert sessions([{"type": "queue-operation", "timestamp": "2026-01-01T00:00:00.000Z"}], final=True) == []
    assert sessions([prompt("u1", 1, "p1", "a")], final=True) == []


def test_open_row_model_is_bounded_to_the_open_bound_and_skips_api_errors() -> None:
    error = assistant(
        "a1", 2, "00000000-0000-4000-8000-0000000000e1", [text_block("API Error")], model="<synthetic>", isApiErrorMessage=True
    )
    root = [
        prompt("u1", 1, "p1", "a"),
        error,
        prompt("u2", 3, "p2", "b"),
        assistant("a2", 4, "m2", [text_block("y")], model="later"),
    ]
    rows = sessions(root, final=False)
    assert "model_primary" not in by(rows, event_kind="open")[0]
    assert sessions(root + [prompt("u3", 5, "p3", "c")], final=False)[0].get("model_primary") is None


def test_open_row_without_any_branch_omits_it() -> None:
    root = [
        prompt("u1", 1, "p1", "a", gitBranch=""),
        assistant("a1", 2, "m1", [text_block("x")], gitBranch=""),
        prompt("u2", 3, "p2", "b", gitBranch=""),
    ]
    assert "branch" not in by(sessions(root, final=False), event_kind="open")[0]


def test_close_row_per_finalization_with_transcript_outcome() -> None:
    def close(root, final=True):
        return by(sessions(root, final=final), event_kind="close")

    done = [prompt("u1", 1, "p1", "a"), assistant("a1", 2, "m1", [text_block("x")]), {"type": "last-prompt"}]
    (row,) = close(done)
    assert (row["external_ref"], row["entity_ref"], row["outcome"], row["source_ordinal"]) == ("a1#0/close", SID, "success", 1)
    assert row["event_timestamp"] != row["session_started_at"] and "failure_reason" not in row
    assert close(done, final=False) == []
    anchor = done[:2] + [{"type": "queue-operation", "uuid": "q9", "timestamp": "2026-01-01T00:00:09.000Z"}]
    assert close(anchor)[0]["external_ref"] == "q9#0/close"
    unparseable = done[:2] + [
        {"type": "queue-operation", "uuid": "q9", "timestamp": "not a time"},
        {"uuid": "", "timestamp": "x"},
    ]
    assert close(unparseable)[0]["external_ref"] == "a1#0/close"
    sentinel = done[:2] + [prompt("u2", 3, "p2", [text_block("[Request interrupted by user]")])]
    assert close(sentinel)[0]["outcome"] == "cancelled"
    aborted = done[:2] + [prompt("u2", 3, "p2", "b"), assistant("a2", 4, "m2", [text_block("p")], isAbortedMidStream=True)]
    assert close(aborted)[0]["outcome"] == "cancelled"
    rejected = [
        prompt("u1", 1, "p1", "a"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})]),
        tool_result("r1", 3, "t1", "no", pid="p1", is_error=True, tur="x", toolDenialKind="user-rejected"),
    ]
    assert close(rejected)[0]["outcome"] == "cancelled"
    flagged = rejected[:2] + [tool_result("r1", 3, "t1", "no", pid="p1", tur={"interrupted": True})]
    assert close(flagged)[0]["outcome"] == "cancelled"
    pending = rejected[:2]
    assert close(pending)[0]["outcome"] == "cancelled"
    denied = rejected[:2] + [
        tool_result("r1", 3, "t1", "no", pid="p1", is_error=True, tur="x", toolDenialKind="permission-rule"),
        assistant("a2", 4, "m2", [text_block("fine")]),
    ]
    assert close(denied)[0]["outcome"] == "success"
    error = assistant("a3", 5, "mx", [text_block("boom")], model="<synthetic>", isApiErrorMessage=True, error="server_error")
    failed = close(done[:2] + [prompt("u2", 3, "p2", "b"), error])[0]
    assert (failed["outcome"], failed["failure_reason"]) == ("failed", "server_error")
    odd = {**error, "error": "Has Spaces"}
    assert "failure_reason" not in close(done[:2] + [prompt("u2", 3, "p2", "b"), odd])[0]
    assert close(done, final=True)[0]["outcome"] == "success"
    kid = sessions(_sync_root(), {"ag1": _child()})
    assert [r["entity_ref"] for r in by(kid, event_kind="close")] == [SID]


def test_open_row_waits_for_an_assistant_reply_in_a_subagent() -> None:
    silent = [child(prompt("c1", 2.5, "p1", "t"), "ag1")]
    assert by(sessions(_sync_root(), {"ag1": silent}), entity_ref=f"{SID}:ag1") == []


def test_resume_and_compact_rows_wait_for_the_open_marker() -> None:
    root = [
        prompt("u1", 1, "p1", "a"),
        hook("rs", 1.5, "SessionStart:resume"),
        assistant("a1", 2, "m1", [text_block("x")]),
        hook("c1", 3, "PreCompact"),
        hook("c2", 3.1, "PostCompact"),
        prompt("u2", 4, "p2", "b"),
    ]
    assert sessions(root, final=False) == []
    live = sessions(root + [assistant("a2", 5, "m2", [text_block("y")]), prompt("u3", 6, "p3", "c")], final=False)
    assert [(r["event_kind"], r["execution_attempt"]) for r in live] == [("open", 1), ("resume", 2), ("compact", None)]
    assert live[1]["external_ref"] == "rs#0/resume" and live[2]["external_ref"] == "c1#0/compact"


def _sync_root(name="Agent", tur=None, is_error=None, content="child done", bg=False, notify=None):
    tur = tur if tur is not None else {"agentId": "ag1", "status": "completed", "isAsync": bg}
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant(
            "a1",
            2,
            "m1",
            [tool_use_block("tuA", name, {"subagent_type": "Explore", "run_in_background": bg})],
            version="2.9.9",
        ),
        tool_result("r1", 3, "tuA", content, pid="p1", is_error=is_error, tur=tur),
    ]
    if notify:
        root.append(
            attachment("n1", 4, "queued_command", prompt="<task-notification>\n<task-id>ag1</task-id>\n</task-notification>")
        )
    return root


def _child():
    return [
        child(prompt("c1", 2.5, "p1", "t", gitBranch="claude/child"), "ag1"),
        child(assistant("c2", 3, "mc", [text_block("w")], model="claude-c"), "ag1"),
    ]


def test_subagent_session_and_agent_rows() -> None:
    tree = parse_records(_sync_root(), {"ag1": _child()})
    rows = rows_of(build_sessions(tree, make_ctx()))
    kid = by(rows, entity_ref=f"{SID}:ag1")[0]
    assert (kid["external_ref"], kid["workflow"], kid["parent_session_ref"], kid["source_ordinal"]) == (
        f"{SID}:ag1#0/open",
        "subagent",
        SID,
        0,
    )
    assert (
        kid["event_timestamp"] == kid["session_started_at"]
        and kid["branch"] == "claude/child"
        and kid["model_primary"] == "claude-c"
    )
    opened, closed = rows_of(build_agents(tree, make_ctx()))
    assert (opened["event_kind"], opened["external_ref"], opened["entity_ref"], opened["observation_ref"]) == (
        "open",
        "a1#0/agent_open",
        "tuA",
        "tuA",
    )
    assert (opened["session_ref"], opened["agent_type"], opened["agent_name"], opened["model"]) == (
        f"{SID}:ag1",
        AGENT_TYPE,
        "Explore",
        "claude-c",
    )
    assert (opened["trigger"], opened["version"], opened["provider"], opened["outcome"]) == (
        "subagent_sync",
        "2.9.9",
        None,
        None,
    )
    assert (closed["event_kind"], closed["external_ref"], closed["outcome"], closed["error"]) == (
        "close",
        "r1#0/agent_close",
        "success",
        None,
    )


def test_agent_error_scrubbed_before_truncation() -> None:
    secret = build_secret("aws_access")
    row = agents(_sync_root(is_error=True, content="x" * 1989 + " " + secret), {"ag1": _child()})[1]
    assert "AKIA" not in row["error"] and secret[:8] not in row["error"]


def test_agent_close_outcomes_and_background_rules() -> None:
    failed = agents(_sync_root(is_error=True, content="x" * 3000 + " " + "AKIA" + "ABCDEFGHIJKLMNOP"), {"ag1": _child()})[1]
    assert failed["outcome"] == "failed" and len(failed["error"]) == 2000
    interrupted = agents(_sync_root(tur={"agentId": "ag1", "isAsync": False, "interrupted": True}), {"ag1": _child()})[1]
    assert interrupted["outcome"] == "failed" and interrupted["error"] is None
    waiting = agents(_sync_root(bg=True), {"ag1": _child()}, final=False)
    assert waiting == []
    finished = agents(_sync_root(bg=True), {"ag1": _child()}, final=True)
    assert [r["event_kind"] for r in finished] == ["open"] and finished[0]["trigger"] == "subagent_background"
    done = agents(_sync_root(bg=True, notify=True), {"ag1": _child()}, final=False)
    assert [(r["event_kind"], r["outcome"]) for r in done] == [("open", None), ("close", "success")]
    assert done[1]["external_ref"] == "n1#0/agent_close"
    bare = _sync_root()
    bare[1] = assistant("a1", 2, "m1", [{"type": "tool_use", "id": "tuA", "name": "Agent", "input": "raw"}])
    row = agents(bare, {"ag1": _child()})[0]
    assert row["agent_name"] is None and row["version"] == "2.1.0"
    assert agents(_sync_root(), None) == []


def test_agent_type_is_registered_source() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    ids = {entry["canonical_id"] for entry in registry["entries"]}
    assert AGENT_TYPE in ids
    assert {r["agent_type"] for r in agents(_sync_root(), {"ag1": _child()})} == {AGENT_TYPE}


def test_agent_rows_do_not_depend_on_meta_json() -> None:
    files = make_files(_sync_root(), {"ag1": _child()})
    with_meta = dict(files)
    with_meta[f"{SID}/subagents/agent-ag1.meta.json"] = (
        '{"agentType": "SomethingElse", "toolUseId": "other", "requestShape": "background"}'
    )
    plain = record_turn(MemTree(files), None, project_ref=PROJECT_REF, session_final=True)
    meta = record_turn(MemTree(with_meta), None, project_ref=PROJECT_REF, session_final=True)
    assert plain.agents == meta.agents and plain.sessions == meta.sessions and len(plain.agents) == 2
