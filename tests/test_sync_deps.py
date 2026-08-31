"""V2 tests for bin/sync-deps.sh: fingerprint drift detection, fingerprint write,
terraform version-compare (including the config-error and SIGPIPE regressions),
and a real end-to-end install + idempotency check.

bin/sync-deps.sh resolves its own REPO_ROOT relative to its own script location
(mirrors bin/setup-cloud-env.sh and the SessionStart hooks), so each test copies
the real script into a throwaway repo layout under tmp_path (bin/sync-deps.sh +
requirements.txt + requirements-dev.txt [+ config/terraform-version]) rather than
mocking the script's internals.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_SCRIPT_SRC = Path(__file__).resolve().parent.parent / "bin" / "sync-deps.sh"


def _make_fake_repo(
    tmp_path: Path,
    requirements: str = "six==1.16.0\n",
    requirements_dev: str = "typing-extensions==4.12.2\n",
    terraform_version: str | None = "1.10.5",
) -> Path:
    """Build a throwaway repo layout with a real copy of bin/sync-deps.sh.

    Seeds config/terraform-version by default (rec-2687); pass
    terraform_version=None to omit the file (and its directory) entirely for
    the missing-file regression tests.
    """
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    shutil.copy(_SCRIPT_SRC, repo / "bin" / "sync-deps.sh")
    (repo / "bin" / "sync-deps.sh").chmod(0o755)
    (repo / "requirements.txt").write_text(requirements, encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(requirements_dev, encoding="utf-8")
    if terraform_version is not None:
        (repo / "config").mkdir()
        (repo / "config" / "terraform-version").write_text(f"{terraform_version}\n", encoding="utf-8")
    return repo


def _expected_fingerprint(repo: Path) -> str:
    """Replicate the script's own fingerprint formula: sha256sum of both files, then sha256sum of that."""
    inner = subprocess.run(
        ["sha256sum", "requirements.txt", "requirements-dev.txt"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return hashlib.sha256(inner.encode("utf-8")).hexdigest()


def _run_sync(repo: Path, args: list[str] | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run bin/sync-deps.sh under a pinned env.

    Never passes env=None to subprocess.run -- the ambient container may have
    INSTALL_TERRAFORM=1 exported, which would let container state leak into a
    test that never asked for terraform-check behaviour. Callers that need
    INSTALL_TERRAFORM=1 or a stub PATH entry pass their own explicit env dict.
    """
    if env is None:
        home = repo.parent / "home"
        home.mkdir(exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    cmd = ["bash", str(repo / "bin" / "sync-deps.sh"), *(args or [])]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env, timeout=120)


def _write_stub_uv(stub_dir: Path, log_file: Path) -> Path:
    """A stub uv that records its invocation args (space-joined) and exits 0, never touching the network."""
    stub = stub_dir / "uv"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{log_file}"\nexit 0\n', encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _write_stub_python(venv_bin: Path) -> Path:
    """A stub .venv/bin/python: the script only tests -x on it and hands its path to uv, never executes it."""
    venv_bin.mkdir(parents=True, exist_ok=True)
    stub = venv_bin / "python"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


class TestCheckModeDriftDetection:
    """--check reports drift status without installing anything."""

    def test_check_reports_drift_when_fingerprint_missing(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        result = _run_sync(repo, ["--check"])
        assert result.returncode == 1
        assert "drift" in result.stdout
        assert not (repo / ".venv").exists()

    def test_check_reports_drift_when_fingerprint_stale(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        (repo / ".venv").mkdir()
        (repo / ".venv" / ".requirements-fingerprint").write_text("0" * 64, encoding="utf-8")
        result = _run_sync(repo, ["--check"])
        assert result.returncode == 1
        assert "drift" in result.stdout
        # --check must never install -- the fingerprint file is left untouched.
        assert (repo / ".venv" / ".requirements-fingerprint").read_text(encoding="utf-8") == "0" * 64

    def test_check_reports_in_sync_when_fingerprint_matches(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        (repo / ".venv").mkdir()
        (repo / ".venv" / ".requirements-fingerprint").write_text(_expected_fingerprint(repo), encoding="utf-8")
        result = _run_sync(repo, ["--check"])
        assert result.returncode == 0
        assert "in sync" in result.stdout


class TestTerraformDriftDetection:
    """INSTALL_TERRAFORM=1 self-heal decision, proven via a stub terraform on PATH (no real install)."""

    def _stub_terraform(self, tmp_path: Path, version: str) -> Path:
        stub_dir = tmp_path / "stubbin"
        stub_dir.mkdir(exist_ok=True)
        stub = stub_dir / "terraform"
        stub.write_text(f'#!/usr/bin/env bash\necho "Terraform v{version}"\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return stub_dir

    def _in_sync_repo(self, tmp_path: Path, terraform_version: str = "1.10.5") -> Path:
        repo = _make_fake_repo(tmp_path, terraform_version=terraform_version)
        (repo / ".venv").mkdir()
        (repo / ".venv" / ".requirements-fingerprint").write_text(_expected_fingerprint(repo), encoding="utf-8")
        return repo

    def test_terraform_stub_version_mismatch_is_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        stub_dir = self._stub_terraform(tmp_path, version="1.9.0")
        env = {**dict(**{"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"})}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 1
        assert "terraform=1" in result.stdout

    def test_terraform_stub_version_match_is_no_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        stub_dir = self._stub_terraform(tmp_path, version="1.10.5")
        env = {**dict(**{"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"})}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 0
        assert "in sync" in result.stdout

    def test_terraform_absent_from_path_is_drift(self, tmp_path: Path) -> None:
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 1
        assert "terraform=1" in result.stdout

    def test_install_terraform_unset_is_never_drift(self, tmp_path: Path) -> None:
        # No terraform on PATH at all, but INSTALL_TERRAFORM is unset -- must be a no-op.
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 0

    def test_missing_terraform_version_file_fails_loudly(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path, terraform_version=None)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 2
        assert "config/terraform-version" in result.stderr
        assert "ERROR" in result.stderr

    def test_whitespace_only_terraform_version_file_fails_loudly(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path, terraform_version=None)
        (repo / "config").mkdir()
        (repo / "config" / "terraform-version").write_text("   \n\t \n", encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 2
        assert "config/terraform-version" in result.stderr
        assert "ERROR" in result.stderr

    def test_missing_terraform_version_file_install_mode_is_non_fatal(self, tmp_path: Path) -> None:
        # Arm (a): python drift present -- the install must still run; the config
        # error only withholds the fingerprint write, it never suppresses the sync.
        repo_a = _make_fake_repo(tmp_path / "a", terraform_version=None)
        stub_dir = tmp_path / "stub"
        stub_dir.mkdir()
        _write_stub_uv(stub_dir, tmp_path / "uv.log")
        _write_stub_python(repo_a / ".venv" / "bin")
        env_a = {"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result_a = _run_sync(repo_a, env=env_a)
        assert result_a.returncode == 0
        assert "ERROR" in result_a.stderr
        assert "installing requirements.txt via uv" in result_a.stdout
        assert "fingerprint NOT updated" in result_a.stdout
        assert "installing terraform" not in result_a.stdout
        assert not (repo_a / ".venv" / ".requirements-fingerprint").exists()

        # Arm (b): no python drift -- load-bearing, because arm (a)'s py_drift=1
        # makes the "in sync, nothing to do" early exit unreachable regardless of
        # whether it is actually guarded on the config-error flag. Only this arm
        # exercises that guard.
        repo_b = _make_fake_repo(tmp_path / "b", terraform_version=None)
        (repo_b / ".venv").mkdir()
        (repo_b / ".venv" / ".requirements-fingerprint").write_text(_expected_fingerprint(repo_b), encoding="utf-8")
        env_b = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result_b = _run_sync(repo_b, env=env_b)
        assert result_b.returncode == 0
        assert "ERROR" in result_b.stderr
        assert "in sync, nothing to do" not in result_b.stdout
        assert "installing terraform" not in result_b.stdout

    def test_terraform_version_check_survives_early_pipe_close(self, tmp_path: Path) -> None:
        # A stub terraform emitting the version line plus >64KB of trailing
        # output: the old "terraform version | head -1 | grep -q ..." shape hits
        # SIGPIPE once head/grep close the pipe early, and pipefail turns that
        # into spurious drift (measured deterministic, 20/20, against the
        # pre-fix script). The pipe-free capture must survive it every time.
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        stub_dir = tmp_path / "stubbin"
        stub_dir.mkdir()
        stub = stub_dir / "terraform"
        stub.write_text(
            "#!/usr/bin/env bash\necho 'Terraform v1.10.5'\nhead -c 70000 /dev/zero | tr '\\0' 'x'\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        env = {"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "in sync" in result.stdout


@pytest.mark.integration
class TestRealInstallAndIdempotency:
    """Real end-to-end python install in a throwaway venv: install, fingerprint write, idempotency."""

    def test_real_sync_installs_writes_fingerprint_and_is_idempotent(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(
            tmp_path,
            requirements="six==1.16.0\n",
            requirements_dev="typing-extensions==4.12.2\n",
        )

        # 1. First sync: no .venv yet -- must create it, install both files, write the fingerprint.
        result = _run_sync(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        fp_file = repo / ".venv" / ".requirements-fingerprint"
        assert fp_file.exists()
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)

        venv_python = repo / ".venv" / "bin" / "python"
        assert venv_python.exists()
        import_check = subprocess.run(
            [str(venv_python), "-c", "import six, typing_extensions"],
            capture_output=True,
            text=True,
        )
        assert import_check.returncode == 0, import_check.stdout + import_check.stderr

        # 2. Second sync (unchanged files): must be a no-op per --check.
        check_result = _run_sync(repo, ["--check"])
        assert check_result.returncode == 0
        assert "in sync" in check_result.stdout

        # 3. Mutate requirements-dev.txt -- must detect drift and reinstall.
        (repo / "requirements-dev.txt").write_text("typing-extensions==4.12.2\npackaging==24.1\n", encoding="utf-8")
        drift_check = _run_sync(repo, ["--check"])
        assert drift_check.returncode == 1

        resync_result = _run_sync(repo)
        assert resync_result.returncode == 0, resync_result.stdout + resync_result.stderr
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)

        import_check_2 = subprocess.run(
            [str(venv_python), "-c", "import six, typing_extensions, packaging"],
            capture_output=True,
            text=True,
        )
        assert import_check_2.returncode == 0, import_check_2.stdout + import_check_2.stderr

        # 4. Third sync (now in sync again): idempotent no-op.
        final_check = _run_sync(repo, ["--check"])
        assert final_check.returncode == 0
        assert "in sync" in final_check.stdout


class TestHermeticInstall:
    """Hermetic replacement for the install path the integration marker removed from the default lane.

    A stub uv on a pinned PATH serves every install -- pytest's --disable-socket
    does not reach a subprocess, so a stub (not a socket block) is what keeps
    this class off the real package index.
    """

    def test_stub_uv_install_fingerprint_and_drift_cycle(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        stub_dir = tmp_path / "stub"
        stub_dir.mkdir()
        uv_log = tmp_path / "uv.log"
        _write_stub_uv(stub_dir, uv_log)
        _write_stub_python(repo / ".venv" / "bin")
        env = {"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}

        # 1. First sync: python drift (no fingerprint yet) -- must invoke uv for
        # both files with the expected argument list, then write the fingerprint.
        result = _run_sync(repo, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        calls = uv_log.read_text(encoding="utf-8").splitlines()
        assert "pip install --python .venv/bin/python -q -r requirements.txt" in calls
        assert "pip install --python .venv/bin/python -q -r requirements-dev.txt" in calls
        fp_file = repo / ".venv" / ".requirements-fingerprint"
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)

        # 2. Second sync (unchanged files): idempotent no-op per --check.
        check_result = _run_sync(repo, ["--check"], env=env)
        assert check_result.returncode == 0
        assert "in sync" in check_result.stdout

        # 3. Mutate requirements-dev.txt -- must detect drift and reinstall via uv.
        (repo / "requirements-dev.txt").write_text("typing-extensions==4.12.2\npackaging==24.1\n", encoding="utf-8")
        drift_check = _run_sync(repo, ["--check"], env=env)
        assert drift_check.returncode == 1

        dev_calls_before = [c for c in calls if "requirements-dev.txt" in c]
        resync_result = _run_sync(repo, env=env)
        assert resync_result.returncode == 0, resync_result.stdout + resync_result.stderr
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)
        dev_calls_after = [c for c in uv_log.read_text(encoding="utf-8").splitlines() if "requirements-dev.txt" in c]
        assert len(dev_calls_after) > len(dev_calls_before)

        # 4. Third sync (now in sync again): idempotent no-op.
        final_check = _run_sync(repo, ["--check"], env=env)
        assert final_check.returncode == 0
        assert "in sync" in final_check.stdout

    def test_venv_creation_branch_with_stub_uv(self, tmp_path: Path) -> None:
        python312 = shutil.which("python3.12")
        if python312 is None:
            pytest.skip("python3.12 not found on PATH -- cannot exercise the venv-creation branch")
        python312_dir = str(Path(python312).parent)

        repo = _make_fake_repo(tmp_path)
        stub_dir = tmp_path / "stub"
        stub_dir.mkdir()
        _write_stub_uv(stub_dir, tmp_path / "uv.log")
        env = {"PATH": f"{stub_dir}:{python312_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}

        result = _run_sync(repo, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "creating .venv with python3.12" in result.stdout
        assert (repo / ".venv" / "bin" / "python").exists()
        fp_file = repo / ".venv" / ".requirements-fingerprint"
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)
