"""Shared accept/reject vectors for the telemetry_observations process_event name grammar (Decision 210 cl.3).

Data only. The regex itself lives in the contract; tests read it from there and these vectors pin its behaviour.
"""

from __future__ import annotations

ACCEPT: tuple[str, ...] = (
    "hook:unknown",
    "hook:never_on_main",
    "hook:PreToolUse.mcp__github-full__create_pull_request",
    "gate:validate_scope_boundary",
    "precommit:ruff-format",
    "hook:" + "a" * 200,
)
REJECT: tuple[str, ...] = (
    "never_on_main",
    "Bash",
    "Hook:x",
    "hook:",
    "hook:a b",
    "hook:x:y",
    "hook:.foo",
    "hooks:x",
    "gate:x/y",
    "edit:suppression_added",
    "hook:café",
    "hook:" + "a" * 201,
    "hook:x\n",
)
