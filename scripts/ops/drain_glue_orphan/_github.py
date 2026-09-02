"""mcp__github__ payload normalization and pure oracles for the drain runbook (Decision 76).

A Python process cannot call MCP tools -- the agent calls mcp__github__actions_list /
actions_get / get_job_logs / actions_run_trigger between CLI invocations and hands this module
the raw JSON payload. Everything here is pure: normalize the payload's real shape (measured live,
not assumed from the gh CLI it replaces) to this module's internal shape, then decide.

Four measured shape hazards this module exists to close (rec-3381): the real payload uses `id`,
never `databaseId`; `created_at`, never `createdAt`; list_workflow_jobs double-nests as
{"jobs": {"jobs": [...]}}; and get_job_logs' real envelope is flat -- {job_id, logs_content,
message, original_length} -- with no logs[] array and no job_name key (the shape this module's own
planning context predicted before the payload was actually captured and measured).
"""

from __future__ import annotations

from typing import Any, Optional

from scripts.ops.drain_glue_orphan._world import WorldMovedError

_REPO_OWNER = "benjamin-blake"
_REPO_NAME = "theseus"
_RECONCILE_DISPATCH_FILE = "reconcile.yml"
_APPLY_SANDBOX_DISPATCH_FILE = "terraform-apply-sandbox.yml"
_APPLY_SANDBOX_JOB_NAME = "apply-sandbox"
_REVIEW_STEP_NAME = "Subagent plan review (digest-fed, JSON-classified)"
_PLAN_STEP_NAME = "Terraform plan (workflow_dispatch -- fresh plan)"
_DESTRUCTION_LINE = "aws_glue_catalog_database.ops: Destruction complete"
_GLUE_ORPHAN_ADDRESS = "aws_glue_catalog_database.ops"

_NON_TERMINAL_STATUSES = frozenset({"queued", "in_progress", "requested", "waiting", "pending"})


def normalize_runs(payload: Any) -> list[dict[str, Any]]:
    """Accepts the raw actions_list(list_workflow_runs) envelope ({"workflow_runs": [...],
    "total_count": N}) or an already-unwrapped list. Reads `id` / `created_at` -- the real
    mcp__github__ field names -- never `databaseId` / `createdAt`, the gh-CLI-shaped keys the
    predecessor module read (rec-3381 hazards 1/2: `created_at` absence correlates ZERO candidates
    forever, the silent-failure hazard this normalizer exists to close)."""
    rows = payload.get("workflow_runs", []) if isinstance(payload, dict) else (payload or [])
    return [_normalize_run_row(row) for row in rows]


def normalize_run(payload: dict[str, Any]) -> dict[str, Any]:
    """actions_get(get_workflow_run) returns the same run-object shape as one element of
    list_workflow_runs -- one row normalizer, two callers."""
    return _normalize_run_row(payload)


def _normalize_run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row.get("status"),
        "conclusion": row.get("conclusion"),
        "created_at": row.get("created_at", ""),
    }


def unwrap_jobs_payload(payload: Any) -> list[dict[str, Any]]:
    """actions_list(list_workflow_jobs) double-nests: {"jobs": {"jobs": [...], "total_count": N}}.
    The gh CLI's own `--json jobs` shape is single-nested ({"jobs": [...]}), so a normalizer
    written against that assumption resolves neither shape's job list correctly (rec-3381 hazard
    3, measured live against the reconcile.yml and terraform-apply-sandbox.yml runs this plan's
    context names). Handles the double- and single-nested dict shapes plus an already-unwrapped
    list."""
    if isinstance(payload, list):
        return payload
    inner = payload.get("jobs", [])
    if isinstance(inner, dict):
        return inner.get("jobs", [])
    return inner or []


