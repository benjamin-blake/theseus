"""Data-quality half of the context_docs honesty set: check_data_quality_coverage reads the
directory that actually holds the checks and reports an honest UNKNOWN rather than a hard zero --
for an ABSENT directory and for a present-but-UNREADABLE one alike -- _read_last_dq_run degrades a
malformed artifact to a NULL verdict plus a named read_error rather than to a verdict literal no
consumer gauge maps, and print_data_quality_health can no longer suppress a live FAIL verdict or a
zero count from a directory that exists.

Every construct this plan adds is reached as a module ATTRIBUTE
(context_docs._DQ_ALARMING_VERDICTS, context_docs._read_last_dq_run), never as a symbol-level
from-import, so this module still COLLECTS on an origin/main worktree and its failures are red
rather than an rc-2 collection error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.preflight import _common as preflight_common
from scripts.preflight import context_docs

boto3 = pytest.importorskip("boto3")


def _yaml_for(*tables: str) -> str:
    """A minimal, genuinely compilable data-quality check file: one row_count check per table."""
    body = "".join(f"  {table}:\n    row_count:\n      min: 1\n" for table in tables)
    return f"database: agent_platform\ntables:\n{body}"


_ALPHA_BETA = _yaml_for("t_alpha", "t_beta")
_BETA_GAMMA = _yaml_for("t_beta", "t_gamma")
# The run-verdict vocabulary scripts/data_quality_execute.py's run_checks can put in
# dq-latest.json: the aggregate expression yields HARD_GATE, FAIL, DEGRADED or PASS, its two early
# returns yield SKIP and its empty-results branch yields ERROR. UNAVAILABLE and WARN are per-CHECK
# verdicts and unreachable at that key.
_RUN_VERDICTS = ("PASS", "DEGRADED", "SKIP", "FAIL", "HARD_GATE", "ERROR")

# Named once so every live-tree-coupled case in this module points a red run at the data first.
_LIVE_DQ_DATA = (
    "DATA condition, not a code regression: config/agent/data_quality/ must hold at least one "
    "readable check file -- inspect that directory before reading scripts/preflight/context_docs.py"
)

_FAILING_RUN = {
    "verdict": "FAIL",
    "passed": 0,
    "failed": 0,
    "warned": 0,
    "errored": 2,
    "unavailable": 0,
    "timestamp": "2026-01-01T00:00:00+00:00",
}


def _root(tmp_path: Path, *, checks: dict[str, str] | None = None, dq_payload: str | None = None) -> Path:
    """Build a synthetic repo root: optional config/agent/data_quality check files, optional
    logs/debug/dq-latest.json payload."""
    if checks is not None:
        dq_dir = tmp_path / "config" / "agent" / "data_quality"
        dq_dir.mkdir(parents=True)
        for name, body in checks.items():
            (dq_dir / name).write_text(body, encoding="utf-8")
    if dq_payload is not None:
        debug = tmp_path / "logs" / "debug"
        debug.mkdir(parents=True)
        (debug / "dq-latest.json").write_text(dq_payload, encoding="utf-8")
    return tmp_path


class TestDataQualityCoverage:
    def test_live_repo_reports_non_zero_coverage(self) -> None:
        """Live-tree-coupled: reads the REAL config/agent/data_quality corpus. Its assertion
        messages name the DATA condition first, so a red run is triaged as data versus code without
        opening the source."""
        live = context_docs.check_data_quality_coverage()
        assert live.get("coverage_error") is None, (
            f"{_LIVE_DQ_DATA} -- the live check corpus reported a coverage_error: {live.get('coverage_error')}"
        )
        assert live["checks_defined"] and live["checks_defined"] > 0, f"{_LIVE_DQ_DATA} -- checks_defined is {live}"
        assert live["tables_covered"] and live["tables_covered"] > 0, f"{_LIVE_DQ_DATA} -- tables_covered is {live}"

    def test_configured_directory_is_the_agent_subtree(self, tmp_path: Path, monkeypatch) -> None:
        """The retired config/data_quality path is NOT read -- a check file parked there must not
        contribute, and the agent subtree must. The two corpora are deliberately DIFFERENT sizes,
        so reading the wrong directory yields a different count rather than the same one."""
        root = _root(tmp_path, checks={"alpha.yaml": _ALPHA_BETA})
        legacy = root / "config" / "data_quality"
        legacy.mkdir(parents=True)
        (legacy / "legacy.yaml").write_text(_yaml_for("t_x", "t_y", "t_z"), encoding="utf-8")
        monkeypatch.setattr(preflight_common, "ROOT", root)
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] == 2, result
        assert result["tables_covered"] == 2, result

    def test_tables_covered_counts_distinct_tables_across_files(self, tmp_path: Path, monkeypatch) -> None:
        """t_beta appears in BOTH files: a per-file sum would report 4 tables for 3 real ones."""
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, checks={"a.yaml": _ALPHA_BETA, "b.yaml": _BETA_GAMMA}))
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] == 4, result
        assert result["tables_covered"] == 3, result

    def test_missing_directory_yields_none_counts_and_a_path_naming_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "ROOT", tmp_path)
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] is None, result
        assert result["tables_covered"] is None, result
        assert "dq config dir missing" in result["coverage_error"], result
        assert str(tmp_path) in result["coverage_error"], result

    def test_unparseable_check_file_is_partial_and_single_line(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            preflight_common,
            "ROOT",
            _root(tmp_path, checks={"good.yaml": _ALPHA_BETA, "broken.yaml": "tables: [unclosed\n  : :\n"}),
        )
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] == 2, result
        assert len(result["load_errors"]) == 1, result
        assert result["load_errors"][0].startswith("broken.yaml: ")
        assert "\n" not in result["load_errors"][0]

    def test_unreadable_directory_yields_unknown_and_names_the_reason(self, tmp_path: Path, monkeypatch) -> None:
        """The is_dir guard alone does not cover a directory that EXISTS but cannot be read:
        CPython's Path.glob swallows the OSError its selector raises, so the old glob returned a
        silent hard zero -- the same lie in a smaller domain. The scandir probe is guarded BY NAME
        here too, so only the dq directory is denied and importlib's own scandir calls are not. The
        patch targets the os MODULE rather than context_docs.os, so this case fails on its
        assertion against a tree that has no scandir probe at all, never on an AttributeError."""
        root = _root(tmp_path, checks={"a.yaml": _ALPHA_BETA})
        dq_dir = root / "config" / "agent" / "data_quality"
        real_scandir = os.scandir

        def _deny(path, *args, **kwargs):
            if str(path) == str(dq_dir):
                raise PermissionError(13, "Permission denied")
            return real_scandir(path, *args, **kwargs)

        monkeypatch.setattr(preflight_common, "ROOT", root)
        monkeypatch.setattr(os, "scandir", _deny)
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] is None, result
        assert result["tables_covered"] is None, result
        assert "dq config dir unreadable" in result["coverage_error"], result
        assert str(dq_dir) in result["coverage_error"], result
        assert "Permission denied" in result["coverage_error"], result

    def test_config_data_quality_path_that_is_a_file_yields_unknown(self, tmp_path: Path, monkeypatch) -> None:
        """Distinct cell from the directory-shaped dq-latest.json: here the COVERAGE side's
        is_dir guard is what routes to None plus a coverage_error."""
        (tmp_path / "config" / "agent").mkdir(parents=True)
        (tmp_path / "config" / "agent" / "data_quality").write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(preflight_common, "ROOT", tmp_path)
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] is None, result
        assert "dq config dir missing" in result["coverage_error"], result


class TestDataQualityHealthRenderer:
    def _drive(self, monkeypatch, root: Path, capsys: pytest.CaptureFixture) -> tuple[str, str]:
        monkeypatch.setattr(preflight_common, "ROOT", root)
        context_docs.print_data_quality_health()
        captured = capsys.readouterr()
        return captured.out, captured.err

    def test_failing_verdict_prints_and_warns(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        root = _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}, dq_payload=json.dumps(_FAILING_RUN))
        out, err = self._drive(monkeypatch, root, capsys)
        assert "Last run: FAIL" in out, out
        assert "2 checks across 2 tables" in out, out
        assert "verdict=FAIL" in err, err

    def test_failing_verdict_survives_unavailable_coverage(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The exact production configuration that swallowed a live FAIL: coverage unavailable
        AND a failing run on disk."""
        root = _root(tmp_path, dq_payload=json.dumps(_FAILING_RUN))
        out, err = self._drive(monkeypatch, root, capsys)
        assert "Last run: FAIL" in out, out
        assert "coverage UNKNOWN" in out, out
        assert "verdict=FAIL" in err, err
        assert "coverage is UNKNOWN, not zero" in err, err

    def test_degraded_verdict_earns_its_warn(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        payload = dict(_FAILING_RUN, verdict="DEGRADED", unavailable=3)
        out, err = self._drive(monkeypatch, _root(tmp_path, dq_payload=json.dumps(payload)), capsys)
        assert "Last run: DEGRADED" in out, out
        assert "/3U" in out, out
        assert "verdict=DEGRADED" in err, err

    def test_hard_gate_verdict_earns_its_warn(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        """HARD_GATE is the MOST SEVERE run verdict run_checks aggregates -- a tombstone
        resurrection, which data_quality_runner's main exits non-zero for -- so it cannot reach
        session open quieter than DEGRADED, which exits zero. The orient skill's data-quality row
        already scores HARD_GATE as GAP, so a silent producer and an alarmed consumer disagree."""
        payload = dict(_FAILING_RUN, verdict="HARD_GATE", failed=1)
        out, err = self._drive(monkeypatch, _root(tmp_path, dq_payload=json.dumps(payload)), capsys)
        assert "Last run: HARD_GATE" in out, out
        assert "verdict=HARD_GATE" in err, err

    def test_exactly_the_alarming_run_verdicts_warn(self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture) -> None:
        """All SIX run verdicts run_checks can aggregate, driven end to end through the renderer:
        PASS, DEGRADED, SKIP, FAIL, HARD_GATE and ERROR. Every one prints its Last run line, and
        exactly the four that data_quality_runner's main exits non-zero for -- or that it exits
        zero for while naming a real degradation -- earn a stderr WARN. Pins BOTH halves, so an
        alarm set that warns on everything fails here just as one that warns on too little does."""
        warned: set[str] = set()
        for verdict in _RUN_VERDICTS:
            payload = dict(_FAILING_RUN, verdict=verdict)
            root = _root(tmp_path / verdict.lower(), dq_payload=json.dumps(payload))
            out, err = self._drive(monkeypatch, root, capsys)
            assert f"Last run: {verdict}" in out, (verdict, out)
            if f"verdict={verdict}" in err:
                warned.add(verdict)
        assert warned == {"FAIL", "DEGRADED", "ERROR", "HARD_GATE"}, warned

    def test_never_run_prints_the_never_line_without_a_warn(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        out, err = self._drive(monkeypatch, _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}), capsys)
        assert "Last run: never" in out, out
        assert "[WARN]" not in err, err

    def test_healthy_run_prints_the_section_and_stays_silent(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The SILENCE half: a healthy verdict with real coverage earns no stderr line at all."""
        payload = dict(_FAILING_RUN, verdict="PASS", errored=0)
        root = _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}, dq_payload=json.dumps(payload))
        out, err = self._drive(monkeypatch, root, capsys)
        assert "Last run: PASS" in out, out
        assert "2 checks across 2 tables" in out, out
        assert err == "", err

    def test_zero_checks_from_a_present_directory_earns_a_warn(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """An EMPTY directory that exists reports a truthful zero, but a bare zero reads as clean:
        the count is printed AND named on stderr, so no zero is silent."""
        out, err = self._drive(monkeypatch, _root(tmp_path, checks={}), capsys)
        assert "0 checks across 0 tables" in out, out
        assert "coverage is ZERO from a directory that EXISTS" in err, err

    def test_unparseable_payload_names_a_read_error_and_warns(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A malformed artifact is a NAMED degraded state without inventing a verdict literal: the
        verdict is null (which the orient gauge already scores as absent) and the read_error names
        the path and the reason on stdout AND on stderr.

        RE-SHAPE of the exact-equality pin below, recorded rather than silently swapped: the set
        gains HARD_GATE and drops UNAVAILABLE. run_checks in scripts/data_quality_execute.py fixes
        the RUN-verdict vocabulary at PASS, DEGRADED, SKIP, FAIL, HARD_GATE and ERROR, and
        _save_latest_result writes that run verdict to dq-latest.json's verdict key -- so
        UNAVAILABLE, which exists only at per-CHECK grain, was unreachable there while HARD_GATE,
        the most severe verdict of the six, was alarming nobody. The assertion is re-shaped to the
        corrected set, never loosened away from exact equality."""
        root = _root(tmp_path, dq_payload="{not json at all")
        out, err = self._drive(monkeypatch, root, capsys)
        assert "Last run: verdict UNKNOWN" in out, out
        assert "could not be read" in out, out
        assert "[WARN] data-quality last run is UNKNOWN, not clean" in err, err
        assert str(root / "logs" / "debug" / "dq-latest.json") in err, err
        assert context_docs._DQ_ALARMING_VERDICTS == frozenset({"FAIL", "DEGRADED", "ERROR", "HARD_GATE"})

    def test_directory_shaped_artifact_reaches_the_read_error_through_isadirectoryerror(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """IsADirectoryError is an OSError and NOT a ValueError -- this is the cell that proves
        _read_last_dq_run's catch was not narrowed to ValueError/JSONDecodeError."""
        (tmp_path / "logs" / "debug" / "dq-latest.json").mkdir(parents=True)
        out, err = self._drive(monkeypatch, tmp_path, capsys)
        assert "Last run: verdict UNKNOWN" in out, out
        assert "[WARN] data-quality last run is UNKNOWN, not clean" in err, err

    def test_load_error_is_surfaced_as_a_partial_coverage_warn(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        root = _root(tmp_path, checks={"good.yaml": _ALPHA_BETA, "broken.yaml": "tables: [unclosed\n  : :\n"})
        out, err = self._drive(monkeypatch, root, capsys)
        assert "2 checks across 2 tables" in out, out
        assert "coverage is PARTIAL" in err, err
        assert "broken.yaml" in err, err


class TestDataQualityTotality:
    """Shape matrix: every cell asserts a RETURN VALUE or a rendered line, never an exception.
    print_data_quality_health is the FIRST call in main() and main() retrieves every future via
    .result(), so a raise for any of these shapes bricks session open."""

    def test_unimportable_loader_yields_unknown(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}))
        monkeypatch.setitem(sys.modules, "scripts.data_quality_runner", None)
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] is None, result
        assert "loader unavailable" in result["coverage_error"], result

    def test_non_string_verdict_does_not_raise_on_the_membership_test(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A well-formed JSON mapping whose verdict is a LIST or a MAPPING: membership in the
        _DQ_ALARMING_VERDICTS frozenset raises TypeError unhashable type on an uncoerced value,
        and print_data_quality_health is the FIRST call in main()."""
        for verdict in (["FAIL", "DEGRADED"], {"nested": "FAIL"}):
            payload = json.dumps(dict(_FAILING_RUN, verdict=verdict))
            monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path / str(id(verdict)), dq_payload=payload))
            context_docs.print_data_quality_health()
            assert "Last run:" in capsys.readouterr().out

    def test_non_mapping_payload_is_a_null_verdict_with_a_read_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, dq_payload='["a", "list"]'))
        result = context_docs.check_data_quality_coverage()
        assert result["last_run"]["verdict"] is None, result
        assert "does not carry a JSON object" in result["last_run"]["read_error"], result

    def test_empty_payload_file_is_a_null_verdict_with_a_read_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, dq_payload=""))
        result = context_docs.check_data_quality_coverage()
        assert result["last_run"]["verdict"] is None, result
        assert "could not be read" in result["last_run"]["read_error"], result

    def test_unreadable_dq_directory_returns_a_value(self, tmp_path: Path, monkeypatch) -> None:
        """os.scandir raising for the configured directory routes to the UNKNOWN sentinel rather
        than out of check_data_quality_coverage, which runs at the first call in main()."""
        root = _root(tmp_path, checks={"a.yaml": _ALPHA_BETA})
        dq_dir = root / "config" / "agent" / "data_quality"
        real_scandir = os.scandir

        def _deny(path, *args, **kwargs):
            if str(path) == str(dq_dir):
                raise OSError(5, "Input/output error")
            return real_scandir(path, *args, **kwargs)

        monkeypatch.setattr(preflight_common, "ROOT", root)
        monkeypatch.setattr(os, "scandir", _deny)
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] is None, result
        assert "dq config dir unreadable" in result["coverage_error"], result

    def test_payload_missing_every_field_does_not_raise(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """RE-SHAPED (Decision 181): this case asserted the literal 'Last run: unknown' -- a value
        that is neither one of the runner's six run verdicts nor null, so the orient gauge had no
        state for it. A readable payload with no verdict key is now the named degraded state: a
        null verdict rendered as UNKNOWN plus a read_error naming the missing key and a stderr WARN."""
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, dq_payload="{}"))
        context_docs.print_data_quality_health()
        captured = capsys.readouterr()
        assert "Last run: verdict UNKNOWN" in captured.out, captured.out
        assert "carries no verdict key" in captured.err, captured.err
        result = context_docs.check_data_quality_coverage()
        assert result["last_run"]["verdict"] is None, result
        assert "carries no verdict key" in result["last_run"]["read_error"], result

    def test_present_but_null_verdict_is_the_degraded_state(
        self, tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A JSON null (or empty-string) verdict is the same condition as a missing key -- no run
        verdict -- so it must take the same route, never coerce to the string 'None' that no gauge maps."""
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, dq_payload='{"verdict": null, "passed": 1}'))
        context_docs.print_data_quality_health()
        captured = capsys.readouterr()
        assert "Last run: verdict UNKNOWN" in captured.out, captured.out
        assert "carries no verdict key" in captured.err, captured.err
        result = context_docs.check_data_quality_coverage()
        assert result["last_run"]["verdict"] is None, result
        assert result["last_run"]["passed"] == 1, result

    def test_checks_without_a_table_are_counted_but_cover_no_table(self, tmp_path: Path, monkeypatch) -> None:
        """The check COUNT is gated on the checks list, not on the table set: a loader whose checks
        carry table=None still counts them and covers zero tables, never inflating tables_covered."""
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}))
        with patch("scripts.data_quality_runner.load_checks", return_value=([SimpleNamespace(table=None)] * 2, None)):
            result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] == 2, result
        assert result["tables_covered"] == 0, result

    def test_loader_returning_a_non_sized_iterable_is_a_partial_load(self, tmp_path: Path, monkeypatch) -> None:
        """len(checks) is CONSUMPTION of the loader's return and belongs inside the per-file guard:
        a truthy iterable with no __len__ is one load_errors line, never a raise."""

        class _TruthyIter:
            def __iter__(self):
                return iter([SimpleNamespace(table="alpha")])

            def __bool__(self) -> bool:
                return True

        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}))
        with patch("scripts.data_quality_runner.load_checks", return_value=(_TruthyIter(), None)):
            result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] == 0, result
        assert len(result["load_errors"]) == 1, result
        assert "no len()" in result["load_errors"][0], result

    def test_stat_raising_root_returns_a_value(self, monkeypatch) -> None:
        """A ROOT whose components cannot even be STAT-ed: Path.exists and Path.is_dir re-raise any
        OSError outside (ENOENT, ENOTDIR, EBADF, ELOOP), and ENAMETOOLONG and EACCES are both
        outside it -- so a permission-denied config/agent under a non-root runner reaches the same
        branch. Both probes must sit inside a guard, or the FIRST call in main() raises."""
        monkeypatch.setattr(preflight_common, "ROOT", Path("/" + "n" * 300))
        result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] is None, result
        assert result["tables_covered"] is None, result
        assert "dq config dir unreadable" in result["coverage_error"], result
        assert result["last_run"]["verdict"] is None, result
        assert "could not be read" in result["last_run"]["read_error"], result

    def test_loaded_checks_without_a_table_attribute_are_a_partial_load(self, tmp_path: Path, monkeypatch) -> None:
        """The CONSUMPTION of load_checks' return, not the call: a loader that yields objects with
        no .table raises AttributeError where the generator is drained, so that expression belongs
        inside the same per-file guard as the call. One bad file is PARTIAL, never a raise."""
        monkeypatch.setattr(preflight_common, "ROOT", _root(tmp_path, checks={"a.yaml": _ALPHA_BETA}))
        with patch("scripts.data_quality_runner.load_checks", return_value=([object()], None)):
            result = context_docs.check_data_quality_coverage()
        assert result["checks_defined"] == 0, result
        assert result["tables_covered"] == 0, result
        assert len(result["load_errors"]) == 1, result
        assert result["load_errors"][0].startswith("a.yaml: "), result

    def test_bare_root_returns_a_value(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(preflight_common, "ROOT", tmp_path)
        result = context_docs.check_data_quality_coverage()
        assert result["last_run"] is None, result
        assert result["checks_defined"] is None, result
