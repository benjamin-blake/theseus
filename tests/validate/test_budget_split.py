"""The fast tier's TWO budgets (Decision 182, amending Decision 153): an unwaivable NON-TEST
half asserted by subtraction on ``elapsed - phase_times['pytest_diff']``, and a breadth-derived
TEST-EXECUTION allowance asserted on that one subtracted phase.

Sibling mirror module of tests/validate/test_budget.py (which owns the pre-existing exit-code and
rec-filing behaviour) and tests/validate/test_budget_manifest.py (which owns the recorded block) --
the same one-source/several-mirror-modules precedent. Every case drives the REAL scripts/validate.py
main() with a synthetic phase shape and a stubbed selection manifest; none runs the tier.

Helpers are owned by this module (Decision 131: no import from another test_* module); the
phase-shaping driver mirrors the sibling's own module-level _drive_pre rather than importing it.
"""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import registry
from scripts.checks.deps import affected_tests as at
from scripts.checks.deps import selection_budget as sb
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

# The PR #1049 incident shape, read off the CI selection-manifest artifact: 263 selected modules,
# a 308.747s pytest_diff phase inside a 374.248s run, full_suite_forced False.
_INCIDENT_N = 263
_INCIDENT_TEST_S = 308.747
_INCIDENT_ELAPSED = 374.248


def _drive_pre(
    monkeypatch: pytest.MonkeyPatch,
    pre_sequence_stub,
    *,
    phases: dict[str, float],
    unattributed: float = 0.0,
    n_selected: int = 0,
    manifest: dict | None = None,
    ignore_budget: bool = False,
    checks: tuple[str, ...] = (),
) -> tuple[int, MagicMock, MagicMock]:
    """Drive scripts/validate.py --pre with a synthetic per-phase clock and return
    (exit_code, breach_rec_mock, bypass_rec_mock).

    ``phases`` maps a --pre step name to the seconds that step consumes; ``unattributed`` is time
    spent before the phase loop (inside the patched derivation), so it lands in elapsed while no
    phase carries it.
    """
    argv = ["validate", "--pre"] + (["--ignore-budget"] if ignore_budget else [])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("_VALIDATE_DEPTH", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("S3_LOG_BUCKET", raising=False)

    clock = {"t": 0.0}

    def _advance(step: str):
        def _fn(*_args: object, **_kwargs: object) -> None:
            clock["t"] += float(phases.get(step, 0.0))

        return _fn

    selection = {
        "selected": [f"tests/t{index}.py" for index in range(n_selected)],
        "manifest": dict(manifest if manifest is not None else {"full_suite_forced": False}),
    }

    def _derive(*_args: object, **_kwargs: object) -> dict:
        clock["t"] += unattributed
        return selection

    breach_rec, bypass_rec = MagicMock(), MagicMock()
    contexts = [
        patch("scripts.checks._common.get_changed_files", return_value=[]),
        patch("scripts.checks._common.get_status_aware_diff", return_value=[]),
        patch("scripts.checks._common.run", side_effect=_pre_mock_run),
        patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=checks)),
        patch("scripts.checks.deps.affected_tests.derive_affected_tests", side_effect=_derive),
        patch("scripts.checks.deps.affected_tests.emit_manifest"),
        patch("validate.run_lint_checks", side_effect=_advance("lint")),
        patch("validate.run_precommit_checks", side_effect=_advance("precommit_changed")),
        patch("validate.run_pytest_diff", side_effect=_advance("pytest_diff")),
        patch("validate.run_coverage_check", side_effect=_advance("verifier_coverage_report")),
        patch("validate._file_budget_breach_rec", breach_rec),
        patch("validate._file_budget_bypass_rec", bypass_rec),
        patch("time.monotonic", side_effect=lambda: clock["t"]),
    ]
    if "validate_vp_replay" in checks:
        contexts.append(
            patch(
                "scripts.checks.verification.validate_vp_replay.validate_vp_replay",
                side_effect=_advance("validate_vp_replay"),
            )
        )

    with ExitStack() as stack:
        for context in contexts:
            stack.enter_context(context)
        with pytest.raises(SystemExit) as exc_info:
            _validate.main()
    code = exc_info.value.code
    return (code if isinstance(code, int) else 0), breach_rec, bypass_rec


def _budget_block() -> dict:
    """The `budget` block from the manifest this run wrote (tests/conftest.py's autouse
    _isolate_selection_manifest fixture has redirected DEBUG_MANIFEST_PATH into tmp_path)."""
    return json.loads(at.DEBUG_MANIFEST_PATH.read_text(encoding="utf-8"))["budget"]


