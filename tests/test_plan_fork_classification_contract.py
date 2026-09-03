"""Content contract for PLAN-step-6b-fork-classification (audit remedy B2-R4, finding PDB-03,
rec-3042).

Four surfaces carry one non-contradictory fork-classification rule and Step 6b relay shape:
docs/contracts/overseer-dispatch.yaml (the nine-field autonomy_tiers.plan_fork_classification
section, the fourth `step-6b-confirmation` gate value declared across
gate_request_trampoline's request_schema / gate_run_id / pending_gates, its own
trampoline_sequence stage, and the corrected injected dispatch header + gate_run_id.provenance
scoping), .claude/commands/plan.md (Step 6b's presentation shape and contract pointer),
.claude/skills/planning/SKILL.md (the pointer-not-payload Confirmation Gate section), and
.claude/skills/overseer/SKILL.md (the dispatched carrier, replacing the retired "no overseer
mediation needed" claim rec-3042 identified). Each surface gets a positive case (asserts against
the real artefact) and at least one negative case (asserts the SAME helper fails against a
mutated copy with its clause removed or the retired phrasing reinstated) -- proving the positive
case is not vacuous.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "docs" / "contracts" / "overseer-dispatch.yaml"
PLAN_MD_PATH = REPO_ROOT / ".claude" / "commands" / "plan.md"
PLANNING_SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "planning" / "SKILL.md"
OVERSEER_SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "overseer" / "SKILL.md"

_RETIRED_PHRASE = "no overseer mediation needed"


def _load_contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _plan_md_step6_block(text: str) -> str:
    return text[text.index("## Step 6") : text.index("## Step 7")]


def _planning_confirmation_gate_block(text: str) -> str:
    return text[text.index("## Confirmation Gate (Workflow Step 6b)") : text.index("## Create Branch (Workflow Step 7)")]


def _hop_flow(doc: dict[str, Any]) -> list[str]:
    stages = [s for s in doc["trampoline_sequence"]["stages"] if s.get("gate") == "step-6b-confirmation"]
    assert stages, "trampoline_sequence.stages must carry its own step-6b-confirmation entry"
    stage = stages[0]
    return [str(stage.get("fires_at") or "")] + [str(x) for x in (stage.get("flow") or [])]


def _exact_header(doc: dict[str, Any]) -> str:
    return "".join(str(sig.get("exact_header") or "") for sig in doc["subagent_detection"]["signals"])


# ---------------------------------------------------------------------------
# Assertion helpers -- each operates on parsed dict or raw text so it runs
# against either the real artefact (positive case) or a mutated copy (negative case).
# ---------------------------------------------------------------------------


def _assert_contract_section_declares_the_full_classification(doc: dict[str, Any]) -> None:
    section = doc["autonomy_tiers"]["plan_fork_classification"]
    required = (
        "applies_to",
        "consistency_only_test",
        "settled_consensus_reread",
        "always_ask",
        "ask_shape_interactive",
        "ask_shape_dispatched",
        "record_grammar",
        "notice_tier",
        "enforcement_coverage",
    )
    missing = [k for k in required if not str(section.get(k) or "").strip()]
    assert not missing, f"plan_fork_classification is missing non-empty field(s): {missing}"

    criteria = section["consistency_only_test"]
    for token in ("settled", "convention-fit", "reversible", "no-credible-alternative"):
        assert token in criteria, f"consistency_only_test must name the {token!r} criterion"

    reread = section["settled_consensus_reread"]
    assert "NEVER precedent" in reread, "a decided-with-notice line must be pinned as NEVER precedent"
    assert "always asks" in reread, "a fork without precedent must always ask"
    assert "PLAN-dcg-decisions-index" in reread, "the audit's first corpus member must be named"
    assert "PLAN-provisional-contract-alarm" in reread, "the audit's second corpus member must be named"

    grammar = section["record_grammar"]
    for token in ("decision", "contract", "answered-fork", "precedent_kind"):
        assert token in grammar, f"record_grammar must carry {token!r}"
    assert "precedent: none" in grammar and "class: asked" in grammar, (
        "precedent: none must be paired with class: asked in the record grammar"
    )

    always_ask = section["always_ask"].lower()
    for token in ("iam", "spend", "public-surface", "governed", "scout"):
        assert token in always_ask, f"always_ask must name {token!r}"

    coverage = section["enforcement_coverage"]
    assert isinstance(coverage, list) and coverage, "enforcement_coverage must be a non-empty row list"
    statuses = set()
    for row in coverage:
        status = row.get("status")
        owner = row.get("enforced_by") or row.get("residual_owner")
        assert status, f"enforcement_coverage row {row.get('surface')!r} is missing status"
        assert owner, f"enforcement_coverage row {row.get('surface')!r} is missing enforced_by/residual_owner"
        residual = row.get("residual_owner")
        if residual is not None:
            assert residual != "rec-NNNN", "residual_owner must be an allocated id, never a placeholder"
        statuses.add(status)
    assert statuses == {"mechanical", "residual_agent_obligation"}, (
        f"enforcement_coverage must carry both status kinds, got {sorted(statuses)}"
    )


def _assert_trampoline_declares_the_step_6b_relay_hop(doc: dict[str, Any]) -> None:
    trampoline = doc["gate_request_trampoline"]
    assert "step-6b-confirmation" in trampoline["request_schema"], "request_schema must enumerate the fourth gate value"
    assert "step-6b-confirmation" in str(trampoline["gate_run_id"].get("not_applicable_to") or ""), (
        "gate_run_id.not_applicable_to must name step-6b-confirmation"
    )
    assert "step-6b-confirmation" in trampoline["pending_gates"]["write_ahead"], (
        "pending_gates.write_ahead must require a step-6b-confirmation entry"
    )
    hop = _hop_flow(doc)
    assert any("open_questions" in entry for entry in hop), "the relay hop must carry open_questions"
    assert any("never before the decision-scout verdict" in entry for entry in hop), (
        "the relay hop's ordering phrase must be the pinned lowercase form"
    )


def _assert_dispatch_header_and_provenance_name_the_relay(doc: dict[str, Any]) -> None:
    header = _exact_header(doc)
    assert "step-6b-confirmation" in header, "the injected dispatch header must name the fourth gate value"
    assert "AskUserQuestion" in header, "the injected dispatch header must name the absent AskUserQuestion tool"
    provenance = str(doc["gate_request_trampoline"]["gate_run_id"]["provenance"])
    assert "skill-dispatched" in provenance, "provenance must scope its non-optional claim with the literal token"


def _assert_plan_md_step6b_carries_shape_and_pointer(text: str) -> None:
    block = _plan_md_step6_block(text)
    ptr = "docs/contracts/overseer-dispatch.yaml#autonomy_tiers.plan_fork_classification"
    for token in (
        "consistency-only",
        "decided-with-notice",
        "open_questions",
        "step-6b-confirmation",
        ptr,
        "Fork notices",
    ):
        assert token in block, f"Step 6b must carry {token!r}"


def _assert_planning_skill_points_without_restating(text: str) -> None:
    block = _planning_confirmation_gate_block(text)
    ptr = "docs/contracts/overseer-dispatch.yaml#autonomy_tiers.plan_fork_classification"
    assert ptr in block, "the Confirmation Gate section must point at the contract section"
    assert "step-6b-confirmation" in block, "the Confirmation Gate section must name the dispatched carrier"
    for restated in ("no-credible-alternative", "always-ask list of IAM"):
        assert restated not in text, f"the planning skill must not restate {restated!r} (pointer-not-payload)"


def _assert_dispatched_carrier_is_declared_on_every_surface(text: str) -> None:
    assert _RETIRED_PHRASE not in text, "the retired no-overseer-mediation claim must not survive"
    assert "step-6b-confirmation" in text, "the overseer skill must name the fourth gate value as the carrier"


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


class TestForkClassificationContract:
    def test_contract_section_declares_the_full_classification(self) -> None:
        _assert_contract_section_declares_the_full_classification(_load_contract())

    def test_trampoline_declares_the_step_6b_relay_hop(self) -> None:
        _assert_trampoline_declares_the_step_6b_relay_hop(_load_contract())

    def test_dispatch_header_and_provenance_name_the_relay(self) -> None:
        _assert_dispatch_header_and_provenance_name_the_relay(_load_contract())

    def test_plan_md_step6b_carries_shape_and_pointer(self) -> None:
        _assert_plan_md_step6b_carries_shape_and_pointer(PLAN_MD_PATH.read_text(encoding="utf-8"))

    def test_planning_skill_points_without_restating(self) -> None:
        _assert_planning_skill_points_without_restating(PLANNING_SKILL_PATH.read_text(encoding="utf-8"))

    def test_dispatched_carrier_is_declared_on_every_surface(self) -> None:
        _assert_dispatched_carrier_is_declared_on_every_surface(OVERSEER_SKILL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Negative cases -- each mutates a copy to remove or reinstate exactly the
# clause its positive counterpart pins, and requires the SAME helper to fail.
# ---------------------------------------------------------------------------


class TestNegativeCases:
    def test_section_negative_decided_with_notice_clause_removed(self) -> None:
        doc = _load_contract()
        mutated = copy.deepcopy(doc)
        section = mutated["autonomy_tiers"]["plan_fork_classification"]
        clause = "A decided-with-notice line is NEVER precedent, and a fork without precedent always asks; "
        assert clause in section["settled_consensus_reread"]
        section["settled_consensus_reread"] = section["settled_consensus_reread"].replace(clause, "")
        assert (
            section["settled_consensus_reread"]
            != doc["autonomy_tiers"]["plan_fork_classification"]["settled_consensus_reread"]
        )
        with pytest.raises(AssertionError):
            _assert_contract_section_declares_the_full_classification(mutated)

    def test_section_negative_enforcement_coverage_residual_owner_missing(self) -> None:
        doc = _load_contract()
        mutated = copy.deepcopy(doc)
        coverage = mutated["autonomy_tiers"]["plan_fork_classification"]["enforcement_coverage"]
        residual_rows = [r for r in coverage if r.get("status") == "residual_agent_obligation"]
        assert residual_rows, "fixture must carry a residual row to mutate"
        del residual_rows[0]["residual_owner"]
        with pytest.raises(AssertionError):
            _assert_contract_section_declares_the_full_classification(mutated)

    def test_trampoline_negative_relay_hop_flow_entry_deleted(self) -> None:
        doc = _load_contract()
        mutated = copy.deepcopy(doc)
        for stage in mutated["trampoline_sequence"]["stages"]:
            if stage.get("gate") == "step-6b-confirmation":
                stage["flow"] = [entry for entry in stage["flow"] if "open_questions" not in entry]
        with pytest.raises(AssertionError):
            _assert_trampoline_declares_the_step_6b_relay_hop(mutated)

    def test_dispatch_header_negative_appended_sentences_stripped(self) -> None:
        doc = _load_contract()
        mutated = copy.deepcopy(doc)
        for sig in mutated["subagent_detection"]["signals"]:
            if sig.get("name") == "injected_header":
                original = sig["exact_header"]
                cut = original.index("The same hand-back rule applies")
                sig["exact_header"] = original[:cut]
        with pytest.raises(AssertionError):
            _assert_dispatch_header_and_provenance_name_the_relay(mutated)

    def test_plan_md_negative_pointer_removed(self) -> None:
        text = PLAN_MD_PATH.read_text(encoding="utf-8")
        ptr = "docs/contracts/overseer-dispatch.yaml#autonomy_tiers.plan_fork_classification"
        assert ptr in text
        mutated = text.replace(ptr, "")
        assert mutated != text
        with pytest.raises(AssertionError):
            _assert_plan_md_step6b_carries_shape_and_pointer(mutated)

    def test_planning_skill_negative_restates_four_criteria(self) -> None:
        text = PLANNING_SKILL_PATH.read_text(encoding="utf-8")
        mutated = text.replace(
            "## Create Branch (Workflow Step 7)",
            "no-credible-alternative\n\n## Create Branch (Workflow Step 7)",
            1,
        )
        assert mutated != text
        with pytest.raises(AssertionError):
            _assert_planning_skill_points_without_restating(mutated)

    def test_overseer_skill_negative_retired_phrase_reinstated(self) -> None:
        text = OVERSEER_SKILL_PATH.read_text(encoding="utf-8")
        mutated = text + f"\n{_RETIRED_PHRASE}\n"
        assert mutated != text
        with pytest.raises(AssertionError):
            _assert_dispatched_carrier_is_declared_on_every_surface(mutated)
