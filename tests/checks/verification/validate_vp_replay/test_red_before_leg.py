"""PLAN-vp-red-before-gate: the inverted-polarity plan-only leg's dynamic replay (docs/contracts/
vp-red-before.yaml). Tautology, the two red classes, every unmeasurable arm including timeout,
non-graduate non-execution, and the eligibility predicate's two exempt shapes.
"""

from __future__ import annotations

import subprocess as _subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.checks.verification.validate_vp_replay import _is_red_before_eligible

from .conftest import (
    _ModifiedPlanFixture,
    _RedBeforeFixture,
    validate_vp_replay,
)


def _graduate_step(step: int, command: str, *, hermetic: bool = True) -> dict:
    return {
        "step": step,
        "phase": "pre-deploy",
        "hermetic": hermetic,
        "action": "fixture graduate step",
        "command": command,
        "expected": "n/a",
        "fix_if": "n/a",
        "graduation": "graduate",
        "graduation_check_id": f"vpr-fixture-{step}",
    }


class TestRedBeforeLeg:
    def test_graduate_step_exiting_zero_reddens(self, tmp_path: Path) -> None:
        """A graduate step green-by-construction on the un-implemented tree is a hard failure."""
        repo, rel = _RedBeforeFixture().build(tmp_path, "vpr-tautological", [_graduate_step(1, "true")])
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=tautological" in f for f in failed)

    def test_absent_and_assertion_classes_are_distinct_and_pass(self, tmp_path: Path) -> None:
        """target_absent (pytest collection-error exit 4/5) and assertion_failed (any other
        non-zero exit) are distinct classes and NEITHER fails the check."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-classes-distinct",
            [_graduate_step(1, "exit 5"), _graduate_step(2, "exit 1")],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_non_graduate_dispositions_not_executed(self, tmp_path: Path) -> None:
        """waive and not-applicable steps are never dynamically replayed -- assert no subprocess
        is spawned for either, not merely that the check exits 0."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-non-graduate",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "waive",
                    "command": "echo SHOULD-NOT-RUN-WAIVE",
                    "expected": "n/a",
                    "fix_if": "n/a",
                    "graduation": "waive",
                    "graduation_waiver_reason": "fixture -- deliberately not graduated",
                },
                {
                    "step": 2,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "not-applicable",
                    "command": "echo SHOULD-NOT-RUN-NOTAPPLICABLE",
                    "expected": "n/a",
                    "fix_if": "n/a",
                    "graduation": "not-applicable",
                },
            ],
        )
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.subprocess.run", wraps=_subprocess.run) as mock_run:
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        executed = [call.args[0] for call in mock_run.call_args_list if call.args]
        assert "echo SHOULD-NOT-RUN-WAIVE" not in executed
        assert "echo SHOULD-NOT-RUN-NOTAPPLICABLE" not in executed
        assert failed == []


class TestUnmeasurable:
    """Every unmeasurable arm hard-fails instead of reading as red -- one test per arm so a
    single regressed arm is attributable."""

    def test_exit_126_not_executable(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(tmp_path, "vpr-unm-126", [_graduate_step(1, "exit 126")])
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=unmeasurable" in f for f in failed)

    def test_exit_127_command_not_found(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(tmp_path, "vpr-unm-127", [_graduate_step(1, "exit 127")])
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=unmeasurable" in f for f in failed)

    def test_rg_grep_error_exit_2(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(
            tmp_path, "vpr-unm-rg", [_graduate_step(1, "rg SOMEPATTERN missing/nonexistent/path.py")]
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=unmeasurable" in f for f in failed)

    def test_credential_absence(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-unm-cred",
            [_graduate_step(1, 'echo "Unable to locate credentials" 1>&2; exit 1')],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=unmeasurable" in f for f in failed)

    def test_subprocess_timeout(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(tmp_path, "vpr-unm-timeout", [_graduate_step(1, "sleep 5")])
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.PER_STEP_TIMEOUT_SECONDS", 0.1):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=unmeasurable" in f and "TIMEOUT" in f for f in failed)


class TestEligibility:
    """A MODIFIED plan is not refused, whether or not it carries implementation_declared -- the
    eligibility predicate's two exempt shapes, one test each."""

    def test_modified_plan_already_declared_true_is_exempt(self, tmp_path: Path) -> None:
        """Steady-state: implementation_declared already true before this diff, and this diff
        only modifies the plan -- resolve_declared_plans is edge-triggered (not "resolved"), and
        the red-before leg is exempt too (not added)."""
        repo, rel = _ModifiedPlanFixture().build(
            tmp_path, "vpr-eligible-declared-true", [_graduate_step(1, "true")], declared=True
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_modified_plan_field_absent_legacy_is_exempt(self, tmp_path: Path) -> None:
        """The larger shape: implementation_declared entirely absent (335 of 422 real plans
        predate the field) reads falsy forever, but a MODIFIED (not added) plan is exempt
        regardless -- keying on the field alone would hard-fail any PR editing one of them."""
        repo, rel = _ModifiedPlanFixture().build(
            tmp_path,
            "vpr-eligible-field-absent",
            [_graduate_step(1, "true")],
            omit_declared_field=True,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_import_error_on_eligible_plan_reddens_distinctly(self, tmp_path: Path) -> None:
        """Mirrors the implement leg's own ImportError/content-error split (Decision 55
        fail-loud): a broken scripts.roadmap.plan_document import reddens the red-before leg
        directly, never downgraded to a silent SKIP."""
        repo, rel = _RedBeforeFixture().build(tmp_path, "vpr-importerror", [_graduate_step(1, "true")])
        failed: list[str] = []
        with patch("scripts.roadmap.plan_document.load", side_effect=ImportError("broken plan_document")):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-red-before" in f and "could not import" in f for f in failed)


class TestEligibilityPredicateUnit:
    """Direct unit coverage of `_is_red_before_eligible`'s two never-reached-via-full-dispatch
    edge branches: an added-but-deleted plan, and unparseable YAML at a genuinely added path."""

    def test_added_but_missing_from_disk_is_not_eligible(self, tmp_path: Path) -> None:
        assert _is_red_before_eligible("docs/plans/PLAN-gone.yaml", tmp_path, {"docs/plans/PLAN-gone.yaml"}) is False

    def test_added_but_unparseable_yaml_is_not_eligible(self, tmp_path: Path) -> None:
        rel = "docs/plans/PLAN-bad.yaml"
        plan_path = tmp_path / rel
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text("not: valid: yaml: [", encoding="utf-8")
        assert _is_red_before_eligible(rel, tmp_path, {rel}) is False
