"""run_coverage_check() / ensure_fresh_dq_results() / whole-repo SLOC scan coverage tests --
orchestrator residue (rec-2709 Wave 1)."""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import validation_result
from scripts.checks.sloc._shared import iter_gated_py_files
from scripts.checks.sloc.cc_limits import validate_cc_limits
from scripts.checks.sloc.sloc_limits import _update_sloc_budgets, validate_sloc_limits
from tests.fixtures.subprocess_stubs import _mock_completed
from tests.fixtures.validate_module import _validate

# ensure_fresh_dq_results/run_coverage_check/get_changed_files/ROOT are still reachable on the
# "validate" module object -- all four are retained _common/_scaffolding re-exports
# (scripts/validate.py:42-61), unaffected by Decision 169's check-facade deletion.
ensure_fresh_dq_results = _validate.ensure_fresh_dq_results
run_coverage_check = _validate.run_coverage_check
get_changed_files = _validate.get_changed_files
ROOT = _validate.ROOT


class TestEnsureFreshDqResults:
    """Tests for ensure_fresh_dq_results() — the DQ runner auto-invoke."""

    @pytest.fixture(autouse=True)
    def _inject_boto3_stub(self):
        """Ensure boto3 is in sys.modules so patch("boto3.Session") resolves on CI runners where boto3 is not installed."""
        if "boto3" not in sys.modules:
            sys.modules["boto3"] = MagicMock()
            yield
            del sys.modules["boto3"]
        else:
            yield

    @pytest.fixture(autouse=True)
    def _reset_outcomes(self):
        validation_result._OUTCOMES.clear()
        yield
        validation_result._OUTCOMES.clear()

    def test_ensure_fresh_dq_runs_when_cache_missing(self, tmp_path: Path, capsys) -> None:
        """No dq-latest.json on disk: credential check runs, then data_quality_runner is invoked."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache missing" in captured.out
        assert "data_quality_runner" in captured.out
        # One subprocess call: data_quality_runner only (credential check is boto3).
        assert mock_run.call_count == 1
        runner_cmd = mock_run.call_args_list[0].args[0]
        assert "data_quality_runner" in " ".join(runner_cmd)
        assert failed == []
        assert validation_result._OUTCOMES[-1].status == "enforced"
        assert validation_result._OUTCOMES[-1].kind == "scaffold"

    def test_ensure_fresh_dq_runs_when_cache_stale(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json older than the freshness window: re-runs the runner."""

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Backdate mtime by 2 hours -- well past the 1h freshness window.
        old_mtime = time.time() - 2 * 3600
        os.utime(str(dq_file), (old_mtime, old_mtime))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache stale" in captured.out
        assert "data_quality_runner" in captured.out
        assert mock_run.call_count == 1
        assert failed == []

    def test_ensure_fresh_dq_skips_when_cache_fresh(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json modified within the last hour: skip with a clear message."""
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Default mtime is 'now', well inside the 1h freshness window.

        with patch("scripts.checks._common.ROOT", tmp_path), patch("scripts.checks._common.run") as mock_run:
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache fresh" in captured.out
        # Fresh cache must short-circuit before invoking subprocess at all.
        assert mock_run.call_count == 0
        assert failed == []
        assert validation_result._OUTCOMES[-1].status == "skipped"
        assert validation_result._OUTCOMES[-1].skipped_reason == "DQ cache fresh -- runner not needed"

    def test_ensure_fresh_dq_skips_when_sso_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57/170: a real botocore SSO-token-expired exception prints actionable guidance,
        records a declared skip, and does not touch `failed`. requirements-fast.txt (the --pre
        tier's CI environment) excludes boto3 -- and transitively botocore -- so this genuinely
        skips there rather than crashing on ModuleNotFoundError (constraint 5's own caveat)."""
        botocore_exceptions = pytest.importorskip("botocore.exceptions")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.side_effect = (
                botocore_exceptions.UnauthorizedSSOTokenError()
            )
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        # No subprocess calls -- the runner was never invoked after the credential failure.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_credentials_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57/170: a real botocore ProfileNotFound exception must skip with guidance,
        not crash and not redden `failed`. requirements-fast.txt excludes boto3/botocore -- see
        test_ensure_fresh_dq_skips_when_sso_unavailable's docstring."""
        botocore_exceptions = pytest.importorskip("botocore.exceptions")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.side_effect = botocore_exceptions.ProfileNotFound(profile="agent_platform")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_on_expired_token_client_error(self, tmp_path: Path, capsys) -> None:
        """A ClientError with code ExpiredToken (the live STS-call failure shape) is also
        classified as credentials-unavailable and skips. requirements-fast.txt excludes
        boto3/botocore -- see test_ensure_fresh_dq_skips_when_sso_unavailable's docstring."""
        botocore_exceptions = pytest.importorskip("botocore.exceptions")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.side_effect = botocore_exceptions.ClientError(
                {"Error": {"Code": "ExpiredToken", "Message": "token expired"}}, "GetCallerIdentity"
            )
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_fails_closed_on_a_non_matching_exception(self, tmp_path: Path, capsys) -> None:
        """Constraint 5a's newly-installed fail-closed path: an exception the credential
        classifier does NOT match (a genuine bug, not a credential problem) appends to `failed`
        instead of being silently swallowed."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.side_effect = RuntimeError(
                "boom: unrelated bug in profile resolution"
            )
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "unexpected error" in captured.out.lower()
        assert mock_run.call_count == 0
        assert len(failed) == 1
        assert "unexpected credential-check error" in failed[0]
        assert validation_result._OUTCOMES[-1].status == "failed"

    def test_credential_classifier_message_fallback_when_botocore_unimportable(self) -> None:
        """Coverage-debt payoff: the isinstance tier's `except ImportError: pass` -- when
        botocore.exceptions genuinely cannot be imported, the message-pattern tier alone must
        still discriminate correctly (constraint 5's own stated degradation)."""
        from scripts.checks._scaffolding import _is_credentials_unavailable

        with patch.dict(sys.modules, {"botocore": None, "botocore.exceptions": None}):
            assert _is_credentials_unavailable(Exception("Token has expired")) is True
            assert _is_credentials_unavailable(RuntimeError("boom: unrelated bug")) is False


class TestWholeRepoScanCoverage:
    """Tests for the Decision 130 whole-repo scan extension (tests/ is now gated)."""

    def _write_budget(self, tmp_path: Path, entries: dict[str, int]) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["budgets:"]
        for k, v in entries.items():
            lines.append(f"  {k}: {v}")
        (config_dir / "sloc_budgets.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_oversized_unregistered_tests_file_fails(self, tmp_path: Path) -> None:
        """A tests/ file over 500 SLOC with no budget entry fails validate_sloc_limits."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big_thing.py").write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_registered_tests_file_at_budget_passes(self, tmp_path: Path) -> None:
        """A tests/ file registered at/under its budget passes validate_sloc_limits."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big_thing.py").write_text("x = 1\n" * 600, encoding="utf-8")
        self._write_budget(tmp_path, {"tests/test_big_thing.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_excluded_dir_is_not_gated(self, tmp_path: Path) -> None:
        """A file under an excluded dir (e.g. .venv/) is never scanned, regardless of SLOC."""
        venv_dir = tmp_path / ".venv" / "foo"
        venv_dir.mkdir(parents=True)
        (venv_dir / "vendored.py").write_text("x = 1\n" * 999, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)
            gated = list(iter_gated_py_files())

        assert failed == []
        assert gated == []

    def test_all_three_gate_functions_share_one_scan(self, tmp_path: Path) -> None:
        """validate_sloc_limits, _update_sloc_budgets, and validate_cc_limits all consume the
        same iter_gated_py_files() -- one mock patched into both consumer modules is seen
        identically by all three, so the scan roots can never silently drift apart."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        only_file = tests_dir / "test_only.py"
        only_file.write_text("x = 1\n" * 501, encoding="utf-8")
        self._write_budget(tmp_path, {})

        shared_mock = MagicMock(side_effect=lambda: iter([only_file]))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.sloc.sloc_limits.iter_gated_py_files", shared_mock),
            patch("scripts.checks.sloc.cc_limits.iter_gated_py_files", shared_mock),
        ):
            failed: list[str] = []
            validate_sloc_limits(failed)
            _update_sloc_budgets()
            validate_cc_limits(failed)

        assert shared_mock.call_count == 3  # validate_sloc_limits + _update_sloc_budgets + validate_cc_limits
        assert len(failed) == 1  # only the unregistered oversized file, from validate_sloc_limits

    def test_cc_limits_flags_branchy_function_in_tests_dir(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """validate_cc_limits now covers tests/: a >20-branch function there is flagged."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        (tests_dir / "test_branchy.py").write_text(f"def test_heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert len(failed) == 1
        assert "Cyclomatic complexity" in failed[0]
        captured = capsys.readouterr()
        assert "test_heavy_dispatch" in captured.out


class TestUpdateSlocBudgetsArgv:
    """--update-sloc-budgets main()-argv wiring: the import is deferred (Decision 169) so this
    branch does not make scripts/validate.py eagerly import a check-defining module -- patching
    the defining module (not a validate.* alias) proves the deferred import still resolves live."""

    def test_update_sloc_budgets_flag_runs_and_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--update-sloc-budgets"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.setenv("CI", "true")  # skip the branch guard; not under test here
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with (
            patch("scripts.checks.sloc.sloc_limits._update_sloc_budgets") as mock_update,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()
        assert exc_info.value.code == 0
        mock_update.assert_called_once_with()


class TestBuildUnitTestCmd:
    """Coverage-debt payoff: _build_unit_test_cmd() is otherwise only exercised outside
    tests/validate/ (tests/checks/verification/test_validate_hermeticity_flags.py), which the
    test-coverage-checker's tests/validate/ directory mapping for _scaffolding.py does not see."""

    def test_includes_hermeticity_and_junit_flags(self) -> None:
        from scripts.checks._scaffolding import _build_unit_test_cmd

        cmd = _build_unit_test_cmd()
        assert "tests/" in cmd
        assert "-n" in cmd and "auto" in cmd
        assert "--disable-socket" in cmd
        assert any(str(part).startswith("--junitxml=") for part in cmd)


class TestRunPrecommitChecks:
    """Coverage-debt payoff (Decision 170) -- run_precommit_checks() had no dedicated tests."""

    def test_skips_when_pre_commit_not_installed(self, capsys) -> None:
        with patch("scripts.checks._scaffolding.importlib.util.find_spec", return_value=None):
            failed: list[str] = []
            _validate.run_precommit_checks(failed, all_files=True)
        assert "pre-commit not installed" in capsys.readouterr().out
        assert failed == []

    def test_all_files_flag_is_passed_through(self) -> None:
        with patch("scripts.checks._common.run") as mock_run:
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            _validate.run_precommit_checks(failed, all_files=True)
        cmd = mock_run.call_args.args[0]
        assert "--all-files" in cmd
        assert failed == []

    def test_no_changed_files_skips_without_all_files(self) -> None:
        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run") as mock_run,
        ):
            failed: list[str] = []
            _validate.run_precommit_checks(failed, all_files=False)
        mock_run.assert_not_called()
        assert failed == []

    def test_explicit_files_scope_runs_and_appends_on_failure(self) -> None:
        with patch("scripts.checks._common.run") as mock_run:
            mock_run.return_value = _mock_completed(1)
            failed: list[str] = []
            _validate.run_precommit_checks(failed, all_files=False, files=["scripts/foo.py"])
        cmd = mock_run.call_args.args[0]
        assert "--files" in cmd and "scripts/foo.py" in cmd
        assert failed == ["pre-commit hooks"]


class TestRunLintChecksTargetsAllFiltered:
    """Coverage-debt payoff: an explicit files= scope with NO .py entries filters down to an
    empty target list and no-ops (distinct from files=[] itself, already covered elsewhere)."""

    def test_no_python_files_in_explicit_scope_is_a_no_op(self) -> None:
        with patch("scripts.checks._common.invoke_step") as mock_invoke:
            failed: list[str] = []
            _validate.run_lint_checks(failed, files=["README.md", "docs/x.md"])
        mock_invoke.assert_not_called()
        assert failed == []
