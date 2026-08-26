"""Package conftest for tests/checks/verification/validate_graduation_completeness/ (Decision
176 concern-split decomposition of the former
tests/checks/verification/test_validate_graduation_completeness.py monolith, SLOC
decompose-by-default -- see AGENTS.md SLOC governance).

Homes every helper crossing the split boundary: _write_registry (rewritten from a single flat
yaml.safe_dump to an N-file shard writer -- the old flat registry file under
config/agent/verification_registry/ no longer exists, Decision 176), _step, _write_plan,
_plan_dict, _git, _init_repo, _commit_all, and _ImplementFixture. Without this conftest the
implementer would duplicate ~80 SLOC across the two sibling modules, or import across test_*
modules, which validate_no_cross_test_imports fails in
both tiers (Decision 131 clause 2; conftest.py is exempt by construction).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from scripts.checks.verification.validate_graduation_completeness import (
    _current_registry_entries,  # noqa: F401  (re-exported for `from .conftest import ...` in sibling test modules)
    _default_baseline_registry_entries,  # noqa: F401
    validate_graduation_completeness,  # noqa: F401
)


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


def _plan_dict(slug: str, steps: list[dict], overrides: dict | None = None) -> dict:
    plan = {
        "schema_version": 1,
        "slug": slug,
        "intent": "Test fixture plan.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture -- no roadmap phase.",
        "scope": [{"file": "scripts/example.py", "action": "Create", "purpose": "Demo."}],
        "acceptance_criteria": ["Example acceptance criterion."],
        "verification_plan": steps,
        "execution_steps": ["Create scripts/example.py."],
    }
    plan.update(overrides or {})
    return plan


def _write_plan(root: Path, slug: str, steps: list[dict], overrides: dict | None = None) -> str:
    rel = f"docs/plans/PLAN-{slug}.yaml"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_plan_dict(slug, steps, overrides), sort_keys=False), encoding="utf-8")
    return rel


def _step(step: int, phase: str = "pre-deploy", **overrides) -> dict:
    base = {
        "step": step,
        "phase": phase,
        "action": "do something",
        "command": "echo ok",
        "expected": "prints ok",
        "fix_if": "never fails in practice",
    }
    base.update(overrides)
    return base


def _write_registry(root: Path, entries: list[dict]) -> None:
    """Write each entry to its own config/agent/verification_registry/entries/<check_id>.yaml
    shard (Decision 176) -- never a single flat file."""
    entries_dir = root / "config" / "agent" / "verification_registry" / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        path = entries_dir / f"{entry['check_id']}.yaml"
        path.write_text(yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")


class _ImplementFixture:
    """Repo builder: a base commit (origin/main), then a commit declaring the plan."""

    def build(
        self,
        tmp_path: Path,
        slug: str,
        steps: list[dict],
        registry_entries: list[dict] | None = None,
        plan_overrides: dict | None = None,
        commit_message: str = "checkpoint",
    ) -> tuple[Path, str]:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        overrides = {"implementation_declared": True}
        overrides.update(plan_overrides or {})
        rel = _write_plan(repo, slug, steps, overrides)
        if registry_entries is not None:
            _write_registry(repo, registry_entries)
        _commit_all(repo, commit_message)
        return repo, rel
