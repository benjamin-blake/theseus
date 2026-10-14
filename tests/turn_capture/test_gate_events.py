"""gate_events: gate:<check> and precommit:<hook> process_events from structured markers only (rules G-1..G-6)."""

from __future__ import annotations

import dataclasses
import json
from collections import Counter

from src.turn_capture.gate_events import GATE_COMMAND_TOKENS, GATE_TAIL_LINES
from src.turn_capture.observations import build_observations
from src.turn_capture.streams import parse_tree
from src.turn_capture.transcript import MemTree
from src.turn_capture.transcripts import Sidecars
from tests.fixtures.turn_capture_corpus import (
    SID,
    assistant,
    build_secret,
    make_ctx,
    make_files,
    prompt,
    rows_of,
    tool_result,
    tool_use_block,
)

GATE = "GATE-FAILURE v1 source=gate check={}"
BLOCK = "ruff.....Failed\n- hook id: ruff\n- exit code: 1\n\nsrc/x.py:1:1: F401\n"
VALIDATE = "bin/venv-python -m scripts.validate --pre"


def events(output, command=VALIDATE, name="Bash", tur=None, sidecars=None, cap=None, is_error=None):
    root = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("tu1", name, {"command": command})]),
        tool_result("r1", 3, "tu1", output, pid="p1", tur=tur, is_error=is_error),
        prompt("u2", 5, "p2", "next"),
    ]
    diag: Counter[str] = Counter()
    tree = MemTree(make_files(root, sidecars=sidecars))
    ctx = make_ctx() if cap is None else dataclasses.replace(make_ctx(), full_output_cap_bytes=cap)
    rows = rows_of(build_observations(parse_tree(tree, None, True), ctx, diag, Sidecars(tree, None)))
    return [r for r in rows if r["external_ref"].find("gate_event") >= 0], diag


def test_gate_and_precommit_rows_have_the_pinned_shape() -> None:
    rows, _ = events("x\n" + GATE.format("alpha") + "\n" + BLOCK)
    assert [(r["name"], r["external_ref"]) for r in rows] == [
        ("gate:alpha", "r1#0/gate_event.1"),
        ("precommit:ruff", "r1#0/gate_event.2"),
    ]
    first = rows[0]
    assert first["entity_ref"] == first["external_ref"] and first["parent_observation_ref"] == "tu1"
    assert (first["observation_type"], first["event_kind"], first["severity"], first["source_ordinal"]) == (
        "process_event",
        "point",
        "error",
        2,
    )
    assert json.loads(first["metadata"]) == {"marker_version": 1, "tool_use_id": "tu1"}
    assert first["session_ref"] == SID


def test_one_row_per_distinct_source_and_signature_in_first_seen_order() -> None:
    text = "\n".join([GATE.format("b"), GATE.format("a"), GATE.format("b"), BLOCK, BLOCK])
    rows, _ = events(text)
    assert [r["name"] for r in rows] == ["gate:b", "gate:a", "precommit:ruff"]
    assert [r["external_ref"] for r in rows] == [f"r1#0/gate_event.{n}" for n in (1, 2, 3)]


def test_gate_markers_count_only_in_the_last_200_lines_but_precommit_blocks_anywhere() -> None:
    filler = "\n".join(f"line {i}" for i in range(GATE_TAIL_LINES))
    far = GATE.format("far") + "\n" + BLOCK + filler + "\n"
    rows, _ = events(far)
    assert [r["name"] for r in rows] == ["precommit:ruff"]
    edge = "\n".join(f"line {i}" for i in range(GATE_TAIL_LINES - 1)) + "\n"
    assert [r["name"] for r in events(GATE.format("edge") + "\n" + edge)[0]] == ["gate:edge"]
    assert events(GATE.format("edge") + "\n" + filler + "\n")[0] == []


def test_only_gate_bash_commands_with_a_matched_result_are_scanned() -> None:
    text = GATE.format("alpha")
    for token in GATE_COMMAND_TOKENS:
        assert len(events(text, command=f"run {token} now")[0]) == 1, token
    assert events(text, command="ls -la")[0] == []
    assert events(text, name="Read")[0] == []
    no_result = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("tu1", "Bash", {"command": VALIDATE})]),
        prompt("u2", 5, "p2", "next"),
    ]
    tree = MemTree(make_files(no_result))
    rows = build_observations(parse_tree(tree, None, True), make_ctx(), Counter(), Sidecars(tree, None))
    assert not [r for r in rows if "gate_event" in r["external_ref"]]
    assert events("GATE-FAILURE v1 source=gate check=")[0] == [] and events("free text: gate failed")[0] == []


def test_persisted_sidecar_text_is_scanned_instead_of_the_preview() -> None:
    body = "head\n" + GATE.format("from_sidecar") + "\n"
    tur = {"persistedOutputPath": "/e/tool-results/g.txt", "persistedOutputSize": len(body)}
    rows, diag = events(GATE.format("from_preview"), tur=tur, sidecars={"g.txt": body})
    assert [r["name"] for r in rows] == ["gate:from_sidecar"] and diag["gate_scan_unavailable"] == 0


def test_gate_scan_unavailable_counts_unreadable_and_oversize_sidecars() -> None:
    tur = {"persistedOutputPath": "/e/tool-results/g.txt", "persistedOutputSize": 40}
    rows, diag = events(GATE.format("preview"), tur=tur, sidecars=None)
    assert rows == [] and diag["gate_scan_unavailable"] == 1
    body = GATE.format("big") + "\n" + "z" * 100
    rows, diag = events("p", tur=tur, sidecars={"g.txt": body}, cap=len(GATE.format("big")))
    assert rows == [] and diag["gate_scan_unavailable"] == 1


def test_scrubbed_text_never_mints_a_name_from_a_credential() -> None:
    secret = build_secret("anthropic")
    rows, _ = events(GATE.format(secret))
    assert rows == []
    assert [r["name"] for r in events(GATE.format("ok") + "\n" + f"token {secret}")[0]] == ["gate:ok"]
