"""The capture pin hook: one fixed stderr line, empty stdout, exit 0 for every source, no file written, no venv needed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "session_start_log_turn.sh"
LINE = "[session_start_log_turn] capture pin\n"


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact", "fork"])
def test_every_source_prints_one_fixed_stderr_line_and_writes_nothing(tmp_path: Path, source: str) -> None:
    env_bin = shutil.which("env")
    bash = shutil.which("bash")
    assert env_bin and bash
    stdin = json.dumps({"hook_event_name": "SessionStart", "source": source, "session_id": "s", "transcript_path": "/x"})
    result = subprocess.run(
        [env_bin, "-i", f"PATH={Path(bash).parent}", "HOME=" + str(tmp_path), bash, str(HOOK), "--project-ref=ontheloop"],
        input=stdin,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", LINE)
    assert list(tmp_path.iterdir()) == []


def test_closed_stdin_and_no_arguments_still_exit_zero(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(HOOK)], stdin=subprocess.DEVNULL, cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", LINE)
    assert list(tmp_path.iterdir()) == []


def test_the_hook_reads_no_stdin_and_runs_no_pass() -> None:
    body = HOOK.read_text(encoding="utf-8")
    commands = [line for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert commands == ["printf '%s\\n' \"[session_start_log_turn] capture pin\" >&2", "exit 0"]
