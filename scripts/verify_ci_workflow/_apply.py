"""VP helper: the apply/reconcile guards for the verify_ci_workflow package."""

from __future__ import annotations

from typing import Any

from scripts.verify_ci_workflow._shared import _load


def _check_apply_rca_fallback() -> None:
    """Assert both sandbox-apply jobs self-dispatch ci-rca on a re-run failure.

    PLAN-gated-apply-rca-trigger: ci-rca.yml's workflow_run trigger is not reliably
    re-dispatched on a manual re-run's completion (confirmed gap: run 28379330706,
    gated-apply, run_attempt=2, zero RCA signal). Each of apply-sandbox and gated-apply
    must carry actions: write and a failure-path step that dispatches ci-rca.yml, gated
    on run_attempt so the workflow_run-covered attempt-1 path does not double-fire.
    """
    data = _load(".github/workflows/terraform-apply-sandbox.yml")
    jobs = data.get("jobs", {})

    for job_name in ("apply-sandbox", "gated-apply"):
        job = jobs.get(job_name)
        assert job is not None, f"Job {job_name!r} not found in terraform-apply-sandbox.yml"

        permissions = job.get("permissions", {}) or {}
        assert permissions.get("actions") == "write", (
            f"{job_name} is missing 'actions: write' permission required for the ci-rca self-dispatch step"
        )

        dispatch_step = None
        for step in job.get("steps", []):
            step_if = str(step.get("if", ""))
            step_run = str(step.get("run", ""))
            if "failure()" in step_if and "run_attempt" in step_if and "gh workflow run ci-rca.yml" in step_run:
                dispatch_step = step
                break

        assert dispatch_step is not None, (
            f"{job_name} is missing a failure()-gated, run_attempt-gated step that dispatches ci-rca.yml "
            "via 'gh workflow run ci-rca.yml'"
        )


def _check_terraform_apply_concurrency() -> None:
    """T2.35 hardening: apply-sandbox's concurrency group must be event-keyed, and
    reconcile.yml must keep sharing the push/dispatch key.

    Regression this guards against: a config that would permit concurrent applies against
    shared tfstate -- either within terraform-apply-sandbox.yml (a bare non-conditional group,
    a missing per-PR key, or cancel-in-progress not gated on pull_request) or across it and
    reconcile.yml (reconcile.yml drifting to a different push/dispatch group, silently
    decoupling the two workflows' serialization).
    """
    apply_data = _load(".github/workflows/terraform-apply-sandbox.yml")
    reconcile_data = _load(".github/workflows/reconcile.yml")

    concurrency = apply_data.get("concurrency") or {}
    group = str(concurrency.get("group", ""))
    cancel_in_progress = str(concurrency.get("cancel-in-progress", ""))

    assert "pull_request" in group, (
        f"terraform-apply-sandbox.yml concurrency.group is not event-keyed on pull_request: {group!r}"
    )
    assert "format(" in group and "pull_request.number" in group, (
        f"terraform-apply-sandbox.yml concurrency.group is missing a per-PR format key: {group!r}"
    )
    assert "terraform-apply-sandbox" in group, (
        f"terraform-apply-sandbox.yml concurrency.group is missing the shared push/dispatch "
        f"key 'terraform-apply-sandbox': {group!r}"
    )

    assert "pull_request" in cancel_in_progress, (
        f"terraform-apply-sandbox.yml concurrency.cancel-in-progress is not gated on pull_request "
        f"(a push/dispatch apply run could be cancelled): {cancel_in_progress!r}"
    )
    assert cancel_in_progress.strip() not in ("true", "${{ true }}"), (
        f"terraform-apply-sandbox.yml concurrency.cancel-in-progress is unconditionally true: {cancel_in_progress!r}"
    )

    reconcile_concurrency = reconcile_data.get("concurrency") or {}
    reconcile_group = str(reconcile_concurrency.get("group", ""))
    assert reconcile_group == "terraform-apply-sandbox", (
        f"reconcile.yml concurrency.group no longer shares the terraform-apply-sandbox push/dispatch "
        f"key (cross-workflow apply serialization broken): {reconcile_group!r}"
    )


