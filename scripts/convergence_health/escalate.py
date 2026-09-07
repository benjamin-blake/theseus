"""Convergence-stale idempotent escalation (CD.35 Wave 6 / T2.35).

Provides an idempotent escalation path: files OR updates a single
tf_convergence_stale rec per red-episode via scripts.ops_data_portal
(file_rec / update_rec). Never writes the convergence record; never runs
terraform apply; never dispatches terraform-apply-sandbox. Part of the
scripts.convergence_health package -- see scripts/convergence_health/__init__.py
for the full public surface.

The file/update/close orchestration below is scripts.rec_episode.run_episode (rec-3291 /
rec-3563): this module used to bulk-fetch every open rec via the `open_recs` named verb and
filter the result on `source`/`status` -- two columns that verb never projects, so the filter
always matched nothing and every red episode re-filed a duplicate rec instead of updating the one
already open. run_episode's find_rec does a source-scoped structural read instead, and raises
rather than silently returning None if a row is ever missing a key this lookup filters on.
"""

from __future__ import annotations

from typing import Any, Optional

from scripts.convergence_health.assess import (
    RED_AGE_THRESHOLD_HOURS,
    STALE_GREEN_BACKLOG_THRESHOLD_HOURS,
    HealthVerdict,
)
from scripts.rec_episode import run_episode

# Three mutually-branched escalation conditions (T2.35 hardening). A stuck gated-apply approval
# takes priority in the title/context even when it co-occurs with a persistently-red record --
# it is the more directly actionable signal (approve/cancel the run). stale_green_backlog and
# persistently_red are mutually exclusive by construction (they require status=="green" and
# status=="red" respectively).
_TITLE_STUCK_APPROVAL = "Gated-apply approval stuck -- staleness escalation"
_TITLE_STALE_GREEN_BACKLOG = "Sandbox convergence green with stale unapplied backlog -- staleness escalation"
_TITLE_PERSISTENTLY_RED = "Sandbox convergence record persistently red -- staleness escalation"

_RESOLUTION_STUCK_APPROVAL = "Gated-apply approval cleared (approved or cancelled); staleness episode resolved."
_RESOLUTION_STALE_GREEN_BACKLOG = "Unapplied terraform/personal/ backlog drained; staleness episode resolved."
_RESOLUTION_PERSISTENTLY_RED = "Convergence record returned to green; staleness episode resolved."

# Per-condition lint-valid acceptance probes (Decision 103 [NOTE]: these are live AWS/gh probes
# because no repo-local command can express "the convergence record returned to green"). Each
# is a static shell command -- credentials-bearing but syntactically real, never prose.
_ACCEPTANCE_STUCK_APPROVAL = (
    "gh api 'repos/benjamin-blake/theseus/actions/workflows/terraform-apply-sandbox.yml/runs"
    "?status=waiting' --jq '.total_count' | grep -qx 0"
)
_ACCEPTANCE_STALE_GREEN_BACKLOG = (
    "aws s3 cp s3://agent-platform-data-lake/convergence/personal/sandbox.json - --profile agent_platform "
    '| grep -q "$(git rev-parse origin/main)"'
)
_ACCEPTANCE_PERSISTENTLY_RED = (
    "aws s3 cp s3://agent-platform-data-lake/convergence/personal/sandbox.json - --profile agent_platform "
    '| grep -q \'"status": "green"\''
)


def _condition_for_verdict(verdict: HealthVerdict) -> str:
    """Classify which of the three escalation conditions this verdict represents."""
    if verdict.stuck_approvals:
        return "stuck_approval"
    if verdict.status == "green" and verdict.unapplied_backlog > 0:
        return "stale_green_backlog"
    return "persistently_red"


def _condition_from_existing_rec(existing: dict[str, Any]) -> str:
    """Recover the escalation condition an open rec was filed for, from its title.

    Needed at close time: by definition every trigger has cleared (over_threshold is False),
    so the current verdict can no longer tell us which condition the rec was tracking.
    """
    title = existing.get("title", "")
    if title == _TITLE_STUCK_APPROVAL:
        return "stuck_approval"
    if title == _TITLE_STALE_GREEN_BACKLOG:
        return "stale_green_backlog"
    return "persistently_red"


