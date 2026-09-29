"""record_turn: golden corpus equality, R7 write order, incremental equals full, finalize, reset, loud pins."""

from __future__ import annotations

import dataclasses
import json

import pytest

from src.turn_capture.cursor import CaptureCursor, CursorError, SourceMutated
from src.turn_capture.record_turn import PARSER_VERSION, PRODUCER, TABLES, record_turn
from src.turn_capture.render import render_rows_json
from src.turn_capture.scrub import scrub_text
from src.turn_capture.streams import ROOT, parse_tree
from src.turn_capture.transcript import MemTree
from tests.fixtures.turn_capture_corpus import (
    PROJECT_REF,
    SID,
    assert_content_hashes,
    assistant,
    build_secret,
    case_names,
    child,
    hook,
    jsonl,
    load_case,
    make_files,
    normalise,
    prompt,
    text_block,
    tool_result,
    tool_use_block,
)
from tests.fixtures.turn_capture_ducklake import load_specs

SECRET_KINDS = ("aws_access", "aws_secret", "aws_session", "anthropic", "github", "github_pat", "bearer")


def capture(files, cursor=None, final=False, **kw):
    return record_turn(MemTree(files), cursor, project_ref=PROJECT_REF, session_final=final, **kw)


def keyed(result):
    return {(table, row["external_ref"]): row for table, rows in result.batches for row in rows}


def test_golden_cases_match_expected_rows() -> None:
    names = case_names()
    assert len(names) == len(set(names))
    for name in names:
        files, expected = load_case(name)
        result = capture(files, final=True)
        assert_content_hashes(result.batches)
        assert normalise(result.batches) == expected, name


def test_no_secret_shaped_value_emitted() -> None:
    for name in case_names():
        files, _ = load_case(name)
        wire = render_rows_json([row for _, rows in capture(files, final=True).batches for row in rows])
        assert scrub_text(wire).counts == {}, name
        for kind in SECRET_KINDS:
            assert build_secret(kind) not in wire, (name, kind)


def test_rows_use_only_caller_known_columns() -> None:
    specs = load_specs()
    for name in case_names():
        files, _ = load_case(name)
        for table, rows in capture(files, final=True).batches:
            spec = specs[table]
            caller_not_null = {c for c in spec.not_null if c in spec.caller_known_columns}
            for row in rows:
                assert set(row) <= spec.caller_known_columns, (name, table, set(row) - spec.caller_known_columns)
                assert all(row.get(col) is not None for col in caller_not_null), (name, table, row["external_ref"])
                for column, plan in spec.key_plans.items():
                    if plan.required:
                        assert row.get(plan.ref_field), (name, table, column)


def test_sessions_batch_written_last() -> None:
    files, _ = load_case("subagent_sync.json")
    result = capture(files, final=True)
    assert [table for table, _ in result.batches] == list(TABLES) and TABLES[-1] == "telemetry_sessions"
    assert result.sessions and all(rows for _, rows in result.batches)
    assert {r["entity_ref"] for r in result.sessions} == {SID, f"{SID}:agent1"}
    assert result.next_cursor is not None and result.next_cursor.finalized and result.next_cursor.producer == PRODUCER


def _line_counts(files):
    counts = {ROOT: files[f"{SID}.jsonl"].count("\n")}
    for rel, body in files.items():
        if "/subagents/agent-" in rel and rel.endswith(".jsonl"):
            counts[rel.split("agent-")[1][: -len(".jsonl")]] = body.count("\n")
    return counts


def _rel(key):
    return f"{SID}.jsonl" if key == ROOT else f"{SID}/subagents/agent-{key}.jsonl"


def _cut(files, cut):
    out = dict(files)
    for key, n in cut.items():
        out[_rel(key)] = "".join(files[_rel(key)].splitlines(keepends=True)[:n])
    return out


def _valid(files, cut, full):
    parsed = parse_tree(MemTree(_cut(files, cut)), None, False)
    return all(cut[s.agent_id] == full[s.agent_id] for s in parsed.spawns if s.complete)


def _paths(files):
    full = _line_counts(files)
    keys = list(full)
    orders = [keys, keys[::-1], "rotate"]
    for order in orders:
        cut = dict.fromkeys(keys, 0)
        path = [dict(cut)]
        turn = 0
        while cut != full:
            prefer = [keys[(turn + i) % len(keys)] for i in range(len(keys))] if order == "rotate" else order
            turn += 1
            for key in prefer:
                if cut[key] < full[key] and _valid(files, {**cut, key: cut[key] + 1}, full):
                    cut[key] += 1
                    path.append(dict(cut))
                    break
            else:
                raise AssertionError("no valid step")
        yield path


def test_incremental_equals_full_at_every_line_cut() -> None:
    for name in case_names():
        files, _ = load_case(name)
        full_rows = keyed(capture(files, final=True))
        for path in _paths(files):
            cursor, seen = None, {}
            for index, cut in enumerate(path):
                last = index == len(path) - 1
                result = capture(_cut(files, cut), cursor, final=last)
                cursor = result.next_cursor
                for key, row in keyed(result).items():
                    assert key not in seen, (name, cut, key)
                    assert row == full_rows[key], (name, cut, key)
                    seen[key] = row
            assert set(seen) == set(full_rows), (name, set(full_rows) ^ set(seen))


def test_finalize_equals_virtual_prompt_at_eof() -> None:
    skipped = {"subagent_background_without_completion.json"}
    for name in case_names():
        if name in skipped:
            continue
        files, _ = load_case(name)
        final_rows = keyed(capture(files, final=True))
        virtual = dict(files)
        for rel in files:
            if rel.endswith(".jsonl"):
                agent = rel.split("agent-")[1][: -len(".jsonl")] if "/subagents/" in rel else None
                rec = prompt(f"zz-{agent or 'root'}", 999, "p-virtual", "virtual")
                virtual[rel] = (
                    files[rel] + ("\n" if not files[rel].endswith("\n") else "") + jsonl([child(rec, agent) if agent else rec])
                )
        live_rows = {k: v for k, v in keyed(capture(virtual, final=False)).items() if not k[1].startswith("zz-")}
        assert live_rows == final_rows, name


