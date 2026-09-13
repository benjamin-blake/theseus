"""The selection manifest's `budget` block -- CI budget-breach observability with zero new
workflow YAML and zero credential surface (D2-2 stage 1).

scripts/validate.py's trailing budget-assertion scaffold attaches a machine-readable budget
verdict to the already-derived manifest and re-writes it locally, so the artifact ci.yml's
pr-validate job already uploads (logs/debug/selection-manifest.json, `if: always()`) carries the
outcome alongside `timings`.

The block exists only when that trailing scaffold is REACHED -- not on "every --pre run". An
abort in an earlier phase, or validate.py's CI hard-reject of --ignore-budget, leaves no `budget`
key at all: a distinguishable third state ("run aborted"), pinned by
test_ci_ignore_budget_reject_writes_no_manifest_at_all below.

Sibling of tests/validate/test_budget.py, which owns the assertion's exit-code and rec-filing
behaviour; its TestBudgetBreachCiTelemetry node id is pinned by a graduated verification-registry
shard, so budget-block coverage lands here rather than by reshaping that file.
"""

from __future__ import annotations

import itertools
import json
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import _budget_recs, registry
from scripts.checks.deps import affected_tests as at
from scripts.checks.deps import selection_budget as sb
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

_CEILING = _validate._FORCED_FULL_SUITE_CEILING_SECONDS

# Decision 182 repair, not a relaxation: a run with every phase at 0.0 is one whose whole elapsed is
# UNATTRIBUTED, which the unwaivable non-test arm now claims. Cases naming a TEST-half arm therefore
# place their elapsed inside a real dominating pytest_diff phase via _drive_pre's shaping hook. A
# test half above CEILING - NON_TEST exceeds every reachable allowance, so a case that must breach
# does so whatever breadth the run's own derivation reports.
_UNREACHABLE_TEST_ALLOWANCE = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS + 100.0


def _drive_pre(
    monkeypatch: pytest.MonkeyPatch,
    pre_sequence_stub,
    *,
    elapsed: float,
    ignore_budget: bool = False,
    stub_manifest: dict | None = None,
    extra_patches: tuple = (),
    test_phase_s: float | None = None,
    n_selected: int = 0,
) -> int:
    """Drive scripts/validate.py --pre to completion and return its exit code.

    stub_manifest=None exercises the REAL derivation + emit_manifest (so the on-disk manifest is
    the run's own); passing one patches both, for the forced-full-suite branches that cannot be
    produced from an empty diff.

    test_phase_s (Decision 182) places that many seconds of ``elapsed`` inside the pytest_diff
    phase and the remainder inside lint, so a case can put its elapsed in the half whose arm it
    names; None keeps the flat clock the sub-budget cases still want.
    """
    argv = ["validate", "--pre"] + (["--ignore-budget"] if ignore_budget else [])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("_VALIDATE_DEPTH", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("S3_LOG_BUCKET", raising=False)

    contexts = [
        patch("scripts.checks._common.get_changed_files", return_value=[]),
        patch("scripts.checks._common.run", side_effect=_pre_mock_run),
        patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
        patch("validate._file_budget_breach_rec"),
        patch("validate._file_budget_bypass_rec"),
    ]
    if test_phase_s is None:
        contexts.append(patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(elapsed))))
    else:
        clock = {"t": 0.0}

        def _advance(seconds: float):
            def _fn(*_args: object, **_kwargs: object) -> None:
                clock["t"] += float(seconds)

            return _fn

        contexts += [
            patch("validate.run_pytest_diff", side_effect=_advance(test_phase_s)),
            patch("validate.run_lint_checks", side_effect=_advance(elapsed - test_phase_s)),
            patch("time.monotonic", side_effect=lambda: clock["t"]),
        ]
    if stub_manifest is not None:
        selection = {"selected": [f"tests/t{index}.py" for index in range(n_selected)], "manifest": stub_manifest}
        contexts += [
            patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=selection),
            patch("scripts.checks.deps.affected_tests.emit_manifest"),
        ]
    contexts += list(extra_patches)

    with ExitStack() as stack:
        for context in contexts:
            stack.enter_context(context)
        with pytest.raises(SystemExit) as exc_info:
            _validate.main()
    return int(exc_info.value.code)


def _budget_block() -> dict:
    """The `budget` block from the manifest this run actually wrote (the autouse
    _isolate_selection_manifest fixture has redirected DEBUG_MANIFEST_PATH into tmp_path)."""
    return json.loads(at.DEBUG_MANIFEST_PATH.read_text(encoding="utf-8"))["budget"]


