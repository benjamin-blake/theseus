"""Tests for validate_ci_rca_lifecycle_projection() -- PLAN-class-d-contract-enforcers.

Covers: green path against a fixture matching the live CiRcaContext + taxonomy pointers, an
unknown-projection-field red path, an enum-mismatch red path, a dead-pointer red path, and
ABSENT/EMPTY projection_fields / watched_workflow_set red paths, plus missing-file and
malformed-YAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.checks import registry
from scripts.checks.contracts import validate_ci_rca_lifecycle_projection as _mod
from scripts.checks.contracts.validate_ci_rca_lifecycle_projection import _field_pattern, validate_ci_rca_lifecycle_projection

_CONTRACT_NAME = "ci-rca-lifecycle.yaml"

_VALID_PROJECTION_FIELDS = {
    "regression_of": {"type": "Optional[str]", "home": "context_v2_json (CiRcaContext)"},
    "escape_class": {
        "type": "Optional[str]",
        "enum": ["no-edge", "capped", "unknown-data-edge"],
        "home": "context_v2_json (CiRcaContext)",
    },
}

_VALID_WATCHED_WORKFLOW_SET = {
    "source_of_truth": "config/ci_rca_taxonomy.yaml",
    "source_of_truth_field": "workflows: (each entry: tier, ci_rca [watched|excluded], owner, rationale)",
    "evaluator": "validate_ci_rca_adjudication",
    "evaluator_module": "scripts/checks/ci_guards/validate_ci_rca_adjudication.py",
}


def _write_contract(contracts_dir: Path, projection_fields: dict, watched_workflow_set: dict) -> None:
    doc = {"projection_fields": projection_fields, "watched_workflow_set": watched_workflow_set}
    (contracts_dir / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")


class TestGreenPath:
    def test_valid_fixture_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert failed == []


class TestUnknownProjectionField:
    def test_unknown_field_fails(self, tmp_path: Path) -> None:
        fields = dict(_VALID_PROJECTION_FIELDS)
        fields["not_a_real_field"] = {"type": "Optional[str]", "home": "context_v2_json (CiRcaContext)"}
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("not on CiRcaContext" in f for f in failed)


class TestEnumMismatch:
    def test_changed_enum_fails(self, tmp_path: Path) -> None:
        fields = {
            "escape_class": {
                "type": "Optional[str]",
                "enum": ["no-edge", "capped"],
                "home": "context_v2_json (CiRcaContext)",
            }
        }
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("does not equal the live CiRcaContext.escape_class pattern alternation" in f for f in failed)

    def test_missing_enum_fails(self, tmp_path: Path) -> None:
        fields = {"escape_class": {"type": "Optional[str]", "home": "context_v2_json (CiRcaContext)"}}
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("missing a non-empty 'enum'" in f for f in failed)


class TestDeadPointer:
    def test_dead_source_of_truth_fails(self, tmp_path: Path) -> None:
        watched = dict(_VALID_WATCHED_WORKFLOW_SET)
        watched["source_of_truth"] = "config/does-not-exist.yaml"
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, watched)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("does not resolve to an existing file" in f for f in failed)

    def test_dead_source_of_truth_field_fails(self, tmp_path: Path) -> None:
        watched = dict(_VALID_WATCHED_WORKFLOW_SET)
        watched["source_of_truth_field"] = "not_a_real_key: (whatever)"
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, watched)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("names no top-level key present in" in f for f in failed)

    def test_unregistered_evaluator_fails(self, tmp_path: Path) -> None:
        watched = dict(_VALID_WATCHED_WORKFLOW_SET)
        watched["evaluator"] = "validate_totally_fake_check"
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, watched)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("is not a registered check" in f for f in failed)

    def test_dead_evaluator_module_fails(self, tmp_path: Path) -> None:
        watched = dict(_VALID_WATCHED_WORKFLOW_SET)
        watched["evaluator_module"] = "scripts/checks/ci_guards/does_not_exist.py"
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, watched)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("does not resolve to an existing file" in f for f in failed)

    def test_unparseable_source_of_truth_yaml_is_a_dead_pointer(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "bad.yaml").write_text("{unterminated", encoding="utf-8")
        monkeypatch.setattr(_mod._common, "ROOT", tmp_path)

        watched = dict(_VALID_WATCHED_WORKFLOW_SET)
        watched["source_of_truth"] = "config/bad.yaml"
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, watched)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("names no top-level key present in" in f for f in failed)


_DETECTION_GAP_ESCAPE_MODE_FIELD = {
    "type": "Optional[str]",
    "enum": ["check_ran_vacuously", "tier_misplaced", "no_premerge_gate_by_design", "undetermined"],
    "home": "context_v2_json.detection_gap (CiRcaContext._DetectionGap)",
}


class TestDottedProjectionFieldResolution:
    """T1.13:c9 repair: dotted projection_fields keys resolve through nested BaseModel
    annotations -- detection_gap.escape_mode lives on the nested _DetectionGap model, not
    directly on CiRcaContext, so a top-level-only resolver would false-positive 'not on
    CiRcaContext' for a perfectly real field."""

    def test_dotted_key_on_nested_model_resolves(self, tmp_path: Path) -> None:
        fields = dict(_VALID_PROJECTION_FIELDS)
        fields["detection_gap.escape_mode"] = _DETECTION_GAP_ESCAPE_MODE_FIELD
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert failed == []

    def test_dotted_key_not_on_nested_model_fails(self, tmp_path: Path) -> None:
        fields = dict(_VALID_PROJECTION_FIELDS)
        fields["detection_gap.not_a_real_nested_field"] = {"type": "Optional[str]", "home": "nowhere"}
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("not on CiRcaContext" in f for f in failed)


