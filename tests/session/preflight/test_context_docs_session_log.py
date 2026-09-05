"""Session-log ordering boundary: parse_last_session and read_context_files' recent_sessions both
select by PARSED DATE through context_docs._read_session_blocks, and every unavailability routes to
the empty sentinel PLUS one attributed stderr line.

Both halves of every signal are pinned here. The positive half (an out-of-order log warns, an
absent or unreadable log names the path it could not read) is worthless without the negative half
(the live newest-first log emits NEITHER line across BOTH call sites), because an implementation
that WARNs unconditionally would otherwise satisfy every positive assertion.

Every construct this module exercises is reached as an ATTRIBUTE of the imported module, never as
a symbol-level from-import: a from-import of a name that exists only on the working tree raises
ImportError at COLLECTION time on an origin/main worktree, which pytest reports as exit code 2 and
the failing-first proof classifies as infrastructure failure rather than as red.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.preflight import _common as preflight_common
from scripts.preflight import context_docs

boto3 = pytest.importorskip("boto3")

# Named once so every live-tree-coupled case in this module points a red run at the data first.
_LIVE_LOG_DATA = (
    "DATA condition, not a code regression: docs/SESSION_LOG.md must be newest-first and carry a "
    "parseable ## [YYYY-MM-DD] header -- re-order or repair the log before reading "
    "scripts/preflight/context_docs.py"
)

_NEWEST_FIRST = "## [2026-05-09] - newer\n## [2026-05-01] - older\n"
_OLDEST_FIRST = "## [2026-05-01] - older\n## [2026-05-09] - newer\n"


def _log(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "SESSION_LOG.md"
    path.write_text(text, encoding="utf-8")
    return path


def _five_descending(tmp_path: Path) -> Path:
    body = "".join(f"## [2026-04-0{n}] - entry {n}\n" for n in range(1, 8))
    return _log(tmp_path, body)


class TestSessionLogOrdering:
    def test_parse_last_session_newest_from_newest_first_fixture(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", _log(tmp_path, _NEWEST_FIRST))
        assert "2026-05-09" in context_docs.parse_last_session()

    def test_parse_last_session_newest_from_oldest_first_fixture(self, tmp_path: Path, monkeypatch) -> None:
        """The boundary is correct under EITHER convention: date wins over file position."""
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", _log(tmp_path, _OLDEST_FIRST))
        assert "2026-05-09" in context_docs.parse_last_session()

    def test_out_of_order_log_emits_attributed_warn_with_first_and_max(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", _log(tmp_path, _OLDEST_FIRST))
        context_docs.parse_last_session()
        err = capsys.readouterr().err
        assert "is not newest-first" in err
        assert "first=2026-05-01" in err
        assert "max=2026-05-09" in err

    def test_recent_sessions_are_the_newest_five_in_descending_order(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", _five_descending(tmp_path))
        monkeypatch.setattr(preflight_common, "ROADMAP_FILE", tmp_path / "absent-roadmap.yaml")
        monkeypatch.setattr(preflight_common, "DECISIONS_FILE", tmp_path / "absent-decisions.md")
        recent = context_docs.read_context_files(open_recs_count=0)["recent_sessions"]
        dates = [entry[4:14] for entry in recent]
        assert len(dates) == 5
        assert dates == sorted(dates, reverse=True)
        assert dates[0] == "2026-04-07"

    def test_done_line_suffix_still_appends(self, tmp_path: Path, monkeypatch) -> None:
        """The Done-line half of the grammar is unchanged: a Done line on the IMMEDIATELY next
        line still appends its suffix, and the header text either call site produces is untouched.
        """
        monkeypatch.setattr(
            preflight_common,
            "SESSION_LOG_FILE",
            _log(tmp_path, "## [2026-05-09] - newer\n**Done:** shipped the thing\n"),
        )
        monkeypatch.setattr(preflight_common, "ROADMAP_FILE", tmp_path / "absent-roadmap.yaml")
        monkeypatch.setattr(preflight_common, "DECISIONS_FILE", tmp_path / "absent-decisions.md")
        recent = context_docs.read_context_files(open_recs_count=0)["recent_sessions"]
        assert recent == ["## [2026-05-09] - newer -- shipped the thing"]

    def test_production_shape_last_session_is_the_live_logs_newest_header(self) -> None:
        """Production shape, against the REAL docs/SESSION_LOG.md -- a mirror-test divergence
        cannot hide behind a fixture. The expected date is DERIVED from the file through the same
        parse the boundary uses, never pinned as a literal."""
        content = preflight_common.SESSION_LOG_FILE.read_text(encoding="utf-8", errors="replace")
        dates = [m.group(2) for m in context_docs._SESSION_BLOCK_RE.finditer(content)]
        parseable = [d for d in dates if context_docs._session_sort_key(d) != context_docs._UNPARSEABLE_SESSION_DATE]
        assert parseable, f"{_LIVE_LOG_DATA} -- the live session log carries no parseable session header"
        newest = max(parseable, key=context_docs._session_sort_key)
        last = context_docs.parse_last_session()
        assert newest in last, f"{_LIVE_LOG_DATA} -- newest parsed date {newest} is not the header named by {last!r}"

    def test_production_shape_recent_sessions_are_descending(self) -> None:
        """The live log's own newest date must head recent_sessions -- the tail of a newest-first
        file is also descending, so descending order ALONE does not discriminate the defect."""
        content = preflight_common.SESSION_LOG_FILE.read_text(encoding="utf-8", errors="replace")
        parseable = [
            m.group(2)
            for m in context_docs._SESSION_BLOCK_RE.finditer(content)
            if context_docs._session_sort_key(m.group(2)) != context_docs._UNPARSEABLE_SESSION_DATE
        ]
        recent = context_docs.read_context_files(open_recs_count=0)["recent_sessions"]
        dates = [entry[4:14] for entry in recent]
        assert dates, f"{_LIVE_LOG_DATA} -- the live session log yielded no recent sessions"
        assert dates == sorted(dates, reverse=True), f"{_LIVE_LOG_DATA} -- recent_sessions is not descending: {dates}"
        newest = max(parseable, key=context_docs._session_sort_key)
        assert dates[0] == newest, f"{_LIVE_LOG_DATA} -- recent_sessions heads {dates[0]}, newest parsed is {newest}"

    def test_live_log_silence_across_both_call_sites(self, capsys: pytest.CaptureFixture) -> None:
        """(a) LIVE-LOG SILENCE -- the negative half of the ordering signal. The real newest-first
        log emits NO not-newest-first line and NO unavailability line through EITHER call site, so
        an implementation that emits the WARN unconditionally cannot pass."""
        context_docs.parse_last_session()
        context_docs.read_context_files(open_recs_count=0)
        err = capsys.readouterr().err
        assert "is not newest-first" not in err, f"{_LIVE_LOG_DATA} -- the ordering WARN fired on the live log: {err}"
        assert "UNAVAILABLE" not in err, f"{_LIVE_LOG_DATA} -- an unavailability fired on the live log: {err}"

    def test_absent_log_returns_sentinel_and_names_the_path(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """(b) ABSENT-LOG ATTRIBUTION -- an absent log is an unavailability and owes a line."""
        gone = tmp_path / "no-such-log.md"
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", gone)
        assert context_docs.parse_last_session() == ""
        err = capsys.readouterr().err
        assert "[WARN]" in err
        assert "session log UNAVAILABLE" in err
        assert str(gone) in err

    def test_unreadable_log_reaches_the_same_line_through_oserror(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """(c) UNREADABLE-LOG ATTRIBUTION -- a directory-shaped log exists() but cannot be read."""
        shadowed = tmp_path / "dir-log.md"
        shadowed.mkdir()
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", shadowed)
        assert context_docs.parse_last_session() == ""
        err = capsys.readouterr().err
        assert "[WARN]" in err
        assert "session log UNAVAILABLE" in err
        assert str(shadowed) in err

    def test_undecodable_byte_is_salvaged_not_blanked(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """(d) UNDECODABLE-BYTE SALVAGE -- errors=replace keeps the log, one stray byte does not
        blank it, and no unavailability is claimed for a file that WAS read."""
        raw = tmp_path / "raw.md"
        raw.write_bytes(b"## [2026-05-09] - undecodable \xff byte\n")
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", raw)
        assert "2026-05-09" in context_docs.parse_last_session()
        assert "UNAVAILABLE" not in capsys.readouterr().err

    def test_mid_file_unparseable_header_warns_alone(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        """(e) MID-FILE UNPARSEABLE HEADER -- the order comparison runs over PARSEABLE dates only,
        so a data defect is never misattributed as a convention violation."""
        monkeypatch.setattr(
            preflight_common,
            "SESSION_LOG_FILE",
            _log(tmp_path, "## [2026-05-09] - a\n## [2026-13-45] - impossible\n## [2026-05-01] - c\n"),
        )
        assert "2026-05-09" in context_docs.parse_last_session()
        err = capsys.readouterr().err
        assert "do not parse" in err
        assert "2026-13-45" in err
        assert "is not newest-first" not in err, err


class TestSessionLogOrderingTotality:
    """Nine session-log shapes; every cell asserts a RETURN VALUE or a key TYPE, never an
    exception."""

    def _drive(self, monkeypatch, path: Path) -> tuple[str, list]:
        monkeypatch.setattr(preflight_common, "SESSION_LOG_FILE", path)
        return context_docs.parse_last_session(), context_docs._read_session_blocks()

    def test_absent_file(self, tmp_path: Path, monkeypatch) -> None:
        last, blocks = self._drive(monkeypatch, tmp_path / "absent.md")
        assert last == ""
        assert blocks == []

    def test_unstattable_path_returns_the_sentinel_and_names_it(self, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        """Path.exists re-raises any OSError outside (ENOENT, ENOTDIR, EBADF, ELOOP); ENAMETOOLONG
        and EACCES are both outside it, so the probe must sit inside the guard or main() raises."""
        last, blocks = self._drive(monkeypatch, Path("/" + "n" * 300) / "SESSION_LOG.md")
        assert last == ""
        assert blocks == []
        err = capsys.readouterr().err
        assert "session log UNAVAILABLE" in err, err
        assert "could not be read" in err, err

    def test_empty_file(self, tmp_path: Path, monkeypatch) -> None:
        last, blocks = self._drive(monkeypatch, _log(tmp_path, ""))
        assert last == ""
        assert blocks == []

    def test_newest_first_file(self, tmp_path: Path, monkeypatch) -> None:
        last, blocks = self._drive(monkeypatch, _log(tmp_path, _NEWEST_FIRST))
        assert "2026-05-09" in last
        assert len(blocks) == 2

    def test_oldest_first_file(self, tmp_path: Path, monkeypatch) -> None:
        last, blocks = self._drive(monkeypatch, _log(tmp_path, _OLDEST_FIRST))
        assert "2026-05-09" in last
        assert len(blocks) == 2

    def test_impossible_calendar_date(self, tmp_path: Path, monkeypatch) -> None:
        last, blocks = self._drive(monkeypatch, _log(tmp_path, "## [2026-13-45] - impossible\n## [2026-01-02] - real\n"))
        assert "2026-01-02" in last
        assert "2026-13-45" in blocks[-1][0]

    def test_file_of_undecodable_bytes(self, tmp_path: Path, monkeypatch) -> None:
        path = tmp_path / "SESSION_LOG.md"
        path.write_bytes(b"\xff\xfe\xfd\x00\x01\x02")
        last, blocks = self._drive(monkeypatch, path)
        assert last == ""
        assert blocks == []

    def test_unreadable_file(self, tmp_path: Path, monkeypatch) -> None:
        path = tmp_path / "dir-shaped"
        path.mkdir()
        last, blocks = self._drive(monkeypatch, path)
        assert last == ""
        assert blocks == []

    def test_sort_key_is_a_date_and_never_a_datetime(self) -> None:
        """The ordering key's TYPE, pinned rather than left to construction. datetime subclasses
        date, so isinstance would not discriminate: a key returned as a bare datetime compares
        against the date.min sentinel and raises TypeError on a mixed log."""
        for raw in ("2026-05-09", "2026-13-45", "not-a-date"):
            key = context_docs._session_sort_key(raw)
            assert type(key) is date, (raw, type(key))
            assert not isinstance(key, datetime), (raw, type(key))

    def test_mixed_parseable_and_unparseable_headers_sort_without_raising(self, tmp_path: Path, monkeypatch) -> None:
        """The cell the TYPE pin exists for: sorting compares a parsed key against the sentinel, so
        a bare-datetime key would raise TypeError here rather than return a value."""
        text = "## [2026-05-09] - a\n## [2026-13-45] - impossible\n## [2026-05-01] - c\n"
        last, blocks = self._drive(monkeypatch, _log(tmp_path, text))
        assert "2026-05-09" in last
        assert len(blocks) == 3
        assert "2026-13-45" in blocks[-1][0]
