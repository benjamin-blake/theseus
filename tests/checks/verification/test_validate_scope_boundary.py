"""Tests for validate_scope_boundary() -- implement-scope diff-vs-plan boundary check (Decision
59's deterministic scope guard). Mirror of
scripts/checks/verification/validate_scope_boundary.py.

TestPlanOnlyLeg / TestSkippedBase cover the DEFER and skipped legs (mirrors
test_validate_vp_replay.py's own split). TestEnforcingLeg covers the diff-vs-scope matrix: an
unsanctioned path fails, a prohibited plan-field edit fails, a fully-declared diff passes, each
sanction_rows trigger kind derives its path correctly, and an unimplemented trigger kind fails
loud. TestPlanPathsOverride covers the dispatch seam VP steps 6/11 use to enforce before anything
is committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml as _yaml

from scripts.checks import registry
from scripts.checks.verification.validate_scope_boundary import validate_scope_boundary

_DEFAULT_SANCTION_ROWS = {
    "graduated_registry_shard": {
        "trigger": {"kind": "graduation_check_id_per_step"},
        "sanctions": {"path_template": "config/agent/verification_registry/entries/{graduation_check_id}.yaml"},
        "prohibited_field_edits": [],
    },
    "implementing_plan_bookkeeping": {
        "trigger": {"kind": "resolved_plan_path"},
        "sanctions": {},
        "permitted_field_edits": ["implementation_declared"],
        "prohibited_field_edits": [
            "acceptance_criteria",
            "scope",
            "verification_plan[].command",
            "verification_plan[].expected",
        ],
        "disposition_on_violation": "STOP: an undeclared touched path is never resolved by editing the plan's own scope.",
    },
    "decisions_index_regeneration": {
        "trigger": {"kind": "scope_contains_file", "file": "docs/DECISIONS.md"},
        "sanctions": {"path_template": "docs/decisions-index.json"},
        "prohibited_field_edits": [],
    },
}


_DUMMY_VP_STEP = {
    "step": 1,
    "phase": "pre-deploy",
    "hermetic": True,
    "action": "dummy",
    "command": "true",
    "expected": "n/a",
    "fix_if": "n/a",
}


def _plan_dict(slug: str, scope: list[dict], verification_plan: list[dict] | None = None, declared: bool = False) -> dict:
    return {
        "schema_version": 2,
        "slug": slug,
        "intent": "Fixture plan for validate_scope_boundary unit tests.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture",
        "scope": scope,
        "acceptance_criteria": ["dummy criterion"],
        "verification_plan": verification_plan or [_DUMMY_VP_STEP],
        "execution_steps": ["dummy step"],
        "implementation_declared": declared,
    }


def _write_plan(
    root: Path, slug: str, scope: list[dict], verification_plan: list[dict] | None = None, declared: bool = False
) -> str:
    plans_dir = root / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(
        _yaml.dump(_plan_dict(slug, scope, verification_plan, declared)), encoding="utf-8"
    )
    return rel


def _write_contract(root: Path, sanction_rows: dict | None = None) -> None:
    contracts_dir = root / "docs" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "contract": {"id": "implement-scope-boundary", "class": "D", "subject": "implement-scope-boundary"},
        "sanction_rows": _DEFAULT_SANCTION_ROWS if sanction_rows is None else sanction_rows,
    }
    (contracts_dir / "implement-scope-boundary.yaml").write_text(_yaml.dump(body), encoding="utf-8")


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", message])
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


class _ResolvedFixture:
    """Shared repo builder: a base commit (origin/main, carrying the contract), then a second
    commit declaring the plan's implementation_declared true -- the resolvable, enforceable
    shape."""

    def build(
        self,
        tmp_path: Path,
        slug: str,
        scope: list[dict],
        verification_plan: list[dict] | None = None,
        sanction_rows: dict | None = None,
    ) -> tuple[Path, str]:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo, sanction_rows)
        _write_plan(repo, slug, scope, verification_plan, declared=False)
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = _write_plan(repo, slug, scope, verification_plan, declared=True)
        _commit_all(repo, "declare implementation")
        return repo, rel


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


class TestEnforcingLeg:
    def test_unsanctioned_path_fails(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-unsanctioned", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py", "scripts/rogue.py"], root=repo)
        assert any("scripts/rogue.py" in f and "STOP" in f for f in failed)

    def test_deleted_path_outside_scope_still_flagged(self, tmp_path: Path) -> None:
        """A 'D' row from get_status_aware_diff surfaces as a plain path here (status dropped) --
        an out-of-scope deletion must still fail, not be silently invisible."""
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-deleted", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py", "scripts/removed.py"], root=repo)
        assert any("scripts/removed.py" in f for f in failed)

    def test_fully_declared_diff_passes(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-declared", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert failed == []

    def test_prohibited_plan_field_edit_fails(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        _write_plan(repo, "sb-field-edit", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False)
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = "docs/plans/PLAN-sb-field-edit.yaml"
        plan = _plan_dict("sb-field-edit", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=True)
        plan["acceptance_criteria"] = ["a DIFFERENT criterion than base"]
        (repo / rel).write_text(_yaml.dump(plan), encoding="utf-8")
        _commit_all(repo, "declare + weaken acceptance_criteria")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert any("prohibited plan-field edit" in f and "acceptance_criteria" in f for f in failed)

    def test_prohibited_vp_step_command_edit_fails(self, tmp_path: Path) -> None:
        """VP-step substitution: a resolved plan's own verification_plan[].command changing from
        base is the CONTENT invariant's other mechanical enforcement arm."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        step = dict(_DUMMY_VP_STEP)
        step["command"] = "echo original"
        _write_plan(
            repo, "sb-step-edit", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], [step], declared=False
        )
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = "docs/plans/PLAN-sb-step-edit.yaml"
        weakened_step = dict(step)
        weakened_step["command"] = "echo weakened"
        plan = _plan_dict(
            "sb-step-edit", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], [weakened_step], declared=True
        )
        (repo / rel).write_text(_yaml.dump(plan), encoding="utf-8")
        _commit_all(repo, "declare + weaken VP step command")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert any("prohibited plan-field edit" in f and "step 1 field 'command'" in f for f in failed)

    def test_prohibited_vp_step_deletion_fails(self, tmp_path: Path) -> None:
        """A declared VP step deleted outright (rather than its command edited) is a strictly
        more effective weakening than substitution and must be caught the same way -- a step
        present at base but absent from the working tree's verification_plan."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        step1 = dict(_DUMMY_VP_STEP)
        step2 = dict(_DUMMY_VP_STEP)
        step2["step"] = 2
        step2["command"] = "echo second"
        _write_plan(
            repo,
            "sb-step-delete",
            [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}],
            [step1, step2],
            declared=False,
        )
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = "docs/plans/PLAN-sb-step-delete.yaml"
        plan = _plan_dict(
            "sb-step-delete", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], [step1], declared=True
        )
        (repo / rel).write_text(_yaml.dump(plan), encoding="utf-8")
        _commit_all(repo, "declare + delete VP step 2 entirely")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert any("prohibited plan-field edit" in f and "step 2" in f and "deleted" in f for f in failed)

    def test_permitted_field_edit_does_not_fail(self, tmp_path: Path) -> None:
        """implementation_declared flipping true is the whole point of the resolved-plan flow --
        never itself a prohibited edit."""
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-permitted", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert not any("prohibited plan-field edit" in f for f in failed)

    def test_graduated_registry_shard_row_sanctions_derived_path(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "sb-graduated",
            [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}],
            verification_plan=[
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "a",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                    "graduation": "graduate",
                    "graduation_check_id": "sb-my-check",
                }
            ],
        )
        shard = "config/agent/verification_registry/entries/sb-my-check.yaml"
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py", shard], root=repo)
        assert failed == []

    def test_decisions_index_regeneration_row_sanctions_when_decisions_md_in_scope(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-decisions", [{"file": "docs/DECISIONS.md", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "docs/DECISIONS.md", "docs/decisions-index.json"], root=repo)
        assert failed == []

    def test_decisions_index_not_sanctioned_when_decisions_md_not_in_scope(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-no-decisions", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py", "docs/decisions-index.json"], root=repo)
        assert any("docs/decisions-index.json" in f for f in failed)

    def test_unimplemented_sanction_kind_fails_loud(self, tmp_path: Path) -> None:
        rows = dict(_DEFAULT_SANCTION_ROWS)
        rows["mystery_row"] = {"trigger": {"kind": "some_unimplemented_kind"}, "sanctions": {}}
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-mystery", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], sanction_rows=rows
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert any("unimplemented trigger kind" in f and "mystery_row" in f for f in failed)

    def test_missing_contract_fails_loud(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        # No _write_contract() call -- the contract file is simply absent.
        _write_plan(repo, "sb-no-contract", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False)
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(
            repo, "sb-no-contract", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=True
        )
        _commit_all(repo, "declare implementation")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert any("could not load" in f and "implement-scope-boundary.yaml" in f for f in failed)

    def test_deleted_resolved_plan_path_is_skipped(self, tmp_path: Path, capsys) -> None:
        """A resolved-but-deleted plan path (only reachable via the plan_paths override -- real
        diff-derived resolution requires the plan to exist on disk) contributes no scope and no
        sanctions, but never raises -- it is printed as SKIP, not a failure in its own right."""
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-gone", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        (repo / rel).unlink()

        failed: list[str] = []
        validate_scope_boundary(failed, plan_paths=[rel], changed_files=[], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"SKIP: {rel} (not present on disk -- deleted in this diff)" in out

    def test_malformed_resolved_plan_fails_loud(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        plans_dir = repo / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        rel = "docs/plans/PLAN-sb-malformed.yaml"
        (plans_dir / "PLAN-sb-malformed.yaml").write_text(
            _yaml.dump({"implementation_declared": True, "slug": "sb-malformed"}), encoding="utf-8"
        )
        _commit_all(repo, "malformed plan")

        failed: list[str] = []
        validate_scope_boundary(failed, plan_paths=[rel], changed_files=[rel], root=repo)
        assert any("could not load plan" in f for f in failed)

    def test_prohibited_field_edits_empty_list_is_noop(self, tmp_path: Path) -> None:
        rows = {k: dict(v) for k, v in _DEFAULT_SANCTION_ROWS.items()}
        rows["implementing_plan_bookkeeping"]["prohibited_field_edits"] = []
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo, rows)
        _write_plan(repo, "sb-no-prohibited", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=False)
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = "docs/plans/PLAN-sb-no-prohibited.yaml"
        plan = _plan_dict("sb-no-prohibited", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=True)
        plan["acceptance_criteria"] = ["a DIFFERENT criterion than base"]
        (repo / rel).write_text(_yaml.dump(plan), encoding="utf-8")
        _commit_all(repo, "declare + edit acceptance_criteria, but no prohibited_field_edits declared")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert failed == []

    def test_net_new_plan_absent_at_base_skips_prohibited_edit_check(self, tmp_path: Path) -> None:
        """A plan with no prior content at base (net-new, same-PR plan+implementation) has
        nothing to diff a prohibited edit against -- never a failure."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        base_sha = _commit_all(repo, "base (no plan yet)")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = _write_plan(repo, "sb-net-new", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=True)
        _commit_all(repo, "add plan, already declared")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
        assert failed == []

    def test_unparseable_plan_content_at_base_treated_as_absent(self, tmp_path: Path) -> None:
        """Invalid YAML at the base ref for a resolved plan's path is treated the same as
        genuinely absent -- never a raise, never a false-positive prohibited-edit finding."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_contract(repo)
        plans_dir = repo / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        rel = "docs/plans/PLAN-sb-unparseable.yaml"
        (plans_dir / "PLAN-sb-unparseable.yaml").write_text("not: valid: yaml: [unclosed", encoding="utf-8")
        base_sha = _commit_all(repo, "base with unparseable plan content")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        (plans_dir / "PLAN-sb-unparseable.yaml").write_text(
            _yaml.dump(
                _plan_dict("sb-unparseable", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}], declared=True)
            ),
            encoding="utf-8",
        )
        _commit_all(repo, "replace with valid, declared plan")

        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py"], root=repo)
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
