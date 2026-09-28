"""Stdlib-only reference oracle for the telemetry envelope's GENERATIONS AND READ-SIDE DEDUPE rule
(Decision 207, R4/R5, docs/contracts/telemetry-event-envelope.yaml governance_notes).

Not production code (Decision 84 I-3) -- a homed test fixture (tests/CLAUDE.md's shared-helper
rule: this name never starts with test_). rec-4024's reader verbs must independently pass the same
vectors on DuckLake; this module is the fast-tier (no duckdb) oracle tests/telemetry/test_dedupe_vectors.py
checks against.

Row shape (a plain dict), one entry per stored column this rule needs:
  producer: str            -- grain-key column
  event_id: str             -- grain-key column
  parser_version: int       -- grain-key column
  session_id: str           -- the (producer, session) generation this row belongs to
  event_kind: str | None    -- 'open' marks a telemetry_sessions generation-commit row; else N/A
  created_timestamp: str    -- ISO 8601, sortable; the write-time tiebreak (R5b)
  content: Hashable         -- everything else stored on the row (a caller-chosen marker); two
                               rows at the SAME grain key with differing `content` are the
                               concurrent-write race R5a/R5b's conflict-report case
  observation_id: str | None -- model_call rows only; the R5c entity-collapse key
  event_timestamp: str | None -- model_call rows only, ISO 8601; the R5c DESC tiebreak
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

GrainKey = tuple[str, str, int]

_MODEL_CALL_PRECEDENCE = {"claude_code": 0, "litellm": 1}


def compute_generations(session_rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    """R4: V*(producer, session_id) = max parser_version of that producer's telemetry_sessions
    open rows for that session, within the partition. A producer/session pair with no open row
    is absent from the returned map -- R5 alone applies to it (R8 non-replayable producers)."""
    generations: dict[tuple[str, str], int] = {}
    for row in session_rows:
        if row.get("event_kind") != "open":
            continue
        key = (row["producer"], row["session_id"])
        if key not in generations or row["parser_version"] > generations[key]:
            generations[key] = row["parser_version"]
    return generations


def _resolve_grain_key_groups(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[GrainKey]]:
    """Collapse rows sharing a full (producer, event_id, parser_version) grain key: identical
    `content` collapses to one row; differing `content` is the concurrent-write race -- report the
    grain key as conflicted and pick the earliest created_timestamp row (which one survives is
    unspecified by the rule; this oracle is deterministic for reproducibility only)."""
    groups: dict[GrainKey, list[dict[str, Any]]] = {}
    for row in rows:
        key: GrainKey = (row["producer"], row["event_id"], row["parser_version"])
        groups.setdefault(key, []).append(row)

    conflicted: set[GrainKey] = set()
    resolved: list[dict[str, Any]] = []
    for key, group in groups.items():
        contents = {row["content"] for row in group}
        if len(contents) > 1:
            conflicted.add(key)
        resolved.append(min(group, key=lambda r: r["created_timestamp"]))
    return resolved, conflicted


def resolve_table(
    rows: list[dict[str, Any]],
    generations: dict[tuple[str, str], int],
    *,
    is_model_call: bool = False,
) -> tuple[list[dict[str, Any]], set[GrainKey]]:
    """Apply R5 to one table's rows, bounded to one session's single calendar-day partition.

    Returns (authoritative_rows, conflicted_grain_keys). `is_model_call` additionally applies
    R5c's cross-producer entity collapse per observation_id.
    """
    deduped, conflicted = _resolve_grain_key_groups(rows)

    # R5a: retire rows for (producer, session) below/above V* when V* is defined.
    retired_filtered = [
        row
        for row in deduped
        if (v_star := generations.get((row["producer"], row["session_id"]))) is None or row["parser_version"] == v_star
    ]

    # R5b: event collapse per (producer, event_id) -- keep the highest surviving parser_version,
    # then earliest created_timestamp among ties at that version.
    by_event: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in retired_filtered:
        by_event.setdefault((row["producer"], row["event_id"]), []).append(row)

    survivors: list[dict[str, Any]] = []
    for group in by_event.values():
        max_pv = max(row["parser_version"] for row in group)
        at_max = [row for row in group if row["parser_version"] == max_pv]
        survivors.append(min(at_max, key=lambda r: r["created_timestamp"]))

    if is_model_call:
        by_observation: dict[str, list[dict[str, Any]]] = {}
        for row in survivors:
            by_observation.setdefault(row["observation_id"], []).append(row)

        def _sort_key(row: dict[str, Any]) -> tuple[int, float, str, str, str]:
            precedence = _MODEL_CALL_PRECEDENCE.get(row["producer"], 2)
            event_ts = datetime.fromisoformat(row["event_timestamp"]).timestamp()
            return (
                precedence,
                -event_ts,  # DESC: latest event_timestamp wins (final usage numbers win, rec-4062)
                row["created_timestamp"],
                row["producer"],
                row["event_id"],
            )

        survivors = [min(group, key=_sort_key) for group in by_observation.values()]

    return survivors, conflicted


__all__ = ["GrainKey", "compute_generations", "resolve_table"]
