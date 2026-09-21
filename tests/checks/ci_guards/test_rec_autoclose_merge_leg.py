"""End-to-end: rec-3775's own acceptance predicate. close_recs_from_trailer leaves every named
rec OPEN on a plan-only changed set and closes them on a code-bearing one, with the warehouse
boundary stubbed (the shape tests/ci_rca/test_close_recs_from_trailer.py already established).
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

_COMMIT_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
_RUN_URL = "https://x/runs/1"


class TestPlanOnlyMergeLeavesRecsOpen:
    def test_plan_only_changed_set_closes_nothing(self) -> None:
        with (
            patch(
                "scripts.ops_portal.ci_rca_lifecycle.changed_files",
                return_value={"docs/plans/PLAN-example.yaml"},
            ),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            rc = close_recs_from_trailer(
                ["rec-1", "rec-2"], _COMMIT_SHA, _RUN_URL, {"rec-1": {"status": "open"}, "rec-2": {"status": "open"}}
            )

        assert rc == 0
        mock_update.assert_not_called()

    def test_empty_changed_set_closes_nothing(self) -> None:
        with (
            patch("scripts.ops_portal.ci_rca_lifecycle.changed_files", return_value=set()),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            rc = close_recs_from_trailer(["rec-1"], _COMMIT_SHA, _RUN_URL, {"rec-1": {"status": "open"}})

        assert rc == 0
        mock_update.assert_not_called()

    def test_none_changed_set_closes_nothing(self) -> None:
        with (
            patch("scripts.ops_portal.ci_rca_lifecycle.changed_files", return_value=None),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            rc = close_recs_from_trailer(["rec-1"], _COMMIT_SHA, _RUN_URL, {"rec-1": {"status": "open"}})

        assert rc == 0
        mock_update.assert_not_called()

    def test_refusal_prints_a_greppable_marker_naming_the_recs(self, capsys) -> None:  # noqa: ANN001
        with patch(
            "scripts.ops_portal.ci_rca_lifecycle.changed_files",
            return_value={"docs/plans/PLAN-example.yaml"},
        ):
            rc = close_recs_from_trailer(["rec-1", "rec-2"], _COMMIT_SHA, _RUN_URL, {})

        assert rc == 0
        out = capsys.readouterr().out
        assert "rec-1" in out
        assert "rec-2" in out
        assert "REC-AUTOCLOSE" in out


class TestCodeBearingMergeCloses:
    def test_code_bearing_changed_set_closes_normally(self) -> None:
        with (
            patch(
                "scripts.ops_portal.ci_rca_lifecycle.changed_files",
                return_value={"scripts/rec_trailer.py"},
            ),
            patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update,
        ):
            rc = close_recs_from_trailer(["rec-1"], _COMMIT_SHA, _RUN_URL, {"rec-1": {"status": "open"}})

        assert rc == 0
        mock_update.assert_called_once()

    def test_mixed_plan_and_code_changed_set_closes_normally(self) -> None:
        with (
            patch(
                "scripts.ops_portal.ci_rca_lifecycle.changed_files",
                return_value={"docs/plans/PLAN-example.yaml", "scripts/rec_trailer.py"},
            ),
            patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update,
        ):
            rc = close_recs_from_trailer(["rec-1"], _COMMIT_SHA, _RUN_URL, {"rec-1": {"status": "open"}})

        assert rc == 0
        mock_update.assert_called_once()
