"""MIRROR for src/lambdas/ducklake_maintenance/partition_actions.py (Decision 204,
PLAN-ducklake-partition-layout-remediation).

Mirror test: no-arg refusal, dry_run default, confirm mismatch refused, control-class rewrite
refused by its policy cell, a resolve_scope DuckLakeMaintenanceScopeError wrapped in
PartitionLayoutError, dry_run=false returning the post-ALTER re-read (not the pre-ALTER readout),
DuckLakeRuntimeError subclasses surface as structured 500s, responses pass through.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.lambdas.ducklake_maintenance.partition_actions as pa
from src.common import ducklake_maintenance_scope as scope
from src.common.ducklake_partition_layout import PartitionLayoutError, TableLayout
from src.common.ducklake_partition_rewrite import PartitionRewriteError
from src.common.ducklake_runtime import DuckLakeRuntimeError

pytestmark = pytest.mark.unit

_FULL_DSN = {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}


def _con() -> MagicMock:
    con = MagicMock()
    con.execute.return_value.fetchall.return_value = [("ops_recommendations_history",)]
    return con


def _layout(**overrides) -> TableLayout:
    base = {
        "physical": "ops_recommendations_history",
        "table_class": "scd2",
        "live_transforms": (("day", "created_timestamp"),),
        "active_scheme_id": 1,
        "live_files": 3,
        "legacy_scheme_files": 3,
    }
    base.update(overrides)
    return TableLayout(**base)


# ---------------------------------------------------------------------------
# action_reconcile_partitions -- no-arg refusal
# ---------------------------------------------------------------------------


def test_reconcile_partitions_refuses_missing_data_path():
    with pytest.raises(DuckLakeRuntimeError, match="data_path"):
        pa.action_reconcile_partitions({"meta_schema": "ducklake_ops"}, None)


def test_reconcile_partitions_refuses_missing_meta_schema():
    with pytest.raises(DuckLakeRuntimeError, match="meta_schema"):
        pa.action_reconcile_partitions({"data_path": "s3://b/ducklake/"}, None)


# ---------------------------------------------------------------------------
# action_reconcile_partitions -- dry_run default and behavior
# ---------------------------------------------------------------------------


def test_reconcile_partitions_dry_run_defaults_true_and_never_alters():
    con = _con()
    layouts = {"ops_recommendations_history": _layout()}
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", return_value=scope.ScopeResolution(("ops_recommendations_history",), (), ())),
        patch.object(pa.layout_mod, "read_partition_layout", return_value=layouts),
        patch.object(pa.layout_mod, "compare_to_declared", return_value=[]),
        patch.object(pa.rewrite_mod, "alter_to_declared") as mock_alter,
    ):
        result = pa.action_reconcile_partitions({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    mock_alter.assert_not_called()
    assert set(result) == {"layouts", "drifts", "skipped"}
    assert result["layouts"]["ops_recommendations_history"]["physical"] == "ops_recommendations_history"
    assert result["skipped"] == []
    assert con.close.called


def test_reconcile_partitions_scopes_layouts_to_resolution_to_merge():
    con = _con()
    layouts = {
        "ops_recommendations_history": _layout(),
        "ops_smoke_events_history": _layout(physical="ops_smoke_events_history", table_class="append_only"),
    }
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", return_value=scope.ScopeResolution(("ops_recommendations_history",), (), ())),
        patch.object(pa.layout_mod, "read_partition_layout", return_value=layouts),
        patch.object(pa.layout_mod, "compare_to_declared", return_value=[]) as mock_compare,
    ):
        result = pa.action_reconcile_partitions({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    assert set(result["layouts"]) == {"ops_recommendations_history"}
    scoped_arg = mock_compare.call_args.args[0]
    assert set(scoped_arg) == {"ops_recommendations_history"}


def test_reconcile_partitions_dry_run_false_returns_post_alter_readout_not_pre_alter():
    con = _con()
    pre_alter_layout = _layout(legacy_scheme_files=3)
    post_alter_layout = _layout(legacy_scheme_files=0)
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", return_value=scope.ScopeResolution(("ops_recommendations_history",), (), ())),
        patch.object(
            pa.layout_mod,
            "read_partition_layout",
            side_effect=[
                {"ops_recommendations_history": pre_alter_layout},
                {"ops_recommendations_history": post_alter_layout},
            ],
        ),
        patch.object(pa.layout_mod, "compare_to_declared", return_value=[]),
        patch.object(pa.rewrite_mod, "alter_to_declared", return_value=["ops_recommendations_history"]) as mock_alter,
    ):
        result = pa.action_reconcile_partitions(
            {"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops", "dry_run": False}, None
        )

    mock_alter.assert_called_once()
    assert result["altered"] == ["ops_recommendations_history"]
    # The returned readout is the POST-alter layout (legacy_scheme_files == 0), never the pre-alter one.
    assert result["layouts"]["ops_recommendations_history"]["legacy_scheme_files"] == 0


def test_reconcile_partitions_reports_skipped_tables_read_only():
    con = _con()
    layouts = {
        "ops_recommendations_history": _layout(),
        "ducklake_smoke_history": _layout(physical="ducklake_smoke_history", table_class="smoke_harness"),
    }
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(
            pa.scope,
            "resolve_scope",
            return_value=scope.ScopeResolution(
                ("ops_recommendations_history",),
                (
                    {
                        "table": "ducklake_smoke_history",
                        "table_class": "smoke_harness",
                        "reason": "owned by create_scd2_tables force_recreate",
                    },
                ),
                (),
            ),
        ),
        patch.object(pa.layout_mod, "read_partition_layout", return_value=layouts),
        patch.object(pa.layout_mod, "compare_to_declared", return_value=[]) as mock_compare,
        patch.object(pa.rewrite_mod, "alter_to_declared") as mock_alter,
    ):
        result = pa.action_reconcile_partitions({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)

    mock_alter.assert_not_called()
    assert set(result) == {"layouts", "drifts", "skipped"}
    assert set(result["layouts"]) == {"ops_recommendations_history"}
    assert len(result["skipped"]) == 1
    skipped_entry = result["skipped"][0]
    assert skipped_entry["table"] == "ducklake_smoke_history"
    assert skipped_entry["table_class"] == "smoke_harness"
    assert skipped_entry["reason"] == "owned by create_scd2_tables force_recreate"
    assert skipped_entry["layout"]["physical"] == "ducklake_smoke_history"
    assert skipped_entry["drift"] is None  # compare_to_declared mocked to return no drift
    # Never ALTERed or fed into the to_merge-scoped compare_to_declared call.
    scoped_args = [set(call.args[0]) for call in mock_compare.call_args_list]
    assert {"ops_recommendations_history"} in scoped_args
    assert {"ducklake_smoke_history"} in scoped_args


def test_reconcile_partitions_wraps_scope_error():
    con = _con()
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", side_effect=scope.DuckLakeMaintenanceScopeError("matrix broken")),
    ):
        with pytest.raises(PartitionLayoutError, match="matrix broken"):
            pa.action_reconcile_partitions({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)
    assert con.close.called


# ---------------------------------------------------------------------------
# action_rewrite_partition_layout -- refusals
# ---------------------------------------------------------------------------


def test_rewrite_refuses_missing_table():
    with pytest.raises(DuckLakeRuntimeError, match="destructive-until-snapshot-expiry"):
        pa.action_rewrite_partition_layout({"data_path": "s3://b/ducklake/", "meta_schema": "ducklake_ops"}, None)


def test_rewrite_refuses_confirm_mismatch():
    with pytest.raises(DuckLakeRuntimeError, match="destructive-until-snapshot-expiry"):
        pa.action_rewrite_partition_layout(
            {
                "data_path": "s3://b/ducklake/",
                "meta_schema": "ducklake_ops",
                "table": "ops_recommendations_history",
                "confirm": "wrong",
            },
            None,
        )


def test_rewrite_refuses_control_class_table_via_policy_cell():
    con = _con()
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(
            pa.scope,
            "resolve_scope",
            return_value=scope.ScopeResolution(
                (),
                ({"table": "ops_entity_counters", "table_class": "control", "reason": "entity-id counter, never re-laid"},),
                (),
            ),
        ),
    ):
        with pytest.raises(PartitionRewriteError, match="entity-id counter"):
            pa.action_rewrite_partition_layout(
                {
                    "data_path": "s3://b/ducklake/",
                    "meta_schema": "ducklake_ops",
                    "table": "ops_entity_counters",
                    "confirm": "ops_entity_counters",
                },
                None,
            )
    assert con.close.called


def test_rewrite_refuses_smoke_harness_table_via_policy_cell():
    """Binds the SHIPPED smoke_harness rewrite_partition_layout policy cell to the action -- loads
    the real generated field_semantics.yaml (never a mocked resolve_scope), so this fails if the
    sidecar's smoke_harness row is ever edited or dropped without this action also refusing."""
    con = _con()
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
    ):
        with pytest.raises(PartitionRewriteError):
            pa.action_rewrite_partition_layout(
                {
                    "data_path": "s3://b/ducklake/",
                    "meta_schema": "ducklake_ops",
                    "table": "ducklake_smoke_history",
                    "confirm": "ducklake_smoke_history",
                },
                None,
            )
    assert con.close.called


