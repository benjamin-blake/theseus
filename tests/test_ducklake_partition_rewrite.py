"""MIRROR for src/common/ducklake_partition_rewrite.py (Decision 204,
PLAN-ducklake-partition-layout-remediation).

FakeCon-driven mirror test: no-op-free ALTER issuing declared_spec verbatim, all three rewrite
refusals (non-history side, no legacy files, live spec still drifted), pre_snapshot re-captured
per attempt, the commit-message token set per attempt and commit_snapshot_id resolved by it (a
concurrent commit is never mistaken for the rewrite's own), retry-then-succeed, retry-exhaustion
raise, a non-OCC error wrapped in PartitionRewriteError, pre-commit digest mismatch -> ROLLBACK +
raise, a NULL-bearing row shift changing the digest, post-commit proof failure raising with both
ids.
"""

from __future__ import annotations

import pytest

from src.common.ducklake_partition_layout import PartitionDrift
from src.common.ducklake_partition_rewrite import PartitionRewriteError, alter_to_declared, rewrite_legacy_layout

pytestmark = pytest.mark.unit

_COLUMNS = {
    "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
    "rec_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
    "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
    "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
}


def _semantics() -> dict:
    return {
        "ops_tables": {
            "ops_recommendations": {
                "status": "live",
                "write_mode": "scd2",
                "history_table": "ops_recommendations_history",
                "current_table": "ops_recommendations_current",
                "merge_key": "rec_id",
                "columns": _COLUMNS,
                "partition": {
                    "history": "year(created_timestamp), month(created_timestamp), day(created_timestamp)",
                    "current": "bucket(8, rec_id)",
                },
            },
            "ops_entity_counters": {"status": "live", "write_mode": "control"},
        },
        "fields": _COLUMNS,
        "partition_transforms": {
            "history": "year(created_timestamp), month(created_timestamp), day(created_timestamp)",
            "current": "bucket(8, rec_id)",
        },
        "tables": {
            "history": {
                "name": "ducklake_smoke_history",
                "partition": "year(created_timestamp), month(created_timestamp), day(created_timestamp)",
            },
            "current": {"name": "ducklake_smoke_current", "partition": "bucket(8, rec_id)"},
        },
    }


class FakeRewriteCon:
    """Fake DuckDB connection double covering both read_partition_layout's catalog-metadata reads
    (reused by rewrite_legacy_layout's precondition checks and post-commit re-read) and the
    rewrite transaction's own statements (BEGIN/CALL/CREATE TEMP TABLE/DELETE/INSERT/COMMIT/
    ducklake_snapshots/AT (VERSION => ...)).

    `catalog[physical]` carries the layout state; `proofs[marker]` maps a row_proof table-ref
    substring to a canned (rows, digest) pair; `fail_on` (sql substring, remaining_failures) injects
    an exception on matching statements for N occurrences before letting them through.
    """

    def __init__(
        self,
        catalog: dict,
        *,
        proofs: dict[str, tuple[int, str]],
        snapshot_ids: list[int],
        commit_message_token_to_id: dict[str, int] | None = None,
        fail_on: tuple[str, str, int] | None = None,  # (sql_substring, exc_message, times)
        post_commit_legacy_files: int | None = None,
    ):
        self._catalog = catalog
        self._proofs = proofs
        self._snapshot_ids = iter(snapshot_ids)
        self._commit_message_token_to_id = commit_message_token_to_id or {}
        self._fail_on = list(fail_on) if fail_on else None  # mutable countdown
        self._post_commit_legacy_files = post_commit_legacy_files
        self._committed = False
        self._last_sql = ""
        self._last_params: list | None = None
        self.executed: list[str] = []

    def _entry_by_table_id(self, table_id: int) -> dict:
        return next(v for v in self._catalog.values() if v["table_id"] == table_id)

    def execute(self, sql: str, params: list | None = None):
        self._last_sql = sql
        self._last_params = params or []
        self.executed.append(sql)

        if self._fail_on is not None:
            substr, message, remaining = self._fail_on
            if substr in sql and remaining > 0:
                self._fail_on[2] -= 1
                raise RuntimeError(message)

        if sql == "COMMIT":
            self._committed = True
            if self._post_commit_legacy_files is not None:
                for entry in self._catalog.values():
                    entry["legacy_files"] = self._post_commit_legacy_files
        return self

    def fetchall(self):
        sql, params = self._last_sql, self._last_params or []
        if "table_name FROM" in sql and "ducklake_table" in sql:
            return [(name,) for name in self._catalog]
        if "ducklake_partition_column" in sql:
            table_id = params[1]
            return list(self._entry_by_table_id(table_id)["live_transforms"])
        return []

    def fetchone(self):
        sql, params = self._last_sql, self._last_params or []
        if "table_id FROM" in sql and "ducklake_table" in sql:
            return (self._catalog[params[0]]["table_id"],)
        if "partition_id FROM" in sql and "ducklake_partition_info" in sql:
            entry = self._entry_by_table_id(params[0])
            return (entry["active_scheme_id"],) if entry["active_scheme_id"] is not None else None
        if "count(*)" in sql and "ducklake_data_file" in sql:
            entry = self._entry_by_table_id(params[0])
            if "partition_id IS DISTINCT FROM" in sql:
                return (entry["legacy_files"],)
            return (entry["live_files"],)
        if "current_snapshot()" in sql:
            return (next(self._snapshot_ids),)
        if "count(*), md5" in sql:
            for marker, proof in self._proofs.items():
                if marker in sql:
                    return proof
            raise AssertionError(f"no canned proof for row_proof query: {sql}")
        if "ducklake_snapshots" in sql and "commit_message" in sql:
            token = params[0]
            commit_id = self._commit_message_token_to_id.get(token)
            return (commit_id,) if commit_id is not None else None
        return None


