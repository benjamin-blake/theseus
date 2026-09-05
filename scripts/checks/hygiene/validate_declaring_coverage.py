"""Path-aware declaring-coverage metric -- REPORT-ONLY (Decision 170's deferred-work clause;
docs/contracts/check-accounting.yaml's path_aware_declaring_coverage key).

Walks every registered check's own control flow through
scripts.checks.hygiene._declaring_coverage and reports how many reachable SUCCESS-EXIT paths
reach an examined()/skipped() declaration. This is the path-level observable
check-accounting.yaml's ratchet_limitation names as deferred future work -- the module-level
ratchet (validate_check_accounting) proves a declaration exists somewhere in a module, never
that every exit path reaches one.

REPORT-ONLY is absolute: `failed` is never appended to on ANY path, no threshold is stated
here or in the contract, and no status_vocabulary member is added. Both reachable exits declare
terminally -- examined(len(rows), unit="registered_checks") on the normal path, and
skipped(reason) when the contract's fleet_line_grammar is unavailable (the discrimination
rule's "unavailable input" arm, never a raise: validation_result dispatches a check with no
try/except, so a raise would abort the whole tier).

EVERY grammar-unavailable shape routes to that ONE skipped(reason) exit and none of them
escapes as an exception -- an unreadable contract file (OSError), undecodable bytes
(UnicodeDecodeError), malformed YAML (yaml.YAMLError), a non-mapping document, a missing
path_aware_declaring_coverage key, a missing or non-mapping fleet_line_grammar sub-key, a
non-string grammar value, AND a grammar that is a string the check cannot render: an unknown
placeholder name (KeyError), an unclosed brace (ValueError), a positional field (IndexError),
an invalid format spec (ValueError), an index or attribute field name (TypeError/AttributeError).
Only named exception classes are caught; there is no bare except anywhere in this module.

The template is validated in exactly ONE place, the report_grammar seam
(_is_renderable_grammar): fleet_line therefore renders a template already proved renderable and
carries no second guard of its own. A duplicated guard there would be unreachable through the
public entry point, and covering it would mean inventing a second, unratified report shape for
a template report_grammar has already rejected. See the contract key's
grammar_unavailable_routing.

The fleet report line's format template is READ FROM THE CONTRACT at runtime through
report_grammar() (Decision 168 resolution by evidence of reading) -- editing
path_aware_declaring_coverage.fleet_line_grammar changes what this check emits, and removing
the key degrades the check to a declared skip. The contract's declared evaluator stays
validate_check_accounting, unwidened.
"""

from __future__ import annotations

import string
from pathlib import Path
from typing import Iterable

import yaml

from scripts.checks import _common, registry
from scripts.checks.hygiene._declaring_coverage import CheckCoverage, is_fully_declared, measure_check

_GRAMMAR_FIELDS: tuple[str, ...] = ("checks", "success_exits", "declared", "undeclared", "undecidable")
_TRIAL_VALUES: dict[str, int] = dict.fromkeys(_GRAMMAR_FIELDS, 0)
_CONTRACT_REL_PATH = "docs/contracts/check-accounting.yaml"
_CONTRACT_KEY = "path_aware_declaring_coverage"
_GRAMMAR_FIELD = "fleet_line_grammar"
_OUTSIDE_BOUND_NOTE = "-- outside the measured bound, no declared/undeclared figures"
_REPORT_ONLY_NOTICE = (
    "  REPORT-ONLY: no threshold is stated and nothing is failed here -- undeclared is an UPPER "
    "bound and declared a LOWER bound (see the contract's stated CFG-lite limits)."
)


def _is_renderable_grammar(grammar: str) -> bool:
    """Whether this check can render `grammar` WITHOUT raising: every replacement field names
    one of _GRAMMAR_FIELDS exactly -- no positional field, no index or attribute access -- and a
    trial format with integer dummies succeeds. KeyError, IndexError and ValueError are caught by
    name (a malformed template raises them from parse or from format); the field whitelist is
    what closes the TypeError/AttributeError shapes a trial format alone would let through.

    A template failing either arm is UNAVAILABLE, so report_grammar returns None and the check
    declares skipped(reason). Accepting it instead would put the raise inside a check the tier
    dispatcher wraps in no try/except, aborting the whole full tier.
    """
    try:
        fields = [field for _literal, field, _spec, _conversion in string.Formatter().parse(grammar)]
        if any(field is not None and field not in _TRIAL_VALUES for field in fields):
            return False
        grammar.format(**_TRIAL_VALUES)
    except (KeyError, IndexError, ValueError):
        return False
    return True


