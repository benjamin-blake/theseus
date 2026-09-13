"""Tests for validate_pydantic_yaml_drift / _check_drift_for_table (T0.12)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional
from unittest.mock import patch

from pydantic import BaseModel

from scripts.checks.ops_governance.validate_pydantic_yaml_drift import _check_drift_for_table, validate_pydantic_yaml_drift
from src.schemas.annotations import DqAcceptedValues, DqDeleted, DqNotNull, migrating


def _table(columns: dict) -> dict:
    return {"columns": columns}


def _col(*test_dicts) -> dict:
    return {"tests": list(test_dicts)}


class TestDriftDetectorAligned:
    def test_drift_detector_passes_when_aligned(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        table = _table({"field_a": _col({"not_null": {"enforced": True}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_aligned_with_accepted_values(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), DqAcceptedValues(values=("x", "y"))]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x", "y"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_unannotated_field_skipped(self) -> None:
        class SyntheticModel(BaseModel):
            plain_field: str

        table = _table({"plain_field": _col({"not_null": {}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_field_absent_from_yaml_skipped(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        table = _table({})  # field_a not in YAML columns
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_out_of_vocabulary_yaml_checks_ignored(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        # path_syntax and expression are out-of-vocabulary; only not_null should match
        table = _table({"field_a": _col({"not_null": {}}, {"path_syntax": {}}, {"expression": {}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []


class TestDriftDetectorUnmarkedDivergence:
    def test_drift_detector_fails_on_unmarked_divergence(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull()]

        # YAML has accepted_values but Pydantic does not
        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x", "y"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert any("field_a" in f for f in failed)

    def test_pydantic_extra_marker_fails(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), DqAcceptedValues(values=("x",))]

        # YAML only has not_null, Pydantic has also DqAcceptedValues
        table = _table({"field_a": _col({"not_null": {}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert any("field_a" in f for f in failed)


class TestMigratingMarker:
    def test_migrating_marker_tolerates_divergence(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), migrating(target="9999-12-31")]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_expired_migrating_marker_fails(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqNotNull(), migrating(target="1900-01-01")]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert any("field_a" in f for f in failed)


class TestDqDeleted:
    def test_dqdeleted_field_allowed_when_absent_from_yaml(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqDeleted(since="2026-01-01")]

        table = _table({})  # field_a absent from YAML
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_dqdeleted_field_skips_even_when_present_in_yaml(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[str, DqDeleted(since="2026-01-01")]

        table = _table({"field_a": _col({"not_null": {}}, {"accepted_values": {"values": ["x"]}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []

    def test_optional_annotated_field_is_processed(self) -> None:
        class SyntheticModel(BaseModel):
            field_a: Annotated[Optional[int], DqNotNull(enforced=False)] = None

        table = _table({"field_a": _col({"not_null": {"enforced": False}})})
        failed: list[str] = []
        _check_drift_for_table(failed, SyntheticModel, table)
        assert failed == []


_CLEAN_OPS_YAML = """tables:
  ops_recommendations:
    columns: {}
  ops_decisions:
    columns: {}
"""

# RecPayload.title carries DqNotNull; declaring only accepted_values here makes the
# symmetric difference non-empty, so the field-level append fires through the wrapper.
_DRIFTING_OPS_YAML = """tables:
  ops_recommendations:
    columns:
      title:
        tests:
          - accepted_values:
              values: ["a", "b"]
  ops_decisions:
    columns: {}
"""

_UNPARSEABLE_OPS_YAML = "tables: [unterminated\n"

# Parses cleanly, but to a LIST -- ops.get() then raises AttributeError, which is
# neither ImportError nor YAMLError, so the catch-all arm handles it.
_WRONG_SHAPE_OPS_YAML = "- ops_recommendations\n- ops_decisions\n"


def _write_ops_yaml(root: Path, body: str) -> None:
    dq_dir = root / "config" / "agent" / "data_quality"
    dq_dir.mkdir(parents=True, exist_ok=True)
    (dq_dir / "ops.yaml").write_text(body, encoding="utf-8")


def _run_wrapper(root: Path) -> list[str]:
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", root):
        validate_pydantic_yaml_drift(failed)
    return failed


class TestPydanticYamlDriftWrapper:
    """The REGISTERED wrapper itself -- every existing test above calls the private helper."""

    def test_missing_ops_yaml_appends_a_failure(self, tmp_path: Path, capsys) -> None:
        """No config/agent/data_quality/ops.yaml at all -> the wrapper appends and returns."""
        failed = _run_wrapper(tmp_path)
        assert failed == ["Pydantic-YAML drift"]
        assert "not found" in capsys.readouterr().out

    def test_clean_ops_yaml_prints_the_pass_line(self, tmp_path: Path, capsys) -> None:
        """A drift-free ops.yaml adds no failure AND prints the PASS line."""
        _write_ops_yaml(tmp_path, _CLEAN_OPS_YAML)
        failed = _run_wrapper(tmp_path)
        assert failed == []
        assert "PASS: pydantic-yaml drift check" in capsys.readouterr().out

    def test_drifting_ops_yaml_appends_the_field_level_failure(self, tmp_path: Path) -> None:
        """Anti-vacuity companion: a genuinely drifting ops.yaml reaches the field-level append."""
        _write_ops_yaml(tmp_path, _DRIFTING_OPS_YAML)
        assert _run_wrapper(tmp_path) == ["Pydantic-YAML drift: RecPayload.title"]

    def test_unimportable_schemas_appends_a_failure(self, tmp_path: Path, capsys) -> None:
        """An unimportable src.schemas is reported through the ImportError arm."""
        _write_ops_yaml(tmp_path, _CLEAN_OPS_YAML)
        with patch.dict(sys.modules, {"src.schemas": None}):
            failed = _run_wrapper(tmp_path)
        assert failed == ["Pydantic-YAML drift"]
        assert "Could not import src.schemas" in capsys.readouterr().out

    def test_unparseable_ops_yaml_appends_a_failure(self, tmp_path: Path, capsys) -> None:
        """An unterminated flow sequence raises yaml.YAMLError from safe_load."""
        _write_ops_yaml(tmp_path, _UNPARSEABLE_OPS_YAML)
        failed = _run_wrapper(tmp_path)
        assert failed == ["Pydantic-YAML drift"]
        assert "YAML parse error" in capsys.readouterr().out

    def test_unexpected_error_appends_a_failure(self, tmp_path: Path, capsys) -> None:
        """A parseable-but-wrongly-shaped ops.yaml lands in the catch-all arm."""
        _write_ops_yaml(tmp_path, _WRONG_SHAPE_OPS_YAML)
        failed = _run_wrapper(tmp_path)
        assert failed == ["Pydantic-YAML drift"]
        assert "Unexpected error" in capsys.readouterr().out
