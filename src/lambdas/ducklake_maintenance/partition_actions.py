"""Decision 204 partition-layout maintenance verbs (PLAN-ducklake-partition-layout-remediation).

Two OPERATIONAL, admin-only actions on the ducklake_maintenance function -- invoked over 443 via
`aws lambda invoke` (never a public Function URL, never an agent surface reachable from CI or
PlatformDev), and only by an ADMIN-container agent under explicit human direction (Decision 204
amending Decision 126/151 cl.2/143 cl.2):

  - action_reconcile_partitions: reads every reconcile_partitions-scoped table's live-vs-declared
    partition layout; dry_run=true (default) reports drift only; dry_run=false ALTERs every
    drifted table then RE-READS (never a pre-ALTER readout, which a concurrent writer commit
    could make immediately stale).
  - action_rewrite_partition_layout: refuses unless confirm == table (catalog_reinit's guard
    shape) and the table's rewrite_partition_layout policy cell applies; re-lays that table's
    legacy-scheme files and returns rewrite_legacy_layout's proof body verbatim.

Both raise only DuckLakeRuntimeError subclasses -- scope.resolve_scope's
DuckLakeMaintenanceScopeError (a bare RuntimeError) is wrapped in PartitionLayoutError -- so
handler.py's existing exception mapping yields structured 500s for either verb.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.common import ducklake_maintenance as maint
from src.common import ducklake_maintenance_scope as scope
from src.common import ducklake_partition_layout as layout_mod
from src.common import ducklake_partition_rewrite as rewrite_mod
from src.common import ducklake_runtime as rt
from src.lambdas.ducklake_maintenance._shared import EXTENSION_DIRECTORY, _require_data_path, _require_identifier


def _open_event_connection(event: dict[str, Any], *, action: str) -> tuple[Any, str]:
    """Shared no-arg-refused guard + connection open for both partition verbs.

    Returns (connection, meta_schema). A no-arg invoke (missing data_path or meta_schema) is
    refused before any connection is attempted (Decision 84/81 destructive-action guard)."""
    data_path = _require_data_path(event.get("data_path"))
    raw_schema = event.get("meta_schema")
    if not raw_schema:
        raise rt.DuckLakeRuntimeError(f"{action} requires an explicit 'meta_schema' -- no default production schema")
    meta_schema = _require_identifier(raw_schema)
    con = rt.open_connection(
        dsn=rt.fetch_dsn(), data_path=data_path, meta_schema=meta_schema, extension_directory=EXTENSION_DIRECTORY
    )
    return con, meta_schema


def _skipped_with_readonly_evidence(
    resolution: scope.ScopeResolution, all_layouts: dict[str, Any], semantics: dict[str, Any]
) -> list[dict[str, Any]]:
    """Enrich resolution.skipped with each table's READ-ONLY live layout + declared-spec drift
    (or null) -- reported, never ALTERed, so the readout accounts for every discovered table."""
    if not resolution.skipped:
        return []
    skipped_names = {s["table"] for s in resolution.skipped}
    skipped_layouts = {k: v for k, v in all_layouts.items() if k in skipped_names}
    drift_by_table = {d.physical: d for d in layout_mod.compare_to_declared(skipped_layouts, semantics=semantics)}
    return [
        {
            **s,
            "layout": asdict(skipped_layouts[s["table"]]) if s["table"] in skipped_layouts else None,
            "drift": asdict(drift_by_table[s["table"]]) if s["table"] in drift_by_table else None,
        }
        for s in resolution.skipped
    ]


def action_reconcile_partitions(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Report (dry_run=true, default) or apply (dry_run=false) every reconcile_partitions-scoped
    table's live-vs-declared partition ALTER. Returns {layouts, drifts, skipped} for a dry run, or
    {altered, layouts, drifts, skipped} for an apply -- layouts/drifts AFTER any ALTER, never
    before (a pre-ALTER readout would misreport a benign post-ALTER writer commit as drift);
    `skipped` names every reconcile_partitions-scoped-out table (e.g. smoke_harness) with its
    read-only layout and drift -- never ALTERed or re-laid."""
    con, _meta_schema = _open_event_connection(event, action="reconcile_partitions")
    dry_run = event.get("dry_run", True)
    try:
        semantics = rt.load_field_semantics()
        registry = scope.build_registry(semantics)
        policy = scope.load_policy(semantics)

        rows = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog = ? ORDER BY table_name",
            [maint.CATALOG_ALIAS],
        ).fetchall()
        discovered = [r[0] for r in rows]
        try:
            resolution = scope.resolve_scope(discovered, verb="reconcile_partitions", policy=policy, registry=registry)
        except scope.DuckLakeMaintenanceScopeError as exc:
            raise layout_mod.PartitionLayoutError(f"reconcile_partitions scope resolution failed: {exc}") from exc

        def _scoped_layouts_and_drifts(all_layouts: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
            scoped = {k: v for k, v in all_layouts.items() if k in resolution.to_merge}
            return scoped, layout_mod.compare_to_declared(scoped, semantics=semantics)

        if dry_run:
            all_layouts = layout_mod.read_partition_layout(con, catalog_alias=maint.CATALOG_ALIAS, semantics=semantics)
            layouts, drifts = _scoped_layouts_and_drifts(all_layouts)
            skipped = _skipped_with_readonly_evidence(resolution, all_layouts, semantics)
            return {
                "layouts": {k: asdict(v) for k, v in layouts.items()},
                "drifts": [asdict(d) for d in drifts],
                "skipped": skipped,
            }

        pre_layouts = layout_mod.read_partition_layout(con, catalog_alias=maint.CATALOG_ALIAS, semantics=semantics)
        _, drifts = _scoped_layouts_and_drifts(pre_layouts)
        altered = rewrite_mod.alter_to_declared(con, drifts, catalog_alias=maint.CATALOG_ALIAS)
        post_all_layouts = layout_mod.read_partition_layout(con, catalog_alias=maint.CATALOG_ALIAS, semantics=semantics)
        post_layouts, post_drifts = _scoped_layouts_and_drifts(post_all_layouts)
        skipped = _skipped_with_readonly_evidence(resolution, post_all_layouts, semantics)
        return {
            "altered": altered,
            "layouts": {k: asdict(v) for k, v in post_layouts.items()},
            "drifts": [asdict(d) for d in post_drifts],
            "skipped": skipped,
        }
    finally:
        con.close()


def action_rewrite_partition_layout(event: dict[str, Any], _con: Any) -> dict[str, Any]:
    """Re-lay one table's legacy-scheme files. Refuses unless confirm == table (catalog_reinit's
    destructive-action guard shape) and the table's own rewrite_partition_layout policy cell
    applies. Returns rewrite_legacy_layout's proof body verbatim."""
    table = event.get("table")
    if not table or event.get("confirm") != table:
        raise rt.DuckLakeRuntimeError(
            f"rewrite_partition_layout is destructive-until-snapshot-expiry for table {table!r}: "
            f"pass confirm={table!r} to proceed"
        )
    con, _meta_schema = _open_event_connection(event, action="rewrite_partition_layout")
    try:
        semantics = rt.load_field_semantics()
        registry = scope.build_registry(semantics)
        policy = scope.load_policy(semantics)
        try:
            resolution = scope.resolve_scope([table], verb="rewrite_partition_layout", policy=policy, registry=registry)
        except scope.DuckLakeMaintenanceScopeError as exc:
            raise layout_mod.PartitionLayoutError(f"rewrite_partition_layout scope resolution failed: {exc}") from exc

        if resolution.unclassified:
            raise layout_mod.PartitionLayoutError(f"{table!r} is not a classified table in the field_semantics registry")
        if table not in resolution.to_merge:
            reason = next(
                (s["reason"] for s in resolution.skipped if s["table"] == table), "excluded by the maintenance policy matrix"
            )
            raise rewrite_mod.PartitionRewriteError(f"{table!r} refuses rewrite_partition_layout: {reason}")

        return rewrite_mod.rewrite_legacy_layout(con, table, catalog_alias=maint.CATALOG_ALIAS, semantics=semantics)
    finally:
        con.close()
