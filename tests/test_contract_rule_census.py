"""Mirror test for scripts/contract_rule_census.py (rec-4158 plan A), duckdb-free: rule compilation, the exempt list,
the exit-code mapping from a stubbed DQ harness, and the whitespace class."""

from __future__ import annotations

import re

import pytest

import scripts.contract_rule_census as census
from scripts.contract_rules import DeclaredRule
from scripts.data_quality_models import CheckResult, RunResult

_EXEMPT = {"class": "cross_row", "reason": "r", "owner": "rec-1"}


def _rule(
    kind: str, params: dict | None = None, *, column: str = "c", gate: str | None = None, exemption=None
) -> DeclaredRule:
    return DeclaredRule("ops_recommendations", column, kind, params or {}, gate, exemption)


def _condition(rule: DeclaredRule) -> str:
    return census.compile_rule(rule).sql


def test_each_rule_kind_compiles() -> None:
    assert census.violation_condition(_rule("not_null")) == "c IS NULL"
    sql = _condition(_rule("not_null", gate="2026-05-01"))
    assert sql.endswith("WHERE (c IS NULL) AND created_timestamp >= DATE('2026-05-01')")
    assert sql.startswith("SELECT COUNT(*) AS violation FROM {tbl} WHERE")
    values = census.violation_condition(_rule("accepted_values", {"values": ["a", "b'c"]}))
    assert values == "c IS NOT NULL AND c NOT IN ('a', 'b''c')"
    length = census.violation_condition(_rule("min_length", {"value": 10}))
    assert length.startswith("c IS NOT NULL AND LENGTH(regexp_replace(c, '^[") and length.endswith("< 10")
    assert census.WHITESPACE_CLASS in length
    assert census.violation_condition(_rule("pattern", {"value": "^a'b$"})) == (
        "c IS NOT NULL AND NOT regexp_full_match(c, '^a''b$')"
    )
    array = census.violation_condition(_rule("array_element_format", {"pattern": "^r$"}))
    assert array == ("c IS NOT NULL AND len(list_filter(c, x -> x IS NULL OR NOT regexp_full_match(x, '^r$'))) > 0")
    assert census.violation_condition(_rule("not_before", {"value": "created_timestamp"})) == (
        "c IS NOT NULL AND created_timestamp IS NOT NULL AND c < created_timestamp"
    )
    check = census.compile_rule(_rule("min_length", {"value": 3}, gate="2026-09-01"))
    assert (check.severity, check.enforced, check.exclude_before, check.test_type) == (
        "error",
        True,
        "2026-09-01",
        "min_length",
    )
    with pytest.raises(ValueError, match="no census predicate and no exemption"):
        census.violation_condition(_rule("acceptance_lint", {"require_discrimination": True}))


def test_exempt_rules_are_listed_not_compiled(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    rules = (_rule("not_null"), _rule("array_element_reference", column="d", exemption=_EXEMPT))
    monkeypatch.setattr(census, "declared_rules", lambda table: rules)
    plan = census.build_plan("ops_recommendations")
    assert [c.test_type for c in plan.checks] == ["not_null"] and plan.declared_non_exempt == 1
    assert [r.kind for r in plan.exempt] == ["array_element_reference"]
    code, lines, rows = census.census(("ops_recommendations",), dry_run=True)
    assert code == 0 and rows == []
    assert lines[0] == "EXEMPT  ops_recommendations.d array_element_reference class=cross_row"
    assert sum("array_element_reference" in line for line in lines) == 1
    assert census.main(["--table", "ops_recommendations", "--dry-run", "--json"]) == 0


def _stub(monkeypatch: pytest.MonkeyPatch, verdicts: list[tuple[str, int]], *, rules=None, drop: int = 0) -> list:
    rules = rules if rules is not None else tuple(_rule("not_null", column=f"c{i}") for i in range(len(verdicts)))
    monkeypatch.setattr(census, "declared_rules", lambda table: rules)

    def fake_run(checks, **_kw):
        results = [CheckResult(check=c, verdict=v, violation_count=n) for c, (v, n) in zip(checks, verdicts)]
        return RunResult(results=results[: len(results) - drop] if drop else results)

    monkeypatch.setattr(census, "run_checks", fake_run)
    return list(rules)


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ([("PASS", 0), ("PASS", 0)], 0),
        ([("PASS", 0), ("FAIL", 3)], 1),
        ([("PASS", 0), ("WARN", 2)], 1),
        ([("UNENFORCED_FAIL", 1)], 1),
        ([("PASS", 0), ("SKIP", 0)], 2),
        ([("PASS", 0), ("UNAVAILABLE", 0)], 2),
        ([("ERROR", 0)], 2),
    ],
)
def test_exit_codes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], verdicts, expected) -> None:
    _stub(monkeypatch, verdicts)
    assert census.main(["--table", "ops_recommendations"]) == expected
    out = capsys.readouterr().out
    assert "SUMMARY compiled=" in out
    assert f"violators={verdicts[-1][1]}" in out


def test_exit_two_on_an_empty_set_or_a_count_mismatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, [], rules=())
    assert census.main(["--table", "ops_recommendations"]) == 2
    _stub(monkeypatch, [("PASS", 0), ("PASS", 0)], drop=1)
    assert census.main(["--table", "ops_recommendations"]) == 2
    monkeypatch.setattr(census, "declared_rules", lambda table: (_rule("acceptance_lint"),))
    assert census.main(["--table", "ops_decisions"]) == 2
    assert "census could not compile" in capsys.readouterr().err


def test_json_output_lists_each_rule(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _stub(monkeypatch, [("PASS", 0)])
    assert census.main(["--table", "ops_recommendations", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"rule": "not_null"' in out and '"violators": 0' in out


def test_whitespace_class_equals_isspace() -> None:
    parsed: set[int] = set()
    for lo, hi in re.findall(r"\\x\{([0-9a-f]+)\}(?:-\\x\{([0-9a-f]+)\})?", census.WHITESPACE_CLASS):
        parsed.update(range(int(lo, 16), int(hi or lo, 16) + 1))
    assert parsed == {i for i in range(0x110000) if chr(i).isspace()}
    assert re.sub(r"\\x\{[0-9a-f]+\}(-\\x\{[0-9a-f]+\})?", "", census.WHITESPACE_CLASS) == ""
