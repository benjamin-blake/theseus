"""branch-cleanup.yml structural invariants gate (WS1 completion, dependabot-automation-cleanup).

This is the one workflow in the repo that deletes remote refs. A deleted ref is not recoverable
from the caller's side, and the blast radius of a wrong delete is somebody's unmerged work, so the
properties that keep it safe are asserted structurally rather than trusted to review memory:

  - workflow_dispatch ONLY. A `schedule:` trigger (or any push/pull_request trigger) would turn an
    operator-reviewed action into an unattended one, and the classifier has never run unattended
    against this repo's real branch set. Adding a schedule is a deliberate later change that must
    fail this gate first, not a one-line edit that slips through.
  - dry_run defaults to TRUE. The default invocation must print the decision table and delete
    nothing; a default of false would make the safe mode the one you have to remember to ask for.
  - permissions are exactly `contents: write`. That is what ref deletion needs and nothing else --
    notably not `pull-requests: write`, since this workflow never writes to a PR.
  - checkout uses fetch-depth: 0. The classifier asks git whether a tip is an ancestor of
    origin/main and how old that tip is; a shallow single-branch checkout answers neither, and the
    module's fail-safe response to "cannot determine age" is to KEEP -- so a missing fetch-depth
    would silently degrade the sweep into a no-op rather than failing loudly.
  - The four HARD GUARDS still exist in the decision module. They are asserted by their sentinel
    NAMES (GUARD_PROTECTED_BRANCH, GUARD_OPEN_PR, GUARD_YOUNGER_THAN_MIN_AGE, GUARD_UNKNOWN_AGE)
    and by the shape of the min-age comparison, never by matching a whole line of code: a rename or
    a reflow must not red this gate, but deleting a guard must.

Each guard failure appends a DISTINCT label to `failed` and never raises, matching the ci_guards
module pattern.

Decision 170 (MANDATORY declaration obligation): calls registry.examined() -- this is a NEW check,
so it cannot be grandfathered into config/check_accounting_baseline.yaml (frozen _BASELINE_SEED;
validate_check_accounting rejects an undeclared new check outright).

Filesystem-only: no subprocess, no network, matching every sibling ci_guards module.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.checks import _common, registry
from scripts.verify_ci_workflow import _load

_WORKFLOW_PATH = ".github/workflows/branch-cleanup.yml"
_WORKFLOW_NAME = "branch-cleanup"
_PERMISSIONS = {"contents": "write"}
_DECISION_MODULE_PATH = "scripts/ci/branch_cleanup.py"

_PREFIX = "branch-cleanup"

# Anchored exactly as validate_dependabot_automation.py anchors its own delegation line: `run: bash
# <repo-root-relative-path>.sh`, nothing else (Decision 162 R1, workflow-step variant -- cwd is the
# repo root via actions/checkout, not a github.action_path-relative dir).
_DELEGATE_RUN_RE = re.compile(r"^bash\s+([\w./-]+\.sh)\s*$")

# `main` must be inside the protected set itself, not merely mentioned somewhere in the module --
# anchored on the constant's NAME so a reflow of the set is fine and an emptied set is not.
_PROTECTED_MAIN_RE = re.compile(r"PROTECTED_BRANCHES[^\n]*\"main\"")
# The min-age floor as a comparison, not as a variable that happens to be read and discarded.
_MIN_AGE_COMPARISON_RE = re.compile(r"age_hours\s*<\s*min_age_hours")

_GUARD_SENTINELS = (
    ("protected-branch hard guard", "GUARD_PROTECTED_BRANCH"),
    ("open-PR hard guard", "GUARD_OPEN_PR"),
    ("min-age hard guard", "GUARD_YOUNGER_THAN_MIN_AGE"),
    ("unknown-age hard guard", "GUARD_UNKNOWN_AGE"),
)
_CLASS_SENTINELS = (
    ("merged-PR-head delete class", "CLASS_MERGED_PR_HEAD"),
    ("ancestor-of-main delete class", "CLASS_ANCESTOR_OF_MAIN"),
    ("extra_branches delete class", "CLASS_EXTRA_BRANCH"),
)


def _steps(job: Any) -> list[dict[str, Any]]:
    steps = job.get("steps") if isinstance(job, dict) else None
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _resolve_delegate(jobs: dict[str, Any]) -> str | None:
    """First `run:` body across all jobs that is a bare delegation line, as its script path."""
    for job in jobs.values():
        for step in _steps(job):
            run_body = step.get("run")
            if not isinstance(run_body, str):
                continue
            match = _DELEGATE_RUN_RE.match(run_body.strip())
            if match:
                return match.group(1)
    return None


def _report(failed: list[str], label: str, ok: bool, detail: str = "") -> None:
    """One PASS/FAIL line plus, on failure, one DISTINCT `branch-cleanup: <label>` entry."""
    if ok:
        print(f"  PASS: {label}")
        return
    print(f"  FAIL: {label}{f' ({detail})' if detail else ''}")
    failed.append(f"{_PREFIX}: {label}")


def _assert_triggers(failed: list[str], on: Any) -> None:
    trigger_keys = set(on) if isinstance(on, dict) else set()
    _report(
        failed,
        "trigger set is workflow_dispatch and nothing else",
        trigger_keys == {"workflow_dispatch"},
        f"{sorted(trigger_keys)} -- an unattended trigger on a ref-deleting workflow is the risk",
    )

    dispatch = on.get("workflow_dispatch") if isinstance(on, dict) else None
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    dry_run = inputs.get("dry_run") if isinstance(inputs, dict) else None
    _report(
        failed,
        "dry_run input defaults to true",
        isinstance(dry_run, dict) and dry_run.get("default") is True,
        repr(dry_run),
    )


def _assert_decision_module(failed: list[str], script_text: str) -> None:
    _report(
        failed,
        "shell delegate hands off to the branch_cleanup decision module",
        _DECISION_MODULE_PATH in script_text,
    )

    module_path = _common.ROOT / _DECISION_MODULE_PATH
    if not module_path.is_file():
        print(f"  FAIL: decision module {_DECISION_MODULE_PATH} does not exist on disk")
        failed.append(f"{_PREFIX}: decision module missing on disk")
        return
    print(f"  PASS: decision module {_DECISION_MODULE_PATH} exists")

    module_text = module_path.read_text(encoding="utf-8")
    for label, sentinel in _GUARD_SENTINELS + _CLASS_SENTINELS:
        _report(failed, f"decision module keeps the {label}", sentinel in module_text, sentinel)
    _report(
        failed,
        "decision module protects main by name",
        bool(_PROTECTED_MAIN_RE.search(module_text)),
        "main must sit inside PROTECTED_BRANCHES, not merely be mentioned",
    )
    _report(
        failed,
        "decision module compares tip age against the min-age floor",
        bool(_MIN_AGE_COMPARISON_RE.search(module_text)),
    )
    _report(
        failed,
        "decision module queries open PRs to feed the open-PR guard",
        "def open_pr_heads(" in module_text,
    )
    _report(failed, "decision module exposes the decide_branch policy function", "def decide_branch(" in module_text)
    _report(
        failed,
        "decision module deletes through the git refs endpoint",
        "git/refs/heads/" in module_text,
    )


@registry.register("validate_branch_cleanup", owner="platform")
def validate_branch_cleanup(failed: list[str]) -> None:
    """Assert branch-cleanup.yml's load-bearing shape and its decision module's hard guards."""
    print("\n=== branch-cleanup guard gate ===")
    try:
        data = _load(str(_common.ROOT / _WORKFLOW_PATH))
    except Exception as exc:
        print(f"  FAIL: could not load {_WORKFLOW_PATH}: {exc}")
        failed.append(f"{_PREFIX}: workflow file unreadable")
        registry.examined(0, unit="branch_cleanup_workflows")
        return

    _report(failed, "name field is the taxonomy key", data.get("name") == _WORKFLOW_NAME)
    _assert_triggers(failed, data.get("on") or {})
    _report(
        failed,
        "permissions are exactly contents: write",
        data.get("permissions") == _PERMISSIONS,
        repr(data.get("permissions")),
    )

    jobs = data.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        print("  FAIL: no jobs defined")
        failed.append(f"{_PREFIX}: no jobs defined")
        registry.examined(1, unit="branch_cleanup_workflows")
        return

    all_steps = [step for job in jobs.values() for step in _steps(job)]
    checkout_steps = [step for step in all_steps if str(step.get("uses", "")).startswith("actions/checkout")]
    _report(
        failed,
        "checkout requests full history via fetch-depth: 0",
        bool(checkout_steps) and any((step.get("with") or {}).get("fetch-depth") == 0 for step in checkout_steps),
        "ancestor-of-main and tip-age both need the full history",
    )

    script_rel_path = _resolve_delegate(jobs)
    if script_rel_path is None:
        print("  FAIL: could not resolve a delegate script from any step's run: body")
        failed.append(f"{_PREFIX}: could not resolve delegate script")
        registry.examined(1, unit="branch_cleanup_workflows")
        return

    script_path = _common.ROOT / script_rel_path
    if not script_path.is_file():
        print(f"  FAIL: delegate script {script_rel_path} does not exist on disk")
        failed.append(f"{_PREFIX}: delegate script missing on disk")
        registry.examined(1, unit="branch_cleanup_workflows")
        return
    print(f"  PASS: delegate script {script_rel_path} exists")

    _assert_decision_module(failed, script_path.read_text(encoding="utf-8"))
    registry.examined(1, unit="branch_cleanup_workflows")
