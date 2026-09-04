"""Fast-tier budget formula, constants and plan-time reporter (Decision 182, amends Decision 153).

The single home of every budget constant the fast tier asserts on, of the two-term split those
budgets are asserted over, and of the plan-time CLI that reports a candidate scope's selection
breadth before the work is written. scripts/validate.py restates no number from here: it BINDS its
two existing public constant names to FLOOR_TOTAL_SECONDS and CEILING_SECONDS.

The tier asserts TWO quantities rather than one aggregate wall clock:

* NON_TEST_BUDGET_SECONDS on ``elapsed - phase_times[TEST_PHASE_NAME]`` -- identically
  ``static_s + replay_s + unattributed_s``, so nothing the tier spends is left ungoverned.
  Unwaivable: no bypass, forced-scope, breadth or fallback path reaches it.
* a breadth-derived test-execution allowance on ``phase_times[TEST_PHASE_NAME]``, capped at the
  DERIVED expression ``CEILING_SECONDS - NON_TEST_BUDGET_SECONDS`` so the worst-case ASSERTED total
  across both governed terms is exactly the existing derived ceiling -- no second ceiling constant.

REPLAY_ALLOWANCE_SECONDS is neither a budget asserted here nor a term in the cap: it MIRRORS
validate_vp_replay's own ratified MAX_AGGREGATE_SECONDS + one PER_STEP_TIMEOUT_SECONDS of
final-step overshoot (that guard trips only at the top of its loop). It is recorded because
NON_TEST_BUDGET_SECONDS was derived to DOMINATE it -- a check sanctioned to consume the whole outer
budget would make the two jointly unsatisfiable -- and because the breach diagnostic prints
replay_s beside it, so a replay-dominated non-test breach is self-identifying. It is pinned equal
to its source by a test rather than imported: importing that check's defining module here would
trade this module's stdlib purity (and validate.py's eager import of it) for a coupling the pin
already covers.

Declare or split -- the plan-time reading of this CLI's report:
  within_budget    plan the scope as one unit; the measured breadth is already inside the base.
  breadth_waived   KEEP the scope and DECLARE the measured breadth in the plan, so the waiver is
                   expected and reviewed rather than discovered in CI.
  breach           SPLIT the scope into atomic units until the prediction clears -- the measured
                   selection breadth, not the scope-row file count, is the quantity to plan
                   against.
  non_test_breach  neither declare nor split: the non-test half is drifting, which no scope change
                   fixes; open a planning session against the recorded static_s series.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

# The two budgets the fast tier asserts on, the derived ceiling they are bounded by, and the floor
# total they sum to. Derived in Decision 182 from three CI selection-manifest artifacts plus the
# enumerated in-tier allowance the non-test half must dominate; re-derive by amendment against the
# recorded static_s / replay_s / phase_count series, never by a silent raise.
NON_TEST_BUDGET_SECONDS = 240.0
TEST_BASE_SECONDS = 180.0
PER_MODULE_SECONDS = 2.0

# Derived guardrail, not a second tier budget (Decision 153): pr-validate's 30-min job timeout
# (.github/workflows/ci.yml) minus a ~5-min diagnostic margin, on the fast tier's own elapsed clock
# (job clock additionally includes checkout/pip). Re-derive if timeout-minutes changes.
CEILING_SECONDS = 1500.0

# 420.0 -- written as the partition it IS, so the two halves and their sum can never drift apart.
FLOOR_TOTAL_SECONDS = NON_TEST_BUDGET_SECONDS + TEST_BASE_SECONDS

# Mirror of validate_vp_replay's ratified in-tier allowance (MAX_AGGREGATE_SECONDS +
# PER_STEP_TIMEOUT_SECONDS). Pinned to its source by test; see the module docstring.
REPLAY_ALLOWANCE_SECONDS = 150.0

# The two phase names this module reports on. Their single home: validate.py spells neither.
TEST_PHASE_NAME = "pytest_diff"
REPLAY_PHASE_NAME = "validate_vp_replay"

# Measured pytest_diff population (Decision 182): a 98-module floor at 28.317s and the two
# same-head slopes to 263 modules. Used for the plan-time prediction only -- never asserted on.
_PREDICT_FLOOR_MODULES = 98
_PREDICT_FLOOR_SECONDS = 28.317
_PREDICT_SLOPE_LOW = 1.2742
_PREDICT_SLOPE_HIGH = 1.6996

# The measured non-test halves of the same three artifacts (best / worst), added to the predicted
# test half so the CLI reports a whole-run range rather than only its governed test term.
_PREDICT_NON_TEST_LOW = 51.014
_PREDICT_NON_TEST_HIGH = 71.766

_DECLARE_OR_SPLIT = {
    "within_budget": "declare-or-split: plan the scope as one unit; the measured breadth is already inside the base.",
    "breadth_waived": (
        "declare-or-split: KEEP the scope and DECLARE the measured breadth in the plan, so the waiver is "
        "expected and reviewed rather than discovered in CI."
    ),
    "breach": (
        "declare-or-split: SPLIT the scope into atomic units until the prediction clears -- the measured "
        "selection breadth, not the scope-row file count, is the quantity to plan against."
    ),
    "non_test_breach": (
        "declare-or-split: neither declare nor split -- the non-test half is drifting, which no scope change "
        "fixes; open a planning session against the recorded static_s series."
    ),
}


@dataclasses.dataclass(frozen=True)
class BudgetVerdict:
    """One run's budget disposition: which arm fired, the limit it was judged against, why it was
    waived (if it was) and the exit code the caller owes."""

    outcome: str
    limit_s: float
    waiver_cause: str | None
    exit_code: int
    allowance_s: float

    @property
    def hard_fail(self) -> bool:
        return self.exit_code != 0


def count_test_modules(root: Path | str | None = None) -> int:
    """Census of test modules on disk (tests/**/test_*.py) -- the sanity floor under the breadth
    allowance, so an over-selecting or corrupted selector cannot inflate its own allowance past
    what the repository could actually run. stdlib rglob; never raises on a missing tree."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    tests_dir = base / "tests"
    if not tests_dir.is_dir():
        return 0
    return sum(1 for _ in tests_dir.rglob("test_*.py"))


