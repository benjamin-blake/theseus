"""Unit tests for scripts/north_star_tracker.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.north_star_tracker as nst
import scripts.s3_log_store as s3_mod


def _entry(days_ago: int, done: str) -> str:
    """Build one SESSION_LOG entry dated relative to wall clock, never a frozen literal."""
    stamp = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return f"## [{stamp}] Session\n\n**Done:** {done}\n\n"


def _log_body(infra: int, fixes: int) -> str:
    parts = [_entry(i % 10, "infra pipeline tuning") for i in range(infra)]
    parts += [_entry(i % 10, "fix a login bug") for i in range(fixes)]
    return "".join(parts)


def _write_session_log(root: Path, body: str) -> None:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "SESSION_LOG.md").write_text(body, encoding="utf-8")


def _redirect_main_seams(monkeypatch, root: Path) -> list[dict]:
    """Redirect all three live-tree seams of north_star_tracker.main into *root*.

    ROOT carries the SESSION_LOG read, JSONL_LOG carries the only real filesystem write
    (main's JSONL_LOG.parent.mkdir), and append_jsonl is swapped for a recorder so the
    emitted record is assertable without touching the repository tree.
    """
    records: list[dict] = []

    def _recorder(key: str, entry: dict) -> bool:
        records.append(entry)
        return True

    monkeypatch.setattr(nst, "ROOT", root)
    monkeypatch.setattr(nst, "JSONL_LOG", root / "logs" / ".north-star-log.jsonl")
    monkeypatch.setattr(nst, "append_jsonl", _recorder)
    return records


class TestAppendJsonlLocalMode:
    """Tests for append_jsonl() used by north_star_tracker in local mode."""

    def test_appends_to_local_log(self, tmp_path: Path, monkeypatch) -> None:
        import json

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        with patch.object(s3_mod, "_LOGS_DIR", log_dir):
            with patch.object(s3_mod, "_BOTO3_AVAILABLE", False):
                from scripts.s3_log_store import append_jsonl

                result = append_jsonl(".north-star-log.jsonl", {"timestamp": "2026-01-01", "score": 5})
        assert result is True
        log_file = log_dir / ".north-star-log.jsonl"
        assert log_file.exists()
        data = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert data["score"] == 5

    def test_creates_parent_dirs_if_missing(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        log_dir = tmp_path / "logs"
        # Do NOT create the directory — append_jsonl should create it
        with patch.object(s3_mod, "_LOGS_DIR", log_dir):
            with patch.object(s3_mod, "_BOTO3_AVAILABLE", False):
                from scripts.s3_log_store import append_jsonl

                result = append_jsonl(".north-star-log.jsonl", {"score": 1})
        assert result is True
        assert (log_dir / ".north-star-log.jsonl").exists()


class TestParseSessionLog:
    """parse_session_log: the wall-clock cutoff filter and the bad-date swallow."""

    def test_recent_entry_kept_and_stale_entry_dropped(self) -> None:
        content = _entry(1, "fix a recent bug") + _entry(400, "fix an ancient bug")
        joined = "".join(nst.parse_session_log(content))
        assert "fix a recent bug" in joined
        assert "fix an ancient bug" not in joined

    def test_cutoff_days_parameter_moves_the_boundary(self) -> None:
        content = _entry(10, "fix a ten day old bug")
        assert "fix a ten day old bug" in "".join(nst.parse_session_log(content, cutoff_days=30))
        assert nst.parse_session_log(content, cutoff_days=2) == []

    def test_impossible_date_is_swallowed_and_later_entries_still_parse(self) -> None:
        content = "## [2026-13-45] Session\n\n**Done:** fix an impossible date\n\n" + _entry(1, "fix a real bug")
        joined = "".join(nst.parse_session_log(content))
        assert "fix an impossible date" not in joined
        assert "fix a real bug" in joined

    def test_content_without_entry_headers_returns_empty(self) -> None:
        assert nst.parse_session_log("no session headers at all\n") == []


class TestCategoriseSession:
    """categorise_session: a CATEGORIES table hit plus both other fallbacks."""

    def test_table_hit_returns_the_matching_category(self) -> None:
        assert nst.categorise_session("**Done:** refactor the module layout") == "refactor"

    def test_done_line_matching_no_pattern_returns_other(self) -> None:
        assert nst.categorise_session("**Done:** zzz qqq") == "other"

    def test_entry_without_a_done_line_returns_other(self) -> None:
        assert nst.categorise_session("Session notes without a done marker.\n") == "other"


class TestMainReport:
    """main(): the missing-SESSION_LOG early exit and both infra-ratio branches."""

    def test_missing_session_log_exits_early(self, tmp_path: Path, monkeypatch, capsys) -> None:
        records = _redirect_main_seams(monkeypatch, tmp_path)
        assert tmp_path in nst.JSONL_LOG.parents
        with pytest.raises(SystemExit) as exc:
            nst.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "SESSION_LOG.md not found. Skipping North Star tracker." in out
        assert "North Star Tracker" not in out
        assert records == []
        assert not (tmp_path / "logs").exists()

    def test_infra_ratio_above_threshold_takes_the_warn_branch(self, tmp_path: Path, monkeypatch, capsys) -> None:
        records = _redirect_main_seams(monkeypatch, tmp_path)
        _write_session_log(tmp_path, _log_body(infra=7, fixes=10))
        assert tmp_path in nst.JSONL_LOG.parents
        with pytest.raises(SystemExit) as exc:
            nst.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "WARN - Infra/Meta sessions are 41% of recent total (threshold: 40%)." in out
        assert "meta-work is crowding out product work" in out
        assert "OK   - Infra/Meta ratio" not in out
        assert "North Star momentum : 59%" in out
        assert (tmp_path / "logs").is_dir()
        assert records[-1]["infra_ratio_pct"] == 41
        assert records[-1]["sessions_total"] == 17
        assert records[-1]["infra_count"] == 7
        assert records[-1]["fix_count"] == 10

    def test_infra_ratio_at_the_threshold_takes_the_ok_branch(self, tmp_path: Path, monkeypatch, capsys) -> None:
        records = _redirect_main_seams(monkeypatch, tmp_path)
        _write_session_log(tmp_path, _log_body(infra=2, fixes=3))
        assert tmp_path in nst.JSONL_LOG.parents
        with pytest.raises(SystemExit) as exc:
            nst.main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "OK   - Infra/Meta ratio 40% is within the 40% threshold." in out
        assert "WARN - Infra/Meta sessions are" not in out
        assert "North Star momentum : 60%" in out
        assert (tmp_path / "logs").is_dir()
        assert records[-1]["infra_ratio_pct"] == 40
        assert records[-1]["sessions_total"] == 5
        assert records[-1]["infra_count"] == 2
        assert records[-1]["feature_count"] == 0
