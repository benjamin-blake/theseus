"""Merge-leg refusal predicate for the Resolves: trailer closure gate (rec-3775 / rec-3901).

Pure predicate over an already-computed changed-file set: resolve a fact or return a verdict;
never write, file, retry, or downgrade a status (Decision 55/72). This module imports neither
`changed_files` nor `subprocess` -- CALLER OWNS THE I/O:
scripts.ops_portal.ci_rca_lifecycle.close_recs_from_trailer calls
scripts.ops_portal.closure_gate.changed_files(commit_sha, ROOT) and passes the result in here, so
this module stays trivially unit-testable and ships no dead import (ruff F401).
"""

from __future__ import annotations

_PLAN_PREFIX = "docs/plans/"


def merge_leg_refuses(changed: set[str] | None) -> bool:
    """True when `changed` is None, EMPTY, or entirely under `docs/plans/`.

    None or empty REFUSES deliberately: `git diff-tree -r <sha>` on a true (non-squash) merge
    commit lists nothing, and a fail-open there would reinstate the defect this gate exists to
    close (Decision 55 fail-closed posture) -- an unresolvable sha refuses for the same reason.
    A changed set confined to `docs/plans/` means the merge carries a plan document only, not the
    code its trailer names -- refuse so a plan-only merge cannot close recs it never implemented.
    """
    if not changed:
        return True
    return all(path.startswith(_PLAN_PREFIX) for path in changed)
