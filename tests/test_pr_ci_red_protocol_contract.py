"""Content contract for PLAN-pr-ci-red-ownership.

Four surfaces carry one corrected, non-contradictory PR-branch-vs-post-merge CI-red disposition:
AGENTS.md's Merge protocol, the implement skill's red-CI branch, ci-rca-lifecycle.yaml's
trigger_scope (the single home the other two point at), and Decision 72's dated scope
annotation. Each surface gets a positive case (asserts against the real artefact) and at least
one negative case (asserts the SAME check fails against a fixture copy with its clause removed
or the retired unscoped phrasing reintroduced) -- proving the positive case is not vacuous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.decisions_md import iter_decision_sections

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
IMPLEMENT_SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "implement" / "SKILL.md"
CI_RCA_LIFECYCLE_PATH = REPO_ROOT / "docs" / "contracts" / "ci-rca-lifecycle.yaml"
DECISIONS_PATH = REPO_ROOT / "docs" / "DECISIONS.md"

RETIRED_UNSCOPED_BULLET = (
    "- **On CI failure**: the ci-rca agent (`.github/workflows/ci-rca.yml`) automatically files "
    'a recommendation with `source="ci_rca"` and `priority="critical"`.'
)


# ---------------------------------------------------------------------------
# Assertion functions -- each operates on a text/dict blob so it can be run
# against either the real artefact (positive case) or a mutated copy (negative case).
# ---------------------------------------------------------------------------


def _assert_agents_md_contract(text: str) -> None:
    assert "On CI failure" not in text, "the unscoped bullet must not survive the branch-scoped rewrite"
    assert "forward-fix, never auto-revert" in text, "Decision 73 point 3's forward-fix phrase must survive"
    assert "source=ci_rca" in text, "Decision 73 point 3's source discriminator must survive"
    assert "priority=critical" in text, "Decision 73 point 3's priority must survive"
    assert "PR-branch" in text, "the PR-branch case must be positively named"
    assert "no rec is filed" in text, "the PR-branch disposition must be stated, not just implied"
    assert "trigger_scope" in text, "the PR-branch disposition must route to trigger_scope, not restate it"
    when_cell = "Pre-handoff (local) + post-merge on `main`"
    assert when_cell in text, "the Full row When cell is load-bearing (Decision 163 point 3)"


def _assert_implement_skill_contract(text: str) -> None:
    assert "trigger_scope" in text, "the red-CI branch must point at trigger_scope"
    assert "Never weaken a criterion" in text, "the no-weakening rule is new prose that must be present"
    assert "VP step" in text, "the no-weakening rule must cover VP steps"
    assert "budget" in text, "the no-weakening rule must cover budgets"
    assert "executor-rca" in text and "out of scope" in text, "executor-rca must be named out of scope for PR CI red"

    i = text.index("**Any red**")
    j = text.index("- **Still running**", i)
    segment = text[i:j]
    assert "file_rec" not in segment, "the red-CI branch must add no rec-filing call (VF-08 T3.19 stays deferred)"
    assert "ops_data_portal" not in segment, "the red-CI branch must add no rec-filing call (VF-08 T3.19 stays deferred)"


def _assert_ci_rca_lifecycle_contract(doc: dict[str, Any]) -> None:
    scope = doc.get("trigger_scope")
    assert isinstance(scope, dict), "trigger_scope block must exist"
    gate = scope.get("gate", "")
    assert "default_branch" in gate and "head_branch" in gate, "the gate must name the default-branch head_branch condition"
    narrowing = scope.get("narrowing_authority", "")
    assert "Decision 73 point 3" in narrowing, "Decision 73 point 3 must be named as the narrowing authority"
    pr_disposition = scope.get("pr_branch_disposition", "")
    assert "UNCOVERED BY CONSTRUCTION" in pr_disposition, "PR-branch failures must be recorded as uncovered by construction"


def _assert_decision_72_contract(block: str) -> None:
    assert "post-merge" in block, "the annotation must name the post-merge scope"
    assert "`main`" in block, "the annotation must name main"
    assert "trigger_scope" in block, "the annotation must point at trigger_scope rather than restate its disposition"


def _decision_72_block() -> str:
    content = DECISIONS_PATH.read_text(encoding="utf-8")
    for match, block in iter_decision_sections(content):
        if int(match.group(1)) == 72:
            return block
    raise AssertionError("Decision 72 not found in DECISIONS.md")


# ---------------------------------------------------------------------------
# AGENTS.md
# ---------------------------------------------------------------------------


def test_agents_md_contract_positive() -> None:
    _assert_agents_md_contract(AGENTS_PATH.read_text(encoding="utf-8"))


def test_agents_md_contract_negative_missing_pr_branch_pointer() -> None:
    text = AGENTS_PATH.read_text(encoding="utf-8")
    pr_bullet = (
        "- **PR-branch `--pre` failure**: per `docs/contracts/ci-rca-lifecycle.yaml` trigger_scope, "
        "no rec is filed and nothing gates -- ci-rca watches `main` only; diagnose and fix on the "
        "branch (Git-ops step 6).\n"
    )
    assert pr_bullet in text
    mutated = text.replace(pr_bullet, "")
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_agents_md_contract(mutated)


def test_agents_md_contract_negative_unscoped_bullet_reintroduced() -> None:
    text = AGENTS_PATH.read_text(encoding="utf-8")
    mutated = text.replace(
        "## Instruction architecture",
        RETIRED_UNSCOPED_BULLET + "\n\n## Instruction architecture",
        1,
    )
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_agents_md_contract(mutated)


# ---------------------------------------------------------------------------
# implement SKILL.md
# ---------------------------------------------------------------------------


def test_implement_skill_contract_positive() -> None:
    _assert_implement_skill_contract(IMPLEMENT_SKILL_PATH.read_text(encoding="utf-8"))


def test_implement_skill_contract_negative_missing_no_weakening_clause() -> None:
    text = IMPLEMENT_SKILL_PATH.read_text(encoding="utf-8")
    clause = (
        "Never weaken a criterion, VP step (`### Tier-Specific Guidance` Anti-Patterns), assertion, or budget to obtain green."
    )
    assert clause in text
    mutated = text.replace(clause, "")
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_implement_skill_contract(mutated)


def test_implement_skill_contract_negative_rec_filing_call_added() -> None:
    text = IMPLEMENT_SKILL_PATH.read_text(encoding="utf-8")
    i = text.index("**Any red**")
    marker = "Stay subscribed and end the turn."
    j = text.index(marker, i) + len(marker)
    mutated = text[:j] + " File via ops_data_portal if recurring." + text[j:]
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_implement_skill_contract(mutated)


# ---------------------------------------------------------------------------
# docs/contracts/ci-rca-lifecycle.yaml
# ---------------------------------------------------------------------------


def _load_ci_rca_lifecycle() -> dict[str, Any]:
    return yaml.safe_load(CI_RCA_LIFECYCLE_PATH.read_text(encoding="utf-8"))


def test_ci_rca_lifecycle_contract_positive() -> None:
    _assert_ci_rca_lifecycle_contract(_load_ci_rca_lifecycle())


def test_ci_rca_lifecycle_contract_negative_missing_trigger_scope() -> None:
    doc = _load_ci_rca_lifecycle()
    assert "trigger_scope" in doc
    mutated = dict(doc)
    del mutated["trigger_scope"]
    with pytest.raises(AssertionError):
        _assert_ci_rca_lifecycle_contract(mutated)


def test_ci_rca_lifecycle_contract_negative_missing_narrowing_authority() -> None:
    doc = _load_ci_rca_lifecycle()
    mutated_scope = dict(doc["trigger_scope"])
    mutated_scope["narrowing_authority"] = "some other rationale, no decision cited"
    mutated = dict(doc)
    mutated["trigger_scope"] = mutated_scope
    with pytest.raises(AssertionError):
        _assert_ci_rca_lifecycle_contract(mutated)


# ---------------------------------------------------------------------------
# docs/DECISIONS.md Decision 72
# ---------------------------------------------------------------------------


def test_decision_72_contract_positive() -> None:
    _assert_decision_72_contract(_decision_72_block())


def test_decision_72_contract_negative_missing_annotation() -> None:
    block = _decision_72_block()
    annotation_start = block.index("> **Update (2026-08-31):**")
    mutated = block[:annotation_start].rstrip() + "\n"
    assert mutated != block
    with pytest.raises(AssertionError):
        _assert_decision_72_contract(mutated)
