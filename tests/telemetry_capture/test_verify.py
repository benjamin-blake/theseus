"""Mirror tests for scripts/telemetry_capture/verify.py over fakes: an on-disk tree, an in-memory reader and a fake portal."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.executor.acceptance_lint import lint_acceptance_command
from scripts.telemetry_capture import cursor_tree, verify, verify_due
from scripts.telemetry_capture import state as st
from scripts.telemetry_capture.state import CaptureState, state_dir
from scripts.telemetry_capture.transport import Budget
from scripts.telemetry_verify.alarms import raise_alarms
from src.common.ducklake_reader_client import ResponseTooLargeError
from src.telemetry.append import prepare_batch
from src.turn_capture.record_turn import PARSER_VERSION, CaptureResult, record_turn
from src.turn_capture.transcript import FsTree
from tests.fixtures import telemetry_verification_trees as trees
from tests.fixtures.turn_capture_corpus import PROJECT, PROJECT_REF, SID, TENANT, case_cap, load_case, make_files, prompt
from tests.fixtures.turn_capture_ducklake import load_specs

NOW = 1_800_000_000.0
ROOT_ID = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
SPECS = load_specs()


class Portal:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, action: str, fields: dict[str, Any]) -> str:
        self.calls.append((action, fields))
        return "rec-9000"

    def classes(self) -> list[str]:
        return sorted(c[1]["title"].rsplit(": ", 1)[1] for c in self.calls if c[0] == "file")


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def stored_rows(result: CaptureResult, **tweak: Any) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for table, rows in result.batches:
        if rows:
            out[table] = prepare_batch(SPECS[table], copy.deepcopy(rows), tenant_id=TENANT, project_id=PROJECT).rows
    return out


class Reader:
    """The reader's named() contract over stored rows, plus current_state() for the rec lookup."""

    def __init__(self, stored: dict[str, list[dict[str, Any]]], *, root: bool = True, roots_in_tree: int = 1) -> None:
        self.entries = [
            (table, json.dumps({k: v for k, v in row.items() if k not in ("content", "content_uri")}, default=_iso))
            for table, rows in sorted(stored.items())
            for row in rows
        ]
        self.root, self.roots_in_tree = root, roots_in_tree
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.hook: Any = None
        self.too_large = False
        self.error: Exception | None = None
        self.totals: list[int] | None = None

    def current_state(self, table: str, **kw: Any) -> list[dict[str, Any]]:
        return []

    def named(self, verb: str, **params: Any) -> list[dict[str, Any]]:
        self.calls.append((verb, params))
        if self.error is not None:
            raise self.error
        if self.hook is not None:
            self.hook(verb, params)
        if verb == "telemetry_root_sessions":
            return [{"session_id": ROOT_ID, "entity_ref": SID}] if self.root else []
        if self.too_large and params["max_rows"] > 1:
            raise ResponseTooLargeError("named_read", "too big", {})
        start, size = params["offset"], params["max_rows"]
        total = self.totals.pop(0) if self.totals else len(self.entries)
        return [
            {"table_name": t, "row_json": j, "total_rows": total, "roots_in_tree": self.roots_in_tree}
            for t, j in self.entries[start : start + size]
        ]


@dataclass
class Tree:
    path: Path
    state: CaptureState
    result: CaptureResult
    reader: Reader
    portal: Portal

    def scheduling(self) -> dict[str, Any]:
        return [r for r in self.state.diagnostics() if r.get("event") != "verify"][-1]

    def run(self, **kw: Any) -> verify.VerifyResult:
        args: dict[str, Any] = {
            "trigger": "detached",
            "scheduling_record": self.scheduling(),
            "reader": self.reader,
            "portal": self.portal,
            "budget": Budget.start(600),
            "now": NOW,
            "credentials": lambda: True,
            "lock_wait_s": 0.0,
        }
        return verify.run_verify(self.path, SID, **{**args, **kw})

    def verify_records(self) -> list[dict[str, Any]]:
        return [r for r in self.state.diagnostics() if r.get("event") == "verify"]


