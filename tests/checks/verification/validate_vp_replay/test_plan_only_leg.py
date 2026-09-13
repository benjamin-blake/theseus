"""TestPlanOnlyLeg (PLAN-vp-replay-mirror-decomposition concern-split decomposition of the former
tests/checks/verification/test_validate_vp_replay.py monolith), relocated verbatim.

Covers the DEFER path via the changed_files/root injection seams -- a diff-present plan whose
implementation_declared did not newly flip true DEFERs.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import (
    _build_undeclared_repo,
    _commit_all,
    _git,
    _init_repo,
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
