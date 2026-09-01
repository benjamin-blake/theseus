"""Executable drain runbook for the Decision 178 clause 4 reconcile (PLAN-glue-delete-database-grant).

Realizes VP steps 10-12 (OPERATOR, post-deploy) as three phases -- ``--phase remove``, ``--phase
converge``, ``--phase close`` -- one operator invocation each. Every phase does the same three
things IN ORDER: DERIVE runtime world-state (never a hardcoded SHA, rec id, or assumption), GATE on
it (fail closed with "world has moved -- re-assess" naming the fluent that moved, rather than
proceeding on a stale assumption), then ACT.

Reuses scripts.ci.reconcile_target for the convergence-record read and the bundled-rec open check
(the same two seams tests/test_reconcile_target.py already stubs). The FOUR workflow-topology
invariants this drain depends on are asserted here by PARSING committed source (never grep or a
substring test -- both were measured INVERTING the verdict, see assert_workflow_invariants), so a
workflow or budget edit that would silently break the drain reds a test instead of a critique
finding nobody re-runs.

No dispatch fires twice: the remove phase refuses to dispatch Reconcile while a dispatch-triggered
run is already in a non-terminal status (the dispatch is an irreversible side effect that fires
BEFORE correlation can fail, and the drain spends exactly ONE human tf-gated-apply approval).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from scripts.ci import reconcile_target

_ROOT = Path(__file__).resolve().parents[2]
_TFSTATE_BUCKET = "agent-platform-data-lake"
_TFSTATE_KEY = "tfstate/personal/sandbox/terraform.tfstate"
_ORPHAN_TYPE = "aws_glue_catalog_database"
_ORPHAN_NAME = "ops"
_BUNDLED_REC_IDS = ("rec-3348", "rec-3328")
_APPLY_SANDBOX_WORKFLOW_REL = ".github/workflows/terraform-apply-sandbox.yml"
_RECONCILE_WORKFLOW_REL = ".github/workflows/reconcile.yml"
_AUTHORITY_BUDGET_REL = "terraform/bootstrap/authority_budget.json"
_RECONCILE_DISPATCH_FILE = "reconcile.yml"
_APPLY_SANDBOX_DISPATCH_FILE = "terraform-apply-sandbox.yml"
_APPLY_SANDBOX_JOB_NAME = "apply-sandbox"
_REVIEW_STEP_NAME = "Subagent plan review (digest-fed, JSON-classified)"
_PLAN_STEP_NAME = "Terraform plan (workflow_dispatch -- fresh plan)"
_REMOVAL_REC_TITLE = "Remove the time-boxed glue drain grant now that aws_glue_catalog_database.ops has left state"
# The three _REMOVAL_REC_* constants are the ONE sanctioned exemption from the no-hardcoded-fluent
# source scan (TestWorkflowInvariants::test_module_source_carries_no_hardcoded_fluent): they are
# filed rec CONTENT, not an operational fluent this module reads or branches on.
_REMOVAL_REC_CONTEXT = (
    "Both the identity GlueCatalog Sid and the boundary glue:* ceiling entry were restored SOLELY to "
    "drain the aws_glue_catalog_database.ops orphan the 7b67e21d cleanse left in tfstate (Decision 178 "
    "clause 4 reconcile, rec-3348/rec-3328). Now that the resource is out of state, no remaining HCL "
    "can reach any glue verb, so both grants become standing unused authority on a public-repo CI "
    "identity -- remove them at both layers."
)
_REMOVAL_REC_ACCEPTANCE = (
    "bin/venv-python -m pytest "
    "tests/checks/iam_tf/test_glue_catalog_grant_scope.py::TestGlueCatalogGrantRemoved::"
    "test_glue_sid_absent_at_both_layers -q"
)


class WorldMovedError(RuntimeError):
    """A phase's runtime-derived precondition no longer holds -- fail closed, never proceed stale."""


# ---------------------------------------------------------------------------
# ASSERT: the four routing invariants, parsed from committed STRUCTURED source (never grep).
# ---------------------------------------------------------------------------


