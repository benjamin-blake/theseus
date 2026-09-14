#!/usr/bin/env python3
"""Convergence-drift classifier + refusal-cause renderer (Decision 190, PLAN-convergence-drift-
classification).

STDLIB-ONLY BY DESIGN. Placed in scripts/ci/ deliberately: that package has no __init__.py and
resolves via PEP 420 with only the stdlib, which is the sole placement callable from
terraform-apply-sandbox.yml -- that workflow installs NO Python dependencies anywhere in its
1030 lines (mirrors the scripts.ci.convergence_advisory precedent, Decision 172 PR-2).
scripts.convergence_health is an eager facade whose import pulls yaml and boto3 and would
ImportError there.

The 2026-09-13 incident: a plan showing resource_changes with EMPTY resource_drift (a benign
code-behind-state delta from an operator-sanctioned split-apply, not out-of-band infra change) was
red-latched by terraform-drift.yml's bare `plan_ec == 2` branch, which cannot distinguish "drift"
from "the code hasn't caught up to a change applied out-of-band yet". classify_plan() discriminates
the three outcomes from the MEASURED plan content -- never from the exit code alone:

  resource_drift non-empty                              -> OUT_OF_BAND_DRIFT (WHATEVER resource_changes holds)
  resource_drift empty AND resource_changes non-empty    -> PENDING_CODIFICATION
  both empty                                             -> CONVERGED
  unparseable / non-object JSON                          -> OUT_OF_BAND_DRIFT (never CONVERGED -- fail-closed)

This module also hosts the marker read/write helpers BOTH workflows call (terraform-drift.yml
writes/self-clears/escalates the pending_codification marker; terraform-apply-sandbox.yml renders
the CONVERGENCE_RED refusal naming the measured cause) and the red_cause discriminator shared with
scripts/ci_rca/convergence_dedup.py's own drift-vs-apply-failure split (Decision 142: one
authority, never a second divergent classifier) and scripts/ci/convergence_advisory.py's red-status
wording (both modules import derive_red_cause / render_convergence_advisory_red_description
directly -- same package, no subprocess boundary).

first_seen on the pending_codification marker is WRITE-ONCE (setdefault) -- mirrors
pending_gated.drift_flagged_at's write-once idempotence (terraform-drift.yml), NOT
pending_gated/infra_error's own routed_at, which both overwrite unconditionally. Against the
hourly drift cron, a refreshed first_seen would cap the marker's measured age at ~1h and the
PENDING_CODIFICATION_BOUND_HOURS bound below could never fire.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

CONVERGED = "converged"
PENDING_CODIFICATION = "pending_codification"
OUT_OF_BAND_DRIFT = "out_of_band_drift"
VERDICTS = (CONVERGED, PENDING_CODIFICATION, OUT_OF_BAND_DRIFT)

# Matches STALE_GREEN_BACKLOG_THRESHOLD_HOURS (scripts.convergence_health.assess) -- both bounds
# exist to catch a benign-looking state that has stopped being benign. Kept as an independent
# constant (not imported -- that module pulls yaml/boto3) rather than re-derived.
PENDING_CODIFICATION_BOUND_HOURS = 2.0

RED_CAUSE_OUT_OF_BAND_DRIFT = "out_of_band_drift"
RED_CAUSE_APPLY_FAILURE = "apply_failure"


def classify_plan(plan_json_text: str) -> str:
    """Classify a `terraform show -json` plan into one of the three exhaustive VERDICTS.

    Pure function of the plan JSON text -- no I/O, no AWS call, so every branch is unit-provable.
    Fail-closed: unparseable/non-object JSON classifies as OUT_OF_BAND_DRIFT, never CONVERGED --
    an unreadable plan must never be treated as evidence of nothing having changed.
    """
    try:
        plan = json.loads(plan_json_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return OUT_OF_BAND_DRIFT
    if not isinstance(plan, dict):
        return OUT_OF_BAND_DRIFT
    if plan.get("resource_drift"):
        return OUT_OF_BAND_DRIFT
    if plan.get("resource_changes"):
        return PENDING_CODIFICATION
    return CONVERGED


def derive_red_cause(record: dict[str, Any]) -> str:
    """Measured red-cause discriminator: reads the SAME drift markers
    scripts/ci_rca/convergence_dedup.py's find_open_convergence_cause_rec already discriminates
    on (drift_run_url present) -- Decision 142 one authority, never a second divergent classifier.
    """
    if record.get("drift_run_url"):
        return RED_CAUSE_OUT_OF_BAND_DRIFT
    return RED_CAUSE_APPLY_FAILURE


def render_convergence_red_refusal(record: dict[str, Any]) -> str:
    """Build the CONVERGENCE_RED refusal message naming the MEASURED cause.

    On a drift-caused red, the last-successful-apply commit_sha is stale provenance (merge-
    preserved from the last green write, never touched by a drift red-flip) -- this never
    presents it as the cause, unlike the pre-plan bare `::error::` line which named only commit.
    """
    commit = record.get("commit_sha", "") or ""
    cause = derive_red_cause(record)
    if cause == RED_CAUSE_OUT_OF_BAND_DRIFT:
        reason = record.get("drift_reason") or "out-of-band infra drift"
        run_url = record.get("drift_run_url") or ""
        detected_at = record.get("drift_detected_at") or "an unknown time"
        return (
            f"CONVERGENCE_RED main is non-converged due to MEASURED out-of-band drift ({reason}), "
            f"detected {detected_at} ({run_url}); the last-successful-apply commit {commit} is stale "
            "provenance, not the cause of this red. Review the drift run and resolve via the "
            f"dispatch-ack apply path (workflow_dispatch acknowledge_red_commit={commit}, or the "
            "open rec id) after the failure is reviewed (Decision 55/72)."
        )
    return (
        f"CONVERGENCE_RED main is non-converged at commit {commit} (last sandbox apply FAILED; "
        "cause=apply_failure). Apply REFUSED and the record was NOT overwritten. Unlatch via "
        f"workflow_dispatch acknowledge_red_commit={commit} (or the open rec id) after the failure "
        "is reviewed (Decision 55/72)."
    )


def render_convergence_advisory_red_description(record: dict[str, Any]) -> str:
    """Build the terraform-converged advisory FAILURE description for a red record, naming the
    measured cause instead of unconditionally asserting "last sandbox apply RED at {commit}" --
    which is false on a drift-caused red (that commit is the last SUCCESSFUL apply)."""
    commit = record.get("commit_sha", "") or ""
    cause = derive_red_cause(record)
    if cause == RED_CAUSE_OUT_OF_BAND_DRIFT:
        run_url = record.get("drift_run_url") or ""
        return (
            f"main is non-converged (MEASURED out-of-band drift at {run_url}; commit {commit} is the "
            "last successful apply, not the failing one). Advisory only -- not a required check."
        )
    return f"main is non-converged (last sandbox apply RED at {commit}). Advisory only -- not a required check."


def _format_ts(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(ts: str) -> datetime:
    ts = (ts or "").rstrip("Z")
    if not ts:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def build_pending_codification_marker(
    existing_marker: Optional[dict[str, Any]], now: datetime, run_url: str
) -> dict[str, Any]:
    """Read-modify-write shape for the pending_codification marker. first_seen is WRITE-ONCE
    (setdefault) -- see module docstring; last_seen and run_url refresh on every write, mirroring
    the pending_gated/infra_error marker shape otherwise."""
    marker = dict(existing_marker) if isinstance(existing_marker, dict) else {}
    ts = _format_ts(now)
    marker.setdefault("first_seen", ts)
    marker["last_seen"] = ts
    marker["run_url"] = run_url
    return marker


def pending_codification_age_hours(marker: dict[str, Any], now: datetime) -> float:
    """Hours since the marker's write-once first_seen. 0.0 for a malformed/absent first_seen."""
    if not isinstance(marker, dict):
        return 0.0
    first_seen = marker.get("first_seen")
    if not first_seen:
        return 0.0
    since = _parse_utc(first_seen)
    return max(0.0, (now - since).total_seconds() / 3600.0)