_LIVE_TRANSFORMS = (("year", "created_timestamp"), ("month", "created_timestamp"), ("day", "created_timestamp"))

_BASE_HISTORY_ENTRY = {
    "table_id": 1,
    "active_scheme_id": 10,
    "live_transforms": _LIVE_TRANSFORMS,
    "live_files": 93,
    "legacy_files": 40,
}
_BASE_CURRENT_ENTRY = {
    "table_id": 2,
    "active_scheme_id": 20,
    "live_transforms": (("bucket(8)", "rec_id"),),
    "live_files": 8,
    "legacy_files": 0,
}
_BASE_CONTROL_ENTRY = {
    "table_id": 3,
    "active_scheme_id": None,
    "live_transforms": (),
    "live_files": 1,
    "legacy_files": 0,
}


def _catalog(**overrides) -> dict:
    cat = {
        "ops_recommendations_history": dict(_BASE_HISTORY_ENTRY),
        "ops_recommendations_current": dict(_BASE_CURRENT_ENTRY),
        "ops_entity_counters": dict(_BASE_CONTROL_ENTRY),
    }
    for physical, entry_overrides in overrides.items():
        cat[physical].update(entry_overrides)
    return cat


# ---------------------------------------------------------------------------
# alter_to_declared -- no-op-free ALTER, one table per transaction, OCC retry, ceiling raise
# ---------------------------------------------------------------------------


def _drift(
    physical: str = "ops_recommendations_history",
    declared_spec: str = "year(created_timestamp), month(created_timestamp), day(created_timestamp)",
):
    return PartitionDrift(
        physical=physical,
        table_class="scd2",
        declared_spec=declared_spec,
        declared=(("year", "created_timestamp"), ("month", "created_timestamp"), ("day", "created_timestamp")),
        live=(("day", "created_timestamp"),),
        legacy_scheme_files=40,
    )


def test_alter_to_declared_issues_declared_spec_verbatim():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[])
    altered = alter_to_declared(con, [_drift()], catalog_alias="cat")
    assert altered == ["ops_recommendations_history"]
    alter_sql = next(s for s in con.executed if s.startswith("ALTER TABLE"))
    assert alter_sql.startswith("ALTER TABLE cat.ops_recommendations_history SET PARTITIONED BY (")
    assert "year(created_timestamp), month(created_timestamp), day(created_timestamp)" in alter_sql


