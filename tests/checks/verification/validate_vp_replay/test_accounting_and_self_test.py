"""PLAN-vp-red-before-gate: the widened Decision 170 accounting declaration and the classifier
self-test/vacuity cross-check (docs/contracts/vp-red-before.yaml).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml as _yaml

from scripts.checks.verification.validate_vp_replay import _classify_outcome

from .conftest import (
    _commit_all,
    _RedBeforeFixture,
    _ResolvedFixture,
    _write_vp_replay_plan,
    registry,
    validate_vp_replay,
)


def _graduate_step(step: int, command: str) -> dict:
    return {
        "step": step,
        "phase": "pre-deploy",
        "hermetic": True,
        "action": "fixture graduate step",
        "command": command,
        "expected": "n/a",
        "fix_if": "n/a",
        "graduation": "graduate",
        "graduation_check_id": f"vpr-accounting-{step}",
    }


class TestAccountingDeclaration:
    """The declaration distinguishes an executing plan from a zero-graduate one, under a unit
    naming the grain actually counted."""

    def test_pure_implement_leg_keeps_declared_plans_unit(self, tmp_path: Path) -> None:
        """No red-before-eligible plan in the diff -- unchanged from the pre-Decision-189 shape."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-acct-declared",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "x",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration.unit == "declared_plans"
        assert declaration.count == 1

    def test_eligible_plan_with_graduate_steps_declares_plans_acted_on(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(tmp_path, "vpr-acct-acted-on", [_graduate_step(1, "exit 1")])
        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration.unit == "plans_acted_on"
        assert declaration.count == 1

    def test_eligible_plan_with_zero_graduate_steps_declares_vacuous(self, tmp_path: Path) -> None:
        """A plan-only PR whose plan carries ZERO graduate steps declares vacuous (count 0),
        never falsely "enforced" -- the widening defect this criterion exists to prevent."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-acct-vacuous",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "not-applicable",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                    "graduation": "not-applicable",
                }
            ],
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration.kind == "examined"
        assert declaration.unit == "plans_acted_on"
        assert declaration.count == 0

    def test_mixed_dispatch_counts_plans_acted_on_in_either_leg(self, tmp_path: Path) -> None:
        """One resolved (implement leg) plus one eligible-with-graduate-steps (red-before leg)
        plan in the SAME dispatch -- the union of both legs' acted-on plans."""
        repo, resolved_rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-acct-mixed-resolved",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "x",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        red_before_rel = _write_vp_replay_plan(repo, "vpr-acct-mixed-redbefore", [_graduate_step(1, "exit 1")], declared=False)
        _commit_all(repo, "add second plan")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[resolved_rel, red_before_rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration.unit == "plans_acted_on"
        assert declaration.count == 2


class TestClassifierSelfTest:
    """A broken classifier reddens the check that depends on it, in the same dispatch -- the
    self-test runs unconditionally, before any precondition early-return, and contributes to
    `failed` only, never to `examined()`."""

    def test_self_test_runs_even_with_no_plan_in_diff(self, tmp_path: Path) -> None:
        broken = lambda command, returncode, combined_output, *, timed_out: "tautological"  # noqa: E731
        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks.verification._vp_replay_classify._classify_outcome", broken):
            validate_vp_replay(failed, changed_files=["scripts/unrelated.py"], root=tmp_path)
        declaration = registry.pop_declaration()
        assert any("self-test" in f for f in failed)
        # The self-test's own failures never count toward examined() -- the empty-domain PASS
        # branch (no plan in the diff at all) still declares its ordinary vacuous "declared_plans".
        assert declaration.kind == "examined"
        assert declaration.unit == "declared_plans"
        assert declaration.count == 0

    def test_mislabeled_classifier_fails_the_self_test(self, tmp_path: Path) -> None:
        broken = lambda command, returncode, combined_output, *, timed_out: "assertion_failed"  # noqa: E731
        failed: list[str] = []
        with patch("scripts.checks.verification._vp_replay_classify._classify_outcome", broken):
            validate_vp_replay(failed, changed_files=[], root=tmp_path)
        assert any("self-test" in f and "'assertion_failed'" in f for f in failed)

    def test_self_test_covers_the_timeout_arm_distinctly(self, tmp_path: Path) -> None:
        """A classifier that mislabels ONLY the timed_out branch (every other arm correct) must
        still be caught -- proving the self-test genuinely exercises the timeout fixture, not
        merely piggy-backing on the exit-127 fixture's coverage."""

        def timeout_blind(command, returncode, combined_output, *, timed_out):
            if timed_out:
                return "assertion_failed"  # wrong -- should be "unmeasurable"
            return _classify_outcome(command, returncode, combined_output, timed_out=timed_out)

        failed: list[str] = []
        with patch("scripts.checks.verification._vp_replay_classify._classify_outcome", timeout_blind):
            validate_vp_replay(failed, changed_files=[], root=tmp_path)
        assert any("self-test" in f and "'sleep 5'" in f for f in failed)

    def test_correct_classifier_passes_the_self_test(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[], root=tmp_path)
        assert not any("self-test" in f for f in failed)


class TestVacuityCrossCheck:
    """An independent count of the plans genuinely acted on equals what the check declared
    examined -- derived without reference to the check's own resolution path (a raw re-parse of
    each fixture plan's own YAML, not any helper this module exports)."""

    def test_independent_graduate_plan_count_matches_declaration(self, tmp_path: Path) -> None:
        repo, rel_with_graduate = _RedBeforeFixture().build(
            tmp_path, "vpr-vacuity-with-graduate", [_graduate_step(1, "exit 1")]
        )
        rel_without_graduate = _write_vp_replay_plan(
            repo,
            "vpr-vacuity-without-graduate",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "not-applicable",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                    "graduation": "not-applicable",
                }
            ],
            declared=False,
        )
        _commit_all(repo, "add second plan")

        # Independent count: raw YAML re-parse, no reference to validate_vp_replay's own helpers.
        independent_count = 0
        for rel in (rel_with_graduate, rel_without_graduate):
            data = _yaml.safe_load((repo / rel).read_text(encoding="utf-8"))
            steps = data.get("verification_plan", [])
            if any(s.get("phase") == "pre-deploy" and s.get("graduation") == "graduate" for s in steps):
                independent_count += 1

        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel_with_graduate, rel_without_graduate], root=repo)
        declaration = registry.pop_declaration()
        assert declaration.count == independent_count