def pending_codification_is_stale(
    marker: dict[str, Any], now: datetime, bound_hours: float = PENDING_CODIFICATION_BOUND_HOURS
) -> bool:
    """True once a pending_codification marker's measured age reaches the bound -- a
    misclassified real drift must never sit indefinitely under a benign marker."""
    return pending_codification_age_hours(marker, now) >= bound_hours


def apply_pending_codification_write(existing_record: Optional[dict[str, Any]], now: datetime, run_url: str) -> dict[str, Any]:
    """Merge a pending_codification marker onto the record. Status is read-modify-written
    UNCHANGED (anti-masking, Decision 55) -- absent status defaults to green (pass-on-absent
    convention, matches terraform-drift.yml's prior_status read), never a literal overwrite.
    commit_sha and every other top-level field are untouched (STRICTLY ADDITIVE schema)."""
    record = dict(existing_record) if isinstance(existing_record, dict) else {}
    record.setdefault("status", "green")
    existing_marker = record.get("pending_codification")
    record["pending_codification"] = build_pending_codification_marker(existing_marker, now, run_url)
    return record


def escalate_stale_pending_codification(
    existing_record: Optional[dict[str, Any]], now: datetime, run_url: str
) -> dict[str, Any]:
    """A pending_codification marker that outlived PENDING_CODIFICATION_BOUND_HOURS without
    self-clearing escalates to a genuine red -- the marker is removed (superseded by the red
    status, never left to coexist and confuse a reader) and drift_reason/drift_run_url/
    drift_detected_at are set exactly as the out-of-band-drift write already does, so every
    existing red-status reader (reconcile_target, convergence_advisory, the refusal renderer)
    handles it identically to a directly-measured drift red."""
    record = dict(existing_record) if isinstance(existing_record, dict) else {}
    record.pop("pending_codification", None)
    record["status"] = "red"
    record["drift_detected_at"] = _format_ts(now)
    record["drift_run_url"] = run_url
    record["drift_reason"] = (
        "a pending_codification marker exceeded the "
        f"{PENDING_CODIFICATION_BOUND_HOURS:.1f}h bound without self-clearing -- escalated to "
        "out-of-band drift (the benign code-behind-state classification is no longer trusted)"
    )
    return record


