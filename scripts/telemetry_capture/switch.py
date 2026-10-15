"""The capture switch and guards (rule SW-1) and the synthetic-bound smoke override (rule SW-2). Stdlib and yaml only."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

SWITCH_FILE = Path("config") / "telemetry" / "capture.yaml"
SMOKE_ENV = "OTL_TURN_CAPTURE_SMOKE_REF"
SMOKE_PREFIX = "synthetic:"
OFF, ON, SMOKE = "off", "on", "smoke"


def switch_enabled(repo_root: Path) -> bool:
    try:
        data = yaml.safe_load((repo_root / SWITCH_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return False
    return isinstance(data, dict) and data.get("enabled") is True


def smoke_ref(env: Mapping[str, str]) -> str | None:
    ref = env.get(SMOKE_ENV) or ""
    return ref if ref.startswith(SMOKE_PREFIX) and len(ref) > len(SMOKE_PREFIX) else None


def capture_mode(env: Mapping[str, str], repo_root: Path) -> str:
    """off, on, or smoke (allowed only for a tree pinned to the smoke ref, which the runner re-checks)."""
    if env.get("GITHUB_ACTIONS") == "true" or env.get("OTL_TURN_CAPTURE") == "off":
        return OFF
    if smoke_ref(env) is not None:
        return SMOKE
    if env.get("CLAUDE_CODE_REMOTE") == "true" and switch_enabled(repo_root):
        return ON
    return OFF


def capture_allowed(env: Mapping[str, str], repo_root: Path) -> bool:
    return capture_mode(env, repo_root) != OFF
