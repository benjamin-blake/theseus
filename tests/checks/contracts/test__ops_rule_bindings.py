"""Unit cases for scripts/checks/contracts/_ops_rule_bindings.py: the ops.yaml write_time parity and the status
vocabulary legs, moved verbatim from validate_ops_rule_source (rec-4158) with one change -- the not_null parity reads
presence through scripts.contract_rules."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.checks.contracts import _ops_rule_bindings as bindings
from scripts.checks.contracts import _rule_grammar as grammar

_REPO = Path(__file__).resolve().parents[3]
_OPS = "config/agent/data_quality/ops.yaml"
_SOURCES = (_OPS, "src/common/ducklake_scd2_schema.py", "scripts/executor/jsonl_store.py")


@pytest.fixture
def recs() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fields, intents, _ = grammar.read_table("ops_recommendations", _REPO / "docs/contracts", _REPO)
    return fields, intents


def _root(tmp_path: Path) -> Path:
    for rel in _SOURCES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_REPO / rel, tmp_path / rel)
    return tmp_path


def _ops_with(tmp_path: Path, column: str, tests: list[Any]) -> Path:
    (tmp_path / _OPS).parent.mkdir(parents=True, exist_ok=True)
    doc = {"tables": {"ops_recommendations": {"columns": {column: {"tests": tests}}}}}
    (tmp_path / _OPS).write_text(yaml.safe_dump(doc), encoding="utf-8")
    return tmp_path


def test_the_real_tree_agrees(recs) -> None:
    assert bindings.binding_errors(_REPO, *recs) == []


def test_not_null_parity_reads_presence(tmp_path: Path) -> None:
    root = _ops_with(tmp_path, "risk", [{"not_null": {"write_time": True}}])
    raw = {"risk": {"iceberg_type": "string"}}
    blank_rejecting = {"accepted_values": {"values": ["low"]}}
    for declared in (True, {"exclude_before": "2026-10-01"}, {"enforced": True}):
        assert bindings._parity_errors(root, raw, {"risk": {"not_null": declared, **blank_rejecting}}) == [], declared
    for undeclared in ({}, {"not_null": {"enforced": False}}):
        errors = bindings._parity_errors(root, raw, {"risk": {**undeclared, **blank_rejecting}})
        assert any("ops.yaml risk.not_null: no equal not_null rule in the contract" in e for e in errors), undeclared
    errors = bindings._parity_errors(root, raw, {"risk": {"not_null": True}})
    assert any("a VARCHAR column needs a blank-rejecting rule" in e for e in errors)


@pytest.mark.parametrize(
    ("tests", "message"),
    [
        (["a_bare_name", {}], "test entry {} must be a name or a single-key mapping"),
        ([{"made_up": {"write_time": True}}], "write_time test kind 'made_up' has no contract mapping"),
        ([{"expression": {"write_time": True}}], None),
        ([{"not_null": {"write_time": False}}], None),
    ],
)
def test_ops_yaml_entries(tmp_path: Path, recs, tests: list[Any], message: str | None) -> None:
    errors = bindings._parity_errors(_ops_with(tmp_path, "title", tests), *recs)
    if message is None:
        assert errors == []
    else:
        assert any(message in e for e in errors), errors


def test_a_column_the_contract_does_not_declare(tmp_path: Path, recs) -> None:
    root = _ops_with(tmp_path, "ghost", [{"not_null": {"write_time": True}}])
    assert any("column the contract does not declare" in e for e in bindings._parity_errors(root, *recs))


def test_parity_of_each_test_kind(tmp_path: Path, recs) -> None:
    fields, intents = recs
    tests = [
        {"min_length": {"write_time": True, "value": 1}},
        {"accepted_values": {"write_time": True, "values": ["nope"]}},
        {"array_element_format": {"write_time": True, "pattern": "^x$"}},
        {"path_syntax": {"write_time": True}},
        {"acceptance_lint": {"write_time": True}},
    ]
    errors = bindings._parity_errors(_ops_with(tmp_path, "title", tests), fields, {"title": {"not_null": True}})
    for expected in (
        "ops.yaml title.min_length: value differs",
        "ops.yaml title.accepted_values: values differ",
        "ops.yaml title.array_element_format: pattern differs",
        "ops.yaml title.path_syntax: no equal pattern rule",
        "ops.yaml title.acceptance_lint: no declared acceptance_lint",
    ):
        assert any(expected in e for e in errors), (expected, errors)


def test_status_sources_fail_closed(tmp_path: Path, recs) -> None:
    _, intents = recs
    root = _root(tmp_path)
    assert bindings._status_errors(root, intents) == []
    (root / "scripts/executor/jsonl_store.py").write_text("OTHER = 1\n", encoding="utf-8")
    errors = bindings._status_errors(root, intents)
    assert any("could not read the jsonl_store._VALID_STATUSES" in e for e in errors)
    assert any("could not read the Recommendation status Literal" in e for e in errors)
    (root / "scripts/executor/jsonl_store.py").write_text("_VALID_STATUSES = frozenset(compute())\n", encoding="utf-8")
    assert any("could not read the jsonl_store._VALID_STATUSES" in e for e in bindings._status_errors(root, intents))
    (root / "src/common/ducklake_scd2_schema.py").write_text("STATUS_TRANSITIONS = {}\n", encoding="utf-8")
    assert any("STATUS_TRANSITIONS enforced set" in e for e in bindings._status_errors(root, intents))
    (root / "src/common/ducklake_scd2_schema.py").write_text("STATUS_TRANSITIONS = build()\n", encoding="utf-8")
    assert any("STATUS_TRANSITIONS enforced set" in e for e in bindings._status_errors(root, intents))
    drifted = {**intents, "status": {"accepted_values": {"values": ["open"]}}}
    assert any(
        "status vocabulary: the contract's ['open'] differs" in e
        for e in bindings._status_errors(_root(tmp_path / "b"), drifted)
    )


def test_unreadable_inputs_raise_for_the_entry_to_report(tmp_path: Path, recs) -> None:
    (tmp_path / _OPS).parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(OSError):
        bindings.binding_errors(tmp_path, *recs)
    root = _root(tmp_path / "b")
    (root / "scripts/executor/jsonl_store.py").write_text("_VALID_STATUSES = []\nx = (\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        bindings.binding_errors(root, *recs)