def test_execution_allowance(n_selected: int, census: int | None = None) -> float:
    """The breadth-derived allowance for the test half.

    Flat TEST_BASE_SECONDS below the crossover, PER_MODULE_SECONDS per selected module above it,
    clamped by the on-disk census and capped at the DERIVED expression
    CEILING_SECONDS - NON_TEST_BUDGET_SECONDS -- written as that expression, never as a literal, so
    the worst-case asserted total across both governed terms stays exactly CEILING_SECONDS.
    """
    effective = min(n_selected, census) if census is not None else n_selected
    return min(max(TEST_BASE_SECONDS, PER_MODULE_SECONDS * max(effective, 0)), CEILING_SECONDS - NON_TEST_BUDGET_SECONDS)


def split_phase_times(phase_times: dict[str, float], elapsed: float) -> tuple[float, float, float, float]:
    """Split one run's recorded phases into (static_s, test_s, replay_s, unattributed_s).

    TEST_PHASE_NAME is the SOLE subtracted phase. REPLAY_PHASE_NAME is broken out for REPORTING
    only -- replay_s stays inside the non-test half it is measured in, and nothing exempts it. The
    unattributed remainder is returned separately and never folded into static_s, so both
    ``static_s + test_s + replay_s + unattributed_s == elapsed`` and ``non_test_s + test_s ==
    elapsed`` hold by construction.
    """
    test_s = float(phase_times.get(TEST_PHASE_NAME, 0.0))
    replay_s = float(phase_times.get(REPLAY_PHASE_NAME, 0.0))
    static_s = float(sum(v for name, v in phase_times.items() if name not in (TEST_PHASE_NAME, REPLAY_PHASE_NAME)))
    unattributed_s = float(elapsed) - float(sum(phase_times.values()))
    return static_s, test_s, replay_s, unattributed_s


def dominant_non_test_phase(phase_times: dict[str, float]) -> str | None:
    """The slowest phase OTHER than the test phase, so an unwaivable non-test alarm is always
    attributable to a named component rather than to an opaque remainder."""
    candidates = {name: seconds for name, seconds in phase_times.items() if name != TEST_PHASE_NAME}
    if not candidates:
        return None
    return max(candidates, key=lambda name: candidates[name])


