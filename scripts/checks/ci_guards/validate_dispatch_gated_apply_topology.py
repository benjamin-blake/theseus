"""terraform-apply-sandbox.yml dispatch-gated-apply topology guard (Decision 183; rec-2918 part (c)).

rec-2918 identified a dispatch-vs-push deadlock: the workflow_dispatch acknowledge-and-retry path
(the ONLY heal verb that plans fresh at main HEAD) could hit a guard-ROUTED verdict (out-of-budget
IAM / trust / destroy) and have nowhere to go -- gated-apply's job-level `if` admitted a push event
only, so a routed dispatch's fresh plan was silently discarded and the red convergence record
stayed latched. Decision 183 makes gated-apply DISPATCH-REACHABLE: reachable from EITHER heal verb,
with the fresh plan.bin handed over as a run-scoped SANDBOX_FRESH_PLAN_ARTIFACT (mirrors
reconcile.yml's RECONCILE_FRESH_PLAN_ARTIFACT hand-off verbatim) instead of being fetched from S3.

Seven invariants, asserted over the PARSED workflow (never a whole-file grep, matching the sibling
scripts.verify_ci_workflow._check_recovery_workflow_topology shape this guard is modelled on):

  (i)   gated-apply's `if` contains the routed signal and NO LONGER contains the push conjunct --
        the exact pre-fix shape this guard exists to reject.
  (ii)  gated-apply still declares `environment: tf-gated-apply` (the sole authorization boundary,
        Decision 92) and its `apply` step applies plan.bin verbatim; no step in the job re-plans
        (Decision 77 no-TOCTOU -- a `terraform plan` smuggled into gated-apply would defeat the
        guard's inspection of the applied plan).
  (iii) apply-sandbox declares the three job outputs the hand-off depends on: fresh_plan_pending
        (derived from the EMIT step's outcome), fresh_plan_sha256, and artifact_sha.
  (iv)  the upload-artifact step and the sha256 EMIT step are gated on BOTH a workflow_dispatch
        event and a guard-routed verdict -- the fresh plan.bin must never upload on a push (it
        already has a saved plan in S3) or on an un-routed dispatch (nothing to hand off).
  (v)   gated-apply's download-artifact and sha256 VERIFY steps are gated on fresh_plan_pending;
        fetch_plan is gated on ITS NEGATION plus push -- the two plan sources stay mutually
        exclusive and a saved plan.bin is never fetched on a dispatch.
  (vi)  the artifact-sha chain survives the widened reach: gated-apply's artifact_sha step echoes
        needs.apply-sandbox.outputs.artifact_sha (it can no longer re-resolve a PR from a dispatch
        commit) and its DuckLake fetch step still reads steps.artifact_sha.outputs.value.
  (vii) both best-effort wake steps derive their PR-lookup SHA from the acknowledge input on a
        dispatch, so the wake targets the incident PR being watched, not an unrelated HEAD commit.

Declares registry.examined(7, unit="topology_invariants") (Decision 170) -- one count per
invariant above, not per individual assertion within one. Loads the workflow via
scripts.verify_ci_workflow._load (never re-implements YAML parsing); registry.skipped(reason) only
if the workflow file itself cannot be read.

Own module because scripts/verify_ci_workflow.py sits at exactly 500 SLOC (Decision 128: never
raise without a marker; a new module beats a facade decomposition for one guard).

Filesystem-only: no subprocess, no network, matching every sibling ci_guards module.
"""

from __future__ import annotations

from typing import Any

from scripts.checks import _common, registry
from scripts.verify_ci_workflow import _load

_WORKFLOW_PATH = ".github/workflows/terraform-apply-sandbox.yml"
_PREFIX = "dispatch-gated-apply-topology"

_ROUTED_SIGNAL = "needs.apply-sandbox.outputs.routed == 'true'"
_PUSH_CONJUNCT = "github.event_name == 'push'"
_DISPATCH_EVENT = "github.event_name == 'workflow_dispatch'"
_FRESH_PLAN_PENDING = "needs.apply-sandbox.outputs.fresh_plan_pending == 'true'"
_FRESH_PLAN_NOT_PENDING = "needs.apply-sandbox.outputs.fresh_plan_pending != 'true'"
_ACK_INPUT = "acknowledge_red_commit"


def _report(failed: list[str], label: str, ok: bool, detail: str = "") -> None:
    """One PASS/FAIL line plus, on failure, one DISTINCT `dispatch-gated-apply-topology: <label>` entry."""
    if ok:
        print(f"  PASS: {label}")
        return
    print(f"  FAIL: {label}{f' ({detail})' if detail else ''}")
    failed.append(f"{_PREFIX}: {label}")


