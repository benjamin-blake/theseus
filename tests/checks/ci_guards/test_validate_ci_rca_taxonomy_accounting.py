"""Check-accounting declaration tests for validate_ci_rca_taxonomy() (Decision 170)."""

import importlib
from pathlib import Path

import pytest
import yaml

import scripts.checks.ci_guards.validate_ci_rca_taxonomy as subject
from scripts.checks import registry, validation_result
from scripts.checks.ci_guards.validate_ci_rca_taxonomy import validate_ci_rca_taxonomy

_REPO_ROOT = Path(__file__).parents[3]
_UNIT = "taxonomy_subjects"


def _synthetic(workflows: list[str], checks: list[str], categories: list[str]) -> dict:
    return {
        "schema_version": 1,
        "taxonomy_version": 1,
        "failure_categories": [*categories, "unknown", "evidence_insufficient"],
        "function_to_category": dict.fromkeys(checks, categories[0]),
        "step_name_to_category": {f"step_{c}": c for c in categories},
        "log_pattern_to_category": [],
        "workflows": {w: {"tier": "CI"} for w in workflows},
    }


def _declare(
    monkeypatch: pytest.MonkeyPatch, taxonomy: dict, workflows: list[str], checks: list[str]
) -> tuple[list[str], registry._Declaration | None]:
    monkeypatch.setattr(subject.registry, "all_checks", lambda: dict.fromkeys(checks))
    monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: list(workflows))
    monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: taxonomy)
    registry.pop_declaration()
    failed: list[str] = []
    validate_ci_rca_taxonomy(failed)
    return failed, registry.pop_declaration()


class TestCiRcaTaxonomyAccountingDeclaration:
    """The evaluator declares how many taxonomy subjects it checked -- every workflow name, every
    registered check and every declared failure category -- so a run is recorded enforced with a
    count that tracks the three rosters instead of undeclared."""

    def test_real_tree_declares_every_taxonomy_subject(self) -> None:
        workflow_names = 0
        for path in (_REPO_ROOT / ".github" / "workflows").glob("*.yml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            workflow_names += isinstance(data, dict) and "name" in data
        registered = sum(
            len(importlib.import_module(f"scripts.checks.{path.parent.name}._manifest").ENTRIES)
            for path in (_REPO_ROOT / "scripts" / "checks").glob("*/_manifest.py")
        )
        taxonomy = yaml.safe_load((_REPO_ROOT / "config" / "ci_rca_taxonomy.yaml").read_text(encoding="utf-8"))
        categories = len(set(taxonomy["failure_categories"]))
        expected = workflow_names + registered + categories

        registry.pop_declaration()
        failed: list[str] = []
        validate_ci_rca_taxonomy(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)

    def test_declared_count_sums_all_three_rosters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        base_tax = _synthetic(["CI"], ["validate_a"], ["lint"])
        failed, base = _declare(monkeypatch, base_tax, ["CI"], ["validate_a"])
        grown_tax = _synthetic(["CI", "Deploy"], ["validate_a", "validate_b", "validate_c"], ["lint", "typing"])
        grown_failed, grown = _declare(monkeypatch, grown_tax, ["CI", "Deploy"], ["validate_a", "validate_b", "validate_c"])
        assert failed == [] and grown_failed == []
        assert base is not None and grown is not None
        assert (base.count, grown.count) == (1 + 1 + 3, 2 + 3 + 4)

    def test_duplicate_failure_categories_counted_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        taxonomy = _synthetic(["CI"], ["validate_a"], ["lint"])
        taxonomy["failure_categories"].append("lint")
        failed, declaration = _declare(monkeypatch, taxonomy, ["CI"], ["validate_a"])
        assert failed == []
        assert declaration is not None and declaration.count == 1 + 1 + 3

    @pytest.mark.parametrize(
        ("mutate", "workflows", "fragment"),
        [
            (lambda t: None, ["CI", "Unmapped"], "absent from workflows"),
            (lambda t: t["function_to_category"].clear(), ["CI"], "absent from function_to_category"),
            (lambda t: t.pop("failure_categories"), ["CI"], "missing top-level 'failure_categories:'"),
            (lambda t: t["failure_categories"].append("orphan"), ["CI"], "absent from all classifier maps"),
        ],
    )
    def test_failing_runs_record_failed(self, monkeypatch: pytest.MonkeyPatch, mutate, workflows, fragment) -> None:
        taxonomy = _synthetic(["CI"], ["validate_a"], ["lint"])
        mutate(taxonomy)
        monkeypatch.setattr(subject.registry, "all_checks", lambda: {"validate_a": None})
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: list(workflows))
        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: taxonomy)
        validation_result._OUTCOMES.clear()
        failed: list[str] = []
        try:
            validation_result.dispatch_recording("validate_ci_rca_taxonomy", failed, validate_ci_rca_taxonomy)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert any(fragment in f for f in failed), failed
        assert outcome.status == "failed"

    def test_real_tree_is_recorded_enforced(self) -> None:
        validation_result._OUTCOMES.clear()
        try:
            validation_result.dispatch_recording("validate_ci_rca_taxonomy", [], validate_ci_rca_taxonomy)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert (outcome.status, outcome.examined_unit) == ("enforced", _UNIT)
        assert outcome.examined_count is not None and outcome.examined_count > 0
