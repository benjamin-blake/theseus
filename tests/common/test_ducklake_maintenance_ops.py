"""Tests for src/common/ducklake_maintenance_ops.py -- the G1-G4 fail-closed guard set (T2.18,
Decision 188 amending Decision 81 clause 6 / CD.33 H1).

Mocked-connection coverage for G1 (reachability), G2 (retention floor), G3 (catalog sanity), and
G4 (deletion bound) runs unconditionally. TestG4RealDryRunSizeColumn is the one real-engine anchor
(marked @pytest.mark.integration, network-gated): every other cleanup/orphan test in this repo
mocks the connection with a tuple double, so without this anchor G4's byte accounting could be
green on a mock and byte-blind in production -- reproducing rec-3773 under a new name.
"""

from __future__ import annotations

import functools
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.common import ducklake_maintenance as maint
from src.common import ducklake_maintenance_ops as gcops

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


class FakeCon:
    """Minimal connection double: records SQL; returns configurable results per substring."""

    def __init__(self, fetchall_map: dict[str, list[Any]] | None = None, fetchone_map: dict[str, Any] | None = None):
        self.executed: list[str] = []
        self._fetchall_map: dict[str, list[Any]] = fetchall_map or {}
        self._fetchone_map: dict[str, Any] = fetchone_map or {}
        self._last = ""

    def execute(self, sql: str, params: Any = None) -> "FakeCon":
        self.executed.append(sql)
        self._last = sql
        return self

    def fetchone(self) -> tuple[Any, ...]:
        for sub, val in self._fetchone_map.items():
            if sub in self._last:
                return val
        return (0,)

    def fetchall(self) -> list[Any]:
        for sub, val in self._fetchall_map.items():
            if sub in self._last:
                return val
        return []

    def close(self) -> None:
        pass


class RaisingCon:
    """Connection double whose execute() always raises -- fail-closed anchor (rec-3772)."""

    def execute(self, sql: str, params: Any = None) -> "RaisingCon":
        raise RuntimeError("catalog introspection failed")


def _guarded_gc_con(*, cleanup_paths: list[str] | None = None, orphan_paths: list[str] | None = None) -> FakeCon:
    """A GC-pass fixture where the live set and would-delete set are DISJOINT (the happy path)."""
    live_files = [("s3://b/live0", 100), ("s3://b/live1", 100)]
    cleanup_paths = cleanup_paths if cleanup_paths is not None else ["s3://b/cleanup0"]
    orphan_paths = orphan_paths if orphan_paths is not None else []
    return FakeCon(
        fetchall_map={
            "ducklake_list_files": live_files,
            "ducklake_cleanup_old_files": [(p,) for p in cleanup_paths],
            "ducklake_delete_orphaned_files": [(p,) for p in orphan_paths],
            "ducklake_snapshots": [(1, _NOW), (2, _NOW)],
            "ducklake_expire_snapshots": [],
        },
        fetchone_map={
            "ducklake_cleanup_old_files": (len(cleanup_paths),),
            "ducklake_delete_orphaned_files": (len(orphan_paths),),
            "ducklake_expire_snapshots": (0,),
            "ducklake_snapshots": (2,),
        },
    )


# ---------------------------------------------------------------------------
# Fail-closed anchor (VP1): a catalog-introspection failure must raise
# DuckLakeMaintenanceError -- never a permissive all-clear result.
# ---------------------------------------------------------------------------


def test_guards_raise_when_catalog_introspection_fails():
    """rec-3772: the shipped check_gc_breaker was demonstrated returning breaker_tripped False
    with total_files 0 against a raising connection (2026-09-12). The guard set must instead raise."""
    with pytest.raises(maint.DuckLakeMaintenanceError, match="catalog introspection failed"):
        gcops.run_guarded_gc(
            RaisingCon(),
            ["t1"],
            catalog="cat",
            live_before={},
            grace_days=7,
            retain_days=30,
            floor=2,
            now=_NOW,
        )


class DirectMaintenanceErrorCon:
    """Connection double whose execute() raises DuckLakeMaintenanceError directly (not a generic
    exception) -- exercises the pass-through branch that never double-wraps an error that is
    already the guard set's own type."""

    def execute(self, sql: str, params: Any = None) -> "DirectMaintenanceErrorCon":
        raise maint.DuckLakeMaintenanceError("already a guard-set error")


def test_guard_input_collection_passes_through_an_existing_guard_error_unwrapped():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="already a guard-set error"):
        gcops.run_guarded_gc(
            DirectMaintenanceErrorCon(),
            ["t1"],
            catalog="cat",
            live_before={},
            grace_days=7,
            retain_days=30,
            floor=2,
            now=_NOW,
        )


