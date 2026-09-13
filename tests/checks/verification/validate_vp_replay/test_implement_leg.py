"""TestImplementLeg (PLAN-vp-replay-mirror-decomposition concern-split decomposition of the
former tests/checks/verification/test_validate_vp_replay.py monolith), relocated verbatim.

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
                    "action": "Run a command that hangs past the per-step timeout.",
                    "command": "sleep 5",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.PER_STEP_TIMEOUT_SECONDS", 0.1):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("TIMEOUT" in f for f in failed)

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

    def test_default_changed_files_falls_back_to_common_get_changed_files(self) -> None:
        """No changed_files arg -- falls back to _common.get_changed_files(). An empty diff means
        no plan paths at all, so the check no-ops without ever touching git state."""
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            validate_vp_replay(failed)
        assert failed == []
