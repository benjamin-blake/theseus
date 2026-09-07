"""One-time duplicate-episode cleanup for a rec source with more than one open rec (rec-3291 /
rec-3563 migration).

Deliberately SEPARATE from scripts/rec_episode.py: a migration is not a durable verb, and lodging
a bulk destructive close inside the primitive three monitors import would leave it permanently
reachable. Delete this module once the migration is done.

`--propose` prints the keeper it would retain and the ids it would supersede, and writes nothing.
`--confirm` performs the closes. Decision 103 requires a semantic verdict (duplicate/superseded)
to produce a close_proposed proposal for human confirmation before any close -- the operator's
standing direction licenses the RULE (newest open rec per source is the keeper, title-blind,
matching the runtime find_rec lookup this migration installs), this module puts the enumerated
LIST in front of them before --confirm acts on it.

Keyed on SOURCE alone, not (source, title): the runtime lookup this migration installs
(scripts.rec_episode.find_rec / find_recs) matches on source (+status), title-blind, because one
rec can cover several conditions for the same source (see
scripts.convergence_health.escalate._condition_from_existing_rec). A per-title cleanup would leave
a second open rec for the source that the runtime lookup would never revisit.
"""

from __future__ import annotations

import sys
from typing import Any, Optional

from scripts.rec_episode import find_recs


def select_keeper(open_recs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the newest open rec for the source (title-blind), or None if the list is empty.

    Ranked by `created_timestamp` (an ISO-8601 string sorts correctly lexicographically); ties
    fall back to the larger numeric rec-N suffix so selection stays deterministic without a
    separate tie-break flag. A rec id that doesn't parse as rec-<digits> sorts before every
    parseable id rather than raising -- this is a read-only ranking, not a write-time gate.
    """
    if not open_recs:
        return None

    def _rec_num(rec: dict[str, Any]) -> int:
        try:
            return int(str(rec.get("id", "")).rsplit("-", 1)[-1])
        except ValueError:
            return -1

    return max(open_recs, key=lambda r: (r.get("created_timestamp") or "", _rec_num(r)))


def propose(source: str, *, reader: Any = None, profile: Optional[str] = None) -> dict[str, Any]:
    """Print (and return) the keeper and the ids it would supersede. Writes nothing."""
    open_recs = find_recs(source, reader=reader, profile=profile)
    keeper = select_keeper(open_recs)
    superseded = sorted(r["id"] for r in open_recs if keeper is not None and r["id"] != keeper["id"])
    result = {"source": source, "keeper": keeper["id"] if keeper else None, "superseded": superseded}
    print(f"[rec_episode_dedupe] PROPOSE source={source!r}: keeper={result['keeper']!r} supersede={superseded}")
    return result


def confirm(
    source: str,
    *,
    portal_caller: Optional[Any] = None,
    reader: Any = None,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Close every open rec for `source` except the keeper, as superseded naming the keeper.

    Re-derives the population fresh (never reuses a prior propose() call's result) -- a
    population that moved between propose and confirm produces a different, correctly-scoped
    confirm outcome rather than acting on a stale list.
    """
    open_recs = find_recs(source, reader=reader, profile=profile)
    keeper = select_keeper(open_recs)
    if keeper is None:
        print(f"[rec_episode_dedupe] CONFIRM source={source!r}: no open recs -- nothing to do.")
        return {"source": source, "keeper": None, "closed": []}

    closed: list[str] = []
    for rec in open_recs:
        if rec["id"] == keeper["id"]:
            continue
        updates = {
            "status": "closed",
            "resolution": f"Superseded by {keeper['id']} (rec_episode_dedupe migration, source={source}).",
        }
        if portal_caller is not None:
            portal_caller("close", {"id": rec["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(rec["id"], updates, profile=profile)
        closed.append(rec["id"])

    closed.sort()
    print(f"[rec_episode_dedupe] CONFIRM source={source!r}: keeper={keeper['id']!r} closed={closed}")
    return {"source": source, "keeper": keeper["id"], "closed": closed}


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: <source> (--propose | --confirm) [--profile PROFILE].

    python -m scripts.rec_episode_dedupe tf_convergence_stale --propose
    python -m scripts.rec_episode_dedupe tf_convergence_stale --confirm
    """
    args = list(argv if argv is not None else sys.argv[1:])
    positional = [a for a in args if not a.startswith("--")]
    has_mode = "--propose" in args or "--confirm" in args
    if not positional or not has_mode or ("--propose" in args and "--confirm" in args):
        print("usage: python -m scripts.rec_episode_dedupe <source> (--propose | --confirm) [--profile PROFILE]")
        return 2

    source = positional[0]
    profile = None
    if "--profile" in args:
        profile_idx = args.index("--profile")
        if profile_idx + 1 < len(args):
            profile = args[profile_idx + 1]

    if "--propose" in args:
        propose(source, profile=profile)
        return 0

    confirm(source, profile=profile)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