class RaisesOnlyOnG2RecheckCon:
    """Connection double: every call succeeds (empty catalog, floor-skip on expiry) except the G2
    fresh snapshot-count re-read, which raises -- exercises G2's own fail-closed wrapping,
    distinct from the fail-closed wrapping around the initial reachability-input collection."""

    def __init__(self) -> None:
        self._last = ""

    def execute(self, sql: str, params: Any = None) -> "RaisesOnlyOnG2RecheckCon":
        if sql.startswith("SELECT count(*) FROM ducklake_snapshots"):
            raise RuntimeError("connection dropped before G2 re-read")
        self._last = sql
        return self

    def fetchall(self) -> list[Any]:
        if "ducklake_snapshots" in self._last:
            return [(1, _NOW), (2, _NOW)]  # 2 snapshots, floor=2 -> expire_snapshots floor-skips
        return []

    def fetchone(self) -> tuple[Any, ...]:
        return (0,)


def test_g2_recheck_introspection_failure_wraps_as_guard_error():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="could not re-read snapshot count for G2"):
        gcops.run_guarded_gc(
            RaisesOnlyOnG2RecheckCon(),
            ["t1"],
            catalog="cat",
            live_before={},
            grace_days=7,
            retain_days=30,
            floor=2,
            now=_NOW,
        )


class RaisesOnlyOnPostPassLiveSetCon:
    """Connection double: every call succeeds -- including both destructive calls -- except the
    SECOND `ducklake_list_files` read (the post-destructive live-set collection feeding the G1
    re-check and G3), which raises. Exercises the fail-closed wrapping around that specific
    collection, distinct from the pre-pass collection and the G2 recheck (code-review finding:
    this call site had no try/except, so a raw exception here -- right after real deletions have
    run -- would propagate past run_gc's own callers unwrapped)."""

    def __init__(self) -> None:
        self._last = ""
        self._list_files_calls = 0

    def execute(self, sql: str, params: Any = None) -> "RaisesOnlyOnPostPassLiveSetCon":
        if "ducklake_list_files" in sql:
            self._list_files_calls += 1
            if self._list_files_calls > 1:
                raise RuntimeError("connection dropped before the post-pass live-set re-read")
        self._last = sql
        return self

    def fetchall(self) -> list[Any]:
        if "ducklake_list_files" in self._last:
            return [("s3://b/live0", 100), ("s3://b/live1", 100)]
        if "ducklake_snapshots" in self._last:
            return [(1, _NOW), (2, _NOW)]  # 2 snapshots, floor=2 -> expire_snapshots floor-skips
        return []

    def fetchone(self) -> tuple[Any, ...]:
        if "SELECT count(*) FROM ducklake_snapshots" in self._last:
            return (2,)  # G2 recheck: 2 remaining, at the floor -- must not raise here
        return (0,)


class RaisesGuardErrorOnPostPassLiveSetCon(RaisesOnlyOnPostPassLiveSetCon):
    """Same fixture, but the second `ducklake_list_files` read raises DuckLakeMaintenanceError
    directly -- exercises the post-pass collection's own pass-through branch (never double-wrap
    an error that is already the guard set's own type), mirroring
    test_guard_input_collection_passes_through_an_existing_guard_error_unwrapped for the
    pre-pass collection."""

    def execute(self, sql: str, params: Any = None) -> "RaisesGuardErrorOnPostPassLiveSetCon":
        if "ducklake_list_files" in sql:
            self._list_files_calls += 1
            if self._list_files_calls > 1:
                raise maint.DuckLakeMaintenanceError("already a guard-set error, post-pass")
        self._last = sql
        return self


def test_post_pass_live_set_guard_error_passes_through_unwrapped():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="already a guard-set error, post-pass"):
        gcops.run_guarded_gc(
            RaisesGuardErrorOnPostPassLiveSetCon(),
            ["t1"],
            catalog="cat",
            live_before={"s3://b/live0": 100, "s3://b/live1": 100},
            grace_days=7,
            retain_days=30,
            floor=2,
            now=_NOW,
        )


def test_post_pass_live_set_introspection_failure_wraps_as_guard_error():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="collecting the post-pass live set for the G1 re-check and G3"):
        gcops.run_guarded_gc(
            RaisesOnlyOnPostPassLiveSetCon(),
            ["t1"],
            catalog="cat",
            live_before={"s3://b/live0": 100, "s3://b/live1": 100},
            grace_days=7,
            retain_days=30,
            floor=2,
            now=_NOW,
        )


# ---------------------------------------------------------------------------
# G1 reachability
# ---------------------------------------------------------------------------


