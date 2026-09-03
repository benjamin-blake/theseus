"""Contract test for docs/contracts/implement-scope-boundary.yaml (PLAN-inline-defer-boundary-
contract, rec-3332 items 2-4, Decision 59 discharge, Decision 181).

Covers: both invariants declared, the CONTENT enforcement-coverage map (a single rec-owned
residual, never an unqualified binary invariant), sanction_rows as conditional trigger ->
derived-path rows (never a flat allowlist), AGENTS.md and the implement skill pointing at the
contract rather than restating it, the file-router route (topic-equals-subject + a dated
amendment_log entry), Decision 181's required Significance envelope and reversal conditions, and
AC 10's tri-surface STOP-disposition identity (contract row, check module failure guidance,
deviation trigger branch (b)).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from scripts.checks.verification import validate_scope_boundary as _check_module
from scripts.decisions_md import iter_decision_sections

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "docs" / "contracts" / "implement-scope-boundary.yaml"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "implement" / "SKILL.md"
FILE_ROUTER_PATH = REPO_ROOT / "docs" / "contracts" / "file-router.yaml"
DECISIONS_PATH = REPO_ROOT / "docs" / "DECISIONS.md"

_STOP_DISPOSITION = (
    "STOP: an undeclared touched path is never resolved by editing the plan's own scope -- the "
    "escape is a human-directed plan amendment landed as its own reviewed act, never a unilateral append."
)


def _load_contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _decision_block(number: int) -> str:
    content = DECISIONS_PATH.read_text(encoding="utf-8")
    for match, block in iter_decision_sections(content):
        if int(match.group(1)) == number:
            return block
    raise AssertionError(f"Decision {number} not found in DECISIONS.md")


class TestContractShape:
    def test_both_invariants_declared(self) -> None:
        doc = _load_contract()
        invariants = doc["invariants"]
        assert "location" in invariants and "content" in invariants
        assert "Decision 59" in invariants["location"]["authority"]

    def test_location_invariant_names_the_deleted_path_visibility_gap(self) -> None:
        """AC 4: deleted paths are named as a known gap in the contract -- get_changed_files
        existence-filters them out and only get_status_aware_diff carries 'D' rows, so the seam
        choice decides whether a deletion is even visible."""
        doc = _load_contract()
        known_gaps = doc["invariants"]["location"].get("known_gaps")
        assert known_gaps, "location invariant must document the deleted-path visibility gap"
        gaps_text = " ".join(known_gaps)
        assert "get_changed_files" in gaps_text
        assert "get_status_aware_diff" in gaps_text
        assert "deleted" in gaps_text.lower() or "deletion" in gaps_text.lower()

    def test_content_invariant_has_enforcement_coverage_with_single_rec_owned_residual(self) -> None:
        doc = _load_contract()
        coverage = doc["invariants"]["content"]["enforcement_coverage"]
        assert coverage, "CONTENT invariant must carry a non-empty enforcement_coverage map"
        residual_rows = [row for row in coverage if row.get("status") != "mechanical"]
        assert len(residual_rows) == 1, "exactly one residual row is permitted in the CONTENT map"
        residual = residual_rows[0]
        assert residual["status"] == "residual_agent_obligation"
        assert re.match(r"^rec-\d+$", str(residual.get("residual_owner", ""))), (
            f"residual row must carry a real owning rec id, got {residual.get('residual_owner')!r}"
        )
        for row in coverage:
            if row.get("status") == "mechanical":
                assert row.get("enforced_by"), f"mechanical row has no enforcer: {row}"

    def test_content_invariant_never_an_unqualified_binary(self) -> None:
        """Decision 163 point 2: never a bare statement with no coverage map."""
        doc = _load_contract()
        content = doc["invariants"]["content"]
        assert content.get("enforcement_coverage"), "CONTENT must carry a non-empty enforcement_coverage map"

    def test_sanction_rows_are_conditional_not_flat_allowlist(self) -> None:
        doc = _load_contract()
        rows = doc["sanction_rows"]
        assert len(rows) >= 3
        for name, row in rows.items():
            assert "trigger" in row and "kind" in row["trigger"], (
                f"{name} has no trigger.kind -- looks like a flat allowlist entry"
            )
            assert row.get("purpose"), f"{name} has no purpose"

    def test_known_residuals_note_distinct_from_content_coverage_map(self) -> None:
        doc = _load_contract()
        content = doc["invariants"]["content"]
        known = content.get("known_residuals")
        assert known, "known_residuals must be non-empty"
        assert any("R6" in note for note in known)
        coverage_text = " ".join((row.get("note", "") + row.get("surface", "")) for row in content["enforcement_coverage"])
        assert "R6" not in coverage_text, (
            "the R6 split's own residual belongs in known_residuals, not the CONTENT coverage map"
        )

    def test_bookkeeping_row_permits_the_followon_recs_write_back(self) -> None:
        """PLAN-plan-followon-recs-field (PDB-01): /implement Step 7 closure writes a deferred
        half's filed rec id back into the resolved plan's followon_recs, ahead of the item that
        sets implementation_declared true -- sanctioned here alongside closes_criteria."""
        doc = _load_contract()
        row = doc["sanction_rows"]["implementing_plan_bookkeeping"]
        assert "followon_recs" in row["permitted_field_edits"]
        entries = doc["amendment_log"]
        assert any("plan-followon-recs-field" in (e.get("summary") or "") for e in entries)

    def test_unmodelled_companions_present(self) -> None:
        doc = _load_contract()
        companions = {row["path"] for row in doc["unmodelled_companions"]}
        assert ".secrets.baseline" in companions
        assert "config/composite_action_body_baseline.yaml" in companions


class TestProseSurfacesPointAtContract:
    def test_agents_md_safety_bullet_points_at_contract(self) -> None:
        text = AGENTS_PATH.read_text(encoding="utf-8")
        assert "implement-scope-boundary.yaml" in text
        assert "Decision 59" in text

    def test_implement_skill_deviation_trigger_has_three_branches_and_pointers(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        i = text.find("### Deviation trigger")
        assert i >= 0, "### Deviation trigger section absent"
        section = re.split(r"\n#{2,3} ", text[i:], maxsplit=1)[0]
        assert "(a)" in section and "(b)" in section and "(c)" in section
        assert "Fable Advice-Consult Protocol" in section
        assert "overseer/SKILL.md" in section
        assert "3-fix-attempt" in section and "VF-08" in section

    def test_implement_skill_deviation_trigger_adds_no_auto_file_path(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        i = text.find("### Deviation trigger")
        section = re.split(r"\n#{2,3} ", text[i:], maxsplit=1)[0]
        for token in ("file_rec", "ops_data_portal", "--file-rec"):
            assert token not in section


class TestFileRouterRegistration:
    def test_route_topic_equals_subject(self) -> None:
        doc = yaml.safe_load(FILE_ROUTER_PATH.read_text(encoding="utf-8"))
        routes = {r["topic"]: r for r in doc["routes"]}
        assert "implement-scope-boundary" in routes
        assert routes["implement-scope-boundary"]["targets"] == ["docs/contracts/implement-scope-boundary.yaml"]

    def test_amendment_log_has_dated_entry_for_this_change(self) -> None:
        doc = yaml.safe_load(FILE_ROUTER_PATH.read_text(encoding="utf-8"))
        entries = doc["amendment_log"]
        assert any("implement-scope-boundary" in (e.get("summary") or "") for e in entries)


class TestDecision181:
    def test_significance_envelope_present(self) -> None:
        block = _decision_block(181)
        fence = "```yaml"
        i = block.find(fence)
        assert i >= 0, "Decision 181 must carry a fenced yaml metadata envelope"
        end = block.find("```", i + len(fence))
        env = yaml.safe_load(block[i + len(fence) : end])
        assert env["number"] == 181
        sig = env["significance"]
        assert sig["value"] == "numbered_decision"
        justification = sig["justification"]
        assert "implement-scope-boundary.yaml" in justification
        assert "amendment" in justification.lower()

    def test_reversal_conditions_present(self) -> None:
        block = _decision_block(181)
        assert "eversal" in block

    def test_points_at_contract_rather_than_restating(self) -> None:
        block = _decision_block(181)
        assert "implement-scope-boundary.yaml" in block
        assert "Decision 59" in block
        assert "Decision 163" in block


class TestTriSurfaceStopDispositionIdentity:
    """AC 10: an undeclared touched path has exactly ONE disposition, stated identically in the
    contract's implementing_plan_bookkeeping row, the check module's failure guidance, and the
    deviation trigger's branch (b)."""

    def test_contract_row_carries_disposition(self) -> None:
        doc = _load_contract()
        row = doc["sanction_rows"]["implementing_plan_bookkeeping"]
        assert _STOP_DISPOSITION in row["disposition_on_violation"]

    def test_deviation_trigger_branch_b_carries_same_disposition(self) -> None:
        doc = _load_contract()
        branches = {b["id"]: b for b in doc["deviation_trigger"]["branches"]}
        assert _STOP_DISPOSITION in branches["b"]["description"]

    def test_check_module_failure_guidance_carries_same_disposition(self) -> None:
        assert _check_module._STOP_DISPOSITION == _STOP_DISPOSITION
