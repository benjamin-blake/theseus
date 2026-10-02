"""claude -p retry wrapper enforcement (Decision 73, Decision 92)."""

from __future__ import annotations

from pathlib import Path

from scripts.checks import _common, registry


def _scan_claude_p_raw_invocations(workflows_root: Path) -> tuple[list[str], int]:
    """Return (violations, workflow files read) for unwrapped `claude -p` lines in CI workflow files.

    Skips blank lines, YAML/shell comments (leading #), `command -v claude` presence
    checks, and `claude --version` calls. Parity with _TRANSIENT_CLAUDE_SIGNATURES.
    An unreadable file is skipped and not counted as read.
    """
    violations = []
    read = 0
    for wf_path in sorted(workflows_root.glob("*.yml")):
        try:
            lines = wf_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        read += 1
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "command -v claude" in line or "claude --version" in line:
                continue
            if "claude -p" in line and "claude_p_retry.sh" not in line:
                violations.append(f"{wf_path.name}:{lineno}: unwrapped `claude -p` invocation")
    return violations, read


def _check_claude_p_raw_invocations(workflows_root: Path) -> list[str]:
    """Return violation strings for unwrapped `claude -p` lines in CI workflow files."""
    return _scan_claude_p_raw_invocations(workflows_root)[0]


@registry.register("validate_claude_p_retry_wrapper", owner="platform")
def validate_claude_p_retry_wrapper(failed: list[str]) -> None:
    """Enforce that every `claude -p` invocation in CI workflows routes through scripts/ci/claude_p_retry.sh.

    Parity with _TRANSIENT_CLAUDE_SIGNATURES (this file) and scripts/ci/claude_p_retry.sh.
    Decision 73: validate.py is the single source of truth for CI checks. Decision 92.
    Declares examined(.github/workflows/*.yml files read, unit="workflow_files") (Decision 170).
    """
    print("\n=== claude -p retry wrapper enforcement ===")
    violations, read = _scan_claude_p_raw_invocations(_common.ROOT / ".github" / "workflows")
    registry.examined(read, unit="workflow_files")
    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
            failed.append(f"claude_p_retry wrapper: {v}")
    else:
        print("  PASS: all claude -p invocations route through scripts/ci/claude_p_retry.sh")