class TestGeneralisedEnumParity:
    """The enum-parity obligation derives from the LIVE PYDANTIC MODEL, not from the contract's
    own `enum:` key -- so the check stays mandatory and the contract cannot disarm it."""

    def test_alternation_shaped_dotted_field_missing_enum_fails(self, tmp_path: Path) -> None:
        fields = dict(_VALID_PROJECTION_FIELDS)
        fields["detection_gap.escape_mode"] = {"type": "Optional[str]", "home": "context_v2_json.detection_gap"}
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("projection_fields.detection_gap.escape_mode missing a non-empty 'enum'" in f for f in failed)

    def test_alternation_shaped_dotted_field_wrong_enum_fails(self, tmp_path: Path) -> None:
        fields = dict(_VALID_PROJECTION_FIELDS)
        fields["detection_gap.escape_mode"] = {**_DETECTION_GAP_ESCAPE_MODE_FIELD, "enum": ["bogus"]}
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("does not equal the live CiRcaContext.detection_gap.escape_mode pattern alternation" in f for f in failed)

    def test_escape_class_enum_still_required_after_generalisation(self, tmp_path: Path) -> None:
        """No-weakening half: deleting escape_class.enum must STILL fail post-generalisation --
        proving the obligation derives from the live model, not merely from the contract's own
        historical hardcoded escape_class lookup."""
        fields = {"escape_class": {"type": "Optional[str]", "home": "context_v2_json (CiRcaContext)"}}
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("missing a non-empty 'enum'" in f for f in failed)

    def test_accumulates_both_missing_enums_rather_than_returning_early(self, tmp_path: Path) -> None:
        """Two enum-less alternation-shaped entries must BOTH be reported -- an early `return`
        after the first would silently hide the second."""
        fields = {
            "escape_class": {"type": "Optional[str]", "home": "context_v2_json (CiRcaContext)"},
            "detection_gap.escape_mode": {"type": "Optional[str]", "home": "context_v2_json.detection_gap"},
        }
        _write_contract(tmp_path, fields, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        joined = " ".join(failed)
        assert "escape_class" in joined
        assert "detection_gap.escape_mode" in joined


class TestFieldPatternHelper:
    def test_returns_none_when_no_pattern_metadata(self) -> None:
        class _NoPatternMeta:
            pass

        class _FakeFieldInfo:
            metadata = [_NoPatternMeta()]

        assert _field_pattern(_FakeFieldInfo()) is None


class TestAbsentEmptyTarget:
    def test_missing_projection_fields_fails(self, tmp_path: Path) -> None:
        doc = {"watched_workflow_set": _VALID_WATCHED_WORKFLOW_SET}
        (tmp_path / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("missing or empty top-level 'projection_fields'" in f for f in failed)

    def test_missing_watched_workflow_set_fails(self, tmp_path: Path) -> None:
        doc = {"projection_fields": _VALID_PROJECTION_FIELDS}
        (tmp_path / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("missing or empty top-level 'watched_workflow_set'" in f for f in failed)


class TestMissingFile:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("not found" in f for f in failed)


class TestMalformedYaml:
    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("projection_fields: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("could not read/parse" in f for f in failed)

    def test_non_mapping_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("- a\n- b\n", encoding="utf-8")

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert any("is not a YAML mapping" in f for f in failed)


class TestWiring:
    def test_wiring_registered_in_pre_and_full(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}

        assert "validate_ci_rca_lifecycle_projection" in pre_names
        assert "validate_ci_rca_lifecycle_projection" in full_names

    def test_wiring_resolves_via_registry(self) -> None:
        resolved = registry.resolve("validate_ci_rca_lifecycle_projection")

        assert callable(resolved)
        assert resolved is validate_ci_rca_lifecycle_projection


class TestPassLineOutput:
    """The PASS summary is the ONLY test-observable consequence of the `len(failed) ==
    error_count_before` accounting branch: registry.examined() runs unconditionally above it,
    so neither the accounting channel nor `failed` can discriminate a flipped comparison."""

    def test_clean_fixture_prints_the_pass_line(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_contract(tmp_path, _VALID_PROJECTION_FIELDS, _VALID_WATCHED_WORKFLOW_SET)

        failed: list[str] = []
        validate_ci_rca_lifecycle_projection(failed, contracts_dir=tmp_path)

        assert failed == []
        out = capsys.readouterr().out
        expected = "  PASS: ci-rca-lifecycle.yaml projection_fields, escape_class enum, and watched_workflow_set all resolve."
        assert expected in out
