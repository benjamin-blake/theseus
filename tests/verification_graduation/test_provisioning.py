"""Provisioning / environment-probe / teardown-safety tests (PLAN-verification-graduation-gate-fix).

Decomposition of test_differential.py (413/500 SLOC before this plan) rather than a budget raise
(Decision 128) -- see AGENTS.md SLOC governance. Covers the defect this plan removes: a revert-leg
FAIL caused by an unprovisioned scratch worktree (no `.venv`, so `bin/venv-python` cannot resolve
an interpreter) was silently read as content discrimination and admitted. Real git worktrees and
real subprocesses throughout -- never mock the revert leg, which is the defect being fixed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import verification_graduation as vg
from scripts.verification_checks import CheckStatus, CommandExitZeroCheck

from .conftest import _commit_all, _git, _init_repo

# A minimal stand-in for the real bin/venv-python: tracked in git (so it is present in every
# worktree, matching reality -- only `.venv/` itself is gitignored, never the wrapper script),
# and it fails cleanly (a controlled `exit 1`, never a crash) whenever `.venv/bin/python` is
# absent relative to its OWN location -- exactly the real wrapper's REPO_ROOT-via-$0 derivation.
_UNPROVISIONABLE_VENV_PYTHON = (
    "#!/usr/bin/env bash\n"
    'REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"\n'
    'if [ -x "$REPO_ROOT/.venv/bin/python" ]; then exec "$REPO_ROOT/.venv/bin/python" "$@"; fi\n'
    "exit 1\n"
)


def _write_tracked_venv_python(repo: Path) -> None:
    bin_dir = repo / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "venv-python"
    script.write_text(_UNPROVISIONABLE_VENV_PYTHON, encoding="utf-8")
    script.chmod(0o755)


# ---------------------------------------------------------------------------
# TestProvisionedDifferential (VP step 2) -- run against the REAL repo, since a synthetic
# fixture repo has neither .venv nor bin/venv-python of its own.
# ---------------------------------------------------------------------------


class TestProvisionedDifferential:
    def test_tautological_venv_python_check_is_rejected(self) -> None:
        """Before the fix this was silently admitted=True (the live defect VP step 1 reproduces)."""
        row = {
            "check_id": "taut-venv-python-provisioning-test",
            "primitive_slot": "command_exit_zero",
            "check_spec": {"command": ["bin/venv-python", "-c", "print(1)"]},
        }
        outcome = vg.run_differential(row, repo_root=vg.ROOT)
        assert not outcome.admitted
        assert "tautological" in outcome.reason, outcome.reason


# ---------------------------------------------------------------------------
# TestEnvironmentProbe (VP step 3) -- an unrunnable interpreter raises, never admits; the
# probe scans the whole command, not just argv[0]; an unrecognised head is simply skipped.
# ---------------------------------------------------------------------------


class TestEnvironmentProbe:
    def test_unrunnable_interpreter_raises_not_admits(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_tracked_venv_python(repo)
        _commit_all(repo, "base: tracked bin/venv-python, no .venv anywhere")

        row = {
            "check_id": "unrunnable",
            "primitive_slot": "command_exit_zero",
            "check_spec": {"command": ["bin/venv-python", "-c", "print(1)"]},
        }
        runner = vg.make_worktree_revert_runner(row, ref="HEAD", repo_root=repo)
        with pytest.raises(vg.GraduationError, match="bin/venv-python.*not runnable in the revert worktree"):
            runner(vg.materialize_check_in_tree(row, repo))

    def test_bash_wrapped_venv_python_is_probed(self, tmp_path: Path) -> None:
        """A bash-headed row whose BODY calls bin/venv-python is still detected -- the shape a
        head-only (argv[0]-only) probe would miss for 29 of 139 real cohort rows."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_tracked_venv_python(repo)
        _commit_all(repo, "base: tracked bin/venv-python, no .venv anywhere")

        row = {
            "check_id": "bash-wrapped-unrunnable",
            "primitive_slot": "command_exit_zero",
            "check_spec": {"command": ["bash", "-c", "bin/venv-python -c 'print(1)'"]},
        }
        runner = vg.make_worktree_revert_runner(row, ref="HEAD", repo_root=repo)
        with pytest.raises(vg.GraduationError, match="bin/venv-python"):
            runner(vg.materialize_check_in_tree(row, repo))

    def test_unrecognised_head_is_skipped_not_failed(self, tmp_path: Path) -> None:
        """A command whose interpreter falls outside the allowlist is simply not probed -- the
        probe is a positive detector only and must never manufacture a failure for it."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        script = repo / "custom-tool-xyz"
        script.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        script.chmod(0o755)
        _commit_all(repo, "base")

        row = {
            "check_id": "unrecognised-head",
            "primitive_slot": "command_exit_zero",
            "check_spec": {"command": ["./custom-tool-xyz"]},
        }
        runner = vg.make_worktree_revert_runner(row, ref="HEAD", repo_root=repo)
        result = runner(vg.materialize_check_in_tree(row, repo))
        assert result.status == CheckStatus.FAIL

    def test_probed_interpreter_tokens_word_boundary_and_dedup(self) -> None:
        """A naive substring scan finds 'sh' inside 'shard'/'push'/'shell'/'shutil'/'sha256' --
        42 spurious hits across the live corpus. Word-boundary matching must not, and a
        'bin/venv-python' occurrence must not also register a second, separate 'python' hit."""
        command = [
            "bash",
            "-c",
            "cd shard_push && bin/venv-python -m shutil sha256sum && bash -c 'echo done'",
        ]
        tokens = vg._probed_interpreter_tokens(command)
        assert tokens == ["bash", "bin/venv-python"]

    def test_probed_interpreter_tokens_empty_when_no_allowlisted_token(self) -> None:
        assert vg._probed_interpreter_tokens(["./custom-tool-xyz", "--check"]) == []

    def test_probe_interpreter_missing_executable_is_probe_failure(self, tmp_path: Path) -> None:
        ok, detail = vg._probe_interpreter("bin/venv-python", tmp_path)
        assert ok is False
        assert detail

    def test_probe_interpreter_success(self) -> None:
        ok, detail = vg._probe_interpreter("bash", vg.ROOT)
        assert ok is True
        assert detail == ""

    def test_probe_environment_on_fail_skips_non_probeable_slot(self, tmp_path: Path) -> None:
        row = {"check_id": "x", "primitive_slot": "grep_count", "check_spec": {}}
        check = CommandExitZeroCheck(name="x", command=["bin/venv-python"])
        vg._probe_environment_on_fail(row, check, tmp_path)  # must not raise

    def test_probe_environment_on_fail_skips_empty_command(self, tmp_path: Path) -> None:
        row = {"check_id": "x", "primitive_slot": "command_exit_zero", "check_spec": {}}
        check = CommandExitZeroCheck(name="x", command=[])
        vg._probe_environment_on_fail(row, check, tmp_path)  # must not raise

    def test_probe_environment_on_fail_ignored_when_revert_leg_passes(self, tmp_path: Path) -> None:
        """Do NOT probe when the revert leg PASSes -- a passing command already proves the
        environment ran it, and the outcome is rejection, the fail-safe direction."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "target.txt").write_text("sentinel\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        row = {
            "check_id": "passes-both",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "target.txt", "pattern": "sentinel", "operator": "eq", "count": 1},
        }
        outcome = vg.run_differential(row, repo_root=repo)
        assert not outcome.admitted
        assert "tautological" in outcome.reason


