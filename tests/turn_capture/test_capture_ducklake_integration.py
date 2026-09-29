"""Real local DuckLake: the golden cases' batches append through src.telemetry.append.append_events in write order.

pytest.mark.integration. Fixed tenant/project ULIDs stand in for writer-side resolution (Decision 200). Every case
gets a fresh catalog (the corpus reuses uuids across cases by design). The extension helper FAILS, never skips.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from src.telemetry.gate import AppendError
from src.turn_capture.record_turn import record_turn
from tests.fixtures.telemetry_dedupe_reference import compute_generations, resolve_table
from tests.fixtures.turn_capture_corpus import PROJECT, PROJECT_REF, TENANT, case_names, load_case, mem_tree
from tests.fixtures.turn_capture_ducklake import TABLES, create_tables, load_specs, open_local_lake

pytestmark = pytest.mark.integration

OVER_64K = {"large_tool_result_over_64k.json"}
FKS = (
    ("telemetry_observations", "session_id", "telemetry_sessions", "session_id"),
    ("telemetry_transcripts", "session_id", "telemetry_sessions", "session_id"),
    ("telemetry_transcripts", "observation_id", "telemetry_observations", "observation_id"),
    ("telemetry_agents", "session_id", "telemetry_sessions", "session_id"),
    ("telemetry_agents", "observation_id", "telemetry_observations", "observation_id"),
    ("telemetry_observations", "parent_observation_id", "telemetry_observations", "observation_id"),
    ("telemetry_sessions", "parent_session_id", "telemetry_sessions", "session_id"),
)


def load(con: Any, specs: dict, result) -> dict[str, int]:
    """Append every non-empty batch in write order; returns inserted counts per table."""
    inserted: dict[str, int] = {}
    for table, rows in result.batches:
        if rows:
            done = append_rows(con, specs[table], rows)
            assert done.inserted == len(rows), (table, done)
            inserted[table] = done.inserted
    return inserted


def append_rows(con: Any, spec: Any, rows: list[dict[str, Any]]):
    from src.telemetry.append import append_events  # noqa: PLC0415

    return append_events(con, spec, rows, tenant_id=TENANT, project_id=PROJECT, catalog="lake")


def dangling(con: Any, child: str, column: str, parent: str, key: str) -> int:
    sql = (
        f"SELECT count(*) FROM lake.{child} c WHERE c.{column} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM lake.{parent} p WHERE p.{key} = c.{column})"
    )
    return con.execute(sql).fetchone()[0]


def read_rows(con: Any, table: str) -> list[dict[str, Any]]:
    cur = con.execute(f"SELECT * FROM lake.{table}")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def test_every_golden_case_loads_with_every_fk_resolving(tmp_path: Path) -> None:
    specs = load_specs()
    for name in case_names():
        if name in OVER_64K:
            continue
        files, _ = load_case(name)
        result = record_turn(mem_tree(files), None, project_ref=PROJECT_REF, session_final=True)
        con = open_local_lake(tmp_path / name.removesuffix(".json"))
        create_tables(con, specs)
        load(con, specs, result)
        for child, column, parent, key in FKS:
            assert dangling(con, child, column, parent, key) == 0, (name, child, column)
        starts = {
            con.execute(f"SELECT count(DISTINCT session_started_at) FROM lake.{t}").fetchone()[0]
            for t in TABLES
            if any(rows for tbl, rows in result.batches if tbl == t)
        }
        assert starts == {1}, name
        stored = con.execute("SELECT coalesce(max(strlen(content)), 0) FROM lake.telemetry_transcripts").fetchone()[0]
        assert stored <= 65536, name
        con.close()


def test_replay_mutation_and_generation_bump_on_a_nested_tree(tmp_path: Path) -> None:
    specs = load_specs()
    files, _ = load_case("nested_subagent_depth2.json")
    result = record_turn(mem_tree(files), None, project_ref=PROJECT_REF, session_final=True)
    con = open_local_lake(tmp_path)
    create_tables(con, specs)
    load(con, specs, result)
    for table, rows in result.batches:
        assert append_rows(con, specs[table], rows).inserted == 0, table

    victim = dict(result.transcripts[0], content="a different payload", content_sha256="0" * 64)
    with pytest.raises(AppendError, match="TELEMETRY_GRAIN_CONFLICT"):
        append_rows(con, specs["telemetry_transcripts"], [victim])

    for table, rows in result.batches:
        bumped = [dict(row, parser_version=2) for row in rows]
        assert append_rows(con, specs[table], bumped).inserted == len(bumped), table

    def oracle(table: str) -> list[dict[str, Any]]:
        out = []
        for row in read_rows(con, table):
            marker = repr(sorted((k, str(v)) for k, v in row.items() if k not in ("parser_version", "created_timestamp")))
            out.append(
                {**row, "content": marker, "created_timestamp": row["created_timestamp"].isoformat(),
                 "event_timestamp": row["event_timestamp"].isoformat(), "observation_id": row.get("observation_id")}
            )  # fmt: skip
        return out

    sessions = oracle("telemetry_sessions")
    generations = compute_generations(sessions)
    assert generations and set(generations.values()) == {2}
    for table in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
        rows = oracle(table)
        survivors, conflicted = resolve_table(rows, generations)
        assert not conflicted and {r["parser_version"] for r in survivors} == {2}
        assert len(survivors) == len(rows) // 2, table
    model_calls = [r for r in oracle("telemetry_observations") if r["observation_type"] == "model_call"]
    survivors, conflicted = resolve_table(model_calls, generations, is_model_call=True)
    assert not conflicted and {r["parser_version"] for r in survivors} == {2}
    con.close()


def test_cursor_persisted_after_every_batch_round_trips(tmp_path: Path) -> None:
    specs = load_specs()
    files, _ = load_case("hooks_resume_and_compact.json")
    first = record_turn(mem_tree(files), None, project_ref=PROJECT_REF, session_final=False)
    con = open_local_lake(tmp_path)
    create_tables(con, specs)
    load(con, specs, first)
    second = record_turn(mem_tree(files), first.next_cursor, project_ref=PROJECT_REF, session_final=True)
    load(con, specs, second)
    full = record_turn(mem_tree(files), None, project_ref=PROJECT_REF, session_final=True)
    for table, rows in full.batches:
        stored = con.execute(f"SELECT count(*) FROM lake.{table}").fetchone()[0]
        assert stored == len(rows), table
    assert dataclasses.is_dataclass(second.next_cursor)
    con.close()