def assert_workflow_invariants(repo_root: Path = _ROOT) -> None:
    """Parse (never grep/substring) the two workflow YAMLs + authority_budget.json for the four
    facts this drain's routing depends on. A substring test for "aws_iam_role" against
    in_budget_resource_types INVERTS the verdict (matches the aws_iam_role_policy prefix); a
    file-level grep for event_name false-positives on reconcile.yml's own comment about
    apply-sandbox. Raises WorldMovedError naming every violated invariant, never silently."""
    apply_sandbox = yaml.safe_load((repo_root / _APPLY_SANDBOX_WORKFLOW_REL).read_text(encoding="utf-8"))
    reconcile_wf = yaml.safe_load((repo_root / _RECONCILE_WORKFLOW_REL).read_text(encoding="utf-8"))
    budget = json.loads((repo_root / _AUTHORITY_BUDGET_REL).read_text(encoding="utf-8"))

    violations: list[str] = []

    gated_apply_if = str(apply_sandbox.get("jobs", {}).get("gated-apply", {}).get("if", ""))
    if "github.event_name == 'push'" not in gated_apply_if:
        violations.append("(a) terraform-apply-sandbox.yml gated-apply no longer requires github.event_name == 'push'")

    gar_if = str(reconcile_wf.get("jobs", {}).get("gated-apply-reconcile", {}).get("if", ""))
    if "github.event_name == 'push'" in gar_if:
        violations.append("(b) reconcile.yml gated-apply-reconcile now carries a push condition")

    in_budget_types = budget.get("in_budget_resource_types", [])
    if "aws_iam_role" in in_budget_types:
        violations.append("(c) authority_budget.json in_budget_resource_types now exact-lists aws_iam_role")

    apply_steps = apply_sandbox.get("jobs", {}).get("apply-sandbox", {}).get("steps", [])
    checkout = apply_steps[0] if apply_steps else {}
    if "ref" in (checkout.get("with") or {}):
        violations.append("(d) apply-sandbox's checkout step now pins a ref:")
    fresh_plan: dict[str, Any] = next((s for s in apply_steps if s.get("id") == "plan"), {})
    if "github.event_name == 'workflow_dispatch'" not in str(fresh_plan.get("if", "")):
        violations.append("(d) apply-sandbox's fresh-plan step is no longer gated on workflow_dispatch")

    if violations:
        raise WorldMovedError("world has moved -- re-assess: " + "; ".join(violations))


# ---------------------------------------------------------------------------
# DERIVE: runtime world-state (never a hardcoded SHA, rec id, or assumption).
# ---------------------------------------------------------------------------


