"""Mirror home (flat rule) for scripts/test_coverage_checker.py.

Uses the shared singleton loader (tests/fixtures/coverage_checker_module.py) so
`patch("test_coverage_checker.<name>")` intercepts the SAME module object every other
tests/test_coverage_checker_*.py file resolves against -- see that fixture's docstring.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures.coverage_checker_module import ROOT, checker

get_changed_source_files = checker.get_changed_source_files
measure_per_file_coverage = checker.measure_per_file_coverage
check_per_file_coverage = checker.check_per_file_coverage


class TestGetChangedSourceFilesPushContextBase:
    """get_changed_source_files() delegates its whole git-diff branch to
    scripts.checks._common.get_status_aware_diff(root=base_root) (Decision 159 pairing
    invariant). Push-context-base selection itself is owned by
    tests/checks/_common/test_push_context_base.py (TestPushContextBase) and the merge-base ->
    HEAD fallback by tests/validate/test_changed_files.py::TestGetStatusAwareDiff::
    test_falls_back_to_head_when_merge_base_fails (Decision 181) -- this class guards only the
    delegation and root-forwarding contract at the checker's own call site."""

    def test_forwards_resolved_root(self, tmp_path: Path) -> None:
        """get_changed_source_files forwards the resolved root (the explicit `root` argument,
        else the patched test_coverage_checker.ROOT) to get_status_aware_diff, and maps the
        helper's (status, path) tuples through its own filters."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("A", "scripts/foo.py")]) as mock_diff,
        ):
            result = get_changed_source_files()

        assert any("foo.py" in str(p) for p in result)
        mock_diff.assert_called_once_with(root=tmp_path)

    def test_diffs_against_merge_base(self, tmp_path: Path) -> None:
        """push_context_base() returning None keeps the merge-base-or-HEAD base selection --
        pinned here via scripts.checks._common.run (NOT get_status_aware_diff itself), the
        ~12-line replacement for the deleted line-53 subprocess assertion."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bar.py").write_text("x = 1\n", encoding="utf-8")

        mock_merge_base = MagicMock(returncode=0, stdout="abc123\n")
        mock_diff = MagicMock(returncode=0, stdout="A\tsrc/bar.py\n")
        mock_ls_files = MagicMock(returncode=0, stdout="")

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "merge-base"]:
                return mock_merge_base
            if cmd[:2] == ["git", "diff"]:
                return mock_diff
            if cmd[:2] == ["git", "ls-files"]:
                return mock_ls_files
            raise AssertionError(f"unexpected git invocation: {cmd}")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("scripts.checks._common.push_context_base", return_value=None),
            patch("scripts.checks._common.run", side_effect=fake_run) as mock_run,
        ):
            result = get_changed_source_files()

        assert any("bar.py" in str(p) for p in result)
        diff_call = next(c for c in mock_run.call_args_list if c.args[0][:2] == ["git", "diff"])
        assert diff_call.args[0][-1] == "abc123"


class TestMeasurePerFileCoverageEntryPoint:
    """measure_per_file_coverage() is the same measurement mechanism check_per_file_coverage()
    consumes -- an observability requirement so a caller (e.g. a VP anti-vacuity check) can
    assert the gate produced a REAL numeric result rather than a silent no-op."""

    def test_measure_per_file_coverage_reports_same_number_as_check(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text('{"files": {"scripts/probe.py": {"summary": {"percent_covered": 87.7}}}}', encoding="utf-8")

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_file),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
        ):
            pcts = measure_per_file_coverage([source])

        assert pcts == {str(source.resolve()): 87.7}

    def test_unmeasured_file_reports_none_not_missing_key(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "orphan.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=None),
        ):
            pcts = measure_per_file_coverage([source])

        assert pcts == {}


class TestCheckPerFileCoverageBaselineAware:
    """check_per_file_coverage()'s baseline-aware pass/fail semantics (Decision 130 style)."""

    def test_unbaselined_file_fails_below_100(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text('{"files": {"scripts/probe.py": {"summary": {"percent_covered": 90.0}}}}', encoding="utf-8")

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_file),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
            patch("scripts.checks.misc.coverage_baseline.load_baseline", return_value={}),
        ):
            errors = check_per_file_coverage([source])

        assert errors and "expected 100%" in errors[0]

    def test_baselined_file_passes_below_100_when_meets_entry(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_data_portal.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_dir = tmp_path / "tests" / "ops_data_portal"
        test_dir.mkdir(parents=True)
        (test_dir / "test_write_paths.py").write_text("# test", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text(
            '{"files": {"scripts/ops_data_portal.py": {"summary": {"percent_covered": 75.5}}}}', encoding="utf-8"
        )

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
            patch("scripts.checks.misc.coverage_baseline.load_baseline", return_value={"scripts/ops_data_portal.py": 75.4}),
        ):
            errors = check_per_file_coverage([source])

        assert errors == []

    def test_baselined_file_fails_when_below_entry(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_data_portal.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_dir = tmp_path / "tests" / "ops_data_portal"
        test_dir.mkdir(parents=True)
        (test_dir / "test_write_paths.py").write_text("# test", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text(
            '{"files": {"scripts/ops_data_portal.py": {"summary": {"percent_covered": 70.0}}}}', encoding="utf-8"
        )

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
            patch("scripts.checks.misc.coverage_baseline.load_baseline", return_value={"scripts/ops_data_portal.py": 75.4}),
        ):
            errors = check_per_file_coverage([source])

        assert len(errors) == 1
        assert "expected >= 75.4%" in errors[0]


def test_root_and_extract_definitions_are_reachable() -> None:
    """Sanity: the shared fixture singleton exposes ROOT / extract_definitions unchanged."""
    assert ROOT.is_dir()
    assert checker.extract_definitions(ROOT / "scripts" / "test_coverage_checker.py") is not None
