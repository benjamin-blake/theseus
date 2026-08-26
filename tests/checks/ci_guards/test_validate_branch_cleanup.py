"""Tests for validate_branch_cleanup() -- branch-cleanup.yml structural guard."""

import copy
from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ci_guards.validate_branch_cleanup import validate_branch_cleanup

_MODULE = "scripts.checks.ci_guards.validate_branch_cleanup"
_SCRIPT_REL_PATH = "scripts/ci/branch_cleanup.sh"
_MODULE_REL_PATH = "scripts/ci/branch_cleanup.py"

_CHECKOUT_STEP = {"uses": "actions/checkout@v7", "with": {"fetch-depth": 0}}
_DELEGATION_STEP = {"name": "Classify and delete stale remote branches", "run": f"bash {_SCRIPT_REL_PATH}"}

_VALID_WORKFLOW = {
    "name": "branch-cleanup",
    "on": {
        "workflow_dispatch": {
            "inputs": {
                "dry_run": {"type": "boolean", "default": True},
                "min_age_hours": {"default": "48"},
                "extra_branches": {"default": ""},
            }
        }
    },
    "permissions": {"contents": "write"},
    "jobs": {"cleanup": {"runs-on": "ubuntu-latest", "steps": [_CHECKOUT_STEP, _DELEGATION_STEP]}},
}

_VALID_SHELL = f"""\
#!/usr/bin/env bash
set -uo pipefail

exec python3 {_MODULE_REL_PATH}
"""

# A minimal decision module carrying every sentinel the guard looks for. Each fail-path fixture
# below mutates exactly ONE property of this base, so each test isolates one guard assertion.
_VALID_DECISION_MODULE = """\
PROTECTED_BRANCHES = frozenset({"main"})

GUARD_PROTECTED_BRANCH = "protected-branch"
GUARD_OPEN_PR = "open-pr"
GUARD_YOUNGER_THAN_MIN_AGE = "younger-than-min-age"
GUARD_UNKNOWN_AGE = "unknown-age"
CLASS_MERGED_PR_HEAD = "merged-pr-head"
CLASS_ANCESTOR_OF_MAIN = "ancestor-of-main"
CLASS_EXTRA_BRANCH = "extra-branch"


def open_pr_heads(runner):
    return set()


def decide_branch(branch, sha, *, age_hours, min_age_hours, **_kwargs):
    if age_hours < min_age_hours:
        return GUARD_YOUNGER_THAN_MIN_AGE
    return CLASS_UNCLASSIFIED


def delete_remote_branch(runner, repo, branch):
    return runner(["gh", "api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{branch}"])
"""


def _write(tmp_path: Path, rel_path: str, content: str) -> None:
    full_path = tmp_path / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")


def _write_tree(tmp_path: Path, *, shell: str = _VALID_SHELL, module: str = _VALID_DECISION_MODULE) -> None:
    _write(tmp_path, _SCRIPT_REL_PATH, shell)
    _write(tmp_path, _MODULE_REL_PATH, module)


class TestValidateBranchCleanupPassPath:
    """Pass-path: the real files, and a valid mocked pair, both leave failed empty."""

    def test_passes_against_real_workflow_file(self) -> None:
        failed: list[str] = []
        validate_branch_cleanup(failed)
        assert failed == []

    def test_passes_with_well_formed_mocked_data(self) -> None:
        with patch(f"{_MODULE}._load", return_value=_VALID_WORKFLOW):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        assert failed == []

    def test_passes_with_mocked_data_and_isolated_tree(self, tmp_path: Path) -> None:
        """Fully isolated from the real repo files -- pins the minimal valid shape on its own."""
        _write_tree(tmp_path)
        with patch(f"{_MODULE}._load", return_value=_VALID_WORKFLOW), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        assert failed == []


