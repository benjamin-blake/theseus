"""Tests for validate_dependabot_automation() -- dependabot automation structural guard."""

import copy
from pathlib import Path
from typing import Callable
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ci_guards.validate_dependabot_automation import (
    _WORKFLOW_ASSERTIONS,
    assert_auto_merge_workflow,
    assert_stranded_sweep_workflow,
    validate_dependabot_automation,
)

_MODULE = "scripts.checks.ci_guards.validate_dependabot_automation"
_SCRIPT_REL_PATH = "scripts/ci/dependabot_auto_merge.sh"
_SWEEP_SCRIPT_REL_PATH = "scripts/ci/dependabot_stranded_sweep.sh"

_JOB_IF = "github.event.pull_request.user.login == 'dependabot[bot]' && github.repository == 'benjamin-blake/theseus'"

_CHECKOUT_STEP = {"uses": "actions/checkout@v7", "with": {"ref": "${{ github.event.pull_request.base.sha }}"}}
_METADATA_STEP = {
    "name": "Fetch dependabot metadata",
    "id": "metadata",
    "uses": "dependabot/fetch-metadata@v2",
    "with": {"github-token": "${{ secrets.GITHUB_TOKEN }}"},
}
_DELEGATION_STEP = {"name": "Apply the minor/patch auto-merge policy", "run": f"bash {_SCRIPT_REL_PATH}"}


def _workflow_with_steps(steps: list[dict]) -> dict:
    return {
        "name": "dependabot-auto-merge",
        "on": {"pull_request": {"types": ["opened", "synchronize", "reopened"]}},
        "permissions": {"contents": "write", "pull-requests": "write"},
        "jobs": {"auto-merge": {"if": _JOB_IF, "runs-on": "ubuntu-latest", "steps": steps}},
    }


_VALID_WORKFLOW = _workflow_with_steps([_CHECKOUT_STEP, _METADATA_STEP, _DELEGATION_STEP])

# A minimal, self-consistent policy delegate carrying every literal the guard's semantic
# assertions look for. Every fail-path fixture below mutates exactly ONE property of this base so
# each test isolates exactly one guard assertion (never two failures at once).
_VALID_SCRIPT = """\
#!/usr/bin/env bash
set -uo pipefail
set +e

_ALLOWED_PATCH_UPDATE="version-update:semver-patch"
_ALLOWED_MINOR_UPDATE="version-update:semver-minor"
_DENIED_DEPENDENCIES="duckdb ducklake"

gh pr merge --auto --squash "$PR_URL"
merge_rc=$?
"""

_VALID_STRANDED_WORKFLOW = {
    "name": "dependabot-stranded",
    "on": {"schedule": [{"cron": "0 8 * * 1"}], "workflow_dispatch": {}},
    "permissions": {"contents": "write", "pull-requests": "write"},
    "jobs": {
        "sweep": {
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v7"},
                {"name": "Sweep stranded dependabot PRs", "run": f"bash {_SWEEP_SCRIPT_REL_PATH}"},
            ],
        }
    },
}

_VALID_SWEEP_SCRIPT = """\
#!/usr/bin/env bash
set -uo pipefail
set +e

gh pr update-branch "$number"
update_rc=$?

gh pr comment "$number" --body "@dependabot rebase"
"""


def _write_script(tmp_path: Path, content: str, rel_path: str = _SCRIPT_REL_PATH) -> None:
    full_path = tmp_path / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")


def _write_both_scripts(tmp_path: Path, *, auto_merge: str = _VALID_SCRIPT, sweep: str = _VALID_SWEEP_SCRIPT) -> None:
    """Both delegates on an isolated ROOT -- every assertion in _WORKFLOW_ASSERTIONS reads one."""
    _write_script(tmp_path, auto_merge, _SCRIPT_REL_PATH)
    _write_script(tmp_path, sweep, _SWEEP_SCRIPT_REL_PATH)


def _loader(*, auto_merge: dict | None = None, stranded: dict | None = None) -> Callable[[str], dict]:
    """A path-aware `_load` stand-in.

    The check walks EVERY workflow in _WORKFLOW_ASSERTIONS in one pass, so a single `return_value`
    would hand the stranded assertion the auto-merge document and fail it for reasons no test
    intended. Dispatching on the workflow filename keeps each fail-path mutation isolated to the
    one assertion under test.
    """
    auto_merge_data = _VALID_WORKFLOW if auto_merge is None else auto_merge
    stranded_data = _VALID_STRANDED_WORKFLOW if stranded is None else stranded

    def _load(path: str) -> dict:
        return stranded_data if "dependabot-stranded" in str(path) else auto_merge_data

    return _load


class TestValidateDependabotAutomationPassPath:
    """Pass-path: the real workflow file, and a valid mocked _load, both leave failed empty."""

    def test_passes_against_real_workflow_file(self) -> None:
        failed: list[str] = []
        validate_dependabot_automation(failed)
        assert failed == []

    def test_passes_with_well_formed_mocked_data(self) -> None:
        with patch(f"{_MODULE}._load", side_effect=_loader()):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert failed == []

    def test_passes_with_mocked_data_and_isolated_script(self, tmp_path: Path) -> None:
        """Fully isolated from the real repo scripts -- pins the minimal valid shapes on their own."""
        _write_both_scripts(tmp_path)
        with patch(f"{_MODULE}._load", side_effect=_loader()), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert failed == []


