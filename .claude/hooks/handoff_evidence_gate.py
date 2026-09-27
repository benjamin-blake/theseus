#!/usr/bin/env python3
"""PreToolUse hook adapter for the handoff evidence gate -- PLUMBING ONLY (Decision 162).

Reads the JSON payload from stdin, routes it to scripts.session.handoff_push_parse and
scripts.session.handoff_evidence, and prints the outcome per the Claude Code hooks contract:
pass -> exit 0, no stdout; deny -> exit 2 with "handoff-evidence-gate: <rule>: <message>" on
stderr; warn -> exit 0 printing a hookSpecificOutput JSON object with additionalContext (reaches
Claude) and systemMessage (reaches the user), and NEVER a permissionDecision. All classification
and decision logic lives in scripts/session/ -- this file never re-implements it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_MCP_TOOLS = {
    "mcp__github__create_pull_request",
    "mcp__github__push_files",
    "mcp__github__create_or_update_file",
    "mcp__github__delete_file",
    "mcp__github-full__create_pull_request",
    "mcp__github-full__push_files",
    "mcp__github-full__create_or_update_file",
    "mcp__github-full__delete_file",
}


def _print_warn(message: str) -> None:
    print(
        json.dumps(
            {
                "systemMessage": message,
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": message,
                },
            }
        )
    )


def _handle_bash(tool_input: dict) -> int:
    from scripts.session.handoff_evidence import decide_bash
    from scripts.session.handoff_push_parse import is_push_shaped, parse_canonical

    command = tool_input.get("command") or ""
    if not command:
        return 0
    if not is_push_shaped(command):
        return 0

    parsed = parse_canonical(command)
    verdict = decide_bash(parsed, Path.cwd())
    if verdict.kind == "deny":
        sys.stderr.write(f"handoff-evidence-gate: {verdict.rule}: {verdict.message}\n")
        return 2
    if verdict.kind == "warn":
        _print_warn(f"handoff-evidence-gate: {verdict.rule}: {verdict.message}")
    return 0


def _handle_mcp(tool_name: str, tool_input: dict) -> int:
    from scripts.checks import _common
    from scripts.session.handoff_evidence import decide_pr, decide_remote_write

    if tool_name.endswith("create_pull_request"):
        head = tool_input.get("head") or ""
        verdict = decide_pr(Path.cwd(), head, _common.ROOT)
    else:
        branch = tool_input.get("branch") or ""
        if tool_name.endswith("delete_file"):
            paths = [tool_input.get("path") or ""]
        elif tool_name.endswith("create_or_update_file"):
            paths = [tool_input.get("path") or ""]
        else:  # push_files
            files = tool_input.get("files") or []
            paths = [f.get("path") or "" for f in files if isinstance(f, dict)]
        verdict = decide_remote_write(_common.ROOT, branch, [p for p in paths if p])

    if verdict.kind == "deny":
        sys.stderr.write(f"handoff-evidence-gate: {verdict.rule}: {verdict.message}\n")
        return 2
    if verdict.kind == "warn":
        _print_warn(f"handoff-evidence-gate: {verdict.rule}: {verdict.message}")
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}

        if tool_name in ("Bash", "Monitor"):
            return _handle_bash(tool_input)
        if tool_name in _MCP_TOOLS:
            return _handle_mcp(tool_name, tool_input)
        return 0
    except Exception as exc:  # noqa: BLE001 - main() wraps everything, fail closed
        sys.stderr.write(f"handoff gate error: {type(exc).__name__}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
