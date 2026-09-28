"""The fast tier's THREE budgets (Decision 208, amending Decision 182): an unwaivable NON-TEST
half asserted by subtraction on ``elapsed - phase_times['pytest_diff'] - escalation_carve_out``,
a measured-cost TEST-EXECUTION allowance asserted on the one subtracted phase, and a governed
PRE-COMMIT ESCALATION allowance carved from the non-test half.

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
from scripts.checks.deps import module_cost_table as mct
from scripts.checks.deps import selection_budget as sb
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

# The PR #1049 incident shape, read off the CI selection-manifest artifact: 263 selected modules,
# a 308.747s pytest_diff phase inside a 374.248s run, full_suite_forced False.
_INCIDENT_N = 263
_INCIDENT_TEST_S = 308.747
_INCIDENT_ELAPSED = 374.248


@pytest.fixture(autouse=True)
def _pin_cost_table_absent(monkeypatch: pytest.MonkeyPatch):
    """No allowance-asserting test in this module depends on the live base ref's table state --
    pin the merge-base read to the legacy `absent` arm (Decision 208)."""
    monkeypatch.setattr(mct, "read_at_base_ref", lambda root: mct.CostTableRead("absent", {}, 0.0))


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
    precommit_escalated: bool = False,
    cost_table_ok_s: float | None = None,
) -> tuple[int, MagicMock, MagicMock]:
    """Drive scripts/validate.py --pre with a synthetic per-phase clock and return
    (exit_code, breach_rec_mock, bypass_rec_mock).

    ``phases`` maps a --pre step name to the seconds that step consumes; ``unattributed`` is time
    spent before the phase loop (inside the patched derivation), so it lands in elapsed while no
    phase carries it. ``precommit_escalated`` stubs run_precommit_checks' RETURNED decision
    (Decision 208); ``cost_table_ok_s``, when given, overrides this module's autouse `absent` pin
    for this one call with a status-ok table whose selection_cost is that fixed value.
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

    def _advance_precommit(*_args: object, **_kwargs: object) -> bool:
        clock["t"] += float(phases.get("precommit_changed", 0.0))
        return precommit_escalated

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
        patch("validate.run_precommit_checks", side_effect=_advance_precommit),
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
    if cost_table_ok_s is not None:
        contexts.append(patch.object(mct, "read_at_base_ref", lambda root: mct.CostTableRead("ok", {}, 0.0)))
        contexts.append(patch.object(mct, "selection_cost", lambda selected, read, root: cost_table_ok_s))

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
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": sb.NON_TEST_BUDGET_SECONDS + 10.0, "pytest_diff": 20.0},
            n_selected=8,
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
            phases={"lint": sb.NON_TEST_BUDGET_SECONDS + 10.0, "pytest_diff": 20.0},
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
        """Domination, not exemption: validate_vp_replay's own sanctioned green maximum
        (MAX_AGGREGATE_SECONDS alone, under the shared-aggregate deadline model -- the flat
        PER_STEP_TIMEOUT_SECONDS term this used to add on top is retired) sits INSIDE the
        unwaivable half and must still fit under it beside the worst measured static half -- while
        a replay phase its own guard has already hard-failed does breach, because nothing clamps
        replay time out."""
        # The new governed static worst + unattributed max (131.8 + 10.0 = 141.8), so this case
        # exercises the RE-DERIVED domination at 270 rather than the retired 71.8s worst.
        governed_static_worst = 141.8
        green_replay_seconds = sb.REPLAY_ALLOWANCE_SECONDS - 1.0
        green = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"validate_vp_replay": green_replay_seconds, "lint": governed_static_worst, "pytest_diff": 20.0},
            n_selected=8,
            checks=("validate_vp_replay",),
        )
        non_test_half = green_replay_seconds + governed_static_worst
        assert non_test_half < sb.NON_TEST_BUDGET_SECONDS
        assert green[0] == 0, (
            f"a {non_test_half:.1f}s non-test half must fit under a budget that dominates the replay allowance"
        )
        assert _budget_block()["replay_s"] == green_replay_seconds
        capsys.readouterr()

        red = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"validate_vp_replay": 260.0, "lint": governed_static_worst, "pytest_diff": 20.0},
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
        cap = sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS
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
        monkeypatch.setattr(sb, "count_test_modules", lambda root=None: 263)
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 200.0},
            n_selected=10**6,
        )

        assert code == 0
        limit_s = _budget_block()["limit_s"]
        assert limit_s == sb.PER_MODULE_SECONDS * 263
        assert limit_s < sb.CEILING_SECONDS - sb.NON_TEST_BUDGET_SECONDS - sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS


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


