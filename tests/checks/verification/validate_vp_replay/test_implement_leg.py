"""TestImplementLeg (PLAN-vp-replay-mirror-decomposition concern-split decomposition of the
former flat single-file mirror), relocated verbatim.

Exercises the replay path against a real git fixture whose plan resolves via
`implementation_declared`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml as _yaml

from .conftest import (
    _commit_all,
    _git,
    _init_repo,
    _ResolvedFixture,
    _write_vp_replay_plan,
    validate_vp_replay,
)


class TestImplementLeg:
    def test_hermetic_step_failing_command_reddens(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-fail",
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
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_hermetic_step_missing_literal_reddens(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-literal",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command whose output lacks the expected literal.",
                    "command": "echo something-else",
                    "expected": "stdout contains `expected-literal`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("expected-literal" in f for f in failed)

    def test_hermetic_step_passing_command_is_clean(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-pass",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a passing command.",
                    "command": "echo expected-literal",
                    "expected": "stdout contains `expected-literal`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_non_hermetic_and_post_deploy_steps_are_excluded_but_listed(self, tmp_path: Path, capsys) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-excluded",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": False,
                    "action": "Non-hermetic pre-deploy step.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
                {
                    "step": 2,
                    "phase": "post-deploy",
                    "hermetic": True,
                    "action": "Hermetic but post-deploy step.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
                {
                    "step": 3,
                    "phase": "post-deploy",
                    "hermetic": False,
                    "action": "Non-hermetic post-deploy step -- phase disqualifies it regardless of hermetic marker.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"EXCLUDED: {rel}:1 (not-hermetic)" in out
        assert f"EXCLUDED: {rel}:2 (post-deploy)" in out
        assert f"EXCLUDED: {rel}:3 (post-deploy)" in out

    def test_timeout_path_reddens(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-timeout",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that hangs past the aggregate deadline.",
                    "command": "sleep 5",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_AGGREGATE_SECONDS", 0.1):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("TIMEOUT" in f for f in failed)
        assert any("aggregate deadline" in f for f in failed)

    def test_load_error_path_is_skipped_with_note(self, tmp_path: Path, capsys) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        plans_dir = repo / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        rel = "docs/plans/PLAN-vpr-bad.yaml"
        # Valid YAML (so the resolver's raw read succeeds and resolves it -- implementation_declared
        # is true), but not a valid PlanDocument (missing required fields) -- load_plan's schema
        # validation is what must skip this, not the resolver.
        (plans_dir / "PLAN-vpr-bad.yaml").write_text(
            _yaml.dump({"implementation_declared": True, "slug": "vpr-bad"}), encoding="utf-8"
        )
        _commit_all(repo, "checkpoint")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert "SKIP" in out and "load error" in out

    def test_import_error_reddens_distinctly_from_content_error(self, tmp_path: Path) -> None:
        """A broken scripts.roadmap.plan_document import is an infra failure -- it must redden failed[],
        not be downgraded to a silent SKIP alongside routine content-validation errors."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-importerror",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Irrelevant -- load fails before any step runs.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.roadmap.plan_document.load", side_effect=ImportError("broken plan_document")):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-replay" in f and "could not import" in f for f in failed)

    def test_aggregate_step_count_budget_guard(self, tmp_path: Path) -> None:
        steps = [
            {
                "step": i,
                "phase": "pre-deploy",
                "hermetic": True,
                "action": "quick pass",
                "command": "true",
                "expected": "n/a",
                "fix_if": "n/a",
            }
            for i in range(1, 5)
        ]
        repo, rel = _ResolvedFixture().build(tmp_path, "vpr-budget", steps)
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_REPLAYED_STEPS", 2):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("budget exceeded" in f for f in failed)

    def test_pr_relative_excluded_when_base_collapsed(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """PLAN-vp-red-before-gate.yaml step 16's own shape (rec-3845): post-merge, origin/main and
        HEAD collapse onto the same commit while push_context_base() still resolves a distinct
        base (HEAD~1) for implementation_declared edge-triggering -- the PR-relative step's
        origin/main comparison has become vacuous and must be EXCLUDED, never silently replayed.
        The command fails if actually executed, so a wrongly-replayed step reddens the check."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")

        command = "git show origin/main:README.md > /dev/null; exit 1"
        rel = _write_vp_replay_plan(
            repo,
            "vpr-collapse",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "PR-relative step, fails if replayed.",
                    "command": command,
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
            declared=False,
        )
        pre_declare_sha = _commit_all(repo, "add plan")

        plan_path = repo / rel
        plan_dict = _yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        plan_dict["implementation_declared"] = True
        plan_path.write_text(_yaml.dump(plan_dict), encoding="utf-8")
        head_sha = _commit_all(repo, "declare implementation")
        _git(repo, ["update-ref", "refs/remotes/origin/main", head_sha])

        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.delenv("GITHUB_EVENT_BEFORE", raising=False)
        assert _git(repo, ["rev-parse", "HEAD~1"]).stdout.strip() == pre_declare_sha

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"EXCLUDED: {rel}:1 (pr-relative-base-collapsed)" in out

    def test_pr_relative_still_replayed_when_base_distinct(self, tmp_path: Path, capsys) -> None:
        """The same PR-relative shape still replays at PR time, when origin/main and HEAD differ --
        no PR-time verification is lost (the ResolvedFixture shape: HEAD is descendant of, never
        an ancestor of, origin/main)."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-distinct",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "PR-relative step, replayed against a distinct base.",
                    "command": "git diff origin/main -- README.md > /dev/null; echo REPLAYED",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"PASS: {rel}:1 replayed" in out
        assert "EXCLUDED" not in out

    def test_default_changed_files_falls_back_to_common_get_changed_files(self) -> None:
        """No changed_files arg -- falls back to _common.get_changed_files(). An empty diff means
        no plan paths at all, so the check no-ops without ever touching git state."""
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            validate_vp_replay(failed)
        assert failed == []
