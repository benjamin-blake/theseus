"""Pure commit-trailer parser for Resolves: rec-NNNN trailer lines.

No I/O.  Import and call parse_resolves_trailer(message) -> list[str].

BLOCK rule (rec-2922): the message is split on blank lines into blocks. A `Resolves:` line is
read only from a block whose EVERY line is `Key: value`-shaped (`^[A-Za-z][A-Za-z-]*:\\s`) --
never from a line embedded in an ordinary prose paragraph. ANY such block counts, not only the
final one, so a `Resolves:` block followed by this repository's mandated `Co-Authored-By:` /
`Claude-Session:` attribution footer still parses (measured over 600 commits on origin/main: a
final-block-only rule loses 79 of 122 historical Resolves commits to that footer). The space
after the colon is REQUIRED -- `Resolves:rec-NNNN` does not parse under the block-line shape.
"""

from __future__ import annotations

import re

_BLOCK_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z-]*:\s")
_KEY_VALUE_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$")
_TOKEN_RE = re.compile(r"\brec-\d+\b", re.IGNORECASE)


def _blocks(message: str) -> list[list[str]]:
    """Split `message` into blocks of consecutive non-blank lines, dropping blank separators."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in message.splitlines():
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def parse_resolves_trailer(message: str) -> list[str]:
    """Return a deduplicated list of rec-<digits> ids from Resolves: trailers.

    Handles comma- or space-separated lists, is case-insensitive on the
    keyword and the rec- token, and ignores malformed tokens (anything not
    matching rec-<digits>).

    Args:
        message: A git commit message body (may contain multiple lines).

    Returns:
        Deduplicated list of lowercase rec-<digits> ids in first-seen order.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for block in _blocks(message):
        if not all(_BLOCK_LINE_RE.match(line) for line in block):
            continue
        for line in block:
            match = _KEY_VALUE_RE.match(line)
            if match is None or match.group(1).lower() != "resolves":
                continue
            for token in _TOKEN_RE.findall(match.group(2)):
                normalised = token.lower()
                if normalised not in seen:
                    seen.add(normalised)
                    ids.append(normalised)
    return ids
