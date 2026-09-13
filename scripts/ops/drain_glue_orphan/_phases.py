"""Phase/step orchestration for the drain runbook: PhaseOutcome plus the gate/correlate/verify
sub-phases for remove and converge, and phase_close (unchanged in shape from the pre-split module).

Each function is a pure decision over injected evidence (S3 clients, a rec reader, and -- for the
GitHub-touching steps -- an already-fetched raw mcp__github__ payload). No function here calls an
MCP tool or sleeps: the CLI (__main__.py) is invoked once per step, the agent supplies the previous
step's on-disk record plus any freshly-fetched payload, and a "not yet terminal" verdict just names
the same command to re-run later -- the re-invokable-verify pattern Decision 76 requires in place
of a polling loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from scripts.ci import reconcile_target
from scripts.ops.drain_glue_orphan._github import (
    _APPLY_SANDBOX_DISPATCH_FILE,
    _RECONCILE_DISPATCH_FILE,
    _REPO_NAME,
    _REPO_OWNER,
    assert_log_matches_job,
    assert_plan_step_ran,
    converge_guard_review_facts,
    destruction_complete,
    find_in_flight_dispatch,
    is_terminal,
    no_remaining_glue_delete,
    normalize_run,
    normalize_runs,
    plan_shows_zero_destroys,
    resolve_apply_sandbox_job,
    select_dispatch_candidate,
)
from scripts.ops.drain_glue_orphan._world import (
    _BUNDLED_REC_IDS,
    _ROOT,
    RemoveState,
    WorldMovedError,
    assert_workflow_invariants,
    derive_remove_state,
    gate_converge_preconditions,
    gate_remove_preconditions,
    tfstate_has_orphan,
)

_REMOVAL_REC_TITLE = "Remove the time-boxed glue drain grant now that aws_glue_catalog_database.ops has left state"
# The three _REMOVAL_REC_* constants are the ONE sanctioned exemption from the no-hardcoded-fluent
# source scan (TestPreconditionGates::test_module_source_carries_no_hardcoded_fluent): they are
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


@dataclass
class PhaseOutcome:
    status: str
    detail: str
    fluents: dict[str, Any] = field(default_factory=dict)
    next_action: Optional[dict[str, Any]] = None

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"verdict": self.status, "detail": self.detail, "fluents": self.fluents}
        if self.next_action is not None:
            record["next_action"] = self.next_action
        return record

    def report(self) -> int:
        print(f"drain_glue_orphan[{self.status}]: {self.detail}")
        for key, value in self.fluents.items():
            print(f"  {key}={value}")
        if self.next_action is not None:
            print(f"  next_action={self.next_action}")
        return 0 if self.status not in ("world_moved", "error") else 1


def _resume_or_dispatch(
    runs_payload: Any,
    dispatch_ts: str,
    *,
    resume_detail: str,
    dispatch_detail: str,
    dispatch_fluents: dict[str, Any],
    next_action: dict[str, Any],
) -> PhaseOutcome:
    runs = normalize_runs(runs_payload)
    in_flight = find_in_flight_dispatch(runs)
    if in_flight is not None:
        return PhaseOutcome("resume", resume_detail, {"run_id": in_flight["id"], "status": in_flight["status"]})
    return PhaseOutcome(
        "dispatch", dispatch_detail, {"dispatch_timestamp": dispatch_ts, **dispatch_fluents}, next_action=next_action
    )


def _correlate(gate_record: dict[str, Any], runs_payload: Any) -> PhaseOutcome:
    if gate_record.get("verdict") != "dispatch":
        raise WorldMovedError(
            f"cannot correlate: predecessor gate record does not carry verdict=dispatch (got {gate_record.get('verdict')!r})"
        )
    dispatch_ts = (gate_record.get("fluents") or {}).get("dispatch_timestamp")
    if not dispatch_ts:
        raise WorldMovedError("gate record carries no dispatch_timestamp -- cannot correlate")
    runs = normalize_runs(runs_payload)
    candidate = select_dispatch_candidate(runs, dispatch_ts)
    if candidate is None:
        return PhaseOutcome(
            "no_candidates",
            f"zero candidates created at or after {dispatch_ts} -- re-list and re-run this step; do NOT re-dispatch",
            {"dispatch_timestamp": dispatch_ts},
        )
    return PhaseOutcome("correlated", f"correlated run {candidate['id']}", {"run_id": candidate["id"]})


def _resolve_verified_run(
    correlation_record: dict[str, Any], run_payload: dict[str, Any]
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Shared verify precondition: correlation record must carry verdict=correlated, and the
    freshly-fetched run must match the recorded id -- verify refuses to report on the wrong run."""
    if correlation_record.get("verdict") != "correlated":
        raise WorldMovedError(
            f"cannot verify: predecessor correlation record does not carry verdict=correlated "
            f"(got {correlation_record.get('verdict')!r})"
        )
    recorded_run_id = (correlation_record.get("fluents") or {}).get("run_id")
    run = normalize_run(run_payload)
    if run["id"] != recorded_run_id:
        raise WorldMovedError(
            f"fetched run id {run['id']} disagrees with recorded {recorded_run_id!r} -- refusing to verify the wrong run"
        )
    if not is_terminal(run):
        return None, run
    return run, run