def find_job(jobs: list[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    return next((j for j in jobs if j.get("name") == name), None)


def is_terminal(run: dict[str, Any]) -> bool:
    return run.get("status") not in _NON_TERMINAL_STATUSES


def find_in_flight_dispatch(runs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """A dispatch-triggered run already NON-TERMINAL -- dispatching again would park a SECOND run
    on the one human approval this drain spends. `runs` is a bounded, already-filtered
    (workflow + event=workflow_dispatch) listing; this adds no filtering of its own beyond the
    terminal/non-terminal split."""
    for run in runs:
        if run.get("status") in _NON_TERMINAL_STATUSES:
            return run
    return None


def select_dispatch_candidate(runs: list[dict[str, Any]], dispatch_timestamp: str) -> Optional[dict[str, Any]]:
    """FAILS CLOSED (raises) on more than one candidate created_at >= dispatch_timestamp; never
    guesses, never picks the newest. An empty dispatch_timestamp must raise rather than silently
    matching the whole listing (`created_at >= ""` is true for every run) -- an unbound timestamp
    immediately after the irreversible dispatch would raise on multiple candidates anyway, but
    fail-closed here catches it one step earlier and names the real cause."""
    if not dispatch_timestamp:
        raise WorldMovedError("empty dispatch_timestamp -- refusing to correlate against an unbound window")
    candidates = [r for r in runs if r.get("created_at", "") >= dispatch_timestamp]
    if len(candidates) > 1:
        raise WorldMovedError(f"more than one dispatch candidate since {dispatch_timestamp} -- correlate by hand, never guess")
    return candidates[0] if candidates else None


def job_log_lines(envelope: dict[str, Any]) -> list[str]:
    """Reads the real get_job_logs envelope: {job_id, logs_content, message, original_length} --
    flat, no logs[] array, no job_name key. Raises when the returned content is shorter than
    original_length: a truncated log must never license a terminal_without_destruction verdict,
    nor a false "zero destroys" read on the converge four-fact oracle."""
    content = envelope.get("logs_content", "")
    lines = content.splitlines()
    original_length = envelope.get("original_length")
    if original_length is not None and len(lines) < original_length:
        raise WorldMovedError(
            f"job log truncated: {len(lines)} lines returned of {original_length} -- refetch with a larger "
            "tail_lines before reading a destruction verdict from this log"
        )
    return lines


def destruction_complete(envelope: dict[str, Any], marker: str = _DESTRUCTION_LINE) -> bool:
    return any(marker in line for line in job_log_lines(envelope))


def no_remaining_glue_delete(envelope: dict[str, Any], marker: str = _GLUE_ORPHAN_ADDRESS) -> bool:
    """CONVERGE fact 1: the fresh main-tip plan carries zero destroys of the orphan address --
    widened deliberately from a general "no glue delete" scan to this specific address, since a
    destroy of any OTHER remaining retired address would also route the guard and this oracle
    tests the premise that made this phase reachable, rather than assuming it."""
    return not any(marker in line for line in job_log_lines(envelope))


def converge_guard_review_facts(jobs_payload: Any) -> dict[str, bool]:
    """guard_routed / review_approving, read from apply-sandbox's own step conclusions -- never
    inferred from log text. Fails closed (raises) when the job or its review step cannot be found:
    inferring guard_routed from either absence would fail OPEN on the authoritative safety oracle
    the whole converge phase exists to check."""
    jobs = unwrap_jobs_payload(jobs_payload)
    job = find_job(jobs, _APPLY_SANDBOX_JOB_NAME)
    if job is None:
        raise WorldMovedError(
            f"world has moved -- re-assess: no job named {_APPLY_SANDBOX_JOB_NAME!r} in the supplied jobs payload"
        )
    steps = {s.get("name"): s for s in job.get("steps", [])}
    review_step = steps.get(_REVIEW_STEP_NAME)
    if review_step is None:
        raise WorldMovedError(
            f"world has moved -- re-assess: job {_APPLY_SANDBOX_JOB_NAME!r} carries no step named "
            f"{_REVIEW_STEP_NAME!r}; the guard/review verdicts cannot be read, and inferring them from its "
            "absence would fail open"
        )
    return {
        "guard_routed": review_step.get("conclusion") == "skipped",
        "review_approving": review_step.get("conclusion") == "success",
    }
