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
  G4 deletion bound  -- an absolute per-pass file-count/byte cap. A pass over the cap defers the
                         WHOLE pass (nothing is deleted this run) rather than raising, and reports
                         the deferred count/bytes so the backlog is visible.

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

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn

from src.common import ducklake_maintenance as maint

# G3/G4 absolute bounds (module-level constants -- tunable knobs, but NEVER relaxed to make a gate
# pass, Decision 55. Changing them requires a Decision superseding CD.33 / Decision 188).
G3_MAX_LIVE_BYTES_DROP: int = 50 * 1024 * 1024 * 1024  # 50 GiB
G4_MAX_DELETE_FILES: int = 20_000
G4_MAX_DELETE_BYTES: int = 10 * 1024 * 1024 * 1024  # 10 GiB -- the FP-A shipped number, now bounded

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


@dataclass(frozen=True)
class DeletionBound:
    """G4 result: whether this pass proceeds, and the deferred remainder if it does not."""

    proceed: bool
    would_delete_files: int
    would_delete_bytes: int
    deferred_files: int
    deferred_bytes: int


def bound_deletions(
    candidate_bytes: dict[str, int],
    *,
    max_files: int = G4_MAX_DELETE_FILES,
    max_bytes: int = G4_MAX_DELETE_BYTES,
) -> DeletionBound:
    """G4: an absolute per-pass deletion bound, sized from the caller's real byte map.

    `candidate_bytes` maps each would-delete path to its size in bytes, read from a PRE-pass live
    inventory snapshot captured before flush_inlined_data/merge_adjacent_files ran -- never from a
    live inventory taken AFTER those calls, which is empty for any path they just superseded
    (rec-3773's dead byte budget: the retired breaker joined would-delete paths against a
    POST-merge live map, where every one of them was already absent).

    Over budget: the WHOLE pass is deferred (nothing is deleted this run) rather than a raise --
    unlike a G1/G2/G3 violation, a backlog is safe to leave for the next scheduled pass.
    """
    total_files = len(candidate_bytes)
    total_bytes = sum(candidate_bytes.values())
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
) -> dict[str, Any]:
    """Execute the destructive half of the GC pass (expire -> cleanup -> orphan) behind G1-G4.

    Called by ducklake_maintenance.run_gc AFTER flush_inlined_data + merge_adjacent_files.
    `live_before` is the live {path: size_bytes} inventory captured BEFORE those two calls ran --
    the size source G4 needs (see bound_deletions).

    Fail-closed: any catalog-introspection failure while collecting guard inputs raises
    DuckLakeMaintenanceError, never a permissive default (rec-3772 -- the retired breaker's bare
    `except Exception` swallowed exactly this failure and returned an all-clear result instead).
    """
    older_than_cleanup = now - timedelta(days=grace_days)

    try:
        live_now: dict[str, int] = {}
        for table in tables:
            live_now.update(maint._collect_file_paths(con, catalog, table))
        would_delete_paths = set(
            maint._dry_run_cleanup_paths(con, catalog, older_than_cleanup)
            + maint._dry_run_orphan_paths(con, catalog, older_than_cleanup)
        )
    except maint.DuckLakeMaintenanceError:
        raise
    except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
        raise maint.DuckLakeMaintenanceError(
            f"GC guard set: catalog introspection failed while collecting reachability inputs: {exc}"
        ) from exc

    assert_reachability(set(live_now), would_delete_paths)  # G1 pre-check

    expired = maint.expire_snapshots(con, catalog=catalog, retain_days=retain_days, floor=floor, _now=now)

    try:
        remaining_row = con.execute(f"SELECT count(*) FROM ducklake_snapshots('{catalog}')").fetchone()
        remaining_count = int(remaining_row[0]) if remaining_row else 0
    except Exception as exc:  # noqa: BLE001 -- fail-closed re-raise, never a permissive default (rec-3772)
        raise maint.DuckLakeMaintenanceError(f"GC guard set: could not re-read snapshot count for G2: {exc}") from exc
    assert_retention_floor(remaining_count, floor=floor)  # G2

    candidate_bytes = {path: live_before.get(path, 0) for path in would_delete_paths}
    bound = bound_deletions(candidate_bytes)  # G4

    if bound.proceed:
        cleaned = maint.cleanup_old_files(con, catalog=catalog, grace_days=grace_days, _now=now)
        orphaned = maint.delete_orphaned_files(con, catalog=catalog, grace_days=grace_days, _now=now)
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

    assert_reachability(set(live_after), would_delete_paths & set(live_after))  # G1 re-check
    assert_catalog_sane(set(live_after), sum(live_before.values()), sum(live_after.values()))  # G3

    return {
        "snapshots_expired": expired,
        "files_cleaned": cleaned,
        "orphans_deleted": orphaned,
        "guard_stats": {
            "g1_would_delete_candidates": len(would_delete_paths),
            "g2_snapshots_remaining": remaining_count,
            "g4_would_delete_files": bound.would_delete_files,
            "g4_would_delete_bytes": bound.would_delete_bytes,
            "g4_deferred_files": bound.deferred_files,
            "g4_deferred_bytes": bound.deferred_bytes,
            "g4_bounded": not bound.proceed,
        },
    }
