"""Pure span-based touched-tier_item attribution for docs/ROADMAP-PLATFORM.yaml.

Not a registered check and never decorated with registry.register -- an injectable primitives
library in the scripts/checks/<domain>/_helper.py shape (scripts/checks/hygiene/
_declaring_coverage.py, scripts/checks/iam_tf/_read_coverage.py). It shells nothing, reads no
file and imports no subprocess/git surface, so the checked-in fixture at
tests/fixtures/roadmap_touched_items.json drives exactly the functions the live check drives.

WHAT IS MEASURED. `item_spans` cuts one named TOP-LEVEL block (default "tier_items") of a
roadmap image into per-entry line spans: an entry starts at its own `- ` list-item line and ends
at its own LAST CONTENT LINE -- the trailing blank and comment-only lines that separate it from
the next entry are trimmed off by `_content_end` and belong to no entry at all. The roadmap
carries a `# ----- T3: ... -----` section header between tier groups; without the trim it would
sit inside the PRECEDING item's span and an edit to it would be attributed to that item, which is
a false attribution of the same class as the legacy defects this module replaces.
`changed_lines` walks a unified diff's hunks and records the 0-based line numbers each side
actually changed -- added lines against the POST image, removed lines against the PRE image, and
context lines against NEITHER. `touched_item_ids` intersects the two: an item is touched when a
changed line falls inside its span on either image, so a deleted item is still attributed from
its pre-image span.

WHY BLOCK SCOPING IS LOAD-BEARING. Roadmap `- id:` tokens are not unique to tier_items: nested
`exit_criteria` entries carry `- id: cN` and the `candidate_decisions` block carries `- id: CD.N`.
An unscoped whole-file scan therefore names ids that are not tier_items at all, and an edit below
the last tier_item (in `cross_tier_gates` or `open_questions`) must attribute to NOTHING rather
than leaking into the final tier_item's span.

`legacy_regex_item_ids` is the FROZEN pre-rec-2781 detector, retained only as
validate_platform_roadmap criterion (ii)'s unchanged failing-arm input and as the oracle the
span attribution's superset property is measured against. Its pattern's `\\s+` class spans
newlines under re.MULTILINE, which is the measured mechanism behind its false attributions.
"""

from __future__ import annotations

import bisect
import dataclasses
import re

DEFAULT_BLOCK_KEY = "tier_items"

