"""The c8 proof (rule SM-1): the real Stop and SessionEnd entry points against the live writer under a synthetic: ref.

Registers synthetic:pc-smoke-<8 hex>, writes a synthetic transcript tree (a pinning SessionStart attachment, one tool
output above 64 KiB in a tool-results sidecar so blob delivery runs, one completed subagent spawn so all four tables carry
rows) to a temp dir, drives Stop (polling state.json for the detached pass) then SessionEnd with crafted stdin, reads back
with telemetry_probe and compares per-table rows with what record_turn built. Then deletes the cursor and replays both
entry points: per table, run 2 submits run 1's total and inserts 0. Prints counts and PASS/FAIL lines only.

The record shapes are copied from tests/fixtures/turn_capture_corpus.py (scripts/ never imports tests/).
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.telemetry_capture.runner import SnapshotTree
from scripts.telemetry_capture.state import CaptureState, state_dir
from scripts.telemetry_capture.switch import SMOKE_ENV
from scripts.telemetry_capture.transport import MAX_TIMEOUT_S, Budget, WriterClient, make_client
from src.turn_capture.record_turn import TABLES, record_turn
from src.turn_capture.render import render_datetime

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS = REPO_ROOT / ".claude" / "hooks"
SIDECAR = "big1.txt"
SIDECAR_LINE = "pc smoke sidecar output line\n"
SIDECAR_LINES = 2600
POLL_S = 60.0
Entry = Callable[[str, Mapping[str, str]], object]


class SmokeFailure(Exception):
    pass


def _records(sid: str, ref: str, start: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def stamp(seconds: float) -> str:
        return render_datetime(start + timedelta(seconds=seconds))

    def base(rec_uuid: str, t: float, **extra: Any) -> dict[str, Any]:
        rec = {"uuid": rec_uuid, "timestamp": stamp(t), "sessionId": sid, "gitBranch": "smoke", "version": "2.1.0"}
        return {**rec, "cwd": "/smoke", **extra}

    def reply(
        rec_uuid: str, t: float, mid: str, blocks: list[dict[str, Any]], stop: str | None = "end_turn", **extra: Any
    ) -> dict[str, Any]:
        usage: dict[str, Any] = {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 40,
        }
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": 15, "ephemeral_5m_input_tokens": 25}
        message: dict[str, Any] = {"id": mid, "type": "message", "role": "assistant", "model": "claude-smoke-1"}
        message["content"] = blocks
        message.update(stop_reason=stop, usage=usage)
        extra = {"requestedModel": "claude-smoke-1[1m]", "effort": "high", **extra}
        return base(rec_uuid, t, type="assistant", message=message, requestId="req_" + mid, **extra)

    def tool_use(tool_id: str, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input, "caller": {"type": "direct"}}

    def result(rec_uuid: str, t: float, tool_id: str, content: str, use_result: dict[str, Any]) -> dict[str, Any]:
        block = {"tool_use_id": tool_id, "type": "tool_result", "content": content}
        message = {"role": "user", "content": [block]}
        return base(rec_uuid, t, type="user", message=message, promptId="p1", toolUseResult=use_result)

    command = f'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session_start_log_turn.sh" --project-ref={ref}'
    facts = f"checkout={'1' * 40} base={'2' * 40} dirty=false"
    stderr = f"[session_start_log_turn] capture pin {facts}\n"
    pin = {"type": "hook_success", "hookName": "SessionStart:startup", "hookEvent": "SessionStart", "exitCode": 0}
    pin["stderr"] = stderr
    remote = {"type": "remote_session_change", "url": "https://example.invalid/code/session_smoke0000"}
    spawn_usage: dict[str, Any] = {
        "input_tokens": 10,
        "output_tokens": 25,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 40,
    }
    spawn_usage["cache_creation"] = {"ephemeral_1h_input_tokens": 15, "ephemeral_5m_input_tokens": 25}
    persisted = {"interrupted": False, "persistedOutputPath": f"/elsewhere/tool-results/{SIDECAR}", "stdout": "preview"}
    persisted["persistedOutputSize"] = len(SIDECAR_LINE) * SIDECAR_LINES
    root = [
        base("h1", 0, type="attachment", attachment={**pin, "command": command}),
        base("rs1", 0.5, type="attachment", attachment=remote),
        base("u1", 1, type="user", promptId="p1", message={"role": "user", "content": "run the smoke"}),
        reply("a1", 2, "m1", [tool_use("tu1", "Bash", {"command": "cat big"})]),
        result("r1", 3, "tu1", "preview", persisted),
        reply("a2", 4, "m2", [tool_use("tuA", "Agent", {"description": "d", "prompt": "p", "subagent_type": "Explore"})]),
        result(
            "r2",
            6,
            "tuA",
            "child done",
            {"agentId": "agent1", "isAsync": False, "status": "completed", "usage": spawn_usage},
        ),
        reply("a3", 7, "m3", [{"type": "text", "text": "smoke done"}]),
    ]
    child = {"agentId": "agent1", "isSidechain": True}
    children = [
        base("c1", 4.5, type="user", promptId="p1", message={"role": "user", "content": "task"}, **child),
        reply("c2", 5, "mc1", [{"type": "text", "text": "child work"}], None, **child),
    ]
    return root, children


def write_tree(directory: Path, ref: str, *, start: datetime | None = None) -> Path:
    """The synthetic tree under directory; returns its root .jsonl path."""
    sid = str(uuid.uuid4())
    root, children = _records(sid, ref, start or datetime.now(timezone.utc).replace(microsecond=0))
    session = directory / sid
    (session / "subagents").mkdir(parents=True)
    (session / "tool-results").mkdir()
    (session / "tool-results" / SIDECAR).write_text(SIDECAR_LINE * SIDECAR_LINES, encoding="utf-8")
    body = "".join(json.dumps(rec, sort_keys=True) + "\n" for rec in children)
    (session / "subagents" / "agent-agent1.jsonl").write_text(body, encoding="utf-8")
    root_file = directory / f"{sid}.jsonl"
    root_file.write_text("".join(json.dumps(rec, sort_keys=True) + "\n" for rec in root), encoding="utf-8")
    return root_file


def expected_by_ref(root_file: Path, ref: str) -> dict[str, dict[str, int]]:
    """What record_turn builds over the Stop pass then the SessionEnd pass, per session ref (root and sub-agents) and table."""
    first = record_turn(SnapshotTree(root_file), None, project_ref=ref)
    second = record_turn(SnapshotTree(root_file), first.next_cursor, project_ref=ref, session_final=True)
    counts: dict[str, Counter[str]] = {}
    for result in (first, second):
        for table, rows in result.batches:
            for row in rows:
                owner = row["entity_ref"] if table == "telemetry_sessions" else row["session_ref"]
                counts.setdefault(owner, Counter(dict.fromkeys(TABLES, 0)))[table] += 1
    return {owner: dict(per_table) for owner, per_table in counts.items()}


def expected_rows(root_file: Path, ref: str) -> dict[str, int]:
    """The per-table totals of expected_by_ref."""
    total = Counter(dict.fromkeys(TABLES, 0))
    for per_table in expected_by_ref(root_file, ref).values():
        total.update(per_table)
    return dict(total)


def hook_entry(script: Path) -> Entry:
    def run(stdin_text: str, env: Mapping[str, str]) -> object:
        return subprocess.run(
            [sys.executable, str(script)],
            input=stdin_text,
            env=dict(env),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

    return run


def _ok(client: WriterClient, payload: dict[str, Any]) -> Mapping[str, Any]:
    status, body = client.invoke(payload)
    if status != 200 or not isinstance(body, Mapping) or body.get("ok") is not True:
        error = body.get("error_type") if isinstance(body, Mapping) else None
        raise SmokeFailure(f"{payload['action']} status={status} error_type={error}")
    return body


def _submitted(lines: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str]]:
    submitted: Counter[str] = Counter()
    inserted: Counter[str] = Counter()
    for line in lines:
        for request in line.get("requests") or []:
            for table, numbers in request.items():
                submitted[table] += numbers.get("submitted", 0)
                inserted[table] += numbers.get("inserted", 0)
    return submitted, inserted


def _no_halt(state: CaptureState) -> None:
    halt = state.halt()
    if halt is not None:
        raise SmokeFailure("halt recorded: " + json.dumps(halt, sort_keys=True))


class Smoke:
    def __init__(
        self,
        *,
        client_factory: Callable[[], WriterClient],
        stop: Entry,
        session_end: Entry,
        env: Mapping[str, str],
        out: Callable[[str], object] = print,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_s: float = POLL_S,
    ) -> None:
        self.client_factory, self.stop, self.session_end, self.env = client_factory, stop, session_end, env
        self.out, self.sleep, self.clock, self.poll_s = out, sleep, clock, poll_s

    def _drive(self, root_file: Path, state: CaptureState) -> list[dict[str, Any]]:
        before = len(state.diagnostics())
        sid = root_file.stem
        common = {"session_id": sid, "transcript_path": str(root_file), "cwd": str(REPO_ROOT)}
        self.stop(json.dumps({**common, "hook_event_name": "Stop", "stop_hook_active": False}), self.env)
        end = self.clock() + self.poll_s
        while len(state.diagnostics()) <= before:
            if self.clock() >= end:
                raise SmokeFailure("the detached Stop pass did not finish")
            self.sleep(0.5)
        _no_halt(state)
        if not state.state_file.exists():
            raise SmokeFailure(f"the Stop pass wrote no cursor (outcome {state.diagnostics()[-1].get('outcome')})")
        self.session_end(json.dumps({**common, "hook_event_name": "SessionEnd", "reason": "other"}), self.env)
        _no_halt(state)
        return state.diagnostics()[before:]

    def run(self, ref: str, directory: Path) -> None:
        client = self.client_factory()
        _ok(client, {"action": "register_tenant"})
        _ok(client, {"action": "register_project", "project_ref": ref, "name": "pc smoke"})
        root_file = write_tree(directory, ref)
        state = CaptureState(state_dir(root_file, root_file.stem))
        first = self._drive(root_file, state)
        cursor = state.cursor_on_disk()
        if cursor is None or not cursor.finalized:
            raise SmokeFailure("the SessionEnd pass did not finalize the cursor")
        started = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=cursor.session_started_at_ms)
        by_ref = expected_by_ref(root_file, ref)
        expected = expected_rows(root_file, ref)
        read_back: Counter[str] = Counter()
        for session_ref, wanted in by_ref.items():
            probe = {"action": "telemetry_probe", "project_ref": ref, "session_ref": session_ref}
            counts = _ok(self.client_factory(), {**probe, "session_started_at": render_datetime(started)}).get("grain_counts")
            if not isinstance(counts, Mapping):
                raise SmokeFailure("telemetry_probe returned no grain counts")
            for table in TABLES:
                rows = (counts.get(table) or {}).get("rows")
                if rows != wanted[table]:
                    read_back[table] = -1
                    self.out(f"{table} built={wanted[table]} read_back={rows} for one session ref")
                elif read_back[table] >= 0:
                    read_back[table] += rows
        for table in TABLES:
            self.out(f"{table} built={expected[table]} read_back={read_back[table]}")
            if not expected[table] or read_back[table] != expected[table]:
                raise SmokeFailure(f"{table} read-back differs from what record_turn built")
        blobs = sum(line.get("diag", {}).get(k, 0) for line in first for k in ("blobs_uploaded", "blobs_existed"))
        self.out(f"blob rows delivered={blobs}")
        if blobs < 1:
            raise SmokeFailure("no blob row was delivered")
        run1, _ = _submitted(first)
        state.state_file.unlink()
        run2, inserted = _submitted(self._drive(root_file, state))
        for table in TABLES:
            self.out(f"{table} replay submitted={run2[table]} first={run1[table]} inserted={inserted[table]}")
            if run2[table] != run1[table] or inserted[table] != 0:
                raise SmokeFailure(f"{table} replay was not an identical-resend no-op")


def main(argv: list[str] | None = None) -> int:
    del argv
    ref = f"synthetic:pc-smoke-{secrets.token_hex(4)}"
    env = {**os.environ, SMOKE_ENV: ref}
    smoke = Smoke(
        client_factory=lambda: make_client(env, None, Budget.start(MAX_TIMEOUT_S)),
        stop=hook_entry(HOOKS / "stop_log_turn.py"),
        session_end=hook_entry(HOOKS / "session_end_log_turn.py"),
        env=env,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="pc-smoke-") as tmp:
            smoke.run(ref, Path(tmp))
    except Exception as exc:  # noqa: BLE001 -- one FAIL line naming the reason, never a payload
        reason = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
        print(f"PC_SMOKE FAIL {reason}")
        return 1
    print("PC_SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
