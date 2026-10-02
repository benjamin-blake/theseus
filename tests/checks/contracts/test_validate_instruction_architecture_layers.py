"""Tests for validate_instruction_architecture_layers()."""

from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import yaml

from scripts.checks import registry
from scripts.checks.contracts._shared import _load_prompt_compliance
from scripts.checks.contracts.validate_instruction_architecture_layers import validate_instruction_architecture_layers


class TestValidateInstructionArchitectureLayers:
    """Tests for validate_instruction_architecture_layers()."""

    def test_passes_when_all_layers_resolve(self, tmp_path: Path) -> None:
        """No failures when every layer's content_locations resolves."""
        mock_compliance = MagicMock()
        mock_compliance._load_instruction_architecture.return_value = {
            "layers": [{"layer": 1, "name": "Universal rules", "content_locations": []}]
        }
        mock_compliance.check_layer_compliance.return_value = []

        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=mock_compliance,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert failed == []

    def test_fails_when_layer_glob_unresolved(self, tmp_path: Path) -> None:
        """Appends to failed list when a layer glob resolves to nothing."""
        mock_compliance = MagicMock()
        mock_compliance._load_instruction_architecture.return_value = {"layers": []}
        mock_compliance.check_layer_compliance.return_value = ["layer 99 (Ghost): no files match 'ghost/*.md'"]

        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=mock_compliance,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert len(failed) == 1
        assert "Instruction architecture layer claims" in failed[0]

    def test_skips_when_compliance_not_found(self) -> None:
        """No failures when prompt_compliance.py is absent."""
        with patch(
            "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
            return_value=None,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert failed == []


class TestContractPresence:
    """migration-step-3-grandfathering: an absent/unparseable instruction-architecture.yaml now
    FAILS the check instead of silently falling back to a stub dict and passing vacuously (the
    real hole: prompt_compliance._load_instruction_architecture() degrades a missing contract to
    {"layers": []}, which check_layer_compliance reports as zero violations)."""

    def test_missing_contract_fails(self, tmp_path: Path) -> None:
        # tmp_path has no docs/contracts/instruction-architecture.yaml at all.
        mock_compliance = MagicMock()
        with (
            patch("scripts.checks.contracts.validate_instruction_architecture_layers._common.ROOT", tmp_path),
            patch(
                "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
                return_value=mock_compliance,
            ) as load_compliance,
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert len(failed) == 1
        assert "does not exist" in failed[0]
        # The presence assertion fires BEFORE delegating -- the vacuous-pass loader is never
        # even reached on a genuinely missing contract.
        load_compliance.assert_not_called()

    def test_present_contract_still_delegates_normally(self, tmp_path: Path) -> None:
        contracts_dir = tmp_path / "docs" / "contracts"
        contracts_dir.mkdir(parents=True)
        (contracts_dir / "instruction-architecture.yaml").write_text("layers: []\n", encoding="utf-8")

        mock_compliance = MagicMock()
        mock_compliance._load_instruction_architecture.return_value = {"layers": []}
        mock_compliance.check_layer_compliance.return_value = []

        with (
            patch("scripts.checks.contracts.validate_instruction_architecture_layers._common.ROOT", tmp_path),
            patch(
                "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance",
                return_value=mock_compliance,
            ),
        ):
            failed: list[str] = []
            validate_instruction_architecture_layers(failed)

        assert failed == []


_CHECK = "validate_instruction_architecture_layers"
_UNIT = "content_locations"
_REPO_ROOT = Path(__file__).parents[3]
_LOADER = "scripts.checks.contracts.validate_instruction_architecture_layers._load_prompt_compliance"


class _GlobCountingRoot:
    """Stands in for prompt_compliance.ROOT, counting the glob calls the helper makes while judging."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.glob_calls = 0

    def glob(self, pattern: str) -> Iterator[Path]:
        self.glob_calls += 1
        return self._root.glob(pattern)


def _real_compliance(root: Path | _GlobCountingRoot, contract: dict) -> ModuleType:
    """A fresh, unmocked prompt_compliance module whose layer globbing runs under `root` against `contract`."""
    module = _load_prompt_compliance()
    assert module is not None
    module.ROOT = root
    module._INSTRUCTION_ARCH_REGISTRY = contract
    return module


def _declared(compliance: ModuleType | None) -> tuple[list[str], registry._Declaration | None]:
    registry.pop_declaration()
    failed: list[str] = []
    with patch(_LOADER, return_value=compliance):
        validate_instruction_architecture_layers(failed)
    return failed, registry.pop_declaration()


class TestInstructionArchitectureLayersAccountingDeclaration:
    """The check declares how many content_locations globs it judged, so a run records enforced with a
    count that tracks the contract -- not a constant, not the layer count and not the violation count."""

    def test_real_tree_declares_every_content_location(self) -> None:
        contract = yaml.safe_load(
            (_REPO_ROOT / "docs" / "contracts" / "instruction-architecture.yaml").read_text(encoding="utf-8")
        )
        expected = sum(len(layer.get("content_locations") or []) for layer in contract["layers"])

        registry.pop_declaration()
        failed: list[str] = []
        validate_instruction_architecture_layers(failed)
        declaration = registry.pop_declaration()
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert expected > 0
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)
        assert outcome.status == "enforced"

    def test_count_spans_layers_when_every_glob_resolves(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("x\n", encoding="utf-8")
        (tmp_path / "skills").mkdir()
        (tmp_path / "skills" / "a.md").write_text("x\n", encoding="utf-8")
        contract = {
            "layers": [
                {"layer": 1, "name": "Universal", "content_locations": ["AGENTS.md", "*.md"]},
                {"layer": 2, "name": "Skills", "content_locations": ["skills/*.md", "skills/a.md"]},
            ]
        }

        failed, declaration = _declared(_real_compliance(tmp_path, contract))
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 4, _UNIT)
        assert outcome.status == "enforced"

    def test_unresolved_glob_is_counted_and_records_failed(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text("x\n", encoding="utf-8")
        contract = {
            "layers": [
                {"layer": 1, "name": "Universal", "content_locations": ["AGENTS.md", "ghost/*.md"]},
                {"layer": 2, "name": "No globs"},
                {"layer": 3, "name": "Also universal", "content_locations": ["*.md"]},
            ]
        }

        failed, declaration = _declared(_real_compliance(tmp_path, contract))
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == ["Instruction architecture layer claims"]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "failed"

    def test_declared_count_equals_globs_the_helper_actually_judged(self, tmp_path: Path) -> None:
        """Pins the wrapper's count to the helper's own judging loop: a helper that stopped after the first
        violation, or judged only some layers, would glob fewer times than the check declares."""
        (tmp_path / "AGENTS.md").write_text("x\n", encoding="utf-8")
        contract = {
            "layers": [
                {"layer": 1, "name": "Early violation", "content_locations": ["ghost/*.md", "AGENTS.md"]},
                {"layer": 2, "name": "Second", "content_locations": ["*.md"]},
                {"layer": 3, "name": "Third", "content_locations": ["AGENTS.md"]},
                {"layer": 4, "name": "Fourth", "content_locations": ["phantom/*.md", "*.md"]},
            ]
        }
        root = _GlobCountingRoot(tmp_path)

        failed, declaration = _declared(_real_compliance(root, contract))

        assert failed == ["Instruction architecture layer claims"]
        assert declaration is not None
        assert declaration.count == root.glob_calls == 6

    def test_empty_layers_declares_vacuous_domain(self, tmp_path: Path) -> None:
        failed, declaration = _declared(_real_compliance(tmp_path, {"layers": []}))
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "vacuous"

    def test_absent_prompt_compliance_declares_skipped(self) -> None:
        failed, declaration = _declared(None)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert "prompt_compliance.py" in (declaration.reason or "")
        assert outcome.status == "skipped"
