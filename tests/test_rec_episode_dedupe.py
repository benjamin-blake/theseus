"""Mirror test for scripts/rec_episode_dedupe.py (rec-3291 / rec-3563 migration): keeper
selection is the newest open rec PER SOURCE (title-blind, matching the runtime find_rec lookup),
--propose writes nothing, and --confirm closes exactly the proposed set.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from scripts.rec_episode_dedupe import confirm, main, propose, select_keeper


def _rec(rec_id: str, created: str) -> dict[str, Any]:
    return {"id": rec_id, "source": "tf_convergence_stale", "status": "open", "created_timestamp": created}


class TestSelectKeeper:
    def test_empty_list_returns_none(self) -> None:
        assert select_keeper([]) is None

    def test_single_rec_is_the_keeper(self) -> None:
        rec = _rec("rec-1", "2026-08-01T00:00:00+00:00")
        assert select_keeper([rec]) is rec

    def test_newest_created_timestamp_wins(self) -> None:
        older = _rec("rec-1", "2026-08-01T00:00:00+00:00")
        newer = _rec("rec-2", "2026-08-05T00:00:00+00:00")
        assert select_keeper([older, newer]) is newer

    def test_title_blind_selection(self) -> None:
        """Keyed on source alone -- title never enters the ranking."""
        older = {**_rec("rec-1", "2026-08-01T00:00:00+00:00"), "title": "Z title"}
        newer = {**_rec("rec-2", "2026-08-05T00:00:00+00:00"), "title": "A title"}
        assert select_keeper([older, newer])["id"] == "rec-2"

    def test_tie_breaks_on_larger_numeric_id_suffix(self) -> None:
        same_ts = "2026-08-01T00:00:00+00:00"
        a = _rec("rec-100", same_ts)
        b = _rec("rec-200", same_ts)
        assert select_keeper([a, b])["id"] == "rec-200"

    def test_unparseable_id_does_not_raise(self) -> None:
        weird = {**_rec("rec-abc", "2026-08-01T00:00:00+00:00")}
        normal = _rec("rec-1", "2026-08-01T00:00:00+00:00")
        result = select_keeper([weird, normal])
        assert result is not None


class TestPropose:
    def test_writes_nothing(self) -> None:
        rows = [_rec("rec-1", "2026-08-01T00:00:00+00:00"), _rec("rec-2", "2026-08-05T00:00:00+00:00")]
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=rows) as fr:
            with patch("scripts.ops_data_portal.update_rec") as ur:
                result = propose("tf_convergence_stale")
        fr.assert_called_once_with("tf_convergence_stale", reader=None, profile=None)
        ur.assert_not_called()
        assert result == {"source": "tf_convergence_stale", "keeper": "rec-2", "superseded": ["rec-1"]}

    def test_no_open_recs_proposes_nothing(self) -> None:
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=[]):
            result = propose("tf_convergence_stale")
        assert result == {"source": "tf_convergence_stale", "keeper": None, "superseded": []}

    def test_prints_keeper_and_superseded(self, capsys) -> None:
        rows = [_rec("rec-1", "2026-08-01T00:00:00+00:00"), _rec("rec-2", "2026-08-05T00:00:00+00:00")]
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=rows):
            propose("tf_convergence_stale")
        out = capsys.readouterr().out
        assert "PROPOSE" in out
        assert "rec-2" in out
        assert "rec-1" in out


class TestConfirm:
    def test_closes_every_non_keeper(self) -> None:
        rows = [
            _rec("rec-1", "2026-08-01T00:00:00+00:00"),
            _rec("rec-2", "2026-08-05T00:00:00+00:00"),
            _rec("rec-3", "2026-08-03T00:00:00+00:00"),
        ]
        calls: list[tuple[str, dict[str, Any]]] = []

        def _caller(action: str, fields: dict[str, Any]) -> Any:
            calls.append((action, fields))
            return None

        with patch("scripts.rec_episode_dedupe.find_recs", return_value=rows):
            result = confirm("tf_convergence_stale", portal_caller=_caller)

        assert result == {"source": "tf_convergence_stale", "keeper": "rec-2", "closed": ["rec-1", "rec-3"]}
        assert {c[0] for c in calls} == {"close"}
        assert {c[1]["id"] for c in calls} == {"rec-1", "rec-3"}
        for _, fields in calls:
            assert fields["status"] == "closed"
            assert "rec-2" in fields["resolution"]

    def test_no_open_recs_closes_nothing(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=[]):
            result = confirm("tf_convergence_stale", portal_caller=lambda a, f: calls.append((a, f)))
        assert result == {"source": "tf_convergence_stale", "keeper": None, "closed": []}
        assert calls == []

    def test_single_open_rec_closes_nothing(self) -> None:
        rows = [_rec("rec-1", "2026-08-01T00:00:00+00:00")]
        calls: list[tuple[str, dict[str, Any]]] = []
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=rows):
            result = confirm("tf_convergence_stale", portal_caller=lambda a, f: calls.append((a, f)))
        assert result == {"source": "tf_convergence_stale", "keeper": "rec-1", "closed": []}
        assert calls == []

    def test_no_portal_caller_uses_real_update_rec(self) -> None:
        rows = [_rec("rec-1", "2026-08-01T00:00:00+00:00"), _rec("rec-2", "2026-08-05T00:00:00+00:00")]
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=rows):
            with patch("scripts.ops_data_portal.update_rec") as ur:
                confirm("tf_convergence_stale")
        ur.assert_called_once()
        assert ur.call_args[0][0] == "rec-1"
        assert ur.call_args[0][1]["status"] == "closed"

    def test_confirm_re_derives_population_fresh(self) -> None:
        """confirm() never reuses a prior propose() call's result -- it re-fetches, so a
        population that moved between propose and confirm is reflected correctly."""
        with patch("scripts.rec_episode_dedupe.find_recs", return_value=[_rec("rec-1", "t")]) as fr:
            propose("tf_convergence_stale")
            confirm("tf_convergence_stale", portal_caller=lambda a, f: None)
        assert fr.call_count == 2


class TestMain:
    def test_no_source_prints_usage_and_exits_2(self, capsys) -> None:
        assert main(["--propose"]) == 2

    def test_no_mode_prints_usage_and_exits_2(self, capsys) -> None:
        assert main(["tf_convergence_stale"]) == 2

    def test_both_modes_prints_usage_and_exits_2(self, capsys) -> None:
        assert main(["tf_convergence_stale", "--propose", "--confirm"]) == 2

    def test_propose_mode_calls_propose_not_confirm(self) -> None:
        with patch("scripts.rec_episode_dedupe.propose") as p, patch("scripts.rec_episode_dedupe.confirm") as c:
            code = main(["tf_convergence_stale", "--propose"])
        assert code == 0
        p.assert_called_once_with("tf_convergence_stale", profile=None)
        c.assert_not_called()

    def test_confirm_mode_calls_confirm_not_propose(self) -> None:
        with patch("scripts.rec_episode_dedupe.propose") as p, patch("scripts.rec_episode_dedupe.confirm") as c:
            code = main(["tf_convergence_stale", "--confirm"])
        assert code == 0
        c.assert_called_once_with("tf_convergence_stale", profile=None)
        p.assert_not_called()

    def test_profile_flag_is_forwarded(self) -> None:
        with patch("scripts.rec_episode_dedupe.propose") as p:
            main(["tf_convergence_stale", "--propose", "--profile", "agent_platform"])
        p.assert_called_once_with("tf_convergence_stale", profile="agent_platform")