def test_alter_to_declared_empty_drift_list_issues_no_alter():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[])
    assert alter_to_declared(con, [], catalog_alias="cat") == []
    assert not any(s.startswith("ALTER TABLE") for s in con.executed)


def test_alter_to_declared_retries_then_succeeds():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[], fail_on=("ALTER TABLE", "could not serialize access", 2))
    altered = alter_to_declared(con, [_drift()], catalog_alias="cat", sleep=lambda _s: None)
    assert altered == ["ops_recommendations_history"]
    assert sum(1 for s in con.executed if s.startswith("ALTER TABLE")) == 3


def test_alter_to_declared_retry_ceiling_raises():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[], fail_on=("ALTER TABLE", "could not serialize access", 99))
    with pytest.raises(PartitionRewriteError, match="OCC retry budget exhausted"):
        alter_to_declared(con, [_drift()], catalog_alias="cat", max_attempts=3, sleep=lambda _s: None)


def test_alter_to_declared_non_occ_error_wrapped():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[], fail_on=("ALTER TABLE", "relation does not exist", 99))
    with pytest.raises(PartitionRewriteError, match="relation does not exist"):
        alter_to_declared(con, [_drift()], catalog_alias="cat", sleep=lambda _s: None)


# ---------------------------------------------------------------------------
# rewrite_legacy_layout -- refusals
# ---------------------------------------------------------------------------


def test_rewrite_refuses_non_history_side():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[])
    with pytest.raises(PartitionRewriteError, match="only a HISTORY-side table"):
        rewrite_legacy_layout(con, "ops_recommendations_current", catalog_alias="cat", semantics=_semantics())


def test_rewrite_refuses_zero_legacy_files():
    con = FakeRewriteCon(_catalog(ops_recommendations_history={"legacy_files": 0}), proofs={}, snapshot_ids=[])
    with pytest.raises(PartitionRewriteError, match="no legacy-scheme files"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())


def test_rewrite_refuses_when_live_spec_still_drifted():
    con = FakeRewriteCon(
        _catalog(ops_recommendations_history={"live_transforms": (("day", "created_timestamp"),)}),
        proofs={},
        snapshot_ids=[],
    )
    with pytest.raises(PartitionRewriteError, match="run alter_to_declared first"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())


def test_rewrite_refuses_unknown_physical_table():
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[])
    with pytest.raises(PartitionRewriteError, match="not a live, classified table"):
        rewrite_legacy_layout(con, "not_a_real_table", catalog_alias="cat", semantics=_semantics())


def test_rewrite_refuses_control_class_table():
    """Belt-and-braces: a control-class table is also refused by the side check (its side is
    'table', never 'history') even though its policy-matrix cell should already have excluded it
    upstream."""
    con = FakeRewriteCon(_catalog(), proofs={}, snapshot_ids=[])
    with pytest.raises(PartitionRewriteError, match="only a HISTORY-side table"):
        rewrite_legacy_layout(con, "ops_entity_counters", catalog_alias="cat", semantics=_semantics())


# ---------------------------------------------------------------------------
# rewrite_legacy_layout -- the happy path, retries, and proof failures
# ---------------------------------------------------------------------------


def _happy_con(**fail_kwargs) -> FakeRewriteCon:
    return FakeRewriteCon(
        _catalog(),
        proofs={
            "_partition_rewrite_snap": (93, "DIGEST-A"),
            "SELECT * FROM cat.ops_recommendations_history)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 500)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 501)": (93, "DIGEST-A"),
        },
        snapshot_ids=[500, 501, 502, 503],
        commit_message_token_to_id={},
        post_commit_legacy_files=0,
        **fail_kwargs,
    )