def tfstate_has_orphan(s3_client: Any, bucket: str = _TFSTATE_BUCKET, key: str = _TFSTATE_KEY) -> bool:
    """Read-only S3 get_object on the tfstate object (Decision 119 bars a local terraform init) --
    look for a resources[] entry whose type/name match the orphan. Same injected-client seam as
    reconcile_target.read_convergence_record, so tests stub both the same way."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    state = json.loads(response["Body"].read())
    return any(r.get("type") == _ORPHAN_TYPE and r.get("name") == _ORPHAN_NAME for r in state.get("resources", []))


@dataclass
class RemoveState:
    record: Optional[dict]
    target: reconcile_target.ReconcileTarget
    orphan_in_state: bool
    rec_open: dict[str, bool]


def derive_remove_state(s3_client: Any, rec_reader: Callable[[str], list[dict[str, Any]]]) -> RemoveState:
    record = reconcile_target.read_convergence_record(s3_client)
    target = reconcile_target.resolve_reconcile_target(record)
    orphan_in_state = tfstate_has_orphan(s3_client)
    rec_open = {rec_id: reconcile_target.validate_rec_id_open(rec_id, rec_reader) for rec_id in _BUNDLED_REC_IDS}
    return RemoveState(record=record, target=target, orphan_in_state=orphan_in_state, rec_open=rec_open)


def gate_remove_preconditions(state: RemoveState) -> None:
    if not state.target.actionable:
        raise WorldMovedError(f"world has moved -- re-assess: convergence record is not reconcilable ({state.target.reason})")
    if not state.orphan_in_state:
        raise WorldMovedError(f"world has moved -- re-assess: {_ORPHAN_TYPE}.{_ORPHAN_NAME} is no longer in tfstate")
    # Both this gate and phase_close require the bundled recs CLOSED, and that is not a copy-paste
    # slip: rec-autoclose.yml flips them open -> closed at the merge of the PR that puts the restored
    # grant in HCL, and that merge is the precondition for the drain existing at all. Gating remove on
    # "still open" made this phase unreachable in its own intended sequence -- it could only run before
    # the merge that makes the destroy authorizable.
    still_open = sorted(rec_id for rec_id, is_open in state.rec_open.items() if is_open)
    if still_open:
        raise WorldMovedError(
            f"world has moved -- re-assess: bundled rec(s) still open: {still_open} -- the enabling PR has not "
            "merged, so the restored grant is not in HCL and the destroy would AccessDeny as the original apply did"
        )


def gate_converge_preconditions(record: Optional[dict], orphan_in_state: bool) -> None:
    if record is None or record.get("status") != "red":
        raise WorldMovedError(f"world has moved -- re-assess: convergence record is not CONVERGENCE_RED ({record!r})")
    if orphan_in_state:
        raise WorldMovedError(
            f"world has moved -- re-assess: {_ORPHAN_TYPE}.{_ORPHAN_NAME} is still in tfstate -- drain phase 1 has not landed"
        )


# ---------------------------------------------------------------------------
# Re-entrancy gate + bounded dispatch correlation (remove phase only -- the ONE phase that spends
# the drain's single human tf-gated-apply approval).
# ---------------------------------------------------------------------------

_NON_TERMINAL_STATUSES = frozenset({"queued", "in_progress", "requested", "waiting", "pending"})


def find_in_flight_dispatch(runs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """A dispatch-triggered Reconcile run already NON-TERMINAL -- dispatching again would park a
    SECOND run on the one human approval this drain spends. `runs` is a bounded, already-filtered
    (workflow=reconcile, event=workflow_dispatch) listing; this function adds no filtering of its
    own beyond the terminal/non-terminal split."""
    for run in runs:
        if run.get("status") in _NON_TERMINAL_STATUSES:
            return run
    return None


@dataclass
class CorrelationResult:
    outcome: str  # "correlated" | "dispatched_but_not_correlated"
    run: Optional[dict[str, Any]] = None
    dispatch_timestamp: str = ""


def correlate_dispatch(
    run_lister: Callable[[], list[dict[str, Any]]],
    dispatch_timestamp: str,
    sleeper: Callable[[float], None] = time.sleep,
    attempts: int = 18,
    interval_s: float = 10.0,
) -> CorrelationResult:
    """Re-query the SAME bounded filter every interval_s for up to attempts*interval_s (default 3
    min) before zero candidates becomes a verdict -- a workflow_dispatch run takes seconds to
    appear. FAILS CLOSED on more than one candidate; never --limit 1 (that would be a guess)."""
    for attempt in range(attempts):
        candidates = [r for r in run_lister() if r.get("createdAt", "") >= dispatch_timestamp]
        if len(candidates) > 1:
            raise WorldMovedError(
                f"more than one Reconcile dispatch candidate since {dispatch_timestamp} -- correlate by hand, never guess"
            )
        if len(candidates) == 1:
            return CorrelationResult(outcome="correlated", run=candidates[0])
        if attempt < attempts - 1:
            sleeper(interval_s)
    return CorrelationResult(outcome="dispatched_but_not_correlated", dispatch_timestamp=dispatch_timestamp)


def wait_for_terminal(
    run_viewer: Callable[[str], dict[str, Any]],
    run_id: str,
    sleeper: Callable[[float], None] = time.sleep,
    attempts: int = 120,
    interval_s: float = 30.0,
) -> Optional[dict[str, Any]]:
    """Poll every interval_s up to attempts*interval_s (default 60 min). Returns None on timeout --
    NOT decisive, never grounds for the state-rm fallback (only a TERMINAL run without the
    Destruction-complete line is)."""
    for attempt in range(attempts):
        run = run_viewer(run_id)
        if run.get("status") == "completed":
            return run
        if attempt < attempts - 1:
            sleeper(interval_s)
    return None


# ---------------------------------------------------------------------------
# Phase orchestration
# ---------------------------------------------------------------------------


@dataclass
class PhaseOutcome:
    status: str
    detail: str
    fluents: dict[str, Any] = field(default_factory=dict)

    def report(self) -> int:
        print(f"drain_glue_orphan[{self.status}]: {self.detail}")
        for key, value in self.fluents.items():
            print(f"  {key}={value}")
        return 0 if self.status not in ("world_moved", "error") else 1


def phase_remove(
    *,
    s3_client: Any,
    rec_reader: Callable[[str], list[dict[str, Any]]],
    dispatcher: Callable[[], None],
    run_lister: Callable[[], list[dict[str, Any]]],
    run_viewer: Callable[[str], dict[str, Any]],
    clock: Callable[[], str],
    repo_root: Path = _ROOT,
    sleeper: Callable[[float], None] = time.sleep,
) -> PhaseOutcome:
    assert_workflow_invariants(repo_root)
    state = derive_remove_state(s3_client, rec_reader)
    print(f"drain_glue_orphan[derived]: record={state.record!r} orphan={state.orphan_in_state} rec_open={state.rec_open}")
    gate_remove_preconditions(state)

    in_flight = find_in_flight_dispatch(run_lister())
    if in_flight is not None:
        return PhaseOutcome(
            "already_dispatched",
            "a dispatch-triggered Reconcile run is already in flight -- resuming the WAIT against it, not dispatching again",
            {"run_id": in_flight.get("databaseId"), "status": in_flight.get("status")},
        )

    dispatch_ts = clock()
    dispatcher()
    correlation = correlate_dispatch(run_lister, dispatch_ts, sleeper=sleeper)
    if correlation.outcome != "correlated":
        return PhaseOutcome(
            "dispatched_but_not_correlated",
            f"Reconcile was dispatched at {dispatch_ts} but the bounded correlation window found no unique candidate -- "
            "the run almost certainly exists; correlate by hand (gh run list --workflow reconcile.yml --event "
            f'workflow_dispatch --created ">={dispatch_ts}"). Do NOT re-invoke this phase.',
            {"dispatch_timestamp": dispatch_ts},
        )

    assert correlation.run is not None, "correlated outcome always carries a run"
    run_id = str(correlation.run["databaseId"])
    terminal_run = wait_for_terminal(run_viewer, run_id, sleeper=sleeper)
    if terminal_run is None:
        return PhaseOutcome(
            "awaiting_approval", "still running / timed out awaiting tf-gated-apply approval", {"run_id": run_id}
        )

    drained = "aws_glue_catalog_database.ops: Destruction complete" in str(terminal_run.get("log", ""))
    status = "drained" if drained else "terminal_without_destruction"
    return PhaseOutcome(status, f"Reconcile run {run_id} reached a terminal status", {"run_id": run_id, "drained": drained})


def phase_converge(
    *,
    s3_client: Any,
    dispatcher: Callable[[str], None],
    run_lister: Callable[[], list[dict[str, Any]]],
    run_viewer: Callable[[str], dict[str, Any]],
    clock: Callable[[], str],
    repo_root: Path = _ROOT,
    sleeper: Callable[[float], None] = time.sleep,
) -> PhaseOutcome:
    assert_workflow_invariants(repo_root)
    record = reconcile_target.read_convergence_record(s3_client)
    orphan_in_state = tfstate_has_orphan(s3_client)
    print(f"drain_glue_orphan[derived]: record={record!r} orphan_in_state={orphan_in_state}")
    gate_converge_preconditions(record, orphan_in_state)
    assert record is not None, "gate_converge_preconditions raises WorldMovedError when record is None"

    ack_sha = record["commit_sha"]
    dispatch_ts = clock()
    dispatcher(ack_sha)
    correlation = correlate_dispatch(run_lister, dispatch_ts, sleeper=sleeper)
    if correlation.outcome != "correlated":
        return PhaseOutcome(
            "dispatched_but_not_correlated",
            f"apply-sandbox acknowledge-and-retry dispatched at {dispatch_ts} but not uniquely correlated",
            {"dispatch_timestamp": dispatch_ts, "acknowledge_red_commit": ack_sha},
        )

    assert correlation.run is not None, "correlated outcome always carries a run"
    run_id = str(correlation.run["databaseId"])
    terminal_run = wait_for_terminal(run_viewer, run_id, sleeper=sleeper)
    if terminal_run is None:
        return PhaseOutcome("awaiting_terminal", "apply-sandbox run still running / timed out", {"run_id": run_id})

    post_record = reconcile_target.read_convergence_record(s3_client)
    facts = {
        "no_remaining_glue_delete": "aws_glue_catalog_database.ops" not in str(terminal_run.get("plan_log", "")),
        "guard_passed": terminal_run.get("guard_routed") is not True,
        "review_approving": terminal_run.get("review_approving") is True,
        "record_green": post_record is not None and post_record.get("status") == "green",
    }
    status = "converged" if all(facts.values()) else "not_converged"
    return PhaseOutcome(status, f"apply-sandbox run {run_id} reached a terminal status", {"run_id": run_id, **facts})


def phase_close(
    *,
    s3_client: Any,
    rec_reader: Callable[[str], list[dict[str, Any]]],
    file_rec: Callable[..., str],
    get_rec_write_guidance: Callable[..., Any],
    profile: Optional[str] = None,
) -> PhaseOutcome:
    """Re-derives both bundled recs' status from the warehouse (never the local JSONL read cache),
    confirming the Resolves trailer + rec-autoclose.yml fired rather than assuming it. Refuses to
    file the removal-obligation rec while the orphan is still in state -- fail-closed, not a bug: a
    removal obligation for a grant still in use is the exact fail-open this restructure prevents."""
    still_open = [rec_id for rec_id in _BUNDLED_REC_IDS if reconcile_target.validate_rec_id_open(rec_id, rec_reader)]
    if still_open:
        return PhaseOutcome(
            "recs_still_open",
            f"bundled rec(s) still open -- the Resolves trailer did not fire: {still_open}. Close manually via "
            "ops_data_portal --update-rec with a resolution naming the merge SHA (Decision 70 fallback).",
            {"still_open": still_open},
        )

    if tfstate_has_orphan(s3_client):
        return PhaseOutcome(
            "orphan_still_in_state",
            f"{_ORPHAN_TYPE}.{_ORPHAN_NAME} is still in tfstate -- refusing to file the removal-obligation rec "
            "(a removal obligation for a grant still in use is the exact fail-open this restructure prevents)",
        )

    # Decision 66 Precision Context Injection (AGENTS.md, VP step 12): field semantics reach
    # context BEFORE composition, never as a post-rejection error.
    get_rec_write_guidance(source="manual")
    rec_id = file_rec(
        {
            "title": _REMOVAL_REC_TITLE,
            "file": "terraform/bootstrap/github_ci_apply_policy.tf",
            "status": "open",
            "source": "manual",
            "effort": "XS",
            "priority": "High",
            "risk": "low",
            "context": _REMOVAL_REC_CONTEXT,
            "acceptance": _REMOVAL_REC_ACCEPTANCE,
        },
        profile=profile,
    )
    return PhaseOutcome("filed", f"bundled recs closed; filed removal-obligation {rec_id}", {"removal_rec_id": rec_id})


# ---------------------------------------------------------------------------
# Live wiring (gh CLI + boto3) -- CLI entry point.
# ---------------------------------------------------------------------------


def _gh_json(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def _live_run_lister_for(workflow_file: str) -> Callable[[], list[dict[str, Any]]]:
    """Bounded `gh run list` correlator scoped to ONE workflow file.

    Each phase must correlate against the workflow it ACTUALLY dispatched: remove dispatches
    reconcile.yml, converge dispatches terraform-apply-sandbox.yml. A shared default silently
    made the converge phase poll Reconcile for an apply-sandbox run, so it could never correlate
    and its four-fact oracle was unreachable -- hence the workflow is a parameter, never a
    module-level default, and tests/ops/test_drain_glue_orphan.py pins the per-phase pairing.
    """

    def _lister() -> list[dict[str, Any]]:
        rows = _gh_json(
            [
                "run",
                "list",
                "--workflow",
                workflow_file,
                "--event",
                "workflow_dispatch",
                "--limit",
                "20",
                "--json",
                "databaseId,status,conclusion,createdAt",
            ]
        )
        return rows or []

    return _lister


def _live_run_viewer(run_id: str) -> dict[str, Any]:
    row = _gh_json(["run", "view", run_id, "--json", "status,conclusion,databaseId"]) or {}
    if row.get("status") == "completed":
        log = subprocess.run(
            ["gh", "run", "view", run_id, "--log"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        row["log"] = log.stdout
    return row


def _live_converge_run_viewer(run_id: str) -> dict[str, Any]:
    """phase_converge's run_viewer: on top of _live_run_viewer's status/log, resolves the guard
    and review facts from apply-sandbox's OWN job/step conclusions (gh run view --json jobs) --
    structured and reliable, rather than parsing the review action's raw JSON envelope out of
    combined log text. guard_routed = the review step never ran (skipped, since it is gated
    `if: steps.guard.outputs.routed != 'true'`); review_approving = the review step's own
    conclusion is success (the action itself fails closed on REVISE/STARVED)."""
    row = _live_run_viewer(run_id)
    if row.get("status") != "completed":
        return row
    jobs_payload = _gh_json(["run", "view", run_id, "--json", "jobs"]) or {}
    job: dict[str, Any] = next((j for j in jobs_payload.get("jobs", []) if j.get("name") == _APPLY_SANDBOX_JOB_NAME), {})
    steps = {s.get("name"): s for s in job.get("steps", [])}
    review_step = steps.get(_REVIEW_STEP_NAME)
    if review_step is None:
        # FAIL CLOSED. guard_routed is derived from this step being SKIPPED (it is gated
        # `if: steps.guard.outputs.routed != 'true'`), so a renamed or removed step would read as
        # "not skipped" -> guard passed -- fail-open on the authoritative safety oracle. A step
        # this module cannot find means the workflow topology moved, which is exactly the
        # condition the rest of this module refuses to proceed past.
        raise WorldMovedError(
            f"world has moved -- re-assess: apply-sandbox run {run_id} carries no step named "
            f"{_REVIEW_STEP_NAME!r}; the guard/review verdicts cannot be read, and inferring them "
            "from its absence would fail open"
        )
    plan_step = steps.get(_PLAN_STEP_NAME)
    plan_log = ""
    if plan_step is not None and job.get("databaseId"):
        job_log = subprocess.run(
            ["gh", "run", "view", run_id, "--job", str(job["databaseId"]), "--log"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        plan_log = job_log.stdout
    row["guard_routed"] = review_step.get("conclusion") == "skipped"
    row["review_approving"] = review_step.get("conclusion") == "success"
    row["plan_log"] = plan_log
    return row


def _live_dispatch_reconcile() -> None:
    subprocess.run(["gh", "workflow", "run", _RECONCILE_DISPATCH_FILE], check=True, timeout=30)


def _live_dispatch_apply_sandbox(acknowledge_red_commit: str) -> None:
    subprocess.run(
        ["gh", "workflow", "run", _APPLY_SANDBOX_DISPATCH_FILE, "-f", f"acknowledge_red_commit={acknowledge_red_commit}"],
        check=True,
        timeout=30,
    )


def _live_clock() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="drain_glue_orphan.py")
    parser.add_argument("--phase", choices=("remove", "converge", "close"), required=True)
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)

    import boto3  # noqa: PLC0415

    s3_client = boto3.Session(profile_name=args.profile or None).client("s3")
    rec_reader = reconcile_target._default_reader(args.profile)

    try:
        if args.phase == "remove":
            outcome = phase_remove(
                s3_client=s3_client,
                rec_reader=rec_reader,
                dispatcher=_live_dispatch_reconcile,
                run_lister=_live_run_lister_for(_RECONCILE_DISPATCH_FILE),
                run_viewer=_live_run_viewer,
                clock=_live_clock,
            )
        elif args.phase == "converge":
            outcome = phase_converge(
                s3_client=s3_client,
                dispatcher=_live_dispatch_apply_sandbox,
                run_lister=_live_run_lister_for(_APPLY_SANDBOX_DISPATCH_FILE),
                run_viewer=_live_converge_run_viewer,
                clock=_live_clock,
            )
        else:
            from scripts.executor.rec_write_guidance import get_rec_write_guidance  # noqa: PLC0415
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            outcome = phase_close(
                s3_client=s3_client,
                rec_reader=rec_reader,
                file_rec=file_rec,
                get_rec_write_guidance=get_rec_write_guidance,
                profile=args.profile,
            )
    except WorldMovedError as exc:
        print(f"drain_glue_orphan[world_moved]: {exc}", file=sys.stderr)
        return 1

    return outcome.report()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
