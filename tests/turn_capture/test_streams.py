"""Classification, companion exclusion, stream membership, turn spans and closure, response grouping, completeness."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.turn_capture import streams
from src.turn_capture.streams import ROOT, classify, emitting_streams, is_background_completion, parse_tree
from src.turn_capture.transcript import FsTree, MemTree
from tests.fixtures.turn_capture_corpus import (
    SID,
    assistant,
    attachment,
    child,
    hook,
    make_files,
    prompt,
    text_block,
    tool_result,
    tool_use_block,
)


def parsed(root, children=None, final=False):
    return parse_tree(MemTree(make_files(root, children)), None, final)


def test_companion_records_never_open_a_turn() -> None:
    root = [
        prompt("c0", 0.5, "p0", "injected", sourceToolUseID="tuX"),
        {**prompt("c1", 0.6, "p0", [text_block("x")]), "turnCompanion": True},
        prompt("u1", 1, "p1", "real"),
        prompt("c2", 1.5, "p9", "companion after", sourceToolUseID="tuY"),
        assistant("a1", 2, "m1", [text_block("ok")]),
    ]
    tree = parsed(root, final=True)
    turns = tree.streams[ROOT].turns
    assert [t.prompt_id for t in turns] == ["p1"]
    assert [r.uuid for r in turns[0].companions] == ["c2"]


def test_classification_branches() -> None:
    diag: Counter[str] = Counter()
    ok = {"uuid": "u", "timestamp": "2026-01-01T00:00:00.000Z"}
    cases = {
        "other": [{"type": "mode"}, {"type": "weird", "uuid": "u"}, {"type": "user"}, {"type": "user", "uuid": "u"}],
        "prompt": [{**ok, "type": "user", "promptId": "p", "message": {"content": "x"}}],
        "companion": [{**ok, "type": "user", "promptId": "p", "sourceToolUseID": "s", "message": {"content": "x"}}],
        "tool_result": [{**ok, "type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t"}]}}],
        "assistant": [{**ok, "type": "assistant", "message": {"id": "m", "content": []}}],
        "hook": [{**ok, "type": "attachment", "attachment": {"type": "hook_success"}}],
        "attach": [
            {**ok, "type": "attachment", "attachment": {"type": "date"}},
            {**ok, "type": "attachment", "attachment": {"type": "new_kind"}},
        ],
    }
    for kind, records in cases.items():
        assert {classify(r, diag) for r in records} == {kind}, kind
    assert classify({**ok, "type": "user", "message": {"content": 5}, "promptId": "p"}, diag) == "other"
    assert classify({**ok, "type": "user", "message": {"content": "x"}}, diag) == "other"
    assert classify({**ok, "type": "assistant", "message": {"id": "", "content": []}}, diag) == "other"
    assert classify({**ok, "type": "attachment"}, diag) == "attach"
    assert diag["records_without_uuid"] == 1 and diag["records_without_timestamp"] == 1
    assert diag["unknown_record_type:weird"] == 1 and diag["unknown_attachment_type:new_kind"] == 1
    assert diag["unclassified_user_records"] == 2 and diag["unclassified_assistant_records"] == 1


def test_turn_spans_boundaries_and_closure() -> None:
    root = [
        prompt("u1", 1, "p1", "a"),
        prompt("u1b", 1.5, "p1", "same turn again"),
        assistant("a1", 2, "m1", [text_block("x")]),
        prompt("u2", 3, "p2", "b"),
        assistant("a2", 4, "m2", [text_block("y")]),
    ]
    open_tree = parsed(root)
    turns = open_tree.streams[ROOT].turns
    assert [(t.prompt_id, t.closed, len(t.prompts)) for t in turns] == [("p1", True, 2), ("p2", False, 1)]
    assert turns[0].last_assistant.uuid == "a1" and turns[0].ordinal == 1 and turns[1].ordinal == 2
    assert parsed(root, final=True).streams[ROOT].turns[1].closed is True


def test_resume_boundary_ends_a_turn_and_reused_prompt_id_is_a_companion() -> None:
    root = [
        hook("rs0", 0.5, "SessionStart:resume"),
        prompt("u1", 1, "p1", "a"),
        assistant("a1", 2, "m1", [text_block("x")]),
        hook("rs1", 3, "SessionStart:resume"),
        hook("rs2", 3.1, "SessionStart:resume"),
        assistant("a-pre", 3.5, "mpre", [text_block("pre-turn")]),
        prompt("u2", 4, "p1", "reuses the old id"),
        prompt("u3", 5, "p2", "new"),
        prompt("u4", 6, "p1", "old id again inside p2"),
    ]
    tree = parsed(root)
    stream = tree.streams[ROOT]
    assert [r.uuid for r in stream.resumes] == ["rs0", "rs1"]
    assert [(t.prompt_id, t.closed) for t in stream.turns] == [("p1", True), ("p2", False)]
    assert tree.diag["reused_prompt_ids"] == 2 and tree.diag["pre_turn_assistant_records"] == 1
    assert [r.uuid for r in stream.turns[1].companions] == ["u4"]


def test_compact_group_is_one_record() -> None:
    root = [
        prompt("u1", 1, "p1", "a"),
        assistant("a1", 2, "m1", [text_block("x")]),
        hook("cp1", 3, "PreCompact"),
        hook("cp2", 3.1, "SessionStart:compact"),
        hook("cp3", 3.2, "PostCompact"),
        prompt("u2", 4, "p2", "b"),
        assistant("a2", 5, "m2", [text_block("y")]),
        hook("cp4", 6, "PreCompact"),
        hook("plain", 6.1, "PostToolUse:Bash"),
    ]
    stream = parsed(root).streams[ROOT]
    assert [r.uuid for r in stream.compacts] == ["cp1", "cp4"] and len(stream.hooks) == 5


def test_tools_results_and_responses() -> None:
    root = [
        assistant("pre", 0.5, "mpre", [tool_use_block("tuPre", "Bash", {})]),
        tool_result("rpre", 0.6, "tuPre", "outside"),
        prompt("u1", 1, "p1", "a"),
        assistant(
            "a1", 2, "m1", [tool_use_block("tu1", "Bash", {}), {"type": "text"}, "junk", tool_use_block("tu1", "Bash", {})]
        ),
        tool_result("r1", 3, "tu1", "one", pid="p1"),
        tool_result("r1b", 3.1, "tu1", "dup", pid="p1"),
        {
            **tool_result("rx", 3.2, "tuX", "orphan"),
            "message": {"content": [{"type": "tool_result", "tool_use_id": "tuX"}, {"type": "tool_result"}, 5]},
        },
        hook("h1", 3.3, "PreToolUse:Bash", tool_use_id="tu2", exit_code=2),
        hook("h2", 3.4, "PreToolUse:Bash", tool_use_id="tu2", exit_code=0),
        assistant("a2", 4, "m1", [tool_use_block("tu2", "Bash", {})]),
        prompt("u2", 5, "p2", "b"),
        assistant("a3", 6, "m1", [{"type": "text", "text": "same id, later turn"}]),
        tool_result("rl", 7, "tu2", "late", pid="p2"),
    ]
    tree = parsed(root, final=True)
    stream = tree.streams[ROOT]
    turn1, turn2 = stream.turns
    assert [u.tool_id for u in turn1.tool_uses] == ["tu1", "tu2"] and [u.ordinal for u in turn1.tool_uses] == [1, 2]
    assert turn1.tool_uses[0].result.rec.uuid == "r1" and turn1.tool_uses[1].result is None
    assert [r.tool_use_id for r in turn1.orphan_results] == ["tuX"]
    assert [(r.message_id, len(r.recs), r.owner.uuid) for r in turn1.responses] == [("m1", 2, "a2")]
    assert [(r.message_id, r.owner.uuid) for r in turn2.responses] == [("m1", "a3")]
    assert stream.result_by_id["tuPre"].disposition == "outside"
    assert stream.result_by_id["tu2"].disposition == "late"
    assert stream.pre_tool_blocks == {"tu2": [stream.recs[7].line]}
    for key in (
        "duplicate_tool_uses",
        "duplicate_tool_results",
        "results_outside_turn",
        "late_tool_results",
        "orphan_tool_results",
    ):
        assert tree.diag[key] >= 1, key


def _spawn_root(agent: str, *, bg: bool, notify: bool, name: str = "Agent") -> list[dict]:
    tur = {"agentId": agent, "isAsync": bg, "status": "async_launched" if bg else "completed"}
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("tuA", name, {"subagent_type": "Explore"})]),
        tool_result("r1", 3, "tuA", "x", pid="p1", tur=tur),
    ]
    if notify:
        root.append(attachment("n0", 3.5, "queued_command", prompt="unrelated"))
        root.append(
            attachment(
                "n1", 4, "queued_command", prompt=f"<task-notification>\n<task-id>{agent}</task-id>\n</task-notification>"
            )
        )
    return root


def _kid(agent: str) -> list[dict]:
    return [child(prompt("c1", 2.5, "p1", "t"), agent), child(assistant("c2", 3.5, "mc", [text_block("w")]), agent)]


def test_subagent_completeness_sync_and_background() -> None:
    sync = parsed(_spawn_root("s1", bg=False, notify=False), {"s1": _kid("s1")})
    assert sync.spawns[0].complete and sync.spawns[0].close_result is not None
    assert sync.streams["s1"].session_ref == f"{SID}:s1" and sync.streams["s1"].turns[0].closed
    assert [s.key for s in emitting_streams(sync)] == [ROOT, "s1"]
    waiting = parsed(_spawn_root("b1", bg=True, notify=False), {"b1": _kid("b1")})
    assert not waiting.spawns[0].complete and waiting.spawns[0].close_rec is None
    assert waiting.streams["b1"].turns[0].closed is False
    assert [s.key for s in emitting_streams(waiting)] == [ROOT]
    finished = parsed(_spawn_root("b1", bg=True, notify=False), {"b1": _kid("b1")}, final=True)
    assert [s.key for s in emitting_streams(finished)] == [ROOT, "b1"] and finished.streams["b1"].turns[0].closed
    done = parsed(_spawn_root("b1", bg=True, notify=True), {"b1": _kid("b1")})
    assert done.spawns[0].complete and done.spawns[0].close_rec.uuid == "n1" and done.streams["b1"].turns[0].closed


def test_spawn_edge_cases() -> None:
    task = parsed(_spawn_root("t1", bg=False, notify=False, name="Task"), {"t1": _kid("t1")})
    assert len(task.spawns) == 1
    other_tool = parsed(_spawn_root("t1", bg=False, notify=False, name="Bash"), {"t1": _kid("t1")})
    assert other_tool.spawns == [] and other_tool.diag["orphan_subagents"] == 1
    missing = parsed(_spawn_root("gone", bg=False, notify=False))
    assert missing.diag["missing_child_files"] == 1 and missing.spawns == []
    root = _spawn_root("d1", bg=False, notify=False)
    root[1] = assistant("a1", 2, "m1", [tool_use_block("tuA", "Agent", {}), tool_use_block("tuB", "Agent", {})])
    root.append(tool_result("r2", 3.5, "tuB", "x", pid="p1", tur={"agentId": "d1", "isAsync": False}))
    dup = parsed(root, {"d1": _kid("d1")})
    assert len(dup.spawns) == 1 and dup.diag["duplicate_spawns"] == 1
    no_id = _spawn_root("z", bg=False, notify=False)
    no_id[2] = tool_result("r1", 3, "tuA", "x", pid="p1", tur={"status": "completed"})
    assert parsed(no_id).spawns == []


def test_nested_spawns_are_found_in_the_child_stream() -> None:
    nested = _kid("n1") + [
        child(assistant("c3", 3.6, "mc2", [tool_use_block("tuB", "Task", {})]), "n1"),
        child(tool_result("c4", 3.7, "tuB", "x", pid="p1", tur={"agentId": "n2", "isAsync": False}), "n1"),
    ]
    grand = [child(prompt("g1", 3.65, "p1", "t"), "n2")]
    tree = parsed(_spawn_root("n1", bg=False, notify=False), {"n1": nested, "n2": grand})
    assert [s.agent_id for s in tree.spawns] == ["n1", "n2"] and tree.spawns[1].parent == "n1"
    assert tree.streams["n2"].session_ref == f"{SID}:n2"


def test_background_completion_predicate() -> None:
    def rec_of(record: dict) -> streams.Rec:
        tree = parsed([prompt("u0", 0.1, "p0", "x"), record])
        return tree.streams[ROOT].recs[-1]

    text = "<task-notification>\n<task-id>ag</task-id>\n</task-notification>"
    assert is_background_completion(rec_of(attachment("q", 1, "queued_command", prompt=text)), "ag")
    assert not is_background_completion(rec_of(attachment("q", 1, "queued_command", prompt=text)), "other")
    assert is_background_completion(rec_of(prompt("q", 1, "p0", text)), "ag")
    assert not is_background_completion(rec_of(prompt("q", 1, "p0", "hello")), "ag")
    assert not is_background_completion(rec_of(attachment("q", 1, "queued_command", prompt=5)), "ag")
    assert not is_background_completion(rec_of(attachment("q", 1, "date")), "ag")
    assert not is_background_completion(rec_of(assistant("q", 1, "m", [text_block("x")])), "ag")


def test_missing_files_and_malformed_lines(tmp_path: Path) -> None:
    assert parse_tree(FsTree(tmp_path / "nope.jsonl"), None, True).streams == {}
    files = make_files([prompt("u1", 1, "p1", "a")])
    files[f"{SID}.jsonl"] += "not json\n"
    assert parse_tree(MemTree(files), None, False).diag["malformed_lines"] == 1

    class Tree:
        session_id = SID

        def agent_ids(self):
            return ["ghost"]

        def read(self, key):
            return MemTree(_spawn_files).read(key)

        def sidecar(self, name):
            return None

    _spawn_files = make_files(_spawn_root("ghost", bg=False, notify=False))
    tree = parse_tree(Tree(), None, True)
    assert len(tree.spawns) == 1 and "ghost" not in tree.streams


def test_limits_truncate_each_file() -> None:
    tree = MemTree(make_files(_spawn_root("s1", bg=False, notify=False), {"s1": _kid("s1")}))
    cut = parse_tree(tree, {ROOT: 2}, False)
    assert len(cut.streams[ROOT].recs) == 2 and cut.spawns == [] and cut.lines_total == {ROOT: 2}
    assert parse_tree(tree, {}, False).streams[ROOT].recs == []
