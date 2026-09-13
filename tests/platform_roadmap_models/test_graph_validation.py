"""Tests for scripts/platform_roadmap_models.py: id uniqueness, dangling depends_on, cycle
detection, and the deferred_post_mvp no-live-dependency invariant.

Migrated from the retired tests/test_platform_roadmap_models.py monolith (Decision 128
decompose-don't-raise / Decision 131 mirror convention). Shared fixture helpers live in
tests/fixtures/platform_roadmap_models.py -- never import from a sibling test_*.py module.
"""

from __future__ import annotations

import pytest

from scripts.roadmap.platform_roadmap import PlatformRoadmapState, RoadmapDocument, load
from scripts.session.preflight import _slim_roadmap_state
from tests.fixtures.platform_roadmap_models import _LIVE_ROADMAP, _doc, _item

# ---------------------------------------------------------------------------
# TestIdUniqueness
# ---------------------------------------------------------------------------


class TestIdUniqueness:
    def test_duplicate_id_raises(self) -> None:
        d = _doc(tier_items=[_item("T0.1"), _item("T0.1")])
        with pytest.raises(Exception, match="[Dd]uplicate"):
            RoadmapDocument.model_validate(d)

    def test_unique_ids_pass(self) -> None:
        d = _doc(tier_items=[_item("T0.1"), _item("T0.2")])
        doc = RoadmapDocument.model_validate(d)
        assert len(doc.tier_items) == 2


# ---------------------------------------------------------------------------
# TestDanglingDependsOn
# ---------------------------------------------------------------------------


class TestDanglingDependsOn:
    def test_nonexistent_dep_raises(self) -> None:
        d = _doc(tier_items=[_item("T0.1", depends_on=["T999.0"])])
        with pytest.raises(Exception, match="does not resolve"):
            RoadmapDocument.model_validate(d)

    def test_valid_dep_passes(self) -> None:
        d = _doc(tier_items=[_item("T0.1"), _item("T0.2", depends_on=["T0.1"])])
        doc = RoadmapDocument.model_validate(d)
        assert doc.tier_items[1].depends_on == ["T0.1"]

    def test_tier_shortcut_dep_passes(self) -> None:
        d = _doc(tier_items=[_item("T0.1", tier="T0"), _item("T1.1", tier="T1", depends_on=["T0"])])
        doc = RoadmapDocument.model_validate(d)
        assert "T0" in doc.tier_items[1].depends_on


# ---------------------------------------------------------------------------
# TestCycleDetection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_direct_cycle_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item("T0.1", depends_on=["T0.2"]),
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            RoadmapDocument.model_validate(d)

    def test_three_node_cycle_raises(self) -> None:
        d = _doc(
            tier_items=[
                _item("T0.1", depends_on=["T0.3"]),
                _item("T0.2", depends_on=["T0.1"]),
                _item("T0.3", depends_on=["T0.2"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            RoadmapDocument.model_validate(d)

    def test_linear_chain_passes(self) -> None:
        d = _doc(
            tier_items=[
                _item("T0.1"),
                _item("T0.2", depends_on=["T0.1"]),
                _item("T0.3", depends_on=["T0.2"]),
            ]
        )
        doc = RoadmapDocument.model_validate(d)
        assert len(doc.tier_items) == 3

    def test_tier_shortcut_cycle_raises(self) -> None:
        # T0.1 in T0 depends on tier T1; T1.1 in T1 depends on tier T0 -> cycle
        d = _doc(
            tier_items=[
                _item("T0.1", tier="T0", depends_on=["T1"]),
                _item("T1.1", tier="T1", depends_on=["T0"]),
            ]
        )
        with pytest.raises(Exception, match="[Cc]ycle"):
            RoadmapDocument.model_validate(d)


# ---------------------------------------------------------------------------
# TestDeferredPostMvp -- Decision 93 / PLAN-platform-mvp-boundary
# ---------------------------------------------------------------------------


class TestDeferredPostMvp:
    def _make_doc(self, items: list[dict]) -> RoadmapDocument:
        return RoadmapDocument.model_validate(_doc(tier_items=items))

    def test_deferred_item_absent_from_eligible(self) -> None:
        """(a) deferred_post_mvp item is absent from eligible_items() and next_eligible."""
        doc = self._make_doc([{**_item("T0.1"), "status": "deferred_post_mvp"}])
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        assert "T0.1" not in eligible_ids
        full = state.to_preflight_dict()
        next_ids = {i["id"] for i in full["next_eligible"]}
        assert "T0.1" not in next_ids

    def test_tier_complete_with_deferred_item(self) -> None:
        """(b) tier [complete, deferred_post_mvp] counts as complete; active_tier advances."""
        doc = self._make_doc(
            [
                _item("T0.1", tier="T0", status="complete"),
                {**_item("T0.2", tier="T0"), "status": "deferred_post_mvp"},
                _item("T1.1", tier="T1"),
            ]
        )
        state = PlatformRoadmapState(doc)
        assert state.tier_complete("T0") is True
        assert state.active_tier() == "T1"

    def test_live_dep_on_deferred_raises(self) -> None:
        """(c) not_started item depending on deferred_post_mvp item raises ValueError."""
        d = _doc(
            tier_items=[
                {**_item("T0.1"), "status": "deferred_post_mvp"},
                _item("T0.2", depends_on=["T0.1"]),
            ]
        )
        with pytest.raises(ValueError, match="deferred_post_mvp"):
            RoadmapDocument.model_validate(d)

    def test_in_progress_dep_on_deferred_raises(self) -> None:
        """(c-ext) in_progress item depending on deferred_post_mvp item also raises ValueError."""
        d = _doc(
            tier_items=[
                {**_item("T0.1"), "status": "deferred_post_mvp"},
                {**_item("T0.2", depends_on=["T0.1"]), "status": "in_progress"},
            ]
        )
        with pytest.raises(ValueError, match="deferred_post_mvp"):
            RoadmapDocument.model_validate(d)

    def test_deferred_bucket_in_full_state_absent_from_slim(self) -> None:
        """(d) deferred item in deferred_post_mvp bucket of full state; absent from slim."""
        doc = self._make_doc([{**_item("T0.1"), "status": "deferred_post_mvp"}])
        state = PlatformRoadmapState(doc)
        full = state.to_preflight_dict()
        assert "deferred_post_mvp" in full
        assert any(i["id"] == "T0.1" for i in full["deferred_post_mvp"])
        # session_preflight._slim_roadmap_state must NOT include deferred_post_mvp
        slim = _slim_roadmap_state(full)
        assert "deferred_post_mvp" not in slim

    def test_real_roadmap_parked_ids_absent_from_next_eligible(self) -> None:
        """(e) four parked ids (T2.8/T2.9/T2.11a/T2.11b) absent from next_eligible in real roadmap."""
        doc = load(_LIVE_ROADMAP)
        state = PlatformRoadmapState(doc)
        eligible_ids = {i.id for i in state.eligible_items()}
        parked_ids = {"T2.8", "T2.9", "T2.11a", "T2.11b"}
        assert parked_ids.isdisjoint(eligible_ids), f"Parked items found in eligible: {parked_ids & eligible_ids}"
