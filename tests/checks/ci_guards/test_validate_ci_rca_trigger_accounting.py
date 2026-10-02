"""Check-accounting declaration tests for validate_ci_rca_trigger() (Decision 170)."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks import registry, validation_result
from scripts.checks.ci_guards.validate_ci_rca_trigger import validate_ci_rca_trigger
from scripts.verify_ci_workflow._ci_rca import _REQUIRED_CI_RCA_WORKFLOWS

_REPO_ROOT = Path(__file__).parents[3]
_UNIT = "ci_rca_trigger_workflows"
_CANARY = "Main Canary"
_FLOOR = [*_REQUIRED_CI_RCA_WORKFLOWS, _CANARY]
_RCA_IF = "github.event.workflow_run.head_branch == github.event.repository.default_branch"
_FILED_MARKER = "## Step 6: Report\n\nFILED: rec-NNN or FILED: none\n"


def _run(workflows: list[str], agent_doc: str = _FILED_MARKER) -> tuple[list[str], registry._Declaration | None]:
    rca_data = {"on": {"workflow_run": {"workflows": workflows}}, "jobs": {"rca": {"if": _RCA_IF}}}
    with (
        patch("scripts.verify_ci_workflow._ci_rca._load") as mock_load,
        patch("scripts.verify_ci_workflow._ci_rca.Path") as mock_path,
    ):
        mock_load.side_effect = lambda p: {"name": _CANARY} if "canary" in p else rca_data
        mock_path.return_value.read_text.return_value = agent_doc
        registry.pop_declaration()
        failed: list[str] = []
        validate_ci_rca_trigger(failed)
        return failed, registry.pop_declaration()


def _real_tree_filter_entries() -> int:
    data = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci-rca.yml").read_text(encoding="utf-8"))
    on = data.get("on", data.get(True))
    return len(on["workflow_run"]["workflows"])


class TestCiRcaTriggerAccountingDeclaration:
    """The gate declares how many ci-rca.yml workflow_run.workflows entries it examined, so a run is
    recorded enforced with a count that tracks the filter list -- not the fixed required floor and
    not a constant."""

    def test_real_tree_declares_every_filter_entry(self) -> None:
        expected = _real_tree_filter_entries()

        registry.pop_declaration()
        failed: list[str] = []
        validate_ci_rca_trigger(failed)
        declaration = registry.pop_declaration()

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)

    def test_count_tracks_filter_list_not_required_floor(self) -> None:
        floor_failed, floor = _run(list(_FLOOR))
        grown_failed, grown = _run([*_FLOOR, "deploy-prod-lambdas", "extra-ops-workflow"])

        assert floor_failed == [] and grown_failed == []
        assert floor is not None and grown is not None
        assert (floor.count, grown.count) == (len(_FLOOR), len(_FLOOR) + 2)

    @pytest.mark.parametrize(
        ("workflows", "agent_doc"),
        [
            ([w for w in _FLOOR if w != "CI"], _FILED_MARKER),
            ([*_FLOOR, "CI"], _FILED_MARKER),
            (list(_FLOOR), "## Step 6: Report\n\nno marker here\n"),
        ],
        ids=["missing-required", "duplicate-entry", "missing-filed-marker"],
    )
    def test_failing_runs_record_failed(self, workflows: list[str], agent_doc: str) -> None:
        rca_data = {"on": {"workflow_run": {"workflows": workflows}}, "jobs": {"rca": {"if": _RCA_IF}}}
        validation_result._OUTCOMES.clear()
        failed: list[str] = []
        try:
            with (
                patch("scripts.verify_ci_workflow._ci_rca._load") as mock_load,
                patch("scripts.verify_ci_workflow._ci_rca.Path") as mock_path,
            ):
                mock_load.side_effect = lambda p: {"name": _CANARY} if "canary" in p else rca_data
                mock_path.return_value.read_text.return_value = agent_doc
                validation_result.dispatch_recording("validate_ci_rca_trigger", failed, validate_ci_rca_trigger)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert failed == ["ci-rca trigger gate"]
        assert outcome.status == "failed"

    def test_real_tree_is_recorded_enforced(self) -> None:
        validation_result._OUTCOMES.clear()
        try:
            validation_result.dispatch_recording("validate_ci_rca_trigger", [], validate_ci_rca_trigger)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert (outcome.status, outcome.examined_unit) == ("enforced", _UNIT)
        assert outcome.examined_count == _real_tree_filter_entries()
