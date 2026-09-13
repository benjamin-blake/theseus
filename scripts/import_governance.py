#!/usr/bin/env python3
"""Import governance checks for Decision 80 / T3.11.

Three checks, each callable as a function or via __main__ CLI:
  run_import_contracts()          -- run import-linter against .importlinter; non-zero exit on violation
  check_lockfile_sync()           -- verify the compiled requirements*.txt outputs pin every requirements*.in floor
  evaluate_bazel_revisit_trigger() -- evaluate Decision 80 cl.4 predicate; advisory only, never auto-acts

CLI flags (mutually exclusive):
  --check-contracts   runs run_import_contracts();  exit 0 on pass, 1 on violation
  --check-lockfile    runs check_lockfile_sync();   exit 0 on pass, 1 on drift
  --revisit-trigger   runs evaluate_bazel_revisit_trigger(); exit 0 always (advisory, Decision 55)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).parent.parent
_REQUIREMENTS_IN = ROOT / "requirements.in"
_REQUIREMENTS_DEV_IN = ROOT / "requirements-dev.in"
_REQUIREMENTS_TXT = ROOT / "requirements.txt"
_REQUIREMENTS_DEV_TXT = ROOT / "requirements-dev.txt"
# Declaration sources first, compiled outputs second -- the order check_lockfile_sync's public
# `paths` parameter takes, so callers never have to know which half is which.
_LOCKFILE_PATHS: tuple[Path, ...] = (
    _REQUIREMENTS_IN,
    _REQUIREMENTS_DEV_IN,
    _REQUIREMENTS_TXT,
    _REQUIREMENTS_DEV_TXT,
)
# pip's requirement-file comment rule (the value of pip._internal.req.req_file.COMMENT_RE, copied rather than
# imported from a private API): '#' starts a comment only at line start or after whitespace, so `pkg>=1.0#x`
# stays part of the requirement exactly as pip sees it.
_REQUIREMENT_COMMENT_RE = re.compile(r"(^|\s+)#.*$")


def run_import_contracts() -> tuple[bool, str]:
    """Shell out to lint-imports and return (passed, combined_output).

    Uses the lint-imports entry point installed alongside this interpreter
    so the correct venv binary is always selected.
    """
    lint_imports_bin = Path(sys.executable).parent / "lint-imports"
    cmd: list[str] = [str(lint_imports_bin)] if lint_imports_bin.exists() else ["lint-imports"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )
    except FileNotFoundError:
        return False, "lint-imports not found: install import-linter (requirements.txt) and ensure the venv is active.\n"
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def parse_declared_requirements(
    paths: Sequence[Path] | None = None,
) -> tuple[dict[str, Requirement], list[str]]:
    """Parse dependency FLOORS from the pip-compile .in inputs.

    A declaration is every parseable non-comment, non-empty, non-option line -- the leading
    `-c requirements.txt` constraint line of requirements-dev.in is an option and is skipped.

    Returns (declarations by normalized name, unparseable raw lines).
    """
    declaration_paths = list(paths) if paths is not None else list(_LOCKFILE_PATHS[:2])
    declared: dict[str, Requirement] = {}
    unparseable: list[str] = []
    for path in declaration_paths:
        # A missing input is SKIPPED here, never raised: check_lockfile_sync hard-fails on it
        # before ever calling this (see its `absent` guard), and the registered wrapper calls this
        # helper for its accounting count on exactly that failure path -- raising would abort the
        # check before it could append to `failed`.
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = _REQUIREMENT_COMMENT_RE.sub("", raw_line).strip()
            if not line or line.startswith("-"):
                continue
            try:
                requirement = Requirement(line)
            except InvalidRequirement:
                unparseable.append(raw_line.strip())
                continue
            declared[_normalize_pkg(requirement.name)] = requirement
    return declared, unparseable


def count_declared_requirements() -> int:
    """Number of floors the live .in inputs declare -- the unit validate_lockfile_sync reports.

    Never raises on a missing input: returns the count of what is actually readable (0 when no .in
    input exists), so the registered check can still report and append its failure.
    """
    return len(parse_declared_requirements()[0])


def check_lockfile_sync(paths: Sequence[Path] | None = None) -> tuple[bool, str]:
    """Verify the compiled pip-compile outputs pin every floor the .in inputs declare.

    `paths` is (requirements.in, requirements-dev.in, requirements.txt, requirements-dev.txt) and
    defaults to the live repo files. ALL FOUR ARE REQUIRED -- a missing one is a hard failure,
    because the `-c requirements.txt` constraint form makes both compiled outputs committed
    artifacts that are always present.

    Returns (in_sync, message). The declaration and pin sources are named in the message so
    callers can surface them in audit trails.
    """
    resolved = tuple(paths) if paths is not None else _LOCKFILE_PATHS
    if len(resolved) != 4:
        return False, (
            "check_lockfile_sync expects 4 paths (requirements.in, requirements-dev.in, "
            f"requirements.txt, requirements-dev.txt); got {len(resolved)}"
        )

    absent = [str(path) for path in resolved if not path.exists()]
    if absent:
        return False, (
            f"requirements files not found: {', '.join(absent)}; regenerate with: "
            "pip-compile --strip-extras --output-file=requirements.txt requirements.in"
        )

    declaration_paths, output_paths = resolved[:2], resolved[2:]
    declared, unparseable = parse_declared_requirements(declaration_paths)
    identity = (
        f"floors from {', '.join(path.name for path in declaration_paths)}; "
        f"pins from {', '.join(path.name for path in output_paths)}"
    )
    if unparseable:
        return False, (
            "requirements declarations cannot be parsed (the gate cannot check what it cannot parse): "
            f"{', '.join(repr(entry) for entry in unparseable)} ({identity})"
        )

    per_output: list[dict[str, Version]] = []
    pinned: dict[str, Version] = {}
    extras_pins: list[str] = []
    for path in output_paths:
        output_pins, output_extras = _parse_compiled_pins(path.read_text(encoding="utf-8"))
        per_output.append(output_pins)
        extras_pins.extend(output_extras)
        pinned.update(output_pins)

    # CI installs the compiled outputs directly, and pip hard-rejects extras in a constraints
    # file -- an output regenerated without pip-compile's --strip-extras breaks every install.
    if extras_pins:
        return False, (
            f"compiled pins carry extras (pip rejects extras in constraints files): "
            f"{', '.join(extras_pins)}; regenerate with pip-compile --strip-extras ({identity})"
        )

    # Cross-output coherence replaces the coherence the retired single-resolve lockfile provided:
    # anyio is reached by mcp on the prod side and by httpx/openai on the dev side, so regenerating
    # only one output would silently pin one distribution at two versions.
    shared = per_output[0].keys() & per_output[1].keys()
    disagreements = sorted(
        f"{name} is {per_output[0][name]} in {output_paths[0].name} but {per_output[1][name]} in {output_paths[1].name}"
        for name in shared
        if per_output[0][name] != per_output[1][name]
    )
    if disagreements:
        return False, (
            f"compiled outputs disagree across outputs: {'; '.join(disagreements)}; "
            f"recompile requirements-dev.txt under -c requirements.txt ({identity})"
        )

    missing = [pkg for pkg in declared if pkg not in pinned]
    if missing:
        return False, f"compiled outputs missing pins for: {', '.join(missing)} ({identity})"

    incompatible = [
        f"{requirement.name}{requirement.specifier} rejects {pinned[name]}"
        for name, requirement in declared.items()
        if requirement.specifier and pinned[name] not in requirement.specifier
    ]
    if incompatible:
        return False, f"compiled outputs incompatible pins: {', '.join(incompatible)} ({identity})"

    return True, f"pins all {len(declared)} declared floors compatibly ({identity})"


def _parse_compiled_pins(compiled_text: str) -> tuple[dict[str, Version], list[str]]:
    """Parse compiled-output lines into (exact pins by normalized name, extras-carrying pin strings)."""
    pinned: dict[str, Version] = {}
    extras_pins: list[str] = []
    for raw_line in compiled_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            locked_requirement = Requirement(line)
        except InvalidRequirement:
            continue
        if locked_requirement.extras:
            extras_pins.append(str(locked_requirement))
        exact_pins = [specifier.version for specifier in locked_requirement.specifier if specifier.operator == "=="]
        if len(exact_pins) == 1:
            try:
                pinned[_normalize_pkg(locked_requirement.name)] = Version(exact_pins[0])
            except InvalidVersion:
                continue
    return pinned, extras_pins


def _normalize_pkg(name: str) -> str:
    """Normalize a package name to lowercase with underscores (PEP 503 canonical form)."""
    return name.lower().replace("-", "_").replace(".", "_")


def evaluate_bazel_revisit_trigger() -> tuple[bool, str]:
    """Evaluate the Decision 80 cl.4 Bazel revisit trigger predicate.

    Predicate (AND-gate -- BOTH conditions must be true for the trigger to fire):
      1. Executor concurrency > 1  (T4.4 milestone; currently 1)
      2. KG.13 tier_item filed  OR  _FAST_TIER_BUDGET_SECONDS breach recurred

    Returns (fired, advisory_message). The trigger is ADVISORY ONLY -- never auto-acts
    (Decision 55 / alarm-not-gate). Callers must exit 0 regardless of fired.
    """
    concurrency = _read_executor_concurrency()

    if concurrency <= 1:
        return False, (
            f"Bazel revisit trigger: DORMANT "
            f"(executor concurrency={concurrency}; "
            "trigger requires concurrency>1 AND (KG.13 filed OR budget breach) -- Decision 80 cl.4)"
        )

    kg13 = _kg13_tier_item_filed()
    breach = _fast_tier_budget_breach_open()

    if not (kg13 or breach):
        return False, (
            f"Bazel revisit trigger: DORMANT "
            f"(concurrency={concurrency}>1 but neither KG.13 filed nor budget breach open "
            "-- Decision 80 cl.4 AND-gate not satisfied)"
        )

    reasons: list[str] = []
    if kg13:
        reasons.append("KG.13 tier_item filed")
    if breach:
        reasons.append("_FAST_TIER_BUDGET_SECONDS breach open")
    return True, (
        f"ADVISORY: Bazel revisit trigger FIRED "
        f"(concurrency={concurrency}, {', '.join(reasons)}). "
        "Decision 80 cl.4 signal: schedule a build-orchestrator re-evaluation session. "
        "No automatic action taken (Decision 55 / alarm-not-gate)."
    )


def _read_executor_concurrency() -> int:
    capabilities = ROOT / "config" / "agent" / "executor" / "capabilities.yaml"
    if not capabilities.exists():
        return 1
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(capabilities.read_text(encoding="utf-8"))
        return int(data.get("concurrency", 1))
    except Exception:
        return 1


def _kg13_tier_item_filed() -> bool:
    roadmap = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap.exists():
        return False
    try:
        text = roadmap.read_text(encoding="utf-8")
        return bool(re.search(r"\bid:\s*['\"]?KG\.13['\"]?", text))
    except Exception:
        return False


def _fast_tier_budget_breach_open() -> bool:
    recs_log = ROOT / "logs" / ".recommendations-log.jsonl"
    if not recs_log.exists():
        return False
    try:
        with recs_log.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if (
                    rec.get("status") == "open"
                    and "fast" in rec.get("title", "").lower()
                    and "budget" in rec.get("title", "").lower()
                ):
                    return True
    except Exception:
        return False
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Import governance checks (Decision 80 / T3.11)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-contracts", action="store_true", help="Run import-linter contracts (exit 0=pass)")
    group.add_argument(
        "--check-lockfile", action="store_true", help="Verify compiled-output sync with the .in floors (exit 0=pass)"
    )
    group.add_argument(
        "--revisit-trigger",
        action="store_true",
        help="Evaluate Bazel revisit trigger (advisory; exit 0 always)",
    )
    args = parser.parse_args()

    if args.check_contracts:
        passed, output = run_import_contracts()
        print(output, end="")
        sys.exit(0 if passed else 1)

    if args.check_lockfile:
        in_sync, message = check_lockfile_sync()
        print(message)
        sys.exit(0 if in_sync else 1)

    if args.revisit_trigger:
        _fired, message = evaluate_bazel_revisit_trigger()
        print(message)
        sys.exit(0)


if __name__ == "__main__":
    main()
