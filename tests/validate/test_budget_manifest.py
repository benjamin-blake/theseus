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
from unittest.mock import patch

import pytest

from scripts.checks import registry
from scripts.checks.deps import affected_tests as at
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

_CEILING = _validate._FORCED_FULL_SUITE_CEILING_SECONDS


def _drive_pre(
    monkeypatch: pytest.MonkeyPatch,
    pre_sequence_stub,
    *,
    elapsed: float,
    ignore_budget: bool = False,
    stub_manifest: dict | None = None,
    extra_patches: tuple = (),
) -> int:
    """Drive scripts/validate.py --pre to completion and return its exit code.

    stub_manifest=None exercises the REAL derivation + emit_manifest (so the on-disk manifest is
    the run's own); passing one patches both, for the forced-full-suite branches that cannot be
    produced from an empty diff.
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
        patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(elapsed))),
    ]
    if stub_manifest is not None:
        selection = {"selected": [], "manifest": stub_manifest}
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
        assert budget["limit_s"] == float(_validate._FAST_TIER_BUDGET_SECONDS)
        assert budget["rec_filed"] is False

    def test_breach_records_a_breach_outcome_before_exiting_1(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        assert _drive_pre(monkeypatch, pre_sequence_stub, elapsed=400.0) == 1
        assert _budget_block()["outcome"] == "breach"

    def test_bypass_records_a_bypass_outcome(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        assert _drive_pre(monkeypatch, pre_sequence_stub, elapsed=400.0, ignore_budget=True) == 0
        assert _budget_block()["outcome"] == "bypass"

    def test_forced_waiver_records_forced_waived(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code = _drive_pre(monkeypatch, pre_sequence_stub, elapsed=400.0, stub_manifest={"full_suite_forced": True})
        assert code == 0
        budget = _budget_block()
        assert budget["outcome"] == "forced_waived"
        # The waiver is judged against the forced-run ceiling, so recording the fast-tier 300 here
        # would make elapsed_s/limit_s read as a 1.3x breach of a limit this run never had.
        assert budget["limit_s"] == float(_CEILING)

    def test_forced_ceiling_breach_records_its_own_outcome(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code = _drive_pre(
            monkeypatch, pre_sequence_stub, elapsed=float(_CEILING) + 100.0, stub_manifest={"full_suite_forced": True}
        )
        assert code == 1
        budget = _budget_block()
        assert budget["outcome"] == "forced_ceiling_breach"
        assert budget["limit_s"] == float(_CEILING)

    def test_phase_attribution_is_threaded_into_the_block(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """The block is only useful if validate.py hands it the SAME phase attribution the console
        diagnostic and the breach rec receive -- not an empty placeholder."""
        assert _drive_pre(monkeypatch, pre_sequence_stub, elapsed=400.0) == 1
        budget = _budget_block()
        assert budget["phase_times"], "phase_times must carry the run's measured per-phase seconds"
        assert budget["dominant_phase"] in budget["phase_times"]


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
