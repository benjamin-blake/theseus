"""Shared helper (never a test_ module): an on-disk captured tree, an in-memory reader and a fake portal for verify tests."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.telemetry_capture import state as st
from scripts.telemetry_capture import verify
from scripts.telemetry_capture.state import CaptureState, state_dir
from scripts.telemetry_capture.transport import Budget
from src.common.ducklake_reader_client import ResponseTooLargeError
from src.telemetry.append import prepare_batch
from src.turn_capture.record_turn import CaptureResult, record_turn
from src.turn_capture.transcript import FsTree
from tests.fixtures import telemetry_verification_trees as trees
from tests.fixtures.turn_capture_corpus import PROJECT, PROJECT_REF, SID, TENANT, case_cap, load_case
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
