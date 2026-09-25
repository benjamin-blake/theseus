"""Real-DuckLake integration for src/telemetry/append.py (Decision 199, rec-4024 slice 1).

pytest.mark.integration: runs append_events against a genuine local DuckLake file catalog on the
pinned duckdb/ducklake (Decision 99). A skip here is a FAIL for VP step 6 -- the skip fixture
exists only so unit tiers (which install no duckdb/ducklake) stay clean; it is never a silent
substitute for running this module for real.
"""

from __future__ import annotations

import functools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb")

from src.telemetry.append import EventTableSpec, append_events  # noqa: E402

TENANT = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
PROJECT = "01BRZ3NDEKTSV4RRFFQ69G5FBW"

_COLUMNS = {
    "event_id": "VARCHAR",
    "event_kind": "VARCHAR",
    "event_timestamp": "TIMESTAMP WITH TIME ZONE",
    "session_started_at": "TIMESTAMP WITH TIME ZONE",
    "external_ref": "VARCHAR",
    "entity_ref": "VARCHAR",
    "parser_version": "BIGINT",
    "created_timestamp": "TIMESTAMP WITH TIME ZONE",
    "tenant_id": "VARCHAR",
    "project_id": "VARCHAR",
    "session_id": "VARCHAR",
}
_NOT_NULL = frozenset({"event_id", "parser_version", "session_started_at", "created_timestamp", "session_id"})
_PARTITION_SQL = "year(session_started_at), month(session_started_at), day(session_started_at)"


def _spec() -> EventTableSpec:
    return EventTableSpec(table="telemetry_sessions", columns=dict(_COLUMNS), not_null=_NOT_NULL)


@functools.lru_cache(maxsize=1)
def _has_ducklake_extension() -> bool:
    try:
        con = duckdb.connect()
        con.execute("INSTALL ducklake; LOAD ducklake")
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def _skip_if_no_extension(_allow_network_for_integration: None) -> None:
    if not _has_ducklake_extension():
        pytest.skip("ducklake extension could not load -- see VP step 6 fix_if (environment defect)")


def _local_catalog(tmp_path: Path) -> Any:
    """ATTACH a fresh local-file DuckLake catalog, UTC, inlining disabled."""
    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake")
    con.execute("SET ducklake_default_data_inlining_row_limit=0")
    meta = tmp_path / "catalog.ducklake"
    data = tmp_path / "data"
    con.execute(f"ATTACH 'ducklake:{meta}' AS lake (DATA_PATH '{data}')")
    con.execute("SET TimeZone='UTC'")
    return con


def _create_table(con: Any) -> None:
    col_ddl = ", ".join(f"{c} {t}" for c, t in _COLUMNS.items())
    con.execute(f"CREATE TABLE lake.telemetry_sessions ({col_ddl})")
    con.execute(f"ALTER TABLE lake.telemetry_sessions SET PARTITIONED BY ({_PARTITION_SQL})")


def _file_count(con: Any) -> int:
    return con.execute("SELECT count(*) FROM ducklake_list_files('lake', 'telemetry_sessions')").fetchone()[0]


def _row(**overrides: Any) -> dict[str, Any]:
    t = datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc)
    base = {
        "event_kind": "open",
        "event_timestamp": t,
        "session_started_at": t,
        "external_ref": "src#0/open",
        "entity_ref": "sess-ref-1",
        "parser_version": 1,
    }
    base.update(overrides)
    return base


class _ProfileCapturingConnection:
    """Wraps a real connection; snapshots the JSON profile right after the MERGE executes --
    any later statement (COMMIT) overwrites profiling_output, so capture must happen here."""

    def __init__(self, real: Any, profile_path: Path) -> None:
        self._real = real
        self._profile_path = profile_path
        self.captured_profile: dict[str, Any] | None = None

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        result = self._real.execute(sql, *args, **kwargs)
        if sql.strip().upper().startswith("MERGE"):
            self.captured_profile = json.loads(self._profile_path.read_text(encoding="utf-8"))
        return result


def _find_total_files_read(node: dict[str, Any], acc: list[int]) -> None:
    extra = node.get("extra_info") or {}
    if "Total Files Read" in extra:
        acc.append(int(extra["Total Files Read"]))
    for child in node.get("children") or []:
        _find_total_files_read(child, acc)


@pytest.mark.integration
class TestSingleSessionBatchOneFile:
    def test_single_session_batch_adds_exactly_one_data_file(self, tmp_path: Path, _skip_if_no_extension: None) -> None:
        con = _local_catalog(tmp_path)
        _create_table(con)
        assert _file_count(con) == 0

        rows = [_row(external_ref="src#0/open"), _row(external_ref="src#1/close", event_kind="close")]
        result = append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="lake")

        assert result.inserted == 2
        assert _file_count(con) == 1


