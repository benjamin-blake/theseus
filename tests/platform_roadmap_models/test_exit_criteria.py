"""Tests for scripts/platform_roadmap_models.py: ExitCriterion bare-string normalization,
met/rehomed integrity checks (g)/(h), and the OpenQuestion/KnownGap status lifecycle (i)/(j).

Migrated from the retired tests/test_platform_roadmap_models.py monolith (Decision 128
decompose-don't-raise / Decision 131 mirror convention). Shared fixture helpers live in
tests/fixtures/platform_roadmap_models.py -- never import from a sibling test_*.py module.
"""

from __future__ import annotations

import copy

import pytest

from scripts.roadmap.platform_roadmap import ExitCriterion, KnownGap, OpenQuestion, RoadmapDocument, TierItem, load
from tests.fixtures.platform_roadmap_models import _BASE_DOC, _LIVE_ROADMAP, _item

# ---------------------------------------------------------------------------
# TestExitCriterionNormalizer -- T-1.23
# ---------------------------------------------------------------------------


class TestExitCriterionNormalizer:
    """Bare strings normalize to ExitCriterion(status='open'); structured dicts pass through."""

    def test_bare_string_becomes_exit_criterion(self) -> None:
        item = TierItem(id="X", tier="T0", name="t", exit_criteria=["do something"])
        assert len(item.exit_criteria) == 1
        assert isinstance(item.exit_criteria[0], ExitCriterion)
        assert item.exit_criteria[0].id == "c1"
        assert item.exit_criteria[0].text == "do something"
        assert item.exit_criteria[0].status == "open"
        assert item.exit_criteria[0].met_by is None

    def test_multiple_bare_strings_get_sequential_ids(self) -> None:
        item = TierItem(id="X", tier="T0", name="t", exit_criteria=["a", "b", "c"])
        ids = [c.id for c in item.exit_criteria]
        assert ids == ["c1", "c2", "c3"]

    def test_structured_dict_passes_through(self) -> None:
        item = TierItem(
            id="X",
            tier="T0",
            name="t",
            exit_criteria=[{"id": "c1", "text": "done", "status": "open"}],
        )
        assert isinstance(item.exit_criteria[0], ExitCriterion)
        assert item.exit_criteria[0].id == "c1"
        assert item.exit_criteria[0].text == "done"

    def test_empty_exit_criteria(self) -> None:
        item = TierItem(id="X", tier="T0", name="t", exit_criteria=[])
        assert item.exit_criteria == []

    def test_exit_criterion_model_status_enum(self) -> None:
        for s in ("open", "met", "rehomed"):
            ec = ExitCriterion(id="c1", text="x", status=s, met_by="something" if s != "open" else None)
            assert ec.status == s

    def test_exit_criterion_rejects_unknown_field(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExitCriterion(id="c1", text="x", bogus_field="y")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TestExitCriteriaIntegrity -- model_validator checks (g) and (h)
# ---------------------------------------------------------------------------


class TestExitCriteriaIntegrity:
    """met/rehomed without met_by -> ValueError; rehomed met_by to unknown item -> ValueError."""

    def _doc_with_items(self, *items: dict) -> dict:
        d = copy.deepcopy(_BASE_DOC)
        d["tier_items"] = list(items)
        return d

    def test_met_criterion_requires_met_by(self) -> None:
        from pydantic import ValidationError

        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "met"}]
        with pytest.raises(ValidationError, match="met_by"):
            RoadmapDocument.model_validate(self._doc_with_items(item))

    def test_rehomed_criterion_requires_met_by(self) -> None:
        from pydantic import ValidationError

        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "rehomed"}]
        with pytest.raises(ValidationError, match="met_by"):
            RoadmapDocument.model_validate(self._doc_with_items(item))

    def test_rehomed_met_by_must_resolve_to_known_item(self) -> None:
        from pydantic import ValidationError

        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "rehomed", "met_by": "Z.99"}]
        with pytest.raises(ValidationError, match="does not resolve to a known tier_item id"):
            RoadmapDocument.model_validate(self._doc_with_items(item))

    def test_rehomed_met_by_valid_item_passes(self) -> None:
        item_a = _item("A")
        item_a["exit_criteria"] = [{"id": "c1", "text": "x", "status": "rehomed", "met_by": "B"}]
        item_b = _item("B")
        doc = RoadmapDocument.model_validate(self._doc_with_items(item_a, item_b))
        assert doc.tier_items[0].exit_criteria[0].status == "rehomed"
        assert doc.tier_items[0].exit_criteria[0].met_by == "B"

    def test_met_with_valid_met_by_passes(self) -> None:
        item = _item("A")
        item["exit_criteria"] = [{"id": "c1", "text": "x", "status": "met", "met_by": "some-plan-slug"}]
        doc = RoadmapDocument.model_validate(self._doc_with_items(item))
        assert doc.tier_items[0].exit_criteria[0].status == "met"