def _steps(job: Any) -> list[dict[str, Any]]:
    steps = job.get("steps") if isinstance(job, dict) else None
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _step_body(step: dict[str, Any]) -> str:
    """Flatten one step's `run:`, `if:`, and `env:` values into a single searchable string."""
    env = step.get("env") or {}
    env_text = "\n".join(f"{key}: {value}" for key, value in env.items() if isinstance(value, str))
    return f"{step.get('run') or ''}\n{step.get('if') or ''}\n{env_text}"


def _find_step(
    steps: list[dict[str, Any]], *, step_id: str | None = None, uses_prefix: str | None = None
) -> dict[str, Any] | None:
    for step in steps:
        if step_id is not None and step.get("id") == step_id:
            return step
        if uses_prefix is not None and str(step.get("uses", "")).startswith(uses_prefix):
            return step
    return None


def _check_invariant_i(failed: list[str], gated_if: str) -> None:
    _report(
        failed,
        "(i) gated-apply if carries the routed signal and no push conjunct",
        _ROUTED_SIGNAL in gated_if and _PUSH_CONJUNCT not in gated_if,
        repr(gated_if),
    )


def _check_invariant_ii(failed: list[str], gated_job: dict[str, Any], gated_steps: list[dict[str, Any]]) -> None:
    _report(
        failed,
        "(ii) gated-apply declares environment: tf-gated-apply",
        gated_job.get("environment") == "tf-gated-apply",
        repr(gated_job.get("environment")),
    )
    apply_step = _find_step(gated_steps, step_id="apply")
    apply_body = str(apply_step.get("run", "")) if apply_step else ""
    _report(
        failed,
        "(ii) gated-apply's apply step runs terraform apply ... plan.bin",
        apply_step is not None and "terraform apply" in apply_body and "plan.bin" in apply_body,
        repr(apply_body),
    )
    replan_steps = [str(step.get("run", "")) for step in gated_steps if "terraform plan" in str(step.get("run", ""))]
    _report(
        failed,
        "(ii) no step in gated-apply runs terraform plan",
        not replan_steps,
        f"re-plan step(s) found: {replan_steps}",
    )


def _check_invariant_iii(failed: list[str], apply_sandbox_outputs: dict[str, Any]) -> None:
    _report(
        failed,
        "(iii) apply-sandbox declares fresh_plan_pending from the EMIT step's outcome",
        "steps.upload_fresh_plan_sha256.outcome" in str(apply_sandbox_outputs.get("fresh_plan_pending", "")),
        repr(apply_sandbox_outputs.get("fresh_plan_pending")),
    )
    _report(
        failed,
        "(iii) apply-sandbox declares fresh_plan_sha256",
        "steps.upload_fresh_plan_sha256.outputs.sha256" in str(apply_sandbox_outputs.get("fresh_plan_sha256", "")),
        repr(apply_sandbox_outputs.get("fresh_plan_sha256")),
    )
    _report(
        failed,
        "(iii) apply-sandbox declares artifact_sha",
        "steps.artifact_sha.outputs.value" in str(apply_sandbox_outputs.get("artifact_sha", "")),
        repr(apply_sandbox_outputs.get("artifact_sha")),
    )


def _check_invariant_iv(failed: list[str], apply_sandbox_steps: list[dict[str, Any]]) -> None:
    emit_step = _find_step(apply_sandbox_steps, step_id="upload_fresh_plan_sha256")
    emit_if = str(emit_step.get("if", "")) if emit_step else ""
    _report(
        failed,
        "(iv) the sha256 EMIT step is gated on workflow_dispatch AND guard routed",
        emit_step is not None and _DISPATCH_EVENT in emit_if and "steps.guard.outputs.routed == 'true'" in emit_if,
        repr(emit_if),
    )
    upload_step = next(
        (
            step
            for step in apply_sandbox_steps
            if str(step.get("uses", "")).startswith("actions/upload-artifact") and step.get("id") != "download"
        ),
        None,
    )
    upload_if = str(upload_step.get("if", "")) if upload_step else ""
    _report(
        failed,
        "(iv) the upload-artifact step is gated on workflow_dispatch AND guard routed",
        upload_step is not None and _DISPATCH_EVENT in upload_if and "steps.guard.outputs.routed == 'true'" in upload_if,
        repr(upload_if),
    )


