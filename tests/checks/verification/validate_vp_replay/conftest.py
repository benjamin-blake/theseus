"""Package conftest for tests/checks/verification/validate_vp_replay/ (PLAN-vp-replay-mirror-
decomposition concern-split decomposition of the former
tests/checks/verification/test_validate_vp_replay.py monolith, SLOC decompose-by-default -- see
AGENTS.md SLOC governance; sibling precedents:
tests/checks/verification/validate_graduation_completeness/{conftest.py,test_implement_leg.py},
tests/checks/verification/validate_scope_boundary/{conftest.py,test_plan_legs.py}).

Homes every helper crossing the split boundary: _vp_replay_plan_dict, _write_vp_replay_plan, _git,
_init_repo, _commit_all, and _ResolvedFixture. Also homes _build_undeclared_repo, the ONE permitted
deviation from verbatim relocation: the undeclared-repo build previously inline inside
TestPlanOnlyLeg.test_undeclared_plan_defers_no_execution, lifted here (body moved verbatim, only
its location changes) so PLAN-vp-red-before-gate's slice 2 -- which carries this same conftest as a
Modify row -- never has to re-touch a module this plan just relocated. Without this conftest the
implementer would duplicate this fixture surface across the four sibling modules, or import across
test_* modules, which validate_no_cross_test_imports fails in both tiers (Decision 131 clause 2;
conftest.py is exempt by construction).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml as _yaml

from scripts.checks import registry  # noqa: F401  (re-exported for `from .conftest import ...` in sibling test modules)
from scripts.checks.verification.validate_vp_replay import (
    validate_vp_replay,  # noqa: F401
)


def _vp_replay_plan_dict(slug: str, verification_plan: list[dict], declared: bool = False) -> dict:
    return {
        "schema_version": 2,
        "slug": slug,
        "intent": "Fixture plan for validate_vp_replay unit tests.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture",
        "scope": [{"file": "scripts/dummy.py", "action": "Modify", "purpose": "test fixture"}],
        "acceptance_criteria": ["dummy criterion"],
        "verification_plan": verification_plan,
        "execution_steps": ["dummy step"],
        "implementation_declared": declared,
    }


def _write_vp_replay_plan(root: Path, slug: str, verification_plan: list[dict], declared: bool = False) -> str:
    plans_dir = root / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(
        _yaml.dump(_vp_replay_plan_dict(slug, verification_plan, declared)), encoding="utf-8"
    )
    return rel


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


def _build_undeclared_repo(tmp_path: Path) -> tuple[Path, str]:
    """Base commit (origin/main) plus an undeclared plan commit -- the DEFER-path fixture lifted
    verbatim from the former inline body of TestPlanOnlyLeg.test_undeclared_plan_defers_no_execution."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    base_sha = _commit_all(repo, "base")
    _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

    rel = _write_vp_replay_plan(
        repo,
        "vpr-plan-only",
        [
            {
                "step": 1,
                "phase": "pre-deploy",
                "hermetic": True,
                "action": "Run a command that would fail if replayed.",
                "command": "exit 1",
                "expected": "Exit 0.",
                "fix_if": "n/a",
            }
        ],
        declared=False,
    )
    _commit_all(repo, "add undeclared plan")
    return repo, rel


class _ResolvedFixture:
    """Shared repo builder: a base commit (origin/main), then a second commit declaring the
    plan's implementation_declared true -- the resolvable, replayable shape."""

    def build(self, tmp_path: Path, slug: str, verification_plan: list[dict], commit_message: str = "checkpoint") -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = _write_vp_replay_plan(repo, slug, verification_plan, declared=True)
        _commit_all(repo, commit_message)
        return repo, rel
