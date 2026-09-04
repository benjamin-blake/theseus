"""Tests for the blocked_by/affects blocking-edge semantics (PLAN-roadmap-blocking-edge-semantics):
ExitCriterion.blocked_by, CandidateDecision.affects, ref/until validation, CriterionBlocker's
facade import, and their deliberate exclusion from the depends_on cycle DFS.

New coverage, not migrated from the monolith -- the fields did not exist before this plan.
Shared fixture helpers live in tests/fixtures/platform_roadmap_models.py -- never import from a
sibling test_*.py module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.roadmap.platform_roadmap import CriterionBlocker, RoadmapDocument
from tests.fixtures.platform_roadmap_models import _doc, _item


def _crit(ref: str, until: str, note: str | None = None) -> dict:
    """One exit_criteria[] entry carrying a single blocked_by ref/until pair."""
    blocker = {"ref": ref, "until": until}
    if note is not None:
        blocker["note"] = note
    return {"id": "c1", "text": "x", "blocked_by": [blocker]}


# ---------------------------------------------------------------------------
# TestCriterionBlockerFacadeImport
# ---------------------------------------------------------------------------


class TestCriterionBlockerFacadeImport:
    def test_criterion_blocker_importable_from_facade(self) -> None:
        blocker = CriterionBlocker(ref="T0.1", until="complete")
        assert blocker.ref == "T0.1"
        assert blocker.until == "complete"
        assert blocker.note is None

    def test_criterion_blocker_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            CriterionBlocker(ref="T0.1", until="complete", bogus_field="y")  # type: ignore[call-arg]

    def test_criterion_blocker_disposition_is_not_a_field(self) -> None:
        # Deliberate exclusion (see scripts/platform_roadmap_models.py::CriterionBlocker
        # docstring): 'disposition' names a human activity with no observable terminus on any
        # schema object, unlike ref/until.
        with pytest.raises(ValidationError):
            CriterionBlocker(ref="T0.1", until="complete", disposition="in review")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TestBlockedByRoundTrip
# ---------------------------------------------------------------------------


class TestBlockedByRoundTrip:
    def test_blocked_by_tier_item_ref_round_trip(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("B", "complete")]}
        item_b = _item("B")
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item_a, item_b]))
        blocked_by = doc.tier_items[0].exit_criteria[0].blocked_by
        assert len(blocked_by) == 1
        assert blocked_by[0].ref == "B"
        assert blocked_by[0].until == "complete"

    def test_blocked_by_cd_ref_round_trip(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("CD.1", "ratified", note="n")]}
        cds = [{"id": "CD.1", "title": "T"}]
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item_a], candidate_decisions=cds))
        blocker = doc.tier_items[0].exit_criteria[0].blocked_by[0]
        assert blocker.ref == "CD.1"
        assert blocker.until == "ratified"
        assert blocker.note == "n"

    def test_blocked_by_tier_shortcut_ref_round_trip(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("T0", "complete")]}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item_a]))
        assert doc.tier_items[0].exit_criteria[0].blocked_by[0].ref == "T0"

    def test_blocked_by_defaults_to_empty_list(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [{"id": "c1", "text": "x"}]}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item_a]))
        assert doc.tier_items[0].exit_criteria[0].blocked_by == []


# ---------------------------------------------------------------------------
# TestAffectsRoundTrip
# ---------------------------------------------------------------------------


class TestAffectsRoundTrip:
    def test_affects_tier_item_ref_round_trip(self) -> None:
        cds = [{"id": "CD.1", "title": "T", "affects": ["T0.1"]}]
        doc = RoadmapDocument.model_validate(_doc(tier_items=[_item("T0.1")], candidate_decisions=cds))
        assert doc.candidate_decisions[0].affects == ["T0.1"]
        assert doc.candidate_decisions[0].gates == []

    def test_affects_tier_shortcut_round_trip(self) -> None:
        items = [_item("T0.1", tier="T0")]
        cds = [{"id": "CD.1", "title": "T", "affects": ["T0"]}]
        doc = RoadmapDocument.model_validate(_doc(tier_items=items, candidate_decisions=cds))
        assert doc.candidate_decisions[0].affects == ["T0"]

    def test_affects_defaults_to_empty_list(self) -> None:
        doc = RoadmapDocument.model_validate(_doc(candidate_decisions=[{"id": "CD.1", "title": "T"}]))
        assert doc.candidate_decisions[0].affects == []


# ---------------------------------------------------------------------------
# TestRefResolutionRejection
# ---------------------------------------------------------------------------


class TestRefResolutionRejection:
    def test_blocked_by_unresolvable_ref_raises(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("Z.99", "complete")]}
        with pytest.raises(ValidationError, match="does not resolve"):
            RoadmapDocument.model_validate(_doc(tier_items=[item_a]))

    def test_affects_unresolvable_ref_raises(self) -> None:
        d = _doc(candidate_decisions=[{"id": "CD.1", "title": "T", "affects": ["Z.99"]}])
        with pytest.raises(ValidationError, match="affects ref .* does not resolve"):
            RoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestUntilKindAgreement
# ---------------------------------------------------------------------------


class TestUntilKindAgreement:
    def test_ratified_until_on_tier_item_ref_raises(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("B", "ratified")]}
        item_b = _item("B")
        with pytest.raises(ValidationError, match="must be 'complete'"):
            RoadmapDocument.model_validate(_doc(tier_items=[item_a, item_b]))

    def test_complete_until_on_cd_ref_raises(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("CD.1", "complete")]}
        cds = [{"id": "CD.1", "title": "T"}]
        with pytest.raises(ValidationError, match="must be 'ratified'"):
            RoadmapDocument.model_validate(_doc(tier_items=[item_a], candidate_decisions=cds))

    def test_ratified_until_on_tier_shortcut_ref_raises(self) -> None:
        item_a = {**_item("A"), "exit_criteria": [_crit("T0", "ratified")]}
        with pytest.raises(ValidationError, match="must be 'complete'"):
            RoadmapDocument.model_validate(_doc(tier_items=[item_a]))


# ---------------------------------------------------------------------------
# TestBlockedByExcludedFromDependsOnDfs
# ---------------------------------------------------------------------------


class TestBlockedByExcludedFromDependsOnDfs:
    def test_blocked_by_ring_loads_without_cycle_error(self) -> None:
        # A and B carry NO depends_on edge between them, but each criterion is blocked_by the
        # other -- a real ring in the blocked_by graph. If blocked_by ever leaked into the
        # step-(c) depends_on adjacency, this would raise "Dependency cycle detected"; it must
        # instead load clean.
        item_a = {**_item("A"), "exit_criteria": [_crit("B", "complete")]}
        item_b = {**_item("B"), "exit_criteria": [_crit("A", "complete")]}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item_a, item_b]))
        assert doc.tier_items[0].exit_criteria[0].blocked_by[0].ref == "B"
        assert doc.tier_items[1].exit_criteria[0].blocked_by[0].ref == "A"

    def test_blocked_by_self_ring_loads_without_cycle_error(self) -> None:
        # A single item's own criterion blocked_by itself -- the tightest possible ring.
        item_a = {**_item("A"), "exit_criteria": [_crit("A", "complete")]}
        doc = RoadmapDocument.model_validate(_doc(tier_items=[item_a]))
        assert doc.tier_items[0].exit_criteria[0].blocked_by[0].ref == "A"
