#!/usr/bin/env python3
"""User-level mirror of the repository's Claude Code hooks, skills, commands and agents.

Project threads launch Claude Code with --setting-sources user, which never reads the project source: .claude/settings.json
and the .claude/skills, .claude/commands and .claude/agents trees. `install` (bin/setup-cloud-env.sh, at snapshot build)
copies the hooks block into ~/.claude/settings.json unchanged and links each skill, command and agent entry under
~/.claude. The copy is exact on purpose: web sessions load both sources and Claude Code runs an identical command once,
and every hook keeps its own command and stderr in the transcript, which the capture parser reads (rules P-1, WT-2).

The mirror refreshes only when the environment snapshot is rebuilt, so a change to the hooks block or a new entry under
those trees needs a rebuild before project threads see it. `check` (SessionStart) reports that drift, including mirrored
commands whose script this checkout lacks: a warning on stdout (session context) and one stderr line. A missing Python
hook script exits 1, not 2, through bin/venv-python, so a stale mirror never blocks a tool call. Both subcommands exit 0
on every path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
KINDS = ("skills", "commands", "agents")
SIDECAR = "ontheloop-hooks-mirror.json"
TAG = "[user_hooks_mirror]"
_SCRIPT_TOKEN = re.compile(r".+\.(py|sh)$")
_PROJECT_DIR = re.compile(r"^\$(CLAUDE_PROJECT_DIR|\{CLAUDE_PROJECT_DIR\})/")


class Drift(NamedTuple):
    missing: int
    stale: int
    unlinked: int
    absent: int
    head: str


def _read_object(path: Path) -> dict[str, Any] | None:
    """The JSON object at *path*; {} when absent; None when unreadable or not an object."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    """Replace *path* (a link's target, if a link) keeping its mode; a new file is 0644."""
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _repo_hooks(repo: Path) -> dict[str, Any] | None:
    """The checkout's hooks block; None when .claude/settings.json is missing or unreadable."""
    path = repo / ".claude" / "settings.json"
    settings = _read_object(path) if path.is_file() else None
    if settings is None:
        return None
    hooks = settings.get("hooks", {})
    return hooks if isinstance(hooks, dict) else None


def _hooks(hooks: object) -> list[tuple[str, str, dict[str, Any]]]:
    """(event, matcher, hook) per registered hook."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for group in groups if isinstance(groups, list) else ():
            if isinstance(group, dict):
                found += [(event, str(group.get("matcher", "")), h) for h in group.get("hooks") or () if isinstance(h, dict)]
    return found


def _entries(hooks: object) -> set[tuple[str, str, str]]:
    """Order-free identity of each hook: any change to a matcher or a hook field counts."""
    return {(event, matcher, json.dumps(hook, sort_keys=True)) for event, matcher, hook in _hooks(hooks)}


def _script(command: object, repo: Path) -> Path | None:
    """The first .py/.sh token of *command* as a checkout path, the way the capture parser picks it (rule H-1)."""
    for token in (t.strip("'\"") for t in command.split()) if isinstance(command, str) else ():
        if _SCRIPT_TOKEN.match(token):
            path = Path(_PROJECT_DIR.sub("", token))
            return path if path.is_absolute() else repo / path
    return None


def _sources(repo: Path) -> list[tuple[Path, Path]]:
    """(repo entry, user-level link path) for every skill, command and agent entry, dot-entries excluded."""
    pairs: list[tuple[Path, Path]] = []
    for kind in KINDS:
        src = repo / ".claude" / kind
        if src.is_dir():
            pairs += [(entry, Path(kind) / entry.name) for entry in sorted(src.iterdir()) if not entry.name.startswith(".")]
    return pairs


def _points_at(link: Path, entry: Path) -> bool:
    return link.is_symlink() and Path(os.readlink(link)) == entry


def _ours(link: Path, repo: Path) -> bool:
    """A link into one of the repository's mirrored trees, or a dangling one."""
    target = Path(os.readlink(link))
    return target.parent in {repo / ".claude" / kind for kind in KINDS} or not link.exists()


def _head(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _link(entry: Path, link: Path, repo: Path) -> str | None:
    """Link *link* to *entry*; the warning when a foreign entry holds the name or the filesystem refuses."""
    try:
        if _points_at(link, entry):
            return None
        if link.is_symlink() and _ours(link, repo):
            link.unlink()
        elif link.is_symlink() or link.exists():
            return f"{TAG} WARNING: {link} is not this repository's link; left unchanged"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(entry, target_is_directory=entry.is_dir())
    except OSError as exc:
        return f"{TAG} WARNING: {link} not linked: {exc}"
    return None


def _prune(repo: Path, claude: Path) -> None:
    """Remove links into the repository's trees whose entry no longer exists."""
    for kind in KINDS:
        root, target_root = claude / kind, repo / ".claude" / kind
        for link in sorted(root.iterdir()) if root.is_dir() else ():
            if link.is_symlink() and Path(os.readlink(link)).parent == target_root and not link.exists():
                link.unlink()


def install(repo: Path, home: Path) -> list[str]:
    """Mirror *repo*'s hooks block and link its entries under *home*/.claude; never over foreign hooks."""
    claude = home / ".claude"
    settings_path, sidecar = claude / "settings.json", claude / SIDECAR
    hooks = _repo_hooks(repo)
    if hooks is None:
        return [f"{TAG} WARNING: {repo / '.claude' / 'settings.json'} is missing or unreadable; mirror not installed"]
    settings = _read_object(settings_path)
    if settings is None:
        return [f"{TAG} WARNING: {settings_path} is not a JSON object; mirror not installed"]
    if settings.get("hooks") and not sidecar.exists():
        return [f"{TAG} WARNING: {settings_path} holds hooks this script did not install; mirror not installed"]
    head = _head(repo)
    _write_atomic(sidecar, {"repo_root": str(repo), "head": head, "installed_at": datetime.now(UTC).isoformat()})
    settings["hooks"] = hooks
    _write_atomic(settings_path, settings)
    lines = [warning for entry, rel in _sources(repo) if (warning := _link(entry, claude / rel, repo))]
    _prune(repo, claude)
    return [*lines, f"{TAG} mirrored {len(_entries(hooks))} hook(s) from {head}"]


def drift(repo: Path, home: Path) -> Drift | None:
    """The mirror's difference from *repo*; None when no mirror is installed under *home*."""
    claude = home / ".claude"
    if not (claude / SIDECAR).exists():
        return None
    mirrored_hooks = (_read_object(claude / "settings.json") or {}).get("hooks")
    mirrored, live = _entries(mirrored_hooks), _entries(_repo_hooks(repo))
    unlinked = sum(1 for entry, rel in _sources(repo) if not _points_at(claude / rel, entry))
    scripts = {_script(hook.get("command"), repo) for _, _, hook in _hooks(mirrored_hooks)}
    absent = sum(1 for path in scripts if path is not None and not path.exists())
    head = str((_read_object(claude / SIDECAR) or {}).get("head", "unknown"))
    return Drift(len(live - mirrored), len(mirrored - live), unlinked, absent, head)


def check(repo: Path, home: Path) -> tuple[str, str]:
    """(stdout, stderr) for the SessionStart check."""
    found = drift(repo, home)
    if found is None:
        return "", f"{TAG} no mirror installed"
    if not any(found[:4]):
        return "", f"{TAG} mirror in sync"
    warning = (
        f"WARNING: the user-level hook mirror (~/.claude, built from {found.head}) differs from this checkout: "
        f"{found.missing} hook(s) not mirrored, {found.stale} stale, {found.absent} mirrored script(s) missing here, "
        f"{found.unlinked} skill, command or agent entries not linked. Project threads run the mirror, not "
        ".claude/settings.json, until the cloud environment snapshot is rebuilt (bin/setup-cloud-env.sh reinstalls it)."
    )
    counts = f"missing={found.missing} stale={found.stale} absent={found.absent} unlinked={found.unlinked}"
    return warning, f"{TAG} drift {counts} head={found.head}"


def main(argv: list[str]) -> int:
    try:
        home = Path.home()
        if argv[:1] == ["install"]:
            print("\n".join(install(REPO_ROOT, home)))
        elif argv[:1] == ["check"]:
            out, err = check(REPO_ROOT, home)
            if out:
                print(out)
            sys.stderr.write(err + "\n")
        else:
            sys.stderr.write(f"{TAG} usage: user_hooks_mirror.py install|check\n")
    except Exception as exc:  # noqa: BLE001 -- advisory on every path; never wedges setup or session start
        print(f"{TAG} WARNING: failed: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
