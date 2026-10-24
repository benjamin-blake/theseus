"""Release-order guard for the STATUS v1 grammar (Decision 210 cl.4): nothing emits it before the writer accepts it.

Temporary: the sibling prevention plan relaxes it as a planned change to admit its one emitter helper.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKERS = "src/turn_capture/markers.py"
WHOLE_LINE = re.compile(
    r"STATUS v1 source=[A-Za-z0-9_][A-Za-z0-9_.-]* result=(skipped|failed)( reason=[A-Za-z0-9_][A-Za-z0-9_.-]*)?\s*"
)


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    paths = [ROOT / name for name in out.decode("utf-8").split("\0") if name]
    return [p for p in paths if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".yml", ".json", ".sh", ".txt", ""}]


def test_no_status_emitter_outside_markers() -> None:
    emitters = [*ROOT.glob("scripts/**/*.py"), *ROOT.glob("src/**/*.py"), *ROOT.glob(".claude/hooks/**/*")]
    for path in emitters:
        if not path.is_file() or path.relative_to(ROOT).as_posix() == MARKERS:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "STATUS v1" not in text and "format_status_marker" not in text, path.relative_to(ROOT)
    for path in _tracked_text_files():
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            assert not WHOLE_LINE.fullmatch(line), f"{path.relative_to(ROOT)}:{number}"
