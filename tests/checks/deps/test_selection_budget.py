"""Decision 131 mirror for scripts/checks/deps/selection_budget.py -- the single home of the
fast tier's two budgets, of the two-term phase split and of the plan-time breadth reporter
(Decision 182, amending Decision 153).

Pure-function coverage plus two cheap, load-bearing guards: the DOMINATION pin (the non-test
budget must exceed validate_vp_replay's own ratified in-tier allowance by more than the worst
measured non-test half, so the two gates can never become jointly unsatisfiable again) and the
PHASE-NAME pin (both reported phase names must be real registry.pre_sequence() step names, so a
rename cannot silently turn the subtraction into a 0.0 or drop replay_s out of the recorded
series).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.checks import registry
from scripts.checks.deps import selection_budget as sb

# The worst non-test half measured across the three CI selection-manifest artifacts Decision 182
# was calibrated on (51.014 / 65.501 / 71.766s). Used only by the domination pin below.
_WORST_MEASURED_NON_TEST_HALF = 71.766


class TestAllowance:
    """The breadth-derived test-execution allowance: base, per-module, census clamp, derived cap."""

    def test_allowance_is_base_then_per_module_then_ceiling_capped(self) -> None:
        crossover = int(sb.TEST_BASE_SECONDS / sb.PER_MODULE_SECONDS)
        assert crossover == 90
        assert sb.test_execution_allowance(0) == sb.TEST_BASE_SECONDS
        assert sb.test_execution_allowance(crossover - 1) == sb.TEST_BASE_SECONDS
        assert sb.test_execution_allowance(crossover) == sb.TEST_BASE_SECONDS
        assert sb.test_execution_allowance(crossover + 1) == sb.PER_MODULE_SECONDS * (crossover + 1)
        assert sb.test_execution_allowance(263) == sb.PER_MODULE_SECONDS * 263
        assert sb.test_execution_allowance(522) == sb.PER_MODULE_SECONDS * 522

        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS
        binds_at = int(cap / sb.PER_MODULE_SECONDS)
        assert binds_at == 630
        assert sb.test_execution_allowance(binds_at, census=binds_at) == cap
        assert sb.test_execution_allowance(1000, census=1000) == cap
        assert sb.test_execution_allowance(10**6, census=10**6) == cap

    def test_census_floor_stops_an_over_selecting_selector_inflating_its_allowance(self) -> None:
        census = sb.count_test_modules()
        assert census > 0
        assert sb.test_execution_allowance(10**6, census=census) == sb.test_execution_allowance(census, census=census)
        assert sb.test_execution_allowance(10**6, census=census) < sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS

    def test_coefficient_and_partition_constants_are_pinned(self) -> None:
        assert sb.PER_MODULE_SECONDS == 2.0
        assert sb.TEST_BASE_SECONDS == 180.0
        assert sb.NON_TEST_BUDGET_SECONDS == 240.0
        assert sb.CEILING_SECONDS == 1500.0
        assert sb.NON_TEST_BUDGET_SECONDS + sb.TEST_BASE_SECONDS == sb.FLOOR_TOTAL_SECONDS == 420.0
        # Composite bound: at an unbounded selection the two governed terms land EXACTLY on the
        # existing derived ceiling -- the cap is CEILING - NON_TEST, never a second literal.
        assert sb.NON_TEST_BUDGET_SECONDS + sb.test_execution_allowance(10**6, census=10**6) == sb.CEILING_SECONDS


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
    """The seven keys validate.py merges into build_budget_record's returned dict at its call site."""

    def test_seven_keys_with_pre_truncation_phase_count(self) -> None:
        extra = sb.budget_extra_keys(
            n_selected=263,
            static_s=12.3456,
            test_s=308.7472,
            replay_s=1.5,
            unattributed_s=0.25,
            phase_count=112,
            waiver_cause="selection_breadth",
        )
        assert set(extra) == {
            "n_selected",
            "static_s",
            "test_s",
            "replay_s",
            "unattributed_s",
            "phase_count",
            "waiver_cause",
        }
        assert extra["n_selected"] == 263
        assert extra["static_s"] == 12.346
        assert extra["test_s"] == 308.747
        assert extra["phase_count"] == 112
        assert extra["waiver_cause"] == "selection_breadth"
        assert (
            sb.budget_extra_keys(
                n_selected=0, static_s=0.0, test_s=0.0, replay_s=0.0, unattributed_s=0.0, phase_count=0, waiver_cause=None
            )["waiver_cause"]
            is None
        )