# rec-2847 part (c), narrowed to reconcile.yml's red-recovery topology. The six DEP-10
# fresh-replan fallthrough steps; the seventh (the upload-artifact step) carries no `id` and is
# located by its `uses:` below.
_RECOVERY_FALLTHROUGH_STEP_IDS = (
    "replan",
    "guard_fresh",
    "review_fresh",
    "apply_fresh",
    "upload_fresh_plan_sha256",
)
_RECOVERY_FRESH_PLAN_SIGNAL = "steps.route.outputs.needs_fresh_plan == 'true'"
# The pre-fix, single-cause signal. A saved-plan guard-BLOCK SKIPS the `apply` step, so this
# output is never set on exactly the episodes that most need the fallthrough -- gating any
# fallthrough step on it makes that step structurally unreachable on the BLOCK route.
_RECOVERY_LEGACY_STALE_SIGNAL = "steps.apply.outputs.stale"
_RECOVERY_STALE_DETECTION_MARKERS = (
    "saved plan is stale|plan file can no longer be applied|state was changed",
    "stale=true",
    "STALE_PLAN_FRESH_REPLAN",
)
_RECOVERY_FRESH_PLAN_PENDING = "needs.apply-reconcile.outputs.fresh_plan_pending == 'true'"
_RECOVERY_FRESH_PLAN_NOT_PENDING = "needs.apply-reconcile.outputs.fresh_plan_pending != 'true'"


def _recovery_step_body(step: dict[str, Any]) -> str:
    """Flatten one step's `run:` body and `env:` block into a single searchable string."""
    env = step.get("env") or {}
    env_text = "\n".join(f"{key}: {value}" for key, value in env.items())
    return f"{step.get('run') or ''}\n{env_text}"