class TestValidateDependabotAutomationWorkflowFailPath:
    """Fail-path: mocked workflow data missing each asserted property appends a distinct failure."""

    def test_load_failure_records_failure_no_propagation(self) -> None:
        with patch(f"{_MODULE}._load", side_effect=OSError("no such file")):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        # One "unreadable" entry per guarded workflow, derived from the assertion tuple rather than
        # pinned to a literal, so adding a third dependabot workflow does not break this test.
        assert len(failed) == len(_WORKFLOW_ASSERTIONS)
        assert all("unreadable" in entry for entry in failed)

    def test_wrong_workflow_name_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["name"] = "dependabot-automerge"
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("name field is the taxonomy key" in f for f in failed)

    def test_wrong_pull_request_types_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["on"]["pull_request"]["types"] = ["opened", "synchronize"]
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("exactly the three PR types" in f for f in failed)

    def test_pull_request_target_trigger_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["on"]["pull_request_target"] = {"types": ["opened"]}
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("pull_request_target trigger is absent" in f for f in failed)

    def test_widened_permissions_fail(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["permissions"]["id-token"] = "write"
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("permissions are exactly" in f for f in failed)

    def test_no_jobs_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"] = {}
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("no jobs defined" in f for f in failed)

    def test_missing_author_gate_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["auto-merge"]["if"] = "github.repository == 'benjamin-blake/theseus'"
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("dependabot[bot] PR author" in f for f in failed)

    def test_missing_repository_gate_fails(self) -> None:
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["auto-merge"]["if"] = "github.event.pull_request.user.login == 'dependabot[bot]'"
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("pins github.repository" in f for f in failed)

    def test_actor_gate_fails(self) -> None:
        """An actor gate would silently disable the stranded sweep's update-branch re-evaluations."""
        data = copy.deepcopy(_VALID_WORKFLOW)
        data["jobs"]["auto-merge"]["if"] = f"{_JOB_IF} && github.actor == 'dependabot[bot]'"
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("does not pin github.actor" in f for f in failed)

    def test_checkout_without_base_sha_ref_fails(self) -> None:
        data = _workflow_with_steps([{"uses": "actions/checkout@v7"}, _METADATA_STEP, _DELEGATION_STEP])
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("checkout pins ref to the base SHA" in f for f in failed)

    def test_missing_checkout_step_fails(self) -> None:
        data = _workflow_with_steps([_METADATA_STEP, _DELEGATION_STEP])
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("checkout pins ref to the base SHA" in f for f in failed)

    def test_missing_fetch_metadata_step_fails(self) -> None:
        data = _workflow_with_steps([_CHECKOUT_STEP, _DELEGATION_STEP])
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("fetch-metadata step is present" in f for f in failed)

    def test_unresolvable_delegate_fails(self) -> None:
        data = _workflow_with_steps([_CHECKOUT_STEP, _METADATA_STEP, {"run": "gh pr merge --auto --squash $PR_URL"}])
        with patch(f"{_MODULE}._load", side_effect=_loader(auto_merge=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("could not resolve delegate script" in f for f in failed)

    def test_delegate_script_missing_on_disk_fails(self, tmp_path: Path) -> None:
        with patch(f"{_MODULE}._load", side_effect=_loader()), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("delegate script missing on disk" in f for f in failed)


class TestValidateDependabotAutomationScriptFailPath:
    """Fail-path: the policy delegate missing (or wrongly gaining) each asserted literal."""

    @staticmethod
    def _run(tmp_path: Path, script_text: str) -> list[str]:
        _write_both_scripts(tmp_path, auto_merge=script_text)
        with patch(f"{_MODULE}._load", side_effect=_loader()), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        return failed

    def test_errexit_not_cleared_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT.replace("set +e\n", ""))
        assert any("clears inherited errexit" in f for f in failed)

    def test_missing_patch_update_type_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT.replace("version-update:semver-patch", "semver-patch"))
        assert any("allows the patch update type" in f for f in failed)

    def test_missing_minor_update_type_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT.replace("version-update:semver-minor", "semver-minor"))
        assert any("allows the minor update type" in f for f in failed)

    def test_major_update_type_present_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT + '_ALSO_ALLOWED="version-update:semver-major"\n')
        assert any("never allows the major update type" in f for f in failed)

    def test_missing_duckdb_denylist_literal_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT.replace("duckdb", "sqlite"))
        assert any("names duckdb in the lockstep denylist" in f for f in failed)

    def test_missing_ducklake_denylist_literal_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT.replace("ducklake", "icelake"))
        assert any("names ducklake in the lockstep denylist" in f for f in failed)

    def test_missing_auto_squash_merge_call_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SCRIPT.replace("gh pr merge --auto --squash", "gh pr merge --squash"))
        assert any("arms auto-merge via gh pr merge" in f for f in failed)


