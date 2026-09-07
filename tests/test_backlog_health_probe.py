"""Mirror test for scripts/backlog_health/probe.py (PLAN-backlog-health-detection).

Hermetic: never depends on a real `unshare` being available in the environment running these
tests (VP step 10 -- run against the real GitHub-hosted runner -- is the live proof of that
primitive; this suite tests the verdict logic in isolation via injected runner/isolation_check/
clock callables).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from scripts.backlog_health import probe


class TestIsPytestCommand:
    def test_detects_pytest(self) -> None:
        assert probe.is_pytest_command("bin/venv-python -m pytest tests/test_x.py -q") is True

    def test_non_pytest(self) -> None:
        assert probe.is_pytest_command("grep -q foo bar.txt") is False


class TestIsolationAvailable:
    def test_true_on_zero_exit(self) -> None:
        runner = MagicMock(return_value=MagicMock(returncode=0))
        assert probe.isolation_available(runner=runner) is True

    def test_false_on_nonzero_exit(self) -> None:
        runner = MagicMock(return_value=MagicMock(returncode=1))
        assert probe.isolation_available(runner=runner) is False

    def test_false_on_oserror(self) -> None:
        runner = MagicMock(side_effect=OSError("unshare not found"))
        assert probe.isolation_available(runner=runner) is False

    def test_false_on_timeout(self) -> None:
        runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="unshare", timeout=5))
        assert probe.isolation_available(runner=runner) is False


class TestRunOne:
    def test_pass_on_zero_exit(self, tmp_path: Path) -> None:
        runner = MagicMock(return_value=MagicMock(returncode=0))
        assert probe.run_one("echo hi", repo_root=tmp_path, runner=runner) == probe.PASS

    def test_fail_on_nonzero_exit(self, tmp_path: Path) -> None:
        runner = MagicMock(return_value=MagicMock(returncode=1))
        assert probe.run_one("false", repo_root=tmp_path, runner=runner) == probe.FAIL

    def test_timeout_on_timeout_expired(self, tmp_path: Path) -> None:
        runner = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="sleep", timeout=10))
        assert probe.run_one("sleep 100", repo_root=tmp_path, runner=runner) == probe.TIMEOUT

    def test_fail_never_silently_passes_on_oserror(self, tmp_path: Path) -> None:
        runner = MagicMock(side_effect=OSError("no such sandbox"))
        assert probe.run_one("echo hi", repo_root=tmp_path, runner=runner) == probe.FAIL

    def test_uses_isolated_argv(self, tmp_path: Path) -> None:
        runner = MagicMock(return_value=MagicMock(returncode=0))
        probe.run_one("echo hi", repo_root=tmp_path, runner=runner)
        argv = runner.call_args[0][0]
        assert argv[0] == "unshare"
        assert "-rmn" in argv
        assert "echo hi" in argv[-1]

    def test_pytest_command_gets_30s_timeout(self, tmp_path: Path) -> None:
        captured = {}

        def fake_runner(*args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return MagicMock(returncode=0)

        probe.run_one("bin/venv-python -m pytest tests/test_x.py -q", repo_root=tmp_path, runner=fake_runner)
        assert captured["timeout"] == 30

    def test_non_pytest_command_gets_10s_timeout(self, tmp_path: Path) -> None:
        captured = {}

        def fake_runner(*args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return MagicMock(returncode=0)

        probe.run_one("grep -q foo bar.txt", repo_root=tmp_path, runner=fake_runner)
        assert captured["timeout"] == 10

    def test_scratch_env_redirects_pycache_and_pytest_cache(self, tmp_path: Path) -> None:
        captured = {}

        def fake_runner(*args, **kwargs):
            captured["env"] = kwargs.get("env")
            return MagicMock(returncode=0)

        probe.run_one("echo hi", repo_root=tmp_path, runner=fake_runner)
        env = captured["env"]
        assert env is not None
        assert "PYTHONPYCACHEPREFIX" in env
        assert "PYTEST_ADDOPTS" in env
        assert "cache_dir=" in env["PYTEST_ADDOPTS"]


class TestRunAll:
    def test_isolation_unavailable_marks_every_entry_and_never_runs(self, tmp_path: Path) -> None:
        payload = [{"id": "rec-1", "acceptance": "echo a"}, {"id": "rec-2", "acceptance": "echo b"}]
        runner = MagicMock()
        result = probe.run_all(
            payload,
            repo_root=tmp_path,
            main_sha="deadbeef",
            isolation_check=lambda: False,
            runner=runner,
        )
        assert result["isolation_available"] is False
        assert result["verdicts"] == {"rec-1": probe.ISOLATION_UNAVAILABLE, "rec-2": probe.ISOLATION_UNAVAILABLE}
        runner.assert_not_called()

    def test_stamps_main_sha_unconditionally(self, tmp_path: Path) -> None:
        result = probe.run_all([], repo_root=tmp_path, main_sha="cafef00d", isolation_check=lambda: True)
        assert result["main_sha"] == "cafef00d"

    def test_budget_exhausted_marks_remaining_entries(self, tmp_path: Path) -> None:
        payload = [{"id": "rec-1", "acceptance": "echo a"}, {"id": "rec-2", "acceptance": "echo b"}]
        clock_values = iter([0.0, 0.0, 100.0])  # start, first-entry check (in-budget), second-entry check (over)
        runner = MagicMock(return_value=MagicMock(returncode=0))
        result = probe.run_all(
            payload,
            repo_root=tmp_path,
            main_sha="sha",
            global_budget_s=10,
            isolation_check=lambda: True,
            runner=runner,
            clock=lambda: next(clock_values),
        )
        assert result["verdicts"]["rec-1"] == probe.PASS
        assert result["verdicts"]["rec-2"] == probe.BUDGET_EXHAUSTED

    def test_all_five_verdicts_are_distinct_members_of_vocabulary(self) -> None:
        assert probe.VERDICTS == {probe.PASS, probe.FAIL, probe.TIMEOUT, probe.BUDGET_EXHAUSTED, probe.ISOLATION_UNAVAILABLE}
        assert len(probe.VERDICTS) == 5

    def test_never_records_a_pass_for_a_failing_probe(self, tmp_path: Path) -> None:
        payload = [{"id": "rec-1", "acceptance": "false"}]
        runner = MagicMock(return_value=MagicMock(returncode=1))
        result = probe.run_all(payload, repo_root=tmp_path, main_sha="sha", isolation_check=lambda: True, runner=runner)
        assert result["verdicts"]["rec-1"] != probe.PASS
        assert result["verdicts"]["rec-1"] == probe.FAIL
