"""Source rules: line rules, the pin and deferral, sidecar resolution, sub-agent file lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.turn_capture.record_turn import record_turn
from src.turn_capture.transcript import ROOT, FsTree, MemTree, read_lines, record_time, session_pin
from tests.fixtures.turn_capture_corpus import (
    PROJECT_REF,
    SID,
    assistant,
    child,
    jsonl,
    make_files,
    prompt,
    queue_op,
    text_block,
    tool_result,
    tool_use_block,
    ts,
)


def test_pin_is_first_parseable_timestamp_in_root_file_order() -> None:
    body = jsonl([{"type": "last-prompt"}, {"type": "x", "timestamp": "not a time"}, queue_op(5), prompt("u1", 1, "p1", "hi")])
    pin = session_pin(read_lines(body.encode()))
    assert pin is not None and pin.isoformat().startswith("2026-01-01T00:00:05")
    assert session_pin(read_lines(b'[1]\n{"timestamp": "2026-01-01T00:00:09Z"}\n')) is not None


def test_no_timestamp_defers() -> None:
    files = make_files([{"type": "last-prompt", "sessionId": SID}, {"type": "mode"}])
    result = record_turn(MemTree(files), None, project_ref=PROJECT_REF)
    assert result.next_cursor is None
    assert result.batches[-1][1] == [] and all(rows == [] for _, rows in result.batches)
    assert session_pin(read_lines(b"")) is None


def test_trailing_partial_line_not_consumed() -> None:
    data = jsonl([prompt("u1", 1, "p1", "hi")]).encode() + b'{"type": "user", "uu'
    lines = read_lines(data)
    assert [item.line for item in lines] == [0]
    assert (
        read_lines(b'{"a": 1}\n{"b": 2}\n', limit=1)[0].data == {"a": 1}
        and len(read_lines(b'{"a": 1}\n{"b": 2}\n', limit=1)) == 1
    )


def test_malformed_and_non_object_lines_are_consumed_but_never_records() -> None:
    lines = read_lines(b'garbage\n[1, 2]\n{"ok": true}\n\xff\xfe\n')
    assert [item.data for item in lines] == [None, None, {"ok": True}, None]


def test_record_time_rules() -> None:
    assert record_time({"timestamp": ts(1)}) is not None
    assert record_time({"timestamp": 12}) is None
    assert record_time({"timestamp": "yesterday"}) is None
    assert record_time({}) is None


def test_sidecar_resolved_by_basename_under_session_dir(tmp_path: Path) -> None:
    files = make_files([prompt("u1", 1, "p1", "hi")], sidecars={"out.txt": "FULL"})
    mem = MemTree(files)
    assert mem.sidecar("out.txt") == b"FULL" and mem.sidecar("nope.txt") is None
    for rel, body in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    fs = FsTree(tmp_path / f"{SID}.jsonl")
    assert fs.session_id == SID
    assert fs.sidecar("out.txt") == b"FULL" and fs.sidecar("nope.txt") is None
    assert fs.sidecar("../out.txt") is None


def test_subagent_file_lookup_by_agent_id(tmp_path: Path) -> None:
    files = make_files(
        [prompt("u1", 1, "p1", "hi")],
        {"b2": [child(assistant("c1", 2, "m", [text_block("x")]), "b2")], "a1": [child(prompt("c0", 2, "p1", "t"), "a1")]},
    )
    mem = MemTree(files)
    assert mem.agent_ids() == ["a1", "b2"]
    assert mem.read("a1") is not None and mem.read("zz") is None and mem.read(ROOT) is not None
    for rel, body in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    fs = FsTree(tmp_path / f"{SID}.jsonl")
    assert fs.agent_ids() == ["a1", "b2"]
    assert fs.read("a1") == mem.read("a1") and fs.read("zz") is None and fs.read(ROOT) == mem.read(ROOT)
    assert FsTree(tmp_path / "missing.jsonl").read(ROOT) is None


def test_memtree_needs_exactly_one_root_file() -> None:
    with pytest.raises(ValueError):
        MemTree({"a.jsonl": "", "b.jsonl": ""})
    with pytest.raises(ValueError):
        MemTree({"x/y.txt": ""})


def test_tool_use_result_helpers_are_reachable_from_builders() -> None:
    assert tool_result("r", 1, "t", "c")["message"]["content"][0]["tool_use_id"] == "t"
    assert tool_use_block("t", "Bash", {})["name"] == "Bash"