class TestNonTestHalfBudget:
    """The non-test half is absolute, unwaivable and TOTAL: it is asserted on elapsed minus the one
    subtracted test phase, so static time, the replay phase and unattributed time are all inside
    it, and no bypass, forced-scope, breadth or fallback path reaches it."""

    def test_non_test_breach_hard_fails_with_no_waiver_available(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub, tmp_path: Path
    ) -> None:
        summary = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        code, breach_rec, bypass_rec = _drive_pre(
            monkeypatch, pre_sequence_stub, phases={"lint": 250.0, "pytest_diff": 20.0}, n_selected=8
        )

        assert code == 1
        out = capsys.readouterr().out
        assert "Fast tier exceeded budget" in out
        assert "static" in out and "unattributed" in out
        assert sb.REPLAY_PHASE_NAME in out
        assert "Dominant non-test phase: lint" in out
        block = _budget_block()
        assert block["outcome"] == "non_test_breach"
        assert block["limit_s"] == sb.NON_TEST_BUDGET_SECONDS
        # Rec-free BY DESIGN, but not artifact-free: the arm mirrors its own titled section.
        breach_rec.assert_not_called()
        bypass_rec.assert_not_called()
        assert "Fast-tier non-test budget breached" in summary.read_text(encoding="utf-8")

    def test_ignore_budget_does_not_escape_non_test_breach(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code, breach_rec, bypass_rec = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 250.0, "pytest_diff": 20.0},
            n_selected=8,
            ignore_budget=True,
        )

        assert code == 1
        assert _budget_block()["outcome"] == "non_test_breach"
        breach_rec.assert_not_called()
        bypass_rec.assert_not_called()

    def test_non_test_half_at_exactly_the_budget_passes(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": sb.NON_TEST_BUDGET_SECONDS, "pytest_diff": 20.0},
            n_selected=8,
        )

        assert code == 0
        block = _budget_block()
        assert block["outcome"] == "within_budget"
        assert block["static_s"] == sb.NON_TEST_BUDGET_SECONDS

    def test_fully_unattributed_elapsed_is_a_non_test_breach(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """The residual the retired aggregate used to cover: a run in which NO phase carries any of
        the elapsed. A sum-of-named-phases budget would pass it, leaving it governed only by the
        1500s ceiling."""
        code, breach_rec, _bypass = _drive_pre(monkeypatch, pre_sequence_stub, phases={}, unattributed=400.0)

        assert code == 1
        block = _budget_block()
        assert block["outcome"] == "non_test_breach"
        assert block["unattributed_s"] == 400.0
        assert block["static_s"] == 0.0
        assert block["replay_s"] == 0.0
        breach_rec.assert_not_called()

    def test_green_replay_at_its_ratified_maximum_does_not_breach(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        """Domination, not exemption: validate_vp_replay's own sanctioned green maximum (its
        MAX_AGGREGATE_SECONDS plus one PER_STEP_TIMEOUT_SECONDS) sits INSIDE the unwaivable half and
        must still fit under it beside the worst measured static half -- while a replay phase its
        own guard has already hard-failed does breach, because nothing clamps replay time out."""
        green = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"validate_vp_replay": 149.0, "lint": 71.8, "pytest_diff": 20.0},
            n_selected=8,
            checks=("validate_vp_replay",),
        )
        assert green[0] == 0, "a 220.8s non-test half must fit under a budget that dominates the replay allowance"
        assert _budget_block()["replay_s"] == 149.0
        capsys.readouterr()

        red = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"validate_vp_replay": 260.0, "lint": 71.8, "pytest_diff": 20.0},
            n_selected=8,
            checks=("validate_vp_replay",),
        )
        assert red[0] == 1
        out = capsys.readouterr().out
        assert _budget_block()["outcome"] == "non_test_breach"
        assert f"{sb.REPLAY_ALLOWANCE_SECONDS:.0f}s" in out

    def test_non_test_identity_holds_on_a_mixed_shape(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 30.0, "validate_vp_replay": 40.0, "pytest_diff": 100.0},
            unattributed=12.0,
            n_selected=8,
            checks=("validate_vp_replay",),
        )

        assert code == 0
        block = _budget_block()
        elapsed = block["elapsed_s"]
        non_test_s = block["static_s"] + block["replay_s"] + block["unattributed_s"]
        assert non_test_s + block["test_s"] == pytest.approx(elapsed)
        assert elapsed - block["test_s"] == pytest.approx(non_test_s)
        assert block["unattributed_s"] == 12.0
        assert block["phase_count"] >= len(block["phase_times"])


class TestBreadthDerivedTestBudget:
    """The test half scales with MEASURED selection breadth, is capped by the derived
    CEILING - NON_TEST expression and by the on-disk census, and collapses to its base on a
    degraded derivation."""

    def test_incident_shape_passes_under_breadth_allowance(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        static_s = _INCIDENT_ELAPSED - _INCIDENT_TEST_S
        code, breach_rec, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": static_s, "pytest_diff": _INCIDENT_TEST_S},
            n_selected=_INCIDENT_N,
        )

        assert code == 0
        block = _budget_block()
        assert block["outcome"] == "breadth_waived"
        assert block["waiver_cause"] == "selection_breadth"
        assert block["n_selected"] == _INCIDENT_N
        assert block["limit_s"] == sb.PER_MODULE_SECONDS * _INCIDENT_N
        breach_rec.assert_not_called()
        capsys.readouterr()

        # The same shape plus the measured same-commit spread (454s of runner luck) still passes.
        lucky, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": static_s, "pytest_diff": 454.0 - static_s},
            n_selected=_INCIDENT_N,
        )
        assert lucky == 0
        assert _budget_block()["outcome"] == "breadth_waived"

    def test_same_selection_with_a_600s_test_half_still_hard_fails(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code, breach_rec, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 600.0},
            n_selected=_INCIDENT_N,
        )

        assert code == 1
        assert "Fast tier exceeded budget" in capsys.readouterr().out
        block = _budget_block()
        assert block["outcome"] == "breach"
        assert block["limit_s"] == sb.PER_MODULE_SECONDS * _INCIDENT_N
        breach_rec.assert_called_once()

    def test_breadth_caused_overrun_warns_and_passes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code, breach_rec, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": sb.TEST_BASE_SECONDS + 40.0},
            n_selected=200,
        )

        assert code == 0
        out = capsys.readouterr().out
        assert "selection_breadth" in out
        assert "200 test module(s)" in out
        assert f"{sb.PER_MODULE_SECONDS * 200:.0f}s" in out
        assert "Fast tier exceeded budget" not in out
        assert _budget_block()["waiver_cause"] == "selection_breadth"
        breach_rec.assert_not_called()

    def test_breadth_run_over_the_ceiling_still_hard_fails(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        """The breadth allowance never grows past CEILING - NON_TEST, so a test half above that cap
        hard-fails even though the selection is wide enough to ask for more."""
        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS
        code, breach_rec, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": cap + 100.0},
            n_selected=10**6,
        )

        assert code == 1
        assert "Fast tier exceeded budget" in capsys.readouterr().out
        block = _budget_block()
        assert block["outcome"] == "breach"
        # Non-vacuous: the run must have been judged against the BREADTH-derived limit (bounded by
        # the census clamp and, above it, by the derived cap) -- not against a flat aggregate.
        assert block["limit_s"] == sb.test_execution_allowance(10**6, census=sb.count_test_modules())
        assert block["limit_s"] <= cap
        assert block["n_selected"] == 10**6
        breach_rec.assert_called_once()

    def test_derivation_failure_gets_no_breadth_relief(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code, breach_rec, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 400.0},
            n_selected=_INCIDENT_N,
            manifest={"full_suite_forced": False, "fallback": True, "fallback_reason": "RuntimeError('boom')"},
        )

        assert code == 1
        out = capsys.readouterr().out
        assert "Fast tier exceeded budget" in out
        assert "affected-set derivation fell back" in out
        block = _budget_block()
        assert block["outcome"] == "breach"
        assert block["limit_s"] == sb.TEST_BASE_SECONDS
        assert block["waiver_cause"] is None
        breach_rec.assert_called_once()

    def test_inflated_selection_cannot_raise_its_own_allowance(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        census = sb.count_test_modules()
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 200.0},
            n_selected=10**6,
        )

        assert code == 0
        assert _budget_block()["limit_s"] == sb.test_execution_allowance(census, census=census)


class TestLocalPrediction:
    """A local run prints the measured breadth and the CI-predicted range beside its own wall
    clock, and labels the local number advisory -- enforcement is unchanged."""

    def test_local_run_prints_breadth_and_ci_prediction(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code, _breach, _bypass = _drive_pre(
            monkeypatch, pre_sequence_stub, phases={"lint": 5.0, "pytest_diff": 10.0}, n_selected=128
        )

        assert code == 0
        out = capsys.readouterr().out
        low, high = sb.predict_ci_elapsed(128)
        assert "128 test module(s) selected" in out
        assert f"{low:.0f}-{high:.0f}s" in out
        assert "ADVISORY" in out