# ---------------------------------------------------------------------------
# TestWorktreeProvisioning (VP step 4) -- conditional provisioning, teardown safety.
# ---------------------------------------------------------------------------


class TestWorktreeProvisioning:
    def test_no_venv_in_repo_root_means_no_symlink_and_no_crash(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _commit_all(repo, "base")

        with vg.git_worktree("HEAD", repo_root=repo) as wt:
            assert not (wt / ".venv").exists()

    def test_venv_present_is_symlinked_into_worktree(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _commit_all(repo, "base")
        real_venv = repo / ".venv"
        real_venv.mkdir()
        (real_venv / "canary.txt").write_text("do-not-delete\n", encoding="utf-8")

        with vg.git_worktree("HEAD", repo_root=repo) as wt:
            wt_venv = wt / ".venv"
            assert wt_venv.is_symlink()
            assert (wt_venv / "canary.txt").read_text(encoding="utf-8") == "do-not-delete\n"

    def test_teardown_never_deletes_the_real_venv_through_the_symlink(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _commit_all(repo, "base")
        real_venv = repo / ".venv"
        real_venv.mkdir()
        canary = real_venv / "canary.txt"
        canary.write_text("do-not-delete\n", encoding="utf-8")

        with vg.git_worktree("HEAD", repo_root=repo) as wt:
            assert (wt / ".venv").is_symlink()

        assert real_venv.exists()
        assert canary.read_text(encoding="utf-8") == "do-not-delete\n"

    def test_provision_venv_symlink_returns_none_without_a_venv(self, tmp_path: Path) -> None:
        assert vg._provision_venv_symlink(tmp_path, tmp_path / "no-such-repo") is None
