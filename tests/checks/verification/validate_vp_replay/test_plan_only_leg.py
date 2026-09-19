"""TestPlanOnlyLeg (PLAN-vp-replay-mirror-decomposition concern-split decomposition of the former
flat single-file mirror), relocated verbatim.

Covers the DEFER path via the changed_files/root injection seams -- a diff-present plan whose
implementation_declared did not newly flip true DEFERs.

PLAN-vp-expected-literal-carrier ADDS TestCarrierSelection, TestDeferWorkShape, and
TestExpectedLiteralEmittability below the relocated classes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml as _yaml

from .conftest import (
    _build_undeclared_repo,
    _commit_all,
    _git,
    _init_repo,
    _ModifiedPlanFixture,
    _RedBeforeFixture,
    _ResolvedFixture,
    _write_vp_replay_plan,
    validate_vp_replay,
)


class TestPlanOnlyLeg:
    """A diff-present plan whose implementation_declared did not newly flip true DEFERs."""

    def test_no_plan_in_diff_is_noop_pass(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=tmp_path)
        assert failed == []

    def test_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        """A plan path present in changed_files but absent on disk (deleted in the diff) is a
        no-op, even though origin/main is unreachable here too (no git repo at tmp_path)."""
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_undeclared_plan_defers_no_execution(self, tmp_path: Path, capsys) -> None:
        """A plan-only PR (plan in diff, implementation_declared false) defers -- the hermetic
        step's command ('exit 1') is never executed, so it never reddens failed[]."""
        repo, rel = _build_undeclared_repo(tmp_path)

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" in out
        assert "not newly true" in out

    def test_deleted_plan_path_is_skipped_with_reachable_base(self, tmp_path: Path, capsys) -> None:
        """A plan path in the diff but absent on disk (deleted in the diff) is a no-op even when
        origin/main IS reachable -- distinct from the unreachable-base DEFER-everything path."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_vp_replay_plan(repo, "vpr-real-then-gone", [], declared=True)
        _commit_all(repo, "add then delete")
        (repo / rel).unlink()
        _commit_all(repo, "delete plan")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"SKIP: {rel} (not present on disk -- deleted in this diff)" in out

    def test_resolved_plan_hands_off_to_implement_leg(self, tmp_path: Path, capsys) -> None:
        """A resolved plan (implementation_declared newly true) is NOT deferred -- it is printed
        as handed off and actually replayed against the complete tree."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-resolved",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a passing command.",
                    "command": "echo resolved-ran",
                    "expected": "stdout contains `resolved-ran`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" not in out
        assert f"PASS: {rel}:1 replayed" in out


