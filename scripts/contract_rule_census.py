"""Live census of the ops contracts' declared rules against the warehouse (rec-4158 plan A).

Compiles every non-exempt rule scripts.contract_rules declares for ops_recommendations and ops_decisions into a DQ
Check -- the same FROM form and created_timestamp >= DATE gate scripts/data_quality_compile.py's expression branch
emits -- and runs them through the DQ harness (scripts.data_quality_execute.run_checks; no new reader client). Read
only. Exit 0 only on a complete all-PASS run with zero violators; exit 1 when any rule has violators; exit 2 for
anything that is not a clean answer (SKIP, UNAVAILABLE, ERROR, an empty compiled set, a count mismatch) -- never a
silent pass (Decision 55). A violator under a declared date is a STOP back to /plan (Decision 210 cl.4).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from scripts.contract_rules import DeclaredRule, declared_rules
from scripts.data_quality_compile import to_ducklake_sql
from scripts.data_quality_execute import run_checks
from scripts.data_quality_models import Check

DATABASE = "agent_platform"
TABLES = ("ops_recommendations", "ops_decisions")
EXIT_OK, EXIT_VIOLATIONS, EXIT_UNCLEAN = 0, 1, 2


def _whitespace_class() -> str:
    """The RE2 character-class body equal to exactly the characters str.isspace() accepts."""
    codes = [i for i in range(0x110000) if chr(i).isspace()]
    parts: list[str] = []
    start = prev = codes[0]
    for code in codes[1:] + [None]:  # type: ignore[list-item]
        if code is not None and code == prev + 1:
            prev = code
            continue
        parts.append(f"\\x{{{start:x}}}" if start == prev else f"\\x{{{start:x}}}-\\x{{{prev:x}}}")
        if code is not None:
            start = prev = code
    return "".join(parts)


WHITESPACE_CLASS = _whitespace_class()


def _lit(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _strip_len(column: str) -> str:
    ws = WHITESPACE_CLASS
    return f"LENGTH(regexp_replace({column}, {_lit(f'^[{ws}]+|[{ws}]+$')}, '', 'g'))"


def _pattern(rule: DeclaredRule) -> str:
    return rule.params["pattern" if rule.kind == "array_element_format" else "value"]


def violation_condition(rule: DeclaredRule) -> str:
    """The SQL boolean that is TRUE for a row that violates the rule (a NULL value is not_null's concern)."""
    col = rule.column
    if rule.kind == "not_null":
        return f"{col} IS NULL"
    if rule.kind == "accepted_values":
        values = ", ".join(_lit(v) for v in rule.params["values"])
        return f"{col} IS NOT NULL AND {col} NOT IN ({values})"
    if rule.kind == "min_length":
        return f"{col} IS NOT NULL AND {_strip_len(col)} < {int(rule.params['value'])}"
    if rule.kind == "pattern":
        return f"{col} IS NOT NULL AND NOT regexp_full_match({col}, {_lit(_pattern(rule))})"
    if rule.kind == "array_element_format":
        bad = f"x IS NULL OR NOT regexp_full_match(x, {_lit(_pattern(rule))})"
        return f"{col} IS NOT NULL AND len(list_filter({col}, x -> {bad})) > 0"
    if rule.kind == "not_before":
        other = rule.params["value"]
        return f"{col} IS NOT NULL AND {other} IS NOT NULL AND {col} < {other}"
    raise ValueError(f"{rule.table}.{rule.column}: rule kind {rule.kind!r} has no census predicate and no exemption")


def compile_rule(rule: DeclaredRule) -> Check:
    gate = f" AND created_timestamp >= DATE('{rule.exclude_before}')" if rule.exclude_before else ""
    query_table = f"{DATABASE}.{rule.table}_current"
    sql = f"SELECT COUNT(*) AS violation FROM {query_table} WHERE ({violation_condition(rule)}){gate}"
    return Check(
        table=rule.table,
        column=rule.column,
        test_type=rule.kind,
        sql=to_ducklake_sql(sql, rule.table, DATABASE),
        description=f"{rule.table}.{rule.column}: {rule.kind}",
        severity="error",
        enforced=True,
        exclude_before=rule.exclude_before,
    )


@dataclass(frozen=True)
class Plan:
    table: str
    checks: list[Check]
    exempt: list[DeclaredRule]
    declared_non_exempt: int


def build_plan(table: str) -> Plan:
    rules = declared_rules(table)
    exempt = [r for r in rules if r.exemption]
    live = [r for r in rules if not r.exemption]
    return Plan(table, [compile_rule(r) for r in live], exempt, len(live))


def _describe(result: Any) -> dict[str, Any]:
    check = result.check
    return {
        "table": check.table,
        "column": check.column,
        "rule": check.test_type,
        "gate": check.exclude_before,
        "verdict": result.verdict,
        "violators": result.violation_count,
    }


def census(tables: tuple[str, ...], *, dry_run: bool = False) -> tuple[int, list[str], list[dict[str, Any]]]:
    plans = [build_plan(t) for t in tables]
    lines: list[str] = []
    rows: list[dict[str, Any]] = []
    for plan in plans:
        for rule in plan.exempt:
            lines.append(f"EXEMPT  {rule.table}.{rule.column} {rule.kind} class={rule.exemption['class']}")
    if dry_run:
        for plan in plans:
            lines.extend(f"-- {c.table}.{c.column} {c.test_type}\n{c.sql}" for c in plan.checks)
        return EXIT_OK, lines, rows
    all_checks = [c for p in plans for c in p.checks]
    run = run_checks(all_checks)
    results = list(run.results)
    rows = [_describe(r) for r in results]
    for r in results:
        lines.append(f"{r.verdict:<8}{r.check.table}.{r.check.column} {r.check.test_type} violators={r.violation_count}")
    violators = sum(1 for r in results if r.violation_count > 0)
    unclean = [r for r in results if r.verdict != "PASS" and r.violation_count == 0]
    mismatch = len(results) != len(all_checks) or any(p.declared_non_exempt != len(p.checks) or not p.checks for p in plans)
    summary = (
        f"SUMMARY compiled={len(all_checks)} declared={sum(p.declared_non_exempt for p in plans)} "
        f"exempt={sum(len(p.exempt) for p in plans)} rules_with_violators={violators} unclean={len(unclean)}"
    )
    lines.append(summary)
    if violators:
        return EXIT_VIOLATIONS, lines, rows
    if unclean or mismatch or not results:
        return EXIT_UNCLEAN, lines, rows
    return EXIT_OK, lines, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--table", choices=TABLES, help="census one table (default: both)")
    parser.add_argument("--json", action="store_true", help="print the per-rule results as JSON")
    parser.add_argument("--dry-run", action="store_true", help="print the compiled SQL; no reader is contacted")
    args = parser.parse_args(argv)
    tables = (args.table,) if args.table else TABLES
    try:
        code, lines, rows = census(tables, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"census could not compile: {exc}", file=sys.stderr)
        return EXIT_UNCLEAN
    print("\n".join(lines))
    if args.json:
        print(json.dumps(rows, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
