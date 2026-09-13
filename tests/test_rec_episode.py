"""Mirror test for scripts/rec_episode.py (rec-3291 / rec-3563): find_recs/find_rec's scoped
read + runtime projection assertion, decide()'s four-state truth table, run_episode's
file/update/close orchestration (including build_update returning None as a no-op), and main()'s
read-only --probe/--count diagnostics.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.rec_episode import decide, find_rec, find_recs, main, run_episode


def test_find_rec_raises_when_filtered_key_absent() -> None:
    """VP step 1 / rec-3291's acceptance oracle node id (verbatim): find_rec raises on rows
    lacking `source`/`status` rather than silently returning None."""
    with pytest.raises(RuntimeError, match="missing filtered key"):
        find_rec("x", rows=[{"id": "rec-1"}])


class TestFindRecs:
    def test_scopes_by_source_and_status(self) -> None:
        rows = [
            {"id": "rec-1", "source": "tf_convergence_stale", "status": "open"},
            {"id": "rec-2", "source": "tf_convergence_stale", "status": "closed"},
            {"id": "rec-3", "source": "ci_rca", "status": "open"},
        ]
        result = find_recs("tf_convergence_stale", rows=rows)
        assert [r["id"] for r in result] == ["rec-1"]

    def test_empty_rows_returns_empty_list(self) -> None:
        assert find_recs("tf_convergence_stale", rows=[]) == []

    def test_raises_when_a_row_is_missing_source_or_status(self) -> None:
        """rec-3291 / rec-3563: a row a scoped read hands back without a key this lookup filters
        on must raise, never be silently treated as no-match."""
        with pytest.raises(RuntimeError, match="missing filtered key"):
            find_recs("tf_convergence_stale", rows=[{"id": "rec-1"}])

    def test_raises_when_only_status_is_missing(self) -> None:
        with pytest.raises(RuntimeError, match="missing filtered key"):
            find_recs("tf_convergence_stale", rows=[{"id": "rec-1", "source": "tf_convergence_stale"}])

    def test_live_reader_is_scoped_via_structural_row_filter(self) -> None:
        reader = MagicMock()
        reader.current_state.return_value = []
        find_recs("tf_convergence_stale", reader=reader)
        reader.current_state.assert_called_once_with("ops_recommendations", row_filter="source = 'tf_convergence_stale'")

    def test_default_reader_built_from_profile(self) -> None:
        reader = MagicMock()
        reader.current_state.return_value = []
        with patch("src.common.ducklake_reader_client.make_reader", return_value=reader) as mk:
            find_recs("tf_convergence_stale", profile="agent_platform")
        mk.assert_called_once_with(profile="agent_platform")

    def test_reader_failure_raises_instead_of_degrading_to_empty(self) -> None:
        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("ducklake_reader unreachable")
        with pytest.raises(RuntimeError, match="ducklake_reader unreachable"):
            find_recs("tf_convergence_stale", reader=reader)


class TestFindRec:
    def test_returns_single_match(self) -> None:
        rows = [{"id": "rec-1", "source": "x", "status": "open"}]
        assert find_rec("x", rows=rows) is rows[0]

    def test_returns_none_when_no_match(self) -> None:
        assert find_rec("x", rows=[{"id": "rec-1", "source": "y", "status": "open"}]) is None

    def test_returns_first_match_when_multiple_open(self) -> None:
        rows = [
            {"id": "rec-1", "source": "x", "status": "open"},
            {"id": "rec-2", "source": "x", "status": "open"},
        ]
        assert find_rec("x", rows=rows)["id"] == "rec-1"

    def test_sub_key_narrows_the_candidate_set(self) -> None:
        rows = [
            {"id": "rec-1", "source": "x", "status": "open", "context": "Branch: a. Dominant phase: lint."},
            {"id": "rec-2", "source": "x", "status": "open", "context": "Branch: b. Dominant phase: lint."},
        ]
        result = find_rec("x", rows=rows, sub_key=lambda r: "Branch: b." in r["context"], sub_key_fields=("context",))
        assert result["id"] == "rec-2"

    def test_sub_key_no_match_returns_none(self) -> None:
        rows = [{"id": "rec-1", "source": "x", "status": "open", "context": "Branch: a."}]
        result = find_rec("x", rows=rows, sub_key=lambda r: "Branch: z." in r["context"], sub_key_fields=("context",))
        assert result is None

    def test_raises_when_sub_key_field_is_absent_on_a_candidate(self) -> None:
        rows = [{"id": "rec-1", "source": "x", "status": "open"}]
        with pytest.raises(RuntimeError, match="missing sub_key field"):
            find_rec("x", rows=rows, sub_key=lambda r: True, sub_key_fields=("context",))

    def test_find_rec_raises_when_reader_unreachable(self) -> None:
        """A deliberate divergence from the other current_state call sites in this repo that fail
        open: a dedup read can never be mistaken for 'no open rec'."""
        reader = MagicMock()
        reader.current_state.side_effect = RuntimeError("unreachable")
        with pytest.raises(RuntimeError, match="unreachable"):
            find_rec("x", reader=reader)


class TestDecide:
    def test_file_when_over_threshold_and_no_open_rec(self) -> None:
        assert decide(over_threshold=True, open_rec_exists=False) == "file"

    def test_update_when_over_threshold_and_open_rec_exists(self) -> None:
        assert decide(over_threshold=True, open_rec_exists=True) == "update"

    def test_close_when_under_threshold_and_open_rec_exists(self) -> None:
        assert decide(over_threshold=False, open_rec_exists=True) == "close"

    def test_none_when_under_threshold_and_no_open_rec(self) -> None:
        assert decide(over_threshold=False, open_rec_exists=False) == "none"


class TestRunEpisode:
    def _kwargs(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "source": "x",
            "over_threshold": True,
            "build_fields": lambda: {"title": "t"},
            "build_update": lambda existing: {"context": "updated"},
            "build_close": lambda existing: {"status": "closed", "resolution": "r"},
        }
        base.update(overrides)
        return base

    def test_files_when_over_threshold_and_no_existing(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        result = run_episode(**self._kwargs(portal_caller=lambda a, f: (calls.append((a, f)), "rec-1")[1], rows=[]))
        assert result == {"action": "file", "rec_id": "rec-1"}
        assert calls[0][0] == "file"

    def test_updates_when_over_threshold_and_existing(self) -> None:
        existing = {"id": "rec-1", "source": "x", "status": "open"}
        calls: list[tuple[str, dict[str, Any]]] = []
        result = run_episode(**self._kwargs(portal_caller=lambda a, f: calls.append((a, f)), rows=[existing]))
        assert result == {"action": "update", "rec_id": "rec-1"}
        assert calls[0] == ("update", {"id": "rec-1", "context": "updated"})

    def test_build_update_returning_none_is_a_no_op(self) -> None:
        existing = {"id": "rec-1", "source": "x", "status": "open"}
        calls: list[tuple[str, dict[str, Any]]] = []
        result = run_episode(
            **self._kwargs(
                build_update=lambda existing: None,
                portal_caller=lambda a, f: calls.append((a, f)),
                rows=[existing],
            )
        )
        assert result == {"action": "unchanged", "rec_id": "rec-1"}
        assert calls == []

    def test_closes_when_under_threshold_and_existing(self) -> None:
        existing = {"id": "rec-1", "source": "x", "status": "open"}
        calls: list[tuple[str, dict[str, Any]]] = []
        result = run_episode(
            **self._kwargs(over_threshold=False, portal_caller=lambda a, f: calls.append((a, f)), rows=[existing])
        )
        assert result == {"action": "close", "rec_id": "rec-1"}
        assert calls[0] == ("close", {"id": "rec-1", "status": "closed", "resolution": "r"})

    def test_none_when_under_threshold_and_no_existing(self) -> None:
        result = run_episode(**self._kwargs(over_threshold=False, rows=[]))
        assert result == {"action": "none", "rec_id": None}

    def test_suppress_file_skips_only_a_fresh_file(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        result = run_episode(**self._kwargs(suppress_file=True, portal_caller=lambda a, f: calls.append((a, f)), rows=[]))
        assert result == {"action": "skipped_suppressed", "rec_id": None}
        assert calls == []

    def test_suppress_file_does_not_suppress_update(self) -> None:
        existing = {"id": "rec-1", "source": "x", "status": "open"}
        calls: list[tuple[str, dict[str, Any]]] = []
        result = run_episode(
            **self._kwargs(suppress_file=True, portal_caller=lambda a, f: calls.append((a, f)), rows=[existing])
        )
        assert result == {"action": "update", "rec_id": "rec-1"}
        assert calls

    def test_unknown_decide_result_falls_through_to_skipped(self) -> None:
        with patch("scripts.rec_episode.decide", return_value="bogus"):
            result = run_episode(**self._kwargs(rows=[]))
        assert result == {"action": "skipped", "rec_id": None}

    def test_no_portal_caller_uses_real_file_rec(self) -> None:
        with patch("scripts.ops_data_portal.file_rec", return_value="rec-live") as fr:
            result = run_episode(**self._kwargs(rows=[]))
        fr.assert_called_once_with({"title": "t"}, profile=None)
        assert result == {"action": "file", "rec_id": "rec-live"}

    def test_no_portal_caller_uses_real_update_rec(self) -> None:
        existing = {"id": "rec-1", "source": "x", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = run_episode(**self._kwargs(rows=[existing]))
        ur.assert_called_once_with("rec-1", {"context": "updated"}, profile=None)
        assert result == {"action": "update", "rec_id": "rec-1"}

    def test_no_portal_caller_uses_real_update_rec_for_close(self) -> None:
        existing = {"id": "rec-1", "source": "x", "status": "open"}
        with patch("scripts.ops_data_portal.update_rec") as ur:
            result = run_episode(**self._kwargs(over_threshold=False, rows=[existing]))
        ur.assert_called_once_with("rec-1", {"status": "closed", "resolution": "r"}, profile=None)
        assert result == {"action": "close", "rec_id": "rec-1"}


class TestMain:
    def test_no_probe_prints_usage_and_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == 2
        assert "usage" in capsys.readouterr().out

    def test_probe_with_no_source_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--probe"]) == 2

    def test_probe_matches_and_exits_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("scripts.rec_episode.find_rec", return_value={"id": "rec-1"}) as fr:
            code = main(["--probe", "tf_convergence_stale"])
        assert code == 0
        fr.assert_called_once_with("tf_convergence_stale", profile=None)
        assert "rec-1" in capsys.readouterr().out

    def test_probe_no_match_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("scripts.rec_episode.find_rec", return_value=None):
            code = main(["--probe", "tf_convergence_stale"])
        assert code == 1
        assert "no open rec" in capsys.readouterr().out

    def test_probe_count_prints_count_and_exits_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("scripts.rec_episode.find_recs", return_value=[{"id": "rec-1"}]) as frs:
            code = main(["--probe", "tf_convergence_stale", "--count"])
        assert code == 0
        frs.assert_called_once_with("tf_convergence_stale", profile=None)
        assert "1 open rec" in capsys.readouterr().out

    def test_profile_flag_is_forwarded(self) -> None:
        with patch("scripts.rec_episode.find_rec", return_value={"id": "rec-1"}) as fr:
            main(["--probe", "x", "--profile", "agent_platform"])
        fr.assert_called_once_with("x", profile="agent_platform")

    def test_no_destructive_verb_is_reachable_from_this_module(self) -> None:
        """No destructive verb lives in this module -- see scripts/rec_episode_dedupe.py."""
        import scripts.rec_episode as mod

        assert not hasattr(mod, "confirm")
        assert not hasattr(mod, "select_keeper")
