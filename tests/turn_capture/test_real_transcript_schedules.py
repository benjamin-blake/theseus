"""Implement-time evidence on REAL transcripts: finalize at every SessionStart:resume boundary, then grow (VP 8).

pytest.mark.integration, deselected in every tier (VP 1's golden schedules are the standing CI guard). Counts only are
printed: nothing from a transcript is committed or echoed. The raw walk finds each tree's resume boundaries and its
fork boundary itself; cuts never start before a fork boundary (rule K-1). A tree set with no resume boundary is
reported as unproven, never as a pass of the schedule, and a tree set with no fork as unproven for that leg.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.turn_capture.record_turn import record_turn
from tests.fixtures.turn_capture_real import PrefixTree, discover, raw_inherited, snapshot

pytestmark = pytest.mark.integration

PROJECT_REF = "real/schedules"


def resume_boundaries(root: Path) -> list[int]:
    """Line indexes of the first attachment of each SessionStart:resume hook group, at or after the fork boundary."""
    floor = raw_inherited(root)[1]
    found, in_group = [], False
    for index, raw in enumerate(root.read_bytes().split(b"\n")[:-1]):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        is_resume = str((data.get("attachment") or {}).get("hookName") or "").startswith("SessionStart:resume")
        if data.get("type") == "attachment" and is_resume:
            if not in_group and index >= max(floor, 1):
                found.append(index)
            in_group = True
        elif data.get("type") in ("user", "assistant"):
            in_group = False
    return found


def _keyed(result: Any) -> dict[tuple[str, str], dict[str, Any]]:
    return {(t, r["external_ref"]): r for t, rows in result.batches for r in rows}


def test_finalize_at_every_resume_boundary_emits_each_row_once(tmp_path: Path) -> None:
    sources = discover()
    if not sources:
        pytest.fail(
            "no real Claude Code transcripts found: set TURN_CAPTURE_REAL_TRANSCRIPTS or run on a machine that has them"
        )
    boundaries = forks = 0
    for root in snapshot(sources, tmp_path):
        cuts = resume_boundaries(root)
        forks += bool(raw_inherited(root)[1])
        boundaries += len(cuts)
        full = _keyed(record_turn(PrefixTree(root, 10**9), None, project_ref=PROJECT_REF, session_final=True))
        seen: dict[tuple[str, str], dict[str, Any]] = {}
        cursor, divergence = None, 0
        for limit in [*cuts, 10**9]:
            step = record_turn(PrefixTree(root, limit), cursor, project_ref=PROJECT_REF, session_final=True)
            cursor = step.next_cursor if step.next_cursor is not None else cursor
            divergence += sum(step.diagnostics.get(k, 0) for k in ("prior_content_divergence", "cut_content_divergence"))
            for key, row in _keyed(step).items():
                assert key not in seen, f"a row was emitted twice at resume cut {limit}"
                seen[key] = row
        assert divergence == 0, "content divergence on a resume schedule"
        assert set(full) <= set(seen) and all(seen[k] == full[k] for k in full), "the union misses or changes a full-parse row"
        assert all(k[0] == "telemetry_sessions" and k[1].endswith("/close") for k in set(seen) - set(full))
    print(f"\nschedules: {boundaries} resume boundaries over {len(sources)} trees; {forks} trees with a fork boundary")
    if not boundaries:
        print("schedules: UNPROVEN -- the tree set holds zero SessionStart:resume boundaries")
    if not forks:
        print("schedules: fork-boundary leg UNPROVEN -- the tree set holds no fork")