def build(tmp_path: Path, files: dict[str, str], *, final: bool = False, case: str | None = None, **reader_kw: Any) -> Tree:
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")
    path = tmp_path / f"{SID}.jsonl"

    def capture() -> CaptureResult:
        return record_turn(FsTree(path), None, project_ref=PROJECT_REF, session_final=final)

    if case is not None:
        with case_cap(case):
            result = capture()
    else:
        result = capture()
    assert result.next_cursor is not None
    state = CaptureState(state_dir(path, SID))
    state.save_cursor(result.next_cursor, path.read_bytes(), st.Loaded(None, st.LOST))
    state.append_diagnostic({"event": "Stop", "final": False, "at": int(NOW) - 5, "outcome": "sent"})
    return Tree(path, state, result, Reader(stored_rows(result), **reader_kw), Portal())


def corpus(tmp_path: Path, name: str = "subagent_sync.json", *, final: bool = True, **kw: Any) -> Tree:
    return build(tmp_path, load_case(name)[0], case=name, final=final, **kw)


def ledger_tree(tmp_path: Path, **kw: Any) -> Tree:
    return build(tmp_path, trees.resume_with_cost_state(), **kw)


def test_a_clean_tree_completes_with_every_row_equal(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    result = tree.run()
    stored = sum(len(rows) for rows in stored_rows(tree.result).values())
    assert result.completed and result.compare_skipped == "none" and result.alarms == []
    assert result.counts["rows_equal"] == stored and result.counts["root_checked"] == 1
    assert tree.portal.calls == [] and result.reader_calls == 2
    record = tree.verify_records()[-1]
    assert record["status"] == "completed" and record["counts"]["rows_equal"] == stored
    state = tree.state.verify_state()
    assert state["root_session_id"] == ROOT_ID and state["incomplete_streak"] == 0 and "next_attempt_at" not in state


def test_a_failing_check_is_recorded_silent_and_backs_off(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tree = corpus(tmp_path)
    tree.reader.error = RuntimeError("boom with https://abc.lambda-url.eu-west-2.on.aws and arn:aws:iam::1:role/x")
    result = tree.run()
    assert result.status == "verify_error:RuntimeError" and not result.completed
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    record = tree.verify_records()[-1]
    assert "lambda-url" not in json.dumps(record) and "arn:" not in json.dumps(record)
    state = tree.state.verify_state()
    assert state["next_attempt_at"] == NOW + verify_due.VERIFY_RETRY_S and state["retry_s"] == 2 * verify_due.VERIFY_RETRY_S
    assert state["incomplete_streak"] == 1 and "settled_at" not in state, "a non-benign skip never settles"
    again = tree.run(now=NOW + 2)
    assert tree.state.verify_state()["retry_s"] == min(4 * verify_due.VERIFY_RETRY_S, verify_due.VERIFY_RETRY_MAX_S)
    assert not again.completed


def test_a_pass_during_the_read_is_tree_moved_never_a_finding(tmp_path: Path) -> None:
    tree = corpus(tmp_path)

    def pass_runs(verb: str, params: dict[str, Any]) -> None:
        if verb == "session_tree_rows":
            tree.state.append_diagnostic({"event": "Stop", "final": False, "at": int(NOW) + 1, "outcome": "sent"})

    tree.reader.hook = pass_runs
    result = tree.run()
    assert result.status == "tree_moved" and tree.portal.calls == []
    assert tree.state.verify_state().get("incomplete_streak", 0) == 0, "tree_moved is benign"
    moved_cursor = corpus(tmp_path / "other")
    cursor = moved_cursor.state.cursor_on_disk()
    assert cursor is not None
    moved_cursor.reader.hook = lambda verb, params: moved_cursor.state.save_cursor(
        replace(cursor, lines_consumed={"root": cursor.lines_consumed["root"] + 1}),
        moved_cursor.path.read_bytes(),
        st.Loaded(None, st.LOST),
    )
    assert moved_cursor.run().status == "tree_moved"


def test_writes_happen_only_under_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = corpus(tmp_path)
    writes: list[str] = []

    def guarded(name: str) -> Any:
        original = getattr(CaptureState, name)

        def wrapper(self: CaptureState, *args: Any, **kw: Any) -> Any:
            probe = CaptureState(self.dir).acquire(0.0)
            assert probe is None, f"{name} ran without holding the tree lock"
            writes.append(name)
            return original(self, *args, **kw)

        return wrapper

    for name in ("append_diagnostic", "save_verify_state"):
        monkeypatch.setattr(CaptureState, name, guarded(name))
    assert tree.run().completed
    assert writes == ["append_diagnostic", "save_verify_state"]
    held = tree.state.acquire(0.0)
    assert held is not None
    busy = tree.run()
    held.release()
    assert busy.status == "busy" and writes == ["append_diagnostic", "save_verify_state"], "busy writes nothing"


def test_a_newer_pass_record_skips_the_check(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    scheduled = tree.scheduling()
    tree.state.append_diagnostic({"event": "Stop", "final": False, "at": int(NOW), "outcome": "stopped"})
    result = tree.run(scheduling_record=scheduled)
    assert result.status == "superseded_by_pass" and tree.reader.calls == []
    assert tree.run(scheduling_record=None, trigger="operator").completed, "an operator check has no scheduling pass"


def test_state_fields_are_merged_by_owner(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    tree.state.save_verify_state({"scheduled_at": 7, "sent_passes": 10, "checks_by_day": {"d": 1}})

    def runner_writes(verb: str, params: dict[str, Any]) -> None:
        if verb == "session_tree_rows":
            tree.state.save_verify_state({**tree.state.verify_state(), "sent_passes": 11, "last_ledger_line": 999})

    tree.reader.hook = runner_writes
    assert tree.run().completed
    merged = tree.state.verify_state()
    assert merged["sent_passes"] == 11, "the runner's count survives the check"
    assert merged["checks_by_day"] == {"d": 1} and merged["settled_at"] == 7 and merged["root_session_id"] == ROOT_ID
    assert merged["last_ledger_line"] == 999, "the check only writes last_ledger_line when it covered a record"
    assert "next_attempt_at" not in merged and merged["incomplete_streak"] == 0


def test_moving_and_tail_mismatched_trees_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    moving = corpus(tmp_path / "a")
    monkeypatch.setattr(verify, "PAGE_ROWS", 3)
    moving.reader.totals = [8, 9]
    result = moving.run()
    assert result.status == "tree_moved" and moving.portal.calls == []
    monkeypatch.undo()
    tail = corpus(tmp_path / "b")
    head, marker, last = tail.path.read_bytes().rpartition(b'"uuid": "')
    tail.path.write_bytes(head + marker + b"x" + last)
    skipped = tail.run()
    assert skipped.status == "cursor_tail_mismatch" and tail.reader.calls == []
    halted = corpus(tmp_path / "c")
    halted.state.write_halt({"reason": "x"})
    assert halted.run().status == "halted"
    other = corpus(tmp_path / "d")
    cursor = other.state.cursor_on_disk()
    assert cursor is not None
    other.state.save_cursor(
        replace(cursor, parser_version=PARSER_VERSION - 1), other.path.read_bytes(), st.Loaded(None, st.LOST)
    )
    assert other.run().status == "parser_version_skip"
    synthetic = corpus(tmp_path / "e")
    cursor = synthetic.state.cursor_on_disk()
    assert cursor is not None
    synthetic.state.save_cursor(
        replace(cursor, project_ref="synthetic:x"), synthetic.path.read_bytes(), st.Loaded(None, st.LOST)
    )
    assert synthetic.run().status == "non_real_project"
    other.state.save_verify_state({"scheduled_at": 42})
    other.run()
    assert other.state.verify_state()["settled_at"] == 42, "a per-tree condition settles the scheduled check"


def test_compare_skips_keep_the_transcript_legs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def legs(result: verify.VerifyResult) -> None:
        assert result.completed and result.counts["ledger_records"] >= 1 and result.counts["root_calls"] >= 1
        assert "rows_equal" not in result.counts and "missing_in_store" not in result.counts
        assert "stored_ledger_tested" not in result.counts

    absent = ledger_tree(tmp_path / "absent", root=False)
    result = absent.run()
    legs(result)
    assert result.compare_skipped == "root_absent" and result.counts["root_absent"] == 1 and result.counts["root_checked"] == 1
    assert absent.portal.classes() == ["root_absent"] and result.alarms == ["root_absent"]

    modified = ledger_tree(tmp_path / "modified")
    modified.state.save_verify_state({"producer_changed": True})
    legs(modified.run())
    assert modified.reader.calls == [] and modified.verify_records()[-1]["compare_skipped"] == "producer_modified"
    different = ledger_tree(tmp_path / "different")
    different.state.save_verify_state({"producer_fingerprint": "0" * 64})
    assert different.run().compare_skipped == "producer_modified"

    collision = ledger_tree(tmp_path / "collision", roots_in_tree=2)
    result = collision.run()
    legs(result)
    assert result.compare_skipped == "tree_collision"

    big = ledger_tree(tmp_path / "big")
    monkeypatch.setattr(verify, "MAX_TREE_PAGES", 0)
    result = big.run()
    legs(result)
    assert result.compare_skipped == "tree_too_large" and big.reader.calls == [], "judged from the expected rows"

    monkeypatch.setattr(verify, "MAX_TREE_PAGES", 10)
    early = build(tmp_path / "early", make_files([prompt("u1", 1, "p1", "go")]), root=False)
    result = early.run()
    assert result.completed and result.compare_skipped == "root_not_due" and result.counts.get("root_checked", 0) == 0
    assert early.portal.calls == [] and "missing_in_store" not in result.counts


def test_tree_reads_stop_at_the_call_cap(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    tree.reader.too_large = True
    result = tree.run()
    assert result.completed and result.compare_skipped == "tree_too_large"
    tree_calls = [c for c in tree.reader.calls if c[0] == "session_tree_rows"]
    assert len(tree_calls) == verify.MAX_TREE_PAGES and result.reader_calls == verify.MAX_TREE_PAGES + 1


def test_no_credentials_is_benign(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    result = tree.run(credentials=lambda: False)
    assert result.status == "no_credentials" and tree.reader.calls == [] and tree.portal.calls == []
    state = tree.state.verify_state()
    assert state["next_attempt_at"] == NOW + verify_due.VERIFY_RETRY_S
    assert state.get("incomplete_streak", 0) == 0 and "settled_at" not in state


def test_an_operator_check_never_writes_scheduling_fields(tmp_path: Path) -> None:
    tree = ledger_tree(tmp_path)
    tree.state.save_verify_state({"scheduled_at": 5, "next_attempt_at": 3, "last_ledger_line": 1, "sent_passes": 4})
    before = tree.state.verify_state()
    result = tree.run(trigger="operator", scheduling_record=None, alarms=False)
    assert result.completed
    after = tree.state.verify_state()
    for field in ("last_ledger_line", "held_ledger_line", "settled_at", "next_attempt_at", "retry_s", "incomplete_streak"):
        assert after.get(field) == before.get(field), field
    assert after["root_session_id"] == ROOT_ID and after["sent_passes"] == 4
    assert tree.verify_records()[-1]["trigger"] == "operator"


def test_a_persistent_non_completion_files_one_incomplete_alarm(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    tree.reader.error = ValueError("x")
    for attempt in range(verify.VERIFY_INCOMPLETE_STREAK - 1):
        tree.run(now=NOW + attempt)
        assert tree.portal.calls == []
    benign = tree.run(now=NOW + 10, credentials=lambda: False)
    assert benign.status == "no_credentials" and tree.portal.calls == [], "a benign token neither counts nor files"
    assert tree.state.verify_state()["incomplete_streak"] == verify.VERIFY_INCOMPLETE_STREAK - 1, "nor resets"
    third = tree.run(now=NOW + 20)
    assert not third.completed and tree.portal.classes() == ["verify_incomplete"]
    assert tree.portal.calls[0][1]["acceptance"].endswith("--assert-zero verify_incomplete")
    tree.run(now=NOW + 30)
    assert tree.portal.classes() == ["verify_incomplete"], "the helper's rate limit bounds repeats"
    halted = corpus(tmp_path / "h")
    halted.state.write_halt({"reason": "x"})
    halted.state.save_verify_state({"incomplete_streak": 9})
    halted.run()
    assert halted.portal.calls == [], "a halted tree is a per-tree condition, not a failure"


def test_malformed_lines_keep_one_index_space(tmp_path: Path) -> None:
    ledger_record = {"type": "cost-state", "modelUsage": {}}
    forked = {"type": "cost-state", "forkedFrom": "x", "modelUsage": {"claude-fork": {"inputTokens": 7}}}
    files = trees.resume_with_cost_state()
    lines = files[f"{SID}.jsonl"].split("\n")
    cost_index = next(i for i, line in enumerate(lines) if '"cost-state"' in line)
    lines.insert(cost_index, "this is not json")
    lines.insert(0, "neither is this")
    lines.insert(1, json.dumps(forked))
    lines.insert(2, "{not closed")
    files[f"{SID}.jsonl"] = "\n".join(lines)
    del ledger_record
    tree = build(tmp_path, files)
    result = tree.run()
    assert result.completed, result.status
    state = tree.state.verify_state()
    file_lines = files[f"{SID}.jsonl"].split("\n")
    real_cost = [i for i, line in enumerate(file_lines) if '"cost-state"' in line and "forkedFrom" not in line]
    assert result.counts["stored_ledger_records_inherited"] == 1
    assert result.counts["ledger_fork_unmeasured"] == 1 and "ledger_model_unexplained" not in result.counts
    assert state["held_ledger_line"] == real_cost[-1] and state["last_ledger_line"] == real_cost[-1]
    root = tree.path.read_bytes()
    cursor = tree.state.cursor_on_disk()
    assert cursor is not None
    assert not verify_due.verify_due(
        cursor, root, {**state, "sent_passes": 3}, event="Stop", final=False, outcome="sent", now=NOW + 1
    )


def test_a_pending_record_is_held_not_covered(tmp_path: Path) -> None:
    tree = ledger_tree(tmp_path)
    result = tree.run()
    assert result.completed
    state = tree.state.verify_state()
    assert state["held_ledger_line"] >= 0 and (
        "last_ledger_line" not in state or state["last_ledger_line"] <= state["held_ledger_line"]
    )


def _plant(tree: Tree, table: str, column: str, value: Any, index: int = 0) -> None:
    rows = [(t, json.loads(j)) for t, j in tree.reader.entries]
    seen = -1
    for position, (t, row) in enumerate(rows):
        if t == table:
            seen += 1
            if seen == index:
                row[column] = value
                tree.reader.entries[position] = (t, json.dumps(row))
                return
    raise AssertionError("no row to plant on")


def test_an_r7_boundary_divergence_is_declared_never_filed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = cursor_tree.expected_rows

    def with_notice(*args: Any, **kw: Any) -> CaptureResult:
        result = real(*args, **kw)
        return replace(result, diagnostics={**result.diagnostics, "notice_after_boundary": 1})

    tree = corpus(tmp_path / "a")
    _plant(tree, "telemetry_observations", "name", "changed")
    monkeypatch.setattr(cursor_tree, "expected_rows", with_notice)
    result = tree.run()
    assert result.completed and result.counts["r7_boundary_divergence"] == 1 and "column_mismatch" not in result.counts
    assert tree.portal.calls == [] and result.masked["column_mismatch"] == 1
    assert tree.verify_records()[-1]["r7_masked"]["column_mismatch"] == 1, "the per-class counts stay in the record"

    duplicate = corpus(tmp_path / "b")
    row = json.loads(duplicate.reader.entries[0][1])
    twin = dict(row, event_id=row["event_id"][:-1] + ("0" if row["event_id"][-1] != "0" else "1"))
    duplicate.reader.entries.append((duplicate.reader.entries[0][0], json.dumps(twin)))
    result = duplicate.run()
    assert duplicate.portal.classes() == ["duplicate_ref_rows"], "a keep-first-emitted row cannot produce a duplicate"

    monkeypatch.undo()
    plain = corpus(tmp_path / "c")
    _plant(plain, "telemetry_observations", "name", "changed")
    result = plain.run()
    assert result.counts["column_mismatch"] == 1 and plain.portal.classes() == ["column_mismatch"]


def test_alarm_classes_reach_the_helper_with_scope_and_rate_state(tmp_path: Path) -> None:
    tree = corpus(tmp_path)
    _plant(tree, "telemetry_sessions", "branch", "changed")
    first = tree.run()
    assert first.alarms == ["column_mismatch"] and first.outcome is not None and first.outcome.filed == 1
    action, fields = tree.portal.calls[0]
    assert action == "file" and f"scope={SID}" in fields["context"] and "count=1" in fields["context"]
    assert fields["source"] == "telemetry_verify" and fields["file"] == verify.FILE
    assert tree.state.verify_state()["alarm_at"]["column_mismatch"] == NOW
    again = tree.run(now=NOW + 60)
    assert again.outcome is not None and again.outcome.rate_limited == 1 and len(tree.portal.calls) == 1
    quiet = tree.run(now=NOW + 120, alarms=False)
    assert quiet.alarms == ["column_mismatch"] and len(tree.portal.calls) == 1, "--no-alarms files nothing"


def test_declared_classes_are_passed_as_declared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def spy(findings: Any, **kw: Any) -> Any:
        seen.update(kw, findings=dict(findings))
        return raise_alarms(findings, **kw)

    monkeypatch.setattr(verify, "raise_alarms", spy)
    tree = ledger_tree(tmp_path)
    tree.run()
    assert set(seen["declared"]) == verify.DECLARED_CLASSES
    required = {
        "ledger_exact", "ledger_output_residual_nonfinal", "ledger_auxiliary_only", "ledger_bounded_background",
        "nonfinal_call", "spawn_equal", "spawn_corrects_nonfinal", "background_status_mismatch",
        "stored_ledger_exact", "stored_ledger_untested", "stored_ledger_not_compared", "stored_ledger_bounded",
        "stored_ledger_output_residual_final_false", "race_duplicate_rows", "ledger_fork_unmeasured", "r7_boundary_divergence",
    }  # fmt: skip
    assert required <= verify.DECLARED_CLASSES
    portal = Portal()
    outcome = raise_alarms(
        dict.fromkeys(sorted(verify.DECLARED_CLASSES), 2),
        scope="s", alarm_at=None, now=datetime.fromtimestamp(NOW), portal=portal, file=verify.FILE,
        acceptance_for=verify.acceptance_for, declared=verify.DECLARED_CLASSES, rows=[],
    )  # fmt: skip
    assert (
        portal.calls == []
        and outcome.declared == len(verify.DECLARED_CLASSES)
        and not (verify.DECLARED_CLASSES & verify.ALARM_CLASSES)
    )


def test_acceptance_is_the_verify_command_for_the_class() -> None:
    assert verify.ALARM_CLASSES
    for cls in sorted(verify.ALARM_CLASSES):
        command = verify.acceptance_for(cls)
        assert command.endswith(f"--no-alarms --assert-zero {cls}") and "scripts.telemetry_capture verify --tree" in command
        ok, why = lint_acceptance_command(command, require_decidable=True)
        assert ok, (cls, why)
    assert time.time() > 0
