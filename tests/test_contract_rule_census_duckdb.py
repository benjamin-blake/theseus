"""Census SQL predicates agree row-for-row with the shipped write-time engine on a real DuckDB engine (rec-4158 plan B).

The Python reference is src/row_rules/rules.check_row over RowRules built by project_row_rules for the rule under test,
run as an unchanged older row (prior is the row itself), so the only date logic exercised is the UTC-midnight gate the
census writes as created_timestamp >= DATE(...)."""

from __future__ import annotations

import dataclasses
import itertools
from datetime import datetime
from unittest.mock import patch

import pytest

duckdb = pytest.importorskip("duckdb")

import scripts.contract_rule_census as census  # noqa: E402
import scripts.field_semantics_rule_projection as projection  # noqa: E402
from scripts.contract_rules import DeclaredRule, declared_rules  # noqa: E402
from scripts.ops_portal.write_validators import _validate_file_path  # noqa: E402
from src.row_rules.rules import RowRuleError, RowRules, check_row  # noqa: E402

_TEXT = [
    None,
    "",
    " ",
    "abc",
    "  abc  ",
    "\t\tabcdefghij\t\t",
    "\u00a0\u00a0abc\u00a0",
    "\u3000" * 12,
    "abcdefghij",
    " abcdefghi ",
    "\x85ab\x85",
    "\x1cabcdefghij\x1f",
    "ab\u200bcdefghij",
    "ab\u2003",
    "x" * 80,
    "\u2003" + "y" * 79,
]
_PATHS = [None, "", "a/b.py", "/abs/p", "C:/x", "C:\\x", "a\\b", "c:", "C:x", "1:/x", "ab", ".", "..\\a", "z:\\", "Q:"]
_ARRAYS = [None, [], ["rec-1"], ["rec-1", "rec-22"], ["rec-1", None], [None], ["rec-x"], ["rec-1", ""], ["REC-1"]]
_STAMPS = [
    ("2026-01-01 00:00:00+00", "2026-01-02 00:00:00+00"),
    ("2026-09-01 00:00:00+00", "2026-08-31 00:00:00+00"),
    ("2026-09-10 00:00:00+00", "2026-09-10 00:00:00+00"),
    (None, "2026-09-10 00:00:00+00"),
    ("2026-09-10 00:00:00+00", None),
]


def _rule(kind: str, column: str, params: dict, gate: str | None = None) -> DeclaredRule:
    return DeclaredRule("ops_recommendations", column, kind, params, gate, None)


def _contract_rule(column: str, kind: str) -> DeclaredRule:
    return next(r for r in declared_rules("ops_recommendations") if r.column == column and r.kind == kind)


@pytest.fixture()
def conn():
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE t (n INTEGER, txt VARCHAR, path VARCHAR, arr VARCHAR[], "
        "created_timestamp TIMESTAMPTZ, ts_a TIMESTAMPTZ, ts_b TIMESTAMPTZ)"
    )
    n = 0
    rows = []
    for i in range(max(len(_TEXT), len(_PATHS), len(_ARRAYS), len(_STAMPS))):
        a, b = _STAMPS[i % len(_STAMPS)]
        created = ("2026-04-01 00:00:00+00", "2026-05-01 00:00:00+00", "2026-09-07 00:00:00+00")[i % 3]
        rows.append((n, _TEXT[i % len(_TEXT)], _PATHS[i % len(_PATHS)], _ARRAYS[i % len(_ARRAYS)], created, a, b))
        n += 1
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    yield con, rows
    con.close()


def _violating_ids(con, rule: DeclaredRule) -> set[int]:
    return {r[0] for r in con.execute(f"SELECT n FROM t WHERE ({census.violation_condition(rule)})").fetchall()}


def _gated_count(con, rule: DeclaredRule) -> int:
    sql = census.compile_rule(rule).sql.replace("{tbl}", "t")
    return con.execute(sql).fetchone()[0]


