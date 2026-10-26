#!/usr/bin/env python3
"""User-level mirror of the repository's Claude Code hooks, skills, commands and agents.

Project threads launch Claude Code with --setting-sources user, which never reads the project source: .claude/settings.json
and the .claude/skills, .claude/commands and .claude/agents trees. `install` (bin/setup-cloud-env.sh, at snapshot build)
copies the hooks block into ~/.claude/settings.json unchanged and links each skill, command and agent entry under
~/.claude. The copy is exact on purpose: web sessions load both sources and Claude Code runs an identical command once,
and every hook keeps its own command and stderr in the transcript, which the capture parser reads (rules P-1, WT-2).

The mirror refreshes only when the environment snapshot is rebuilt, so a change to the hooks block or a new entry under
those trees needs a rebuild before project threads see it. `check` (SessionStart) reports that drift: a warning on stdout
(session context) and one stderr line. Both subcommands exit 0 on every path.
"""

from __future__ import annotations

import json
import os
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


class Drift(NamedTuple):
    missing: int
    stale: int
    unlinked: int
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
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _repo_hooks(repo: Path) -> dict[str, Any]:
    settings = _read_object(repo / ".claude" / "settings.json") or {}
    hooks = settings.get("hooks")
    return hooks if isinstance(hooks, dict) else {}


def _entries(hooks: object) -> set[tuple[str, str, str]]:
    """(event, matcher, hook JSON) per registered hook: order-free, but any change to a matcher or a hook field counts."""
    found: set[tuple[str, str, str]] = set()
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for group in groups if isinstance(groups, list) else ():
            if isinstance(group, dict):
                for hook in group.get("hooks") or ():
                    found.add((event, str(group.get("matcher", "")), json.dumps(hook, sort_keys=True)))
    return found


def _sources(repo: Path) -> list[tuple[Path, Path]]:
    """(repo entry, user-level link path) for every skill, command and agent entry, dot-entries excluded."""
    pairs: list[tuple[Path, Path]] = []
    for kind in KINDS:
        src = repo / ".claude" / kind
        if src.is_dir():
            pairs += [(entry, Path(kind) / entry.name) for entry in sorted(src.iterdir()) if not entry.name.startswith(".")]
    return pairs


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


def _link(entry: Path, link: Path, lines: list[str]) -> None:
    if link.is_symlink():
        if Path(os.readlink(link)) == entry:
            return
        link.unlink()
    elif link.exists():
        lines.append(f"{TAG} WARNING: {link} is not a link; left unchanged")
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(entry, target_is_directory=entry.is_dir())


def _prune(repo: Path, claude: Path) -> None:
    """Remove links into the repository's trees whose entry no longer exists."""
    for kind in KINDS:
        root, target_root = claude / kind, repo / ".claude" / kind
        for link in sorted(root.iterdir()) if root.is_dir() else ():
            target = Path(os.readlink(link)) if link.is_symlink() else None
            if target is not None and target.parent == target_root and not target.exists():
                link.unlink()


def install(repo: Path, home: Path) -> list[str]:
    """Mirror *repo*'s hooks block and link its entries under *home*/.claude; all or nothing, never over foreign hooks."""
    claude = home / ".claude"
    settings_path, sidecar = claude / "settings.json", claude / SIDECAR
    settings = _read_object(settings_path)
    if settings is None:
        return [f"{TAG} WARNING: {settings_path} is not a JSON object; mirror not installed"]
    if settings.get("hooks") and not sidecar.exists():
        return [f"{TAG} WARNING: {settings_path} holds hooks this script did not install; mirror not installed"]
    lines: list[str] = []
    settings["hooks"] = _repo_hooks(repo)
    _write_atomic(settings_path, settings)
    for entry, rel in _sources(repo):
        _link(entry, claude / rel, lines)
    _prune(repo, claude)
    head = _head(repo)
    _write_atomic(sidecar, {"repo_root": str(repo), "head": head, "installed_at": datetime.now(UTC).isoformat()})
    lines.append(f"{TAG} mirrored {len(_entries(settings['hooks']))} hook(s) from {head}")
    return lines


def drift(repo: Path, home: Path) -> Drift | None:
    """The mirror's difference from *repo*; None when no mirror is installed under *home*."""
    claude = home / ".claude"
    if not (claude / SIDECAR).exists():
        return None
    sidecar = _read_object(claude / SIDECAR)
    mirrored, live = _entries((_read_object(claude / "settings.json") or {}).get("hooks")), _entries(_repo_hooks(repo))
    unlinked = sum(1 for _, rel in _sources(repo) if not (claude / rel).exists())
    head = str((sidecar or {}).get("head", "unknown"))
    return Drift(len(live - mirrored), len(mirrored - live), unlinked, head)


def check(repo: Path, home: Path) -> tuple[str, str]:
    """(stdout, stderr) for the SessionStart check."""
    found = drift(repo, home)
    if found is None:
        return "", f"{TAG} no mirror installed"
    if not any(found[:3]):
        return "", f"{TAG} mirror in sync"
    warning = (
        f"WARNING: the user-level hook mirror (~/.claude, built from {found.head}) differs from this checkout: "
        f"{found.missing} hook(s) not mirrored, {found.stale} stale, {found.unlinked} skill, command or agent "
        "entries not linked. Project threads run the mirror, not .claude/settings.json, until the cloud environment snapshot "
        "is rebuilt (bin/setup-cloud-env.sh reinstalls it)."
    )
    return warning, f"{TAG} drift missing={found.missing} stale={found.stale} unlinked={found.unlinked} head={found.head}"


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
        sys.stderr.write(f"{TAG} failed: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