# ---------------------------------------------------------------------------
# TestOpenQuestionKnownGapLifecycle -- PLAN-close-audit-ulf-04-ulf-10 (Decision 114)
# ---------------------------------------------------------------------------


class TestOpenQuestionKnownGapLifecycle:
    """status/resolution_ref lifecycle fields on OpenQuestion and KnownGap (checks (i)/(j))."""

    def _doc_with_oq(self, *oqs: dict) -> dict:
        d = copy.deepcopy(_BASE_DOC)
        d["open_questions"] = list(oqs)
        return d

    def _doc_with_kg(self, *kgs: dict) -> dict:
        d = copy.deepcopy(_BASE_DOC)
        d["known_gaps"] = list(kgs)
        return d

    def test_open_question_status_enum_accepted(self) -> None:
        for s in ("open", "resolved", "closed", "promoted"):
            oq = OpenQuestion(id="OQ.1", question="q", status=s, resolution_ref="x" if s != "open" else None)
            assert oq.status == s

    def test_known_gap_status_enum_accepted(self) -> None:
        for s in ("open", "resolved", "closed", "promoted"):
            kg = KnownGap(id="KG.1", gap="g", status=s, resolution_ref="x" if s != "open" else None)
            assert kg.status == s

    def test_open_question_invalid_status_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OpenQuestion(id="OQ.1", question="q", status="bogus")  # type: ignore[arg-type]

    def test_known_gap_invalid_status_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            KnownGap(id="KG.1", gap="g", status="bogus")  # type: ignore[arg-type]

    def test_open_question_defaults_to_open_no_resolution_ref(self) -> None:
        oq = OpenQuestion(id="OQ.1", question="q")
        assert oq.status == "open"
        assert oq.resolution_ref is None

    def test_known_gap_non_open_without_resolution_ref_raises(self) -> None:
        from pydantic import ValidationError

        d = self._doc_with_kg({"id": "KG.1", "gap": "g", "status": "resolved"})
        with pytest.raises(ValidationError, match="resolution_ref"):
            RoadmapDocument.model_validate(d)

    def test_open_question_non_open_without_resolution_ref_raises(self) -> None:
        from pydantic import ValidationError

        d = self._doc_with_oq({"id": "OQ.1", "question": "q", "status": "resolved"})
        with pytest.raises(ValidationError, match="resolution_ref"):
            RoadmapDocument.model_validate(d)

    def test_open_question_non_open_with_resolution_ref_passes(self) -> None:
        d = self._doc_with_oq({"id": "OQ.1", "question": "q", "status": "resolved", "resolution_ref": "T0.9"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.open_questions[0].status == "resolved"
        assert doc.open_questions[0].resolution_ref == "T0.9"

    def test_known_gap_non_open_with_resolution_ref_passes(self) -> None:
        d = self._doc_with_kg({"id": "KG.1", "gap": "g", "status": "promoted", "resolution_ref": "CD.18"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.known_gaps[0].status == "promoted"
        assert doc.known_gaps[0].resolution_ref == "CD.18"

    def test_open_question_open_status_no_resolution_ref_required(self) -> None:
        d = self._doc_with_oq({"id": "OQ.1", "question": "q", "status": "open"})
        doc = RoadmapDocument.model_validate(d)
        assert doc.open_questions[0].status == "open"
        assert doc.open_questions[0].resolution_ref is None

    def test_live_roadmap_loads_clean(self) -> None:
        doc = load(_LIVE_ROADMAP)
        non_open_oq = [q for q in doc.open_questions if q.status != "open"]
        non_open_kg = [g for g in doc.known_gaps if g.status != "open"]
        assert len(non_open_oq) == 11
        assert len(non_open_kg) == 4
        for entry in (*non_open_oq, *non_open_kg):
            assert entry.resolution_ref, f"{entry.id} has non-open status but no resolution_ref"
