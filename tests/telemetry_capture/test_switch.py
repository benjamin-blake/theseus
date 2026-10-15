"""Mirror test for scripts/telemetry_capture/switch.py (SW-1, SW-2) and the inertness of every hook with the switch off."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from scripts.telemetry_capture import switch

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".claude" / "hooks"
SMOKE = {"OTL_TURN_CAPTURE_SMOKE_REF": "synthetic:pc-smoke-0000abcd"}
REMOTE = {"CLAUDE_CODE_REMOTE": "true"}


def repo(tmp_path: Path, text: str | None) -> Path:
    root = tmp_path / "repo"
    (root / "config" / "telemetry").mkdir(parents=True)
    if text is not None:
        (root / "config" / "telemetry" / "capture.yaml").write_text(text, encoding="utf-8")
    return root


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_capture_hook_{name}", HOOKS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_switch_is_on_and_still_guarded() -> None:
    data = yaml.safe_load((REPO / switch.SWITCH_FILE).read_text(encoding="utf-8"))
    assert data == {"enabled": True}
    assert switch.capture_mode(REMOTE, REPO) == switch.ON
    assert switch.capture_mode({}, REPO) == switch.OFF
    assert switch.capture_mode({**REMOTE, "GITHUB_ACTIONS": "true"}, REPO) == switch.OFF
    assert switch.capture_mode({**REMOTE, "OTL_TURN_CAPTURE": "off"}, REPO) == switch.OFF


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("enabled: true\n", True),
        ("enabled: false\n", False),
        ("enabled: 'true'\n", False),
        ("[1]\n", False),
        (":\n- {", False),
    ],
)
def test_switch_enabled_reads_only_a_literal_true(tmp_path: Path, text: str, expected: bool) -> None:
    assert switch.switch_enabled(repo(tmp_path, text)) is expected


def test_a_missing_switch_file_is_off(tmp_path: Path) -> None:
    assert switch.switch_enabled(repo(tmp_path, None)) is False


@pytest.mark.parametrize(
    ("env", "enabled", "mode"),
    [
        (REMOTE, True, switch.ON),
        (REMOTE, False, switch.OFF),
        ({}, True, switch.OFF),
        ({**REMOTE, "GITHUB_ACTIONS": "true"}, True, switch.OFF),
        ({**REMOTE, "OTL_TURN_CAPTURE": "off"}, True, switch.OFF),
        ({**REMOTE, "OTL_TURN_CAPTURE": "on"}, True, switch.ON),
        (SMOKE, False, switch.SMOKE),
        ({**SMOKE, "GITHUB_ACTIONS": "true"}, False, switch.OFF),
        ({**SMOKE, "OTL_TURN_CAPTURE": "off"}, True, switch.OFF),
        ({"OTL_TURN_CAPTURE_SMOKE_REF": "ontheloop"}, False, switch.OFF),
        ({"OTL_TURN_CAPTURE_SMOKE_REF": "synthetic:"}, False, switch.OFF),
    ],
)
def test_capture_mode_guards(tmp_path: Path, env: dict[str, str], enabled: bool, mode: str) -> None:
    root = repo(tmp_path, f"enabled: {str(enabled).lower()}\n")
    assert switch.capture_mode(env, root) == mode
    assert switch.capture_allowed(env, root) is (mode != switch.OFF)


def _tree(tmp_path: Path) -> tuple[Path, str]:
    sid = "aaaaaaaa-0000-4000-8000-0000000000ff"
    root = tmp_path / "projects" / f"{sid}.jsonl"
    root.parent.mkdir(parents=True)
    root.write_text(json.dumps({"type": "user", "uuid": "u1", "timestamp": "2026-01-01T00:00:00.000Z"}) + "\n")
    return root, sid


def test_switch_off_keeps_every_hook_inert(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    root, sid = _tree(tmp_path)
    detached: list[object] = []

    def factory(*args, **kw):
        raise AssertionError("no client may be built while the switch is off")

    stop, end = load("stop_log_turn"), load("session_end_log_turn")
    off_repo = repo(tmp_path, "enabled: true\n")
    switch_off = repo(tmp_path / "switch_off", "enabled: false\n")
    cases = [
        (REMOTE, switch_off),
        ({**REMOTE, "GITHUB_ACTIONS": "true"}, off_repo),
        ({**REMOTE, "OTL_TURN_CAPTURE": "off"}, off_repo),
        ({}, off_repo),
    ]
    for env, root_dir in cases:
        for event in ("Stop", "StopFailure"):
            stdin = json.dumps({"hook_event_name": event, "transcript_path": str(root), "session_id": sid})
            assert stop.main(stdin, env=env, repo_root=root_dir, detach=lambda a, e: detached.append(a)) == 0
        stdin = json.dumps({"hook_event_name": "SessionEnd", "transcript_path": str(root), "session_id": sid})
        assert (
            end.main(stdin, env=env, repo_root=root_dir, client_factory=factory, detach=lambda a, e: detached.append(a)) == 0
        )
    pin = subprocess.run(
        ["bash", str(HOOKS / "session_start_log_turn.sh"), "--project-ref=ontheloop"],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": sid}),
        cwd=root.parent,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **REMOTE},
        capture_output=True,
        text=True,
        check=False,
    )
    assert pin.returncode == 0 and pin.stdout == ""
    assert detached == []
    assert sorted(p.name for p in root.parent.iterdir()) == [root.name]
    out, err = capfd.readouterr()
    assert (out, err) == ("", "")
