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


def test_open_waits_for_a_closed_turn_with_an_assistant_or_finalize() -> None:
    lone = [prompt("u1", 1, "p1", "a"), assistant("a1", 2, "m1", [text_block("x")])]
    assert sessions(lone, final=False) == []
    assert len(sessions(lone, final=True)) == 1
    two = lone + [prompt("u2", 3, "p2", "b")]
    assert len(sessions(two, final=False)) == 1
    no_reply = [prompt("u1", 1, "p1", "a", gitBranch="claude/only"), prompt("u2", 3, "p2", "b")]
    assert sessions(no_reply, final=False) == []
    final_open = sessions(no_reply, final=True)[0]
    assert final_open["model_primary"] is None and final_open["branch"] == "claude/only"
    assert (
        sessions([{"type": "queue-operation", "timestamp": "2026-01-01T00:00:00.000Z"}], final=True)[0]["workflow"]
        == "claude_code"
    )
    no_pin_line = sessions([prompt("u1", 1, "p1", "a")], final=True)[0]
    assert no_pin_line["source_ordinal"] == 0 and no_pin_line["branch"] == "claude/test"


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