def _grown_files():
    base = [
        prompt("u1", 1, "p1", "go"),
        assistant("a1", 2, "m1", [tool_use_block("tuX", "Bash", {})]),
    ]
    grown = [
        hook("rs1", 10, "SessionStart:resume"),
        prompt("u2", 11, "p2", "back"),
        assistant("a2", 12, "m2", [text_block("hello again")]),
        tool_result("late", 13, "tuX", "very late", pid="p2"),
    ]
    return make_files(base), make_files(base + grown)


def test_finalize_then_grow_through_resume_re_emits_nothing() -> None:
    before, after = _grown_files()
    first = capture(before, final=True)
    assert "a1#0/tool_call_close" in {r["external_ref"] for r in first.observations}
    second = capture(after, first.next_cursor, final=True)
    old_keys, new_keys = set(keyed(first)), set(keyed(second))
    assert not old_keys & new_keys
    assert ("telemetry_sessions", "rs1#0/resume") in new_keys and ("telemetry_observations", "a2#0/turn_close") in new_keys
    assert not any(k[1] == "late#0/tool_call_close" for k in new_keys)
    assert set(keyed(capture(after, None, final=True))) == old_keys | new_keys
    assert capture(after, second.next_cursor, final=True).observations == []


def test_cursor_reset_on_version_mismatch_reuses_pins() -> None:
    files, _ = load_case("subagent_sync.json")
    first = capture(files, final=True)
    stale = dataclasses.replace(first.next_cursor, parser_version=PARSER_VERSION - 1)
    again = capture(files, stale, final=True)
    assert keyed(again) == keyed(first)
    kept, fresh = again.next_cursor, first.next_cursor
    assert (kept.project_ref, kept.session_started_at_ms, kept.root_session_ref, kept.billing_shape) == (
        fresh.project_ref, fresh.session_started_at_ms, fresh.root_session_ref, fresh.billing_shape,
    )  # fmt: skip
    assert kept.parser_version == PARSER_VERSION
    other_producer = dataclasses.replace(first.next_cursor, producer="somebody_else")
    assert keyed(capture(files, other_producer, final=True)) == keyed(first)
    reset = dataclasses.replace(stale, session_started_at_ms=stale.session_started_at_ms + 1)
    with pytest.raises(CursorError):
        capture(files, reset, final=True)


def test_pin_mismatch_and_sidecar_mutation_are_loud() -> None:
    files, _ = load_case("sidecar_present.json")
    cursor = capture(files, final=False).next_cursor
    assert cursor is not None
    with pytest.raises(CursorError, match="project_ref"):
        record_turn(MemTree(files), cursor, project_ref="another/project")
    with pytest.raises(CursorError, match="billing_shape"):
        record_turn(MemTree(files), cursor, project_ref=PROJECT_REF, billing_shape="metered_marginal")
    other = {k.replace(SID, "bbbbbbbb-0000-4000-8000-000000000002"): v for k, v in files.items()}
    with pytest.raises(CursorError, match="root_session_ref"):
        record_turn(MemTree(other), cursor, project_ref=PROJECT_REF)
    pinned = capture(files, final=True).next_cursor
    assert isinstance(pinned.sidecars["big1.txt"], str)
    mutated = dict(files)
    mutated[f"{SID}/tool-results/big1.txt"] = "TAMPERED"
    with pytest.raises(SourceMutated):
        capture(mutated, pinned, final=True)
    vanished = {k: v for k, v in files.items() if "tool-results" not in k}
    with pytest.raises(SourceMutated):
        capture(vanished, pinned, final=True)


def test_finalize_then_grow_keeps_the_synthetic_close_anchored() -> None:
    before, after = _grown_files()
    close_before = keyed(capture(before, final=True))[("telemetry_observations", "a1#0/tool_call_close")]
    close_after = keyed(capture(after, final=True))[("telemetry_observations", "a1#0/tool_call_close")]
    assert close_before == close_after and close_after["outcome"] == "interrupted"


def test_inputs_are_validated_and_diagnostics_are_counts() -> None:
    files, _ = load_case("unknown_record_and_attachment_types.json")
    with pytest.raises(ValueError, match="billing_shape"):
        capture(files, billing_shape="free")
    with pytest.raises(ValueError, match="project_ref"):
        record_turn(MemTree(files), None, project_ref="")
    result = capture(files, final=True, billing_shape="metered_marginal")
    assert (
        all(isinstance(v, int) for v in result.diagnostics.values())
        and result.diagnostics["unknown_record_type:weird-new"] == 1
    )
    assert {r["billing_shape"] for r in result.observations if r["observation_type"] == "model_call"} == {"metered_marginal"}
    assert CaptureCursor.from_json(result.next_cursor.to_json()) == result.next_cursor
    assert json.loads(result.next_cursor.to_json())["finalized"] is True


def test_duplicate_source_refs_are_counted_and_first_wins() -> None:
    files = make_files(
        [
            prompt("u1", 1, "p1", "go"),
            assistant("a1", 2, "m1", [text_block("first")]),
            prompt("u2", 3, "p2", "next"),
            assistant("a1", 4, "m2", [text_block("same uuid again")]),
        ]
    )
    result = capture(files, final=True)
    assert result.diagnostics["duplicate_refs"] >= 1
    assert [r["content"] for r in result.transcripts if r["external_ref"] == "a1#0"] == ["first"]
