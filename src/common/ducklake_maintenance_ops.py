"""Fail-closed structural guards for the DuckLake GC pass (T2.18, Decision 188 amending Decision 81
clause 6 / CD.33 H1).

Replaces the retired file-fraction/byte-budget circuit breaker -- which failed OPEN on catalog
introspection error and whose file-fraction metric could not pass in steady state -- with four
guards whose healthy value is zero and whose failure mode is a raise, never a permissive default:

  G1 reachability    -- the would-delete set and the live set must be disjoint; checked before the
                         destructive calls and re-checked after.
  G2 retention floor -- re-asserts, from a fresh post-expiry read, that expire_snapshots actually
                         left at least SNAPSHOT_FLOOR snapshots (today nothing verifies the engine
                         honoured the Python-computed cutoff).
  G3 catalog sanity  -- aborts on an empty live set, or a live-byte drop past an absolute bound,
                         after the pass.
  G4 deletion bound  -- an absolute per-pass file-count/byte cap, sized from the caller's declared
                         size source (never the catalog live set -- rec-3871). A pass over the cap
                         DRAINS at the youngest cutoff that fits both caps (rec-3888's partial
                         drain) rather than deferring wholesale; if no cutoff at or above the grace
                         floor admits a positive count, the pass defers the WHOLE pass (nothing is
                         deleted this run) and reports the deferred count/bytes so the backlog
                         stays visible.

G1-G4's own predicates (assert_reachability / assert_retention_floor / assert_catalog_sane /
bound_deletions) are pure computations over already-collected paths/sizes/counts -- no connection,
no I/O -- so they are directly unit-testable. run_guarded_gc is the connection-owning orchestrator
that ducklake_maintenance.run_gc calls (via a function-local import -- see the note below).

Import-cycle note: this module imports ducklake_maintenance at module load (for
DuckLakeMaintenanceError and the introspection/primitive helpers). ducklake_maintenance.run_gc
imports THIS module back, but only inside its own function body (never at ducklake_maintenance's
module level), so the cycle never actually closes at import time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn

from src.common import ducklake_maintenance as maint

# G3/G4 absolute bounds (module-level constants -- tunable knobs, but NEVER relaxed to make a gate
# pass, Decision 55. Changing them requires a Decision superseding CD.33 / Decision 188).
G3_MAX_LIVE_BYTES_DROP: int = 50 * 1024 * 1024 * 1024  # 50 GiB
G4_MAX_DELETE_FILES: int = 20_000
G4_MAX_DELETE_BYTES: int = 10 * 1024 * 1024 * 1024  # 10 GiB -- the FP-A shipped number, now bounded

# The partial-drain walk (rec-3888): youngest-first grace ladder, bracketed then bisected to find
# the youngest cutoff (in days) that admits a positive count under both G4 caps. 7 is
# FILE_CLEANUP_GRACE_DAYS, the safety floor the walk never crosses.
_DRAIN_LADDER_DAYS: tuple[int, ...] = (7, 14, 30, 60, 90, 180, 365)
# ceil(log2(185)) = 8: the widest ladder bracket is (180, 365], a 185-day span, so 8 probes is the
# minimum that resolves every bracket to a single day (see the plan's probe-budget derivation).
_DRAIN_BISECT_PROBE_BUDGET: int = 8

# G1 breaker-probe forcing input (successor to the retired _BREAKER_PROBE_FILE_FRACTION /
# _BREAKER_PROBE_BYTE_BUDGET). An INTERNAL sentinel path, never an event field or contract
# parameter -- synthetically injected into BOTH the live and would-delete sets so the probe trips
# independently of the smoke catalog's real contents (a real catalog with zero deletable files
# must still trip this probe; docs/contracts/ducklake_maintenance.yaml declares breaker_probe out
# of contract scope, unchanged by this retirement).
G1_PROBE_FORCE_CONFLICT: str = "__gc_guard_probe_forced_conflict__"


def assert_reachability(
    live_paths: set[str],
    would_delete_paths: set[str],
    *,
    force_conflict: str | None = None,
) -> None:
    """G1: raise unless the would-delete set is disjoint from the live set.

    `force_conflict` synthetically injects one path into BOTH sets before checking -- the
    breaker_probe forcing mechanism (module constant G1_PROBE_FORCE_CONFLICT), guaranteeing a trip
    independent of the real catalog contents.
    """
    if force_conflict is not None:
        live_paths = live_paths | {force_conflict}
        would_delete_paths = would_delete_paths | {force_conflict}
    overlap = live_paths & would_delete_paths
    if overlap:
        sample = sorted(overlap)[:5]
        raise maint.DuckLakeMaintenanceError(
            f"G1 reachability violated: {sample} would be deleted while still live -- refusing to "
            "issue any destructive call (T2.18 / Decision 188). RCA before the next scheduled pass."
        )


def assert_retention_floor(remaining_snapshot_count: int, *, floor: int) -> None:
    """G2: re-assert, from a fresh post-expiry read, that at least `floor` snapshots remain.

    expire_snapshots computes its cutoff in Python from the requested floor; this guard verifies
    the engine actually honoured it instead of trusting the computation.
    """
    if remaining_snapshot_count < floor:
        raise maint.DuckLakeMaintenanceError(
            f"G2 retention floor violated: {remaining_snapshot_count} snapshot(s) remain after "
            f"expiry, below the floor of {floor} (T2.18 / Decision 188). expire_snapshots' cutoff "
            "computation did not match what the engine actually retained -- RCA before retrying."
        )


def assert_catalog_sane(
    live_paths_after: set[str],
    live_bytes_before: int,
    live_bytes_after: int,
    *,
    max_byte_drop: int = G3_MAX_LIVE_BYTES_DROP,
) -> None:
    """G3: abort on an empty live set, or a live-byte drop past an absolute bound.

    A maintenance pass that leaves NO live files, or removes more live-footprint bytes than any
    plausible weekly GC pass should, is a catalog-sanity failure -- not output to trust.
    """
    if not live_paths_after:
        raise maint.DuckLakeMaintenanceError(
            "G3 catalog sanity violated: the live file set is empty after the maintenance pass -- "
            "aborting rather than trusting an empty catalog read (T2.18 / Decision 188)."
        )
    dropped = live_bytes_before - live_bytes_after
    if dropped > max_byte_drop:
        raise maint.DuckLakeMaintenanceError(
            f"G3 catalog sanity violated: live bytes dropped by {dropped} (before={live_bytes_before}, "
            f"after={live_bytes_after}), exceeding the {max_byte_drop}-byte bound (T2.18 / Decision "
            "188). RCA the storage accumulation before the next scheduled pass -- do NOT raise the "
            "bound to pass."
        )


def size_candidates(
    paths: Iterable[str],
    size_source: dict[str, int],
    *,
    strict_sizes: bool,
) -> tuple[dict[str, int], int]:
    """Join would-delete `paths` against the caller's DECLARED `size_source` for G4's byte
    accounting -- never the catalog live set, which sizes every would-delete candidate to zero
    because a would-delete path is by definition already superseded/expired out of the catalog
    (rec-3871).

    `strict_sizes=True` raises DuckLakeMaintenanceError naming the first unsized path (of
    potentially several) -- no destructive path may silently size an unmeasurable candidate as 0
    (Decision 163: removing the exception path entirely, not an enumerated carve-out). Every
    destructive caller of run_guarded_gc uses this arm, unconditionally.

    `strict_sizes=False` sizes an unsized path as 0 and returns the count of how many were unsized
    instead of raising -- gc_ops's dry_run MEASUREMENT path is the one production consumer: a
    dry-run deletes nothing, so counting what could not be sized is correct there and a raise would
    make the pre-enablement canary unable to report what it exists to measure.
    """
    candidate_sizes: dict[str, int] = {}
    unsized: list[str] = []
    for path in paths:
        if path in size_source:
            candidate_sizes[path] = size_source[path]
        else:
            unsized.append(path)
    if unsized:
        if strict_sizes:
            raise maint.DuckLakeMaintenanceError(
                f"size_candidates: {unsized[0]!r} has no entry in the declared size source "
                f"({len(unsized)} unsized path(s) total) -- refusing to size a destructive "
                "candidate as 0 by omission (Decision 163 / Decision 193)."
            )
        for path in unsized:
            candidate_sizes[path] = 0
    return candidate_sizes, len(unsized)


@dataclass(frozen=True)
class DeletionBound:
    """G4 result: whether this pass proceeds, and the deferred remainder if it does not."""

    proceed: bool
    would_delete_files: int
    would_delete_bytes: int
    deferred_files: int
    deferred_bytes: int


def bound_deletions(
    candidate_sizes: dict[str, int],
    *,
    max_files: int = G4_MAX_DELETE_FILES,
    max_bytes: int = G4_MAX_DELETE_BYTES,
) -> DeletionBound:
    """G4: an absolute per-pass deletion bound, sized from the caller's real size map.

    `candidate_sizes` maps each would-delete path to its size in bytes -- the output of
    `size_candidates` joined against the caller's declared size source (a PRE-pass storage or live
    inventory snapshot; never a live inventory taken AFTER a prelude superseded the candidate,
    which is empty for it -- rec-3773's dead byte budget).

    Over budget: the caller drains partially (rec-3888) or, if nothing admits a positive count, the
    WHOLE pass is deferred (nothing is deleted this run) rather than a raise -- unlike a G1/G2/G3
    violation, a backlog is safe to leave for the next scheduled pass.
    """
    total_files = len(candidate_sizes)
    total_bytes = sum(candidate_sizes.values())
    if total_files <= max_files and total_bytes <= max_bytes:
        return DeletionBound(
            proceed=True,
            would_delete_files=total_files,
            would_delete_bytes=total_bytes,
            deferred_files=0,
            deferred_bytes=0,
        )
    return DeletionBound(
        proceed=False,
        would_delete_files=total_files,
        would_delete_bytes=total_bytes,
        deferred_files=total_files,
        deferred_bytes=total_bytes,
    )


def probe_g1_trip() -> NoReturn:
    """VP7 / smoke breaker_probe: force a guaranteed G1 trip, independent of catalog contents.

    Successor to the retired _BREAKER_PROBE_FILE_FRACTION / _BREAKER_PROBE_BYTE_BUDGET forcing
    parameters. Needs no connection and no catalog read -- G1_PROBE_FORCE_CONFLICT is synthetically
    injected into both sides of the reachability check, so this always raises regardless of
    whether the smoke catalog holds any deletable files (an empty smoke catalog must not let the
    probe no-op). Typed NoReturn: this function never returns normally.
    """
    assert_reachability(set(), set(), force_conflict=G1_PROBE_FORCE_CONFLICT)
    raise AssertionError("unreachable -- assert_reachability always raises when force_conflict is set")  # pragma: no cover


def _probe_dry_run_candidates(con: Any, catalog: str, now: datetime, days: int) -> set[str]:
    """A REAL re-probe of the dry-run cleanup/orphan candidate paths at an explicit `days` grace
    cutoff -- never a local sort of a previously-fetched set (both dry-run table functions return a
    single `path` column with no timestamp, so there is nothing to sort locally against)."""
    older_than = now - timedelta(days=days)
    return set(maint._dry_run_cleanup_paths(con, catalog, older_than) + maint._dry_run_orphan_paths(con, catalog, older_than))


@dataclass(frozen=True)
class _DrainProbe:
    """One re-probed rung/bisection point: the candidate set at `days` and its G4 evaluation."""

    days: int
    paths: set[str]
    sizes: dict[str, int]
    bound: DeletionBound


def _evaluate_cutoff(
    con: Any,
    catalog: str,
    now: datetime,
    days: int,
    candidate_size_source: dict[str, int],
    *,
    max_files: int,
    max_bytes: int,
) -> _DrainProbe:
    paths = _probe_dry_run_candidates(con, catalog, now, days)
    sizes, _unsized = size_candidates(paths, candidate_size_source, strict_sizes=True)
    bound = bound_deletions(sizes, max_files=max_files, max_bytes=max_bytes)
    return _DrainProbe(days=days, paths=paths, sizes=sizes, bound=bound)


def _drain_walk(
    con: Any,
    catalog: str,
    now: datetime,
    grace_days: int,
    candidate_size_source: dict[str, int],
    *,
    max_files: int,
    max_bytes: int,
) -> tuple[int | None, _DrainProbe | None]:
    """rec-3888: find the YOUNGEST cutoff (in days, at or above `grace_days`) that admits a POSITIVE
    candidate count under both G4 caps. Returns (selected_days, probe), or (None, None) when no
    such cutoff exists -- the pass must defer wholesale.

    THREE parts (called only when the `grace_days` cutoff itself is over budget):
      (i)   LADDER, youngest first, to bracket the boundary: the last rung that does NOT fit and
            the first rung that DOES.
      (ii)  BISECT inside that bracket (<= 8 probes -- enough to resolve the widest bracket,
            (180, 365], to a single day) for the exact youngest fitting day.
      (iii) REQUIRE A POSITIVE ADMITTED COUNT. A cutoff that fits only by admitting zero is not a
            drain (the anti-pattern rec-3871 named: an older cutoff admits fewer candidates, so
            "the oldest cutoff that fits" is trivially satisfied by deleting nothing) -- treated the
            same as no cutoff fitting at all.
    """
    ladder = [grace_days, *[d for d in _DRAIN_LADDER_DAYS if d > grace_days]]

    last_over_days: int | None = None
    fit: _DrainProbe | None = None
    for days in ladder:
        probe = _evaluate_cutoff(con, catalog, now, days, candidate_size_source, max_files=max_files, max_bytes=max_bytes)
        if probe.bound.proceed:
            fit = probe
            break
        last_over_days = days

    if fit is None:
        return None, None  # no ladder rung fits even at the oldest -- defer wholesale

    if last_over_days is not None:
        lo, hi = last_over_days, fit.days
        for _ in range(_DRAIN_BISECT_PROBE_BUDGET):
            if hi - lo <= 1:
                break
            mid = (lo + hi) // 2
            probe = _evaluate_cutoff(con, catalog, now, mid, candidate_size_source, max_files=max_files, max_bytes=max_bytes)
            if probe.bound.proceed:
                hi = mid
                fit = probe
            else:
                lo = mid

    if fit.bound.would_delete_files == 0:
        return None, None  # fits only by admitting zero -- not a drain (rec-3871's anti-pattern)

    return fit.days, fit


def run_guarded_gc(
    con: Any,
    tables: tuple[str, ...] | list[str],
    *,
    catalog: str,
    live_before: dict[str, int],
    grace_days: int,
    retain_days: int,
    floor: int,
    now: datetime,
    candidate_size_source: dict[str, int],
) -> dict[str, Any]:
    """Execute the destructive half of the GC pass (expire -> cleanup -> orphan) behind G1-G4.

    Called by ducklake_maintenance.run_gc AFTER flush_inlined_data + merge_adjacent_files.
    `live_before` is the live {path: size_bytes} inventory captured BEFORE those two calls ran --
    used by G3's byte-drop check. `candidate_size_source` (required, no default -- no destructive
    path may size a candidate as 0 by omission) is the caller's declared {path: size_bytes} source
    for G4's byte accounting -- always sized STRICT here; the caller's own dry-run measurement path
    is the only place a non-strict size_candidates call is legal.

    G4 evaluates the POST-EXPIRY candidate set (re-probed after expire_snapshots): on a
    never-expired catalog neither a pre-expiry bound nor a pre-expiry G1 check would cover what is
    actually deleted. An over-budget pass drains at the youngest cutoff that admits a positive
    count under both caps (rec-3888); if none does, it defers wholesale.

    Fail-closed: any catalog-introspection failure while collecting guard inputs raises
    DuckLakeMaintenanceError, never a permissive default (rec-3772 -- the retired breaker's bare
    `except Exception` swallowed exactly this failure and returned an all-clear result instead).
    """
    older_than_cleanup = now - timedelta(days=grace_days)

    try:
        live_now: dict[str, int] = {}
        for table in tables:
            live_now.update(maint._collect_file_paths(con, catalog, table))
        pre_expiry_would_delete_paths = set(
            maint._dry_run_cleanup_paths(con, catalog, older_than_cleanup)
            + maint._dry_run_orphan_paths(con, catalog, older_than_cleanup)
        )
    except maint.DuckLakeMaintenanceError:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
        raise maint.DuckLakeMaintenanceError(
            f"GC guard set: catalog introspection failed while collecting reachability inputs: {exc}"
        ) from exc

    expired = maint.expire_snapshots(con, catalog=catalog, retain_days=retain_days, floor=floor, _now=now)

    try:
        remaining_row = con.execute(f"SELECT count(*) FROM ducklake_snapshots('{catalog}')").fetchone()
        remaining_count = int(remaining_row[0]) if remaining_row else 0
    except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
        raise maint.DuckLakeMaintenanceError(f"GC guard set: could not re-read snapshot count for G2: {exc}") from exc
    assert_retention_floor(remaining_count, floor=floor)  # G2

    try:
        post_expiry_would_delete_paths = _probe_dry_run_candidates(con, catalog, now, grace_days)
    except maint.DuckLakeMaintenanceError:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
        raise maint.DuckLakeMaintenanceError(
            f"GC guard set: catalog introspection failed while re-probing the post-expiry candidate set: {exc}"
        ) from exc

    # G1 pre-check: the POST-EXPIRY set, against the REUSED pre-expiry live_now map -- expiry
    # retains the current snapshot and _collect_file_paths is current-snapshot scoped, so the live
    # set provably cannot change across expire_snapshots; a re-read would add a rescan for an
    # identical value.
    assert_reachability(set(live_now), post_expiry_would_delete_paths)

    full_sizes, _unsized = size_candidates(post_expiry_would_delete_paths, candidate_size_source, strict_sizes=True)
    # Read the module-level caps at call time (not via bound_deletions' own defaults, which are
    # bound at definition time) so this initial decision and the drain walk below always agree on
    # the same live caps -- both are then consistently overridable together (e.g. by a test).
    bound = bound_deletions(full_sizes, max_files=G4_MAX_DELETE_FILES, max_bytes=G4_MAX_DELETE_BYTES)

    drain_cutoff_days: int | None
    admitted_paths: set[str]
    admitted_sizes: dict[str, int]

    if bound.proceed:
        drain_cutoff_days = grace_days
        admitted_paths = post_expiry_would_delete_paths
        admitted_sizes = full_sizes
    else:
        try:
            selected_days, probe = _drain_walk(
                con,
                catalog,
                now,
                grace_days,
                candidate_size_source,
                max_files=G4_MAX_DELETE_FILES,
                max_bytes=G4_MAX_DELETE_BYTES,
            )
        except maint.DuckLakeMaintenanceError:
            raise
        except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
            raise maint.DuckLakeMaintenanceError(
                f"GC guard set: catalog introspection failed during the drain walk: {exc}"
            ) from exc
        if selected_days is None or probe is None:
            drain_cutoff_days = None
            admitted_paths = set()
            admitted_sizes = {}
        else:
            drain_cutoff_days = selected_days
            admitted_paths = probe.paths
            admitted_sizes = probe.sizes

    deferred_paths = post_expiry_would_delete_paths - admitted_paths
    deferred_bytes = sum(full_sizes[p] for p in deferred_paths)
    admitted_files = len(admitted_paths)
    admitted_bytes = sum(admitted_sizes.values())

    if admitted_paths:
        older_than = now - timedelta(days=drain_cutoff_days)  # type: ignore[arg-type]
        cleaned = maint.cleanup_old_files(con, catalog=catalog, grace_days=grace_days, older_than=older_than, _now=now)
        orphaned = maint.delete_orphaned_files(con, catalog=catalog, grace_days=grace_days, older_than=older_than, _now=now)
    else:
        cleaned = 0
        orphaned = 0

    try:
        live_after: dict[str, int] = {}
        for table in tables:
            live_after.update(maint._collect_file_paths(con, catalog, table))
    except maint.DuckLakeMaintenanceError:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
        raise maint.DuckLakeMaintenanceError(
            f"GC guard set: catalog introspection failed while collecting the post-pass live set for the "
            f"G1 re-check and G3: {exc}"
        ) from exc

    # G1 re-check: the ADMITTED set intersected with a fresh live_after read -- what was actually
    # deleted, which under a drain differs from the post-expiry set G4 decided against.
    assert_reachability(set(live_after), admitted_paths & set(live_after))
    assert_catalog_sane(set(live_after), sum(live_before.values()), sum(live_after.values()))  # G3

    return {
        "snapshots_expired": expired,
        "files_cleaned": cleaned,
        "orphans_deleted": orphaned,
        "guard_stats": {
            "pre_expiry_would_delete_candidates": len(pre_expiry_would_delete_paths),
            "post_expiry_would_delete_candidates": len(post_expiry_would_delete_paths),
            "g2_snapshots_remaining": remaining_count,
            "g4_would_delete_files": admitted_files,
            "g4_would_delete_bytes": admitted_bytes,
            "g4_deferred_files": len(deferred_paths),
            "g4_deferred_bytes": deferred_bytes,
            "g4_bounded": not bound.proceed,
            "g4_drain_cutoff_days": drain_cutoff_days,
        },
    }
