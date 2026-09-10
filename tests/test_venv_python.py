"""Wrapper-fallback tests for bin/venv-python (Trap B, Decision 148).

Invokes the real script via subprocess in a temp repo layout (tmp_path/bin/venv-python), so
REPO_ROOT resolves relative to the copy -- no real .venv or PATH state is touched. This is the
wrapper's own test home (a new home; unrelated to tests/test_verification_graduation.py's vg
materializer coverage).
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

_WRAPPER_SRC = Path(__file__).parent.parent / "bin" / "venv-python"
_EXEC_BITS = stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH


def _install_wrapper(repo: Path) -> Path:
    bin_dir = repo / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / "venv-python"
    shutil.copy(_WRAPPER_SRC, dest)
    dest.chmod(dest.stat().st_mode | _EXEC_BITS)
    return dest


def _make_fake_interpreter(path: Path, importable: bool) -> None:
    """A minimal shell shim standing in for a system python on PATH.

    When ``importable`` is True it delegates to the real interpreter running this test (so
    `exec "$PYTHON" "$@"` still runs real Python end-to-end); when False it always exits
    non-zero, simulating an interpreter that cannot import the sentinel dep.
    """
    if importable:
        script = f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n'
    else:
        script = "#!/usr/bin/env bash\nexit 1\n"
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | _EXEC_BITS)


class TestVenvPythonWrapper:
    def test_resolves_venv_when_present(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        os.symlink(sys.executable, venv_bin / "python")

        result = subprocess.run(
            [str(wrapper), "-c", "print('venv-resolved')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert "venv-resolved" in result.stdout

    def test_falls_back_to_dep_bearing_system_interpreter_when_venv_absent(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        fake_path_dir = tmp_path / "fakebin"
        fake_path_dir.mkdir()
        _make_fake_interpreter(fake_path_dir / "python3", importable=True)

        env = dict(os.environ)
        env["PATH"] = f"{fake_path_dir}:{env['PATH']}"

        result = subprocess.run(
            [str(wrapper), "-c", "import pydantic; print('fallback-resolved')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 0
        assert "fallback-resolved" in result.stdout

    def test_fail_loud_when_no_interpreter_can_import_sentinel(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        fake_path_dir = tmp_path / "fakebin"
        fake_path_dir.mkdir()
        _make_fake_interpreter(fake_path_dir / "python3", importable=False)
        _make_fake_interpreter(fake_path_dir / "python", importable=False)

        env = dict(os.environ)
        env["PATH"] = f"{fake_path_dir}:{env['PATH']}"

        result = subprocess.run(
            [str(wrapper), "-c", "print('should not run')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr
        assert "pydantic" in result.stderr
        assert "should not run" not in result.stdout


def _make_off_version_interpreter(path: Path, reported_minor: str) -> None:
    """A shim that imports the sentinel fine but reports a non-target minor version.

    Simulates the observed defect: a fresh cloud dev container whose default python carries
    pydantic but runs a minor ahead of the one CI pins. The wrapper's qualify-probe raises
    SystemExit and its diagnostic probe prints the version, so the two are distinguished by
    argument text -- SystemExit is matched FIRST because the qualify-probe contains both markers.
    """
    script = f"""#!/usr/bin/env bash
for arg in "$@"; do
    case "$arg" in
        *SystemExit*) exit 3 ;;
        *version_info*) echo "{reported_minor}"; exit 0 ;;
    esac
done
exec "{sys.executable}" "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | _EXEC_BITS)


def _required_minor() -> str:
    for line in _WRAPPER_SRC.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^REQUIRED_PYTHON_MINOR="([0-9]+\.[0-9]+)"$', line.strip())
        if match:
            return match.group(1)
    raise AssertionError("bin/venv-python does not declare REQUIRED_PYTHON_MINOR")


class TestFallbackVersionGate:
    """The fallback admits an interpreter only when the sentinel imports AND the minor matches."""

    def test_rejects_sentinel_bearing_interpreter_on_wrong_minor(self, tmp_path: Path) -> None:
        wrapper = _install_wrapper(tmp_path)
        fake_path_dir = tmp_path / "fakebin"
        fake_path_dir.mkdir()
        _make_off_version_interpreter(fake_path_dir / "python3", reported_minor="3.14")
        _make_off_version_interpreter(fake_path_dir / "python", reported_minor="3.14")

        env = dict(os.environ)
        env["PATH"] = f"{fake_path_dir}:{env['PATH']}"

        result = subprocess.run(
            [str(wrapper), "-c", "print('should not run')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 1
        assert "should not run" not in result.stdout
        assert _required_minor() in result.stderr
        assert "3.14" in result.stderr

    def test_wrong_minor_diagnostic_is_distinct_from_missing_sentinel(self, tmp_path: Path) -> None:
        """An off-version interpreter must not be reported as a missing dependency.

        The pre-existing sentinel message names pydantic and tells the operator to pip install;
        that remediation is wrong for a version mismatch and would send them in a circle.
        """
        wrapper = _install_wrapper(tmp_path)
        fake_path_dir = tmp_path / "fakebin"
        fake_path_dir.mkdir()
        _make_off_version_interpreter(fake_path_dir / "python3", reported_minor="3.14")
        _make_off_version_interpreter(fake_path_dir / "python", reported_minor="3.14")

        env = dict(os.environ)
        env["PATH"] = f"{fake_path_dir}:{env['PATH']}"

        result = subprocess.run([str(wrapper), "-c", "print('x')"], capture_output=True, text=True, encoding="utf-8", env=env)
        assert "cannot import" not in result.stderr

    def test_venv_interpreter_is_not_version_probed(self, tmp_path: Path) -> None:
        """Deliberate scope limit: only the FALLBACK is gated.

        A .venv is an operator artifact rather than an automatic choice, and this wrapper runs on
        the PreToolUse hook path fired for every harness edit -- probing it would add an
        interpreter start-up to each one. Pinned so a later change to probe it is a deliberate
        edit to this test rather than a silent latency regression.
        """
        wrapper = _install_wrapper(tmp_path)
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        _make_off_version_interpreter(venv_bin / "python", reported_minor="3.14")

        result = subprocess.run(
            [str(wrapper), "-c", "print('venv-used-unprobed')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0
        assert "venv-used-unprobed" in result.stdout


class TestRequiredMinorPinnedToSources:
    """REQUIRED_PYTHON_MINOR is restated in shell, so it is pinned to its sources by test."""

    def test_matches_pyproject_mypy_python_version(self) -> None:
        pyproject = tomllib.loads((_WRAPPER_SRC.parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
        assert pyproject["tool"]["mypy"]["python_version"] == _required_minor()

    def test_matches_every_setup_python_pin_in_workflows(self) -> None:
        workflows = sorted((_WRAPPER_SRC.parent.parent / ".github" / "workflows").glob("*.yml"))
        assert workflows, "no workflow files found"
        pinned: dict[str, set[str]] = {}
        for workflow in workflows:
            found = set(re.findall(r"python-version:\s*['\"]?([0-9]+\.[0-9]+)", workflow.read_text(encoding="utf-8")))
            if found:
                pinned[workflow.name] = found
        assert pinned, "no setup-python pins found in any workflow"
        off_target = {name: sorted(v) for name, v in pinned.items() if v != {_required_minor()}}
        assert not off_target, f"workflow python-version pins disagree with REQUIRED_PYTHON_MINOR: {off_target}"
