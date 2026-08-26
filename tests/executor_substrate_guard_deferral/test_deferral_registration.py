"""Mirror test for PLAN-executor-substrate-guard-deferral.

Reads RAW YAML (yaml.safe_load on docs/ROADMAP-PLATFORM.yaml), never the Pydantic loader
(scripts.roadmap.platform_roadmap.load), whose exit_criteria normalizer would launder a stray
bare string into an ExitCriterion object and make the shape assertion vacuous.

Asserts: T4.2's exit_criteria are all mappings; c7 exists naming both triggers and its future
evaluator check_id; T4.2's criterion ids are unique; T2.45 is complete with every criterion met
and a resolving met_by. It then factors the two status couplings this plan registers into a
PURE PREDICATE over (tier_item_dict, registry_check_ids) and exercises it two ways: against the
LIVE T4.2 dict and the live graduated check_ids (proving the predicate applies to real data), and
against SYNTHETIC structures (proving the predicate actually discriminates, since both couplings'
antecedents are false against the live roadmap today and would assert nothing on their own).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from scripts.verification_graduation import load_entries

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP_PATH = REPO_ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
PLANS_DIR = REPO_ROOT / "docs" / "plans"

_CHECK_ID_RE = re.compile(r"check_id\s+([a-z0-9][a-z0-9-]*)")


def _load_roadmap() -> dict[str, Any]:
    return yaml.safe_load(ROADMAP_PATH.read_text(encoding="utf-8"))


def _tier_item(item_id: str, roadmap: dict[str, Any]) -> dict[str, Any]:
    return next(i for i in roadmap["tier_items"] if i["id"] == item_id)


def _c7(item: dict[str, Any]) -> dict[str, Any] | None:
    return next((c for c in item.get("exit_criteria", []) if isinstance(c, dict) and c.get("id") == "c7"), None)


def _live_registry_check_ids() -> set[str]:
    return {row["check_id"] for row in load_entries(repo_root=REPO_ROOT) if "check_id" in row}


def coupling_violations(item: dict[str, Any], registry_check_ids: set[str]) -> list[str]:
    """Pure predicate, no I/O: (tier_item dict, live registry check_ids) -> violation list.

    Coupling A: item.status == complete implies its c7 criterion is status met.
    Coupling B: c7.status == met implies a verification-registry row named by c7's check_id
    exists. Without both, a future session could flip c7 to met with no evaluator registered,
    or complete the item with c7 open, and every other gate would stay green.
    """
    violations: list[str] = []
    c7 = _c7(item)
    c7_met = c7 is not None and c7.get("status") == "met"
    if item.get("status") == "complete" and not c7_met:
        violations.append("coupling-a: item status is complete but c7 is not met")
    if c7_met:
        match = _CHECK_ID_RE.search(c7.get("text", ""))
        check_id = match.group(1) if match else None
        if not check_id or check_id not in registry_check_ids:
            violations.append("coupling-b: c7 is met but its named check_id has no registry row")
    return violations


def test_t42_criteria_are_all_mappings():
    d = _load_roadmap()
    t42 = _tier_item("T4.2", d)
    for crit in t42["exit_criteria"]:
        assert isinstance(crit, dict), f"T4.2 exit criterion is not a mapping: {crit!r}"


def test_t42_c7_exists_naming_both_triggers_and_evaluator():
    d = _load_roadmap()
    t42 = _tier_item("T4.2", d)
    c7 = _c7(t42)
    assert c7 is not None, "T4.2 must carry a c7 criterion"
    assert c7.get("status") == "open"
    text = c7["text"]
    assert "executor-substrate-guard-classification-complete" in text, "c7 must name its future evaluator check_id"
    assert "T4.15" in text, "c7 must name the T4.15 substrate-ratification trigger"
    assert "rec-2816" in text, "c7 must name the rec-2816 remediation trigger"
    assert "PLAN-executor-substrate-guard-deferral" in text, "c7 must name this plan as the recon carrier"


def test_t42_criterion_ids_are_unique():
    d = _load_roadmap()
    t42 = _tier_item("T4.2", d)
    ids = [c["id"] for c in t42["exit_criteria"]]
    assert len(ids) == len(set(ids)), f"T4.2 criterion ids are not unique: {ids}"


def test_t245_is_complete_with_all_criteria_met_and_resolving_met_by():
    d = _load_roadmap()
    t245 = _tier_item("T2.45", d)
    assert t245["status"] == "complete"
    for c in t245["exit_criteria"]:
        assert c["status"] == "met", f"T2.45 criterion {c['id']} is not met: {c}"
        met_by = c.get("met_by")
        assert met_by, f"T2.45 criterion {c['id']} has no met_by"
        assert (PLANS_DIR / f"PLAN-{met_by}.yaml").exists(), (
            f"T2.45 criterion {c['id']}'s met_by {met_by!r} does not resolve to a real plan file"
        )


def test_coupling_predicate_against_live_roadmap():
    d = _load_roadmap()
    t42 = _tier_item("T4.2", d)
    violations = coupling_violations(t42, _live_registry_check_ids())
    assert violations == [], f"unexpected coupling violation against the live roadmap: {violations}"


def test_coupling_predicate_discriminates_on_synthetic_structures():
    complete_and_met = {
        "status": "complete",
        "exit_criteria": [{"id": "c7", "status": "met", "text": "check_id fake-check-a"}],
    }
    assert coupling_violations(complete_and_met, {"fake-check-a"}) == []

    complete_but_open = {
        "status": "complete",
        "exit_criteria": [{"id": "c7", "status": "open", "text": "check_id fake-check-a"}],
    }
    assert coupling_violations(complete_but_open, {"fake-check-a"}) != []

    not_started_and_open = {
        "status": "not_started",
        "exit_criteria": [{"id": "c7", "status": "open", "text": "check_id fake-check-b"}],
    }
    assert coupling_violations(not_started_and_open, set()) == []

    met_but_check_id_absent = {
        "status": "in_progress",
        "exit_criteria": [{"id": "c7", "status": "met", "text": "check_id fake-check-c"}],
    }
    assert coupling_violations(met_but_check_id_absent, set()) != []
