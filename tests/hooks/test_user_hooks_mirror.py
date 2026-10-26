"""The user-level mirror of the repository's Claude Code hooks, skills, commands and agents (project threads)."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / ".claude" / "hooks" / "user_hooks_mirror.py"
SETUP = ROOT / "bin" / "setup-cloud-env.sh"
CHECK_CMD = "bin/venv-python .claude/hooks/user_hooks_mirror.py check"
INSTALL_CALL = "bin/venv-python .claude/hooks/user_hooks_mirror.py install"
SCRIPTS = (".claude/hooks/a.sh", ".claude/hooks/guard.py", "gate.sh", "stop.py")
STOP = '"$CLAUDE_PROJECT_DIR/bin/venv-python" "$CLAUDE_PROJECT_DIR/stop.py"'

HOOKS: dict[str, Any] = {
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash .claude/hooks/a.sh"}]}],
    "PreToolUse": [
        {"matcher": "Edit|Bash", "hooks": [{"type": "command", "command": "bin/venv-python .claude/hooks/guard.py"}]},
        {"matcher": "^(Bash)$", "hooks": [{"type": "command", "command": "bash gate.sh", "timeout": 60}]},
    ],
    "Stop": [{"hooks": [{"type": "command", "command": STOP}]}],
}


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_user_hooks_mirror_under_test", MIRROR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    claude = repo / ".claude"
    for skill in ("planning", "implement", ".hidden"):
        (claude / "skills" / skill).mkdir(parents=True)
        (claude / "skills" / skill / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    (claude / "commands").mkdir()
    (claude / "commands" / "plan.md").write_text("plan\n", encoding="utf-8")
    (claude / "agents" / "scheduled").mkdir(parents=True)
    (claude / "agents" / "scheduled" / "ci-rca.md").write_text("agent\n", encoding="utf-8")
    for script in SCRIPTS:
        (repo / script).parent.mkdir(parents=True, exist_ok=True)
        (repo / script).write_text("exit 0\n", encoding="utf-8")
    write_settings(repo, HOOKS)
    return repo


def write_settings(repo: Path, hooks: dict[str, Any]) -> None:
    settings = {"model": "opus[1m]", "env": {"X": "1"}, "hooks": hooks}
    (repo / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def user_settings(home: Path) -> dict[str, Any]:
    return json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))


def counts(found: Any) -> tuple[int, int, int, int]:
    assert found is not None
    return found.missing, found.stale, found.unlinked, found.absent


def test_install_copies_the_hooks_block_exactly_and_nothing_else(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    assert user_settings(home) == {"hooks": HOOKS}
    assert (home / ".claude" / mirror.SIDECAR).is_file()
    assert stat.S_IMODE((home / ".claude" / "settings.json").stat().st_mode) == 0o644


def test_install_keeps_other_user_keys_and_mode_and_is_idempotent(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"theme": "dark"}', encoding="utf-8")
    (home / ".claude" / "settings.json").chmod(0o600)
    mirror.install(repo, home)
    first = (home / ".claude" / "settings.json").read_bytes()
    mirror.install(repo, home)
    assert (home / ".claude" / "settings.json").read_bytes() == first
    assert user_settings(home) == {"theme": "dark", "hooks": HOOKS}
    assert stat.S_IMODE((home / ".claude" / "settings.json").stat().st_mode) == 0o600
    assert sorted(p.name for p in (home / ".claude").iterdir() if p.name.startswith(".")) == []


def test_install_refreshes_its_own_mirror(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    changed = {"Stop": HOOKS["Stop"]}
    write_settings(repo, changed)
    mirror.install(repo, home)
    assert user_settings(home)["hooks"] == changed


def test_install_leaves_foreign_hooks_and_unreadable_settings_alone(tmp_path: Path) -> None:
    mirror, repo = load(), make_repo(tmp_path)
    for name, body in (("foreign", '{"hooks": {"Stop": []}}'), ("broken", "{not json"), ("array", "[]")):
        home = tmp_path / name
        (home / ".claude").mkdir(parents=True)
        (home / ".claude" / "settings.json").write_text(body, encoding="utf-8")
        lines = mirror.install(repo, home)
        assert (home / ".claude" / "settings.json").read_text(encoding="utf-8") == body
        assert any("WARNING" in line for line in lines)
        assert sorted(p.name for p in (home / ".claude").iterdir()) == ["settings.json"]


def test_install_refuses_an_unreadable_repository_settings_file(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    (repo / ".claude" / "settings.json").write_text("{broken", encoding="utf-8")
    lines = mirror.install(repo, home)
    assert any("WARNING" in line for line in lines)
    assert not (home / ".claude").exists()


def test_install_links_each_skill_command_and_agent_entry(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    own = home / ".claude" / "skills" / "session-start-hook"
    own.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (home / ".claude" / "skills" / "other").symlink_to(elsewhere)
    (home / ".claude" / "skills" / "gone").symlink_to(repo / ".claude" / "skills" / "gone")
    mirror.install(repo, home)
    skills = home / ".claude" / "skills"
    assert sorted(p.name for p in skills.iterdir()) == ["implement", "other", "planning", "session-start-hook"]
    assert (skills / "planning").resolve() == (repo / ".claude" / "skills" / "planning").resolve()
    assert own.is_dir() and not own.is_symlink()
    assert (home / ".claude" / "commands" / "plan.md").resolve() == (repo / ".claude" / "commands" / "plan.md").resolve()
    assert (home / ".claude" / "agents" / "scheduled").resolve() == (repo / ".claude" / "agents" / "scheduled").resolve()


def test_install_never_replaces_a_foreign_entry_and_check_counts_it(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    real = home / ".claude" / "skills" / "planning"
    real.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (home / ".claude" / "skills" / "implement").symlink_to(elsewhere)
    lines = mirror.install(repo, home)
    assert real.is_dir() and not real.is_symlink()
    assert Path(os.readlink(home / ".claude" / "skills" / "implement")) == elsewhere
    assert sum("WARNING" in line for line in lines) == 2
    assert counts(mirror.drift(repo, home)) == (0, 0, 2, 0)


def test_a_failed_link_does_not_lock_the_mirror_out(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "commands").write_text("not a directory\n", encoding="utf-8")
    lines = mirror.install(repo, home)
    assert any("WARNING" in line and "plan.md" in line for line in lines)
    assert user_settings(home)["hooks"] == HOOKS
    assert counts(mirror.drift(repo, home)) == (0, 0, 1, 0)
    (home / ".claude" / "commands").unlink()
    mirror.install(repo, home)
    assert counts(mirror.drift(repo, home)) == (0, 0, 0, 0)


def test_check_is_silent_and_inert_without_a_mirror(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    assert mirror.drift(repo, home) is None
    out, err = mirror.check(repo, home)
    assert out == "" and "no mirror" in err
    assert not (home / ".claude").exists()


def test_check_is_quiet_when_in_sync(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    out, err = mirror.check(repo, home)
    assert out == "" and err == "[user_hooks_mirror] mirror in sync"


def test_check_reports_missing_and_stale_hook_commands(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    live = json.loads(json.dumps(HOOKS))
    live["PreToolUse"][1]["hooks"][0]["timeout"] = 90
    live["SessionEnd"] = [{"hooks": [{"type": "command", "command": "end.py"}]}]
    write_settings(repo, live)
    assert counts(mirror.drift(repo, home)) == (2, 1, 0, 0)
    out, err = mirror.check(repo, home)
    assert "WARNING" in out and "snapshot" in out
    assert err.startswith("[user_hooks_mirror] drift missing=2 stale=1 absent=0 unlinked=0 head=")


def test_check_reports_mirrored_scripts_this_checkout_lacks(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    (repo / ".claude" / "hooks" / "guard.py").unlink()
    (repo / "stop.py").unlink()
    assert counts(mirror.drift(repo, home)) == (0, 0, 0, 2)
    assert "2 mirrored script(s) missing here" in mirror.check(repo, home)[0]


def test_check_ignores_hook_order_but_not_matchers(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    live = json.loads(json.dumps(HOOKS))
    live["PreToolUse"].reverse()
    write_settings(repo, live)
    assert counts(mirror.drift(repo, home)) == (0, 0, 0, 0)
    live["PreToolUse"][0]["matcher"] = "Bash"
    write_settings(repo, live)
    assert counts(mirror.drift(repo, home)) == (1, 1, 0, 0)


def test_check_reports_entries_added_after_the_snapshot(tmp_path: Path) -> None:
    mirror, repo, home = load(), make_repo(tmp_path), tmp_path / "home"
    mirror.install(repo, home)
    (repo / ".claude" / "skills" / "orient").mkdir()
    assert counts(mirror.drift(repo, home)) == (0, 0, 1, 0)


def run_cli(args: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(MIRROR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
        check=False,
    )


def test_the_real_repository_mirrors_cleanly(tmp_path: Path) -> None:
    home = tmp_path / "home"
    installed = run_cli(["install"], home)
    assert installed.returncode == 0, installed.stderr
    assert "WARNING" not in installed.stdout
    real_hooks = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    assert user_settings(home) == {"hooks": real_hooks}
    checked = run_cli(["check"], home)
    assert (checked.returncode, checked.stdout, checked.stderr.strip()) == (0, "", "[user_hooks_mirror] mirror in sync")


def test_the_cli_always_exits_zero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for args in ([], ["bogus"], ["check"]):
        assert run_cli(args, home).returncode == 0
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / load().SIDECAR).write_text("{broken", encoding="utf-8")
    (home / ".claude" / "settings.json").write_text("{broken", encoding="utf-8")
    assert run_cli(["check"], home).returncode == 0


def test_the_check_runs_every_session_start() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [item["command"] for item in settings["hooks"]["SessionStart"][0]["hooks"]]
    assert CHECK_CMD in commands


def _setup_step(script: str) -> str:
    lines = script.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("if ") and INSTALL_CALL in line)
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start : end + 1])


def test_setup_installs_the_mirror_warn_and_continue(tmp_path: Path) -> None:
    script = SETUP.read_text(encoding="utf-8")
    assert script.count(INSTALL_CALL) == 1
    assert script.index("pre-commit install-hooks") < script.index(INSTALL_CALL)
    assert script.index(INSTALL_CALL) < script.index("bash .claude/hooks/session_start_aws.sh")
    (tmp_path / "bin").mkdir()
    stub = tmp_path / "bin" / "venv-python"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    body = "set -euo pipefail\nlog() { printf '[setup] %s\\n' \"$*\"; }\n" + _setup_step(script) + "\necho reached-end\n"
    result = subprocess.run(["bash", "-c", body], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert result.returncode == 0
    assert "WARNING: user-level hook mirror install failed" in result.stdout
    assert result.stdout.rstrip().endswith("reached-end")
