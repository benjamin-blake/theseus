"""Package conftest for tests/checks/verification/validate_scope_boundary/ (Decision 131
concern-split decomposition of the former
tests/checks/verification/test_validate_scope_boundary.py monolith, SLOC decompose-by-default --
see AGENTS.md SLOC governance; sibling precedent:
tests/checks/verification/validate_graduation_completeness/{conftest.py,test_plan_leg.py}).

Homes every helper crossing the split boundary: _DEFAULT_SANCTION_ROWS (now carrying the
secrets_baseline_regeneration row), _DUMMY_VP_STEP, _plan_dict, _write_plan, _write_contract,
_git, _init_repo, _commit_all, _ResolvedFixture, and the new _write_baseline. Without this
conftest the implementer would duplicate this fixture surface across the sibling modules, or
import across test_* modules, which validate_no_cross_test_imports fails in both tiers (Decision
131 clause 2; conftest.py is exempt by construction).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml as _yaml

from scripts.checks import registry  # noqa: F401  (re-exported for `from .conftest import ...` in sibling test modules)
from scripts.checks.verification.validate_scope_boundary import (
    validate_scope_boundary,  # noqa: F401
)

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
    "secrets_baseline_regeneration": {
        "trigger": {"kind": "scope_file_in_secrets_baseline", "baseline_path": ".secrets.baseline"},
        "sanctions": {"path_template": ".secrets.baseline"},
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


def _write_baseline(root: Path, results: dict[str, list], rel: str = ".secrets.baseline") -> None:
    """Write a `.secrets.baseline`-shaped JSON file. `results` values must be empty lists (e.g.
    `{"scripts/x.py": []}`) so no fixture literal can trip the real detect-secrets hook and make
    this test module itself a baseline key."""
    (root / rel).write_text(json.dumps({"results": results}), encoding="utf-8")


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
