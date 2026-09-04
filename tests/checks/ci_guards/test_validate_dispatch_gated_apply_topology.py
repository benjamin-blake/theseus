"""Tests for validate_dispatch_gated_apply_topology() -- terraform-apply-sandbox.yml's
dispatch-reachable gated-apply topology guard (Decision 183; rec-2918 part (c)).

Pass-path fixture is the REAL committed workflow (never an inline stand-in, so a future edit that
quietly drifts the real file is caught here too). Every negative deep-copies that real parsed
workflow and mutates exactly one invariant-relevant field, then patches this module's own `_load`
binding to return the mutated dict -- so each negative isolates to its own invariant's failure
label and never trips a sibling invariant by accident.
"""

from __future__ import annotations

import copy
from unittest.mock import patch

from scripts.checks import _common, registry
from scripts.checks.ci_guards.validate_dispatch_gated_apply_topology import (
    validate_dispatch_gated_apply_topology,
)
from scripts.verify_ci_workflow import _load

_MODULE = "scripts.checks.ci_guards.validate_dispatch_gated_apply_topology"
_WORKFLOW_REL_PATH = ".github/workflows/terraform-apply-sandbox.yml"


def _real_workflow() -> dict:
    return _load(str(_common.ROOT / _WORKFLOW_REL_PATH))


def _run(data: dict) -> list[str]:
    with patch(f"{_MODULE}._load", return_value=data):
        failed: list[str] = []
        validate_dispatch_gated_apply_topology(failed)
    return failed


def _pre_fix_shape() -> dict:
    """Deep-copy the real parsed workflow and rebuild the EXACT pre-fix shape gated-apply carried
    before Decision 183: its `if` regains the push conjunct that made a guard-ROUTED
    workflow_dispatch structurally unreachable (rec-2918's dispatch-vs-push deadlock). This is the
    LOAD-BEARING negative -- it must fail invariant (i) and nothing else."""
    data = copy.deepcopy(_real_workflow())
    gated_if = str(data["jobs"]["gated-apply"]["if"])
    data["jobs"]["gated-apply"]["if"] = f"{gated_if} && github.event_name == 'push'"
    return data


class TestPassPath:
    def test_passes_against_the_real_committed_workflow(self) -> None:
        failed: list[str] = []
        validate_dispatch_gated_apply_topology(failed)
        assert failed == []

    def test_registered_in_pre_sequence(self) -> None:
        names = {step.name for step in registry.pre_sequence()}
        assert "validate_dispatch_gated_apply_topology" in names

    def test_examined_count_is_seven_topology_invariants(self) -> None:
        with registry.outcome_scope("validate_dispatch_gated_apply_topology"):
            failed: list[str] = []
            validate_dispatch_gated_apply_topology(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 7
        assert declaration.unit == "topology_invariants"


class TestPreFixShapeNegative:
    def test_pre_fix_shape_fails_only_invariant_i(self) -> None:
        failed = _run(_pre_fix_shape())
        assert any("(i)" in item for item in failed), failed
        # LOAD-BEARING: the pre-fix shape only reintroduces the push conjunct -- every other
        # invariant must stay green, or this negative is not isolating the defect it claims to.
        assert not any("(ii)" in item for item in failed), failed
        assert not any("(iii)" in item for item in failed), failed


class TestPerInvariantNegatives:
    def test_invariant_i_fails_when_routed_signal_missing(self) -> None:
        data = copy.deepcopy(_real_workflow())
        data["jobs"]["gated-apply"]["if"] = "always() && needs.apply-sandbox.result == 'success'"
        failed = _run(data)
        assert any("(i)" in item for item in failed), failed

    def test_invariant_ii_fails_when_environment_dropped(self) -> None:
        data = copy.deepcopy(_real_workflow())
        del data["jobs"]["gated-apply"]["environment"]
        failed = _run(data)
        assert any("(ii)" in item for item in failed), failed

    def test_invariant_ii_fails_when_terraform_plan_smuggled_in(self) -> None:
        data = copy.deepcopy(_real_workflow())
        data["jobs"]["gated-apply"]["steps"].append({"name": "sneaky replan", "run": "terraform plan -out=plan.bin"})
        failed = _run(data)
        assert any("(ii)" in item for item in failed), failed

    def test_invariant_iii_fails_when_fresh_plan_pending_output_missing(self) -> None:
        data = copy.deepcopy(_real_workflow())
        del data["jobs"]["apply-sandbox"]["outputs"]["fresh_plan_pending"]
        failed = _run(data)
        assert any("(iii)" in item for item in failed), failed

    def test_invariant_iv_fails_when_upload_artifact_step_ungated(self) -> None:
        data = copy.deepcopy(_real_workflow())
        for step in data["jobs"]["apply-sandbox"]["steps"]:
            if str(step.get("uses", "")).startswith("actions/upload-artifact"):
                step["if"] = "success()"
        failed = _run(data)
        assert any("(iv)" in item for item in failed), failed

    def test_invariant_v_fails_when_download_artifact_step_ungated(self) -> None:
        data = copy.deepcopy(_real_workflow())
        for step in data["jobs"]["gated-apply"]["steps"]:
            if str(step.get("uses", "")).startswith("actions/download-artifact"):
                step["if"] = "success()"
        failed = _run(data)
        assert any("(v)" in item for item in failed), failed

    def test_invariant_v_fails_when_fetch_plan_not_mutually_exclusive(self) -> None:
        data = copy.deepcopy(_real_workflow())
        for step in data["jobs"]["gated-apply"]["steps"]:
            if step.get("id") == "fetch_plan":
                step["if"] = "success()"
        failed = _run(data)
        assert any("(v)" in item for item in failed), failed

    def test_invariant_vi_fails_when_artifact_sha_not_consumed(self) -> None:
        data = copy.deepcopy(_real_workflow())
        for step in data["jobs"]["gated-apply"]["steps"]:
            if step.get("id") == "artifact_sha":
                step["run"] = 'echo "value=hardcoded" >> "$GITHUB_OUTPUT"'
        failed = _run(data)
        assert any("(vi)" in item for item in failed), failed

    def test_invariant_vii_fails_when_wake_sha_not_derived_from_ack_input(self) -> None:
        data = copy.deepcopy(_real_workflow())
        for step in data["jobs"]["apply-sandbox"]["steps"]:
            if "wake" in str(step.get("name", "")).lower():
                step["env"]["SHA"] = "${{ github.sha }}"
        failed = _run(data)
        assert any("(vii)" in item for item in failed), failed


class TestUnreadableWorkflow:
    def test_skipped_is_declared_when_workflow_unreadable(self) -> None:
        with registry.outcome_scope("validate_dispatch_gated_apply_topology"):
            with patch(f"{_MODULE}._load", side_effect=OSError("no such file")):
                failed: list[str] = []
                validate_dispatch_gated_apply_topology(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "skipped"
