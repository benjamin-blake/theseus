"""TestPlanOnlyLeg, TestSkippedBase, TestPlanPathsOverride, TestAccounting (Decision 131
concern-split decomposition of the former flat test_validate_scope_boundary.py monolith that used
to live one directory up), moved verbatim.

TestPlanOnlyLeg / TestSkippedBase cover the DEFER and skipped legs (mirrors
test_validate_vp_replay.py's own split). TestPlanPathsOverride covers the dispatch seam VP steps
6/11 use to enforce before anything is committed. TestAccounting covers the Decision 170 terminal
declaration.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import (
    _commit_all,
    _git,
    _init_repo,
    _ResolvedFixture,
    _write_contract,
    _write_plan,
    registry,
    validate_scope_boundary,
)


class TestPlanOnlyLeg:
    def test_no_plan_in_diff_is_vacuous_pass(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=["scripts/foo.py"], root=tmp_path)
        assert failed == []

    def test_undeclared_plan_defers_no_enforcement(self, tmp_path: Path, capsys) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(
            repo, "sb-plan-only", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False
        )
        _commit_all(repo, "add undeclared plan")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/rogue.py"], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" in out


class TestSkippedBase:
    def test_declaration_skipped_when_base_unreachable(self, tmp_path: Path) -> None:
        rel = _write_plan(
            tmp_path, "sb-no-base", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_scope_boundary(failed, changed_files=[rel], root=tmp_path)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []


class TestPlanPathsOverride:
    """VP steps 6/11's own dispatch shape: an explicit plan_paths override IS the resolved set
    directly, bypassing implementation_declared flip-detection entirely -- required because the
    Verification Plan runs before the commit flow sets that field."""

    def test_override_enforces_even_when_not_yet_declared(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        rel = _write_plan(
            repo, "sb-override", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False
        )
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        failed: list[str] = []
        validate_scope_boundary(failed, plan_paths=[rel], changed_files=[rel, "scripts/foo.py", "scripts/rogue.py"], root=repo)
        assert any("scripts/rogue.py" in f for f in failed)

    def test_override_passes_when_fully_declared(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        rel = _write_plan(
            repo, "sb-override-ok", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False
        )
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        failed: list[str] = []
        validate_scope_boundary(failed, plan_paths=[rel], changed_files=[rel, "scripts/foo.py"], root=repo)
        assert failed == []


class TestAccounting:
    def test_examined_count_matches_resolved_plans(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-acct", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "declared_plans"

    def test_examined_zero_when_no_plan_in_diff(self) -> None:
        failed: list[str] = []
        registry.pop_declaration()
        validate_scope_boundary(failed, changed_files=["scripts/foo.py"], root=Path("/nonexistent"))
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_default_changed_files_uses_status_aware_diff(self, tmp_path: Path) -> None:
        """No changed_files arg -- falls back to _common.get_status_aware_diff(). An empty diff
        means no plan paths at all, so the check no-ops without touching real git state."""
        from unittest.mock import patch

        failed: list[str] = []
        with patch("scripts.checks._common.get_status_aware_diff", return_value=[]):
            validate_scope_boundary(failed)
        assert failed == []
