"""Append-only live-body immutability guard (PLAN-adr-restructure-wave, rec-3249).

Locks the live decision corpus after the ADR restructuring wave: once ratified, a decision
body is never rewritten in place. Every future correction is a dated append annotation, a
supersession, or a Decision 146 archive move -- the post-lock correction dialect.

THE LOCK HAS NO WAIVER ROUTE AND READS NO CONFIG. An exception path would be the Decision 163
anti-pattern (a gate whose escape hatch becomes the default); the dialect above is the escape
hatch, and it is expressive enough that a mechanical bypass is never needed. This module
deliberately imports no config loader and consults no allowlist file.

Classification, for every decision number present at the origin/main baseline (union across
both corpus files, via the shared scripts.checks.decisions._baseline reader):

  (i)   Number in docs/DECISIONS.md, body does NOT newly declare Superseded -- EXACT-LINE
        APPEND-ONLY. Every prepared baseline line must appear verbatim as a distinct prepared
        current line, in order (injective, order-preserving, exact equality). New lines may be
        inserted anywhere, including inside an Intent section. Any modification, deletion,
        join, or reorder of an existing line FAILS. Because the embedding is injective,
        deleting one of two identical lines FAILS -- each duplicate consumes its own match.
  (ii)  Number in docs/DECISIONS.md, body NEWLY declares Superseded (baseline did not) -- the
        body must satisfy the STRICT STUB SHAPE below. scripts.decisions_md.is_compacted_stub
        is deliberately NOT the predicate: it tests marker PRESENCE only, so a full body
        carrying both markers would pass it, leaving a pointer-bearing Status-flip bypass open.
  (iii) Number absent from docs/DECISIONS.md but present in docs/DECISIONS_ARCHIVE.md -- a
        Decision 146 archive move. The archived body must EMBED the prepared baseline lines
        under the same injective ordered rule, with exactly two exemptions (the header line,
        whose trailing parenthetical the move retitles, and the baseline Status marker line,
        rewritten to the archive convention). A conforming move PASSES; an
        archive-move-with-rewrite FAILS -- relocation is not a content escape.
  (iv)  Number absent from BOTH files -- FAIL unconditionally (never_remove_headers).
  (v)   Baseline body ALREADY declared Superseded -- defer to the conformance stub/archive
        enforcement, which owns historical stubs and superseded bodies.

LINE PREPARATION for every comparison: both bodies are taken as line sequences with each line
rstripped (so a trailing-whitespace-only difference is not a modification), and lines inside a
CLOSED fenced reversal-conditions stanza are EXCLUDED on both sides. That stanza is a mutable,
machine-monitored surface -- scripts/preflight/decision_conditions.py is its watcher and its own
on_trigger dialect says "update or re-arm this stanza" -- so re-arms and review_by bumps stay
legal. STANZA PRESENCE is still guarded: if the baseline body contains such a stanza, the
current body must contain one too. Interiors free, existence locked.

Two properties keep that carve-out from becoming the bypass this lock exists to prevent, and both
are load-bearing rather than incidental. The fence grammar is IMPORTED from the owning module, so
the set of spellings this lock exempts is identical BY CONSTRUCTION to the set that module
monitors -- a locally-authored pattern even slightly wider would exempt a fence nothing else
polices. And an UNTERMINATED fence grants no exemption at all: its opening line and everything
after it stay in the comparison, so opening a fence and never closing it cannot lift a body out
of this lock's reach.

Consequence, recorded in the ratifying Decision: mid-line splices and table-cell appends are
retired micro-shapes. A correction lands as its own dated annotation line, never as an edit to
an existing line.

Advisory SKIP (never a failure) when origin/main is unreachable -- the check cannot resolve
current-vs-baseline without it, mirroring the sibling decisions-domain checks.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry
from scripts.checks.decisions._baseline import BaselineBodyReaderFn
from scripts.checks.decisions._baseline import baseline_decision_bodies as _default_baseline_decision_bodies
from scripts.decisions_md import iter_decision_sections, status_is_superseded
from scripts.preflight.decision_conditions import _FENCE_CLOSE_RE, _FENCE_OPEN_RE

_LIVE_REL_PATH = "docs/DECISIONS.md"
_ARCHIVE_REL_PATH = "docs/DECISIONS_ARCHIVE.md"

# The carve-out's fence grammar is IMPORTED from scripts/preflight/decision_conditions.py -- the
# module that owns the Decision 133 monitored stanza -- and never re-spelled here (Decision 134
# clause 3 shared-parser mandate, the same rule _baseline.py's docstring cites).
#
# This is load-bearing, not stylistic. A locally-authored pattern even slightly WIDER than the
# owner's is a self-service bypass of this lock: a fence spelling the lock carves out but the
# owner does not recognise is invisible to validate_reversal_stanzas, so its span leaves this
# lock's jurisdiction with nothing else policing it. Importing makes the two sets identical by
# construction, so they cannot drift apart in a later edit.
#
# Note the owner's regexes are compiled with re.MULTILINE for whole-block .search(); they are
# used here per-line with .match(), which is unaffected by that flag.

_STATUS_MARKER_RE = re.compile(r"^\*\*Status:\*\*")
_HEADING_RE = re.compile(r"^#{2,3}\s+Decision\s+\d+:")

# The strict stub shape (branch ii): after the header line, every non-blank line up to the
# block separator must match one of these. Deliberately narrower than is_compacted_stub.
_STUB_LINE_PATTERNS = (
    re.compile(r"^\*\*Status:\*\*\s*Superseded\s*$"),
    re.compile(r"^\*\*Date:\*\*\s*.+$"),
    re.compile(r"^\*\*Decision:\*\*\s*.+$"),
    re.compile(r"^\*\*Superseded by:\s*Decision\s+\d+\*\*\s*$"),
    re.compile(r"^---\s*$"),
)


def prepare_lines(block: str) -> list[str]:
    """Rstripped line sequence with CLOSED reversal-conditions stanza interiors removed.

    The stanza's own fence lines are dropped alongside its interior: a re-arm that rewrites the
    whole stanza (fences included) must not fail on a fence-line mismatch, and stanza PRESENCE
    is asserted separately by has_reversal_stanza rather than by line embedding.

    FAIL-SAFE ON AN UNTERMINATED FENCE: a stanza that opens and never closes before the end of
    the block grants NO exemption -- its opening fence and every line after it stay in the
    comparison. Excluding them would hand an author a one-line, self-service way to move a whole
    body out of this lock's jurisdiction, which is precisely what the lock exists to prevent. The
    exemption is a reward for a well-formed stanza, never a consequence of an ill-formed one.
    """
    lines = [raw.rstrip() for raw in block.splitlines()]
    excluded: set[int] = set()
    open_at: int | None = None
    for i, line in enumerate(lines):
        if open_at is None:
            if _FENCE_OPEN_RE.match(line):
                open_at = i
            continue
        if _FENCE_CLOSE_RE.match(line):
            excluded.update(range(open_at, i + 1))
            open_at = None
    # A still-open stanza at end-of-block is deliberately NOT added to `excluded`.
    return [line for i, line in enumerate(lines) if i not in excluded]


def has_reversal_stanza(block: str) -> bool:
    """True iff block contains a reversal-conditions stanza opener the OWNER also recognises."""
    return any(_FENCE_OPEN_RE.match(raw.rstrip()) for raw in block.splitlines())


def embeds_in_order(baseline: list[str], current: list[str], exempt: set[int] | None = None) -> int | None:
    """Index of the first baseline line with no ordered, injective match in current, or None.

    Greedy left-to-right matching over exact (already-rstripped) equality. Because each match
    consumes its current-side position, N identical baseline lines require N identical current
    lines -- deleting one duplicate is detected. `exempt` holds baseline indices that need no
    match at all (branch iii's header and Status lines).
    """
    exempt = exempt or set()
    cursor = 0
    for i, line in enumerate(baseline):
        if i in exempt:
            continue
        try:
            offset = current.index(line, cursor)
        except ValueError:
            return i
        cursor = offset + 1
    return None


def _stub_shape_violation(block: str) -> str | None:
    """First line of block violating the strict stub shape, or None when conformant."""
    lines = block.splitlines()
    if not lines or not _HEADING_RE.match(lines[0].rstrip()):
        return "missing '## Decision N:' header line"
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        if not any(pattern.match(line) for pattern in _STUB_LINE_PATTERNS):
            return line
    return None


def _archive_exempt_indices(baseline_lines: list[str]) -> set[int]:
    """Branch-iii exemptions: the header line and the baseline Status marker line.

    A Decision 146 move retitles the header's trailing parenthetical and rewrites the Status
    marker to the archive convention. Every OTHER baseline line must still embed, so an
    archive-move-with-rewrite is caught.
    """
    exempt: set[int] = set()
    for i, line in enumerate(baseline_lines):
        if _HEADING_RE.match(line) or _STATUS_MARKER_RE.match(line):
            exempt.add(i)
    return exempt


def _current_entries(root: Path, rel: str) -> dict[int, str]:
    """decision number -> heading-inclusive raw block for one corpus file in the working tree."""
    path = root / rel
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {int(match.group(1)): block for match, block in iter_decision_sections(content)}


def _classify_issues(
    baseline_live: dict[int, str],
    baseline_archive: dict[int, str],
    current_live: dict[int, str],
    current_archive: dict[int, str],
) -> list[str]:
    """Return one issue string per violating baseline number, in ascending number order."""
    issues: list[str] = []
    baseline_numbers = sorted(set(baseline_live) | set(baseline_archive))

    for number in baseline_numbers:
        baseline_block = baseline_live.get(number, baseline_archive.get(number, ""))

        # Branch (v): already superseded at baseline -- conformance's jurisdiction.
        if status_is_superseded(baseline_block):
            continue

        current_block = current_live.get(number)

        if current_block is None:
            archived_block = current_archive.get(number)
            if archived_block is None:
                # Branch (iv): vanished from both files.
                issues.append(
                    f"  FAIL: Decision {number} is present at origin/main but absent from BOTH "
                    f"{_LIVE_REL_PATH} and {_ARCHIVE_REL_PATH} -- never_remove_headers (Decision 149). "
                    f"Compact to a stub or archive the entry; never delete a header."
                )
                continue
            # Branch (iii): archive move.
            issues.extend(_archive_move_issues(number, baseline_block, archived_block))
            continue

        if status_is_superseded(current_block):
            # Branch (ii): newly superseded -- strict stub shape.
            violation = _stub_shape_violation(current_block)
            if violation is not None:
                issues.append(
                    f"  FAIL: Decision {number} newly declares '**Status:** Superseded' but its body is not a "
                    f"strict compaction stub -- first offending line: {violation!r}. A Status flip may only "
                    f"accompany a body reduced to the stub grammar (Status / Date / a single Decision pointer / "
                    f"'**Superseded by: Decision N**' / '---'); retaining other prose alongside the markers is the "
                    f"pointer-bearing bypass this guard closes."
                )
            continue

        # Branch (i): exact-line append-only.
        issues.extend(_append_only_issues(number, baseline_block, current_block))

    return issues


def _append_only_issues(number: int, baseline_block: str, current_block: str) -> list[str]:
    issues: list[str] = []
    baseline_lines = prepare_lines(baseline_block)
    current_lines = prepare_lines(current_block)
    missing = embeds_in_order(baseline_lines, current_lines)
    if missing is not None:
        issues.append(
            f"  FAIL: Decision {number} ({_LIVE_REL_PATH}) modifies or removes a ratified body line -- "
            f"live bodies are append-only. First unmatched baseline line: {baseline_lines[missing]!r}. "
            f"Corrections land as a NEW dated annotation line (decision-entry.yaml amendment_forms) or a "
            f"supersession; never as an edit to an existing line."
        )
    if has_reversal_stanza(baseline_block) and not has_reversal_stanza(current_block):
        issues.append(
            f"  FAIL: Decision {number} ({_LIVE_REL_PATH}) deletes its fenced reversal-conditions stanza. "
            f"Stanza INTERIORS are freely editable (re-arm, review_by bump -- decision_conditions.py is their "
            f"watcher); stanza EXISTENCE is locked."
        )
    return issues


def _archive_move_issues(number: int, baseline_block: str, archived_block: str) -> list[str]:
    issues: list[str] = []
    baseline_lines = prepare_lines(baseline_block)
    archived_lines = prepare_lines(archived_block)
    exempt = _archive_exempt_indices(baseline_lines)
    missing = embeds_in_order(baseline_lines, archived_lines, exempt=exempt)
    if missing is not None:
        issues.append(
            f"  FAIL: Decision {number} moved to {_ARCHIVE_REL_PATH} but its body was rewritten in the move -- "
            f"first unmatched baseline line: {baseline_lines[missing]!r}. A Decision 146 move may retitle the "
            f"header's trailing parenthetical and rewrite the Status marker; every other line must survive "
            f"verbatim. Relocation is not a content escape."
        )
    if has_reversal_stanza(baseline_block) and not has_reversal_stanza(archived_block):
        issues.append(
            f"  FAIL: Decision {number} lost its fenced reversal-conditions stanza in the move to "
            f"{_ARCHIVE_REL_PATH}. Stanza existence survives an archive move."
        )
    return issues


@registry.register("validate_live_entry_immutability", owner="platform")
def validate_live_entry_immutability(
    failed: list[str],
    root: Path | None = None,
    baseline_body_reader: BaselineBodyReaderFn | None = None,
) -> None:
    """Enforce append-only immutability on every baseline-present live decision body.

    root / baseline_body_reader are test/dogfood injection seams (mirrors the sibling
    decisions-domain checks) -- default to _common.ROOT and the shared memoized
    `git show origin/main:...` body reader respectively.
    """
    print("\n=== Live decision-body immutability (append-only lock) ===")
    root = root if root is not None else _common.ROOT
    baseline_body_reader = baseline_body_reader or _default_baseline_decision_bodies

    baseline_bodies = baseline_body_reader(root)
    if baseline_bodies is None:
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI).")
        registry.skipped("origin/main unreachable")
        return

    baseline_live = baseline_bodies.get(_LIVE_REL_PATH, {})
    baseline_archive = baseline_bodies.get(_ARCHIVE_REL_PATH, {})
    current_live = _current_entries(root, _LIVE_REL_PATH)
    current_archive = _current_entries(root, _ARCHIVE_REL_PATH)

    issues = _classify_issues(baseline_live, baseline_archive, current_live, current_archive)
    examined = len(set(baseline_live) | set(baseline_archive))

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Live decision-body immutability")
    else:
        print(f"  PASS: all {examined} baseline decision bodies are unmodified or append-only.")
    registry.examined(examined, unit="baseline_decision_bodies")
