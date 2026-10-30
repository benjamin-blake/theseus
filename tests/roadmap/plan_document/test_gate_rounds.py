"""Tests for PlanDocument.gate_rounds (PLAN-critique-severity-convergence)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.roadmap.plan_document import GateRound, PlanDocument
from tests.fixtures.plan_document_helpers import _mutate

_HANDOFF = {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"}


def _v5(**overrides) -> dict:
    return _mutate(schema_version=5, handoff_policy=dict(_HANDOFF), **overrides)


def _row(gate: str = "plan-critique", round_: int = 1, verdict: str = "PROCEED", **extra) -> dict:
    return {"gate": gate, "round": round_, "verdict": verdict, **extra}


def test_gate_rounds_is_optional_and_defaults_empty() -> None:
    assert not PlanDocument.model_fields["gate_rounds"].is_required()
    assert PlanDocument.model_validate(_v5()).gate_rounds == []


def test_a_full_record_validates() -> None:
    rows = [
        _row("decision-scout", 1, "FLAGS_FOUND"),
        _row(round_=1, verdict="REVISE", blocking=2, nits=3),
        _row(round_=2, verdict="PROCEED", nits=1),
        _row(round_=3, verdict="PROCEED", gate_run_id="run-3"),
    ]
    doc = PlanDocument.model_validate(_v5(gate_rounds=rows))
    assert [(r.gate, r.round, r.verdict) for r in doc.gate_rounds][-1] == ("plan-critique", 3, "PROCEED")


@pytest.mark.parametrize(
    ("gate", "verdict"),
    [("plan-critique", "BLOCK"), ("plan-critique", "PROCEED-WITH-NITS"), ("decision-scout", "PROCEED")],
)
def test_verdict_must_belong_to_its_gate(gate: str, verdict: str) -> None:
    with pytest.raises(ValidationError, match="verdict must be one of"):
        GateRound.model_validate(_row(gate, 1, verdict))


def test_gate_is_one_of_the_two_plan_gates() -> None:
    with pytest.raises(ValidationError):
        GateRound.model_validate(_row("report-critique", 1, "PROCEED"))


@pytest.mark.parametrize(("verdict", "blocking"), [("REVISE", 0), ("PROCEED", 1)])
def test_plan_critique_verdict_follows_blocking_count(verdict: str, blocking: int) -> None:
    with pytest.raises(ValidationError, match="REVISE carries at least one blocking finding"):
        GateRound.model_validate(_row(verdict=verdict, blocking=blocking))


def test_nits_alone_are_a_proceed() -> None:
    assert GateRound.model_validate(_row(verdict="PROCEED", nits=4)).blocking == 0


def test_escalation_choice_requires_an_escalation() -> None:
    with pytest.raises(ValidationError, match="set escalated: true"):
        GateRound.model_validate(_row(verdict="REVISE", blocking=1, escalation_choice="one more round"))


def test_escalation_choice_is_the_five_choice_menu() -> None:
    with pytest.raises(ValidationError):
        GateRound.model_validate(_row(verdict="REVISE", blocking=1, escalated=True, escalation_choice="merge"))


@pytest.mark.parametrize("rounds", [[2], [1, 3], [2, 1], [1, 1]])
def test_rounds_number_one_to_n_without_gaps(rounds: list[int]) -> None:
    rows = [_row(round_=n, verdict="PROCEED") for n in rounds]
    with pytest.raises(ValidationError, match="must number 1..N"):
        PlanDocument.model_validate(_v5(gate_rounds=rows))


def test_negative_counts_are_refused() -> None:
    with pytest.raises(ValidationError):
        GateRound.model_validate(_row(nits=-1))


def test_gate_rounds_require_schema_version_five() -> None:
    with pytest.raises(ValidationError, match="gate_rounds requires schema_version 5"):
        PlanDocument.model_validate(_mutate(gate_rounds=[_row()]))
