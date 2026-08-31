"""DECISIONS.md / DECISIONS_ARCHIVE.md per-entry authoring-size governance (Decision 167 clause 3;
the module's three mechanical stock ceilings -- the live '## Decision' header count, the
live-byte-only ceiling, and the live+archive combined byte ceiling -- are RETIRED by Decision 179).

Bounded decision-scout retrieval (PLAN-decision-scout-bounded-retrieval) means no consumer reads
the live corpus wholesale anymore, so the stock guards that sized that read no longer have a
referent; Decision 150's significance bar is the retained lever on entry count and triage quality.
This check survives as the per-NEW-entry authoring size norm enforcer only
(docs/contracts/decision-entry.yaml size_governance.per_entry_size_norm, Decision 167 clause 3,
rec-2934): a new-in-diff decision entry over the cap HARD-FAILS in the --pre tier. Historical
entries are never measured (forward-only, mirrors validate_decision_entry_conformance's own
new-vs-baseline scope). Since this check is registered UNGATED in the --pre tier (unlike the
glob-gated conformance check), the per-entry sub-check's own (git-cost) baseline read is skipped
whenever a non-default `root` is injected for testing -- production calls (the default root) pay
it only when a DECISIONS file changed in this diff.
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks import _common, registry
from scripts.checks.decisions._baseline import BaselineReaderFn, baseline_decision_numbers
from scripts.decisions_md import iter_decision_sections

_PER_ENTRY_CAP_BYTES = 6_144


_PER_ENTRY_CAP_HARD_FAIL_CITATION = (
    'Decision 167 clause 3: "A new entry over 6,144 bytes ... fails validate_decisions_size in '
    "the --pre tier -- Decision 160 point 11 named a per-entry norm as the only lever that bends "
    "the corpus's growth RATE, and this clause installs it.\""
)


def _new_entries_examined_count(root: Path, baseline_numbers: set[int]) -> int:
    """Count of NEW (non-baseline) decision entries the per-entry cap sub-check evaluated --
    mirrors `_per_entry_cap_failures`'s own new-vs-baseline scope, for the Decision 170
    declaration on the fall-through exit path."""
    count = 0
    for rel in ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"):
        path = root / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for m, _block in iter_decision_sections(content):
            if int(m.group(1)) not in baseline_numbers:
                count += 1
    return count


def _per_entry_cap_failures(root, baseline_numbers: set[int]) -> list[str]:
    """HARD-FAIL (Decision 167 clause 3's dated pre-commitment, fired by migration step 3) for
    each NEW entry (absent from baseline_numbers) over the per-entry authoring cap. Historical
    entries are still never measured -- forward-only, mirrors
    validate_decision_entry_conformance's own new-vs-baseline scope. Renamed from
    `_per_entry_cap_warnings` (WARN-tier): the old name is actively misleading once this appends
    to `failed` instead of only printing."""
    failures: list[str] = []
    for rel in ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"):
        path = root / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for m, block in iter_decision_sections(content):
            n = int(m.group(1))
            if n in baseline_numbers:
                continue
            size = len(block.encode("utf-8"))
            if size > _PER_ENTRY_CAP_BYTES:
                failures.append(
                    f"  FAIL: Decision {n} ({rel}) is {size} bytes, exceeding the {_PER_ENTRY_CAP_BYTES}-byte "
                    f"per-entry authoring cap (docs/contracts/decision-entry.yaml "
                    f"size_governance.per_entry_size_norm) -- {_PER_ENTRY_CAP_HARD_FAIL_CITATION}"
                )
    return failures


@registry.register("validate_decisions_size", owner="platform")
def validate_decisions_size(
    failed: list[str],
    root=None,
    baseline_reader: BaselineReaderFn | None = None,
) -> None:
    """Enforce the per-NEW-entry authoring size cap (Decision 167 clause 3) on
    docs/DECISIONS.md and docs/DECISIONS_ARCHIVE.md. The stock ceilings this check formerly
    also enforced -- the live header count and the live+archive combined byte ceiling -- are
    retired by Decision 179: bounded decision-scout retrieval means no consumer reads the live
    corpus wholesale anymore, so the guards that sized that read no longer have a referent;
    Decision 150's significance bar is the retained lever on entry count and triage quality.

    root / baseline_reader are test injection seams (mirrors validate_decision_entry_conformance)
    for the hard-fail per-entry cap sub-check below (Decision 167 clause 3, fired by migration
    step 3). A non-default root always exercises that sub-check (deterministic for tests); the
    default (production) root skips it whenever this check's own root equals _common.ROOT AND
    neither DECISIONS file changed in this diff, since this check runs UNGATED on every --pre
    invocation and the git baseline read is not free.

    Composes exactly ONE terminal Decision 170 declaration on each of its five reachable exit
    paths: a missing live or archive file `skipped()`s (could not examine); the cost-gated
    early return `examined(0, ...)`s (definitively zero new entries to check, not an unmet
    precondition); an unreachable diff base for the per-entry cap `skipped()`s; the
    fall-through `examined(N, ...)`s the new entries actually checked against the cap.
    """
    print("\n=== DECISIONS size governance ===")

    using_default_root = root is None
    root = root if root is not None else _common.ROOT
    baseline_reader = baseline_reader or baseline_decision_numbers

    live_path = root / "docs" / "DECISIONS.md"
    archive_path = root / "docs" / "DECISIONS_ARCHIVE.md"

    if not live_path.exists():
        print("  FAIL: docs/DECISIONS.md not found")
        failed.append("DECISIONS size governance")
        registry.skipped("docs/DECISIONS.md not found")
        return
    if not archive_path.exists():
        print("  FAIL: docs/DECISIONS_ARCHIVE.md not found")
        failed.append("DECISIONS size governance")
        registry.skipped("docs/DECISIONS_ARCHIVE.md not found")
        return

    if using_default_root and not (set(_common.get_changed_files(root)) & {"docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"}):
        registry.examined(0, unit="new_decision_entries")
        return

    baseline_numbers = baseline_reader(root)
    if baseline_numbers is None:
        print("  (per-entry cap: SKIP, origin/main unreachable.)")
        registry.skipped("origin/main unreachable")
        return
    per_entry_failures = _per_entry_cap_failures(root, baseline_numbers)
    for failure in per_entry_failures:
        print(failure)
    if per_entry_failures:
        failed.append("DECISIONS size governance")
    registry.examined(_new_entries_examined_count(root, baseline_numbers), unit="new_decision_entries")