class TestEscalationCarveOut:
    """The escalated pre-commit phase is carved from the unwaivable half only when this run
    actually escalated (the observed run_precommit_checks return, never re-evaluated), capped at
    PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS; excess above the allowance stays unwaivable
    (Decision 208)."""

    def test_escalated_run_within_the_carved_allowance_passes(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        other_static = sb.NON_TEST_BUDGET_SECONDS - 50.0
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": other_static, "precommit_changed": 100.0, "pytest_diff": 20.0},
            n_selected=8,
            precommit_escalated=True,
        )
        assert code == 0
        block = _budget_block()
        assert block["outcome"] == "within_budget"
        assert block["precommit_escalated"] is True
        assert block["escalation_s"] == 100.0

    def test_the_same_run_not_escalated_hard_fails_non_test_breach(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        other_static = sb.NON_TEST_BUDGET_SECONDS - 50.0
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": other_static, "precommit_changed": 100.0, "pytest_diff": 20.0},
            n_selected=8,
            precommit_escalated=False,
        )
        assert code == 1
        block = _budget_block()
        assert block["outcome"] == "non_test_breach"
        assert block["precommit_escalated"] is False
        assert block["escalation_s"] == 0.0

    def test_discriminating_excess_case(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """An uncapped carve would leave NON_TEST - 20 (pass); the capped carve leaves NON_TEST + 10
        and must breach -- the case the allowance CAP, not merely the escalation flag, discriminates."""
        other_static = sb.NON_TEST_BUDGET_SECONDS - 20.0
        escalated_precommit_s = sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS + 30.0
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": other_static, "precommit_changed": escalated_precommit_s, "pytest_diff": 20.0},
            n_selected=8,
            precommit_escalated=True,
        )
        assert code == 1
        block = _budget_block()
        assert block["outcome"] == "non_test_breach"
        assert block["escalation_s"] == sb.PRECOMMIT_ESCALATION_ALLOWANCE_SECONDS

    def test_non_vacuous_cost_path_is_recorded_and_differs_from_legacy(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        n_selected = 8
        cost_c = 400.0
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 50.0},
            n_selected=n_selected,
            cost_table_ok_s=cost_c,
        )
        assert code == 0
        block = _budget_block()
        expected = sb.cost_based_allowance(cost_c, n_selected)
        assert block["limit_s"] == expected
        assert expected != sb.test_execution_allowance(n_selected, census=sb.count_test_modules())
        assert block["cost_s"] == cost_c
        assert block["cost_table_status"] == "ok"

    def test_cost_ratio_above_recorded_envelope_prints_an_advisory(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 100.0},
            n_selected=8,
            cost_table_ok_s=1.0,
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "ADVISORY: this run's cost ratio" in out
        assert "RECORDED_K_MIN" in out

    def test_unreadable_status_collapses_to_test_base(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """A WIDE selection (n_selected=200) discriminates this from the legacy breadth path: the
        legacy formula would give PER_MODULE_SECONDS * 200 = 400s here, well above TEST_BASE_SECONDS
        -- so a case that collapses to 180s regardless proves derivation_ok was actually forced
        False on `unreadable`, not merely that a small selection happened to floor out anyway."""
        monkeypatch.setattr(mct, "read_at_base_ref", lambda root: mct.CostTableRead("unreadable", {}, 0.0))
        code, _breach, _bypass = _drive_pre(
            monkeypatch,
            pre_sequence_stub,
            phases={"lint": 20.0, "pytest_diff": 50.0},
            n_selected=200,
        )
        assert code == 0
        block = _budget_block()
        assert block["limit_s"] == sb.TEST_BASE_SECONDS
        assert block["limit_s"] != sb.test_execution_allowance(200, census=sb.count_test_modules())
        assert block["cost_table_status"] == "unreadable"
        assert block["cost_s"] is None
