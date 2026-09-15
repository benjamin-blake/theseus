"""VP helper: ci.yml-shape structural guards for the verify_ci_workflow package."""

from __future__ import annotations

import re
from typing import Any

from scripts.verify_ci_workflow._shared import _assert_runtime_lock, _get_steps_text, _load


def _check_jobs_and_flags() -> None:
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    assert "validate-python" not in jobs, "Old validate-python job still present in ci.yml"
    assert "pr-validate" in jobs, "pr-validate job missing from ci.yml"
    assert "main-validate" in jobs, "main-validate job missing from ci.yml"

    pr_job = jobs["pr-validate"]
    main_job = jobs["main-validate"]

    assert pr_job.get("if") == "github.event_name == 'pull_request'", f"pr-validate.if is wrong: {pr_job.get('if')!r}"
    assert main_job.get("if") == "github.event_name == 'push'", f"main-validate.if is wrong: {main_job.get('if')!r}"

    pr_steps = _get_steps_text(pr_job)
    main_steps = _get_steps_text(main_job)

    assert "--pre" in pr_steps, "pr-validate steps do not contain --pre"
    assert "--pre" not in main_steps, "main-validate steps contain --pre (should not)"
    _assert_runtime_lock(main_job, "main-validate")


def _is_truthy_concurrency_flag(value: Any) -> bool:
    """Accept a YAML bool True or a templated/string truthy value ("true", "${{ true }}").

    GitHub Actions `cancel-in-progress` is normally a bare YAML boolean (PyYAML loads it as
    Python True), but may also appear quoted or as a `${{ ... }}` expression -- both of which
    PyYAML loads as plain strings.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    return bool(re.fullmatch(r"\$\{\{\s*true\s*\}\}", normalized))


def _check_concurrency() -> None:
    """VTS-11: pr-validate must cancel superseded runs on a per-PR key (so a force-pushed PR
    doesn't leave a stale run occupying a required check); main-validate -- the merge-to-main
    gate -- must NOT cancel in-flight runs (drift-canary + per-commit RCA role, dec-73 L8). Also
    retains the CD.21 ci-runner-serialisation-group-absence anti-regression guard for both jobs.
    """
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    # CD.21: the self-hosted runner is retired; each job runs on its own
    # isolated GitHub-hosted runner, so the ci-runner serialisation group
    # is obsolete. Assert it is absent as an anti-regression guard.
    for job_name in ("pr-validate", "main-validate"):
        job = jobs.get(job_name)
        assert job is not None, f"Job {job_name!r} not found in ci.yml"
        concurrency = job.get("concurrency") or {}
        assert concurrency.get("group") != "ci-runner", (
            f"{job_name} still declares obsolete concurrency.group 'ci-runner' (retired by CD.21)"
        )

    # pr-validate: a superseded run (e.g. after a force-push) must be cancelled, keyed
    # per-PR so distinct PRs never cross-cancel each other.
    pr_job = jobs.get("pr-validate") or {}
    pr_concurrency = pr_job.get("concurrency") or {}
    pr_group = str(pr_concurrency.get("group", ""))
    assert any(key in pr_group for key in ("github.ref", "head_ref", "pull_request")), (
        f"pr-validate concurrency.group is not per-PR keyed (expected github.ref / head_ref / "
        f"pull_request in the group): {pr_group!r}"
    )
    assert _is_truthy_concurrency_flag(pr_concurrency.get("cancel-in-progress")), (
        f"pr-validate concurrency.cancel-in-progress is not truthy: {pr_concurrency.get('cancel-in-progress')!r}"
    )

    # main-validate: the merge-to-main gate must run to completion even if superseded --
    # cancel-in-progress must stay absent/false.
    main_job = jobs.get("main-validate") or {}
    main_concurrency = main_job.get("concurrency") or {}
    assert not _is_truthy_concurrency_flag(main_concurrency.get("cancel-in-progress")), (
        f"main-validate concurrency.cancel-in-progress is truthy (must not cancel in-flight main "
        f"runs): {main_concurrency.get('cancel-in-progress')!r}"
    )


def _check_fetch_depth() -> None:
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    pr_job = jobs.get("pr-validate", {})
    main_job = jobs.get("main-validate", {})

    pr_checkout = None
    main_checkout = None

    for step in pr_job.get("steps", []):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            pr_checkout = step
            break

    for step in main_job.get("steps", []):
        if str(step.get("uses", "")).startswith("actions/checkout"):
            main_checkout = step
            break

    assert pr_checkout is not None, "pr-validate has no checkout step"
    assert main_checkout is not None, "main-validate has no checkout step"

    pr_with = pr_checkout.get("with", {}) or {}
    assert pr_with.get("fetch-depth") == 0, f"pr-validate checkout fetch-depth is {pr_with.get('fetch-depth')!r}, expected 0"

    main_with = main_checkout.get("with", {}) or {}
    assert main_with.get("fetch-depth") == 2, (
        f"main-validate checkout fetch-depth is {main_with.get('fetch-depth')!r}, expected 2 "
        "(Decision 159: HEAD~1 must resolve for the push-context diff base, squash-merge convention)"
    )


def _check_full_tier_runtime_lock() -> None:
    ci_jobs = _load(".github/workflows/ci.yml").get("jobs", {})
    main_job = ci_jobs.get("main-validate")
    assert main_job is not None, "main-validate job missing from ci.yml"
    _assert_runtime_lock(main_job, "main-validate")

    canary_jobs = _load(".github/workflows/main-canary.yml").get("jobs", {})
    assert len(canary_jobs) == 1, "main-canary.yml must contain exactly one full-tier job"
    _assert_runtime_lock(next(iter(canary_jobs.values())), "main-canary")


_MODULE_INVOCATION_RE = re.compile(
    r"(?:python[0-9.]*\s+-m\s+scripts\.([A-Za-z_][A-Za-z0-9_]*)|scripts/([A-Za-z_][A-Za-z0-9_]*)\.py)"
)
_CHECK_LIKE_RE = re.compile(r"^(validate|verify|check)")


def _check_validate_single_source() -> None:
    """Decision 80: ci.yml's only validation entrypoint is `scripts.validate`.

    Every check-like `python -m scripts.<mod>` / `scripts/<mod>.py` invocation in
    ci.yml (module name matching ^(validate|verify|check)) must resolve to the
    scripts.validate registry runner -- not a bespoke module bypassing it.
    """
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    violations = []
    for job_name, job in jobs.items():
        steps_text = _get_steps_text(job)
        for match in _MODULE_INVOCATION_RE.finditer(steps_text):
            module = match.group(1) or match.group(2)
            if _CHECK_LIKE_RE.match(module) and module != "validate":
                violations.append(f"{job_name}: scripts.{module}")

    assert not violations, f"ci.yml invokes check-like module(s) other than scripts.validate: {violations}"


def _admits_pull_request(if_expr: Any) -> bool:
    """A job is PR-gating unless its `if` is a push-only guard.

    A job with NO `if` key runs on every triggering event, including pull_request --
    that makes it PR-gating too (e.g. terraform-validate). A job whose `if` mentions
    `push` but not `pull_request` is treated as a push-only guard and excluded. An
    `if` mentioning neither (e.g. a schedule/workflow_dispatch-only guard) defaults
    to PR-gating -- the conservative direction, since excluding a job that actually
    can run on pull_request would silently create an ungated merge path.
    """
    if if_expr is None:
        return True
    if_str = str(if_expr)
    if "pull_request" in if_str:
        return True
    if "push" in if_str:
        return False
    return True


def _check_signal_green_needs() -> None:
    """Every PR-gating job in ci.yml must be listed in signal-green.needs."""
    data = _load(".github/workflows/ci.yml")
    jobs = data.get("jobs", {})

    signal_green = jobs.get("signal-green")
    assert signal_green is not None, "signal-green job missing from ci.yml"

    needs = signal_green.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]

    missing = [
        job_name
        for job_name, job in jobs.items()
        if job_name != "signal-green" and _admits_pull_request(job.get("if")) and job_name not in needs
    ]

    assert not missing, f"PR-gating job(s) missing from signal-green.needs: {missing}"
