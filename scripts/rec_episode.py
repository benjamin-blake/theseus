"""Shared episode primitive for rec-governance dedup lookups (rec-3291 / rec-3563).

Root cause this replaces: three scheduled-monitor dedup lookups (escalate.py's
find_open_convergence_stale_rec, code_drift.py's two finders) bulk-fetched every open rec via the
`open_recs` named verb (id/title/context/created_timestamp/automatable ONLY) and then filtered the
result on `source`/`status` -- two columns that verb never projects. Every such filter silently
matched nothing, so every episode re-filed a duplicate rec instead of updating the one already
open. scripts/checks/_budget_recs.py's own dedupe independently discovered and worked around the
same defect (an absent-key-means-satisfied inversion) rather than fixing the read.

This module is the one scoped-read primitive every rec-governance monitor now calls instead:

  find_recs(source, ...)  -- every rec matching (source, status), scoped by a structural
                             single-key `current_state(..., row_filter="source = '<source>'")`
                             read (never a bulk fetch-then-client-filter), with a runtime
                             assertion that every returned row carries the keys this lookup
                             filters on.
  find_rec(source, ...)   -- the single match (plus an optional sub_key predicate for a finer
                             grain than source+status, e.g. budget_ingest's (branch, phase)).
  decide(...)             -- the four-state file/update/close/none truth table (re-homed from
                             scripts.convergence_health.assess.escalation_action -- that module
                             re-exports this).
  run_episode(...)        -- the file/update/close orchestration escalate() and the two
                             code_drift sensors previously duplicated by hand.

`current_state` (not a new NAMED_READS verb) is the deliberate choice: it is an already-sanctioned
structural read that returns every column of ops_recommendations, so no NAMED_READS_VERSION bump
or Lambda-manifest change is needed, and a narrowed verb can never reintroduce this defect class
(the registered guard at scripts/checks/hygiene/validate_episode_lookup_projection.py covers the
`named()` verbs that DO narrow).

No destructive verb lives here -- main() below exposes ONLY read-only --probe/--count
diagnostics. The one-time duplicate-rec cleanup this migration also needs lives in the sibling
module scripts/rec_episode_dedupe.py, deliberately kept out of this primitive (see that module's
docstring for why).
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

_OPS_RECOMMENDATIONS_TABLE = "ops_recommendations"

# The keys every find_recs/find_rec call filters on unconditionally -- checked present on every
# row a scoped read returns, regardless of sub_key. A row missing either one means the read no
# longer projects a key this lookup depends on; raising here is what makes that unreachable
# instead of silently indistinguishable from "no open rec" (the rec-3291 / rec-3563 defect shape).
_BASE_FILTERED_KEYS: tuple[str, ...] = ("source", "status")


def _make_reader(profile: Optional[str] = None) -> Any:
    from src.common.ducklake_reader_client import make_reader  # noqa: PLC0415

    return make_reader(profile=profile)


def _assert_rows_carry_keys(rows: list[dict[str, Any]], source: str, keys: tuple[str, ...]) -> None:
    for row in rows:
        missing = [k for k in keys if k not in row]
        if missing:
            raise RuntimeError(
                f"rec_episode.find_recs: row {row.get('id', '<unknown id>')!r} for source={source!r} "
                f"is missing filtered key(s) {missing} -- the read no longer projects a key this "
                "lookup depends on. Returning None here would be indistinguishable from 'no open "
                "rec' and would silently re-file a duplicate (rec-3291 / rec-3563)."
            )


def find_recs(
    source: str,
    *,
    status: str = "open",
    rows: Optional[list[dict[str, Any]]] = None,
    reader: Any = None,
    profile: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return every rec matching (source, status), via a scoped read.

    Production reads via `current_state("ops_recommendations", row_filter="source = '<source>'")`
    -- a structural single-key filter (never interpolated SQL), so only rows for `source` ever
    cross the boundary; `status` is filtered client-side because the reader has no compound
    row_filter. `rows` is the test-injection seam: when supplied, it is treated as if it were
    already the result of that scoped read (still asserted and status-filtered the same way), so
    a caller can hand a mixed-source fixture without special-casing test setup.

    Never catches a reader failure: an unreachable reader raises here, so a dedup read can never
    be mistaken for a genuinely empty result (a deliberate divergence from two of the three other
    current_state call sites in this repo that fail open -- see the module docstring).
    """
    live_rows = rows
    if live_rows is None:
        live_reader = reader if reader is not None else _make_reader(profile)
        live_rows = live_reader.current_state(_OPS_RECOMMENDATIONS_TABLE, row_filter=f"source = '{source}'")

    _assert_rows_carry_keys(live_rows, source, _BASE_FILTERED_KEYS)
    return [row for row in live_rows if row.get("source") == source and row.get("status") == status]