def _stamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _engine_ids(rows, rule: DeclaredRule) -> set[int]:
    """The ids the shipped engine rejects for *rule*, each row evaluated as an unchanged older row."""
    names = ("txt", "path", "arr", "ts_a", "ts_b")
    spec = {name: {"nullable": True} for name in names}
    with patch.object(projection, "declared_rules", return_value=(rule,)):
        rules = RowRules.from_projection(projection.project_row_rules("t", spec))
    rejected: set[int] = set()
    for n, txt, path, arr, created, ts_a, ts_b in rows:
        row = {"txt": txt, "path": path, "arr": arr, "ts_a": _stamp(ts_a), "ts_b": _stamp(ts_b)}
        try:
            check_row("t", row, rules, _stamp(created), prior=row)
        except RowRuleError:
            rejected.add(n)
    return rejected


def test_not_null_accepted_values_and_gate(conn) -> None:
    con, rows = conn
    rule = _rule("not_null", "txt", {})
    assert _violating_ids(con, rule) == _engine_ids(rows, rule)
    gated = _rule("not_null", "txt", {}, "2026-05-01")
    assert _gated_count(con, gated) == len(_engine_ids(rows, gated))
    values = _rule("accepted_values", "txt", {"values": ["abc", "it's"]})
    assert _violating_ids(con, values) == _engine_ids(rows, values)


@pytest.mark.parametrize("minimum", [1, 10, 80])
def test_min_length_agrees_with_str_strip_including_unicode_whitespace(conn, minimum: int) -> None:
    con, rows = conn
    rule = _rule("min_length", "txt", {"value": minimum})
    assert _violating_ids(con, rule) == _engine_ids(rows, rule)
    assert _violating_ids(con, rule) or minimum == 1
    dated = dataclasses.replace(rule, exclude_before="2026-05-01")
    assert _gated_count(con, dated) == len(_engine_ids(rows, dated))


def test_pattern_and_the_portal_file_path_validator_agree(conn) -> None:
    con, rows = conn
    contract_rule = _contract_rule("file", "pattern")
    pattern = contract_rule.params["value"]
    rule = dataclasses.replace(contract_rule, column="path", exclude_before=None)
    assert _violating_ids(con, rule) == _engine_ids(rows, rule)

    def portal_rejects(path: str) -> bool:
        try:
            _validate_file_path(path)
        except ValueError:
            return True
        return False

    con.execute("CREATE TABLE p (n INTEGER, path VARCHAR)")
    alphabet = ["a", "Z", "1", "/", "\\", ":", "."]
    corpus = ["".join(chars) for length in range(1, 5) for chars in itertools.product(alphabet, repeat=length)]
    con.executemany("INSERT INTO p VALUES (?, ?)", list(enumerate(corpus)))
    flagged = {
        corpus[i]
        for (i,) in con.execute(
            f"SELECT n FROM p WHERE path IS NOT NULL AND NOT regexp_full_match(path, {census._lit(pattern)})"
        ).fetchall()
    }
    assert flagged == {path for path in corpus if portal_rejects(path)}


def test_array_element_format_counts_null_elements_and_empty_lists(conn) -> None:
    con, rows = conn
    for pattern in ("^rec-[0-9]+$", "^[a-z][a-z0-9-]*$"):
        rule = _rule("array_element_format", "arr", {"pattern": pattern})
        assert _violating_ids(con, rule) == _engine_ids(rows, rule)
        dated = dataclasses.replace(rule, exclude_before="2026-09-08")
        assert _gated_count(con, dated) == len(_engine_ids(rows, dated))
    flagged = _violating_ids(con, _rule("array_element_format", "arr", {"pattern": "^rec-[0-9]+$"}))
    assert {i for i, r in enumerate(rows) if r[3] == []}.isdisjoint(flagged)
    assert {r[0] for r in rows if r[3] and None in r[3]} <= flagged


def test_not_before_orders_two_timestamps(conn) -> None:
    con, rows = conn
    rule = _rule("not_before", "ts_a", {"value": "ts_b"})
    assert _violating_ids(con, rule) == _engine_ids(rows, rule)
    assert _violating_ids(con, rule)
