"""SLOC budget-raise guardrail (Decision 128, amends Decision 102; upgraded to authorization
by the Decision 165 marker-guard consolidation).

A `config/sloc_budgets.yaml` entry increase, or a brand-new >500-SLOC registration, is a
deliberate trade against model-portability (large files degrade comprehension on lower-tier
models) and must be loud and Decision-cited, not a frictionless one-line YAML edit. This check
diffs the registry against origin/main and retroactively re-scans every currently-committed
marker; both shapes FAIL unless the changed/marked line carries an inline
`# raise-approved: dec-NNN <reason>` marker naming a real `## Decision NNN:` header whose body
actually authorizes the entry's path (mentions the path or a >=2-segment ancestor of it) --
citing a Decision that merely exists is no longer sufficient.

Ratchet-down direction (decreases, removals) always passes -- this check only gates the upward
direction. Markers are not required to persist after merge for the DIFF leg (the raise is
durably recorded in git history plus the cited Decision), but a marker that IS present is
retroactively load-bearing (the second, present-markers leg).

Delegates its diff/authorization mechanics to scripts.checks._marker_guard (shared across all
five raise-marker guards); this module owns only the registry's own RegistrySpec binding.
"""

from __future__ import annotations

from typing import Callable, Optional

from scripts.checks import _common, _marker_guard, registry

_BUDGETS_REL_PATH = "config/sloc_budgets.yaml"

_SPEC = _marker_guard.RegistrySpec(
    rel_path=_BUDGETS_REL_PATH,
    token="raise-approved",
    gated_direction="up",
    extractor=_marker_guard.make_flat_extractor("raise-approved", value_type=int),
    gates_new_entry=lambda _value: True,
    label="SLOC budget-raise guardrail (Decision 128)",
)


@registry.register("validate_sloc_budget_raises", owner="platform")
def validate_sloc_budget_raises(
    failed: list[str],
    base_reader: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """Fail on an unauthorized config/sloc_budgets.yaml increase, new >500 registration, or a
    currently-committed marker that no longer authorizes its entry.

    Declares skipped when the registry file is absent or origin/main is unreachable (the diff leg's
    base is unavailable), else examined over the current registry entries (unit "entries"), each of
    which the diff leg judged against its base value.
    """
    print(f"\n=== {_SPEC.label} ===")
    current_path = _common.ROOT / _SPEC.rel_path
    if not current_path.exists():
        print(f"  {_SPEC.rel_path} not found -- nothing to check.")
        registry.skipped(f"{_SPEC.rel_path} not found")
        return

    base_text = (base_reader or _marker_guard.default_base_reader)(_SPEC.rel_path)
    diff_violations = _marker_guard.check_diff(_SPEC, base_reader=lambda _rel: base_text)
    violations = diff_violations + _marker_guard.check_present_markers(_SPEC)

    if violations:
        print("SLOC budget-raise violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append(_SPEC.label)
    else:
        print("No unauthorized SLOC budget raises.")

    if base_text is None:
        registry.skipped("origin/main unreachable")
    else:
        registry.examined(len(_SPEC.extractor(current_path.read_text(encoding="utf-8"))), unit="entries")