def _build_context(verdict: HealthVerdict, condition: str) -> str:
    if condition == "stuck_approval":
        parts = [
            f"{len(verdict.stuck_approvals)} terraform-apply-sandbox run(s) are waiting on "
            "the tf-gated-apply Environment approval (stuck > threshold), independent of the "
            f"convergence record's own status ({verdict.status})."
        ]
        parts.append(
            "Resolve via: approve or cancel the pending gated-apply run in GitHub Actions -> "
            "Review pending deployments. This rec closes automatically on the next sensor "
            "tick once no stuck approvals remain."
        )
    elif condition == "stale_green_backlog":
        parts = [
            f"The sandbox convergence record is green, but {verdict.unapplied_backlog} merged "
            "terraform/personal/ commit(s) have been pending application for "
            f"{verdict.record_age_hours:.1f} hours -- past the "
            f"{STALE_GREEN_BACKLOG_THRESHOLD_HOURS:.1f}h stale-green-backlog threshold."
        ]
        parts.append(
            "Resolve via: run terraform-apply-sandbox workflow_dispatch (or land a "
            "terraform/personal/ change) to apply the pending backlog. This rec closes "
            "automatically on the next sensor tick once the backlog drains."
        )
    else:
        parts = [
            f"The sandbox convergence record has been red for {verdict.red_age_hours:.1f} hours.",
        ]
        if verdict.unapplied_backlog:
            parts.append(
                f"{verdict.unapplied_backlog} merged terraform/personal/ commit(s) are pending "
                "application since the last green convergence commit."
            )
        parts.append(
            "Resolve via: (a) approve the pending gated-apply run in GitHub Actions, or "
            "(b) run terraform-apply-sandbox workflow_dispatch with acknowledge_red_commit "
            "naming the red commit SHA. This rec closes automatically on the next sensor "
            "tick once the convergence record returns to green."
        )
    return " ".join(parts)


def _build_rec_fields(verdict: HealthVerdict, condition: str) -> dict[str, Any]:
    title = {
        "stuck_approval": _TITLE_STUCK_APPROVAL,
        "stale_green_backlog": _TITLE_STALE_GREEN_BACKLOG,
    }.get(condition, _TITLE_PERSISTENTLY_RED)
    acceptance = {
        "stuck_approval": _ACCEPTANCE_STUCK_APPROVAL,
        "stale_green_backlog": _ACCEPTANCE_STALE_GREEN_BACKLOG,
    }.get(condition, _ACCEPTANCE_PERSISTENTLY_RED)
    return {
        "title": title,
        "file": ".github/workflows/convergence-health.yml",
        "status": "open",
        "source": "tf_convergence_stale",
        "priority": "High",
        "effort": "S",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_context(verdict, condition),
        "acceptance": acceptance,
    }


def escalate(
    verdict: HealthVerdict,
    portal_caller: Optional[Any] = None,
    open_recs: Optional[list[dict[str, Any]]] = None,
    threshold_hours: float = RED_AGE_THRESHOLD_HOURS,
    profile: Optional[str] = None,
    reconcile_in_flight: bool = False,
) -> dict[str, Any]:
    """Idempotent escalation: file/update/close exactly one tf_convergence_stale rec per episode.

    Args:
        verdict:       HealthVerdict from assess_health.
        portal_caller: Injected callable(action, fields) for testability. When None,
                       uses scripts.ops_data_portal.file_rec / update_rec directly.
        open_recs:     Pre-fetched rows (for testing) -- treated as if they were already the
                       result of the scoped tf_convergence_stale read. When None, fetches live
                       via current_state("ops_recommendations", row_filter="source = "
                       "'tf_convergence_stale'") (not the JSONL cache, and never a bulk fetch of
                       every open rec).
        threshold_hours: Red-age threshold triggering escalation.
        profile:       AWS profile for the reader / portal.
        reconcile_in_flight: T2.37 c4 -- True when a reconcile.yml Actions run has already
                       started (or completed) during the current red episode (see
                       has_in_flight_reconcile_for_episode). Suppresses ONLY a fresh "file"
                       action -- an already-open rec still updates/closes normally, since
                       refreshing an existing rec's context is not a double-file.

    Returns:
        {"action": "file"|"update"|"unchanged"|"close"|"none"|"skipped"|"skipped_suppressed",
         "rec_id": str|None}
    """
    stuck_approval_trigger = bool(verdict.stuck_approvals)
    red_age_trigger = verdict.status == "red" and verdict.red_age_hours >= threshold_hours
    stale_green_backlog_trigger = (
        verdict.status == "green"
        and verdict.unapplied_backlog > 0
        and verdict.record_age_hours >= STALE_GREEN_BACKLOG_THRESHOLD_HOURS
    )
    over_threshold = stuck_approval_trigger or red_age_trigger or stale_green_backlog_trigger

    def _build_fields() -> dict[str, Any]:
        condition = _condition_for_verdict(verdict)
        return _build_rec_fields(verdict, condition)

    def _build_update(existing: dict[str, Any]) -> dict[str, Any]:
        condition = _condition_for_verdict(verdict)
        return {"context": _build_context(verdict, condition)}

    def _build_close(existing: dict[str, Any]) -> dict[str, Any]:
        condition = _condition_from_existing_rec(existing)
        resolution = {
            "stuck_approval": _RESOLUTION_STUCK_APPROVAL,
            "stale_green_backlog": _RESOLUTION_STALE_GREEN_BACKLOG,
        }.get(condition, _RESOLUTION_PERSISTENTLY_RED)
        return {"status": "closed", "resolution": resolution}

    return run_episode(
        source="tf_convergence_stale",
        over_threshold=over_threshold,
        build_fields=_build_fields,
        build_update=_build_update,
        build_close=_build_close,
        suppress_file=reconcile_in_flight,
        portal_caller=portal_caller,
        rows=open_recs,
        profile=profile,
    )
