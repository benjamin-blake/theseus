"""Integration-marked real-DuckLake conformance for the calendar-day partition fix (rec-4068, rec-3808).

Attaches a LOCAL DuckLake catalog (no S3/AWS credentials needed -- only the extension download) as
CATALOG_ALIAS, matching what create_scd2_tables/create_control_table hardcode, and exercises every
declared table's REAL DDL + write path against duckdb's own day()/month()/year() partition
semantics -- not the FakeCon SQL-recording double the rest of the suite uses.

NON-VACUITY (critique r3 F1): default data inlining leaves ZERO rows as partition-value metadata
rows, so this attaches with ducklake_default_data_inlining_row_limit=0 and TimeZone UTC, mirroring
open_connection, and asserts live file count >= distinct calendar dates written > 0 before the
per-file single-day assertion.

The layout assertion reads partition values through the SAME smoke_actions partition-value helper
EC6 uses (S4), so its metadata SQL runs on a real engine pre-merge, not first at post-deploy step 21.
"""

from __future__ import annotations

import functools
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.common import ducklake_control_tables as ctl
from src.common import ducklake_scd2_schema as schema
from src.common import ducklake_tables as tables
from src.common.ducklake_scd2_schema import CATALOG_ALIAS
from src.lambdas.ducklake_writer.smoke_actions import _partition_layout

pytestmark = pytest.mark.integration

_PROBE_DAYS = (
    datetime(2026, 1, 24, tzinfo=timezone.utc),
    datetime(2026, 2, 24, tzinfo=timezone.utc),
    datetime(2027, 1, 24, tzinfo=timezone.utc),
)


@functools.lru_cache(maxsize=1)
def _has_ducklake_extension() -> bool:
    """Return True if the ducklake extension is available over the network."""
    try:
        import duckdb

        c = duckdb.connect()
        c.execute("INSTALL ducklake; LOAD ducklake")
        c.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def con(tmp_path: Path):
    if not _has_ducklake_extension():
        pytest.skip("ducklake extension unavailable (no network)")
    import duckdb

    c = duckdb.connect()
    c.execute("INSTALL ducklake")
    c.execute("LOAD ducklake")
    # Mirror open_connection (Decision 96 / rec-4068): inlining off + UTC pinned BEFORE the ATTACH.
    c.execute("SET ducklake_default_data_inlining_row_limit=0")
    c.execute("SET TimeZone='UTC'")
    db_path = tmp_path / "cat.db"
    data_path = str(tmp_path / "data") + "/"
    c.execute(f"ATTACH 'ducklake:{db_path}' AS {CATALOG_ALIAS} (DATA_PATH '{data_path}')")
    yield c
    c.close()


def _sql_literal(sql_type: str) -> str:
    """A generic non-null literal for *sql_type*, used only to satisfy a NOT NULL column."""
    if sql_type.endswith("[]"):
        return "[]"
    if sql_type in ("BIGINT", "INTEGER"):
        return "0"
    if sql_type == "BOOLEAN":
        return "false"
    return "'x'"


def _insert_history_row(con: Any, spec: schema.ScdTableSpec, ulid: str, merge_key_value: str, created_ts: datetime) -> None:
    """Direct SQL INSERT into *spec*'s history table, bypassing write_scd2/the schema gate --
    this test proves the DECLARED partition specs behave as calendar days on the real engine, not
    the write-path plumbing (which the rest of the suite already covers via FakeCon)."""
    cols: list[str] = []
    vals: list[str] = []
    for name, sql_type in spec.ordered_columns:
        cols.append(name)
        if name == "ulid":
            vals.append(f"'{ulid}'")
        elif name == spec.merge_key:
            vals.append(f"'{merge_key_value}'")
        elif name in ("created_timestamp", "last_updated_timestamp"):
            vals.append(f"TIMESTAMPTZ '{created_ts.isoformat()}'")
        elif bool(spec.fields[name].get("nullable", True)):
            vals.append("NULL")
        else:
            vals.append(_sql_literal(spec.fields[name]["sql_type"]))
    con.execute(f"INSERT INTO {CATALOG_ALIAS}.{spec.history_table} ({', '.join(cols)}) VALUES ({', '.join(vals)})")


def _conformance_targets() -> list[str | None]:
    """None = smoke pair; else every non-control ops table in the generated projection."""
    semantics = schema.load_field_semantics()
    targets: list[str | None] = [None]
    for name in schema.ops_table_names():
        if semantics["ops_tables"][name].get("write_mode") == "control":
            continue
        targets.append(name)
    return targets


@pytest.mark.parametrize("table", _conformance_targets(), ids=lambda t: t or "smoke")
def test_history_partition_is_one_file_per_calendar_day(con: Any, table: str | None) -> None:
    """For every declared table, rows sharing a day-of-month across a month AND a year boundary
    stay in DISTINCT calendar-day partitions through ducklake_merge_adjacent_files."""
    spec = schema.resolve_table_spec(table)
    tables.create_scd2_tables(con, table=table, force_recreate=True)

    for i, ts in enumerate(_PROBE_DAYS):
        _insert_history_row(con, spec, ulid=f"01PROBE{i}", merge_key_value=f"probe-{i}", created_ts=ts)

    con.execute(f"CALL ducklake_merge_adjacent_files('{CATALOG_ALIAS}')")

    layout = _partition_layout(con, CATALOG_ALIAS, spec.history_table)

    # Non-vacuity: real files were written and their partition values were actually read back.
    distinct_dates = set(layout["value_tuples"].values())
    assert layout["total"] >= len(distinct_dates) > 0, (table, layout)
    assert len(distinct_dates) == len(_PROBE_DAYS), (table, layout)

    # Per-file single-day assertion: every live file's partition tuple is unique to its day.
    assert len(layout["value_tuples"]) == layout["total"], (table, layout)
    assert len(set(layout["value_tuples"].values())) == layout["total"], (
        f"{table}: files collapsed into fewer partitions than days written -- {layout}"
    )


def test_create_scd2_tables_repeated_call_is_idempotent(con: Any) -> None:
    """rec-3808 twin: a repeated non-force create_scd2_tables call does not error."""
    tables.create_scd2_tables(con, force_recreate=True)
    tables.create_scd2_tables(con, force_recreate=False)  # must not raise


def test_create_control_table_repeated_call_is_idempotent(con: Any) -> None:
    """rec-3808 acceptance: a repeated non-force create_control_table call raises nothing and
    leaves exactly one active partition_info row."""
    spec = ctl.resolve_control_spec("ops_entity_counters")
    tables.create_control_table(con, table="ops_entity_counters", force_recreate=True)
    tables.create_control_table(con, table="ops_entity_counters", force_recreate=False)  # must not raise

    rows = con.execute(
        f"SELECT count(*) FROM __ducklake_metadata_{CATALOG_ALIAS}.ducklake_partition_info pi "
        f"JOIN __ducklake_metadata_{CATALOG_ALIAS}.ducklake_table t ON pi.table_id = t.table_id "
        f"WHERE t.table_name = ? AND pi.end_snapshot IS NULL",
        [spec.table],
    ).fetchone()
    assert int(rows[0]) == 1
