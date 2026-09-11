"""Shared, check-side agent-loop cap grammar and comparator (audit finding LSA-05).

Leading-underscore helper module -- NOT a registered check: it adds no _manifest.py Entry, no
registry name, no check-accounting roster row, and no function_to_category row. Consumed by
scripts/checks/ci_guards/validate_ci_rca_adjudication.py (the workflow-region caller) and
scripts/checks/contracts/validate_composite_action_shape_rosters.py (the action-region caller).

Owns three things:
  (1) The extraction grammar -- CHECK-SIDE ON PURPOSE: a declaration row never names a regex or a
      line number, only a value, so an author cannot retarget the derivation to dodge a mismatch.
      Resolves ``--max-turns <token>`` in two forms: an inline integer, and a same-file shell-
      variable reference (``$VAR`` / ``"$VAR"`` / ``"${VAR}"``) resolved against a ``VAR=<int>``
      assignment elsewhere in the same file -- the review.sh:68 shape, where one ``MAX_TURNS=5``
      assignment feeds two separate invocations.
  (2) Fail-closed unresolvability: a token that is neither an inline integer nor a
      same-file-resolvable variable, and a file yielding two DIFFERENT values for one kind, both
      surface as failure strings rather than silently dropping out of the census. A governed-kind
      literal found anywhere under .github/ OUTSIDE the two governed regions
      (``.github/workflows/**.{yml,yaml}``, ``.github/actions/**.{yml,yaml,sh}``) is the same kind
      of failure -- relocating a cap out of the grammar's reach is not an escape from declaration.
  (3) The two-way comparator over ``{repo-relative file: {kind: value}}``: discovered but
      undeclared FAILS, declared but not discovered FAILS (stale row), both present with unequal
      values FAILS.

Also owns the shared PROSE NON-TRIVIALITY FLOOR both callers apply to a declared entry's
on_exhaustion and rationale, so the floor is defined ONCE and cannot drift between the workflow
and action regions: at least 40 stripped characters, not equal (case-insensitively) to the kind
name, and the two fields not equal to each other.

Filesystem reads only -- no subprocess, no network (Decision 153 fast-tier budget).
"""

from __future__ import annotations

import re
from pathlib import Path

# Exactly one governed kind today -- the audit finding's own scope. Job-level timeout-minutes is
# deliberately NOT governed (see docs/plans/PLAN-declared-caps.yaml constraints); a second kind is
# a row-and-grammar addition later, never a redesign.
GOVERNED_KIND_FLAGS: dict[str, str] = {"max_turns": "--max-turns"}
GOVERNED_KINDS: frozenset[str] = frozenset(GOVERNED_KIND_FLAGS)

NON_TRIVIALITY_MIN_CHARS = 40

_ASSIGNMENT_RE = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)=(-?\d+)\b", re.MULTILINE)
_VAR_TOKEN_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
_INT_TOKEN_RE = re.compile(r"-?\d+")


def _flag_pattern(flag: str) -> re.Pattern[str]:
    return re.compile(re.escape(flag) + r'[ \t]+("[^"]*"|\'[^\']*\'|\S+)')