@pytest.mark.integration
class TestReplayAddsNoFiles:
    def test_replay_adds_zero_new_files_and_rows(self, tmp_path: Path, _skip_if_no_extension: None) -> None:
        con = _local_catalog(tmp_path)
        _create_table(con)
        rows = [_row()]
        append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="lake")
        files_after_first = _file_count(con)
        rows_after_first = con.execute("SELECT count(*) FROM lake.telemetry_sessions").fetchone()[0]

        result = append_events(con, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="lake")

        assert result.inserted == 0
        assert _file_count(con) == files_after_first
        assert con.execute("SELECT count(*) FROM lake.telemetry_sessions").fetchone()[0] == rows_after_first


@pytest.mark.integration
class TestDayBoundedMergeReadsExactlyOneFile:
    def test_day_bounded_merge_scans_only_the_touched_day(self, tmp_path: Path, _skip_if_no_extension: None) -> None:
        con = _local_catalog(tmp_path)
        _create_table(con)

        # Seed one wide-event_id-range file for the touched day, the adjacent day, and the SAME
        # day-of-month in another month -- each spans low..high so the id-equality dynamic filter
        # cannot prune it; only the day-partition boundary should restrict which file is read.
        low, high = "0" * 20, "z" * 20
        for date in ("2026-09-24", "2026-09-25", "2026-10-25"):
            con.execute(
                "INSERT INTO lake.telemetry_sessions VALUES "
                f"('{low}', 'point', TIMESTAMP '{date} 09:00:00+00', TIMESTAMP '{date} 09:00:00+00', "
                f"'seed-lo', 'seed-lo', 1, TIMESTAMP '{date} 09:00:00+00', '{TENANT}', '{PROJECT}', 'seed-session'), "
                f"('{high}', 'point', TIMESTAMP '{date} 09:00:00+00', TIMESTAMP '{date} 09:00:00+00', "
                f"'seed-hi', 'seed-hi', 1, TIMESTAMP '{date} 09:00:00+00', '{TENANT}', '{PROJECT}', 'seed-session')"
            )
        assert _file_count(con) == 3

        profile_path = tmp_path / "profile.json"
        con.execute("PRAGMA enable_profiling=json")
        con.execute(f"PRAGMA profiling_output='{profile_path}'")
        recorder = _ProfileCapturingConnection(con, profile_path)

        rows = [_row(external_ref="new-batch/open")]
        result = append_events(recorder, _spec(), rows, tenant_id=TENANT, project_id=PROJECT, catalog="lake")
        con.execute("PRAGMA disable_profiling")

        assert result.inserted == 1
        assert recorder.captured_profile is not None
        assert recorder.captured_profile["query_name"].strip().upper().startswith("MERGE")
        found: list[int] = []
        _find_total_files_read(recorder.captured_profile, found)
        assert found, "no DuckLake scan node reported Total Files Read in the captured profile"
        assert found == [1], found


@pytest.mark.integration
class TestCalendarDayCompactionGuarantee:
    def test_compaction_yields_one_file_per_calendar_date_no_mixing(self, tmp_path: Path, _skip_if_no_extension: None) -> None:
        con = _local_catalog(tmp_path)
        _create_table(con)

        dates = ("2026-09-24", "2026-09-25", "2026-10-24")
        for date in dates:
            for i in range(2):  # >=2 seed files per date
                con.execute(
                    "INSERT INTO lake.telemetry_sessions VALUES "
                    f"('id-{date}-{i}', 'point', TIMESTAMP '{date} 0{i}:00:00+00', "
                    f"TIMESTAMP '{date} 0{i}:00:00+00', 'ref-{date}-{i}', 'ref-{date}-{i}', 1, "
                    f"TIMESTAMP '{date} 0{i}:00:00+00', '{TENANT}', '{PROJECT}', 'seed-session')"
                )
        assert _file_count(con) == 2 * len(dates)

        con.execute("SET TimeZone='UTC'")
        con.execute("CALL ducklake_merge_adjacent_files('lake')")
        con.execute("CALL ducklake_cleanup_old_files('lake', cleanup_all => true)")

        remaining = con.execute("SELECT data_file FROM ducklake_list_files('lake', 'telemetry_sessions')").fetchall()
        assert len(remaining) == len(dates)

        for (path,) in remaining:
            file_dates = con.execute(
                f"SELECT DISTINCT date_trunc('day', session_started_at) FROM read_parquet('{path}')"
            ).fetchall()
            assert len(file_dates) == 1, f"{path} mixes more than one UTC calendar date: {file_dates}"
