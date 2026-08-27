"""Dependabot automation structural invariants gate (WS2/WS3 dependabot-automation-cleanup).

Guards the workflows that press merge buttons on dependabot PRs. Each of them arms or advances a
merge without a human in the loop, so the properties that make that safe are structural, not
conventional, and belong in a standing gate rather than in review memory:

  - `pull_request`, never `pull_request_target`. pull_request_target would run an elevated-
    permission job against the base repo's secrets while checking out attacker-controlled head
    code; the checkout must additionally pin `ref` to the base SHA so only trusted main-side code
    ever executes.
  - Exactly `contents: write` + `pull-requests: write`. Both are required for `gh pr merge --auto`
    on a dependabot-triggered run; anything wider is unearned authority on an unattended path.
  - The author gate (`github.event.pull_request.user.login == 'dependabot[bot]'`) plus the
    repository gate, and deliberately NO `github.actor` gate -- the stranded sweep's
    `gh pr update-branch` fires synchronize events whose actor is not dependabot, and those
    re-evaluations are wanted. An actor gate would silently disable that composition.
  - The policy itself lives in the shell delegate, so the delegate's load-bearing literals (the two
    allowed semver update types, the absence of the major one, the duckdb/DuckLake lockstep
    denylist, and the `gh pr merge --auto --squash` call) are asserted against the SCRIPT's own
    contents, the way validate_pr_conflict_signal.py follows its delegation.
  - The stranded sweep's two-step recovery. `gh pr update-branch` is what turns a BEHIND PR back
    into a re-evaluated one, and the `@dependabot rebase` comment is the only fallback that can
    rescue a DIRTY branch (dependabot alone can rewrite its own branch). Losing either literal
    silently converts the sweep into a reporting-only job that clears nothing, which no test of the
    workflow's shape would otherwise notice.

Each guard failure appends a DISTINCT label to `failed` and never raises, matching the ci_guards
module pattern. Assertions are grouped one function per workflow (`_WORKFLOW_ASSERTIONS`), so a
second dependabot workflow is added by writing its own helper and appending it to that tuple --
nothing else in this module changes.

Decision 170 (MANDATORY declaration obligation): calls registry.examined() -- this is a NEW check,
so it cannot be grandfathered into config/check_accounting_baseline.yaml (frozen _BASELINE_SEED;
validate_check_accounting rejects an undeclared new check outright).

Filesystem-only: no subprocess, no network, matching every sibling ci_guards module.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from scripts.checks import _common, registry
from scripts.verify_ci_workflow import _load

_AUTO_MERGE_WORKFLOW_PATH = ".github/workflows/dependabot-auto-merge.yml"
_AUTO_MERGE_WORKFLOW_NAME = "dependabot-auto-merge"
_AUTO_MERGE_PR_TYPES = ("opened", "reopened", "synchronize")
_AUTO_MERGE_PERMISSIONS = {"contents": "write", "pull-requests": "write"}

_AUTHOR_GATE_LITERALS = ("github.event.pull_request.user.login", "dependabot[bot]")
_REPOSITORY_GATE_LITERAL = "github.repository"
_ACTOR_GATE_LITERAL = "github.actor"
_BASE_SHA_REF_LITERAL = "github.event.pull_request.base.sha"
_FETCH_METADATA_PREFIX = "dependabot/fetch-metadata@"

_STRANDED_WORKFLOW_PATH = ".github/workflows/dependabot-stranded.yml"
_STRANDED_WORKFLOW_NAME = "dependabot-stranded"
_STRANDED_PERMISSIONS = {"contents": "write", "pull-requests": "write"}
_UPDATE_BRANCH_LITERAL = "gh pr update-branch"
_REBASE_FALLBACK_LITERAL = "@dependabot rebase"

# Anchored exactly as validate_pr_conflict_signal.py anchors its own delegation line: `run: bash
# <repo-root-relative-path>.sh`, nothing else (Decision 162 R1, workflow-step variant -- cwd is the
# repo root via actions/checkout, not a github.action_path-relative dir).
_DELEGATE_RUN_RE = re.compile(r"^bash\s+([\w./-]+\.sh)\s*$")


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


def _job_if_text(jobs: dict[str, Any]) -> str:
    return "\n".join(str(job.get("if", "")) for job in jobs.values() if isinstance(job, dict))


def _report(failed: list[str], prefix: str, label: str, ok: bool, detail: str = "") -> None:
    """One PASS/FAIL line plus, on failure, one DISTINCT `<prefix>: <label>` entry in `failed`."""
    if ok:
        print(f"  PASS: {label}")
        return
    print(f"  FAIL: {label}{f' ({detail})' if detail else ''}")
    failed.append(f"{prefix}: {label}")


def _delegate_script_text(failed: list[str], prefix: str, jobs: dict[str, Any]) -> str | None:
    """Follow the workflow's one-line delegation to its script and return that script's contents.

    Shared by every workflow assertion below: each one asserts its OWN literals, but "the delegate
    resolves and exists on disk" is the same precondition for all of them, and a resolution failure
    must read identically wherever it happens. None means the precondition failed and the caller
    has nothing further to assert.
    """
    script_rel_path = _resolve_delegate(jobs)
    if script_rel_path is None:
        print("  FAIL: could not resolve a delegate script from any step's run: body")
        failed.append(f"{prefix}: could not resolve delegate script")
        return None

    script_path = _common.ROOT / script_rel_path
    if not script_path.is_file():
        print(f"  FAIL: delegate script {script_rel_path} does not exist on disk")
        failed.append(f"{prefix}: delegate script missing on disk")
        return None
    print(f"  PASS: delegate script {script_rel_path} exists")
    return script_path.read_text(encoding="utf-8")


def assert_auto_merge_workflow(failed: list[str]) -> int:
    """dependabot-auto-merge.yml plus its policy delegate. Returns the workflow count examined."""
    prefix = _AUTO_MERGE_WORKFLOW_NAME
    try:
        data = _load(str(_common.ROOT / _AUTO_MERGE_WORKFLOW_PATH))
    except Exception as exc:
        print(f"  FAIL: could not load {_AUTO_MERGE_WORKFLOW_PATH}: {exc}")
        failed.append(f"{prefix}: workflow file unreadable")
        return 0

    _report(failed, prefix, "name field is the taxonomy key", data.get("name") == _AUTO_MERGE_WORKFLOW_NAME)

    on = data.get("on") or {}
    pull_request = on.get("pull_request") or {}
    types = pull_request.get("types")
    _report(
        failed,
        prefix,
        "pull_request trigger declares exactly the three PR types",
        isinstance(types, list) and tuple(sorted(types)) == _AUTO_MERGE_PR_TYPES,
        repr(types),
    )
    _report(
        failed,
        prefix,
        "pull_request_target trigger is absent",
        "pull_request_target" not in on,
        "elevated permissions plus head-code checkout is the pwn-request shape",
    )

    _report(
        failed,
        prefix,
        "permissions are exactly contents: write + pull-requests: write",
        data.get("permissions") == _AUTO_MERGE_PERMISSIONS,
        repr(data.get("permissions")),
    )

    jobs = data.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        print("  FAIL: no jobs defined")
        failed.append(f"{prefix}: no jobs defined")
        return 1

    if_text = _job_if_text(jobs)
    _report(
        failed,
        prefix,
        "job if-gate pins the dependabot[bot] PR author",
        all(literal in if_text for literal in _AUTHOR_GATE_LITERALS),
    )
    _report(failed, prefix, "job if-gate pins github.repository", _REPOSITORY_GATE_LITERAL in if_text)
    _report(
        failed,
        prefix,
        "job if-gate does not pin github.actor",
        _ACTOR_GATE_LITERAL not in if_text,
        "an actor gate would silently disable the stranded sweep's update-branch re-evaluations",
    )

    all_steps = [step for job in jobs.values() for step in _steps(job)]
    checkout_steps = [step for step in all_steps if str(step.get("uses", "")).startswith("actions/checkout")]
    _report(
        failed,
        prefix,
        "checkout pins ref to the base SHA",
        bool(checkout_steps)
        and all(_BASE_SHA_REF_LITERAL in str((step.get("with") or {}).get("ref", "")) for step in checkout_steps),
    )
    _report(
        failed,
        prefix,
        "dependabot/fetch-metadata step is present",
        any(str(step.get("uses", "")).startswith(_FETCH_METADATA_PREFIX) for step in all_steps),
    )

    script_text = _delegate_script_text(failed, prefix, jobs)
    if script_text is None:
        return 1

    _report(
        failed,
        prefix,
        "delegate script clears inherited errexit",
        "\nset +e\n" in f"\n{script_text}\n",
    )
    for label, present in (
        ("delegate script allows the patch update type", "version-update:semver-patch" in script_text),
        ("delegate script allows the minor update type", "version-update:semver-minor" in script_text),
        ("delegate script names duckdb in the lockstep denylist", "duckdb" in script_text),
        ("delegate script names ducklake in the lockstep denylist", "ducklake" in script_text),
        ("delegate script arms auto-merge via gh pr merge --auto --squash", "gh pr merge --auto --squash" in script_text),
    ):
        _report(failed, prefix, label, present)
    _report(
        failed,
        prefix,
        "delegate script never allows the major update type",
        "version-update:semver-major" not in script_text,
        "a major bump is left for human review",
    )
    return 1


def assert_stranded_sweep_workflow(failed: list[str]) -> int:
    """dependabot-stranded.yml plus its sweep delegate. Returns the workflow count examined."""
    prefix = _STRANDED_WORKFLOW_NAME
    try:
        data = _load(str(_common.ROOT / _STRANDED_WORKFLOW_PATH))
    except Exception as exc:
        print(f"  FAIL: could not load {_STRANDED_WORKFLOW_PATH}: {exc}")
        failed.append(f"{prefix}: workflow file unreadable")
        return 0

    _report(failed, prefix, "sweep name field is the taxonomy key", data.get("name") == _STRANDED_WORKFLOW_NAME)

    on = data.get("on") or {}
    schedule = on.get("schedule")
    _report(
        failed,
        prefix,
        "sweep declares a cron schedule",
        isinstance(schedule, list) and any(isinstance(item, dict) and item.get("cron") for item in schedule),
        repr(schedule),
    )
    _report(
        failed,
        prefix,
        "sweep declares workflow_dispatch for on-demand backlog clearing",
        "workflow_dispatch" in on,
    )
    _report(
        failed,
        prefix,
        "sweep permissions are exactly contents: write + pull-requests: write",
        data.get("permissions") == _STRANDED_PERMISSIONS,
        repr(data.get("permissions")),
    )

    jobs = data.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        print("  FAIL: no sweep jobs defined")
        failed.append(f"{prefix}: no jobs defined")
        return 1

    script_text = _delegate_script_text(failed, prefix, jobs)
    if script_text is None:
        return 1

    _report(failed, prefix, "sweep delegate clears inherited errexit", "\nset +e\n" in f"\n{script_text}\n")
    _report(
        failed,
        prefix,
        "sweep delegate updates behind branches via gh pr update-branch",
        _UPDATE_BRANCH_LITERAL in script_text,
        "without it the sweep reports the backlog but clears nothing",
    )
    _report(
        failed,
        prefix,
        "sweep delegate keeps the @dependabot rebase fallback",
        _REBASE_FALLBACK_LITERAL in script_text,
        "a DIRTY branch can only be rescued by dependabot recreating it",
    )
    return 1


_WORKFLOW_ASSERTIONS: tuple[Callable[[list[str]], int], ...] = (
    assert_auto_merge_workflow,
    assert_stranded_sweep_workflow,
)


@registry.register("validate_dependabot_automation", owner="platform")
def validate_dependabot_automation(failed: list[str]) -> None:
    """Assert the load-bearing shape of every dependabot-automation workflow. See module docstring."""
    print("\n=== dependabot automation guard gate ===")
    examined = 0
    for assertion in _WORKFLOW_ASSERTIONS:
        examined += assertion(failed)
    registry.examined(examined, unit="dependabot_automation_workflows")
