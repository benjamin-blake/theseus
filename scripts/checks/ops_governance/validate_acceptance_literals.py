"""Repo-wide static acceptance-literal lint guard (rec-2772, PLAN-escalation-acceptance-lint).

Closes the defect class rather than the five known instances: any programmatic rec-filing site
under scripts/ or personal_scripts/ that hardcodes a lint-invalid "acceptance" dict-literal value
now fails validate.py, instead of silently shipping a rec no executor or human can ever satisfy.

Syntactic walk, not a rec-filing-site prover: it lints every statically-resolvable "acceptance"
dict-literal value under the scanned trees, whether or not the enclosing dict is actually a
file_rec/update_rec payload (verified harmless at planning time -- a dry run over scripts/ found
exactly the 5 known-bad sites, no collateral red; the live resolvable-literal count is what the check
declares via examined(), never a figure pinned here). Values that cannot
be statically resolved (a variable, a function call, an f-string with a non-constant format spec)
are skipped rather than guessed at.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from scripts.checks import _common, registry
from scripts.executor.acceptance_lint import lint_acceptance_command

_PLACEHOLDER = "<EXPR>"


def _resolve_string_value(node: ast.expr) -> Optional[str]:
    """Resolve a statically-known string from a Constant or JoinedStr (f-string) node.

    Adjacent string literals ("a" "b") are already folded into a single Constant by the
    parser, so no separate concatenation handling is needed. A JoinedStr's FormattedValue
    segments (the {expr} parts of an f-string) are substituted with a placeholder token so the
    surrounding literal text is still lint-checked structurally, even though the interpolated
    value itself is not known statically. Any other node shape (Name, Call, BinOp, ...)
    returns None -- skip rather than guess.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for segment in node.values:
            if isinstance(segment, ast.Constant) and isinstance(segment.value, str):
                parts.append(segment.value)
            elif isinstance(segment, ast.FormattedValue):
                parts.append(_PLACEHOLDER)
            else:
                return None
        return "".join(parts)
    return None


def _scan_file(path: Path) -> tuple[list[str], int]:
    """Return (violations, number of statically-resolved acceptance literals linted)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], 0
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return [], 0

    rel = path.relative_to(_common.ROOT)
    violations: list[str] = []
    linted = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "acceptance"):
                continue
            resolved = _resolve_string_value(value)
            if resolved is None:
                continue
            linted += 1
            ok, msg = lint_acceptance_command(resolved)
            if not ok:
                lineno = getattr(value, "lineno", node.lineno)
                first_line = (msg or "").strip().splitlines()[0] if msg else "lint failed"
                violations.append(f"{rel}:{lineno}: acceptance literal fails lint_acceptance_command -- {first_line}")
    return violations, linted


def _find_violations() -> tuple[list[str], int]:
    search_dirs = [_common.ROOT / "scripts"]
    personal_dir = _common.ROOT / "personal_scripts"
    if personal_dir.exists():
        search_dirs.append(personal_dir)

    violations: list[str] = []
    linted = 0
    for search_dir in search_dirs:
        for py_file in sorted(search_dir.glob("**/*.py")):
            file_violations, file_linted = _scan_file(py_file)
            violations.extend(file_violations)
            linted += file_linted
    return violations, linted


@registry.register("validate_acceptance_literals", owner="platform")
def validate_acceptance_literals(failed: list[str]) -> None:
    """Fail any statically-resolvable "acceptance" dict-literal value under scripts/ or
    personal_scripts/ that does not pass lint_acceptance_command (rec-2772)."""
    print("\n=== Acceptance literal lint ===")
    violations, linted = _find_violations()
    registry.examined(linted, unit="acceptance_literals")
    if violations:
        print("Acceptance literal lint violations found:")
        for v in violations:
            print(f"  - {v}")
        for v in violations:
            failed.append(v)
    else:
        print("No lint-invalid acceptance literals found.")