def predict_ci_elapsed(n_selected: int) -> tuple[float, float]:
    """Predicted CI elapsed range (low, high) for a selection of ``n_selected`` modules, from the
    two measured pytest_diff slopes above the measured 98-module floor plus the measured non-test
    half. A report, never an assertion."""
    above = max(0, n_selected - _PREDICT_FLOOR_MODULES)
    test_low = _PREDICT_FLOOR_SECONDS + _PREDICT_SLOPE_LOW * above
    test_high = _PREDICT_FLOOR_SECONDS + _PREDICT_SLOPE_HIGH * above
    return test_low + _PREDICT_NON_TEST_LOW, test_high + _PREDICT_NON_TEST_HIGH


def predict_test_half(n_selected: int) -> tuple[float, float]:
    """The test-half term of predict_ci_elapsed, alone -- the quantity the breadth allowance
    governs, so the CLI can compare like with like."""
    above = max(0, n_selected - _PREDICT_FLOOR_MODULES)
    return (
        _PREDICT_FLOOR_SECONDS + _PREDICT_SLOPE_LOW * above,
        _PREDICT_FLOOR_SECONDS + _PREDICT_SLOPE_HIGH * above,
    )


def budget_extra_keys(
    *,
    n_selected: int,
    static_s: float,
    test_s: float,
    replay_s: float,
    unattributed_s: float,
    phase_count: int,
    waiver_cause: str | None,
) -> dict[str, Any]:
    """The pure extra-keys dict the caller merges into build_budget_record's returned record at its
    OWN call site -- so the manifest budget block carries the split without scripts/checks/
    _budget_recs.py being edited.

    ``phase_count`` is the PRE-truncation phase count: the recorded phase_times is truncated to the
    10 slowest, so without it static_s could not be re-derived from the same artifact.
    """
    return {
        "n_selected": int(n_selected),
        "static_s": round(float(static_s), 3),
        "test_s": round(float(test_s), 3),
        "replay_s": round(float(replay_s), 3),
        "unattributed_s": round(float(unattributed_s), 3),
        "phase_count": int(phase_count),
        "waiver_cause": waiver_cause,
    }


def classify(
    *,
    non_test_s: float,
    static_s: float,
    test_s: float,
    replay_s: float,
    elapsed: float,
    n_selected: int,
    forced: bool,
    derivation_ok: bool,
    bypass: bool = False,
    census: int | None = None,
) -> BudgetVerdict:
    """Dispatch one run to exactly one named outcome, in a PINNED branch order.

    (1) non_test_breach -- unwaivable, evaluated BEFORE any bypass so the escape hatch cannot reach
        it and before the forced waiver so a forced run whose non-test half has drifted no longer
        gets Decision 153 point 1's waiver; (2) bypass; (3) forced_waived; (4)
        forced_ceiling_breach; (5) breach; (6) breadth_waived; (7) within_budget.

    ``derivation_ok`` False (a Decision 55 selection fallback) collapses the allowance to
    TEST_BASE_SECONDS: a degraded selection gets no breadth relief.
    """
    allowance = TEST_BASE_SECONDS if not derivation_ok else test_execution_allowance(n_selected, census)
    if non_test_s > NON_TEST_BUDGET_SECONDS:
        return BudgetVerdict("non_test_breach", NON_TEST_BUDGET_SECONDS, None, 1, allowance)
    if bypass:
        return BudgetVerdict("bypass", allowance, "ignore_budget_flag", 0, allowance)
    if forced and elapsed <= CEILING_SECONDS:
        return BudgetVerdict("forced_waived", CEILING_SECONDS, "full_suite_forced", 0, allowance)
    if forced:
        return BudgetVerdict("forced_ceiling_breach", CEILING_SECONDS, None, 1, allowance)
    if test_s > allowance:
        return BudgetVerdict("breach", allowance, None, 1, allowance)
    if test_s > TEST_BASE_SECONDS:
        return BudgetVerdict("breadth_waived", allowance, "selection_breadth", 0, allowance)
    return BudgetVerdict("within_budget", allowance, None, 0, allowance)


def _report(paths: list[str], root: Path) -> dict[str, Any]:
    """Measure a candidate scope's selection breadth and report the outcome the fast tier would
    reach for it. Imports derive_affected_tests LAZILY so this module's own scope stays
    stdlib-only (module-scope networkx here would break validate.py's --terraform-only path)."""
    from scripts.checks.deps.affected_tests import derive_affected_tests  # noqa: PLC0415

    selection = derive_affected_tests([("M", p) for p in paths], repo_root=root)
    n_selected = len(selection["selected"])
    census = count_test_modules(root)
    allowance = test_execution_allowance(n_selected, census)
    test_low, test_high = predict_test_half(n_selected)
    low, high = predict_ci_elapsed(n_selected)
    verdict = classify(
        non_test_s=_PREDICT_NON_TEST_HIGH,
        static_s=_PREDICT_NON_TEST_HIGH,
        test_s=test_high,
        replay_s=0.0,
        elapsed=high,
        n_selected=n_selected,
        forced=bool(selection["manifest"].get("full_suite_forced", False)),
        derivation_ok=not selection["manifest"].get("fallback", False),
        census=census,
    )
    return {
        "paths": paths,
        "n_selected": n_selected,
        "census": census,
        "allowance_s": allowance,
        "predicted_test_half_s": [round(test_low, 3), round(test_high, 3)],
        "predicted_elapsed_s": [round(low, 3), round(high, 3)],
        "predicted_outcome": verdict.outcome,
        "declare_or_split": _DECLARE_OR_SPLIT[verdict.outcome],
    }


def _paths_from_plan(plan_path: Path) -> list[str]:
    """Read scope[].file rows out of a plan YAML without importing yaml (module scope is
    stdlib-only): the rows are a flat ``- file: <path>`` sequence in this repo's schema."""
    paths: list[str] = []
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- file:"):
            paths.append(stripped.split(":", 1)[1].strip().strip("'\""))
    return paths


def main(argv: list[str] | None = None) -> int:
    """Plan-time reporter. Exits 0 on every path -- it is a report, never a gate."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.checks.deps.selection_budget",
        description="Report a candidate scope's measured selection breadth and the fast-tier outcome it predicts.",
        epilog=(
            "Declare or split -- the plan-time reading of this report:\n"
            "  within_budget    plan the scope as one unit; the measured breadth is already inside the base.\n"
            "  breadth_waived   KEEP the scope and DECLARE the measured breadth in the plan, so the waiver is\n"
            "                   expected and reviewed rather than discovered in CI.\n"
            "  breach           SPLIT the scope into atomic units until the prediction clears -- the measured\n"
            "                   selection breadth, not the scope-row file count, is the quantity to plan\n"
            "                   against.\n"
            "  non_test_breach  neither declare nor split: the non-test half is drifting, which no scope change\n"
            "                   fixes; open a planning session against the recorded static_s series."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--paths", nargs="+", default=[], help="repo-relative paths of the candidate scope")
    parser.add_argument("--plan", default=None, help="a PLAN-*.yaml whose scope[].file rows are the candidate scope")
    parser.add_argument("--json", action="store_true", help="emit the same record as JSON")
    parser.add_argument("--root", default=None, help="repository root (defaults to this file's repo)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[3]
    paths = list(args.paths)
    if args.plan:
        plan_path = Path(args.plan)
        paths += _paths_from_plan(plan_path if plan_path.is_absolute() else root / plan_path)
        paths.append(str(plan_path))
    if not paths:
        parser.print_help()
        return 0

    record = _report(paths, root)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    low, high = record["predicted_elapsed_s"]
    test_low, test_high = record["predicted_test_half_s"]
    print(f"scope: {len(paths)} path(s) | n_selected: {record['n_selected']} (census {record['census']})")
    print(f"test-execution allowance: {record['allowance_s']:.0f}s | non-test budget: {NON_TEST_BUDGET_SECONDS:.0f}s")
    print(f"predicted CI test half: {test_low:.1f}-{test_high:.1f}s | predicted CI elapsed: {low:.1f}-{high:.1f}s")
    print(f"predicted outcome: {record['predicted_outcome']}")
    print(record["declare_or_split"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
