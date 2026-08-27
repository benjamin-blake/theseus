"""The status-aware dedupe half: a resolved rec's episode is DROPPED, never re-filed, and the two
reader named-verbs that make non-open recs visible from this runtime at all.

Split out of the retired single-file test_budget_ingest.py monolith (rec-3288 wave-4 fixups).
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from scripts.convergence_health import budget_ingest as bi

from .conftest import MARKERS, _artifact, _budget_block, _caller_for, _fetcher_for, _full_rec, _ingest_one, _rec, _ToyWarehouse

_DROPPED = {
    "action": "drop",
    "rec_id": "rec-4001",
    "branch": "claude/slow-branch",
    "dominant_phase": "pytest",
    "runs": 1,
}


class TestResolvedRecsAreNeverResurrected:
    """Correctness 1: the trigger is an IMMUTABLE artifact inside its 14-day retention, so closing
    the rec does not remove it. An open-recs-only dedupe re-files a human-closed rec every hour,
    for up to 14 days -- the defect scripts/ci_rca/dedup.py already solved ("a CLOSED head is never
    bumped")."""

    def _tick(self, warehouse: _ToyWarehouse) -> dict[str, Any]:
        return _ingest_one(
            portal_caller=warehouse.portal,
            open_recs=warehouse.open_recs,
            resolved_recs=warehouse.resolved_recs,
        )

    def test_a_closed_rec_is_never_re_filed_by_a_later_tick(self) -> None:
        warehouse = _ToyWarehouse()
        first = self._tick(warehouse)
        assert first["actions"][0]["action"] == "file"
        assert len(warehouse.recs) == 1

        warehouse.close("rec-4001")
        for _ in range(3):
            later = self._tick(warehouse)
            assert later["actions"] == [_DROPPED]
            assert len(warehouse.recs) == 1
            assert warehouse.recs[0]["status"] == "closed"

    def test_a_dropped_episode_is_never_reopened_or_updated(self) -> None:
        warehouse = _ToyWarehouse()
        self._tick(warehouse)
        warehouse.close("rec-4001")
        before = dict(warehouse.recs[0])
        self._tick(warehouse)
        assert warehouse.recs[0] == before

    def test_a_resolved_rec_for_another_phase_does_not_suppress_the_file(self) -> None:
        resolved = _full_rec(context="Branch: claude/slow-branch. Dominant phase: mypy.")
        result = _ingest_one(portal_caller=lambda action, fields: "rec-4002", resolved_recs=[resolved])
        assert result["actions"][0]["action"] == "file"

    def test_an_open_rec_wins_over_a_resolved_one_for_the_same_episode(self) -> None:
        result = _ingest_one(
            portal_caller=lambda action, fields: None,
            open_recs=[_rec("rec-3001")],
            resolved_recs=[_full_rec("rec-3000")],
        )
        assert result["actions"][0] == {
            "action": "update",
            "rec_id": "rec-3001",
            "branch": "claude/slow-branch",
            "dominant_phase": "pytest",
            "runs": 1,
        }

    @pytest.mark.parametrize("status", sorted(bi.RESOLVED_REC_STATUSES))
    def test_every_resolved_status_drops_the_episode(self, status: str) -> None:
        resolved = _full_rec(status=status)
        assert bi._find_resolved_budget_breach_rec([resolved], "claude/slow-branch", "pytest") is resolved

    def test_the_resolved_status_vocabulary_tracks_the_schema_source_of_truth(self) -> None:
        from src.common.ducklake_scd2_schema import STATUS_TRANSITIONS

        assert bi.RESOLVED_REC_STATUSES == STATUS_TRANSITIONS["ops_recommendations"]["resolved"]

    def test_an_in_flight_rec_is_neither_a_resolved_match_nor_dropped(self) -> None:
        assert bi._find_resolved_budget_breach_rec([_full_rec(status="in_progress")], "claude/slow-branch", "pytest") is None

    def test_a_resolved_rec_of_another_source_is_ignored(self) -> None:
        bypass = _full_rec(source="budget_bypass")
        assert bi._find_resolved_budget_breach_rec([bypass], "claude/slow-branch", "pytest") is None

    def test_the_dry_run_reports_a_drop_without_touching_the_portal(self, capsys: pytest.CaptureFixture[str]) -> None:
        def _explode(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("--dry-run must never reach the portal")

        result = _ingest_one(portal_caller=_explode, resolved_recs=[_full_rec()], dry_run=True)
        assert result["actions"][0]["action"] == "would_drop"
        assert "would_drop" in capsys.readouterr().out


class TestFetchResolvedBudgetRecs:
    """The reader half: two named verbs, because no single verb returns non-open recs WITH context."""

    def _reader(self, prefix_rows: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> Any:
        reader = MagicMock()

        def _named(verb: str, **params: Any) -> list[dict[str, Any]]:
            if verb == "recs_by_title_prefix":
                return prefix_rows
            if verb == "rec_by_id":
                row = by_id.get(params["id"])
                return [row] if row is not None else []
            raise AssertionError(f"unexpected verb {verb!r}")

        reader.named.side_effect = _named
        return reader

    def test_binds_the_branch_into_the_any_status_title_prefix_verb(self) -> None:
        reader = self._reader([], {})
        with patch("src.common.ducklake_reader_client.make_reader", return_value=reader):
            assert bi._fetch_resolved_budget_recs("claude/slow-branch", profile="agent_platform") == []
        reader.named.assert_called_once_with("recs_by_title_prefix", title_prefix="Fast-tier budget%on claude/slow-branch")

    def test_hydrates_only_resolved_budget_breach_candidates(self) -> None:
        prefix_rows = [
            {"id": "rec-1", "status": "closed", "source": "budget_breach"},
            {"id": "rec-2", "status": "open", "source": "budget_breach"},
            {"id": "rec-3", "status": "closed", "source": "budget_bypass"},
        ]
        full = _full_rec("rec-1", context=MARKERS)
        reader = self._reader(prefix_rows, {"rec-1": full})
        with patch("src.common.ducklake_reader_client.make_reader", return_value=reader):
            resolved = bi._fetch_resolved_budget_recs("claude/slow-branch")
        assert resolved == [full]
        assert [call.args[0] for call in reader.named.call_args_list] == ["recs_by_title_prefix", "rec_by_id"]

    def test_one_reader_sweep_per_branch_even_with_several_phases(self) -> None:
        calls: list[str] = []

        def _fetch(branch: str, profile: Optional[str] = None) -> list[dict[str, Any]]:
            calls.append(branch)
            return []

        with patch("scripts.convergence_health.budget_ingest._fetch_resolved_budget_recs", side_effect=_fetch):
            bi.ingest_budget_breaches(
                gh_caller=_caller_for([_artifact(1), _artifact(2)]),
                artifact_fetcher=_fetcher_for(
                    {
                        1: {"budget": _budget_block(dominant_phase="pytest")},
                        2: {"budget": _budget_block(dominant_phase="mypy")},
                    }
                ),
                portal_caller=lambda action, fields: "rec-4004",
                open_recs=[],
            )
        assert calls == ["claude/slow-branch"]


class TestFacadeSurface:
    """The scripts.convergence_health facade re-exports budget_ingest's public surface (Decision
    128 facade pattern). Unpinned re-exports are deletable with the suite green -- pin them."""

    _NAMES = (
        "ARTIFACT_NAME",
        "INGESTED_OUTCOMES",
        "MANIFEST_MEMBER",
        "collect_budget_episodes",
        "extract_budget_block",
        "ingest_budget_breaches",
    )

    @pytest.mark.parametrize("name", _NAMES)
    def test_name_resolves_off_the_package_and_is_the_submodule_attribute(self, name: str) -> None:
        import scripts.convergence_health as facade

        assert hasattr(facade, name), f"{name} is not re-exported by scripts.convergence_health"
        assert getattr(facade, name) is getattr(bi, name)

    @pytest.mark.parametrize("name", _NAMES)
    def test_name_is_declared_in_the_package_all(self, name: str) -> None:
        import scripts.convergence_health as facade

        assert name in facade.__all__
