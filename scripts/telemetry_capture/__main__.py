"""`python -m scripts.telemetry_capture <cmd>`: the runner entry the hooks detach (`run`) and the operator CLI (rule OP-1).

run (silent, exit 0 always); pass --tree [--final]; status --tree; probe --tree [--require t1,t2]; observe --tree;
mark --tree; clear-halt --tree; register --project-ref --name --remote. No sweep exists: a pass starts on a tree only
through its own hook or an explicit --tree. Operator output is counts and fixed tokens, never content or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.telemetry_capture.runner import STOP_BUDGET_S, ClientFactory, default_client_factory, run_pass
from scripts.telemetry_capture.state import CaptureState, state_dir
from scripts.telemetry_capture.transport import MAX_TIMEOUT_S, Budget, CaptureUnavailable
from src.turn_capture.render import render_datetime
from src.turn_capture.transcript import PIN_SCRIPT_STEM, ROOT, FsTree, hook_script, project_ref_pin, read_lines, record_time

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
OK_OUTCOMES = ("sent", "no_rows")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.telemetry_capture")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--event", required=True)
    run.add_argument("--transcript", required=True)
    run.add_argument("--session-id", required=True)
    run.add_argument("--final", action="store_true")
    run.add_argument("--lock-wait", type=float, default=0.0)
    for name in ("pass", "status", "probe", "observe", "mark", "clear-halt"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--tree", required=True, type=Path)
        if name == "pass":
            cmd.add_argument("--final", action="store_true")
        if name == "probe":
            cmd.add_argument("--require", default="")
    register = sub.add_parser("register")
    register.add_argument("--project-ref", required=True)
    register.add_argument("--name", required=True)
    register.add_argument("--remote", required=True)
    return parser


def _state(tree: Path) -> CaptureState:
    return CaptureState(state_dir(tree, tree.stem))


def _cmd_run(args: argparse.Namespace, env: Mapping[str, str], repo_root: Path, factory: ClientFactory) -> int:
    try:
        run_pass(
            Path(args.transcript),
            args.session_id,
            args.event,
            final=args.final,
            budget=Budget.start(args.lock_wait + STOP_BUDGET_S),
            env=env,
            repo_root=repo_root,
            client_factory=factory,
            lock_wait=args.lock_wait,
        )
    except Exception:  # noqa: BLE001 -- the detached runner is silent on every path
        pass
    return 0


def _cmd_pass(args: argparse.Namespace, env: Mapping[str, str], repo_root: Path, factory: ClientFactory, out: Callable) -> int:
    if project_ref_pin(FsTree(args.tree)) is None:
        out("refused: the tree has no pinning SessionStart attachment")
        return 1
    result = run_pass(
        args.tree,
        args.tree.stem,
        "operator",
        final=args.final,
        budget=Budget.start(STOP_BUDGET_S),
        env=env,
        repo_root=repo_root,
        client_factory=factory,
    )
    out(json.dumps({"outcome": result.outcome, "rows": result.diag.get("rows", {}), "diag": result.diag.get("diag", {})}))
    return 0 if result.outcome in OK_OUTCOMES else 1


def _cmd_status(args: argparse.Namespace, out: Callable) -> int:
    state = _state(args.tree)
    cursor = state.cursor_on_disk()
    last = (state.diagnostics() or [{}])[-1]
    summary = {
        "lines_consumed": cursor.lines_consumed if cursor else None,
        "finalized": cursor.finalized if cursor else None,
        "finalize_cuts": len(cursor.finalize_cuts) if cursor else None,
        "halt": state.halt(),
        "last": {k: last[k] for k in ("event", "outcome", "rows", "requests", "diag") if k in last},
    }
    out(json.dumps(summary, sort_keys=True))
    return 0


def _cmd_probe(args: argparse.Namespace, env: Mapping[str, str], factory: ClientFactory, out: Callable) -> int:
    state = _state(args.tree)
    cursor = state.cursor_on_disk()
    if cursor is None:
        out("probe: no cursor for this tree")
        return 1
    started = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=cursor.session_started_at_ms)
    try:
        client = factory(env, state, Budget.start(MAX_TIMEOUT_S))
        status, body = client.invoke(
            {
                "action": "telemetry_probe",
                "project_ref": cursor.project_ref,
                "session_ref": cursor.root_session_ref,
                "session_started_at": render_datetime(started),
            }
        )
    except CaptureUnavailable as exc:
        out(f"probe: {exc.reason}")
        return 1
    counts = body.get("grain_counts") if status == 200 and isinstance(body, Mapping) else None
    if not isinstance(counts, Mapping):
        out(f"probe: status {status}, no grain counts")
        return 1
    for table in sorted(counts):
        out(f"{table} rows={counts[table].get('rows')} keys={counts[table].get('keys')}")
    required = [t for t in args.require.split(",") if t]
    short = [t for t in required if not (counts.get(t) or {}).get("rows")]
    halt = state.halt()
    if halt is not None:
        out("probe: halt recorded")
    if short:
        out("probe: zero rows in " + ",".join(short))
    return 1 if short or halt is not None else 0


def _prefix_sha(tree: Path, size: int) -> str | None:
    try:
        with tree.open("rb") as handle:
            data = handle.read(size)
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest() if len(data) == size else None


def _boot_id(boot_id: Path) -> str | None:
    try:
        return boot_id.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _cmd_mark(args: argparse.Namespace, out: Callable, boot_id: Path) -> int:
    state = _state(args.tree)
    size = args.tree.stat().st_size
    marker = {"boot_id": _boot_id(boot_id), "prefix_bytes": size, "prefix_sha256": _prefix_sha(args.tree, size)}
    state.write_marker(marker)
    out(f"mark: written prefix_bytes={size}")
    return 0


def _late_sidecars(tree: Path) -> tuple[int, int]:
    """(sidecars whose mtime is later than their tool_result record's timestamp, sidecars seen)."""
    files = [tree, *sorted((tree.parent / tree.stem / "subagents").glob("agent-*.jsonl"))]
    late = seen = 0
    for path in files:
        for item in read_lines(path.read_bytes() if path.is_file() else b""):
            info = item.data.get("toolUseResult") if item.data is not None else None
            persisted = info.get("persistedOutputPath") if isinstance(info, dict) else None
            when = record_time(item.data) if item.data is not None else None
            if not isinstance(persisted, str) or when is None:
                continue
            sidecar = tree.parent / tree.stem / "tool-results" / persisted.rsplit("/", 1)[-1]
            if sidecar.is_file():
                seen += 1
                late += int(sidecar.stat().st_mtime > when.timestamp())
    return late, seen


def _cmd_observe(args: argparse.Namespace, out: Callable, boot_id: Path) -> int:
    sources: Counter[str] = Counter()
    for item in read_lines(FsTree(args.tree).read(ROOT) or b""):
        att = item.data.get("attachment") if item.data is not None else None
        if not isinstance(att, dict) or att.get("hookEvent") != "SessionStart":
            continue
        if hook_script(att.get("command"))[0] == PIN_SCRIPT_STEM:
            sources[str(att.get("hookName") or "SessionStart").partition(":")[2] or "unknown"] += 1
    state = _state(args.tree)
    late, seen = _late_sidecars(args.tree)
    ends = sum(1 for line in state.diagnostics() if line.get("event") == "SessionEnd")
    out(json.dumps({"session_start_by_source": dict(sorted(sources.items())), "session_end_passes": ends}, sort_keys=True))
    out(f"tool_results_sidecars late={late} seen={seen}")
    marker = state.marker()
    if marker is None:
        out("reclaim: unproven (no marker)")
        return 0
    now = _boot_id(boot_id)
    reclaimed = now is not None and marker.get("boot_id") is not None and now != marker.get("boot_id")
    prefix_equal = _prefix_sha(args.tree, int(marker.get("prefix_bytes") or 0)) == marker.get("prefix_sha256")
    if not reclaimed:
        out(f"reclaim: no reclaim seen, unproven; marker_present=True prefix_hash_equal={prefix_equal}")
    else:
        out(f"reclaim: boot_id_changed=True marker_present=True prefix_hash_equal={prefix_equal}")
    return 0


def _cmd_clear_halt(args: argparse.Namespace, out: Callable) -> int:
    out("clear-halt: cleared" if _state(args.tree).clear_halt() else "clear-halt: no halt recorded")
    return 0


def _cmd_register(args: argparse.Namespace, env: Mapping[str, str], factory: ClientFactory, out: Callable) -> int:
    try:
        client = factory(env, None, Budget.start(MAX_TIMEOUT_S))
    except CaptureUnavailable as exc:
        out(f"register: {exc.reason}")
        return 1
    for payload in (
        {"action": "register_tenant"},
        {"action": "register_project", "project_ref": args.project_ref, "name": args.name, "remote": args.remote},
    ):
        status, body = client.invoke(payload)
        ok = status == 200 and isinstance(body, Mapping) and body.get("ok") is True
        created = body.get("created") if ok else None
        error = body.get("error_type") if isinstance(body, Mapping) else None
        out(f"{payload['action']}: " + (f"ok created={created}" if ok else f"failed status={status} error_type={error}"))
        if not ok:
            return 1
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path = REPO_ROOT,
    client_factory: ClientFactory = default_client_factory,
    out: Callable[[str], Any] = print,
    boot_id: Path = BOOT_ID,
) -> int:
    args = _parser().parse_args(argv)
    environ = dict(os.environ) if env is None else env
    if args.cmd == "run":
        return _cmd_run(args, environ, repo_root, client_factory)
    if args.cmd == "pass":
        return _cmd_pass(args, environ, repo_root, client_factory, out)
    if args.cmd == "status":
        return _cmd_status(args, out)
    if args.cmd == "probe":
        return _cmd_probe(args, environ, client_factory, out)
    if args.cmd == "observe":
        return _cmd_observe(args, out, boot_id)
    if args.cmd == "mark":
        return _cmd_mark(args, out, boot_id)
    if args.cmd == "clear-halt":
        return _cmd_clear_halt(args, out)
    return _cmd_register(args, environ, client_factory, out)


if __name__ == "__main__":
    sys.exit(main())