class TestStrandedSweepWorkflowFailPath:
    """Fail-path: the dependabot-stranded workflow missing each asserted property."""

    @staticmethod
    def _run(data: dict) -> list[str]:
        with patch(f"{_MODULE}._load", side_effect=_loader(stranded=data)):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        return failed

    def test_wrong_sweep_workflow_name_fails(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        data["name"] = "dependabot-sweep"
        assert any("sweep name field is the taxonomy key" in f for f in self._run(data))

    def test_missing_cron_schedule_fails(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        del data["on"]["schedule"]
        assert any("sweep declares a cron schedule" in f for f in self._run(data))

    def test_schedule_without_a_cron_key_fails(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        data["on"]["schedule"] = [{}]
        assert any("sweep declares a cron schedule" in f for f in self._run(data))

    def test_missing_workflow_dispatch_fails(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        del data["on"]["workflow_dispatch"]
        assert any("sweep declares workflow_dispatch" in f for f in self._run(data))

    def test_widened_sweep_permissions_fail(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        data["permissions"]["id-token"] = "write"
        assert any("sweep permissions are exactly" in f for f in self._run(data))

    def test_narrowed_sweep_permissions_fail(self) -> None:
        """contents: write alone cannot update a branch; the sweep would fail on every PR."""
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        del data["permissions"]["pull-requests"]
        assert any("sweep permissions are exactly" in f for f in self._run(data))

    def test_no_sweep_jobs_fails(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        data["jobs"] = {}
        assert any("no jobs defined" in f for f in self._run(data))

    def test_unresolvable_sweep_delegate_fails(self) -> None:
        data = copy.deepcopy(_VALID_STRANDED_WORKFLOW)
        data["jobs"]["sweep"]["steps"] = [{"run": "gh pr update-branch 1"}]
        assert any("could not resolve delegate script" in f for f in self._run(data))

    def test_sweep_delegate_missing_on_disk_fails(self, tmp_path: Path) -> None:
        _write_script(tmp_path, _VALID_SCRIPT, _SCRIPT_REL_PATH)
        with patch(f"{_MODULE}._load", side_effect=_loader()), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        assert any("dependabot-stranded: delegate script missing on disk" in f for f in failed)


class TestStrandedSweepScriptFailPath:
    """Fail-path: the sweep delegate missing each asserted recovery literal."""

    @staticmethod
    def _run(tmp_path: Path, sweep_text: str) -> list[str]:
        _write_both_scripts(tmp_path, sweep=sweep_text)
        with patch(f"{_MODULE}._load", side_effect=_loader()), patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        return failed

    def test_sweep_errexit_not_cleared_fails(self, tmp_path: Path) -> None:
        failed = self._run(tmp_path, _VALID_SWEEP_SCRIPT.replace("set +e\n", ""))
        assert any("sweep delegate clears inherited errexit" in f for f in failed)

    def test_missing_update_branch_call_fails(self, tmp_path: Path) -> None:
        """Without it the sweep reports the backlog but never clears a single BEHIND PR."""
        failed = self._run(tmp_path, _VALID_SWEEP_SCRIPT.replace("gh pr update-branch", "gh pr view"))
        assert any("updates behind branches via gh pr update-branch" in f for f in failed)

    def test_missing_rebase_fallback_fails(self, tmp_path: Path) -> None:
        """A DIRTY branch can only be rescued by dependabot recreating it."""
        failed = self._run(tmp_path, _VALID_SWEEP_SCRIPT.replace("@dependabot rebase", "please rebase"))
        assert any("keeps the @dependabot rebase fallback" in f for f in failed)


class TestAccountingDeclaration:
    """Decision 170: a new check must declare examined()/skipped() on every reachable exit path."""

    def test_examined_is_declared_on_the_pass_path(self) -> None:
        with registry.outcome_scope("validate_dependabot_automation"):
            failed: list[str] = []
            validate_dependabot_automation(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count >= 1

    def test_examined_is_declared_when_the_workflow_is_unreadable(self) -> None:
        with registry.outcome_scope("validate_dependabot_automation"):
            with patch(f"{_MODULE}._load", side_effect=OSError("no such file")):
                failed: list[str] = []
                validate_dependabot_automation(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"


class TestWorkflowAssertionRegistry:
    """The per-workflow assertion tuple is the extension point: a second dependabot workflow adds
    its own helper here and nothing else in the module changes."""

    def test_auto_merge_assertion_is_registered(self) -> None:
        assert assert_auto_merge_workflow in _WORKFLOW_ASSERTIONS

    def test_stranded_sweep_assertion_is_registered(self) -> None:
        assert assert_stranded_sweep_workflow in _WORKFLOW_ASSERTIONS

    def test_every_assertion_is_callable_and_returns_an_examined_count(self) -> None:
        assert all(callable(assertion) for assertion in _WORKFLOW_ASSERTIONS)
        failed: list[str] = []
        assert all(isinstance(assertion(failed), int) for assertion in _WORKFLOW_ASSERTIONS)
        assert failed == []