def test_rewrite_refuses_unclassified_table():
    con = _con()
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", return_value=scope.ScopeResolution((), (), ("a_stray_table",))),
    ):
        with pytest.raises(PartitionLayoutError, match="not a classified table"):
            pa.action_rewrite_partition_layout(
                {
                    "data_path": "s3://b/ducklake/",
                    "meta_schema": "ducklake_ops",
                    "table": "a_stray_table",
                    "confirm": "a_stray_table",
                },
                None,
            )


def test_rewrite_wraps_scope_error():
    con = _con()
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", side_effect=scope.DuckLakeMaintenanceScopeError("matrix broken")),
    ):
        with pytest.raises(PartitionLayoutError, match="matrix broken"):
            pa.action_rewrite_partition_layout(
                {
                    "data_path": "s3://b/ducklake/",
                    "meta_schema": "ducklake_ops",
                    "table": "ops_recommendations_history",
                    "confirm": "ops_recommendations_history",
                },
                None,
            )


# ---------------------------------------------------------------------------
# action_rewrite_partition_layout -- happy path returns rewrite_legacy_layout's result verbatim
# ---------------------------------------------------------------------------


def test_rewrite_returns_rewrite_legacy_layout_result_verbatim():
    con = _con()
    proof = {
        "physical": "ops_recommendations_history",
        "pre_snapshot_id": 10,
        "commit_snapshot_id": 11,
        "rows_pre": 3,
        "rows_commit": 3,
        "digest_pre": "D",
        "digest_commit": "D",
        "files_before": 3,
        "files_after": 3,
        "attempts": 1,
    }
    with (
        patch.object(pa.rt, "fetch_dsn", return_value=_FULL_DSN),
        patch.object(pa.rt, "open_connection", return_value=con),
        patch.object(pa.rt, "load_field_semantics", return_value={}),
        patch.object(pa.scope, "build_registry", return_value={}),
        patch.object(pa.scope, "load_policy", return_value={}),
        patch.object(pa.scope, "resolve_scope", return_value=scope.ScopeResolution(("ops_recommendations_history",), (), ())),
        patch.object(pa.rewrite_mod, "rewrite_legacy_layout", return_value=dict(proof)) as mock_rewrite,
    ):
        result = pa.action_rewrite_partition_layout(
            {
                "data_path": "s3://b/ducklake/",
                "meta_schema": "ducklake_ops",
                "table": "ops_recommendations_history",
                "confirm": "ops_recommendations_history",
            },
            None,
        )

    assert result == proof
    mock_rewrite.assert_called_once()
    assert con.close.called
