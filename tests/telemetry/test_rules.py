"""Mirror test for src/telemetry/rules.py: every rule kind rejects with table, rule and column; exemptions; the module
holds no table literal. Stdlib only (fast tier)."""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.telemetry.rules as rules_module
from src.telemetry.rules import RowRuleError, RowRules, RuleProjectionError, check_row

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
CREATED = T0 + timedelta(seconds=10)
TABLE = "demo"

COLUMNS = {
    "kind": {"role": "input", "sql_type": "VARCHAR", "nullable": False, "accepted_values": ["a", "b"]},
    "mode": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
    "needed": {"role": "input", "sql_type": "VARCHAR", "nullable": True, "required_when": {"kind": ["a"], "mode": ["x"]}},
    "digest": {"role": "input", "sql_type": "VARCHAR", "nullable": True, "pattern": "^[0-9a-f]{4}$"},
    "started": {"role": "input", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": True},
    "happened": {
        "role": "input",
        "sql_type": "TIMESTAMP WITH TIME ZONE",
        "nullable": True,
        "not_before": "started",
        "max_after_write_seconds": 300,
    },
    "total": {"role": "input", "sql_type": "BIGINT", "nullable": True},
    "part": {
        "role": "input",
        "sql_type": "BIGINT",
        "nullable": True,
        "at_most": "total",
        "null_or_zero_when": {"mode": ["none"]},
    },
    "inline": {"role": "input", "sql_type": "VARCHAR", "nullable": True, "representation_of": ["sha", "size"]},
    "uri": {"role": "input", "sql_type": "VARCHAR", "nullable": True, "representation_of": ["sha", "size"]},
    "why": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
    "sha": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
    "size": {"role": "input", "sql_type": "BIGINT", "nullable": True},
}
TABLE_RULES = {
    "exactly_one_of": [["inline", "uri", "why"]],
    "payload": {
        "inline": "inline",
        "uri": "uri",
        "sha": "sha",
        "size": "size",
        "threshold": 10,
        "cap": 100,
        "integrity": True,
    },
}


def make_rules(**table_overrides) -> RowRules:
    return RowRules.from_projection(COLUMNS, {**TABLE_RULES, **table_overrides})


def good(**over):
    row = {
        "kind": "b", "started": T0, "happened": T0 + timedelta(seconds=1), "total": 5, "part": 3, "mode": "y",
        "inline": "hello", "sha": hashlib.sha256(b"hello").hexdigest(), "size": 5,
    }  # fmt: skip
    row.update(over)
    return row


def violation(row, rules=None, created=CREATED) -> RowRuleError:
    with pytest.raises(RowRuleError) as raised:
        check_row(TABLE, row, rules or make_rules(), created)
    return raised.value


def test_a_conforming_row_passes() -> None:
    check_row(TABLE, good(), make_rules(), CREATED)


def test_each_rule_kind_rejects_with_table_rule_and_column() -> None:
    cases = [
        ({"kind": None}, "not_null", "kind"),
        ({"kind": "z"}, "accepted_values", "kind"),
        ({"kind": "a", "mode": "x"}, "required_when", "needed"),
        ({"digest": "XYZ1"}, "pattern", "digest"),
        ({"happened": T0 - timedelta(seconds=1)}, "not_before", "happened"),
        ({"part": 6}, "at_most", "part"),
        ({"mode": "none", "part": 1}, "null_or_zero_when", "part"),
        ({"happened": CREATED + timedelta(seconds=301)}, "max_after_write_seconds", "happened"),
        ({"inline": None, "sha": None}, "exactly_one_of", "inline"),
    ]
    for override, rule, column in cases:
        error = violation(good(**override))
        assert (error.table, error.rule, error.column) == (TABLE, rule, column), override
        assert TABLE in str(error) and rule in str(error) and column in str(error)


def test_error_message_never_carries_a_value() -> None:
    leaked = "unexpected-value-xyz"
    error = violation(good(kind=leaked))
    assert leaked not in str(error) and error.rule == "accepted_values"


def test_required_when_and_exactly_one_of_with_omission() -> None:
    check_row(TABLE, good(kind="a", mode="y"), make_rules(), CREATED)
    check_row(TABLE, good(kind="a", mode="x", needed="present"), make_rules(), CREATED)
    check_row(TABLE, good(inline=None, why="oversize", sha="0" * 64, size=999999), make_rules(), CREATED)
    two = violation(good(uri="k/1", size=50))
    assert two.rule == "exactly_one_of"
    none = violation(good(inline=None, why=None))
    assert none.rule == "exactly_one_of"


def test_ordering_and_write_time_skew_are_monotone_on_retry() -> None:
    rules = make_rules()
    edge = good(happened=CREATED + timedelta(seconds=300))
    check_row(TABLE, edge, rules, CREATED)
    assert violation(good(happened=CREATED + timedelta(seconds=300, milliseconds=1))).rule == "max_after_write_seconds"
    for later in (CREATED + timedelta(seconds=1), CREATED + timedelta(hours=3)):
        check_row(TABLE, edge, rules, later)
    check_row(TABLE, good(happened=T0), rules, CREATED)
    check_row(TABLE, good(happened=None, started=None), rules, CREATED)


def test_content_integrity_threshold_legs_and_cap() -> None:
    rules = make_rules()
    assert violation(good(sha="0" * 64)).rule == "integrity"
    assert violation(good(size=6)).rule == "integrity"
    assert violation(good(inline="hello world!", sha=hashlib.sha256(b"hello world!").hexdigest(), size=12)).rule == (
        "inline_within_threshold"
    )
    assert violation(good(inline=None, uri="t/p/s/x", size=10)).rule == "uri_above_threshold"
    check_row(TABLE, good(inline=None, uri="t/p/s/x", size=11), rules, CREATED)
    check_row(TABLE, good(inline=None, uri="t/p/s/x", size=100), rules, CREATED)
    assert violation(good(inline=None, uri="t/p/s/x", size=101)).rule == "within_cap"
    check_row(TABLE, good(inline=None, why="oversize", sha="f" * 64, size=5_000), rules, CREATED)
    check_row(TABLE, good(size=None), make_rules(payload={**TABLE_RULES["payload"], "integrity": False}), CREATED)
    uncapped = make_rules(payload={**TABLE_RULES["payload"], "cap": None})
    check_row(TABLE, good(inline=None, uri="t/p/s/x", size=10**9), uncapped, CREATED)
    plain = make_rules(payload={**TABLE_RULES["payload"], "integrity": False})
    check_row(TABLE, good(sha="any", size=5), plain, CREATED)
    assert violation(good(inline="x" * 101, sha="any", size=101), plain).rule == "inline_within_threshold"


def test_declared_exemption_is_honoured_and_named() -> None:
    long_text = "x" * 40
    row = good(inline=long_text, sha=hashlib.sha256(long_text.encode()).hexdigest(), size=40)
    assert violation(row).rule == "inline_within_threshold"
    exempt = {k: dict(v) for k, v in COLUMNS.items()}
    exempt["inline"]["write_time_exemptions"] = {"inline_within_threshold": {"reason": "route lands later", "owner": "rec-1"}}
    rules = RowRules.from_projection(exempt, TABLE_RULES)
    assert rules.exemptions == {"inline_within_threshold": ("route lands later", "rec-1")}
    check_row(TABLE, row, rules, CREATED)
    assert violation(good(sha="0" * 64), rules).rule == "integrity"
    over = good(inline="y" * 200, sha=hashlib.sha256(b"y" * 200).hexdigest(), size=200)
    assert violation(over, rules).rule == "within_cap"
    every = {k: dict(v) for k, v in COLUMNS.items()}
    every["inline"]["write_time_exemptions"] = {
        leg: {"reason": "r", "owner": "o"} for leg in ("inline_within_threshold", "within_cap", "integrity")
    }
    every["uri"]["write_time_exemptions"] = {"uri_above_threshold": {"reason": "r", "owner": "o"}}
    open_rules = RowRules.from_projection(every, TABLE_RULES)
    check_row(TABLE, good(sha="0" * 64, size=1), open_rules, CREATED)
    check_row(TABLE, good(inline=None, uri="k", size=1), open_rules, CREATED)
    check_row(TABLE, good(inline="z" * 200, size=200), open_rules, CREATED)
    check_row(TABLE, good(inline=None, uri="k", size=500), open_rules, CREATED)


def test_column_bound_and_conditional_zero() -> None:
    check_row(TABLE, good(part=5, total=5), make_rules(), CREATED)
    check_row(TABLE, good(part=9, total=None), make_rules(), CREATED)
    check_row(TABLE, good(part=None, total=1), make_rules(), CREATED)
    assert violation(good(part=6, total=5)).rule == "at_most"
    check_row(TABLE, good(mode="none", part=None), make_rules(), CREATED)
    check_row(TABLE, good(mode="none", part=0), make_rules(), CREATED)
    check_row(TABLE, good(mode="y", part=4), make_rules(), CREATED)
    assert violation(good(mode="none", part=2)).rule == "null_or_zero_when"


def test_from_projection_fails_closed_on_malformed_input() -> None:
    def project(columns=None, table_rules=None):
        return RowRules.from_projection(columns or COLUMNS, table_rules)

    with pytest.raises(RuleProjectionError, match="unknown table rule"):
        project(table_rules={"nonsense": 1})
    with pytest.raises(RuleProjectionError, match="unknown rule key"):
        project({"c": {"role": "input", "sql_type": "VARCHAR", "nullable": True, "mystery": 1}})
    for bad in (-1, "300", 1.5):
        with pytest.raises(RuleProjectionError, match="max_after_write_seconds"):
            project({"c": {"nullable": True, "max_after_write_seconds": bad}})
    with pytest.raises(RuleProjectionError, match="unknown or duplicate leg"):
        project({"c": {"nullable": True, "write_time_exemptions": {"made_up": {"reason": "r", "owner": "o"}}}})
    with pytest.raises(RuleProjectionError, match="needs a reason and an owner"):
        project({"c": {"nullable": True, "write_time_exemptions": {"integrity": {"reason": "r"}}}})
    both = {
        "a": {"nullable": True, "write_time_exemptions": {"integrity": {"reason": "r", "owner": "o"}}},
        "b": {"nullable": True, "write_time_exemptions": {"integrity": {"reason": "r", "owner": "o"}}},
    }
    with pytest.raises(RuleProjectionError, match="unknown or duplicate leg"):
        project(both)
    with pytest.raises(RuleProjectionError, match="exactly_one_of names unknown"):
        project(table_rules={"exactly_one_of": [["kind", "ghost"]]})
    for bad_condition in ({}, "kind", {"kind": []}, {"kind": "a"}):
        with pytest.raises(RuleProjectionError, match="required_when"):
            project({"c": {"nullable": True, "required_when": bad_condition}})
    with pytest.raises(RuleProjectionError, match="pattern"):
        project({"c": {"nullable": True, "pattern": "("}})
    with pytest.raises(RuleProjectionError, match="pattern"):
        project({"c": {"nullable": True, "pattern": 5}})
    with pytest.raises(RuleProjectionError, match="not_before"):
        project({"c": {"nullable": True, "not_before": "ghost"}})
    with pytest.raises(RuleProjectionError, match="at_most"):
        project({"c": {"nullable": True, "at_most": 3}})
    base = TABLE_RULES["payload"]
    with pytest.raises(RuleProjectionError, match="unknown content rule key"):
        project(table_rules={"payload": {**base, "extra": 1}})
    with pytest.raises(RuleProjectionError, match="names an unknown column"):
        project(table_rules={"payload": {**base, "sha": "ghost"}})
    with pytest.raises(RuleProjectionError, match="integers"):
        project(table_rules={"payload": {**base, "threshold": "10"}})
    with pytest.raises(RuleProjectionError, match="integers"):
        project(table_rules={"payload": {**base, "cap": 1.5}})
    with pytest.raises(RuleProjectionError, match="below the threshold"):
        project(table_rules={"payload": {**base, "cap": 5}})
    assert project().content is None or project(table_rules={}).content is None
    assert project().representation_only == {"inline", "uri"}


def test_rules_module_holds_no_table_literal() -> None:
    from tests.fixtures.turn_capture_ducklake import load_specs

    specs = load_specs()
    names = set()
    for spec in specs.values():
        names |= set(spec.columns) | {spec.table}
    distinctive_values = {
        "telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents", "tool_call",
        "model_call", "claude_code", "tool_output", "tool_result", "fixed_non_rollover_allowance", "summarized",
        "omitted", "oversize",
    }  # fmt: skip
    tree = ast.parse(Path(rules_module.__file__).read_text(encoding="utf-8"))
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    hits = literals & (names | distinctive_values)
    assert not hits, hits
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m and m.startswith("src.telemetry") for m in modules) and "gate" not in imported