# ---------------------------------------------------------------------------
# REMOVE
# ---------------------------------------------------------------------------


def remove_gate(
    *,
    profile_s3_client: Any,
    state_s3_client: Any,
    rec_reader: Callable[[str], list[dict[str, Any]]],
    runs_payload: Any,
    clock: Callable[[], str],
    repo_root: Any = _ROOT,
) -> PhaseOutcome:
    assert_workflow_invariants(repo_root)
    state: RemoveState = derive_remove_state(profile_s3_client, state_s3_client, rec_reader)
    print(f"drain_glue_orphan[derived]: record={state.record!r} orphan={state.orphan_in_state} rec_open={state.rec_open}")
    gate_remove_preconditions(state)
    dispatch_ts = clock()
    return _resume_or_dispatch(
        runs_payload,
        dispatch_ts,
        resume_detail=(
            "a dispatch-triggered Reconcile run is already in flight -- resume against it (skip to verify), do not "
            "dispatch again"
        ),
        dispatch_detail=f"preconditions clean and no in-flight run -- dispatch Reconcile now (gate time {dispatch_ts})",
        dispatch_fluents={},
        next_action={
            "tool": "mcp__github__actions_run_trigger",
            "method": "run_workflow",
            "owner": _REPO_OWNER,
            "repo": _REPO_NAME,
            "workflow_id": _RECONCILE_DISPATCH_FILE,
            "ref": "main",
        },
    )


def remove_correlate(*, gate_record: dict[str, Any], runs_payload: Any) -> PhaseOutcome:
    return _correlate(gate_record, runs_payload)


def remove_verify(
    *, correlation_record: dict[str, Any], run_payload: dict[str, Any], job_logs_payload: dict[str, Any]
) -> PhaseOutcome:
    terminal_run, run = _resolve_verified_run(correlation_record, run_payload)
    if terminal_run is None:
        return PhaseOutcome(
            "not_yet_terminal",
            (
                f"run {run['id']} status={run['status']!r} -- still running / awaiting tf-gated-apply approval; "
                "re-run this same command later"
            ),
            {"run_id": run["id"], "status": run["status"]},
        )
    # This step has no jobs payload to correlate against (VP16 supplies only the run and the log),
    # so the envelope's own job_id is recorded on the verdict rather than left implicit: the
    # irreversible step's evidence must name which job's log licensed it.
    job_id = job_logs_payload.get("job_id")
    if job_id is None:
        raise WorldMovedError(
            "job-logs envelope carries no job_id -- refusing to license a destruction verdict from a log "
            "that cannot say which job it came from"
        )
    if destruction_complete(job_logs_payload):
        return PhaseOutcome(
            "drained", f"Reconcile run {run['id']} destroyed the orphan", {"run_id": run["id"], "job_id": job_id}
        )
    return PhaseOutcome(
        "terminal_without_destruction",
        f"Reconcile run {run['id']} reached a terminal status with NO destruction line -- escalate to operator, "
        "never terraform state rm",
        {"run_id": run["id"], "job_id": job_id},
        next_action={"tool": "escalate_to_operator"},
    )


# ---------------------------------------------------------------------------
# CONVERGE
# ---------------------------------------------------------------------------


