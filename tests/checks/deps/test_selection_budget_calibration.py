"""Evidence-driven calibration tests over the recorded CI population (Decision 208, VP steps 3-4).

Reads "tests/fixtures/fast_tier_calibration_series.json" and "config/agent/fast_tier/module_costs.json"
as LITERAL strings (never through a constant) so a table-only or fixture-only diff selects this
module through Decision 135's data-edge channel (proved by VP step 9's affected-set probe).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import pytest

from scripts.checks.deps import module_cost_table as mct
from scripts.checks.deps import selection_budget as sb

_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = "tests/fixtures/fast_tier_calibration_series.json"
_TABLE_PATH = "config/agent/fast_tier/module_costs.json"

_ESCALATION_ALLOWANCE_S = 120.0


def _fixture() -> dict:
    return json.loads((_ROOT / _FIXTURE_PATH).read_text(encoding="utf-8"))


def _table_read() -> mct.CostTableRead:
    table = json.loads((_ROOT / _TABLE_PATH).read_text(encoding="utf-8"))
    costs = {str(path): float(seconds) for path, seconds in table["modules"].items()}
    values = list(costs.values())
    default_cost = statistics.quantiles(values, n=10, method="inclusive")[8]
    return mct.CostTableRead("ok", costs, default_cost)


def _cost_of(run: dict, modules: list[str], read: mct.CostTableRead) -> float:
    paths = [modules[i] for i in run["selected"]]
    return mct.selection_cost(paths, read, _ROOT, require_on_disk=False)


def _overhead(n_selected: int) -> float:
    return sb.PREPASS_FIXED_SECONDS + sb.PREPASS_PER_MODULE_SECONDS * n_selected


def _single_s(run: dict) -> float:
    """The estimated single-invocation test half: test_s directly for a single-invocation run,
    or primary_session_s plus the collect-only prepass term for a reactive (double-invoked) run."""
    if run.get("reactive_two_invocation"):
        return float(run["primary_session_s"]) + _overhead(run["n_selected"])
    return float(run["test_s"])


class TestCostModelCalibration:
    """RECORDED_K_MIN, NOISE_MARGIN, COST_COEFFICIENT and the predictor constants are each pinned
    to the committed calibration series and cost table -- a regenerated table or series that moves
    them without a matching constant change turns this class red (Decision 181/201)."""

    def test_k_min_and_noise_margin_derive_the_coefficient(self) -> None:
        d = _fixture()
        modules = d["modules"]
        read = _table_read()
        green = [r for r in d["runs"] if r.get("pytest_final_green") and r.get("primary_session_s") is not None]
        assert len(green) == 98

        candidates = []
        for r in green:
            cost = _cost_of(r, modules, read)
            if cost <= 0:
                continue
            single_s = _single_s(r)
            if single_s > sb.TEST_BASE_SECONDS:
                candidates.append((single_s - _overhead(r["n_selected"])) / cost)
        assert candidates
        k_min = max(candidates)

        by_run_id: dict[int, list[float]] = {}
        for r in d["runs"]:
            session = r.get("primary_session_s")
            if session is not None:
                by_run_id.setdefault(r["run_id"], []).append(float(session))
        spreads = [
            max(sessions) / min(sessions) for sessions in by_run_id.values() if len(sessions) >= 2 and min(sessions) >= 60.0
        ]
        assert spreads
        noise_margin = max(spreads)

        assert sb.RECORDED_K_MIN == round(k_min, 3)
        assert sb.NOISE_MARGIN == round(noise_margin, 3)
        assert sb.COST_COEFFICIENT == math.ceil(sb.RECORDED_K_MIN * sb.NOISE_MARGIN * 10) / 10
        assert sb.COST_COEFFICIENT >= sb.RECORDED_K_MIN

    def test_predict_cost_ratio_low_is_the_median_ratio(self) -> None:
        d = _fixture()
        modules = d["modules"]
        read = _table_read()
        green = [r for r in d["runs"] if r.get("pytest_final_green") and r.get("primary_session_s") is not None]

        ratios = []
        for r in green:
            cost = _cost_of(r, modules, read)
            if cost <= 0:
                continue
            single_s = _single_s(r)
            ratios.append((single_s - _overhead(r["n_selected"])) / cost)
        assert ratios
        assert sb.PREDICT_COST_RATIO_LOW == round(statistics.median(ratios), 2)

    def test_predict_non_test_bounds_are_the_green_governed_median_and_max(self) -> None:
        d = _fixture()
        success = [r for r in d["runs"] if r["job_conclusion"] == "success"]
        assert success

        def _governed_non_test(r: dict) -> float:
            non_test = r["elapsed_s"] - r["test_s"]
            pc = r["phase_times_top10"].get(sb.PRECOMMIT_PHASE_NAME, 0.0)
            carve = min(pc, _ESCALATION_ALLOWANCE_S) if r.get("precommit_escalated") else 0.0
            return non_test - carve

        values = [_governed_non_test(r) for r in success]
        assert sb._PREDICT_NON_TEST_LOW == round(statistics.median(values), 3)
        assert sb._PREDICT_NON_TEST_HIGH == round(max(values), 3)


class TestCompositionAwarePrediction:
    """rec-3677's rewritten acceptance node: the recorded pair ranks correctly by composition, and
    the slow selection is not within_budget; the legacy linear predictor ranks them backwards."""

    def test_slow_selection_predicts_higher_than_fast_despite_fewer_modules(self) -> None:
        d = _fixture()
        modules = d["modules"]
        read = _table_read()
        fast = d["incidents"]["rec-3677-fast"]
        slow = d["incidents"]["rec-3677-slow"]
        assert slow["n_selected"] < fast["n_selected"]

        fast_cost = _cost_of(fast, modules, read)
        slow_cost = _cost_of(slow, modules, read)

        _fast_low, fast_high = sb.predict_test_half(fast["n_selected"], cost_s=fast_cost)
        _slow_low, slow_high = sb.predict_test_half(slow["n_selected"], cost_s=slow_cost)
        assert slow_high > fast_high

        slow_verdict = sb.classify(
            non_test_s=0.0,
            static_s=0.0,
            test_s=slow_high,
            replay_s=0.0,
            elapsed=slow_high,
            n_selected=slow["n_selected"],
            forced=False,
            derivation_ok=True,
            cost_s=slow_cost,
        )
        assert slow_verdict.outcome != "within_budget"

        # The legacy linear predictor (module count alone) ranks the pair the OTHER way.
        assert sb.PER_MODULE_SECONDS * fast["n_selected"] > sb.PER_MODULE_SECONDS * slow["n_selected"]


class TestRecordedIncidents:
    """PR #1157's (rec-3796) and PR #1264's (rec-4035) recorded single-invocation test halves fit
    the new allowance -- their breaches were the ulid double run."""

    @pytest.mark.parametrize("incident_key,run_id", [("rec-3796-pr1157", None), (None, 36076407848)])
    def test_incident_fits_the_new_allowance(self, incident_key: str | None, run_id: int | None) -> None:
        d = _fixture()
        modules = d["modules"]
        read = _table_read()
        run = d["incidents"][incident_key] if incident_key else next(r for r in d["runs"] if r["run_id"] == run_id)

        cost = _cost_of(run, modules, read)
        single_s = float(run["primary_session_s"]) + _overhead(run["n_selected"])
        allowance = sb.cost_based_allowance(cost, run["n_selected"])
        assert single_s <= allowance