class TestBudgetBlockPerOutcome:
    """One `budget` row per terminating branch of the budget assertion, so an ingester can count
    breaches AND compute a rate -- `within_budget` is the denominator, not dead weight."""

    def test_within_budget_run_records_a_within_budget_outcome(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        assert _drive_pre(monkeypatch, pre_sequence_stub, elapsed=60.0) == 0
        budget = _budget_block()
        assert budget["outcome"] == "within_budget"
        # Decision 182: the run is judged against the breadth-derived allowance for the selection it
        # actually made, not against the floor total -- asserted as the wiring it is.
        assert budget["limit_s"] == sb.test_execution_allowance(budget["n_selected"], census=sb.count_test_modules())
        assert budget["rec_filed"] is False

    def test_breach_records_a_breach_outcome_before_exiting_1(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        elapsed = _UNREACHABLE_TEST_ALLOWANCE + 100.0
        code = _drive_pre(monkeypatch, pre_sequence_stub, elapsed=elapsed, test_phase_s=_UNREACHABLE_TEST_ALLOWANCE)
        assert code == 1
        assert _budget_block()["outcome"] == "breach"

    def test_bypass_records_a_bypass_outcome(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        elapsed = _UNREACHABLE_TEST_ALLOWANCE + 100.0
        code = _drive_pre(
            monkeypatch, pre_sequence_stub, elapsed=elapsed, ignore_budget=True, test_phase_s=_UNREACHABLE_TEST_ALLOWANCE
        )
        assert code == 0
        assert _budget_block()["outcome"] == "bypass"

    def test_forced_waiver_records_forced_waived(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=400.0,
            stub_manifest={"full_suite_forced": True},
            test_phase_s=380.0,
        )
        assert code == 0
        budget = _budget_block()
        assert budget["outcome"] == "forced_waived"
        # The waiver is judged against the forced-run ceiling, so recording the fast-tier 300 here
        # would make elapsed_s/limit_s read as a 1.3x breach of a limit this run never had.
        assert budget["limit_s"] == float(_CEILING)

    def test_forced_ceiling_breach_records_its_own_outcome(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=float(_CEILING) + 100.0,
            stub_manifest={"full_suite_forced": True},
            test_phase_s=float(_CEILING),
        )
        assert code == 1
        budget = _budget_block()
        assert budget["outcome"] == "forced_ceiling_breach"
        assert budget["limit_s"] == float(_CEILING)

    def test_phase_attribution_is_threaded_into_the_block(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """The block is only useful if validate.py hands it the SAME phase attribution the console
        diagnostic and the breach rec receive -- not an empty placeholder."""
        elapsed = _UNREACHABLE_TEST_ALLOWANCE + 100.0
        code = _drive_pre(monkeypatch, pre_sequence_stub, elapsed=elapsed, test_phase_s=_UNREACHABLE_TEST_ALLOWANCE)
        assert code == 1
        budget = _budget_block()
        assert budget["phase_times"], "phase_times must carry the run's measured per-phase seconds"
        assert budget["dominant_phase"] in budget["phase_times"]

    def test_non_test_breach_records_its_own_outcome(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """The seventh row (Decision 182): the unwaivable half's own outcome, judged against its own
        limit -- so the per-outcome census stays complete."""
        code = _drive_pre(monkeypatch, pre_sequence_stub, elapsed=400.0, test_phase_s=20.0)
        assert code == 1
        budget = _budget_block()
        assert budget["outcome"] == "non_test_breach"
        assert budget["limit_s"] == sb.NON_TEST_BUDGET_SECONDS

    def test_breadth_waived_records_its_own_outcome(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """The eighth row: a warn-and-pass whose cause is measured breadth rather than forced scope."""
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=sb.TEST_BASE_SECONDS + 60.0,
            stub_manifest={"full_suite_forced": False},
            test_phase_s=sb.TEST_BASE_SECONDS + 40.0,
            n_selected=200,
        )
        assert code == 0
        budget = _budget_block()
        assert budget["outcome"] == "breadth_waived"
        assert budget["waiver_cause"] == "selection_breadth"
        assert budget["limit_s"] == sb.PER_MODULE_SECONDS * 200


class TestBudgetBlockCarriesTheSplit:
    """The recorded block carries the split's seven new keys ALONGSIDE every pre-existing key --
    and the merge happens at validate.py's own call site, which is what keeps
    scripts/checks/_budget_recs.py byte-identical (build_budget_record is still called with exactly
    its existing six keyword arguments)."""

    _PRE_EXISTING_KEYS = {
        "outcome",
        "elapsed_s",
        "elapsed_min",
        "limit_s",
        "dominant_phase",
        "phase_times",
        "diff_file_count",
        "diff_manifest",
        "branch",
        "run_id",
        "repository",
        "ci",
        "rec_filed",
        "rec_skipped_reason",
    }
    _NEW_KEYS = {"n_selected", "static_s", "test_s", "replay_s", "unattributed_s", "phase_count", "waiver_cause"}

    def test_block_carries_the_split_without_touching_the_record_builder(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        spy = MagicMock(side_effect=_budget_recs.build_budget_record)
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=100.0,
            stub_manifest={"full_suite_forced": False},
            test_phase_s=60.0,
            n_selected=12,
            extra_patches=(patch("validate.build_budget_record", spy),),
        )
        assert code == 0

        budget = _budget_block()
        assert self._PRE_EXISTING_KEYS <= set(budget), "no pre-existing key may be dropped or renamed"
        assert self._NEW_KEYS <= set(budget)
        assert budget["n_selected"] == 12
        assert budget["test_s"] == 60.0
        assert budget["static_s"] == 40.0
        assert budget["replay_s"] == 0.0
        assert budget["unattributed_s"] == 0.0
        assert budget["waiver_cause"] is None
        # PRE-truncation: phase_times is truncated to the 10 slowest, so phase_count is what keeps
        # static_s re-derivable from the same artifact.
        assert budget["phase_count"] >= len(budget["phase_times"])
        assert budget["static_s"] + budget["test_s"] + budget["replay_s"] + budget["unattributed_s"] == pytest.approx(
            budget["elapsed_s"]
        )

        spy.assert_called_once()
        assert set(spy.call_args.kwargs) == {
            "outcome",
            "elapsed_s",
            "limit_s",
            "dominant_phase",
            "diff_manifest",
            "phase_times",
        }
        assert not spy.call_args.args


class TestNewOutcomesFileNoRec:
    """The round-4 narrowing, asserted mechanically: neither new outcome touches the breach-rec
    stream, so _REC_FILING_OUTCOMES keeps its two rows and the retired 'limit 5m' wording is never
    emitted by a new arm."""

    @staticmethod
    def _rec_spies() -> tuple[MagicMock, MagicMock]:
        return MagicMock(), MagicMock()

    def test_non_test_breach_files_no_rec(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        breach, bypass = self._rec_spies()
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=400.0,
            test_phase_s=20.0,
            extra_patches=(
                patch("validate._file_budget_breach_rec", breach),
                patch("validate._file_budget_bypass_rec", bypass),
            ),
        )
        assert code == 1
        budget = _budget_block()
        assert budget["outcome"] == "non_test_breach"
        assert (budget["rec_filed"], budget["rec_skipped_reason"]) == (False, "no_rec_for_outcome")
        breach.assert_not_called()
        bypass.assert_not_called()

    def test_breadth_waived_files_no_rec(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        breach, bypass = self._rec_spies()
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=sb.TEST_BASE_SECONDS + 60.0,
            stub_manifest={"full_suite_forced": False},
            test_phase_s=sb.TEST_BASE_SECONDS + 40.0,
            n_selected=200,
            extra_patches=(
                patch("validate._file_budget_breach_rec", breach),
                patch("validate._file_budget_bypass_rec", bypass),
            ),
        )
        assert code == 0
        budget = _budget_block()
        assert budget["outcome"] == "breadth_waived"
        assert (budget["rec_filed"], budget["rec_skipped_reason"]) == (False, "no_rec_for_outcome")
        breach.assert_not_called()
        bypass.assert_not_called()

    def test_rec_filing_outcomes_still_has_exactly_its_two_producers(self) -> None:
        assert _budget_recs._REC_FILING_OUTCOMES == ("breach", "bypass")


class TestBudgetBlockWriteIsNeverLoadBearing:
    """Decision 55 loud-skip: the budget verdict must not depend on an observability write, so an
    OSError from the late write can never change the assertion's exit code."""

    @staticmethod
    def _raising_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    def test_write_failure_leaves_a_breach_exiting_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=400.0,
            stub_manifest={"full_suite_forced": False},
            extra_patches=(patch("scripts.checks.deps.affected_tests.write_manifest", side_effect=self._raising_write),),
            test_phase_s=380.0,
        )
        assert code == 1
        assert "loud skip" in capsys.readouterr().out.lower()

    def test_write_failure_leaves_a_within_budget_run_exiting_0(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        code = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            elapsed=60.0,
            stub_manifest={"full_suite_forced": False},
            extra_patches=(patch("scripts.checks.deps.affected_tests.write_manifest", side_effect=self._raising_write),),
        )
        assert code == 0


class TestBudgetBlockIsNotUniversal:
    """Honesty pin (do NOT claim 'every --pre run'): the block exists only when the trailing
    budget-assertion scaffold is reached."""

    def test_ci_ignore_budget_reject_writes_no_manifest_at_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _validate.main()

        assert exc_info.value.code == 1
        assert not at.DEBUG_MANIFEST_PATH.exists(), "an aborted run must leave no manifest, hence no budget block"
