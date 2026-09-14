"""Tests for scripts/checks/contracts/validate_maintenance_policy_matrix.py (exhaustiveness gate,
compaction-scope-policy-matrix, Decision 191)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.checks.contracts import validate_maintenance_policy_matrix as check

pytestmark = pytest.mark.unit


def _write_sidecar(tmp_path: Path, matrix: dict) -> Path:
    path = tmp_path / "field_semantics.static.yaml"
    path.write_text(yaml.dump({"maintenance_policy": matrix}), encoding="utf-8")
    return path


_EXHAUSTIVE_MATRIX = {
    "scd2": {"merge_ops": {"apply": True, "reason": "standard"}},
    "append_only": {"merge_ops": {"apply": True, "reason": "standard"}},
    "control": {"merge_ops": {"apply": True, "reason": "standard"}},
}
_UNIVERSE = {"scd2", "append_only", "control"}
_VERBS = ("merge_ops",)


def test_exhaustive_matrix_passes(tmp_path: Path) -> None:
    path = _write_sidecar(tmp_path, _EXHAUSTIVE_MATRIX)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == []


def test_missing_cell_fails(tmp_path: Path) -> None:
    matrix = {k: v for k, v in _EXHAUSTIVE_MATRIX.items() if k != "control"}
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == ["Maintenance policy matrix exhaustiveness"]


def test_missing_apply_key_fails(tmp_path: Path) -> None:
    matrix = dict(_EXHAUSTIVE_MATRIX)
    matrix["control"] = {"merge_ops": {"reason": "no apply key here"}}
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == ["Maintenance policy matrix exhaustiveness"]


def test_apply_false_missing_reason_fails(tmp_path: Path) -> None:
    matrix = dict(_EXHAUSTIVE_MATRIX)
    matrix["control"] = {"merge_ops": {"apply": False}}
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == ["Maintenance policy matrix exhaustiveness"]


def test_apply_false_with_reason_passes(tmp_path: Path) -> None:
    matrix = dict(_EXHAUSTIVE_MATRIX)
    matrix["control"] = {"merge_ops": {"apply": False, "reason": "deliberately excluded"}}
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == []


def test_unknown_class_fails(tmp_path: Path) -> None:
    """A matrix row for a class outside the DECLARED universe is a drift signal, not a free pass."""
    matrix = dict(_EXHAUSTIVE_MATRIX)
    matrix["bogus_class"] = {"merge_ops": {"apply": True, "reason": "should never appear"}}
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == ["Maintenance policy matrix exhaustiveness"]


def test_self_referential_universe_is_vacuously_exhaustive(tmp_path: Path) -> None:
    """Documents the exact failure mode this gate exists to close: deriving the class universe
    FROM the matrix's own keys makes any matrix trivially exhaustive against itself, even one
    missing a real declared class -- proving why class_universe must come from an independent
    source, never a default computed from the matrix under test."""
    matrix = {k: v for k, v in _EXHAUSTIVE_MATRIX.items() if k != "control"}  # missing "control"
    self_referential_universe = set(matrix.keys())  # the anti-pattern: universe == matrix.keys()
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(
        failed, sidecar_path=path, class_universe=self_referential_universe, verb_universe=_VERBS
    )
    assert failed == [], "a self-referential universe hides the missing 'control' class -- this is the bug being documented"


def test_default_universe_rejects_what_a_self_referential_universe_would_hide(tmp_path: Path) -> None:
    """The counterpart to the self-referential test: the SAME matrix missing 'control', checked
    against the true declared universe, is correctly rejected."""
    matrix = {k: v for k, v in _EXHAUSTIVE_MATRIX.items() if k != "control"}
    path = _write_sidecar(tmp_path, matrix)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert failed == ["Maintenance policy matrix exhaustiveness"]


def test_default_class_universe_reads_the_live_registry(tmp_path: Path) -> None:
    """Without an override, class_universe is derived from the live field_semantics registry
    (never from the matrix under test) -- exercises _declared_class_universe()'s real body."""
    path = _write_sidecar(tmp_path, _EXHAUSTIVE_MATRIX)
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=path, verb_universe=_VERBS)
    assert failed == []


def test_unreadable_sidecar_path_fails(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.yaml"
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed, sidecar_path=missing, class_universe=_UNIVERSE, verb_universe=_VERBS)
    assert len(failed) == 1
    assert "could not read" in failed[0]


def test_real_sidecar_is_exhaustive() -> None:
    """Sanity: the committed sidecar's real matrix passes against the real live registry."""
    failed: list[str] = []
    check.validate_maintenance_policy_matrix(failed)
    assert failed == []