def _check_recovery_workflow_topology() -> None:
    """rec-2847: reconcile.yml's red-recovery flow must stay reachable on BOTH fresh-plan causes.

    Four invariants, asserted over the PARSED workflow (never a whole-file grep):
      (i)   the `route` aggregator exists and reads BOTH cause signals;
      (ii)  no fresh-replan fallthrough step is gated on the pre-fix stale-only signal, and every
            one of them is gated on the aggregate `needs_fresh_plan` signal;
      (iii) the saved-plan apply step still carries its stale-signature detection -- the union
            ADDS to the DEP-10 stale route, it must never replace it;
      (iv)  the cross-job hand-off is intact: the `fresh_plan_pending` / `fresh_plan_sha256` job
            outputs are declared, gated-apply-reconcile's download + sha256 VERIFY steps are gated
            on pending, and fetch-saved-plan is gated on its negation (mutually exclusive sources).
    """
    data = _load(".github/workflows/reconcile.yml")
    jobs = data.get("jobs", {})

    apply_job = jobs.get("apply-reconcile")
    assert apply_job is not None, "reconcile.yml has no apply-reconcile job"
    gated_job = jobs.get("gated-apply-reconcile")
    assert gated_job is not None, "reconcile.yml has no gated-apply-reconcile job"

    steps = apply_job.get("steps", []) or []
    by_id = {step.get("id"): step for step in steps if step.get("id")}

    # (i) the route aggregator exists and unions BOTH causes.
    route = by_id.get("route")
    assert route is not None, (
        "reconcile.yml apply-reconcile has no `route` step -- without it the fresh-replan "
        "fallthrough is gated on a single cause and is structurally unreachable on a saved-plan "
        "guard-BLOCK (rec-2847)"
    )
    route_body = _recovery_step_body(route)
    for cause in (_RECOVERY_LEGACY_STALE_SIGNAL, "steps.guard.outputs.routed"):
        assert cause in route_body, (
            f"`route` step does not read cause signal {cause!r} -- needs_fresh_plan must be the "
            "UNION of the stale-saved-plan and saved-plan-guard-routed causes, or the defect is "
            "merely relocated"
        )
    assert "needs_fresh_plan" in route_body, "`route` step does not emit a needs_fresh_plan output"

    # (ii) every fallthrough step rides the aggregate signal, none the pre-fix stale-only one.
    upload_artifact = next(
        (step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact")),
        None,
    )
    assert upload_artifact is not None, "reconcile.yml apply-reconcile has no upload-artifact fallthrough step"

    gated_steps: list[tuple[str, dict[str, Any]]] = [
        (step_id, by_id[step_id]) for step_id in _RECOVERY_FALLTHROUGH_STEP_IDS if step_id in by_id
    ]
    missing = [step_id for step_id in _RECOVERY_FALLTHROUGH_STEP_IDS if step_id not in by_id]
    assert not missing, f"reconcile.yml apply-reconcile is missing fresh-replan fallthrough step(s): {missing}"
    gated_steps.append(("upload-artifact", upload_artifact))

    for label, step in gated_steps:
        condition = str(step.get("if", ""))
        assert _RECOVERY_LEGACY_STALE_SIGNAL not in condition, (
            f"fallthrough step {label!r} is still gated on {_RECOVERY_LEGACY_STALE_SIGNAL!r} -- "
            "a saved-plan guard-BLOCK skips the apply step, so that output is never set and this "
            "step can never run on the BLOCK route (rec-2847)"
        )
        assert _RECOVERY_FRESH_PLAN_SIGNAL in condition, (
            f"fallthrough step {label!r} is not gated on {_RECOVERY_FRESH_PLAN_SIGNAL!r}: {condition!r}"
        )

    # (iii) the DEP-10 stale route survived -- the union ADDS to it, never replaces it.
    apply_step = by_id.get("apply")
    assert apply_step is not None, "reconcile.yml apply-reconcile has no saved-plan `apply` step"
    apply_body = apply_step.get("run") or ""
    for marker in _RECOVERY_STALE_DETECTION_MARKERS:
        assert marker in apply_body, (
            f"saved-plan `apply` step lost its stale-signature detection ({marker!r}) -- the "
            "guard-BLOCK cause must be UNIONED with the stale cause, not substituted for it"
        )

    # (iv) the cross-job hand-off is intact.
    outputs = apply_job.get("outputs", {}) or {}
    assert "steps.upload_fresh_plan_sha256.outcome" in str(outputs.get("fresh_plan_pending", "")), (
        "apply-reconcile does not declare a fresh_plan_pending job output derived from steps.upload_fresh_plan_sha256.outcome"
    )
    assert "steps.upload_fresh_plan_sha256.outputs.sha256" in str(outputs.get("fresh_plan_sha256", "")), (
        "apply-reconcile does not declare a fresh_plan_sha256 job output"
    )

    gated_job_steps = gated_job.get("steps", []) or []
    download = next(
        (step for step in gated_job_steps if str(step.get("uses", "")).startswith("actions/download-artifact")),
        None,
    )
    assert download is not None, "gated-apply-reconcile has no download-artifact step"
    assert _RECOVERY_FRESH_PLAN_PENDING in str(download.get("if", "")), (
        f"gated-apply-reconcile's download step is not gated on {_RECOVERY_FRESH_PLAN_PENDING!r}: {download.get('if')!r}"
    )

    verify = next((step for step in gated_job_steps if "FRESH_PLAN_SHA256" in _recovery_step_body(step)), None)
    assert verify is not None, "gated-apply-reconcile has no fresh plan.bin sha256 VERIFY step"
    assert _RECOVERY_FRESH_PLAN_PENDING in str(verify.get("if", "")), (
        f"gated-apply-reconcile's sha256 VERIFY step is not gated on {_RECOVERY_FRESH_PLAN_PENDING!r}: {verify.get('if')!r}"
    )

    fetch_plan = next((step for step in gated_job_steps if step.get("id") == "fetch_plan"), None)
    assert fetch_plan is not None, "gated-apply-reconcile has no fetch_plan step"
    assert _RECOVERY_FRESH_PLAN_NOT_PENDING in str(fetch_plan.get("if", "")), (
        "gated-apply-reconcile's fetch-saved-plan step is not gated on "
        f"{_RECOVERY_FRESH_PLAN_NOT_PENDING!r} -- the fresh and saved plan sources must stay "
        f"mutually exclusive: {fetch_plan.get('if')!r}"
    )
