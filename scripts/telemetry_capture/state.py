"""The per-tree capture state directory (rules ST-1..ST-4).

<transcript dir>/<session id>/telemetry-capture/ holds state.json (the cursor envelope), lock, halt.json,
diagnostics.jsonl, writer_url and the OP-1 marker. FsTree reads only <sid>/subagents and <sid>/tool-results, so the
directory is invisible to the parser. Every write is a temp file plus os.replace. Diagnostics are counts only.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.turn_capture.cursor import CaptureCursor, CursorError
from src.turn_capture.transcript import ROOT, read_lines

STATE_DIRNAME = "telemetry-capture"
DIAGNOSTICS_KEEP = 500
VALID, LOST, TAIL_MISMATCH = "valid", "cursor_lost", "cursor_tail_mismatch"


def state_dir(transcript_path: Path, session_id: str) -> Path:
    return transcript_path.parent / session_id / STATE_DIRNAME


def root_tail_uuid(root: bytes, lines_consumed: int) -> str | None:
    """The uuid of the last root record below lines_consumed that carries one (rule ST-3)."""
    for item in reversed(read_lines(root, lines_consumed)):
        uuid = item.data.get("uuid") if item.data is not None else None
        if isinstance(uuid, str):
            return uuid
    return None


@dataclass(frozen=True)
class Loaded:
    cursor: CaptureCursor | None
    status: str

    @property
    def valid(self) -> bool:
        return self.status == VALID


class Lock:
    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def release(self) -> None:
        try:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
        finally:
            self._handle.close()


class CaptureState:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.state_file = directory / "state.json"
        self.halt_file = directory / "halt.json"
        self.diagnostics_file = directory / "diagnostics.jsonl"
        self.url_file = directory / "writer_url"
        self.marker_file = directory / "marker.json"

    def _write(self, path: Path, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def acquire(
        self, wait_s: float, *, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic
    ) -> Lock | None:
        """flock the tree's lock, polling up to wait_s; None when another pass holds it."""
        self.dir.mkdir(parents=True, exist_ok=True)
        handle = (self.dir / "lock").open("a")
        end = clock() + max(0.0, wait_s)
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return Lock(handle)
            except BlockingIOError:
                if clock() >= end:
                    handle.close()
                    return None
                sleep(min(0.2, max(0.0, end - clock())))

    def halt(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.halt_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return {"halt": "unreadable"}
        return data if isinstance(data, dict) else {"halt": "unreadable"}

    def write_halt(self, fields: dict[str, Any]) -> None:
        self._write(self.halt_file, json.dumps(fields, sort_keys=True) + "\n")

    def clear_halt(self) -> bool:
        existed = self.halt_file.exists()
        self.halt_file.unlink(missing_ok=True)
        return existed

    def load_cursor(self, root: bytes) -> Loaded:
        """A missing file, a parse failure or a root tail mismatch is a lost cursor (rule ST-3)."""
        try:
            envelope = json.loads(self.state_file.read_text(encoding="utf-8"))
            cursor = CaptureCursor.from_json(json.dumps(envelope["cursor"]))
            stored_tail = envelope["root_tail_uuid"]
        except FileNotFoundError:
            return Loaded(None, LOST)
        except (OSError, ValueError, KeyError, TypeError, CursorError):
            return Loaded(None, LOST)
        if root_tail_uuid(root, cursor.lines_consumed.get(ROOT, 0)) != stored_tail:
            return Loaded(None, TAIL_MISMATCH)
        return Loaded(cursor, VALID)

    def save_cursor(self, cursor: CaptureCursor, root: bytes, loaded: Loaded) -> bool:
        """Persist the envelope; refuse a regression below a valid loaded cursor (rule ST-2). False when refused."""
        if loaded.valid and loaded.cursor is not None:
            if cursor.lines_consumed.get(ROOT, 0) < loaded.cursor.lines_consumed.get(ROOT, 0):
                return False
        envelope = {
            "cursor": json.loads(cursor.to_json()),
            "root_tail_uuid": root_tail_uuid(root, cursor.lines_consumed.get(ROOT, 0)),
        }
        self._write(self.state_file, json.dumps(envelope, sort_keys=True) + "\n")
        return True

    def cursor_on_disk(self) -> CaptureCursor | None:
        try:
            return CaptureCursor.from_json(json.dumps(json.loads(self.state_file.read_text(encoding="utf-8"))["cursor"]))
        except (OSError, ValueError, KeyError, TypeError, CursorError):
            return None

    def diagnostics(self) -> list[dict[str, Any]]:
        try:
            lines = self.diagnostics_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def append_diagnostic(self, record: dict[str, Any]) -> None:
        """One JSON line per pass; only the last DIAGNOSTICS_KEEP lines are kept (rule ST-4)."""
        kept = self.diagnostics()[-(DIAGNOSTICS_KEEP - 1) :]
        kept.append(record)
        self._write(self.diagnostics_file, "".join(json.dumps(item, sort_keys=True) + "\n" for item in kept))

    def write_marker(self, marker: dict[str, Any]) -> None:
        self._write(self.marker_file, json.dumps(marker, sort_keys=True) + "\n")

    def marker(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.marker_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def writer_url(self) -> str | None:
        try:
            url = self.url_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return url or None

    def remember_writer_url(self, url: str) -> None:
        self._write(self.url_file, url + "\n")