class TestValidateBranchCleanupWorkflowFailPath:
    """Fail-path: mocked workflow data missing each asserted property appends a distinct failure."""

    @staticmethod
    def _run(data: dict) -> list[str]:
        with patch(f"{_MODULE}._load", return_value=data):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        return failed

    def test_load_failure_records_failure_no_propagation(self) -> None:
        with patch(f"{_MODULE}._load", side_effect=OSError("no such file")):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        assert failed == ["branch-cleanup: workflow file unreadable"]

    def test_wrong_workflow_name_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["name"] = "branch-cleaner"
        assert any("name field is the taxonomy key" in f for f in self._run(data))

    def test_added_schedule_trigger_fails(self) -> None:
        """An unattended trigger on a ref-deleting workflow is exactly the risk this gate holds."""
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["on"]["schedule"] = [{"cron": "0 3 * * 0"}]
        assert any("trigger set is workflow_dispatch and nothing else" in f for f in self._run(data))

    def test_added_push_trigger_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["on"]["push"] = {"branches": ["main"]}
        assert any("trigger set is workflow_dispatch and nothing else" in f for f in self._run(data))

    def test_dry_run_defaulting_to_false_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["on"]["workflow_dispatch"]["inputs"]["dry_run"]["default"] = False
        assert any("dry_run input defaults to true" in f for f in self._run(data))

    def test_missing_dry_run_input_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        del data["on"]["workflow_dispatch"]["inputs"]["dry_run"]
        assert any("dry_run input defaults to true" in f for f in self._run(data))

    def test_widened_permissions_fail(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["permissions"]["pull-requests"] = "write"
        assert any("permissions are exactly contents: write" in f for f in self._run(data))

    def test_no_jobs_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"] = {}
        assert any("no jobs defined" in f for f in self._run(data))

    def test_shallow_checkout_fails(self) -> None:
        """Without full history the classifier cannot answer ancestor-of-main or tip age."""
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["cleanup"]["steps"] = [{"uses": "actions/checkout@v7"}, _DELEGATION_STEP]
        assert any("checkout requests full history" in f for f in self._run(data))

    def test_unresolvable_delegate_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["cleanup"]["steps"] = [_CHECKOUT_STEP, {"run": "python3 scripts/ci/branch_cleanup.py"}]
        assert any("could not resolve delegate script" in f for f in self._run(data))

    def test_delegate_script_missing_on_disk_fails(self, tmp_path: Path) -> None:
        with patch(f"{_MODULE}._load", return_value=_VALID_WORKFLOW), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        assert any("delegate script missing on disk" in f for f in failed)


class TestValidateBranchCleanupDecisionModuleFailPath:
    """Fail-path: the shell delegate or the decision module missing each asserted sentinel."""

    @staticmethod
    def _run(tmp_path: Path, *, shell: str = _VALID_SHELL, module: str = _VALID_DECISION_MODULE) -> list[str]:
        _write_tree(tmp_path, shell=shell, module=module)
        with patch(f"{_MODULE}._load", return_value=_VALID_WORKFLOW), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        return failed

    def test_shell_not_naming_the_module_fails(self, tmp_path: Path) -> None:
        shell = _VALID_SHELL.replace(_MODULE_REL_PATH, "scripts/ci/something_else.py")
        assert any("hands off to the branch_cleanup decision module" in f for f in self._run(tmp_path, shell=shell))

    def test_decision_module_missing_on_disk_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, _SCRIPT_REL_PATH, _VALID_SHELL)
        with patch(f"{_MODULE}._load", return_value=_VALID_WORKFLOW), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        assert any("decision module missing on disk" in f for f in failed)

    def test_missing_protected_branch_guard_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("GUARD_PROTECTED_BRANCH", "_UNUSED_A")
        assert any("keeps the protected-branch hard guard" in f for f in self._run(tmp_path, module=module))

    def test_missing_open_pr_guard_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("GUARD_OPEN_PR", "_UNUSED_B")
        assert any("keeps the open-PR hard guard" in f for f in self._run(tmp_path, module=module))

    def test_missing_min_age_guard_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("GUARD_YOUNGER_THAN_MIN_AGE", "_UNUSED_C")
        assert any("keeps the min-age hard guard" in f for f in self._run(tmp_path, module=module))

    def test_missing_unknown_age_guard_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("GUARD_UNKNOWN_AGE", "_UNUSED_D")
        assert any("keeps the unknown-age hard guard" in f for f in self._run(tmp_path, module=module))

    def test_missing_merged_pr_class_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("CLASS_MERGED_PR_HEAD", "_UNUSED_E")
        assert any("keeps the merged-PR-head delete class" in f for f in self._run(tmp_path, module=module))

    def test_missing_ancestor_class_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("CLASS_ANCESTOR_OF_MAIN", "_UNUSED_F")
        assert any("keeps the ancestor-of-main delete class" in f for f in self._run(tmp_path, module=module))

    def test_missing_extra_branch_class_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("CLASS_EXTRA_BRANCH", "_UNUSED_G")
        assert any("keeps the extra_branches delete class" in f for f in self._run(tmp_path, module=module))

    def test_main_dropped_from_the_protected_set_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace('PROTECTED_BRANCHES = frozenset({"main"})', "PROTECTED_BRANCHES = frozenset()")
        assert any("protects main by name" in f for f in self._run(tmp_path, module=module))

    def test_min_age_comparison_removed_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("age_hours < min_age_hours", "age_hours is None")
        assert any("compares tip age against the min-age floor" in f for f in self._run(tmp_path, module=module))

    def test_missing_open_pr_query_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("def open_pr_heads(", "def _heads(")
        assert any("queries open PRs to feed the open-PR guard" in f for f in self._run(tmp_path, module=module))

    def test_missing_decide_branch_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("def decide_branch(", "def _decide(")
        assert any("exposes the decide_branch policy function" in f for f in self._run(tmp_path, module=module))

    def test_missing_refs_endpoint_fails(self, tmp_path: Path) -> None:
        module = _VALID_DECISION_MODULE.replace("git/refs/heads/", "git/tags/")
        assert any("deletes through the git refs endpoint" in f for f in self._run(tmp_path, module=module))


class TestAccountingDeclaration:
    """Decision 170: a new check must declare examined()/skipped() on every reachable exit path."""

    def test_examined_is_declared_on_the_pass_path(self) -> None:
        with registry.outcome_scope("validate_branch_cleanup"):
            failed: list[str] = []
            validate_branch_cleanup(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1

    def test_examined_is_declared_when_the_workflow_is_unreadable(self) -> None:
        with registry.outcome_scope("validate_branch_cleanup"):
            with patch(f"{_MODULE}._load", side_effect=OSError("no such file")):
                failed: list[str] = []
                validate_branch_cleanup(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"

    def test_examined_is_declared_when_the_delegate_cannot_be_resolved(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["cleanup"]["steps"] = [_CHECKOUT_STEP]
        with registry.outcome_scope("validate_branch_cleanup"):
            with patch(f"{_MODULE}._load", return_value=data):
                failed: list[str] = []
                validate_branch_cleanup(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"

    def test_examined_is_declared_when_no_jobs_are_defined(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"] = {}
        with registry.outcome_scope("validate_branch_cleanup"):
            with patch(f"{_MODULE}._load", return_value=data):
                failed: list[str] = []
                validate_branch_cleanup(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
