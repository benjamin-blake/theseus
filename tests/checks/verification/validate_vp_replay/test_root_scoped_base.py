"""TestRootScopedBase (PLAN-vp-replay-mirror-decomposition concern-split decomposition of the
former tests/checks/verification/test_validate_vp_replay.py monolith), relocated verbatim.

rec-3166 class: content-keyed plan resolution must read its base from the INJECTED `root`'s
repository, never from `_common.ROOT` (patched to an unrelated DECOY repo in every test here). A
plan already declared at the true base (steady state) must NOT spuriously re-resolve just because
push context derived its base from the wrong repo. Its own module for the same shard-pinning
reason as TestContentKeyedResolution -- root-scoped-diff-base-vp-replay-root-scoping pins this
class as a node_id.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from .conftest import (
    _commit_all,
    _git,
    _init_repo,
    _write_vp_replay_plan,
    registry,
    validate_vp_replay,
)


class TestRootScopedBase:
    """rec-3166 class: content-keyed plan resolution must read its base from the INJECTED
    `root`'s repository, never from `_common.ROOT` (patched to an unrelated DECOY repo in
    every test here). A plan already declared at the true base (steady state) must NOT
    spuriously re-resolve just because push context derived its base from the wrong repo."""

    def _build_steady_repo(self, tmp_path: Path, slug: str) -> tuple[Path, str, str]:
        """A repo whose plan is ALREADY declared at `before_sha` (steady state, no flip), then
        merged to main (`origin/main` pinned to HEAD, simulating post-merge main)."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        rel = _write_vp_replay_plan(repo, slug, [], declared=True)
        before_sha = _commit_all(repo, "base, already declared")
        (repo / "unrelated.txt").write_text("x\n", encoding="utf-8")
        after_sha = _commit_all(repo, "unrelated follow-up commit")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])
        return repo, rel, before_sha

    def test_push_event_trigger_does_not_spuriously_reresolve(self, tmp_path: Path, monkeypatch) -> None:
        decoy = tmp_path / "decoy"
        _init_repo(decoy)
        (decoy / "d.txt").write_text("decoy\n", encoding="utf-8")
        _commit_all(decoy, "decoy first")
        (decoy / "d2.txt").write_text("decoy2\n", encoding="utf-8")
        _commit_all(decoy, "decoy second")

        repo, rel, before_sha = self._build_steady_repo(tmp_path, "vpr-root-scoped-push")

        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.setenv("GITHUB_EVENT_BEFORE", before_sha)

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", decoy):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0, "already-declared-at-base plan must not spuriously re-resolve"
        assert failed == []

    def test_on_main_trigger_does_not_spuriously_reresolve(self, tmp_path: Path) -> None:
        # The decoy must ALSO trigger push_context_base()'s on-main branch (own branch=="main"
        # AND merge-base(origin/main, HEAD)==HEAD) so the pre-fix bare call returns a WRONG but
        # non-None sha (absent from `repo`) instead of harmlessly falling through to None --
        # otherwise this test would pass even pre-fix, proving nothing.
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        _git(decoy, ["init", "-q", "-b", "main"])
        _git(decoy, ["config", "user.email", "test@example.com"])
        _git(decoy, ["config", "user.name", "Test"])
        (decoy / "d.txt").write_text("decoy\n", encoding="utf-8")
        _commit_all(decoy, "decoy first")
        (decoy / "d2.txt").write_text("decoy2\n", encoding="utf-8")
        decoy_head = _commit_all(decoy, "decoy second")
        _git(decoy, ["update-ref", "refs/remotes/origin/main", decoy_head])

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, ["init", "-q", "-b", "main"])
        _git(repo, ["config", "user.email", "test@example.com"])
        _git(repo, ["config", "user.name", "Test"])
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        rel = _write_vp_replay_plan(repo, "vpr-root-scoped-onmain", [], declared=True)
        _commit_all(repo, "base, already declared")
        (repo / "unrelated.txt").write_text("x\n", encoding="utf-8")
        after_sha = _commit_all(repo, "unrelated follow-up commit")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])  # merge-base(origin/main, HEAD) == HEAD

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", decoy):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0, "already-declared-at-base plan must not spuriously re-resolve"
        assert failed == []
