"""Shared fixture helpers for tests/platform_roadmap_models/ (mirror package, Decision 131).

Migrated from the retired tests/test_platform_roadmap_models.py monolith (Decision 128
decompose-don't-raise). This module's names never start with `test_`, so it is exempt from the
cross-test-import guard (validate_no_cross_test_imports) by construction -- every mirror module
imports these helpers from here rather than from a sibling test_*.py file.

Deliberately near-verbatim duplicate of tests/fixtures/platform_roadmap_state.py's _BASE_DOC/
_doc/_item/_state_from_doc shape (Decision 131 clause 2 forbids cross-test-module imports, and
one fixture module per mirror package is the deliberate repo pattern -- see also
plan_document_helpers, ops_portal_records, affected_tests_helpers -- not accidental copy-paste).

PATH-DEPTH NOTE: _LIVE_ROADMAP is computed repo-root-anchored from THIS file's location
(tests/fixtures/, depth-2 under tests/), not from a migrated test module's own __file__ (which
sits at tests/platform_roadmap_models/, also depth-2, but with a different relative
resolution). Every migrated live-roadmap reference imports _LIVE_ROADMAP from here instead of
recomputing `Path(__file__).parent.parent` locally -- that recomputation is exactly what broke on
the monolith-to-package move (see tests/fixtures/platform_roadmap_state.py, same precedent).
"""

from __future__ import annotations

import copy
from pathlib import Path

from scripts.roadmap.platform_roadmap import PlatformRoadmapState, RoadmapDocument

_LIVE_ROADMAP = Path(__file__).resolve().parents[2] / "docs" / "ROADMAP-PLATFORM.yaml"

_BASE_DOC: dict = {
    "document": {
        "id": "ROADMAP-TEST",
        "version": 1,
        "status": "draft",
        "filed_via": "pending_log_decision_lambda",
        "gate_helpers": [
            {"name": "tier_complete", "arity": 1},
            {"name": "all_in_tier_with_status", "arity": 2},
            {"name": "grace_period_elapsed", "arity": 2},
            {"name": "item_field_eq", "arity": 3},
        ],
    },
    "tier_items": [],
    "candidate_decisions": [],
    "cross_tier_gates": [],
}


def _doc(**overrides) -> dict:
    d = copy.deepcopy(_BASE_DOC)
    d.update(overrides)
    return d


def _item(item_id: str, tier: str = "T0", depends_on: list | None = None, status: str = "not_started") -> dict:
    return {
        "id": item_id,
        "tier": tier,
        "name": f"Test item {item_id}",
        "depends_on": depends_on or [],
        "files_in_scope": [],
        "exit_criteria": [],
        "effort": "S",
        "strategic": False,
        "status": status,
    }


def _state_from_doc(doc_dict: dict) -> PlatformRoadmapState:
    return PlatformRoadmapState(RoadmapDocument.model_validate(doc_dict))
