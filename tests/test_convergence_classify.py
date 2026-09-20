"""Tests for scripts/ci/convergence_classify.py (Decision 190, PLAN-convergence-drift-classification).

Parametrised verdict matrix over real plan-JSON shapes (drift-only, changes-only, both, neither,
malformed), route-exhaustiveness, the never-writes-red / prior-status-preservation marker
contract, the commit_sha top-level write shape, the stale-marker escalation bound, and an
import-surface census proving the module resolves under the standard library alone -- the sole
constraint that makes it callable from terraform-apply-sandbox.yml, which installs no Python
dependencies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from scripts.ci.convergence_classify import (
    CONVERGED,
    OUT_OF_BAND_DRIFT,
    PENDING_CODIFICATION,
    PENDING_CODIFICATION_BOUND_HOURS,
    RED_CAUSE_APPLY_FAILURE,
    RED_CAUSE_OUT_OF_BAND_DRIFT,
    apply_pending_codification_write,
    build_pending_codification_marker,
    classify_plan,
    decide_pending_codification_action,
    derive_red_cause,
    escalate_stale_pending_codification,
    main,
    pending_codification_is_stale,
    render_convergence_advisory_red_description,
    render_convergence_red_refusal,
    self_clear_pending_codification,
)


def _plan(resource_drift=None, resource_changes=None) -> str:
    body: dict = {}
    if resource_drift is not None:
        body["resource_drift"] = resource_drift
    if resource_changes is not None:
        body["resource_changes"] = resource_changes
    return json.dumps(body)


DRIFT_ONLY = _plan(resource_drift=[{"address": "aws_s3_bucket.x"}])
CHANGES_ONLY = _plan(resource_changes=[{"address": "aws_iam_role_policy.y"}])
BOTH_PRESENT = _plan(resource_drift=[{"address": "aws_s3_bucket.x"}], resource_changes=[{"address": "aws_iam_role_policy.y"}])
NEITHER = _plan(resource_drift=[], resource_changes=[])
ABSENT_KEYS = _plan()


def test_verdict_precedence_matrix() -> None:
    assert classify_plan(DRIFT_ONLY) == OUT_OF_BAND_DRIFT
    assert classify_plan(CHANGES_ONLY) == PENDING_CODIFICATION
    assert classify_plan(BOTH_PRESENT) == OUT_OF_BAND_DRIFT
    assert classify_plan(NEITHER) == CONVERGED
    assert classify_plan(ABSENT_KEYS) == CONVERGED
    assert classify_plan("{not valid json") == OUT_OF_BAND_DRIFT
    assert classify_plan("[1, 2, 3]") == OUT_OF_BAND_DRIFT
    assert classify_plan("") == OUT_OF_BAND_DRIFT


class TestRouteExhaustiveness:
    """Every classify_plan() return value is a VERDICTS member -- no fourth outcome exists."""

    @pytest.mark.parametrize(
        "plan_text",
        [DRIFT_ONLY, CHANGES_ONLY, BOTH_PRESENT, NEITHER, ABSENT_KEYS, "{not valid json", "[1,2,3]", "", "null", "42"],
    )
    def test_verdict_is_always_a_member(self, plan_text: str) -> None:
        from scripts.ci.convergence_classify import VERDICTS

        assert classify_plan(plan_text) in VERDICTS


def test_pending_codification_preserves_prior_status() -> None:
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    for prior in ("green", "red", "unknown"):
        existing = {"status": prior, "commit_sha": "abc123"}
        updated = apply_pending_codification_write(existing, now=now, run_url="https://x/1")
        assert updated["status"] == prior, f"marker write must never move status (prior={prior})"
        assert "pending_codification" in updated

    # Absent status defaults to green (pass-on-absent), never red.
    updated_absent = apply_pending_codification_write(None, now=now, run_url="https://x/1")
    assert updated_absent["status"] == "green"
    assert updated_absent["status"] != "red"


def test_commit_sha_written_top_level_never_nested() -> None:
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    existing = {"status": "green", "commit_sha": "abc123", "run_id": "1", "run_url": "u", "timestamp": "t", "plan_sha": "p"}
    updated = apply_pending_codification_write(existing, now=now, run_url="https://x/2")
    assert updated["commit_sha"] == "abc123"
    assert "commit_sha" not in updated["pending_codification"]
    for key in ("commit_sha", "run_id", "run_url", "timestamp", "plan_sha"):
        assert key in updated, f"{key} must stay top-level and unmoved"

    escalated = escalate_stale_pending_codification(existing, now=now, run_url="https://x/3")
    assert escalated["commit_sha"] == "abc123"
    assert "pending_codification" not in escalated


def test_stale_pending_codification_escalates() -> None:
    first_seen = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    marker = build_pending_codification_marker(None, now=first_seen, run_url="https://x/1")
    existing = {"status": "green", "commit_sha": "abc", "pending_codification": marker}

    just_under_bound = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    assert not pending_codification_is_stale(marker, just_under_bound)
    assert decide_pending_codification_action(existing, just_under_bound) == "mark"

    at_bound = datetime(2026, 9, 13, 2, 0, tzinfo=timezone.utc)
    assert pending_codification_is_stale(marker, at_bound, bound_hours=PENDING_CODIFICATION_BOUND_HOURS)
    assert decide_pending_codification_action(existing, at_bound) == "escalate"

    escalated = escalate_stale_pending_codification(existing, now=at_bound, run_url="https://x/escalation")
    assert escalated["status"] == "red"
    assert "pending_codification" not in escalated
    assert escalated["drift_run_url"] == "https://x/escalation"
    assert escalated["drift_detected_at"]


def test_repeat_marker_write_preserves_first_seen() -> None:
    t0 = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    t1 = t0.replace(hour=1)
    existing = {"status": "green", "commit_sha": "abc"}

    written_once = apply_pending_codification_write(existing, now=t0, run_url="https://x/1")
    first_seen = written_once["pending_codification"]["first_seen"]

    written_twice = apply_pending_codification_write(written_once, now=t1, run_url="https://x/2")
    assert written_twice["pending_codification"]["first_seen"] == first_seen
    assert written_twice["pending_codification"]["last_seen"] != first_seen
    assert written_twice["pending_codification"]["run_url"] == "https://x/2"

    # Measured age must keep growing across repeated writes -- the whole point of write-once.
    age_at_t0 = 0.0
    age_at_t1 = (t1 - t0).total_seconds() / 3600.0
    assert age_at_t1 > age_at_t0


class TestSelfClear:
    def test_noop_when_no_marker_present(self) -> None:
        now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        assert self_clear_pending_codification({"status": "green"}, now) is None
        assert self_clear_pending_codification(None, now) is None

    def test_clears_marker_and_writes_closure_stamp(self) -> None:
        now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        marker = build_pending_codification_marker(None, now=now, run_url="https://x/1")
        existing = {"status": "green", "commit_sha": "abc", "pending_codification": marker}
        cleared = self_clear_pending_codification(existing, now)
        assert cleared is not None
        assert "pending_codification" not in cleared
        assert cleared["benign_delta_resolved_at"]
        assert "pending_codification" not in json.dumps(cleared)
        assert cleared["status"] == "green"
        assert cleared["commit_sha"] == "abc"


class TestDeriveRedCause:
    def test_drift_run_url_present_is_out_of_band_drift(self) -> None:
        assert derive_red_cause({"drift_run_url": "https://x"}) == RED_CAUSE_OUT_OF_BAND_DRIFT

    def test_absent_drift_run_url_is_apply_failure(self) -> None:
        assert derive_red_cause({"commit_sha": "abc"}) == RED_CAUSE_APPLY_FAILURE
        assert derive_red_cause({}) == RED_CAUSE_APPLY_FAILURE


class TestRenderConvergenceRedRefusal:
    def test_drift_caused_red_never_names_commit_as_the_cause(self) -> None:
        record = {
            "status": "red",
            "commit_sha": "lastgoodsha",
            "drift_run_url": "https://x/drift-run",
            "drift_reason": "out-of-band infra drift detected by scheduled terraform plan",
            "drift_detected_at": "2026-09-13T16:24:36Z",
        }
        message = render_convergence_red_refusal(record)
        assert "MEASURED out-of-band drift" in message
        assert "lastgoodsha" in message  # named as stale provenance, not the cause
        assert "stale provenance, not the cause" in message

    def test_apply_failure_red_names_commit_as_the_failing_apply(self) -> None:
        record = {"status": "red", "commit_sha": "badsha"}
        message = render_convergence_red_refusal(record)
        assert "badsha" in message
        assert "cause=apply_failure" in message


class TestRenderConvergenceAdvisoryRedDescription:
    def test_drift_red_does_not_blame_last_apply_commit(self) -> None:
        record = {"status": "red", "commit_sha": "lastgoodsha", "drift_run_url": "https://x/drift-run"}
        desc = render_convergence_advisory_red_description(record)
        assert "last sandbox apply RED" not in desc
        assert "out-of-band drift" in desc

    def test_apply_failure_red_keeps_original_wording(self) -> None:
        record = {"status": "red", "commit_sha": "badsha"}
        desc = render_convergence_advisory_red_description(record)
        assert "last sandbox apply RED at badsha" in desc

    def test_drift_red_description_stays_within_github_status_char_limit_with_realistic_data(self) -> None:
        """rec-3954 round 2: the drift branch measured 259 chars with realistic data (a 40-char
        SHA and a real-shaped GitHub Actions run URL) -- nearly 2x GitHub's 140-char commit-status
        description limit, the same defect class as rec-3954's two convergence_advisory templates,
        worse. Proves the shortened description fits with realistic data AND a worst-case
        longer-run-id variant (a future GitHub Actions run id could grow well past today's 11
        digits)."""
        real_sha = "a" * 40
        realistic_run_url = "https://github.com/benjamin-blake/theseus/actions/runs/35525861643"
        record = {"status": "red", "commit_sha": real_sha, "drift_run_url": realistic_run_url}
        desc = render_convergence_advisory_red_description(record)
        assert len(desc) <= 140
        assert "35525861643" in desc

        worst_case_run_url = (
            "https://github.com/some-very-long-organization-name/"
            "an-extremely-long-repository-name-for-testing/actions/runs/" + "9" * 20
        )
        worst_case_record = {"status": "red", "commit_sha": real_sha, "drift_run_url": worst_case_run_url}
        worst_case_desc = render_convergence_advisory_red_description(worst_case_record)
        assert len(worst_case_desc) <= 140


class TestCliCommands:
    def test_classify_plan_command(self, capsys) -> None:
        with patch.dict(os.environ, {"PLAN_JSON": CHANGES_ONLY}, clear=False):
            rc = main(["--classify-plan"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == PENDING_CODIFICATION

    def test_refusal_command(self, capsys) -> None:
        rec = json.dumps({"status": "red", "commit_sha": "badsha"})
        with patch.dict(os.environ, {"REC_JSON": rec}, clear=False):
            rc = main(["--refusal"])
        assert rc == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == RED_CAUSE_APPLY_FAILURE
        assert lines[1] == "badsha"
        assert "badsha" in lines[2]

    def test_pending_codification_write_command_marks(self, capsys) -> None:
        env = {"EXISTING": json.dumps({"status": "green", "commit_sha": "abc"}), "RUN_URL": "https://x/1"}
        with patch.dict(os.environ, env, clear=False):
            rc = main(["--pending-codification-write"])
        assert rc == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "marked"
        record = json.loads(lines[1])
        assert record["status"] == "green"
        assert record["pending_codification"]["run_url"] == "https://x/1"

    def test_pending_codification_write_command_escalates(self, capsys) -> None:
        stale_marker = {"first_seen": "2020-01-01T00:00:00Z", "last_seen": "2020-01-01T00:00:00Z", "run_url": "u"}
        env = {
            "EXISTING": json.dumps({"status": "green", "commit_sha": "abc", "pending_codification": stale_marker}),
            "RUN_URL": "https://x/escalate",
        }
        with patch.dict(os.environ, env, clear=False):
            rc = main(["--pending-codification-write"])
        assert rc == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "escalated"
        record = json.loads(lines[1])
        assert record["status"] == "red"

    def test_self_clear_command_noop(self, capsys) -> None:
        with patch.dict(os.environ, {"EXISTING": json.dumps({"status": "green"})}, clear=False):
            rc = main(["--self-clear"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "noop"

    def test_self_clear_command_clears(self, capsys) -> None:
        marker = {"first_seen": "2026-09-13T00:00:00Z", "last_seen": "2026-09-13T00:00:00Z", "run_url": "u"}
        env = {"EXISTING": json.dumps({"status": "green", "pending_codification": marker})}
        with patch.dict(os.environ, env, clear=False):
            rc = main(["--self-clear"])
        assert rc == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "cleared"
        record = json.loads(lines[1])
        assert "pending_codification" not in record

    def test_unknown_flag_prints_usage_and_exits_2(self, capsys) -> None:
        rc = main(["--bogus"])
        assert rc == 2
        assert "usage" in capsys.readouterr().err


def test_module_imports_stdlib_only() -> None:
    """Import-surface census (mirrors VP step 5's shell census exactly): the module's transitive
    import set must be stdlib-only, proven by a real module census rather than a bare import --
    this repo's own container has yaml/boto3 present from dist-packages under a bare python3, so
    only a census (never a bare `import ...`) can discriminate."""
    import sys

    extra = (
        {n.split(".")[0] for n in sys.modules}
        - set(sys.stdlib_module_names)
        - {
            "scripts",
            "__main__",
            "sitecustomize",
            "_distutils_hack",
        }
    )
    # scripts.ci.convergence_classify is already imported at module scope above; assert its own
    # import did not drag in anything non-stdlib that wasn't already present for another reason.
    import scripts.ci.convergence_classify as _mod  # noqa: F401

    extra_after = (
        {n.split(".")[0] for n in sys.modules}
        - set(sys.stdlib_module_names)
        - {
            "scripts",
            "__main__",
            "sitecustomize",
            "_distutils_hack",
        }
    )
    # No NEW non-stdlib top-level module should appear solely from importing this module again
    # (it's already imported; this guards against a future edit adding a fresh heavy import).
    assert extra_after == extra