def find_rec(
    source: str,
    *,
    status: str = "open",
    sub_key: Optional[Callable[[dict[str, Any]], bool]] = None,
    sub_key_fields: tuple[str, ...] = (),
    rows: Optional[list[dict[str, Any]]] = None,
    reader: Any = None,
    profile: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return the single rec matching (source, status[, sub_key]), or None.

    `sub_key` narrows the (source, status) candidate set with an arbitrary client-side predicate
    (e.g. budget_ingest's (branch, phase) context-substring match) -- `sub_key_fields` names the
    keys that predicate reads, so a row missing one of them raises (the same anti-silent-None
    guarantee find_recs gives `source`/`status`) instead of the predicate quietly evaluating a
    default/absent value as a false match or non-match.
    """
    candidates = find_recs(source, status=status, rows=rows, reader=reader, profile=profile)
    if sub_key is None:
        return candidates[0] if candidates else None

    if sub_key_fields:
        missing_rows = [c.get("id", "<unknown id>") for c in candidates if any(k not in c for k in sub_key_fields)]
        if missing_rows:
            raise RuntimeError(
                f"rec_episode.find_rec: row(s) {missing_rows} for source={source!r} are missing "
                f"sub_key field(s) {sub_key_fields} the caller's predicate filters on."
            )

    matched = [c for c in candidates if sub_key(c)]
    return matched[0] if matched else None


def decide(*, over_threshold: bool, open_rec_exists: bool) -> str:
    """Return the action to take given trigger state and existing-rec state.

    Re-homed from scripts.convergence_health.assess.escalation_action (that module now re-exports
    this unchanged) -- the truth table itself is unchanged:

        "file"   -- new rec should be filed (over threshold, no open rec yet)
        "update" -- existing open rec should be updated (still over threshold)
        "close"  -- existing open rec should be closed (under threshold / green)
        "none"   -- nothing to do (under threshold, no open rec)
    """
    if over_threshold and not open_rec_exists:
        return "file"
    if over_threshold and open_rec_exists:
        return "update"
    if not over_threshold and open_rec_exists:
        return "close"
    return "none"


def run_episode(
    *,
    source: str,
    over_threshold: bool,
    build_fields: Callable[[], dict[str, Any]],
    build_update: Callable[[dict[str, Any]], Optional[dict[str, Any]]],
    build_close: Callable[[dict[str, Any]], dict[str, Any]],
    status: str = "open",
    sub_key: Optional[Callable[[dict[str, Any]], bool]] = None,
    sub_key_fields: tuple[str, ...] = (),
    suppress_file: bool = False,
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    rows: Optional[list[dict[str, Any]]] = None,
    reader: Any = None,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent file/update/close orchestration for one alarm/sensor episode.

    Looks up the existing episode via find_rec(source, status=status, sub_key=sub_key,
    sub_key_fields=sub_key_fields), decides the action via decide(), and dispatches to
    build_fields()/build_update(existing)/build_close(existing) -- the shape escalate() and the
    two code_drift sensors previously duplicated by hand.

    build_update returning None is a no-op update: the caller is signalling "nothing changed",
    so no update write happens (the caller would otherwise emit a duplicate SCD2 history row for
    an unchanged episode).

    suppress_file: True suppresses ONLY a fresh "file" action (escalate()'s reconcile_in_flight
    guard, T2.37 c4) -- an already-open rec still updates/closes normally; refreshing an existing
    rec is not a double-file.

    Returns {"action": "file"|"update"|"unchanged"|"close"|"none"|"skipped"|"skipped_suppressed",
    "rec_id": str|None}.
    """
    existing = find_rec(
        source,
        status=status,
        sub_key=sub_key,
        sub_key_fields=sub_key_fields,
        rows=rows,
        reader=reader,
        profile=profile,
    )
    action = decide(over_threshold=over_threshold, open_rec_exists=existing is not None)

    if action == "file" and suppress_file:
        return {"action": "skipped_suppressed", "rec_id": None}

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        fields = build_fields()
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        updates = build_update(existing)
        if updates is None:
            return {"action": "unchanged", "rec_id": existing["id"]}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        updates = build_close(existing)
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}  # pragma: no cover -- decide() is exhaustive


def main(argv: Optional[list[str]] = None) -> int:
    """Read-only CLI diagnostics: --probe <source> and --count. No destructive verb lives here --
    see scripts/rec_episode_dedupe.py for the one-time duplicate-rec cleanup.

        python -m scripts.rec_episode --probe <source> [--count] [--profile PROFILE]
    """
    args = list(argv if argv is not None else sys.argv[1:])
    if "--probe" not in args:
        print("usage: python -m scripts.rec_episode --probe <source> [--count] [--profile PROFILE]")
        return 2

    probe_idx = args.index("--probe")
    if probe_idx + 1 >= len(args):
        print("error: --probe requires a source argument")
        return 2
    source = args[probe_idx + 1]

    profile = None
    if "--profile" in args:
        profile_idx = args.index("--profile")
        if profile_idx + 1 < len(args):
            profile = args[profile_idx + 1]

    if "--count" in args:
        recs = find_recs(source, profile=profile)
        print(f"[rec_episode] {len(recs)} open rec(s) for source={source!r}")
        return 0

    rec = find_rec(source, profile=profile)
    if rec is None:
        print(f"[rec_episode] no open rec found for source={source!r}")
        return 1
    print(f"[rec_episode] matched rec {rec.get('id')!r} for source={source!r}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
