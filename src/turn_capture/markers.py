"""Structured gate-failure markers and the pre-commit failure grammar (stdlib only).

Single declared home of both grammars: scripts/validate.py prints gate markers, pre-commit prints
its own per-hook block, and the turn-capture parser reads both through parse_markers.
"""

from __future__ import annotations

import re
from typing import NamedTuple

GATE_MARKER_PREFIX = "GATE-FAILURE"
GATE_MARKER_VERSION = 1
SIGNATURE_PATTERN = "[A-Za-z0-9_][A-Za-z0-9_.-]{0,199}"

_SIGNATURE_RE = re.compile(SIGNATURE_PATTERN)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_GATE_RE = re.compile(rf"{GATE_MARKER_PREFIX} v{GATE_MARKER_VERSION} source=gate check=({SIGNATURE_PATTERN})")
_HOOK_RE = re.compile(rf"- hook id: ({SIGNATURE_PATTERN})")
_EXIT_RE = re.compile(r"- exit code: (-?[0-9]+)")
_MODIFIED_LINE = "- files were modified by this hook"


class Marker(NamedTuple):
    source: str
    signature: str
    line: int


def format_gate_marker(check: str) -> str:
    if not _SIGNATURE_RE.fullmatch(check):
        raise ValueError(f"check name does not fit the signature class: {check!r}")
    return f"{GATE_MARKER_PREFIX} v{GATE_MARKER_VERSION} source=gate check={check}"


def _normalise(line: str) -> str:
    line = _ANSI_RE.sub("", line)
    return line[:-1] if line.endswith("\r") else line


def _block_failed(lines: list[str]) -> bool:
    for line in lines:
        if line == _MODIFIED_LINE:
            return True
        match = _EXIT_RE.fullmatch(line)
        if match and int(match.group(1)) != 0:
            return True
    return False


def parse_markers(text: str) -> list[Marker]:
    lines = [_normalise(raw) for raw in text.split("\n")]
    markers: list[Marker] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        gate = _GATE_RE.fullmatch(line)
        if gate:
            markers.append(Marker("gate", gate.group(1), index))
            index += 1
            continue
        hook = _HOOK_RE.fullmatch(line)
        if hook:
            end = index + 1
            while end < len(lines) and lines[end].startswith("- "):
                end += 1
            if _block_failed(lines[index + 1 : end]):
                markers.append(Marker("precommit", hook.group(1), index))
            index = end
            continue
        index += 1
    return markers