def report_grammar(contract_path: Path | None = None) -> str | None:
    """The str.format template this check formats its fleet report line with, read from the
    contract's path_aware_declaring_coverage.fleet_line_grammar.

    Returns None -- and NEVER raises -- for every unavailable shape: an unreadable file
    (OSError), undecodable bytes (UnicodeDecodeError), malformed YAML (yaml.YAMLError), a
    non-mapping document, a missing path_aware_declaring_coverage key, a missing or non-mapping
    fleet_line_grammar sub-key, a non-string grammar value, and a string grammar that is not
    renderable over _GRAMMAR_FIELDS (_is_renderable_grammar -- an unknown placeholder name, an
    unclosed brace, a positional field, an invalid format spec, an index/attribute field name).
    Only named exception classes are caught, never a bare except. The caller then declares
    skipped(reason) rather than inventing a fallback template.
    """
    path = contract_path if contract_path is not None else _common.ROOT / _CONTRACT_REL_PATH
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    key = data.get(_CONTRACT_KEY) if isinstance(data, dict) else None
    grammar = key.get(_GRAMMAR_FIELD) if isinstance(key, dict) else None
    if not isinstance(grammar, str) or not _is_renderable_grammar(grammar):
        return None
    return grammar


def measure_fleet(names: Iterable[str] | None = None) -> list[CheckCoverage]:
    """One CheckCoverage row per registered check, in check-name order. `names` is a test/
    dogfood injection seam; the default population is the live registry roster."""
    roster = sorted(registry.all_checks()) if names is None else sorted(names)
    return [measure_check(name, registry.resolve(name)) for name in roster]


def fleet_line(rows: list[CheckCoverage], grammar: str) -> str:
    """Render `grammar` (the contract's own template) over `rows`.

    The kwargs below are exactly _GRAMMAR_FIELDS, the whitelist report_grammar validates a
    template against, so a grammar that reached here has already been proved renderable and this
    format needs no guard of its own (module docstring: the guard lives in one place)."""
    return grammar.format(
        checks=len(rows),
        success_exits=sum(r.success_exits for r in rows),
        declared=sum(r.declared for r in rows),
        undeclared=sum(r.undeclared for r in rows),
        undecidable=sum(1 for r in rows if r.undecidable_reason is not None),
    )


def _per_check_line(row: CheckCoverage) -> str:
    """An UNDECIDABLE row prints its reason and NO declared/undeclared figures: on such a row
    those fields are zero because nothing was walked, so printing them would invite reading an
    absent measurement as a bound (see the contract's bound_direction)."""
    if row.undecidable_reason is not None:
        return f"  {row.check}: undecidable={row.undecidable_reason} {_OUTSIDE_BOUND_NOTE}"
    return f"  {row.check}: success_exits={row.success_exits} declared={row.declared} undeclared={row.undeclared}"


@registry.register("validate_declaring_coverage", owner="platform")
def validate_declaring_coverage(
    failed: list[str],
    rows: list[CheckCoverage] | None = None,
    contract_path: Path | None = None,
) -> None:
    """Report path-aware declaring coverage over the registered fleet. Never appends to
    `failed` -- this is a standing observable, not a gate.

    `rows` / `contract_path` are injection seams: `rows` substitutes a synthetic fleet for the
    live walk, `contract_path` repoints the grammar read at a fixture contract.
    """
    print(f"\n=== Path-aware declaring coverage ({_CONTRACT_REL_PATH}, report-only) ===")
    grammar = report_grammar(contract_path)
    if grammar is None:
        reason = f"{_CONTRACT_REL_PATH}: {_CONTRACT_KEY}.{_GRAMMAR_FIELD} unavailable -- no report line emitted"
        print(f"  SKIP: {reason}")
        registry.skipped(reason)
        return
    measured = measure_fleet() if rows is None else rows
    for row in measured:
        if not is_fully_declared(row):
            print(_per_check_line(row))
    print(f"  {fleet_line(measured, grammar)}")
    print(_REPORT_ONLY_NOTICE)
    registry.examined(len(measured), unit="registered_checks")
