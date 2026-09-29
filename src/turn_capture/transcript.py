"""Claude Code transcript source access (stdlib json/pathlib).

Tree layout: <sessionId>.jsonl, <sessionId>/subagents/agent-<agentId>.jsonl,
<sessionId>/tool-results/<basename>. A line is a record iff newline-terminated and json.loads yields a dict;
a trailing partial line is NOT consumed; a terminated non-object line is malformed (counted, consumed, never
a row source). Sidecars resolve only as <session dir>/tool-results/<basename(persistedOutputPath)>.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src.telemetry.timestamps import TimestampError, parse_iso8601_utc

ROOT = "root"


class TranscriptTree(Protocol):
    session_id: str

    def agent_ids(self) -> list[str]: ...

    def read(self, key: str) -> bytes | None: ...

    def sidecar(self, basename: str) -> bytes | None: ...


class FsTree:
    def __init__(self, root_file: Path) -> None:
        self.root_file = root_file
        self.session_id = root_file.stem
        self._dir = root_file.parent / root_file.stem

    def agent_ids(self) -> list[str]:
        found = (self._dir / "subagents").glob("agent-*.jsonl")
        return sorted(p.stem[len("agent-") :] for p in found)

    def read(self, key: str) -> bytes | None:
        path = self.root_file if key == ROOT else self._dir / "subagents" / f"agent-{key}.jsonl"
        return path.read_bytes() if path.is_file() else None

    def sidecar(self, basename: str) -> bytes | None:
        path = self._dir / "tool-results" / basename
        return path.read_bytes() if path.is_file() else None


class MemTree:
    """In-memory twin of FsTree: files maps a relative path to its text body."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        roots = [p for p in files if "/" not in p and p.endswith(".jsonl")]
        if len(roots) != 1:
            raise ValueError("a tree needs exactly one root .jsonl file")
        self.session_id = roots[0][: -len(".jsonl")]

    def agent_ids(self) -> list[str]:
        prefix = f"{self.session_id}/subagents/agent-"
        return sorted(p[len(prefix) : -len(".jsonl")] for p in self.files if p.startswith(prefix) and p.endswith(".jsonl"))

    def read(self, key: str) -> bytes | None:
        rel = f"{self.session_id}.jsonl" if key == ROOT else f"{self.session_id}/subagents/agent-{key}.jsonl"
        body = self.files.get(rel)
        return None if body is None else body.encode("utf-8")

    def sidecar(self, basename: str) -> bytes | None:
        body = self.files.get(f"{self.session_id}/tool-results/{basename}")
        return None if body is None else body.encode("utf-8")


@dataclass(frozen=True)
class RawLine:
    line: int
    data: dict | None


def read_lines(data: bytes, limit: int | None = None) -> list[RawLine]:
    """Every newline-terminated line (up to *limit* of them) as a record or a malformed marker."""
    out: list[RawLine] = []
    for index, raw in enumerate(data.split(b"\n")[:-1]):
        if limit is not None and index >= limit:
            break
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        out.append(RawLine(index, parsed if isinstance(parsed, dict) else None))
    return out


def record_time(data: dict) -> datetime | None:
    stamp = data.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        return parse_iso8601_utc(stamp)
    except TimestampError:
        return None


def session_pin(lines: list[RawLine]) -> datetime | None:
    """The first record in root file order, of any type, whose timestamp parses; None defers capture."""
    for item in lines:
        if item.data is not None and (when := record_time(item.data)) is not None:
            return when
    return None