def _write_versioned_resolved_plan(repo: Path, slug: str, verification_plan: list[dict], *, schema_version: int) -> str:
    """A resolved (implementation_declared=true) plan at an arbitrary schema_version -- conftest's
    own _write_vp_replay_plan/_ResolvedFixture hardcode schema_version 2, so carrier-selection
    tests need their own writer rather than a modification to that shared fixture."""
    plan: dict = {
        "schema_version": schema_version,
        "slug": slug,
        "intent": "Fixture plan for carrier-selection tests.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture",
        "scope": [{"file": "scripts/dummy.py", "action": "Modify", "purpose": "test fixture"}],
        "acceptance_criteria": ["dummy criterion"],
        "verification_plan": verification_plan,
        "execution_steps": ["dummy step"],
        "implementation_declared": True,
    }
    if schema_version in (3, 4, 5):
        plan["handoff_policy"] = {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"}
    plans_dir = repo / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(_yaml.dump(plan), encoding="utf-8")
    return rel


def _build_resolved_repo(tmp_path: Path, slug: str, verification_plan: list[dict], *, schema_version: int) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base_sha = _commit_all(repo, "base")
    _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
    rel = _write_versioned_resolved_plan(repo, slug, verification_plan, schema_version=schema_version)
    _commit_all(repo, "checkpoint")
    return repo, rel


class TestCarrierSelection:
    """The implement leg's carrier is SELECTED by the plan's own schema_version: the byte-identical
    backtick-in-``expected`` scan at v4-and-below, ``expected_literals`` at v5."""

    def test_v4_plan_checks_backtick_literal_in_expected(self, tmp_path: Path) -> None:
        repo, rel = _build_resolved_repo(
            tmp_path,
            "vpr-carrier-v4",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo ok",
                    "expected": "stdout contains `MISSING`.",
                    "fix_if": "n/a",
                }
            ],
            schema_version=4,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("missing literal(s)" in f and "MISSING" in f for f in failed)

    def test_v4_plan_passes_when_backtick_literal_present(self, tmp_path: Path) -> None:
        repo, rel = _build_resolved_repo(
            tmp_path,
            "vpr-carrier-v4-pass",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo ok",
                    "expected": "stdout contains `ok`.",
                    "fix_if": "n/a",
                }
            ],
            schema_version=4,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_v5_plan_checks_expected_literals_not_expected_prose(self, tmp_path: Path) -> None:
        """The plan's `expected` prose carries no backtick (v5 hermetic steps refuse one at
        schema-validation time) -- only `expected_literals` is checked, proving the v4 backtick
        scan is NOT also applied at v5."""
        repo, rel = _build_resolved_repo(
            tmp_path,
            "vpr-carrier-v5",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo ok",
                    "expected": "stdout contains the token.",
                    "expected_literals": ["MISSING"],
                    "fix_if": "n/a",
                }
            ],
            schema_version=5,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("missing literal(s)" in f and "MISSING" in f for f in failed)

    def test_v5_plan_passes_when_expected_literals_present(self, tmp_path: Path) -> None:
        repo, rel = _build_resolved_repo(
            tmp_path,
            "vpr-carrier-v5-pass",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo ok",
                    "expected": "stdout contains the token.",
                    "expected_literals": ["ok"],
                    "fix_if": "n/a",
                }
            ],
            schema_version=5,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []


class TestDeferWorkShape:
    """The per-step literal print is sited AFTER the eligibility filter -- never at the
    unconditional DEFER line, which would force a plan load for every deferred plan."""

    def test_ineligible_deferred_plan_never_loads_the_plan_document(self, tmp_path: Path, capsys) -> None:
        repo, rel = _ModifiedPlanFixture().build(
            tmp_path,
            "vpr-ineligible-defer",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo ok",
                    "expected": "n/a",
                    "fix_if": "n/a",
                    "graduation": "graduate",
                    "graduation_check_id": "vpr-ineligible-1",
                }
            ],
            declared=False,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.load_plan") as mock_load:
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert f"DEFER: {rel}" in out
        assert "LITERALS:" not in out
        mock_load.assert_not_called()
        assert failed == []

    def test_eligible_plan_prints_literals_after_eligibility_filter(self, tmp_path: Path, capsys) -> None:
        repo, rel = _RedBeforeFixture().build(
            tmp_path,
            "vpr-eligible-literals",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo ok",
                    "expected": "stdout contains `ok`.",
                    "fix_if": "n/a",
                    "graduation": "graduate",
                    "graduation_check_id": "vpr-eligible-1",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert f"DEFER: {rel}" in out
        assert f"LITERALS: {rel}:1 expected_literals=['ok']" in out


class TestExpectedLiteralEmittability:
    """rec-3900's filed acceptance probe pins this exact identifier -- the dynamic replay leg's
    own mirror of the emittability truth table vp_literals owns directly."""

    def test_resolved_v5_plan_with_unemittable_literal_fails_replay(self, tmp_path: Path) -> None:
        """expected_literals is proven emittable at authoring time (plan_document); this proves
        the implement leg's own carrier selection stays consistent with that guard's intent by
        still catching a literal the command never prints."""
        repo, rel = _build_resolved_repo(
            tmp_path,
            "vpr-emittability",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "fixture",
                    "command": "echo something-else",
                    "expected": "prints the token.",
                    "expected_literals": ["ok"],
                    "fix_if": "n/a",
                }
            ],
            schema_version=5,
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("missing literal(s)" in f and "ok" in f for f in failed)
