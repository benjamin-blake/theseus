"""Mirror test for scripts/field_semantics_rule_projection.py (rec-4158 plan B): the ops_recommendations contract's
declared rules reach the generated projection exactly once, exemptions ship only as exemptions, an unknown kind fails
closed, and the rule projection moves nothing but rule keys under ops_tables.*.columns."""

from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

import scripts.field_semantics_rule_projection as projection
from scripts.contract_rules import DeclaredRule, declared_rules
from scripts.schema_to_field_semantics import generate

_RULE_KEYS = frozenset(
    {"not_null", "min_length", "array_element_format", "exclude_before", "accepted_values", "pattern", "not_before"}
)


def _columns(table: str) -> dict:
    return generate()["ops_tables"][table]["columns"]


def _expected_value(rule: DeclaredRule):
    if rule.kind == "accepted_values":
        return list(rule.params["values"])
    if rule.kind == "array_element_format":
        return rule.params["pattern"]
    return rule.params["value"]


def test_projects_every_declared_rule_once() -> None:
    columns = _columns("ops_recommendations")
    seen: set[tuple[str, str]] = set()
    for rule in declared_rules("ops_recommendations"):
        spec = columns[rule.column]
        key = (rule.column, rule.kind)
        assert key not in seen
        seen.add(key)
        if rule.exemption is not None:
            assert rule.kind not in spec, key
            assert spec["write_time_exemptions"][rule.kind]["owner"] == rule.exemption["owner"]
            continue
        if rule.kind == "not_null":
            if spec["nullable"] is False:
                assert "not_null" not in spec, key
                assert rule.exclude_before is None
                continue
            assert spec["not_null"] is True
        else:
            assert spec[rule.kind] == _expected_value(rule), key
        if rule.exclude_before is not None:
            assert spec["exclude_before"][rule.kind] == rule.exclude_before, key
        else:
            assert rule.kind not in spec.get("exclude_before", {}), key
    projected = {(c, k) for c, spec in columns.items() for k in _RULE_KEYS & set(spec) if k != "exclude_before"}
    expected = {(r.column, r.kind) for r in declared_rules("ops_recommendations") if r.exemption is None} - {
        (r.column, "not_null") for r in declared_rules("ops_recommendations") if columns[r.column]["nullable"] is False
    }
    assert projected == expected
    assert columns["title"]["nullable"] is False and columns["title"]["min_length"] == 10


def test_exemptions_and_unknown_kinds() -> None:
    columns = _columns("ops_recommendations")
    assert set(columns["acceptance"]["write_time_exemptions"]) == {"acceptance_lint"}
    assert set(columns["dependencies"]["write_time_exemptions"]) == {"array_element_reference"}
    assert columns["dependencies"]["array_element_format"] == "^rec-[0-9]+$"
    base = {"id": {"role": "input", "sql_type": "VARCHAR", "nullable": False}}
    unknown = DeclaredRule("t", "id", "mystery", {"value": 1})
    with patch.object(projection, "declared_rules", return_value=(unknown,)):
        with pytest.raises(ValueError, match="unknown rule kind 'mystery'"):
            projection.project_row_rules("t", base)
    dated_not_null = DeclaredRule("t", "id", "not_null", {}, "2026-09-01")
    with patch.object(projection, "declared_rules", return_value=(dated_not_null,)):
        with pytest.raises(ValueError, match="dated not_null on a nullable:false column"):
            projection.project_row_rules("t", base)
    ghost = DeclaredRule("t", "ghost", "not_null", {})
    with patch.object(projection, "declared_rules", return_value=(ghost,)):
        with pytest.raises(ValueError, match="names a column the projection does not carry"):
            projection.project_row_rules("t", base)
    before = copy.deepcopy(base)
    with patch.object(projection, "declared_rules", return_value=()):
        projection.project_row_rules("t", base)
    assert base == before


def test_other_tables_project_no_rule_key() -> None:
    for table in ("ops_decisions", "ops_entity_counters"):
        for name, spec in _columns(table).items():
            assert not (_RULE_KEYS & set(spec)) and "write_time_exemptions" not in spec, (table, name)


def _strip_rule_keys(doc: dict) -> dict:
    out = copy.deepcopy(doc)
    for entry in out["ops_tables"].values():
        for spec in (entry.get("columns") or {}).values():
            for key in _RULE_KEYS | {"write_time_exemptions"}:
                spec.pop(key, None)
    return out


def test_rule_projection_touches_only_rule_keys() -> None:
    with patch.object(projection, "project_row_rules", side_effect=lambda table_id, columns: columns):
        plain = generate()
    real = generate()
    assert real != plain
    assert _strip_rule_keys(real) == _strip_rule_keys(plain)
    changed = [t for t in real["ops_tables"] if real["ops_tables"][t] != plain["ops_tables"][t]]
    assert changed == ["ops_recommendations"]