def test_g1_disjoint_sets_do_not_raise():
    gcops.assert_reachability({"a", "b"}, {"c", "d"})  # no raise


def test_g1_intersecting_sets_raise_naming_the_path():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G1 reachability"):
        gcops.assert_reachability({"a", "b"}, {"b", "c"})


def test_g1_force_conflict_trips_independent_of_empty_inputs():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G1 reachability"):
        gcops.assert_reachability(set(), set(), force_conflict=gcops.G1_PROBE_FORCE_CONFLICT)


def test_g1_probe_g1_trip_always_raises():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G1 reachability"):
        gcops.probe_g1_trip()


def test_g1_non_forcing_call_does_not_trip():
    """Red case for the forcing mechanism itself: with no force_conflict and disjoint sets, the
    guard must NOT raise -- proving the FORCING ARGUMENT (not an unconditional raise) is what
    trips the probe."""
    gcops.assert_reachability(set(), set())  # no raise


def test_g1_nonempty_intersection_via_run_guarded_gc_raises_and_issues_zero_destructive_sql():
    con = _guarded_gc_con(cleanup_paths=["s3://b/live0"])  # live0 is BOTH live and would-delete
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G1 reachability"):
        gcops.run_guarded_gc(con, ["t1"], catalog="cat", live_before={}, grace_days=7, retain_days=30, floor=1, now=_NOW)
    assert not any("dry_run=False" in s for s in con.executed), "no destructive call may be issued after a G1 violation"


def test_g1_disjoint_sets_via_run_guarded_gc_do_not_raise():
    con = _guarded_gc_con()  # cleanup0 is disjoint from live0/live1
    result = gcops.run_guarded_gc(con, ["t1"], catalog="cat", live_before={}, grace_days=7, retain_days=30, floor=1, now=_NOW)
    assert result["guard_stats"]["g1_would_delete_candidates"] == 1


# ---------------------------------------------------------------------------
# G2 retention floor
# ---------------------------------------------------------------------------


def test_g2_raises_when_post_expiry_count_below_floor():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G2 retention floor"):
        gcops.assert_retention_floor(1, floor=2)


def test_g2_passes_when_at_or_above_floor():
    gcops.assert_retention_floor(2, floor=2)  # no raise
    gcops.assert_retention_floor(5, floor=2)  # no raise


def test_g2_violation_via_run_guarded_gc_raises():
    con = _guarded_gc_con()
    con._fetchone_map["ducklake_snapshots"] = (1,)  # engine under-retained relative to floor=2
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G2 retention floor"):
        gcops.run_guarded_gc(con, ["t1"], catalog="cat", live_before={}, grace_days=7, retain_days=30, floor=2, now=_NOW)


# ---------------------------------------------------------------------------
# G3 catalog sanity
# ---------------------------------------------------------------------------


def test_g3_raises_on_empty_live_set():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G3 catalog sanity"):
        gcops.assert_catalog_sane(set(), live_bytes_before=1000, live_bytes_after=0)


def test_g3_raises_on_byte_drop_past_bound():
    with pytest.raises(maint.DuckLakeMaintenanceError, match="G3 catalog sanity"):
        gcops.assert_catalog_sane({"a"}, live_bytes_before=100 * 1024**3, live_bytes_after=0, max_byte_drop=10)


def test_g3_passes_within_bound():
    gcops.assert_catalog_sane({"a"}, live_bytes_before=1000, live_bytes_after=900)  # no raise


# ---------------------------------------------------------------------------
# G4 deletion bound
# ---------------------------------------------------------------------------


def test_g4_within_budget_proceeds():
    bound = gcops.bound_deletions({"a": 100, "b": 200}, max_files=10, max_bytes=10_000)
    assert bound.proceed is True
    assert bound.would_delete_files == 2
    assert bound.would_delete_bytes == 300
    assert bound.deferred_files == 0
    assert bound.deferred_bytes == 0


def test_g4_over_file_count_defers_whole_pass():
    candidates = {f"f{i}": 10 for i in range(5)}
    bound = gcops.bound_deletions(candidates, max_files=3, max_bytes=10_000)
    assert bound.proceed is False
    assert bound.deferred_files == 5
    assert bound.deferred_bytes == 50


def test_g4_over_byte_budget_defers_whole_pass():
    candidates = {"big": 1_000_000}
    bound = gcops.bound_deletions(candidates, max_files=10, max_bytes=1000)
    assert bound.proceed is False
    assert bound.deferred_bytes == 1_000_000