def _check_invariant_v(failed: list[str], gated_steps: list[dict[str, Any]]) -> None:
    download_step = _find_step(gated_steps, uses_prefix="actions/download-artifact")
    download_if = str(download_step.get("if", "")) if download_step else ""
    _report(
        failed,
        "(v) gated-apply's download-artifact step is gated on fresh_plan_pending",
        download_step is not None and _FRESH_PLAN_PENDING in download_if,
        repr(download_if),
    )
    verify_step = _find_step(gated_steps, step_id="verify_fresh_plan_sha256")
    verify_if = str(verify_step.get("if", "")) if verify_step else ""
    _report(
        failed,
        "(v) gated-apply's sha256 VERIFY step is gated on fresh_plan_pending",
        verify_step is not None and _FRESH_PLAN_PENDING in verify_if,
        repr(verify_if),
    )
    fetch_plan_step = _find_step(gated_steps, step_id="fetch_plan")
    fetch_plan_if = str(fetch_plan_step.get("if", "")) if fetch_plan_step else ""
    _report(
        failed,
        "(v) gated-apply's fetch_plan step is gated on NOT fresh_plan_pending AND push",
        fetch_plan_step is not None and _FRESH_PLAN_NOT_PENDING in fetch_plan_if and _PUSH_CONJUNCT in fetch_plan_if,
        repr(fetch_plan_if),
    )


def _check_invariant_vi(failed: list[str], gated_steps: list[dict[str, Any]]) -> None:
    artifact_sha_step = _find_step(gated_steps, step_id="artifact_sha")
    artifact_sha_body = str(artifact_sha_step.get("run", "")) if artifact_sha_step else ""
    _report(
        failed,
        "(vi) gated-apply's artifact_sha step echoes needs.apply-sandbox.outputs.artifact_sha",
        artifact_sha_step is not None and "needs.apply-sandbox.outputs.artifact_sha" in artifact_sha_body,
        repr(artifact_sha_body),
    )
    build_step = next(
        (step for step in gated_steps if str(step.get("uses", "")).endswith("build-ducklake-artifacts")),
        None,
    )
    build_with = build_step.get("with", {}) if build_step else {}
    _report(
        failed,
        "(vi) gated-apply's build-ducklake-artifacts step keeps mode fetch reading steps.artifact_sha.outputs.value",
        build_step is not None
        and build_with.get("mode") == "fetch"
        and "steps.artifact_sha.outputs.value" in str(build_with.get("artifact-sha", "")),
        repr(build_with),
    )


def _check_invariant_vii(
    failed: list[str], apply_sandbox_steps: list[dict[str, Any]], gated_steps: list[dict[str, Any]]
) -> None:
    wake_steps = [step for step in apply_sandbox_steps + gated_steps if "wake" in str(step.get("name", "")).lower()]
    bad = [step.get("name") for step in wake_steps if _ACK_INPUT not in str((step.get("env") or {}).get("SHA", ""))]
    _report(
        failed,
        "(vii) both best-effort wake steps derive SHA from the acknowledge input",
        len(wake_steps) == 2 and not bad,
        f"wake step count={len(wake_steps)}, not deriving from {_ACK_INPUT}: {bad}",
    )


@registry.register("validate_dispatch_gated_apply_topology", owner="platform")
def validate_dispatch_gated_apply_topology(failed: list[str]) -> None:
    """Assert terraform-apply-sandbox.yml's dispatch-reachable gated-apply topology (Decision 183;
    rec-2918 part (c)). See module docstring for the seven invariants."""
    print("\n=== dispatch-gated-apply topology guard ===")
    try:
        data = _load(str(_common.ROOT / _WORKFLOW_PATH))
    except Exception as exc:
        print(f"  FAIL: could not load {_WORKFLOW_PATH}: {exc}")
        registry.skipped(f"workflow file unreadable: {exc}")
        return

    jobs = data.get("jobs") or {}
    apply_sandbox = jobs.get("apply-sandbox") or {}
    gated_apply = jobs.get("gated-apply") or {}

    if not apply_sandbox or not gated_apply:
        print("  FAIL: apply-sandbox or gated-apply job missing from the workflow")
        failed.append(f"{_PREFIX}: apply-sandbox or gated-apply job missing")
        registry.examined(0, unit="topology_invariants")
        return

    apply_sandbox_steps = _steps(apply_sandbox)
    gated_steps = _steps(gated_apply)
    gated_if = str(gated_apply.get("if", ""))

    _check_invariant_i(failed, gated_if)
    _check_invariant_ii(failed, gated_apply, gated_steps)
    _check_invariant_iii(failed, apply_sandbox.get("outputs") or {})
    _check_invariant_iv(failed, apply_sandbox_steps)
    _check_invariant_v(failed, gated_steps)
    _check_invariant_vi(failed, gated_steps)
    _check_invariant_vii(failed, apply_sandbox_steps, gated_steps)

    registry.examined(7, unit="topology_invariants")