def converge_gate(
    *,
    profile_s3_client: Any,
    state_s3_client: Any,
    runs_payload: Any,
    clock: Callable[[], str],
    repo_root: Any = _ROOT,
) -> PhaseOutcome:
    assert_workflow_invariants(repo_root)
    record = reconcile_target.read_convergence_record(profile_s3_client)
    orphan_in_state = tfstate_has_orphan(state_s3_client)
    print(f"drain_glue_orphan[derived]: record={record!r} orphan_in_state={orphan_in_state}")
    gate_converge_preconditions(record, orphan_in_state)
    assert record is not None, "gate_converge_preconditions raises WorldMovedError when record is None"
    ack_sha = record["commit_sha"]
    dispatch_ts = clock()
    return _resume_or_dispatch(
        runs_payload,
        dispatch_ts,
        resume_detail=(
            "a dispatch-triggered apply-sandbox run is already in flight -- resume against it, do not dispatch again"
        ),
        dispatch_detail=f"preconditions clean and no in-flight run -- dispatch apply-sandbox now (gate time {dispatch_ts})",
        dispatch_fluents={"acknowledge_red_commit": ack_sha},
        next_action={
            "tool": "mcp__github__actions_run_trigger",
            "method": "run_workflow",
            "owner": _REPO_OWNER,
            "repo": _REPO_NAME,
            "workflow_id": _APPLY_SANDBOX_DISPATCH_FILE,
            "ref": "main",
            "inputs": {"acknowledge_red_commit": ack_sha},
        },
    )


def converge_correlate(*, gate_record: dict[str, Any], runs_payload: Any) -> PhaseOutcome:
    return _correlate(gate_record, runs_payload)


def converge_verify(
    *,
    correlation_record: dict[str, Any],
    run_payload: dict[str, Any],
    jobs_payload: Any,
    job_logs_payload: dict[str, Any],
    profile_s3_client: Any,
) -> PhaseOutcome:
    terminal_run, run = _resolve_verified_run(correlation_record, run_payload)
    if terminal_run is None:
        return PhaseOutcome(
            "not_yet_terminal",
            f"run {run['id']} status={run['status']!r} -- still running; re-run this same command later",
            {"run_id": run["id"], "status": run["status"]},
        )
    # Fail-closed preconditions BEFORE any fact is read: the supplied log must belong to the
    # apply-sandbox job of the correlated run, and the step that produces the plan log must exist.
    # Neither is a fact -- a verdict read from another job's log is not a "not_converged", it is
    # evidence this module must refuse outright.
    job = resolve_apply_sandbox_job(jobs_payload)
    assert_plan_step_ran(job)
    job_id = assert_log_matches_job(job_logs_payload, job)
    raw = converge_guard_review_facts(jobs_payload)
    post_record = reconcile_target.read_convergence_record(profile_s3_client)
    # Every key here is POSITIVE polarity (True == good) so all(facts.values()) means what it
    # says -- guard_routed (True == the guard BLOCKED) inverts to guard_passed on the way in,
    # rather than being fed to all() in its raw, blocked-is-truthy shape.
    facts: dict[str, Any] = {
        "plan_zero_destroys": plan_shows_zero_destroys(job_logs_payload),
        "guard_passed": raw["guard_routed"] is not True,
        "review_approving": raw["review_approving"] is True,
        # CORRELATED, not merely green: the record carries the run_id of whichever run wrote it,
        # so an uncorrelated status check would accept a green written by a concurrent push apply
        # or a stale green from an earlier run -- the same correlation hole closed above for the
        # job log, one field over. Both sides are str()-coerced: the record serializes run_id as a
        # string while the runs payload reports it as an int.
        "record_green_for_this_run": (
            post_record is not None
            and post_record.get("status") == "green"
            and str(post_record.get("run_id")) == str(run["id"])
        ),
    }
    status = "converged" if all(facts.values()) else "not_converged"
    return PhaseOutcome(
        status,
        f"apply-sandbox run {run['id']} reached a terminal status",
        {
            "run_id": run["id"],
            "apply_sandbox_job_id": job_id,
            # Diagnostic, deliberately outside facts: VP19's fix_if triages a non-empty destroy
            # set by whether the orphan itself or some other retired address is still going.
            "orphan_delete_absent": no_remaining_glue_delete(job_logs_payload),
            **facts,
        },
    )


# ---------------------------------------------------------------------------
# CLOSE
# ---------------------------------------------------------------------------


def phase_close(
    *,
    profile_s3_client: Any,
    state_s3_client: Any,
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

    if tfstate_has_orphan(state_s3_client):
        return PhaseOutcome(
            "orphan_still_in_state",
            "aws_glue_catalog_database.ops is still in tfstate -- refusing to file the removal-obligation rec "
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
