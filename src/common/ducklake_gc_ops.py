"""Production destructive-GC pass body (T2.18, docs/plans/PLAN-production-gc-and-storage-stability.yaml).

Split out of src/lambdas/ducklake_maintenance/handler.py (Decision 128 decompose-by-default: the
handler is at 458 of 500 SLOC with no budget entry, and this pass body alone exceeds
action_merge_ops's ~110 SLOC).

Five properties are load-bearing:

1. UNIVERSAL LIVE SET. The live-file inventory feeding G1/G3 and `referenced_missing` enumerates
   EVERY table catalog enumeration returns, UNCONDITIONALLY -- never derived from
   scope.resolve_scope, and no policy input reaches it. The destructive verbs
   (expire_snapshots/cleanup_old_files/delete_orphaned_files) are catalog-wide, so filtering the
   live set would not narrow what gets deleted -- it would narrow what the guards can SEE (the
   guard-blindness regression this plan's own critique found).
2. NO PER-TABLE PRELUDE. flush_inlined_data is a documented guaranteed no-op (inlining disabled at
   the connection level) and merge_adjacent_files already runs on every ops table every 6h via
   action_merge_ops -- 28x/week against this pass's 1x/week. One verb, one job: merge_ops compacts,
   gc_ops reclaims.
3. `run_guarded_gc` is called UNMODIFIED -- this module changes no shipped guard code. G4's byte
   half is INERT for a no-prelude pass (a would-delete path is absent from live_before only when a
   prelude superseded it first), so the file-count half is the only binding cap here; see
   rec-3871.
4. READ ORDERING IS LOAD-BEARING: the CATALOG live set is collected FIRST and STORAGE is listed
   SECOND. In that order an interleaved write shows up as a spurious ORPHAN (harmless to
   `referenced_missing`); the reverse order manufactures a spurious REFERENCED-MISSING, which would
   trip the safety gate on a race rather than on a real defect.
5. The complete metric set every verification step depends on is emitted into the
   DuckLakeMaintenance CloudWatch namespace, with GcReferencedMissing emitted BEFORE the
   referenced-missing raise -- an unemitted metric reads ABSENT, not breached, which is the worst
   failure shape for a guard whose whole job is to be noticed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.common import ducklake_gc_verification as gcver
from src.common import ducklake_maintenance as maint
from src.common import ducklake_maintenance_ops as guard

MetricSink = Callable[[str, float], None]
StorageLister = Callable[[str], dict[str, int]]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_s3_uri(data_path: str) -> tuple[str, str]:
    if not data_path.startswith("s3://"):
        raise maint.DuckLakeMaintenanceError(f"gc_ops: data_path must be an s3:// URI, got {data_path!r}")
    without_scheme = data_path[len("s3://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise maint.DuckLakeMaintenanceError(f"gc_ops: data_path {data_path!r} carries no bucket")
    return bucket, prefix


def _default_list_storage(data_path: str, *, client: Any = None) -> dict[str, int]:
    """ListObjectsV2 walk of the production prefix -- the managed-primitive storage-side source for
    `referenced_missing` (Decision 100: no client-tooling substitution for a managed primitive).

    Returns {s3://bucket/key: size_bytes}, the same path shape DuckLake's own `data_file` column
    uses, so the result compares directly against the catalog live-set paths.
    """
    import boto3  # noqa: PLC0415

    bucket, prefix = _parse_s3_uri(data_path)
    s3 = client if client is not None else boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    paths: dict[str, int] = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            paths[f"s3://{bucket}/{obj['Key']}"] = int(obj.get("Size", 0))
    return paths


def _discover_all_tables(con: Any, catalog: str) -> list[str]:
    """Enumerate EVERY table in the catalog via unfiltered information_schema -- no naming-convention
    predicate, no policy input. Mirrors action_merge_ops's own discovery query."""
    rows = con.execute(
        f"SELECT table_name FROM information_schema.tables WHERE table_catalog = '{catalog}' ORDER BY table_name"
    ).fetchall()
    discovered = [r[0] for r in rows]
    if not discovered:
        raise maint.DuckLakeMaintenanceError(
            "gc_ops: no tables discovered in the catalog -- verify data_path and meta_schema point "
            "at the production DuckLake (ducklake_ops @ s3://.../ducklake/)"
        )
    return discovered


def _current_snapshot_id(con: Any, catalog: str) -> int:
    """The pass-start CATALOG snapshot id -- captured BEFORE any destructive call. Snapshot identity
    is catalog-level, so this one id covers every table for verify_read_path."""
    row = con.execute(
        f"SELECT snapshot_id FROM ducklake_snapshots('{catalog}') ORDER BY snapshot_time DESC LIMIT 1"
    ).fetchone()
    if not row or row[0] is None:
        raise maint.DuckLakeMaintenanceError(f"gc_ops: could not determine the pass-start snapshot id for catalog {catalog!r}")
    return int(row[0])


def gc_ops(
    con: Any,
    *,
    catalog: str,
    data_path: str,
    dry_run: bool = False,
    grace_days: int = maint.FILE_CLEANUP_GRACE_DAYS,
    retain_days: int = maint.SNAPSHOT_RETAIN_DAYS,
    floor: int = maint.SNAPSHOT_FLOOR,
    now: datetime | None = None,
    metric_sink: MetricSink | None = None,
    list_storage: StorageLister | None = None,
) -> dict[str, Any]:
    """The production destructive-GC pass. See module docstring for the five load-bearing properties.

    `dry_run=True` performs NO deletion and NO write of any kind: it still emits GcReferencedMissing
    and GcWouldDeleteFiles (the read-only baseline gate), computed from the read-only dry-run
    primitives already provided by src.common.ducklake_maintenance.
    """
    now = now or _now_utc()
    metric_sink = metric_sink or (lambda _name, _value: None)
    list_storage = list_storage or _default_list_storage

    tables = _discover_all_tables(con, catalog)

    # Pass-start CATALOG snapshot id, captured before any destructive call (property: snapshot
    # identity is catalog-level -- one id for the whole pass, never one per table).
    snapshot_id = _current_snapshot_id(con, catalog)

    # Property 2: NO per-table prelude (no flush_inlined_data, no merge_adjacent_files). This IS
    # live_before for both G4's byte-sizing and the dry-run would-delete accounting below --
    # because there is no prelude, "before" and "current" are the same read.
    live_before: dict[str, int] = {}
    for table in tables:
        live_before.update(maint._collect_file_paths(con, catalog, table))

    older_than_cleanup = now - timedelta(days=grace_days)
    would_delete_paths = set(
        maint._dry_run_cleanup_paths(con, catalog, older_than_cleanup)
        + maint._dry_run_orphan_paths(con, catalog, older_than_cleanup)
    )
    would_delete_bytes_map = {p: live_before.get(p, 0) for p in would_delete_paths}
    would_delete_files = len(would_delete_paths)
    would_delete_bytes = sum(would_delete_bytes_map.values())
    metric_sink("GcWouldDeleteFiles", float(would_delete_files))

    guard_stats: dict[str, Any] | None = None
    snapshots_expired = files_cleaned = orphans_deleted = 0

    if not dry_run:
        # Property 3: run_guarded_gc UNMODIFIED. `tables` here serves ONLY the guard live-set
        # collection inside run_guarded_gc -- gc_ops never inherits run_gc's dual-purpose (prelude +
        # guard live set) use of the same argument, because gc_ops has no prelude to begin with.
        guard_result = guard.run_guarded_gc(
            con,
            tables,
            catalog=catalog,
            live_before=live_before,
            grace_days=grace_days,
            retain_days=retain_days,
            floor=floor,
            now=now,
        )
        snapshots_expired = guard_result["snapshots_expired"]
        files_cleaned = guard_result["files_cleaned"]
        orphans_deleted = guard_result["orphans_deleted"]
        guard_stats = guard_result["guard_stats"]
        metric_sink("GcSnapshotsRetainedMin", float(guard_stats["g2_snapshots_remaining"]))
        metric_sink("GcDeletedSnapshots", float(snapshots_expired))
        metric_sink("GcDeletedFiles", float(files_cleaned))
        metric_sink("GcDeletedOrphans", float(orphans_deleted))

    # Property 1 + 4: universal live-set re-collection (post-pass in a real run; unchanged in
    # dry_run since nothing destructive ran) over EVERY table, then storage SECOND (read-ordering).
    live_now: dict[str, int] = {}
    for table in tables:
        live_now.update(maint._collect_file_paths(con, catalog, table))
    storage_paths = list_storage(data_path)

    missing = gcver.referenced_missing(set(live_now), set(storage_paths))
    # Property 5: GcReferencedMissing is emitted BEFORE the referenced-missing raise below.
    metric_sink("GcReferencedMissing", float(len(missing)))

    live_bytes = sum(live_now.values())
    storage_bytes = sum(storage_paths.values())
    debt_ratio = gcver.gc_debt_ratio(storage_bytes, live_bytes) if live_bytes > 0 else 0.0
    metric_sink("GcDebtRatio", debt_ratio)
    metric_sink("GcDebtBytes", float(storage_bytes - live_bytes))
    metric_sink("GcStorageObjects", float(len(storage_paths)))

    if missing:
        raise maint.DuckLakeMaintenanceError(
            f"gc_ops: referenced_missing non-empty ({len(missing)} path(s)) -- sample: "
            f"{sorted(missing)[:5]}. Over-reclaim signal -- refusing to treat this pass as safe; "
            "RCA before the next scheduled pass (T2.18 / production-gc-and-storage-stability)."
        )

    read_path: dict[str, dict[str, Any]] | None = None
    if not dry_run:
        read_path = gcver.verify_read_path(con, snapshot_id, tables, catalog=catalog)

    return {
        "ok": True,
        "action": "gc_ops",
        "dry_run": dry_run,
        "tables": list(tables),
        "snapshot_id": snapshot_id,
        "would_delete_files": would_delete_files,
        "would_delete_bytes": would_delete_bytes,
        "referenced_missing": len(missing),
        "snapshots_expired": snapshots_expired,
        "files_cleaned": files_cleaned,
        "orphans_deleted": orphans_deleted,
        "guard_stats": guard_stats,
        "debt_ratio": debt_ratio,
        "storage_bytes": storage_bytes,
        "live_bytes": live_bytes,
        "storage_objects": len(storage_paths),
        "read_path": read_path,
    }