def _wire_commit_token(con: FakeRewriteCon, commit_snapshot_id: int) -> None:
    """A FakeRewriteCon can't know the uuid-derived token in advance, so intercept execute() to
    learn the token from the CALL statement and register it -- mirroring the real engine's own
    later-queryable commit_message binding."""
    original_execute = con.execute

    def _execute(sql, params=None):
        if sql.startswith("CALL") and "set_commit_message" in sql and params:
            con._commit_message_token_to_id[params[1]] = commit_snapshot_id
        return original_execute(sql, params)

    con.execute = _execute  # type: ignore[method-assign]


def test_rewrite_happy_path_returns_full_proof_and_zero_legacy_after():
    con = _happy_con()
    _wire_commit_token(con, commit_snapshot_id=501)

    result = rewrite_legacy_layout(
        con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics(), uuid_factory=lambda: "fixed-uuid"
    )

    assert result["physical"] == "ops_recommendations_history"
    assert result["pre_snapshot_id"] == 500
    assert result["commit_snapshot_id"] == 501
    assert result["rows_pre"] == result["rows_commit"] == 93
    assert result["digest_pre"] == result["digest_commit"] == "DIGEST-A"
    assert result["files_before"] == 93
    assert result["files_after"] == 93  # post_commit_legacy_files=0 doesn't change live_files in this fixture
    assert result["attempts"] == 1
    assert con._committed is True


_SMOKE_HISTORY_ENTRY = {
    "table_id": 7,
    "active_scheme_id": 70,
    "live_transforms": (("year", "created_timestamp"), ("month", "created_timestamp"), ("day", "created_timestamp")),
    "live_files": 5,
    "legacy_files": 0,
}
_SMOKE_CURRENT_ENTRY = {
    "table_id": 8,
    "active_scheme_id": 80,
    "live_transforms": (("bucket(8)", "rec_id"),),
    "live_files": 2,
    "legacy_files": 0,
}


def test_rewrite_proceeds_with_declared_smoke_harness_resident():
    """rewrite_legacy_layout's own precondition read is a whole-catalog read_partition_layout call
    -- a catalog that also carries the declared smoke-harness pair must not fail that read closed
    (Decision 191 amendment); an ops history table's legitimate legacy rewrite still proceeds."""
    catalog = _catalog()
    catalog["ducklake_smoke_history"] = dict(_SMOKE_HISTORY_ENTRY)
    catalog["ducklake_smoke_current"] = dict(_SMOKE_CURRENT_ENTRY)
    con = FakeRewriteCon(
        catalog,
        proofs={
            "_partition_rewrite_snap": (93, "DIGEST-A"),
            "SELECT * FROM cat.ops_recommendations_history)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 500)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 501)": (93, "DIGEST-A"),
        },
        snapshot_ids=[500, 501, 502, 503],
        commit_message_token_to_id={},
        post_commit_legacy_files=0,
    )
    _wire_commit_token(con, commit_snapshot_id=501)

    result = rewrite_legacy_layout(
        con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics(), uuid_factory=lambda: "fixed-uuid"
    )

    assert result["physical"] == "ops_recommendations_history"
    assert result["commit_snapshot_id"] == 501
    assert con._committed is True


def test_rewrite_pre_commit_digest_mismatch_rolls_back_and_raises():
    con = FakeRewriteCon(
        _catalog(),
        proofs={
            "_partition_rewrite_snap": (93, "DIGEST-A"),
            "SELECT * FROM cat.ops_recommendations_history)": (93, "DIGEST-DIFFERENT"),
        },
        snapshot_ids=[500],
    )
    with pytest.raises(PartitionRewriteError, match="pre-commit proof mismatch"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())
    assert "ROLLBACK" in con.executed
    assert "COMMIT" not in con.executed


def test_rewrite_pre_commit_row_count_mismatch_from_null_bearing_shift_rolls_back():
    """A NULL-bearing column shift changes the row count OR digest -- proven here via a row-count
    disagreement between the snapshot and the re-inserted table."""
    con = FakeRewriteCon(
        _catalog(),
        proofs={
            "_partition_rewrite_snap": (93, "DIGEST-A"),
            "SELECT * FROM cat.ops_recommendations_history)": (92, "DIGEST-A"),
        },
        snapshot_ids=[500],
    )
    with pytest.raises(PartitionRewriteError, match="pre-commit proof mismatch"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())