def test_g4_bounds_large_candidate_pass_reports_nonzero_deferred_remainder():
    """rec-3773: a 24,435-candidate pass, each with a real non-zero size, must report a non-zero
    deferred remainder AND non-zero would-delete bytes -- the exact property the retired breaker's
    dead byte budget could never demonstrate (it always summed to 0)."""
    candidates = {f"s3://b/f{i}": 1024 for i in range(24_435)}
    bound = gcops.bound_deletions(candidates, max_files=20_000, max_bytes=10 * 1024**3)
    assert bound.proceed is False
    assert bound.deferred_files == 24_435
    assert bound.deferred_bytes == 24_435 * 1024
    assert bound.would_delete_bytes > 0


def test_g4_defers_via_run_guarded_gc_skips_destructive_calls():
    """Integration-level defer check: construct a would-delete candidate set that exceeds G4's
    real file-count bound, and confirm run_guarded_gc skips the destructive calls entirely while
    G1-G3 (evaluated against a consistent live-file total) still pass."""
    cleanup_paths = [f"s3://b/cleanup{i}" for i in range(gcops.G4_MAX_DELETE_FILES + 1)]
    con = _guarded_gc_con(cleanup_paths=cleanup_paths)
    live_before = {"s3://b/live0": 100, "s3://b/live1": 100}  # matches the fixture's live set exactly
    result = gcops.run_guarded_gc(
        con, ["t1"], catalog="cat", live_before=live_before, grace_days=7, retain_days=30, floor=1, now=_NOW
    )
    assert result["guard_stats"]["g4_bounded"] is True
    assert result["guard_stats"]["g4_deferred_files"] == len(cleanup_paths)
    assert not any("dry_run=False" in s for s in con.executed), "an over-budget pass must defer, not partially delete"
    assert result["files_cleaned"] == 0
    assert result["orphans_deleted"] == 0


# ---------------------------------------------------------------------------
# G4 real-engine anchor (network-gated integration test)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _has_ducklake_extension() -> bool:
    """Return True if the ducklake extension is available (installed or fetchable over network)."""
    try:
        import duckdb

        con = duckdb.connect()
        con.execute("INSTALL ducklake; LOAD ducklake")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.integration
class TestG4RealDryRunSizeColumn:
    """G4's byte accounting must come from a REAL pre-merge size snapshot joined against a REAL
    dry-run candidate list, on the pinned DuckLake engine -- not a FakeCon tuple mock. Every other
    cleanup/orphan test in this repo mocks the connection, so without this anchor G4 could be green
    on a mock and byte-blind in production (rec-3773 under a new name, Decision 187 pt 2)."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_ducklake_extension(self, _allow_network_for_integration: None) -> None:
        if not _has_ducklake_extension():
            pytest.skip("ducklake extension not available over the network")

    def test_g4_reads_real_dry_run_size_column_on_pinned_engine(self, tmp_path: Any) -> None:
        import duckdb

        catalog_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        data_path.mkdir()

        con = duckdb.connect(":memory:")
        try:
            con.execute("INSTALL ducklake")
            con.execute("LOAD ducklake")
            con.execute(f"ATTACH 'ducklake:{catalog_path}' AS lk (DATA_PATH '{data_path}', DATA_INLINING_ROW_LIMIT 0)")
            con.execute("USE lk")
            con.execute("CREATE TABLE t1 (id INTEGER, val VARCHAR)")
            con.execute("INSERT INTO t1 SELECT range, 'v' || range FROM range(1000)")
            con.execute("INSERT INTO t1 SELECT range, 'v' || range FROM range(1000, 2000)")

            catalog = "lk"
            table = "t1"

            # Pre-pass size inventory -- BEFORE merge supersedes the two small files. This is the
            # exact fix: the retired breaker joined would-delete paths against a POST-merge
            # inventory, where a just-superseded path is always absent (rec-3773's dead byte budget).
            live_before = maint._collect_file_paths(con, catalog, table)
            assert live_before, "expected at least one live file before merge"

            maint.merge_adjacent_files(con, [table], catalog=catalog)

            now = datetime.now(timezone.utc) + timedelta(seconds=1)
            maint.expire_snapshots(con, catalog=catalog, retain_days=0, floor=1, _now=now)

            candidate_paths = set(
                maint._dry_run_cleanup_paths(con, catalog, now) + maint._dry_run_orphan_paths(con, catalog, now)
            )
            assert candidate_paths, "expected the two pre-merge files to be cleanup/orphan candidates"

            candidate_bytes = {p: live_before.get(p, 0) for p in candidate_paths}
            bound = gcops.bound_deletions(candidate_bytes, max_files=100, max_bytes=10 * 1024**3)

            assert bound.would_delete_bytes > 0, (
                "G4 byte accounting is dead (rec-3773): joining candidate paths against a "
                "PRE-merge size snapshot must yield a non-zero total on the real engine"
            )
        finally:
            con.close()