def self_clear_pending_codification(existing_record: Optional[dict[str, Any]], now: datetime) -> Optional[dict[str, Any]]:
    """On a plan_ec == 0 cycle (no changes at all), self-clear a present pending_codification
    marker and write a durable closure stamp (Decision 55 anti-hiding: the episode's resolution
    must be recorded, never silently reverted without a trace). Returns None (no-op) when no
    marker is present -- the caller skips the S3 write entirely in that case."""
    record = dict(existing_record) if isinstance(existing_record, dict) else {}
    if not isinstance(record.get("pending_codification"), dict):
        return None
    record.pop("pending_codification", None)
    # Named to NOT contain "pending_codification" as a substring (code-review finding): every
    # reader of the marker's absence -- terraform-drift.yml's self-clear read-back verify,
    # escalate.py's two rec-acceptance probes -- greps the bare string "pending_codification",
    # so a closure-stamp key containing that substring would make a genuine self-clear look like
    # the marker is still present, forever.
    record["benign_delta_resolved_at"] = _format_ts(now)
    return record


def decide_pending_codification_action(existing_record: Optional[dict[str, Any]], now: datetime) -> str:
    """ "escalate" when the existing pending_codification marker has gone stale, else "mark"."""
    record = existing_record or {}
    marker = record.get("pending_codification")
    if isinstance(marker, dict) and pending_codification_is_stale(marker, now):
        return "escalate"
    return "mark"


def _read_json_env(name: str) -> dict[str, Any]:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _cmd_classify_plan() -> int:
    plan_text = os.environ.get("PLAN_JSON", "")
    print(classify_plan(plan_text))
    return 0


def _cmd_refusal() -> int:
    record = _read_json_env("REC_JSON")
    print(derive_red_cause(record))
    print(record.get("commit_sha", "") or "")
    print(render_convergence_red_refusal(record))
    return 0


def _cmd_pending_codification_write() -> int:
    existing = _read_json_env("EXISTING")
    run_url = os.environ.get("RUN_URL", "")
    now = datetime.now(timezone.utc)
    if decide_pending_codification_action(existing, now) == "escalate":
        print("escalated")
        print(json.dumps(escalate_stale_pending_codification(existing, now, run_url)))
    else:
        print("marked")
        print(json.dumps(apply_pending_codification_write(existing, now, run_url)))
    return 0


def _cmd_self_clear() -> int:
    existing = _read_json_env("EXISTING")
    now = datetime.now(timezone.utc)
    cleared = self_clear_pending_codification(existing, now)
    if cleared is None:
        print("noop")
    else:
        print("cleared")
        print(json.dumps(cleared))
    return 0


_COMMANDS = {
    "--classify-plan": _cmd_classify_plan,
    "--refusal": _cmd_refusal,
    "--pending-codification-write": _cmd_pending_codification_write,
    "--self-clear": _cmd_self_clear,
}


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for flag, handler in _COMMANDS.items():
        if flag in argv:
            return handler()
    print(f"usage: python3 -m scripts.ci.convergence_classify [{'|'.join(_COMMANDS)}]", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
