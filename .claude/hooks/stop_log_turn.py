#!/usr/bin/env python3
"""Stop and StopFailure capture shim (PLAN-telemetry-capture-hooks rule HK-3).

Reads the hook JSON from stdin and exits 0 at once when stop_hook_active is true, when the switch or a guard says no
(rule SW-1), or on any error; otherwise starts the capture runner fully detached (own session, /dev/null descriptors)
and exits 0 without waiting. Never runs a pass in the hook process and prints nothing on any path. The switch is checked
before any import beyond the stdlib and yaml. RUNNER_MODULE is a constant: no environment variable redirects it.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_MODULE = "scripts.telemetry_capture"


def _hook_fields(stdin_text: str) -> tuple[str, str, str] | None:
    payload = json.loads(stdin_text)
    if not isinstance(payload, dict) or payload.get("stop_hook_active") is True:
        return None
    fields = (payload.get("hook_event_name"), payload.get("transcript_path"), payload.get("session_id"))
    if not all(isinstance(value, str) and value for value in fields):
        return None
    return fields  # type: ignore[return-value]


def main(
    stdin_text: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path = REPO_ROOT,
    detach: Callable[[Sequence[str], Mapping[str, str]], object] | None = None,
) -> int:
    try:
        fields = _hook_fields(sys.stdin.read() if stdin_text is None else stdin_text)
        if fields is None:
            return 0
        environ = os.environ if env is None else env
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from scripts.telemetry_capture import switch  # noqa: PLC0415

        if not switch.capture_allowed(environ, repo_root):
            return 0
        event, transcript, session_id = fields
        args = ["--event", event, "--transcript", transcript, "--session-id", session_id]
        if detach is not None:
            detach(args, environ)
        else:
            from scripts.telemetry_capture import detach_runner  # noqa: PLC0415

            detach_runner(RUNNER_MODULE, args, repo_root, env=None if env is None else env)
    except Exception:  # noqa: BLE001, S110 -- the hook exits 0 silently on every path
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
