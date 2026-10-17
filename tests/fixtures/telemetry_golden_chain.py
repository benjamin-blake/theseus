"""Shared helper (never a test_ module): the golden chain for the derived layer.

transcript tree -> record_turn -> append_events on a telemetry catalog -> every derivation reader verb, beside the independent
oracle in scripts.telemetry_verify run over the rows read back from the same catalog.

duckdb is imported lazily by tests/fixtures/telemetry_read_db.py, never here. A tree is named "corpus:<golden case>" or
"verification:<tree>" (the tests/telemetry/fixtures/derived_golden_*.yaml tree key); a session is named by a selector,
"root" or
"agent:<agentId>", resolved to its stored session_id by entity_ref.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import functools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from scripts.telemetry_verify import derive
from scripts.telemetry_verify.joins import load_telemetry_joins
from src.common import ducklake_event_reads as ev
from src.telemetry.append import append_events
from src.turn_capture.record_turn import CaptureResult, record_turn
from tests.fixtures import telemetry_read_db as db
from tests.fixtures import telemetry_verification_trees as verification
from tests.fixtures.turn_capture_corpus import PROJECT, PROJECT_REF, SID, TENANT, case_cap, load_case, mem_tree
from tests.fixtures.turn_capture_ducklake import load_specs

FIXTURES = Path(__file__).resolve().parents[1] / "telemetry" / "fixtures"
HELD_BACK_BYTES = 65536  # the kernel facade has no blob route; the writer stores larger payloads out of line
DAY = {"day_from": "2026-01-01", "day_to": "2026-01-01"}
TABLES = db.TABLES
_TIMED = {"as_of", "last_event_timestamp", "session_started_at", "event_timestamp"}


def expectation_trees() -> list[dict[str, Any]]:
    """Every tree entry of both derived_golden files (state first)."""
    out: list[dict[str, Any]] = []
    for name in ("derived_golden_state.yaml", "derived_golden_rollups.yaml"):
        doc = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
        out += [dict(entry, file=name, parser_version=doc["parser_version"]) for entry in doc["trees"]]
    return out


def tree_files(tree: str) -> tuple[dict[str, str], Any]:
    """(files, a context manager applying the case's test-only cap) of a named tree."""
    kind, name = tree.split(":", 1)
    if kind == "corpus":
        return load_case(f"{name}.json")[0], case_cap(f"{name}.json")
    return verification.TREES[name](), contextlib.nullcontext()


@functools.lru_cache(maxsize=None)
def _emit(tree: str, final: bool) -> CaptureResult:
    files, cap = tree_files(tree)
    with cap:
        return record_turn(mem_tree(files), None, project_ref=PROJECT_REF, session_final=final)


def emit(tree: str, final: bool = True) -> CaptureResult:
    return copy.deepcopy(_emit(tree, final))


def pass_is_final(entry: dict[str, Any]) -> bool:
    return entry["pass"] == "final"


def record(tree: str, files: dict[str, str], cursor: Any, final: bool) -> CaptureResult:
    _, cap = tree_files(tree)
    with cap:
        return record_turn(mem_tree(files), cursor, project_ref=PROJECT_REF, session_final=final)


def hold_back(result: CaptureResult, *, store_held_back_as_blob: bool = False) -> CaptureResult:
    """The result without payloads above the inline threshold (they ride the blob route in production).

    With store_held_back_as_blob each such row is kept the way the writer's blob route stores it: content null, a synthetic
    content_uri, content_sha256 and content_bytes as emitted, so a verify over the chain sees every emitted row stored.
    """
    held = [r for r in result.transcripts if "content" in r and r["content_bytes"] > HELD_BACK_BYTES]
    kept = [r for r in result.transcripts if r not in held]
    if store_held_back_as_blob:
        kept += [
            {**{k: v for k, v in r.items() if k != "content"}, "content_uri": f"blob://synthetic/{r['content_sha256']}"}
            for r in held
        ]
    return dataclasses.replace(result, transcripts=kept)


def latest_event(result: CaptureResult) -> datetime:
    stamps = [row["event_timestamp"] for _, rows in result.batches for row in rows]
    return max(stamps) if stamps else datetime(2026, 1, 1, tzinfo=timezone.utc)


def open_catalog(kind: str = "memory", tmp_path: Path | None = None) -> Any:
    con = db.open_memory_catalog() if kind == "memory" else db.open_local_lake(tmp_path)  # type: ignore[arg-type]
    db.insert_projects(con, [{"project_id": PROJECT, "tenant_id": TENANT, "project_ref": PROJECT_REF, "purpose": "real"}])
    return con


@functools.lru_cache(maxsize=1)
def specs() -> dict[str, Any]:
    return load_specs()


def append_batches(con: Any, result: CaptureResult, *, now: datetime | None = None, reverse: bool = False) -> dict[str, int]:
    """Append every non-empty batch in write order (reversed on request, rows too); inserted counts per table."""
    moment = now if now is not None else latest_event(result) + timedelta(seconds=1)
    batches = list(reversed(result.batches)) if reverse else result.batches
    inserted: dict[str, int] = {}
    for table, rows in batches:
        if rows:
            rows = list(reversed(rows)) if reverse else rows
            done = append_events(
                con, specs()[table], copy.deepcopy(rows), tenant_id=TENANT, project_id=PROJECT, catalog=db.ALIAS, now=moment
            )
            inserted[table] = done.inserted
    return inserted


def stored_rows(con: Any) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for table in TABLES:
        cursor = con.execute(f"SELECT * FROM {db.ALIAS}.{table}")
        names = [d[0] for d in cursor.description]
        out[table] = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    return out


def session_ids(rows: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """selector -> stored session_id, by the session's entity_ref (root = the transcript's session uuid)."""
    out = {}
    for row in rows["telemetry_sessions"]:
        ref = row["entity_ref"]
        out["root" if ref == SID else "agent:" + ref.removeprefix(SID + ":")] = row["session_id"]
    return out


def last_event(rows: dict[str, list[dict[str, Any]]], session_id: str) -> datetime:
    return max(r["event_timestamp"] for table in TABLES for r in rows[table] if r["session_id"] == session_id)


def as_of_rule(last: datetime) -> list[str]:
    """Inside the idle threshold, exactly at it (not abandoned: idle must EXCEED it), and beyond it."""
    return [
        stamp.isoformat() for stamp in (last + timedelta(hours=12), last + timedelta(seconds=86400), last + timedelta(days=2))
    ]


def run_verb(con: Any, verb: str, **params: Any) -> list[dict[str, Any]]:
    return ev.execute(con, verb=verb, params=params)


def run_oracle(rows: dict[str, list[dict[str, Any]]], verb: str, **params: Any) -> list[dict[str, Any]]:
    if verb.startswith("sessions_window"):
        return derive.sessions_window(
            rows,
            {PROJECT: "real"},
            params["day_from"],
            params["day_to"],
            params["as_of"],
            all_purposes=verb.endswith("purposes"),
        )
    return getattr(derive, verb)(rows, **params)


def canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def _resolve(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, dict) and set(value) == {"session"}:
        return ids[value["session"]]
    if isinstance(value, list):
        return [_resolve(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, ids) for k, v in value.items()}
    return value


def _equal(actual: Any, wanted: Any, key: str) -> bool:
    if key in _TIMED and isinstance(wanted, str):
        wanted = datetime.fromisoformat(wanted)
    return canonical(actual) == canonical(wanted)


def verb_params(expect: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    params = dict(expect["params"])
    if "session" in expect:
        params["session_id"] = ids[expect["session"]]
    return params


def mismatches(actual: list[dict[str, Any]], expect: dict[str, Any], ids: dict[str, str], label: str) -> list[str]:
    """Differences between an engine's rows and an expectation's asserted subset."""
    wanted = _resolve(expect["rows"], ids)
    if len(actual) != len(wanted):
        return [f"{label}: {len(actual)} rows, expected {len(wanted)}"]
    out = []
    for index, (got, want) in enumerate(zip(actual, wanted)):
        for key, value in want.items():
            if not _equal(got[key], value, key):
                out.append(f"{label}[{index}].{key}: {got[key]!r} != {value!r}")
    return out


def reconcile(
    con: Any, rows: dict[str, list[dict[str, Any]]], expectations: list[dict[str, Any]], ids: dict[str, str]
) -> list[str]:
    """Verb rows and oracle rows against each expectation, and against each other. Empty means reconciled."""
    problems: list[str] = []
    for expect in expectations:
        params, verb = verb_params(expect, ids), expect["verb"]
        got = run_verb(con, verb, **params)
        oracle = run_oracle(rows, verb, **params)
        tag = f"{verb} {expect.get('session', 'window')} {expect['params'].get('as_of', '')}"
        problems += mismatches(got, expect, ids, f"verb {tag}")
        problems += mismatches(oracle, expect, ids, f"oracle {tag}")
        if canonical(got) != canonical(oracle):
            problems.append(f"verb != oracle {tag}")
    return problems


def expectations_of(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return entry["expect"]


def combined_expectations(tree: str, final: bool) -> list[dict[str, Any]]:
    """The expectations of both files for one (tree, pass), in file order."""
    out: list[dict[str, Any]] = []
    for entry in expectation_trees():
        if entry["tree"] == tree and pass_is_final(entry) == final:
            out += entry["expect"]
    return out


@contextlib.contextmanager
def loaded(
    tree: str, final: bool = True, kind: str = "memory", tmp_path: Path | None = None, *, store_held_back_as_blob: bool = False
) -> Iterator[tuple[Any, dict[str, list[dict[str, Any]]], dict[str, str]]]:
    """A catalog holding one tree's batches: (connection, stored rows, selector -> session_id)."""
    con = open_catalog(kind, tmp_path)
    try:
        append_batches(con, hold_back(emit(tree, final), store_held_back_as_blob=store_held_back_as_blob))
        rows = stored_rows(con)
        yield con, rows, session_ids(rows)
    finally:
        con.close()


def dangling(con: Any, child: str, column: str, parent: str, key: str) -> int:
    sql = (
        f"SELECT count(*) FROM {db.ALIAS}.{child} c WHERE c.{column} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM {db.ALIAS}.{parent} p WHERE p.{key} = c.{column})"
    )
    return con.execute(sql).fetchone()[0]


def unresolved_joins(con: Any) -> list[str]:
    """Every telemetry join of docs/contracts/_joins.yaml with at least one child value that has no parent."""
    return [
        join_id for join_id, child, column, parent, key in load_telemetry_joins() if dangling(con, child, column, parent, key)
    ]
