"""TestContentKeyedResolution (PLAN-vp-replay-mirror-decomposition concern-split decomposition of
the former flat single-file mirror), relocated verbatim.

The defect this re-key closes: a branch whose only content commit is an automated checkpoint (no
feat({slug}) commit subject) still resolves and replays, because resolution is keyed off
implementation_declared, not commit-message shape. Also covers the single terminal Decision 170
declaration composed once per dispatch. Its own module because a live registry shard
(vp-replay-content-keyed-can-still-fail) pins this class as a node_id.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import (
    _commit_all,
    _git,
    _init_repo,
    _ResolvedFixture,
    _write_vp_replay_plan,
    registry,
    validate_vp_replay,
)


class TestContentKeyedResolution:
    """The defect this re-key closes: a branch whose only content commit is an automated
    checkpoint (no feat({slug}) commit subject) still resolves and replays, because resolution
    is keyed off implementation_declared, not commit-message shape. Also covers the single
    terminal Decision 170 declaration composed once per dispatch."""

    def test_checkpoint_only_commit_message_branch_still_resolves(self, tmp_path: Path) -> None:
        """Red before this plan: a checkpoint-only branch with a declaration resolved nothing
        and no-opped (commit-subject resolution found no feat({slug}) subject). Green after:
        the hermetic step is genuinely replayed and reddens on a real failure."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-checkpoint-only",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that fails.",
                    "command": "exit 1",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
            commit_message="chore: automated checkpoint",
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_declaration_enforced_when_a_plan_resolves(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-declared-enforced",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "pass",
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
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "declared_plans"

    def test_declaration_vacuous_when_plan_present_but_undeclared(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_vp_replay_plan(repo, "vpr-declared-vacuous", [], declared=False)
        _commit_all(repo, "add undeclared plan")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_vacuous_when_no_plan_in_diff(self) -> None:
        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=Path("/nonexistent"))
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_skipped_when_base_unreachable(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(tmp_path, "vpr-declared-skipped", [], declared=False)

        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []
