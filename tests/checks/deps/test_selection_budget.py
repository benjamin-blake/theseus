"""Decision 131 mirror for scripts/checks/deps/selection_budget.py -- the single home of the
fast tier's three budgets, of the three-term phase split and of the plan-time breadth reporter
(Decision 208, amending Decision 182).

Pure-function coverage plus two cheap, load-bearing guards: the DOMINATION pin (the non-test
budget must exceed validate_vp_replay's own ratified in-tier allowance by more than the worst
measured governed non-test half, so the two gates can never become jointly unsatisfiable again) and
the PHASE-NAME pin (both reported phase names must be real registry.pre_sequence() step names, so a
rename cannot silently turn the subtraction into a 0.0 or drop replay_s out of the recorded
series).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

import pytest

from scripts.checks import registry
from scripts.checks.deps import module_cost_table as mct
from scripts.checks.deps import selection_budget as sb

# The worst GOVERNED (escalation carve-out already subtracted) static half measured across the
# recorded CI population Decision 208 was calibrated on. Used only by the domination pin below.
_WORST_MEASURED_NON_TEST_HALF = 131.832

_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = "tests/fixtures/fast_tier_calibration_series.json"


class TestAllowance:
    """The LEGACY breadth-derived test-execution allowance: base, per-module, census clamp,
    derived cap. Kept, never removed (Decision 208), as the merge-base-`absent` fallback."""

    def test_allowance_is_base_then_per_module_then_ceiling_capped(self) -> None:
        crossover = int(sb.TEST_BASE_SECONDS / sb.PER_MODULE_SECONDS)
        assert crossover == 90
        assert sb.test_execution_allowance(0) == sb.TEST_BASE_SECONDS
        assert sb.test_execution_allowance(crossover - 1) == sb.TEST_BASE_SECONDS
        assert sb.test_execution_allowance(crossover) == sb.TEST_BASE_SECONDS
        assert sb.test_execution_allowance(crossover + 1) == sb.PER_MODULE_SECONDS * (crossover + 1)
        assert sb.test_execution_allowance(263) == sb.PER_MODULE_SECONDS * 263
        assert sb.test_execution_allowance(522) == sb.PER_MODULE_SECONDS * 522

        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
        binds_at = int(cap / sb.PER_MODULE_SECONDS)
        assert binds_at == 555
        assert sb.test_execution_allowance(binds_at, census=binds_at) == cap
        assert sb.test_execution_allowance(1000, census=1000) == cap
        assert sb.test_execution_allowance(10**6, census=10**6) == cap

    def test_census_floor_stops_an_over_selecting_selector_inflating_its_allowance(self) -> None:
        cap_expr = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
        binds_at = int(cap_expr / sb.PER_MODULE_SECONDS)
        for c in (100, 263, binds_at - 1):
            clamped = sb.test_execution_allowance(10**6, census=c)
            assert clamped == sb.test_execution_allowance(c, census=c)
            assert clamped == max(sb.TEST_BASE_SECONDS, sb.PER_MODULE_SECONDS * c)
            assert clamped < sb.test_execution_allowance(10**6)

        live = sb.count_test_modules()
        assert live > 0
        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
        expected = min(max(sb.TEST_BASE_SECONDS, sb.PER_MODULE_SECONDS * live), cap)
        assert sb.test_execution_allowance(10**6, census=live) == sb.test_execution_allowance(live, census=live)
        assert sb.test_execution_allowance(10**6, census=live) == expected

    def test_census_clamp_saturates_at_the_derived_cap_on_a_real_tree(self, tmp_path) -> None:
        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
        binds_at = int(cap / sb.PER_MODULE_SECONDS)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        written = 0
        for size in (binds_at - 1, binds_at, binds_at + 3):
            for i in range(written, size):
                (tests_dir / f"test_{i}.py").write_text("", encoding="utf-8")
            written = size

            assert sb.count_test_modules(root=tmp_path) == size
            allowance = sb.test_execution_allowance(10**6, census=size)
            if size < binds_at:
                assert allowance == sb.PER_MODULE_SECONDS * size
            else:
                assert allowance == cap

    def test_coefficient_and_partition_constants_are_pinned(self) -> None:
        assert sb.PER_MODULE_SECONDS == 2.0
        assert sb.TEST_BASE_SECONDS == 180.0
        assert sb.NON_TEST_BUDGET_SECONDS == 270.0
        assert sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS == 120.0
        assert sb.CEILING_SECONDS == 1500.0
        assert sb.NON_TEST_BUDGET_SECONDS + sb.TEST_BASE_SECONDS == sb.FLOOR_TOTAL_SECONDS == 450.0
        # Composite bound: at an unbounded selection the THREE governed terms land EXACTLY on the
        # existing derived ceiling -- the cap is CEILING - NON_TEST - ESCALATION, never a fourth literal.
        assert (
            sb.NON_TEST_BUDGET_SECONDS
            + sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
            + sb.test_execution_allowance(10**6, census=10**6)
            == sb.CEILING_SECONDS
        )


class TestCostBasedAllowance:
    """The measured-cost test-execution allowance (Decision 208): floored at TEST_BASE_SECONDS,
    the prepass/overhead term is linear in selection size, capped at the same derived cap."""

    def test_floors_at_test_base(self) -> None:
        assert sb.cost_based_allowance(0.0, 0) == sb.TEST_BASE_SECONDS

    def test_scales_with_coefficient_and_prepass_overhead(self) -> None:
        cost_s = 100.0
        n = 50
        expected = sb.COST_COEFFICIENT * cost_s + sb.PREPASS_FIXED_SECONDS + sb.PREPASS_PER_MODULE_SECONDS * n
        assert sb.cost_based_allowance(cost_s, n) == pytest.approx(expected)

    def test_census_clamps_the_overhead_term(self) -> None:
        census = 10
        unclamped = sb.cost_based_allowance(1.0, 10**6)
        clamped = sb.cost_based_allowance(1.0, 10**6, census=census)
        assert clamped < unclamped

    def test_caps_at_the_derived_expression(self) -> None:
        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
        assert sb.cost_based_allowance(10**6, 10**6) == cap


class TestEscalationCarveOut:
    """Carved only when this run actually escalated; capped at PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS."""

    def test_zero_when_not_escalated(self) -> None:
        assert sb.escalation_carve_out({sb.PRECOMMIT_PHASE_NAME: 500.0}, precommit_escalated=False) == 0.0

    def test_carves_the_phase_time_when_under_the_allowance(self) -> None:
        assert sb.escalation_carve_out({sb.PRECOMMIT_PHASE_NAME: 50.0}, precommit_escalated=True) == 50.0

    def test_caps_at_the_allowance_leaving_excess_ungoverned(self) -> None:
        carve = sb.escalation_carve_out({sb.PRECOMMIT_PHASE_NAME: 500.0}, precommit_escalated=True)
        assert carve == sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS

    def test_absent_phase_carves_nothing(self) -> None:
        assert sb.escalation_carve_out({}, precommit_escalated=True) == 0.0


class TestSplitPhaseTimes:
    """Exactly ONE phase is subtracted; replay is reported but stays inside the non-test half."""

    @staticmethod
    def _mixed() -> tuple[dict[str, float], float]:
        phases = {"lint": 12.5, sb.REPLAY_PHASE_NAME: 40.25, sb.TEST_PHASE_NAME: 100.0, "mypy_diff": 2.25}
        return phases, 200.0

    def test_test_phase_is_the_sole_subtracted_phase(self) -> None:
        phases, elapsed = self._mixed()
        static_s, test_s, replay_s, _unattributed = sb.split_phase_times(phases, elapsed)
        assert test_s == 100.0
        assert static_s == 12.5 + 2.25
        assert replay_s == 40.25

    def test_replay_is_reported_but_left_inside_the_non_test_half(self) -> None:
        phases, elapsed = self._mixed()
        static_s, test_s, replay_s, unattributed_s = sb.split_phase_times(phases, elapsed)
        non_test_s = elapsed - test_s
        assert replay_s == 40.25
        assert non_test_s == static_s + replay_s + unattributed_s

    def test_absent_named_phases_yield_zero(self) -> None:
        static_s, test_s, replay_s, unattributed_s = sb.split_phase_times({"lint": 5.0}, 9.0)
        assert (test_s, replay_s) == (0.0, 0.0)
        assert static_s == 5.0
        assert unattributed_s == 4.0

    def test_identities_hold_on_a_mixed_shape(self) -> None:
        phases, elapsed = self._mixed()
        static_s, test_s, replay_s, unattributed_s = sb.split_phase_times(phases, elapsed)
        assert static_s + test_s + replay_s + unattributed_s == pytest.approx(elapsed)
        assert (elapsed - test_s) + test_s == pytest.approx(elapsed)
        assert unattributed_s == pytest.approx(elapsed - sum(phases.values()))

    def test_dominant_non_test_phase_never_names_the_test_phase(self) -> None:
        phases, _elapsed = self._mixed()
        assert sb.dominant_non_test_phase(phases) == sb.REPLAY_PHASE_NAME
        assert sb.dominant_non_test_phase({sb.TEST_PHASE_NAME: 900.0}) is None
        assert sb.dominant_non_test_phase({}) is None


class TestBudgetExtraKeys:
    """The twelve keys validate.py merges into build_budget_record's returned dict at its call site."""

    def test_twelve_keys_with_pre_truncation_phase_count(self) -> None:
        extra = sb.budget_extra_keys(
            n_selected=263,
            static_s=12.3456,
            test_s=308.7472,
            replay_s=1.5,
            unattributed_s=0.25,
            phase_count=112,
            waiver_cause="selection_breadth",
            precommit_escalated=True,
            escalation_s=42.0,
            cost_s=100.0,
            cost_table_status="ok",
        )
        assert set(extra) == {
            "n_selected",
            "static_s",
            "test_s",
            "replay_s",
            "unattributed_s",
            "phase_count",
            "waiver_cause",
            "precommit_escalated",
            "escalation_s",
            "cost_s",
            "cost_table_status",
            "cost_ratio",
        }
        assert extra["n_selected"] == 263
        assert extra["static_s"] == 12.346
        assert extra["test_s"] == 308.747
        assert extra["phase_count"] == 112
        assert extra["waiver_cause"] == "selection_breadth"
        assert extra["precommit_escalated"] is True
        assert extra["escalation_s"] == 42.0
        assert extra["cost_s"] == 100.0
        assert extra["cost_table_status"] == "ok"
        overhead = sb.PREPASS_FIXED_SECONDS + sb.PREPASS_PER_MODULE_SECONDS * 263
        assert extra["cost_ratio"] == round((308.7472 - overhead) / 100.0, 3)

        defaults = sb.budget_extra_keys(
            n_selected=0, static_s=0.0, test_s=0.0, replay_s=0.0, unattributed_s=0.0, phase_count=0, waiver_cause=None
        )
        assert defaults["waiver_cause"] is None
        assert defaults["precommit_escalated"] is False
        assert defaults["escalation_s"] == 0.0
        assert defaults["cost_s"] is None
        assert defaults["cost_table_status"] is None
        assert defaults["cost_ratio"] is None

    def test_cost_ratio_is_null_off_the_cost_path(self) -> None:
        extra = sb.budget_extra_keys(
            n_selected=10, static_s=1.0, test_s=200.0, replay_s=0.0, unattributed_s=0.0, phase_count=5, waiver_cause=None
        )
        assert extra["cost_ratio"] is None

    def test_cost_ratio_null_when_cost_is_zero(self) -> None:
        extra = sb.budget_extra_keys(
            n_selected=10,
            static_s=1.0,
            test_s=200.0,
            replay_s=0.0,
            unattributed_s=0.0,
            phase_count=5,
            waiver_cause=None,
            cost_s=0.0,
        )
        assert extra["cost_ratio"] is None


class TestPrediction:
    """The plan-time prediction: the cost-path high end IS the gate's own allowance function, and
    a None cost_s falls back to the measured floor-and-slopes legacy prediction."""

    def test_legacy_prediction_uses_the_measured_floor_and_both_slopes(self) -> None:
        low, high = sb.predict_ci_elapsed(98)
        assert low == pytest.approx(28.317 + sb._PREDICT_NON_TEST_LOW, abs=1e-6)
        assert high == pytest.approx(28.317 + sb._PREDICT_NON_TEST_HIGH, abs=1e-6)
        assert sb.predict_ci_elapsed(10) == sb.predict_ci_elapsed(98)

        test_low, test_high = sb.predict_test_half(128)
        assert test_low == pytest.approx(28.317 + 1.2742 * 30, abs=1e-6)
        assert test_high == pytest.approx(28.317 + 1.6996 * 30, abs=1e-6)
        wide_low, wide_high = sb.predict_ci_elapsed(128)
        assert wide_low == pytest.approx(test_low + sb._PREDICT_NON_TEST_LOW, abs=1e-6)
        assert wide_high == pytest.approx(test_high + sb._PREDICT_NON_TEST_HIGH, abs=1e-6)

    def test_cost_path_high_end_matches_the_gates_own_allowance(self) -> None:
        cost_s = 50.0
        n = 100
        _low, high = sb.predict_test_half(n, cost_s=cost_s)
        overhead = sb.PREPASS_FIXED_SECONDS + sb.PREPASS_PER_MODULE_SECONDS * n
        assert high == pytest.approx(sb.COST_COEFFICIENT * cost_s + overhead)

    def test_cost_path_low_end_uses_the_ratio_constant(self) -> None:
        cost_s = 50.0
        n = 100
        low, _high = sb.predict_test_half(n, cost_s=cost_s)
        overhead = sb.PREPASS_FIXED_SECONDS + sb.PREPASS_PER_MODULE_SECONDS * n
        assert low == pytest.approx(sb.PREDICT_COST_RATIO_LOW * cost_s + overhead)


class TestClassifyBranchOrder:
    """The branch order is part of the contract: it decides whether Decision 153's forced-path
    outcomes survive, and whether the unwaivable half can be escaped."""

    @staticmethod
    def _classify(**overrides: object) -> sb.BudgetVerdict:
        kwargs: dict[str, Any] = {
            "non_test_s": 10.0,
            "static_s": 10.0,
            "test_s": 10.0,
            "replay_s": 0.0,
            "elapsed": 20.0,
            "n_selected": 10,
            "forced": False,
            "derivation_ok": True,
            "bypass": False,
            "census": 522,
        }
        kwargs.update(overrides)
        return sb.classify(**kwargs)

    def test_branch_order_is_pinned(self) -> None:
        # (1) outranks (2): a bypassed run whose non-test half breached is still a non_test_breach.
        assert self._classify(non_test_s=280.0, elapsed=290.0).outcome == "non_test_breach"
        assert self._classify(non_test_s=280.0, elapsed=290.0, bypass=True).outcome == "non_test_breach"
        # (1) outranks (3): a FORCED run whose non-test half breached loses Decision 153's waiver.
        assert self._classify(non_test_s=280.0, elapsed=290.0, forced=True).outcome == "non_test_breach"
        # (2) outranks (3): a bypassed forced run reports bypass.
        assert self._classify(bypass=True, forced=True).outcome == "bypass"
        # (3) outranks (4) at EXACTLY the ceiling, and (4) fires just above it.
        at_ceiling = self._classify(forced=True, elapsed=sb.CEILING_SECONDS, test_s=10.0, non_test_s=10.0)
        assert at_ceiling.outcome == "forced_waived"
        assert at_ceiling.limit_s == sb.CEILING_SECONDS
        assert self._classify(forced=True, elapsed=sb.CEILING_SECONDS + 1.0).outcome == "forced_ceiling_breach"
        # (3) outranks (5)/(6): a forced run with a huge test half still warns-and-passes.
        assert self._classify(forced=True, test_s=1400.0, elapsed=1410.0).outcome == "forced_waived"
        # (5) outranks (6): a test half above the ALLOWANCE is a breach, not a breadth waiver.
        assert self._classify(n_selected=10, test_s=200.0, elapsed=210.0).outcome == "breach"
        # (6) outranks (7): a test half above the BASE but under the allowance is breadth_waived.
        breadth = self._classify(n_selected=263, test_s=300.0, elapsed=310.0)
        assert breadth.outcome == "breadth_waived"
        assert breadth.waiver_cause == "selection_breadth"
        assert breadth.limit_s == sb.PER_MODULE_SECONDS * 263
        # (7) the denominator.
        assert self._classify().outcome == "within_budget"

    def test_exit_dispositions_and_limits_are_named_per_branch(self) -> None:
        assert self._classify(non_test_s=280.0, elapsed=290.0).limit_s == sb.NON_TEST_BUDGET_SECONDS
        assert self._classify(non_test_s=280.0, elapsed=290.0).exit_code == 1
        assert self._classify(non_test_s=sb.NON_TEST_BUDGET_SECONDS, elapsed=250.0).outcome != "non_test_breach"
        assert self._classify(forced=True, elapsed=sb.CEILING_SECONDS + 1.0).exit_code == 1
        assert self._classify(n_selected=10, test_s=200.0, elapsed=210.0).exit_code == 1
        assert self._classify().exit_code == 0
        assert self._classify().waiver_cause is None

    def test_derivation_failure_collapses_the_allowance_to_the_base(self) -> None:
        degraded = self._classify(derivation_ok=False, n_selected=263, test_s=400.0, elapsed=410.0)
        assert degraded.outcome == "breach"
        assert degraded.limit_s == sb.TEST_BASE_SECONDS
        healthy = self._classify(derivation_ok=True, n_selected=263, test_s=400.0, elapsed=410.0)
        assert healthy.outcome == "breadth_waived"

    def test_an_inflated_selection_cannot_raise_its_own_allowance(self) -> None:
        census = 263
        inflated = self._classify(n_selected=10**6, census=census, test_s=10.0)
        assert inflated.allowance_s == sb.PER_MODULE_SECONDS * census
        assert inflated.allowance_s < sb.test_execution_allowance(10**6)

    def test_cost_s_given_selects_the_measured_cost_allowance(self) -> None:
        cost_only = self._classify(cost_s=50.0, n_selected=100, test_s=10.0)
        legacy = self._classify(n_selected=100, test_s=10.0)
        assert cost_only.allowance_s == sb.cost_based_allowance(50.0, 100, census=522)
        assert cost_only.allowance_s != legacy.allowance_s

    def test_derivation_failure_ignores_cost_s(self) -> None:
        degraded = self._classify(derivation_ok=False, cost_s=50.0, n_selected=100, test_s=10.0)
        assert degraded.allowance_s == sb.TEST_BASE_SECONDS


class TestNonTestReDerivation:
    """rec-4093's acceptance node (name verbatim): the governed static worst (static_s minus the
    escalation carve-out) plus the unattributed max plus REPLAY_ALLOWANCE_SECONDS derives
    NON_TEST_BUDGET_SECONDS; PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS dominates every recorded
    escalated run; no green run re-trips reversal (a) on its own calibration population."""

    @staticmethod
    def _fixture() -> dict:
        return json.loads((_ROOT / _FIXTURE_PATH).read_text(encoding="utf-8"))

    def test_non_test_budget_dominates_the_recorded_worst(self) -> None:
        d = self._fixture()
        success = [r for r in d["runs"] if r["job_conclusion"] == "success"]

        def _carve(r: dict) -> float:
            pc = r["phase_times_top10"].get(sb.PRECOMMIT_PHASE_NAME, 0.0)
            return min(pc, sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS) if r.get("precommit_escalated") else 0.0

        governed_static_worst = max(r["static_s"] - _carve(r) for r in success)
        unattributed_max = max(r["unattributed_s"] for r in success)
        joint_worst = governed_static_worst + unattributed_max + sb.REPLAY_ALLOWANCE_SECONDS

        assert governed_static_worst == pytest.approx(131.832, abs=0.01)
        assert unattributed_max == pytest.approx(9.956, abs=0.01)
        assert joint_worst == pytest.approx(261.788, abs=0.01)
        assert sb.NON_TEST_BUDGET_SECONDS == math.ceil(joint_worst / 10) * 10

    def test_escalation_allowance_dominates_every_escalated_run(self) -> None:
        d = self._fixture()
        escalated = [r for r in d["runs"] if r.get("precommit_escalated")]
        assert escalated
        for r in escalated:
            pc = r["phase_times_top10"].get(sb.PRECOMMIT_PHASE_NAME, 0.0)
            assert pc <= sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
        worst = max(r["phase_times_top10"].get(sb.PRECOMMIT_PHASE_NAME, 0.0) for r in escalated)
        assert sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS == math.ceil(worst / 10) * 10 + 10

    def test_no_green_run_re_trips_reversal_a(self) -> None:
        d = self._fixture()
        success = [r for r in d["runs"] if r["job_conclusion"] == "success"]

        def _governed_non_test(r: dict) -> float:
            non_test = r["elapsed_s"] - r["test_s"]
            pc = r["phase_times_top10"].get(sb.PRECOMMIT_PHASE_NAME, 0.0)
            carve = min(pc, sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS) if r.get("precommit_escalated") else 0.0
            return non_test - carve

        band = 0.8 * sb.NON_TEST_BUDGET_SECONDS
        for r in success:
            assert _governed_non_test(r) <= band


class TestPerModuleSeconds:
    """rec-3929's acceptance node (name verbatim): the measured collect-only prepass/overhead term
    is the fixture's own least-squares fit, and cost_based_allowance includes it."""

    def test_accounts_for_collect_only_prepass_cost(self) -> None:
        d = json.loads((_ROOT / _FIXTURE_PATH).read_text(encoding="utf-8"))
        single = [r for r in d["runs"] if r.get("primary_session_s") is not None and not r.get("reactive_two_invocation")]
        assert single
        xs = [r["n_selected"] for r in single]
        ys = [r["test_s"] - r["primary_session_s"] for r in single]
        reg = statistics.linear_regression(xs, ys)

        assert sb.PREPASS_FIXED_SECONDS == round(reg.intercept, 1)
        assert sb.PREPASS_PER_MODULE_SECONDS == round(reg.slope, 3)

        # cost_based_allowance includes the term: two selections of the SAME (above-floor) cost but
        # different n differ by exactly PREPASS_PER_MODULE_SECONDS per extra module.
        base = sb.cost_based_allowance(200.0, 10, census=10**6)
        wider = sb.cost_based_allowance(200.0, 60, census=10**6)
        assert wider - base == pytest.approx(sb.PREPASS_PER_MODULE_SECONDS * 50)


class TestSubtractionSetPins:
    """Two cheap guards that stop the round-2 nesting defect returning silently."""

    def test_non_test_budget_dominates_the_mirrored_allowance_and_phase_names_are_real(self) -> None:
        from scripts.checks.verification import validate_vp_replay as vp  # noqa: PLC0415

        assert sb.REPLAY_ALLOWANCE_SECONDS == vp.MAX_AGGREGATE_SECONDS, (
            "REPLAY_ALLOWANCE_SECONDS mirrors validate_vp_replay's ratified in-tier allowance (the "
            "aggregate ALONE under the shared-aggregate deadline model); if that moved, re-derive "
            "NON_TEST_BUDGET_SECONDS upward in the same edit (and the cap as "
            "CEILING_SECONDS - NON_TEST_BUDGET_SECONDS - PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS), "
            "never exempt the phase instead."
        )
        assert not hasattr(vp, "PER_STEP_TIMEOUT_SECONDS"), (
            "the flat per-step replay cap is retired under the deadline model -- its return would mean "
            "the mirrored allowance above needs a second term again"
        )
        assert sb.NON_TEST_BUDGET_SECONDS > sb.REPLAY_ALLOWANCE_SECONDS + _WORST_MEASURED_NON_TEST_HALF, (
            "the non-test budget must DOMINATE the largest ratified in-tier allowance measured inside it "
            "plus the worst measured governed non-test half, or the two gates are jointly unsatisfiable"
        )

        live_step_names = {step.name for step in registry.pre_sequence()}
        assert sb.TEST_PHASE_NAME in live_step_names
        assert sb.REPLAY_PHASE_NAME in live_step_names
        assert sb.PRECOMMIT_PHASE_NAME in live_step_names


class TestCli:
    """The plan-time reporter: exits 0 on every path, reads --paths / --plan, honours --json.

    Every case pins the module_cost_table.read_at_base_ref seam AND
    scripts.checks._scaffolding.precommit_escalates explicitly, so _report() never runs a real git
    show from a unit test and both cost-table arms are covered here.
    """

    @staticmethod
    def _selection(n: int) -> dict:
        return {
            "selected": [f"tests/t{i}.py" for i in range(n)],
            "manifest": {"full_suite_forced": False, "fallback": False},
        }

    @staticmethod
    def _absent_table() -> mct.CostTableRead:
        return mct.CostTableRead("absent", {}, 0.0)

    def test_cli_reports_breadth_and_predicted_outcome(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", lambda *a, **k: self._selection(263))
        monkeypatch.setattr(mct, "read_at_base_ref", lambda root: self._absent_table())
        monkeypatch.setattr("scripts.checks._scaffolding.precommit_escalates", lambda paths: False)
        assert sb.main(["--paths", "scripts/validate.py"]) == 0

        out = capsys.readouterr().out
        assert "n_selected: 263" in out
        assert f"{sb.PER_MODULE_SECONDS * 263:.0f}s" in out
        assert "predicted outcome: breadth_waived" in out
        assert "declare-or-split" in out
        assert "cost table: absent" in out

    def test_cli_json_emits_the_same_record(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", lambda *a, **k: self._selection(4))
        monkeypatch.setattr(mct, "read_at_base_ref", lambda root: self._absent_table())
        monkeypatch.setattr("scripts.checks._scaffolding.precommit_escalates", lambda paths: False)
        assert sb.main(["--paths", "scripts/validate.py", "--json"]) == 0

        record = json.loads(capsys.readouterr().out)
        assert record["n_selected"] == 4
        assert record["allowance_s"] == sb.TEST_BASE_SECONDS
        assert record["predicted_outcome"] == "within_budget"
        assert record["declare_or_split"].startswith("declare-or-split")
        assert len(record["predicted_elapsed_s"]) == 2
        assert record["cost_table_status"] == "absent"
        assert record["cost_s"] is None

    def test_cli_uses_the_cost_path_when_the_table_is_ok(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", lambda *a, **k: self._selection(50))
        ok_table = mct.CostTableRead("ok", {f"tests/t{i}.py": 1.0 for i in range(50)}, 1.0)
        monkeypatch.setattr(mct, "read_at_base_ref", lambda root: ok_table)
        monkeypatch.setattr(mct, "selection_cost", lambda selected, read, root: 50.0)
        monkeypatch.setattr("scripts.checks._scaffolding.precommit_escalates", lambda paths: False)
        assert sb.main(["--paths", "scripts/validate.py", "--json"]) == 0

        record = json.loads(capsys.readouterr().out)
        assert record["cost_table_status"] == "ok"
        assert record["cost_s"] == 50.0
        assert record["allowance_s"] == sb.cost_based_allowance(50.0, 50, census=sb.count_test_modules())

    def test_cli_reads_plan_scope_rows(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path) -> None:
        seen: dict[str, Any] = {}

        def _derive(entries, **kwargs):
            seen["entries"] = list(entries)
            return self._selection(2)

        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", _derive)
        monkeypatch.setattr(mct, "read_at_base_ref", lambda root: self._absent_table())
        monkeypatch.setattr("scripts.checks._scaffolding.precommit_escalates", lambda paths: False)
        plan = tmp_path / "PLAN-x.yaml"
        plan.write_text(
            "scope:\n- file: scripts/validate.py\n  action: Modify\n- file: 'tests/validate/test_budget.py'\n",
            encoding="utf-8",
        )
        assert sb.main(["--plan", str(plan)]) == 0

        paths = [path for _status, path in seen["entries"]]
        assert "scripts/validate.py" in paths
        assert "tests/validate/test_budget.py" in paths
        assert str(plan) in paths
        assert "n_selected: 2" in capsys.readouterr().out

    def test_cli_with_no_paths_prints_help_and_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        assert sb.main([]) == 0
        assert "declare or split" in capsys.readouterr().out.lower()

    def test_cli_prints_the_precommit_escalation_note(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", lambda *a, **k: self._selection(4))
        monkeypatch.setattr(mct, "read_at_base_ref", lambda root: self._absent_table())
        monkeypatch.setattr("scripts.checks._scaffolding.precommit_escalates", lambda paths: True)
        assert sb.main(["--paths", ".pre-commit-config.yaml"]) == 0
        assert "touches a pre-commit global input" in capsys.readouterr().out


class TestBudgetVerdict:
    """The convenience .hard_fail property: True for any non-zero exit code, False for zero."""

    def test_hard_fail_reflects_exit_code(self) -> None:
        failing = sb.BudgetVerdict(outcome="breach", limit_s=180.0, waiver_cause=None, exit_code=1, allowance_s=180.0)
        passing = sb.BudgetVerdict(outcome="within_budget", limit_s=180.0, waiver_cause=None, exit_code=0, allowance_s=180.0)
        assert failing.hard_fail is True
        assert passing.hard_fail is False


class TestCountTestModules:
    """The on-disk census: zero (never raising) when the tree has no tests/ subdirectory."""

    def test_returns_zero_when_tests_dir_absent(self, tmp_path) -> None:
        assert sb.count_test_modules(root=tmp_path) == 0
