"""Tests for run_lint_checks() -- VTS-18 whole-tree default lint targets (audit validate-test-suite-4df4d48)."""

from unittest.mock import MagicMock, patch

from scripts.checks._scaffolding import run_lint_checks


class TestRunLintChecksWholeTreeTargets:
    """VTS-18: run_lint_checks(failed, files=None) (the whole-tree/full-tier default) must
    include scripts/ alongside src/ and tests/ in its ruff check + ruff format --check targets."""

    def test_whole_tree_default_includes_scripts(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=None)

        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "scripts/" in cmd

    def test_whole_tree_default_still_includes_src_and_tests(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=None)

        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "src/" in cmd
            assert "tests/" in cmd

    def test_ruff_check_and_format_check_both_invoked(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=None)

        commands = [call.args[0] for call in mock_run.call_args_list]
        assert any("check" in cmd for cmd in commands)
        assert any("format" in cmd for cmd in commands)

    def test_no_failure_appended_when_ruff_passes(self) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result):
            failed: list[str] = []
            run_lint_checks(failed, files=None)
        assert failed == []

    def test_explicit_files_argument_is_ignored_for_target_selection(self) -> None:
        """Retargeted (rec-3861/rec-3863): `files=[...]` (the --pre diff-scoped argument) no
        longer narrows the lint targets -- it is accepted (removing the parameter would TypeError
        at the --pre call site) but IGNORED, so the whole tree is always linted regardless of
        what `files` names. Superseded test: the parameter used to filter targets down to a
        single explicit .py file; it no longer does."""
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=["scripts/checks/_scaffolding.py"])

        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "src/" in cmd
            assert "tests/" in cmd
            assert "scripts/" in cmd
            assert "scripts/checks/_scaffolding.py" not in cmd

    def test_empty_files_list_still_lints_whole_tree(self) -> None:
        """Retargeted (rec-3861/rec-3863): an empty `files=[]` used to be a no-op (the exact
        escape that let commit 1c50e26b's five-file, zero-.py ruff-version bump reach main
        unlinted by --pre). It now still lints the whole tree -- there is no reachable
        non-execution path left for run_lint_checks once target selection is unconditional."""
        mock_result = MagicMock(returncode=0)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=[])

        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            assert "src/" in cmd
            assert "tests/" in cmd
            assert "scripts/" in cmd
        assert failed == []

    def test_pin_only_changed_set_still_lints_whole_tree(self) -> None:
        """Unit altitude (VP step 2): a changed set containing no .py file at all (commit
        1c50e26b's actual five-file requirements-pin diff) still emits the whole-tree ruff argv --
        the deleted `[f for f in files if f.endswith(".py")]` filter is unreachable now."""
        mock_result = MagicMock(returncode=0)
        pin_only_changed = [
            "requirements.in",
            "requirements.txt",
            "requirements-dev.in",
            "requirements-dev.txt",
            "requirements-fast.txt",
        ]
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            run_lint_checks(failed, files=pin_only_changed)

        assert mock_run.call_count == 2
        ruff_check = [c for c in mock_run.call_args_list if "check" in c.args[0] and "format" not in c.args[0]]
        assert ruff_check, "No ruff check command issued"
        cmd = ruff_check[0].args[0]
        assert "src/" in cmd
        assert "tests/" in cmd
        assert "scripts/" in cmd
        assert failed == []
