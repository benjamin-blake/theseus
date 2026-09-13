"""PLAN-vp-red-before-gate: the static step lints (negated-sweep sweep + scripts.validate
recursion refusal) and the shared cross-leg replay budget (docs/contracts/vp-red-before.yaml).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.verification.validate_vp_replay import (
    _extract_negated_rg_grep_path,
    _segment_invokes_scripts_validate,
)

from .conftest import (
    _commit_all,
    _ModifiedPlanFixture,
    _RedBeforeFixture,
    _ResolvedFixture,
    _write_vp_replay_plan,
    validate_vp_replay,
)


def _step(step: int, command: str, *, graduation: str = "not-applicable", **extra) -> dict:
    base = {
        "step": step,
        "phase": "pre-deploy",
        "hermetic": True,
        "action": "fixture step",
        "command": command,
        "expected": "n/a",
        "fix_if": "n/a",
        "graduation": graduation,
    }
    base.update(extra)
    return base


class TestStaticStepLints:
    """The negated-sweep lint (every disposition) and the scripts.validate recursion refusal
    (graduate partition only) -- flag, fail open, defer to the dynamic leg on precedence, and
    bind only eligible plans."""

    def test_negated_sweep_flags_absent_path(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(
            tmp_path, "vpr-lint-absent-path", [_step(1, "! rg SOMEPATTERN missing/does/not/exist.py")]
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-red-before-lint" in f and "absent path" in f for f in failed)

    def test_negated_sweep_fails_open_on_unparseable_command(self, tmp_path: Path) -> None:
        """A multi-word / ambiguous remainder after `! rg`/`! grep` is never flagged."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-lint-fail-open",
            [_step(1, "! rg 'a pattern with spaces' one two three extra tokens")],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert not any("vp-red-before-lint" in f for f in failed)

    def test_precedence_suppresses_lint_when_tautology_also_fires(self, tmp_path: Path) -> None:
        """When a GRADUATE step's negated rg/grep also dynamically classifies as tautological
        (the negation silently turns the missing-path exit 2 into exit 0), the tautology failure
        is reported and the lint finding on that same step is suppressed."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-lint-precedence",
            [_step(1, "! rg SOMEPATTERN missing/does/not/exist.py", graduation="graduate", graduation_check_id="vpr-prec")],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("actual=tautological" in f for f in failed)
        assert not any("vp-red-before-lint" in f for f in failed)

    def test_modified_plan_with_negated_sweep_is_not_linted(self, tmp_path: Path) -> None:
        """The lint binds the SAME eligible-plan population as the dynamic leg -- a MODIFIED
        (not added) plan is not linted even though it carries a negated sweep."""
        repo, rel = _ModifiedPlanFixture().build(
            tmp_path,
            "vpr-lint-scoping-modified",
            [_step(1, "! rg SOMEPATTERN missing/does/not/exist.py")],
            declared=True,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_field_absent_legacy_plan_with_negated_sweep_is_not_linted(self, tmp_path: Path) -> None:
        """Field-absent legacy shape: not added, so not linted, regardless of the missing field."""
        repo, rel = _ModifiedPlanFixture().build(
            tmp_path,
            "vpr-lint-scoping-legacy",
            [_step(1, "! rg SOMEPATTERN missing/does/not/exist.py")],
            omit_declared_field=True,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_recursion_refusal_fires_on_graduate_step(self, tmp_path: Path) -> None:
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-recursion-graduate",
            [_step(1, "bin/venv-python -m scripts.validate --pre", graduation="graduate", graduation_check_id="vpr-recur")],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-red-before-recursion" in f for f in failed)

    def test_recursion_refusal_does_not_fire_on_waive_step(self, tmp_path: Path) -> None:
        """The refusal binds the GRADUATE partition only -- a waive step may name
        scripts.validate freely, since nothing executes it."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-recursion-waive",
            [
                _step(
                    1,
                    "bin/venv-python -m scripts.validate --pre",
                    graduation="waive",
                    graduation_waiver_reason="fixture -- recursion hazard, never graduated",
                )
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_recursion_refusal_does_not_flag_import_shape(self, tmp_path: Path) -> None:
        """A graduate step merely IMPORTING scripts.validate (never invoking -m or the script
        path as argv head) is a false-positive shape the substring-based rule would have caught;
        the argv-head rule must not, and the (module-not-found) import failure is a genuine,
        clean red-before pass (assertion_failed)."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-recursion-import-shape",
            [
                _step(
                    1,
                    'python3 -c "import scripts.validate"',
                    graduation="graduate",
                    graduation_check_id="vpr-import-shape",
                )
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_recursion_refusal_does_not_flag_grep_for_function_name_shape(self, tmp_path: Path) -> None:
        """A graduate step grepping scripts/validate.py for a function name (never executing it)
        must pass -- exit 1 (no match) classifies as assertion_failed, a genuine red-before pass."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-recursion-grep-shape",
            [
                _step(
                    1,
                    "grep -q def_that_does_not_exist_yet scripts/validate.py",
                    graduation="graduate",
                    graduation_check_id="vpr-grep-shape",
                )
            ],
        )
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / "validate.py").write_text("def main(): pass\n", encoding="utf-8")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []


class TestSharedBudget:
    """One shared aggregate counter spans both legs within a dispatch; the re-derived
    MAX_REPLAYED_STEPS does not bind before the wall clock for a realistic multi-plan PR."""

    def test_budget_is_shared_across_both_legs(self, tmp_path: Path) -> None:
        """A cap that fits neither leg alone but fits their SUM only trips when both legs'
        replayed steps are counted together."""
        resolved_repo, resolved_rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-budget-resolved",
            [
                {
                    "step": i,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "x",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
                for i in range(1, 4)
            ],
        )
        # Graft a second, red-before-eligible plan onto the SAME repo/diff so one dispatch
        # exercises both legs together.
        red_before_rel = _write_vp_replay_plan(
            resolved_repo,
            "vpr-budget-redbefore",
            [_step(i, "true", graduation="graduate", graduation_check_id=f"vpr-budget-{i}") for i in range(1, 4)],
            declared=False,
        )
        _commit_all(resolved_repo, "add second plan")

        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_REPLAYED_STEPS", 4):
            validate_vp_replay(failed, changed_files=[resolved_rel, red_before_rel], root=resolved_repo)
        assert any("budget exceeded" in f for f in failed)

    def test_default_budget_covers_two_plans_of_this_size(self, tmp_path: Path) -> None:
        """A PR carrying two red-before-eligible plans of 14 quick graduate steps each (28 total)
        must not hard-fail on the COUNT cap under the production default."""
        repo, rel_a = _RedBeforeFixture().build(
            tmp_path,
            "vpr-budget-two-plans-a",
            [_step(i, "true", graduation="graduate", graduation_check_id=f"vpr-a-{i}") for i in range(1, 15)],
        )
        rel_b = _write_vp_replay_plan(
            repo,
            "vpr-budget-two-plans-b",
            [_step(i, "true", graduation="graduate", graduation_check_id=f"vpr-b-{i}") for i in range(1, 15)],
            declared=False,
        )
        _commit_all(repo, "add second plan")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel_a, rel_b], root=repo)
        assert not any("budget exceeded" in f for f in failed)

    def test_aggregate_seconds_guard_still_binds(self, tmp_path: Path) -> None:
        """The aggregate wall-clock cap remains the true backstop independent of the step count."""
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-budget-aggregate",
            [_step(i, "true", graduation="graduate", graduation_check_id=f"vpr-agg-{i}") for i in range(1, 4)],
        )
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_AGGREGATE_SECONDS", 0):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("budget exceeded" in f for f in failed)


class TestNegatedSweepExtractorUnit:
    """Direct unit coverage of `_extract_negated_rg_grep_path`'s fail-open branches -- an empty
    tail, and a quoted or shell-metacharacter-bearing path token."""

    def test_empty_tail_is_unparseable(self) -> None:
        assert _extract_negated_rg_grep_path("! rg") is None

    def test_quoted_path_token_is_unparseable(self) -> None:
        assert _extract_negated_rg_grep_path("! rg PATTERN 'quoted/path.py'") is None

    def test_metacharacter_path_token_is_unparseable(self) -> None:
        assert _extract_negated_rg_grep_path("! rg PATTERN some*glob.py") is None


class TestScriptsValidateSegmentUnit:
    """Direct unit coverage of `_segment_invokes_scripts_validate`'s argv-head branches an
    end-to-end fixture cannot cheaply isolate: an empty segment, a bare script-path argv head,
    and an interpreter-prefixed script-path argv head."""

    def test_empty_tokens_is_false(self) -> None:
        assert _segment_invokes_scripts_validate([]) is False

    def test_bare_script_path_as_argv_head_is_true(self) -> None:
        assert _segment_invokes_scripts_validate(["scripts/validate.py", "--pre"]) is True

    def test_interpreter_prefixed_script_path_is_true(self) -> None:
        assert _segment_invokes_scripts_validate(["python3", "scripts/validate.py"]) is True
