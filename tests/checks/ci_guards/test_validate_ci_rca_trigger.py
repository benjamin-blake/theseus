"""Tests for validate_ci_rca_trigger() -- the presubmit wrapper around _check_ci_rca_filter."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import _common, registry
from scripts.checks.ci_guards.validate_ci_rca_trigger import validate_ci_rca_trigger


class TestValidateCiRcaTrigger:
    """Tests for validate_ci_rca_trigger() -- the presubmit wrapper around _check_ci_rca_filter."""

    def test_passes_when_guard_succeeds(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter = MagicMock(return_value=6)

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)
        registry.pop_declaration()

        assert failed == []
        mock_module._check_ci_rca_filter.assert_called_once()

    def test_success_exit_declares_examined_trigger_workflows(self) -> None:
        """Decision 170: the success exit declares the guard's examined workflow_run.workflows
        entry count, so the run records enforced rather than undeclared."""
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter = MagicMock(return_value=7)

        registry.pop_declaration()
        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)
        declaration = registry.pop_declaration()

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 7, "ci_rca_trigger_workflows")

    def test_failing_guard_declares_nothing(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("main-branch gate missing")

        registry.pop_declaration()
        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert failed == ["ci-rca trigger gate"]
        assert registry.pop_declaration() is None

    def test_appends_to_failed_when_guard_raises(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("main-branch gate missing")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert len(failed) == 1
        assert "ci-rca trigger gate" in failed[0]

    def test_no_error_propagation_on_assertion(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("something wrong")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert failed == ["ci-rca trigger gate"]

    def test_no_error_propagation_on_runtime_error(self) -> None:
        """rec-2027: validate_ci_rca_trigger catches non-AssertionError and records failure."""
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = RuntimeError("unexpected boom")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert len(failed) == 1
        assert "ci-rca trigger gate" in failed[0]

    @pytest.mark.parametrize(
        ("guard_raises", "expected_failed"),
        [
            pytest.param(False, [], id="guard-passes"),
            pytest.param(True, ["ci-rca trigger gate"], id="guard-raises"),
        ],
    )
    def test_sys_path_cleanup_branch_exercised(
        self, monkeypatch: pytest.MonkeyPatch, guard_raises: bool, expected_failed: list[str]
    ) -> None:
        """rec-4159: the finally-block removes a ROOT the check injected, on both exits."""
        root_str = str(_common.ROOT)
        monkeypatch.setattr(sys, "path", [p for p in sys.path if p != root_str])
        root_on_path_during_call: list[bool] = []

        def _guard() -> int:
            root_on_path_during_call.append(root_str in sys.path)
            if guard_raises:
                raise RuntimeError("boom")
            return 6

        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = _guard

        registry.pop_declaration()
        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)
        registry.pop_declaration()

        assert root_on_path_during_call == [True]
        assert root_str not in sys.path
        assert failed == expected_failed
