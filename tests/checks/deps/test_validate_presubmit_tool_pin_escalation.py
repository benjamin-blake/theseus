"""Mirror test for scripts/checks/deps/validate_presubmit_tool_pin_escalation.py -- the Class D
evaluator for docs/contracts/presubmit-tool-pin-escalation.yaml (Decision 168)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.deps.validate_presubmit_tool_pin_escalation import (
    validate_presubmit_tool_pin_escalation,
)

_GOOD_CONTRACT = """\
contract:
  id: presubmit-tool-pin-escalation
  class: D
  contract_version: 1
  status: ratified
  ratified_via: "PLAN-tool-pin-lint-escalation"
  subject: presubmit-tool-pin-escalation
  evaluator:
    check: validate_presubmit_tool_pin_escalation
mechanism:
  lint_targets: [src/, tests/, scripts/]
  precommit_config_path: .pre-commit-config.yaml
"""


def _write_contract(tmp_path: Path, text: str) -> None:
    contracts_dir = tmp_path / "docs" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "presubmit-tool-pin-escalation.yaml").write_text(text, encoding="utf-8")


class TestValidatePresubmitToolPinEscalation:
    def test_passes_when_mechanism_matches_live_code(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, _GOOD_CONTRACT)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_presubmit_tool_pin_escalation(failed)
        assert failed == []

    def test_fails_on_lint_targets_drift(self, tmp_path: Path) -> None:
        drifted = _GOOD_CONTRACT.replace("lint_targets: [src/, tests/, scripts/]", "lint_targets: [src/, tests/]")
        _write_contract(tmp_path, drifted)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_presubmit_tool_pin_escalation(failed)
        assert failed == ["Presubmit tool-pin escalation contract"]

    def test_fails_on_precommit_config_path_drift(self, tmp_path: Path) -> None:
        drifted = _GOOD_CONTRACT.replace(
            "precommit_config_path: .pre-commit-config.yaml", "precommit_config_path: .pre-commit.yaml"
        )
        _write_contract(tmp_path, drifted)
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_presubmit_tool_pin_escalation(failed)
        assert failed == ["Presubmit tool-pin escalation contract"]

    def test_fails_when_mechanism_block_is_missing(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "contract:\n  id: presubmit-tool-pin-escalation\n  class: D\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_presubmit_tool_pin_escalation(failed)
        assert len(failed) == 1

    def test_fails_when_contract_file_is_absent(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_presubmit_tool_pin_escalation(failed)
        assert len(failed) == 1

    def test_fails_on_unparseable_contract(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "not: valid: yaml: [")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_presubmit_tool_pin_escalation(failed)
        assert len(failed) == 1

    def test_live_contract_matches_live_code(self) -> None:
        """Regression guard against the REAL repo tree, not an injected fixture: the checked-in
        docs/contracts/presubmit-tool-pin-escalation.yaml must agree with the live scaffolding
        code today."""
        failed: list[str] = []
        validate_presubmit_tool_pin_escalation(failed)
        assert failed == []
