"""Backlog-health bounded probe runner (PLAN-backlog-health-detection).

THE SOLE EXECUTOR OF REC-AUTHORED COMMANDS in this package (VP step 14 / the AST invariant that
enforces it): every OTHER module in scripts/backlog_health/** must never import or call
`scripts.rec_relevance._run_acceptance_probe`, must never pass `run_acceptance_probe` as anything
but the literal `False`, and must never reach `subprocess`/`os.system`/`os.popen` with a non-
constant-foldable argv. This module is the one deliberate exception, and only for commands
census.py has already classified `probeable` -- never `unprobeable_unsafe`, `unprobeable_shape`,
`prose_only` or `expected_fail_missing_node`.

Each command runs under `unshare -rmn` (new user/mount/net namespaces, current user mapped to
root inside) with a read-only self-bind-mount of the checkout, a `ulimit -u` pid cap, and
PYTHONPYCACHEPREFIX / PYTEST_ADDOPTS redirected to a per-probe scratch dir so pytest's own cache
writes never touch the read-only tree. Network is unreachable inside the new net namespace by
construction (no interface beyond loopback).

Five verdicts, NEVER a silent pass: PASS/FAIL/TIMEOUT come from actually running the command;
BUDGET_EXHAUSTED means the global wall-clock budget ran out before this entry's turn; and
ISOLATION_UNAVAILABLE means the unshare/bind-mount primitive itself failed to engage on this
runner (Ubuntu 24.04 can restrict unprivileged user namespaces via AppArmor) -- when that
happens EVERY entry gets ISOLATION_UNAVAILABLE and NONE is attempted, so a missing sandbox can
never present as a real (and falsely reassuring) result.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

PASS = "pass"
FAIL = "fail"
TIMEOUT = "timeout"
BUDGET_EXHAUSTED = "budget_exhausted"
ISOLATION_UNAVAILABLE = "isolation_unavailable"

VERDICTS: frozenset[str] = frozenset({PASS, FAIL, TIMEOUT, BUDGET_EXHAUSTED, ISOLATION_UNAVAILABLE})

_DEFAULT_TIMEOUT_S = 10
_PYTEST_TIMEOUT_S = 30
_DEFAULT_GLOBAL_BUDGET_S = 25 * 60  # inside the workflow's 30-minute job timeout, leaving margin
_PID_CAP = 64

_PYTEST_RE = re.compile(r"\bpytest\b")


def is_pytest_command(cmd: str) -> bool:
    return bool(_PYTEST_RE.search(cmd))


def isolation_available(runner: Callable[..., Any] = subprocess.run) -> bool:
    """Probe unshare -rmn plus a read-only self-bind-mount, the exact primitive run_one relies
    on. Never raises: any exception, timeout, or non-zero exit means unavailable."""
    try:
        result = runner(
            ["unshare", "-rmn", "--", "bash", "-c", "mount --bind -o ro / / && true"],
            capture_output=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _isolated_argv(cmd: str, repo_root: Path, pid_cap: int) -> list[str]:
    inner = f"mount --bind -o ro {repo_root} {repo_root} && ulimit -u {pid_cap} && exec {cmd}"
    return ["unshare", "-rmn", "--", "bash", "-c", inner]


def _probe_env(scratch: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = str(scratch / "pyc")
    env["PYTEST_ADDOPTS"] = f"-o cache_dir={scratch / 'pytest_cache'}"
    return env


def run_one(
    cmd: str,
    *,
    repo_root: Path,
    timeout: Optional[int] = None,
    pid_cap: int = _PID_CAP,
    runner: Callable[..., Any] = subprocess.run,
) -> str:
    """Execute one already-classified-`probeable` command under isolation.

    Returns PASS/FAIL/TIMEOUT only -- BUDGET_EXHAUSTED and ISOLATION_UNAVAILABLE are decided by
    the caller (run_all) before any individual probe is attempted. Any launch error (OSError) or
    a non-zero exit is FAIL, never silently treated as PASS.
    """
    eff_timeout = timeout if timeout is not None else (_PYTEST_TIMEOUT_S if is_pytest_command(cmd) else _DEFAULT_TIMEOUT_S)
    with tempfile.TemporaryDirectory(prefix="backlog_health_probe_") as scratch_dir:
        scratch = Path(scratch_dir)
        argv = _isolated_argv(cmd, repo_root, pid_cap)
        try:
            result = runner(
                argv,
                cwd=str(repo_root),
                capture_output=True,
                timeout=eff_timeout,
                encoding="utf-8",
                errors="replace",
                env=_probe_env(scratch),
            )
        except subprocess.TimeoutExpired:
            return TIMEOUT
        except OSError:
            return FAIL
    return PASS if result.returncode == 0 else FAIL


def run_all(
    probe_payload: list[dict[str, Any]],
    *,
    repo_root: Path,
    main_sha: str,
    global_budget_s: int = _DEFAULT_GLOBAL_BUDGET_S,
    runner: Callable[..., Any] = subprocess.run,
    isolation_check: Callable[[], bool] = isolation_available,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run every `probe_payload` entry (as emitted by census.run_census), bounded by a global
    wall-clock budget. Returns {"main_sha": str, "isolation_available": bool, "verdicts":
    {rec_id: verdict}} -- `main_sha` is stamped unconditionally, since a vacuity verdict is
    meaningless without the tree it was measured against.

    If isolation is unavailable, no entry is ever attempted -- every entry gets
    ISOLATION_UNAVAILABLE. Once the global budget is exhausted, every REMAINING entry (not yet
    started) gets BUDGET_EXHAUSTED rather than being silently dropped.
    """
    if not isolation_check():
        return {
            "main_sha": main_sha,
            "isolation_available": False,
            "verdicts": {entry["id"]: ISOLATION_UNAVAILABLE for entry in probe_payload},
        }

    verdicts: dict[str, str] = {}
    start = clock()
    for entry in probe_payload:
        if clock() - start >= global_budget_s:
            verdicts[entry["id"]] = BUDGET_EXHAUSTED
            continue
        verdicts[entry["id"]] = run_one(entry["acceptance"], repo_root=repo_root, runner=runner)
    return {"main_sha": main_sha, "isolation_available": True, "verdicts": verdicts}
