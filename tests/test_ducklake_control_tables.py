"""Tests for src/common/ducklake_control_tables.py (T2.26
control-table-class-and-counter-conformance): control spec shape, DDL, partition, and write-verb
refusal, plus the ducklake_scd2_schema shim's directed-raise delegation.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.common import ducklake_control_tables as ct
from src.common import ducklake_scd2_schema as schema
from src.common import ducklake_tables as tables
from src.common import ducklake_writes as writes

pytestmark = pytest.mark.unit


class _RecordingCon:
    def __init__(self):
        self.executed: list[str] = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        return self


def test_control_spec_has_no_history_pair():
    """Control-class resolution returns a single partitioned table with no history/current pair."""
    spec = ct.resolve_control_spec("ops_entity_counters")
    assert spec.table == "ops_entity_counters"
    assert spec.partition_key == "counter_name"
    assert spec.ordered_columns == (("counter_name", "VARCHAR"), ("current_value", "BIGINT"))
    assert not hasattr(spec, "history_table")
    assert not hasattr(spec, "current_table")


def test_resolve_control_spec_rejects_unknown_table():
    with pytest.raises(schema.DuckLakeRuntimeError, match="unknown control table"):
        ct.resolve_control_spec("ops_not_a_real_table")


def test_control_table_names_and_is_control_table():
    assert ct.control_table_names() == ("ops_entity_counters",)
    assert ct.is_control_table("ops_entity_counters") is True
    assert ct.is_control_table("ops_recommendations") is False
    assert ct.is_control_table(None) is False
    assert ct.is_control_table(123) is False


def test_control_ddl_single_table():
    """Control-class creation issues one CREATE plus one SET PARTITIONED BY."""
    con = _RecordingCon()
    tables.create_control_table(con, table="ops_entity_counters")
    creates = [s for s in con.executed if s.startswith("CREATE TABLE")]
    partitions = [s for s in con.executed if "SET PARTITIONED BY" in s]
    drops = [s for s in con.executed if s.startswith("DROP TABLE")]
    assert len(creates) == 1
    assert len(partitions) == 1
    assert not drops
    assert "counter_name VARCHAR NOT NULL" in creates[0]
    assert "current_value BIGINT NOT NULL" in creates[0]
    assert "(counter_name)" in partitions[0]


def test_control_ddl_force_recreate_drops_first():
    con = _RecordingCon()
    tables.create_control_table(con, table="ops_entity_counters", force_recreate=True)
    assert con.executed[0].startswith("DROP TABLE IF EXISTS")
    assert any(s.startswith("CREATE TABLE") for s in con.executed)


def test_write_verb_refusal_on_control_table():
    """write_ops, file_ops and update_ops each raise on a control-class table -- the write verbs
    refuse it rather than falling through into the SCD2 branch against current_table=None."""
    con = object()  # never touched: the refusal fires before any catalog work
    with pytest.raises(schema.SchemaGateError, match="control-class table"):
        writes.write_scd2(con, {"counter_name": "ops_recommendations"}, table="ops_entity_counters")
    with pytest.raises(schema.SchemaGateError, match="control-class table"):
        writes.file_scd2(con, {"counter_name": "ops_recommendations"}, table="ops_entity_counters")
    with pytest.raises(schema.SchemaGateError, match="control-class table"):
        writes.write_scd2(con, {"counter_name": "ops_recommendations"}, table="ops_entity_counters", require_exists=True)


def test_scd2_schema_delegates_without_widening():
    """resolve_table_spec raises a directed error for a control-class table; ScdTableSpec.history_table
    stays non-optional (mypy is ratchet-enforced) -- the shim delegates, it never widens."""
    with pytest.raises(schema.SchemaGateError, match="ducklake_control_tables"):
        schema.resolve_table_spec("ops_entity_counters")

    history_field = next(f for f in dataclasses.fields(schema.ScdTableSpec) if f.name == "history_table")
    assert history_field.type == "str"  # unchanged, non-Optional
    field_names = {f.name for f in dataclasses.fields(schema.ScdTableSpec)}
    assert field_names == {
        "table",
        "history_table",
        "current_table",
        "merge_key",
        "fields",
        "ordered_columns",
        "partition_history",
        "partition_current",
        "entity_id_prefix",
        "id_keyspace",
        "write_mode",
    }


# ---------------------------------------------------------------------------
# Counter bookkeeping (ensure_entity_counters_table / bootstrap_entity_counter /
# _safe_rollback) -- relocated here from ducklake_writes.py (T2.26 SLOC decompose). This is now
# the sole dedicated coverage home for src/common/ducklake_control_tables.py (Decision 131 mirror
# convention: tests/test_ducklake_control_tables.py), so these three primitives need their own
# direct tests independent of ducklake_writes' file_scd2/write_scd2 integration coverage.
# ---------------------------------------------------------------------------


class _BootstrapCon:
    """Minimal scripted double for the bootstrap_entity_counter transaction shape."""

    def __init__(self, *, seed_max: int = 2170, fail_on: str | None = None):
        self.executed: list[str] = []
        self._seed_max = seed_max
        self._fail_on = fail_on
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        if self._fail_on is not None and self._fail_on in sql:
            raise RuntimeError("boom")
        self.executed.append(sql)
        return self

    def fetchone(self):
        if "coalesce(max(CAST(regexp_extract" in self._last:
            return (self._seed_max,)
        return None


def test_ensure_entity_counters_table_issues_create_if_not_exists():
    con = _RecordingCon()
    ct.ensure_entity_counters_table(con)
    assert len(con.executed) == 1
    assert con.executed[0].startswith("CREATE TABLE IF NOT EXISTS")
    assert "counter_name VARCHAR NOT NULL" in con.executed[0]


def test_safe_rollback_swallows_error():
    class _RollbackFailsCon:
        def execute(self, sql, params=None):
            raise RuntimeError("no active transaction")

    ct._safe_rollback(_RollbackFailsCon())  # must not raise


def test_bootstrap_entity_counter_seeds_from_history_max():
    con = _BootstrapCon(seed_max=2178)
    spec = schema.resolve_table_spec("ops_recommendations")
    seed = ct.bootstrap_entity_counter(con, spec)
    assert seed == 2178
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS") for s in con.executed)
    assert any(s.startswith("DELETE FROM") and ct.ENTITY_COUNTERS_TABLE in s for s in con.executed)
    assert any("INSERT INTO" in s and ct.ENTITY_COUNTERS_TABLE in s for s in con.executed)
    assert "COMMIT" in con.executed


def test_bootstrap_entity_counter_rejects_unprefixed_table():
    con = _BootstrapCon()
    spec = schema.resolve_table_spec("ops_priority_queue")
    with pytest.raises(schema.DuckLakeRuntimeError, match="no allocation counter"):
        ct.bootstrap_entity_counter(con, spec)


def test_bootstrap_entity_counter_rejects_caller_keyspace():
    con = _BootstrapCon()
    spec = schema.resolve_table_spec("ops_decisions")
    with pytest.raises(schema.DuckLakeRuntimeError, match="no writer-owned keyspace"):
        ct.bootstrap_entity_counter(con, spec)


def test_bootstrap_entity_counter_rolls_back_and_reraises_on_failure():
    """A mid-transaction failure (e.g. the INSERT) rolls back and re-raises -- never swallowed."""
    con = _BootstrapCon(fail_on="INSERT INTO")
    spec = schema.resolve_table_spec("ops_recommendations")
    with pytest.raises(RuntimeError, match="boom"):
        ct.bootstrap_entity_counter(con, spec)
    assert "ROLLBACK" in con.executed