def _strip_quotes(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _resolve_token(token: str, assignments: dict[str, int]) -> int | None:
    """Resolve one flag argument token to an int, or None if unresolvable. Accepts an inline
    integer (quoted or bare) or a same-file $VAR / "$VAR" / "${VAR}" reference."""
    token = _strip_quotes(token)
    if _INT_TOKEN_RE.fullmatch(token):
        return int(token)
    match = _VAR_TOKEN_RE.fullmatch(token)
    if match:
        return assignments.get(match.group(1))
    return None


def _is_workflow_region(rel: str) -> bool:
    return rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml"))


def _is_action_region(rel: str) -> bool:
    return rel.startswith(".github/actions/") and rel.endswith((".yml", ".yaml", ".sh"))


def scan_cap_literals(root: Path) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Walk .github/** under `root`, extracting agent-loop cap literals from the two governed
    regions (.github/workflows/**.{yml,yaml}, .github/actions/**.{yml,yaml,sh}).

    Returns (discovered, errors). `discovered` is {repo-relative POSIX path: {kind: value}} for
    every governed-region file carrying a resolvable cap. `errors` is a flat list of failure
    strings covering: an unresolvable token; one file yielding two different values for one kind;
    and a governed-kind literal found anywhere under .github/ OUTSIDE the two governed regions.
    Takes an explicit root so every red path is exercisable against a synthetic tree.
    """
    discovered: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    github_dir = Path(root) / ".github"
    if not github_dir.is_dir():
        return discovered, errors

    for path in sorted(p for p in github_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if not (_is_workflow_region(rel) or _is_action_region(rel)):
            for kind, flag in GOVERNED_KIND_FLAGS.items():
                if flag in text:
                    errors.append(
                        f"agent-loop cap: {rel} carries a {kind} ({flag}) literal outside both "
                        "governed regions (.github/workflows/**, .github/actions/**) -- "
                        "relocation is not an escape from declaration"
                    )
            continue

        assignments = {m.group(1): int(m.group(2)) for m in _ASSIGNMENT_RE.finditer(text)}
        for kind, flag in GOVERNED_KIND_FLAGS.items():
            tokens = _flag_pattern(flag).findall(text)
            if not tokens:
                continue
            resolved = [_resolve_token(tok, assignments) for tok in tokens]
            if any(v is None for v in resolved):
                errors.append(
                    f"agent-loop cap: {rel} carries an unresolvable {kind} token ({flag} "
                    "argument is not a literal int or a same-file-resolvable shell variable)"
                )
                continue
            distinct = sorted({v for v in resolved if v is not None})
            if len(distinct) > 1:
                errors.append(
                    f"agent-loop cap: {rel} carries {len(distinct)} different {kind} values "
                    f"{distinct} in one file -- ambiguous"
                )
                continue
            discovered.setdefault(rel, {})[kind] = distinct[0]

    return discovered, errors


def compare_caps(
    declared: dict[str, dict[str, int]],
    discovered: dict[str, dict[str, int]],
    region_label: str,
) -> list[str]:
    """Two-way comparator over {repo-relative file: {kind: value}}. Discovered but undeclared
    FAILS, declared but not discovered FAILS (stale row), both present with unequal values FAILS.

    `region_label` (e.g. "workflow", "action") only labels the failure strings for readability --
    callers are responsible for pre-filtering `discovered` to their own governed region before
    calling this, since a shared unfiltered census would cross-contaminate the two regions'
    undeclared/stale verdicts.
    """
    failures: list[str] = []
    for file in sorted(set(declared) | set(discovered)):
        declared_kinds = declared.get(file, {})
        discovered_kinds = discovered.get(file, {})
        for kind in sorted(set(declared_kinds) | set(discovered_kinds)):
            if kind not in declared_kinds:
                failures.append(
                    f"agent-loop cap ({region_label}): {file} carries a live {kind} literal "
                    f"(value {discovered_kinds[kind]}) with no declared row -- undeclared cap"
                )
            elif kind not in discovered_kinds:
                failures.append(
                    f"agent-loop cap ({region_label}): declared {kind} row for {file} names no "
                    "live literal -- stale declaration"
                )
            elif declared_kinds[kind] != discovered_kinds[kind]:
                failures.append(
                    f"agent-loop cap ({region_label}): {file} {kind} literal="
                    f"{discovered_kinds[kind]} but declared value={declared_kinds[kind]} -- drift"
                )
    return failures


def _clears_non_triviality_floor(text: object, kind: object) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if len(stripped) < NON_TRIVIALITY_MIN_CHARS:
        return False
    return not (isinstance(kind, str) and stripped.casefold() == kind.strip().casefold())


def check_cap_entry_shape(entry: object, *, context: str) -> tuple[list[str], str | None, int | None]:
    """Shared shape+floor validation for one declared agent_loop_caps entry -- used by both the
    workflow-region and action-region callers, so kind/value/floor checks cannot drift between
    them. `context` names the entry for failure messages (e.g. a workflow row or a contract site).

    Returns (failures, kind, value); kind and value are None whenever failures is non-empty, since
    a shape-invalid entry contributes nothing usable to the declared-map comparison.
    """
    if not isinstance(entry, dict):
        return [f"agent-loop cap: {context} entry is not a mapping"], None, None

    failures: list[str] = []
    kind = entry.get("kind")
    value = entry.get("value")
    on_exhaustion = entry.get("on_exhaustion")
    rationale = entry.get("rationale")

    if kind not in GOVERNED_KINDS:
        failures.append(f"agent-loop cap: {context} declares kind={kind!r}, must be one of {sorted(GOVERNED_KINDS)}")
    if not isinstance(value, int) or isinstance(value, bool):
        failures.append(f"agent-loop cap: {context} declares a non-int value {value!r}")
    if not _clears_non_triviality_floor(on_exhaustion, kind):
        failures.append(
            f"agent-loop cap: {context} on_exhaustion fails the non-triviality floor (>= "
            f"{NON_TRIVIALITY_MIN_CHARS} stripped chars, not equal to the kind name)"
        )
    if not _clears_non_triviality_floor(rationale, kind):
        failures.append(
            f"agent-loop cap: {context} rationale fails the non-triviality floor (>= "
            f"{NON_TRIVIALITY_MIN_CHARS} stripped chars, not equal to the kind name)"
        )
    if isinstance(on_exhaustion, str) and isinstance(rationale, str) and on_exhaustion.strip() == rationale.strip():
        failures.append(f"agent-loop cap: {context} on_exhaustion and rationale must not be equal")

    if failures:
        return failures, None, None
    return failures, kind, value