class TestPrediction:
    """The plan-time prediction, from the measured 98-module floor and the two measured slopes."""

    def test_prediction_uses_the_measured_floor_and_both_slopes(self) -> None:
        low, high = sb.predict_ci_elapsed(98)
        assert low == pytest.approx(28.317 + 51.014, abs=1e-6)
        assert high == pytest.approx(28.317 + 71.766, abs=1e-6)
        assert sb.predict_ci_elapsed(10) == sb.predict_ci_elapsed(98)

        test_low, test_high = sb.predict_test_half(128)
        assert test_low == pytest.approx(28.317 + 1.2742 * 30, abs=1e-6)
        assert test_high == pytest.approx(28.317 + 1.6996 * 30, abs=1e-6)
        wide_low, wide_high = sb.predict_ci_elapsed(128)
        assert wide_low == pytest.approx(test_low + 51.014, abs=1e-6)
        assert wide_high == pytest.approx(test_high + 71.766, abs=1e-6)


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
        assert self._classify(non_test_s=250.0, elapsed=260.0, bypass=True).outcome == "non_test_breach"
        # (1) outranks (3): a FORCED run whose non-test half breached loses Decision 153's waiver.
        assert self._classify(non_test_s=250.0, elapsed=260.0, forced=True).outcome == "non_test_breach"
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
        assert self._classify(non_test_s=250.0, elapsed=260.0).limit_s == sb.NON_TEST_BUDGET_SECONDS
        assert self._classify(non_test_s=250.0, elapsed=260.0).exit_code == 1
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
        census = sb.count_test_modules()
        inflated = self._classify(n_selected=10**6, census=census, test_s=10.0)
        assert inflated.allowance_s == sb.test_execution_allowance(census, census=census)


class TestSubtractionSetPins:
    """Two cheap guards that stop the round-2 nesting defect returning silently."""

    def test_non_test_budget_dominates_the_mirrored_allowance_and_phase_names_are_real(self) -> None:
        from scripts.checks.verification import validate_vp_replay as vp  # noqa: PLC0415

        assert sb.REPLAY_ALLOWANCE_SECONDS == vp.MAX_AGGREGATE_SECONDS + vp.PER_STEP_TIMEOUT_SECONDS, (
            "REPLAY_ALLOWANCE_SECONDS mirrors validate_vp_replay's ratified in-tier allowance; if that "
            "moved, re-derive NON_TEST_BUDGET_SECONDS upward in the same edit (and the cap as "
            "CEILING_SECONDS - NON_TEST_BUDGET_SECONDS), never exempt the phase instead."
        )
        assert sb.NON_TEST_BUDGET_SECONDS > sb.REPLAY_ALLOWANCE_SECONDS + _WORST_MEASURED_NON_TEST_HALF, (
            "the non-test budget must DOMINATE the largest ratified in-tier allowance measured inside it "
            "plus the worst measured non-test half, or the two gates are jointly unsatisfiable"
        )

        live_step_names = {step.name for step in registry.pre_sequence()}
        assert sb.TEST_PHASE_NAME in live_step_names
        assert sb.REPLAY_PHASE_NAME in live_step_names


class TestCli:
    """The plan-time reporter: exits 0 on every path, reads --paths / --plan, honours --json."""

    @staticmethod
    def _selection(n: int) -> dict:
        return {
            "selected": [f"tests/t{i}.py" for i in range(n)],
            "manifest": {"full_suite_forced": False, "fallback": False},
        }

    def test_cli_reports_breadth_and_predicted_outcome(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", lambda *a, **k: self._selection(263))
        assert sb.main(["--paths", "scripts/validate.py"]) == 0

        out = capsys.readouterr().out
        assert "n_selected: 263" in out
        assert f"{sb.PER_MODULE_SECONDS * 263:.0f}s" in out
        assert "predicted outcome: breadth_waived" in out
        assert "declare-or-split" in out

    def test_cli_json_emits_the_same_record(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", lambda *a, **k: self._selection(4))
        assert sb.main(["--paths", "scripts/validate.py", "--json"]) == 0

        record = json.loads(capsys.readouterr().out)
        assert record["n_selected"] == 4
        assert record["allowance_s"] == sb.TEST_BASE_SECONDS
        assert record["predicted_outcome"] == "within_budget"
        assert record["declare_or_split"].startswith("declare-or-split")
        assert len(record["predicted_elapsed_s"]) == 2

    def test_cli_reads_plan_scope_rows(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path) -> None:
        seen: dict[str, Any] = {}

        def _derive(entries, **kwargs):
            seen["entries"] = list(entries)
            return self._selection(2)

        monkeypatch.setattr("scripts.checks.deps.affected_tests.derive_affected_tests", _derive)
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
