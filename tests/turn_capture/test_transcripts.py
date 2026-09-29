"""Transcript rows: purpose/origin per block, scrub before hash, empty and binary blocks, sidecar-or-truncated."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest

from src.turn_capture import transcripts
from src.turn_capture.cursor import CaptureCursor, SourceMutated
from src.turn_capture.render import render_rows_json
from src.turn_capture.streams import ROOT
from src.turn_capture.transcript import MemTree
from src.turn_capture.transcripts import Sidecars, build_transcripts, canonical_json, clean, text_of
from tests.fixtures.turn_capture_corpus import (
    SID,
    assistant,
    build_secret,
    make_ctx,
    make_files,
    parse_records,
    prompt,
    rows_of,
    text_block,
    thinking_block,
    tool_result,
    tool_use_block,
)

IMG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}}


def build(root, sidecar_files=None, cursor=None, diag=None):
    files = make_files(root, None, sidecar_files)
    tree = MemTree(files)
    from src.turn_capture.streams import parse_tree

    side = Sidecars(tree, cursor)
    rows = build_transcripts(parse_tree(tree, None, True), make_ctx(), side, diag if diag is not None else Counter())
    return rows_of(rows), side


def by(rows, **match):
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def test_scrubbed_before_hash_empty_and_binary_blocks() -> None:
    secret = build_secret("github")
    root = [
        prompt("u1", 1, "p1", [text_block(f"token {secret}"), text_block(""), IMG, 7]),
        assistant(
            "a1",
            2,
            "m1",
            [thinking_block(""), thinking_block("hmm"), text_block("hi"), tool_use_block("t1", "Bash", {"k": "v"})],
        ),
        tool_result("r1", 3, "t1", [IMG, text_block("caption")], pid="p1"),
    ]
    rows, _ = build(root)
    scrubbed = "token [REDACTED:GITHUB_TOKEN]"
    first = by(rows, external_ref="u1#0")[0]
    assert first["content"] == scrubbed and first["content_sha256"] == hashlib.sha256(scrubbed.encode()).hexdigest()
    assert first["content_bytes"] == len(scrubbed.encode()) and secret not in render_rows_json(rows)
    assert by(rows, external_ref="u1#1") == [] and by(rows, external_ref="u1#3") == []
    stub = json.loads(by(rows, external_ref="u1#2")[0]["content"])
    assert stub == {"bytes": 5, "media_type": "image/png", "sha256": hashlib.sha256(b"hello").hexdigest(), "type": "image"}
    assert by(rows, external_ref="a1#0") == []
    assert [by(rows, external_ref=f"a1#{i}")[0]["purpose"] for i in (1, 2, 3)] == ["thinking", "response", "tool_input"]
    result = by(rows, purpose="tool_result")[0]
    assert json.loads(result["content"])[0]["type"] == "image" and result["origin"] == "tool"


def test_purpose_origin_owner_and_columns() -> None:
    root = [
        prompt("u1", 1, "p1", "meta", isMeta=True),
        prompt("u2", 2, "p1", "human words"),
        prompt("u3", 3, "p1", "reminder", sourceToolUseID="x"),
        assistant("a1", 4, "m1", [tool_use_block("t1", "Bash", {"b": 2, "a": 1})], model="claude-x"),
        tool_result("r1", 5, "t1", "out", pid="p1"),
    ]
    rows, _ = build(root)
    meta, human, companion = (by(rows, external_ref=f"u{i}#0")[0] for i in (1, 2, 3))
    assert (meta["purpose"], meta["origin"]) == ("system", "harness") and (human["purpose"], human["origin"]) == (
        "prompt",
        "human",
    )
    assert (companion["purpose"], companion["origin"]) == ("system", "harness")
    assert all(r["observation_ref"] == f"{SID}/p1" for r in (meta, human, companion))
    tool_input = by(rows, purpose="tool_input")[0]
    assert (
        tool_input["content"] == '{"a":1,"b":2}'
        and tool_input["observation_ref"] == "m1"
        and tool_input["model"] == "claude-x"
    )
    result = by(rows, purpose="tool_result")[0]
    assert (result["observation_ref"], result["origin"], result["model"], result["event_kind"]) == (
        "t1",
        "tool",
        None,
        "point",
    )
    assert (
        result["entity_ref"] == result["external_ref"] == "r1#0"
        and result["content_uri"] is None
        and result["content_truncated"] is False
    )
    assert result["source_ordinal"] == 4 and result["session_ref"] == SID and result["producer"] == "claude_code"


def test_sidecar_or_truncated_and_pins() -> None:
    info = {"persistedOutputPath": "/elsewhere/tool-results/big.txt", "persistedOutputSize": 4}
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant(
            "a1",
            2,
            "m1",
            [tool_use_block("t1", "Bash", {}), tool_use_block("t2", "Bash", {}), tool_use_block("t3", "Bash", {})],
        ),
        tool_result("r1", 3, "t1", "preview", pid="p1", tur=info),
        tool_result("r2", 3.1, "t2", "preview2", pid="p1", tur={**info, "persistedOutputPath": "dir/"}),
        tool_result("r3", 3.2, "t3", "", pid="p1", tur={"persistedOutputPath": "/x/tool-results/none.txt"}),
    ]
    diag: Counter[str] = Counter()
    rows, side = build(root, {"big.txt": "FULL OUTPUT"}, diag=diag)
    full = by(rows, external_ref="r1#0")[0]
    assert full["content"] == "FULL OUTPUT" and full["content_truncated"] is False and diag["sidecar_size_mismatch"] == 1
    assert (
        by(rows, external_ref="r2#0")[0]["content"] == "preview2"
        and by(rows, external_ref="r2#0")[0]["content_truncated"] is False
    )
    assert by(rows, external_ref="r3#0") == []
    absent, _ = build(root, None)
    truncated = by(absent, external_ref="r1#0")[0]
    assert truncated["content"] == "preview" and truncated["content_truncated"] is True
    assert by(absent, external_ref="r3#0") == []
    assert side.used["big.txt"] == hashlib.sha256(b"FULL OUTPUT").hexdigest() and side.used["none.txt"] is None


def _cursor(sidecars):
    return CaptureCursor("claude_code", 1, SID, "p", "fixed_non_rollover_allowance", 1, sidecars=sidecars)


def test_sidecar_pins_are_honoured_and_contradictions_raise() -> None:
    info = {"persistedOutputPath": "/x/tool-results/big.txt"}
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})]),
        tool_result("r1", 3, "t1", "preview", pid="p1", tur=info),
    ]
    sha = hashlib.sha256(b"FULL").hexdigest()
    rows, _ = build(root, {"big.txt": "FULL"}, cursor=_cursor({"big.txt": sha}))
    assert by(rows, purpose="tool_result")[0]["content"] == "FULL"
    with pytest.raises(SourceMutated):
        build(root, {"big.txt": "CHANGED"}, cursor=_cursor({"big.txt": sha}))
    with pytest.raises(SourceMutated):
        build(root, None, cursor=_cursor({"big.txt": sha}))
    honoured, _ = build(root, {"big.txt": "FULL"}, cursor=_cursor({"big.txt": None}))
    assert by(honoured, purpose="tool_result")[0]["content_truncated"] is True


def test_unknown_blocks_and_helpers(monkeypatch) -> None:
    diag: Counter[str] = Counter()
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [{"type": "server_tool_use"}, {"type": "text", "text": None}, "junk"]),
    ]
    rows, _ = build(root, diag=diag)
    assert (
        diag["unknown_block_type:server_tool_use"] == 1
        and diag["unknown_block_type:None"] == 1
        and by(rows, purpose="response") == []
    )
    assert text_of(None) == "" and text_of("x") == "x" and text_of([text_block("a"), text_block("b")]) == "a\nb"
    assert text_of([]) == "" and json.loads(text_of([text_block("a"), {"type": "tool_reference"}]))[1] == {
        "type": "tool_reference"
    }
    assert text_of({"k": 1}) == '{"k":1}' and canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'
    assert clean("a\ud800b") == "a?b"
    assert transcripts._stub("x") == "x" and transcripts._stub({"type": "text"}) == {"type": "text"}
    bad = transcripts._stub({"type": "image", "source": {"data": "!!!not base64!!!"}})
    assert bad["bytes"] == len("!!!not base64!!!") and transcripts._stub({"type": "image"})["bytes"] == 0
    assert transcripts._stub({"type": "document", "source": {"data": "aGk=", "media_type": "x"}})["bytes"] == 2
    monkeypatch.setattr(transcripts, "HARNESS_INTERRUPT_SENTINELS", ("[Request interrupted]",))
    assert transcripts.is_sentinel("[Request interrupted]") and not transcripts.is_sentinel("other")
    monkeypatch.setattr(transcripts, "HARNESS_DENIAL_PREFIXES", ("Denied:",))
    assert transcripts.is_sentinel("Denied: tool")
    sentinel_root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})]),
        tool_result("r1", 3, "t1", "Denied: x", pid="p1"),
    ]
    assert by(build(sentinel_root)[0], purpose="tool_result")[0]["origin"] == "harness"


def test_open_turns_emit_no_transcript_rows() -> None:
    tree = parse_records(
        [prompt("u1", 1, "p1", "a"), assistant("a1", 2, "m1", [text_block("x")]), prompt("u2", 3, "p2", "b")], final=False
    )
    rows = build_transcripts(tree, make_ctx(), Sidecars(MemTree(make_files([prompt("u1", 1, "p1", "a")])), None), Counter())
    assert [r["external_ref"] for r in rows] == ["u1#0", "a1#0"] and ROOT in tree.streams


def test_orphan_and_late_tool_results() -> None:
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("t1", "Bash", {})]),
        tool_result("r0", 3, "ghost", "orphan text", pid="p1"),
        prompt("u2", 4, "p2", "next"),
        tool_result("rl", 5, "t1", "late text", pid="p2"),
    ]
    rows, _ = build(root)
    orphan = by(rows, external_ref="r0#0")[0]
    assert (orphan["purpose"], orphan["observation_ref"], orphan["content"]) == ("tool_result", "ghost", "orphan text")
    assert by(rows, external_ref="rl#0") == []