def test_rewrite_retries_on_occ_collision_then_succeeds():
    con = _happy_con(fail_on=("INSERT INTO cat.ops_recommendations_history", "could not serialize access", 1))
    _wire_commit_token(con, commit_snapshot_id=501)

    result = rewrite_legacy_layout(
        con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics(), sleep=lambda _s: None
    )
    assert result["attempts"] == 2
    assert result["pre_snapshot_id"] == 501  # re-captured on the successful (2nd) attempt


def test_rewrite_occ_retry_ceiling_raises():
    con = _happy_con(fail_on=("INSERT INTO cat.ops_recommendations_history", "could not serialize access", 99))
    with pytest.raises(PartitionRewriteError, match="OCC retry budget exhausted"):
        rewrite_legacy_layout(
            con,
            "ops_recommendations_history",
            catalog_alias="cat",
            semantics=_semantics(),
            max_attempts=2,
            sleep=lambda _s: None,
        )


def test_rewrite_rollback_failure_is_swallowed_and_original_error_surfaces():
    """A 'no active transaction' ROLLBACK failure must never mask the original raised error."""
    con = FakeRewriteCon(
        _catalog(),
        proofs={"_partition_rewrite_snap": (93, "DIGEST-A")},
        snapshot_ids=[500],
        fail_on=("DELETE FROM cat.ops_recommendations_history", "relation does not exist", 99),
    )
    original_execute = con.execute

    def _execute(sql, params=None):
        if sql == "ROLLBACK":
            raise RuntimeError("no active transaction")
        return original_execute(sql, params)

    con.execute = _execute  # type: ignore[method-assign]
    with pytest.raises(PartitionRewriteError, match="relation does not exist"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())


def test_rewrite_non_occ_error_wrapped():
    con = FakeRewriteCon(
        _catalog(),
        proofs={"_partition_rewrite_snap": (93, "DIGEST-A")},
        snapshot_ids=[500],
        fail_on=("DELETE FROM cat.ops_recommendations_history", "relation does not exist", 99),
    )
    with pytest.raises(PartitionRewriteError, match="relation does not exist"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())


def test_rewrite_commit_message_token_unresolvable_raises():
    con = _happy_con()  # commit_message_token_to_id stays empty -- lookup misses
    with pytest.raises(PartitionRewriteError, match="could not resolve commit_snapshot_id"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())


def test_rewrite_post_commit_proof_failure_raises_with_both_snapshot_ids():
    con = FakeRewriteCon(
        _catalog(),
        proofs={
            "_partition_rewrite_snap": (93, "DIGEST-A"),
            "SELECT * FROM cat.ops_recommendations_history)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 500)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 501)": (92, "DIGEST-A"),  # post-commit reproof disagrees
        },
        snapshot_ids=[500],
        commit_message_token_to_id={},
    )
    _wire_commit_token(con, commit_snapshot_id=501)
    with pytest.raises(PartitionRewriteError, match="POST-COMMIT proof failed") as exc_info:
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())
    assert "pre_snapshot_id=500" in str(exc_info.value)
    assert "commit_snapshot_id=501" in str(exc_info.value)


def test_rewrite_post_commit_legacy_files_remaining_raises():
    con = FakeRewriteCon(
        _catalog(),
        proofs={
            "_partition_rewrite_snap": (93, "DIGEST-A"),
            "SELECT * FROM cat.ops_recommendations_history)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 500)": (93, "DIGEST-A"),
            "cat.ops_recommendations_history AT (VERSION => 501)": (93, "DIGEST-A"),
        },
        snapshot_ids=[500],
        commit_message_token_to_id={},
        post_commit_legacy_files=5,  # rewrite committed but legacy files somehow remain
    )
    _wire_commit_token(con, commit_snapshot_id=501)
    with pytest.raises(PartitionRewriteError, match="POST-COMMIT proof failed"):
        rewrite_legacy_layout(con, "ops_recommendations_history", catalog_alias="cat", semantics=_semantics())