_ENTRY_RE = re.compile(r"^(\s*)-\s")
_INLINE_ID_RE = re.compile(r"^\s*-\s+id:\s*(\S+)\s*$")
_KEY_ID_RE = re.compile(r"^\s*id:\s*(\S+)\s*$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_LEGACY_RE = re.compile(r"^[+-]\s+- id: (\S+)", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class ItemSpan:
    """One block entry's inclusive 0-based line span on one image."""

    item_id: str
    start: int
    end: int


@dataclasses.dataclass(frozen=True)
class ChangedLines:
    """The 0-based line numbers a unified diff changed, per image side."""

    pre: frozenset[int]
    post: frozenset[int]


def _block_bounds(lines: list[str], block_key: str) -> tuple[int, int] | None:
    """(first line INSIDE the block, first line AFTER it) for one top-level `block_key:` mapping.

    A top-level key is a line whose first character is not whitespace; the block runs until the
    next such line, or to end of file. Returns None when the block header is absent.
    """
    start = None
    for index, line in enumerate(lines):
        if not line[:1].isspace() and line.rstrip() == f"{block_key}:":
            start = index + 1
            break
    if start is None:
        return None
    for index in range(start, len(lines)):
        if lines[index] and not lines[index][:1].isspace():
            return start, index
    return start, len(lines)


def _entry_id(lines: list[str], start: int, end: int, indent: int) -> str | None:
    """The entry's `id` value: the inline `- id: X` form, else an `id: X` key at the entry's own
    key indent. None when the entry declares none (an unnamed list entry is attributed to
    nothing rather than to a neighbour)."""
    inline = _INLINE_ID_RE.match(lines[start])
    if inline:
        return inline.group(1)
    for index in range(start + 1, end + 1):
        line = lines[index]
        if len(line) - len(line.lstrip()) == indent + 2:
            key = _KEY_ID_RE.match(line)
            if key:
                return key.group(1)
    return None


def _content_end(lines: list[str], start: int, end: int) -> int:
    """The entry's last CONTENT line: trailing blank and comment-only lines are trimmed away.

    Those lines separate one entry from the next -- the roadmap's `# ----- T3: ... -----` tier
    section headers live there. Without the trim they fall inside the PRECEDING entry's span and
    an edit to a section header is attributed to an item it does not belong to.
    """
    while end > start and (not lines[end].strip() or lines[end].lstrip().startswith("#")):
        end -= 1
    return end


def item_spans(text: str, block_key: str = DEFAULT_BLOCK_KEY) -> list[ItemSpan]:
    """Per-entry spans of one top-level block, in file order.

    Entry lines are the `- ` list items at the block's OWN first-entry indentation, so nested
    `exit_criteria` list items (deeper indentation) never start a span of their own. Each span
    ends at its own last content line (see `_content_end`), so the spans are ordered and
    non-overlapping but NOT contiguous: the blank and comment-only lines between two entries are
    inside neither.
    """
    lines = text.splitlines()
    bounds = _block_bounds(lines, block_key)
    if bounds is None:
        return []
    block_start, block_end = bounds
    starts: list[int] = []
    indent: int | None = None
    for index in range(block_start, block_end):
        match = _ENTRY_RE.match(lines[index])
        if match is None:
            continue
        if indent is None:
            indent = len(match.group(1))
        if len(match.group(1)) == indent:
            starts.append(index)
    spans: list[ItemSpan] = []
    for position, start in enumerate(starts):
        raw_end = starts[position + 1] - 1 if position + 1 < len(starts) else block_end - 1
        end = _content_end(lines, start, raw_end)
        item_id = _entry_id(lines, start, end, indent or 0)
        if item_id is not None:
            spans.append(ItemSpan(item_id=item_id, start=start, end=end))
    return spans


def changed_lines(diff_text: str) -> ChangedLines:
    """0-based changed line numbers per side, over a unified diff's hunks.

    Only `+` and `-` body lines count; a context line advances both cursors and changes nothing,
    and the `--- `/`+++ ` file headers sit outside any hunk so they are never mistaken for one.
    """
    pre: set[int] = set()
    post: set[int] = set()
    old = new = 0
    in_hunk = False
    for line in diff_text.splitlines():
        hunk = _HUNK_RE.match(line)
        if hunk:
            old = int(hunk.group(1)) - 1
            new = int(hunk.group(2)) - 1
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("diff --git"):
            in_hunk = False
        elif line.startswith("+"):
            post.add(new)
            new += 1
        elif line.startswith("-"):
            pre.add(old)
            old += 1
        elif not line.startswith("\\"):
            old += 1
            new += 1
    return ChangedLines(pre=frozenset(pre), post=frozenset(post))


def _touched(spans: list[ItemSpan], lines: frozenset[int]) -> set[str]:
    """Ids of the spans containing at least one of `lines`, found by binary search over starts."""
    if not spans or not lines:
        return set()
    ordered = sorted(spans, key=lambda span: span.start)
    starts = [span.start for span in ordered]
    hit: set[str] = set()
    for line in lines:
        position = bisect.bisect_right(starts, line) - 1
        if position >= 0 and ordered[position].end >= line:
            hit.add(ordered[position].item_id)
    return hit


def touched_item_ids(pre_spans: list[ItemSpan], post_spans: list[ItemSpan], changed: ChangedLines) -> set[str]:
    """Ids whose span contains a changed line on EITHER image -- so a wholesale deletion is
    attributed from the pre-image span, which a post-image-only rule would silently drop."""
    return _touched(pre_spans, changed.pre) | _touched(post_spans, changed.post)


def attribute(pre_text: str, post_text: str, diff_text: str, block_key: str = DEFAULT_BLOCK_KEY) -> set[str]:
    """The span attribution for one commit's two images and its unified diff."""
    return touched_item_ids(item_spans(pre_text, block_key), item_spans(post_text, block_key), changed_lines(diff_text))


def legacy_regex_item_ids(diff_text: str) -> set[str]:
    """The FROZEN pre-rec-2781 detector: `^[+-]\\s+- id: (\\S+)` under re.MULTILINE.

    Kept byte-identical to the pattern validate_platform_roadmap criterion (ii) used inline, so
    routing the check through this symbol changes its failing arm's input set not at all.
    """
    return set(_LEGACY_RE.findall(diff_text))
