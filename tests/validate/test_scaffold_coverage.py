"""run_coverage_check() / run_dependency_checks() / --verifier-coverage argv coverage tests --
PR1 decomposition sibling of test_scaffold_gates.py (Decision 128 decompose-by-default: that
module sat at 456 SLOC against the 500 budget). Holds TestRunCoverageCheck,
TestVerifierCoverageArgv, TestRunDependencyChecks and TestRunCoverageCheckSysPathInjection --
orchestrator residue (rec-2709 Wave 1)."""

import sys
from unittest.mock import patch

import pytest

from tests.fixtures.subprocess_stubs import _mock_completed
from tests.fixtures.validate_module import _validate

# run_coverage_check/ROOT are still reachable on the "validate" module object -- both are retained
# _common/_scaffolding re-exports (scripts/validate.py:42-61), unaffected by Decision 169's
# check-facade deletion.
run_coverage_check = _validate.run_coverage_check
ROOT = _validate.ROOT


class TestRunCoverageCheck:
    """Tests for run_coverage_check() — the --coverage advisory mode."""

    def test_run_coverage_check_no_changed_files_prints_message(self, capsys) -> None:
        """When there are no changed files, the function reports nothing to check."""
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "coverage" in captured.out.lower()
        assert "No changed files" in captured.out

    def test_run_coverage_check_all_covered(self, capsys) -> None:
        """When every changed file is covered, the report says 'All scope files covered'."""
        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/ops_data_portal.py"]),
            patch("scripts.verifiers.check_coverage", return_value=[]),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "All scope files covered" in captured.out

    def test_run_coverage_check_lists_uncovered(self, capsys) -> None:
        """Uncovered files are printed line-by-line under the report header."""
        with (
            patch(
                "scripts.checks._common.get_changed_files",
                return_value=["docs/foo.md", "scripts/ops_data_portal.py"],
            ),
            patch(
                "scripts.verifiers.check_coverage",
                return_value=["docs/foo.md"],
            ),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        assert "- docs/foo.md" in captured.out
        assert "Advisory only" in captured.out

    def test_run_coverage_check_uses_supplied_changed_files(self, capsys) -> None:
        """A supplied changed_files list is used verbatim, skipping the get_changed_files() call
        (VF-02(d): the --pre closure reuses its already-computed diff -- budget-safe)."""
        with (
            patch("scripts.checks._common.get_changed_files") as mock_get_changed,
            patch("scripts.verifiers.check_coverage", return_value=["docs/foo.md"]),
        ):
            run_coverage_check(changed_files=["docs/foo.md", "scripts/ops_data_portal.py"])
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        mock_get_changed.assert_not_called()


class TestVerifierCoverageArgv:
    """VTS-21: --verifier-coverage main()-argv wiring, plus the --coverage deprecated alias."""

    def _run_main(self, monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", flag])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.setenv("CI", "true")  # skip the branch guard; not under test here
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def test_verifier_coverage_flag_runs_report_and_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run_main(monkeypatch, "--verifier-coverage")
        with patch("validate.run_coverage_check") as mock_report, pytest.raises(SystemExit) as exc_info:
            _validate.main()
        assert exc_info.value.code == 0
        mock_report.assert_called_once()

    def test_coverage_deprecated_alias_resolves_to_same_behavior(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run_main(monkeypatch, "--coverage")
        with patch("validate.run_coverage_check") as mock_report, pytest.raises(SystemExit) as exc_info:
            _validate.main()
        assert exc_info.value.code == 0
        mock_report.assert_called_once()

    def test_coverage_alias_prints_deprecation_note(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run_main(monkeypatch, "--coverage")
        with patch("validate.run_coverage_check"), pytest.raises(SystemExit):
            _validate.main()
        assert "DEPRECATED" in capsys.readouterr().out

    def test_verifier_coverage_flag_no_deprecation_note(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._run_main(monkeypatch, "--verifier-coverage")
        with patch("validate.run_coverage_check"), pytest.raises(SystemExit):
            _validate.main()
        assert "DEPRECATED" not in capsys.readouterr().out


class TestRunDependencyChecks:
    """Coverage-debt payoff -- run_dependency_checks() had no dedicated tests."""

    def test_reports_vulnerabilities_and_outdated_packages(self, capsys) -> None:
        with patch("scripts.checks._common.run") as mock_run:
            mock_run.side_effect = [_mock_completed(1), _mock_completed(0)]
            _validate.run_dependency_checks()
        out = capsys.readouterr().out
        assert "vulnerabilities found" in out
        assert mock_run.call_count == 2

    def test_clean_run_no_vulnerabilities(self, capsys) -> None:
        with patch("scripts.checks._common.run") as mock_run:
            mock_run.side_effect = [_mock_completed(0), _mock_completed(0)]
            _validate.run_dependency_checks()
        assert "vulnerabilities found" not in capsys.readouterr().out

    def test_pip_audit_not_installed(self, capsys) -> None:
        with patch("scripts.checks._common.run", side_effect=[FileNotFoundError(), _mock_completed(0)]):
            _validate.run_dependency_checks()
        assert "pip-audit not installed" in capsys.readouterr().out

    def test_pip_list_outdated_not_installed(self, capsys) -> None:
        with patch("scripts.checks._common.run", side_effect=[_mock_completed(0), FileNotFoundError()]):
            _validate.run_dependency_checks()
        assert "Could not check outdated packages" in capsys.readouterr().out


class TestRunCoverageCheckSysPathInjection:
    """Coverage-debt payoff: both the sys.path-injection and already-present branches around the
    scripts.verifiers import, mirroring the same shape in validate_lambda_deploy_gating."""

    def test_injects_and_removes_repo_root_when_absent(self) -> None:
        """A full test-suite run can leave MULTIPLE duplicate root_str entries on sys.path
        (accumulated by unrelated modules) -- a single .remove() call does not guarantee
        absence, so this strips EVERY occurrence and restores the same count afterward."""
        root_str = str(ROOT)
        removed_count = 0
        while root_str in sys.path:
            sys.path.remove(root_str)
            removed_count += 1
        try:
            with (
                patch("scripts.checks._common.get_changed_files", return_value=["docs/foo.md"]),
                patch("scripts.verifiers.check_coverage", return_value=[]),
            ):
                run_coverage_check()
            assert root_str not in sys.path
        finally:
            for _ in range(removed_count):
                sys.path.insert(0, root_str)

    def test_leaves_repo_root_alone_when_already_present(self) -> None:
        root_str = str(ROOT)
        already_present = root_str in sys.path
        if not already_present:
            sys.path.insert(0, root_str)
        try:
            with (
                patch("scripts.checks._common.get_changed_files", return_value=["docs/foo.md"]),
                patch("scripts.verifiers.check_coverage", return_value=[]),
            ):
                run_coverage_check()
            assert root_str in sys.path
        finally:
            if not already_present and root_str in sys.path:
                sys.path.remove(root_str)
