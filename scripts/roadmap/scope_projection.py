"""Scope-to-tier_item projection (PDB-04 / remedy B2-R5): a pure-local, credential-free
intersection between a plan's Scope file list and docs/ROADMAP-PLATFORM.yaml's
TierItem.files_in_scope, used by the decision-scout gate's ROADMAP overlay (step 8b).

Read-only: never flips a criterion status (Status-Trusted-Never-Inferred / T2.20), never writes
a file, and performs no warehouse or portal I/O (Decision 105 R1-R3 guard, Decision 88). Import
is side-effect-free; no validation runs at module-import time (AGENTS.md Safety).

Match rule: a tier_item matches when a `files_in_scope` entry and a Scope path are equal, or
either is a directory prefix of the other (`path.rstrip("/") + "/"`) -- bidirectional, so a
directory-shaped `files_in_scope` entry (e.g. "docs/contracts/") matches a file-shaped Scope path
just as a directory-shaped Scope path (e.g. "scripts/") matches a file-shaped `files_in_scope`
entry. Never a bare string prefix: `docs/contract` does not match `docs/contracts/x.yaml`.

KNOWN LIMITATION (measured, PLAN-decision-scout-roadmap-projection): the roadmap carries exactly
one `.claude/skills/` entry, so a skills-only or commands-only Scope list yields zero matches.
Widening the intersection key is out of scope here.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from scripts.roadmap import platform_roadmap
from scripts.roadmap.platform_roadmap import TierItem

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ROADMAP_PATH = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"

# Truncation length for a projected item's `intent` field (word-count discipline on the
# decision-scout report; see .claude/skills/decision-scout/SKILL.md step 8b).
INTENT_CHARS = 240

# Exact roster emitted per projected row. Mirrored verbatim by the `fields=[...]` marker in
# docs/contracts/exit-criteria-ledger.yaml's audit_invariants entry -- widen there first.
PROJECTED_FIELDS = (
    "id",
    "name",
    "status",
    "matched",
    "intent",
    "open_criteria",
    "depends_on",
    "related_candidate_decisions",
)


def _paths_overlap(entry: str, scope_path: str) -> bool:
    """True when `entry` and `scope_path` denote the same path, or either is a directory
    prefix of the other (segment-boundary match, never a bare string prefix).
    """
    if entry == scope_path:
        return True
    entry_dir = entry.rstrip("/") + "/"
    scope_dir = scope_path.rstrip("/") + "/"
    return scope_path.startswith(entry_dir) or entry.startswith(scope_dir)


def matched_paths(files_in_scope: Sequence[str], scope_paths: Sequence[str]) -> list[str]:
    """Return the sorted set of `files_in_scope` entries that overlap any `scope_paths` entry.

    Bidirectional: a directory-shaped `files_in_scope` entry (e.g. "docs/contracts/") matches a
    file-shaped scope path beneath it, and a directory-shaped scope path (e.g. "scripts/") -- as
    plans commonly declare -- matches a file-shaped `files_in_scope` entry beneath it. Never a
    bare string prefix.
    """
    matched: set[str] = set()
    for entry in files_in_scope:
        for scope_path in scope_paths:
            if _paths_overlap(entry, scope_path):
                matched.add(entry)
                break
    return sorted(matched)


def project_items(items: Iterable[TierItem], scope_paths: Sequence[str]) -> list[dict[str, Any]]:
    """Build one PROJECTED_FIELDS dict per TierItem whose files_in_scope intersects scope_paths."""
    projected: list[dict[str, Any]] = []
    for item in items:
        matched = matched_paths(item.files_in_scope, scope_paths)
        if not matched:
            continue
        projected.append(
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "matched": matched,
                "intent": item.intent[:INTENT_CHARS],
                "open_criteria": [{"id": c.id, "text": c.text} for c in item.exit_criteria if c.status == "open"],
                "depends_on": list(item.depends_on),
                "related_candidate_decisions": list(item.related_candidate_decisions),
            }
        )
    return projected


def project(scope_paths: Sequence[str], roadmap_path: str | Path = DEFAULT_ROADMAP_PATH) -> list[dict[str, Any]]:
    """Load the roadmap at `roadmap_path` and project `scope_paths` against its tier_items."""
    doc = platform_roadmap.load(roadmap_path)
    return project_items(doc.tier_items, scope_paths)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("Usage: scope_projection.py <scope-path> [<scope-path> ...]", file=sys.stderr)
        return 2
    print(json.dumps(project(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
