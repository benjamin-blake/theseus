"""Runs every tests/telemetry/fixtures/dedupe_vectors.yaml vector through the stdlib reference
oracle (tests/fixtures/telemetry_dedupe_reference.py), asserting exact surviving event_ids and
conflicted grain keys per table. No duckdb import (fast tier).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.fixtures.telemetry_dedupe_reference import compute_generations, resolve_table

_VECTORS_PATH = Path(__file__).parent / "fixtures" / "dedupe_vectors.yaml"
_ALL_SITUATIONS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}


def _load_vectors() -> list[dict[str, Any]]:
    return yaml.safe_load(_VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]


_VECTORS = _load_vectors()


@pytest.mark.parametrize("vector", _VECTORS, ids=[v["name"] for v in _VECTORS])
def test_vector_resolves_to_expected_rows(vector: dict[str, Any]) -> None:
    rows_by_table = vector["rows"]
    generations = compute_generations(rows_by_table.get("telemetry_sessions") or [])

    for table, expected in vector["expected"].items():
        rows = rows_by_table.get(table) or []
        is_model_call = any("observation_id" in row for row in rows)
        survivors, conflicted = resolve_table(rows, generations, is_model_call=is_model_call)

        actual_event_ids = sorted(row["event_id"] for row in survivors)
        assert actual_event_ids == sorted(expected["surviving_event_ids"]), (
            f"{vector['name']}/{table}: expected {expected['surviving_event_ids']}, got {actual_event_ids}"
        )

        actual_conflicted = {tuple(k) for k in conflicted}
        expected_conflicted = {tuple(k) for k in expected["conflicted_grain_keys"]}
        assert actual_conflicted == expected_conflicted, (
            f"{vector['name']}/{table}: expected conflicted {expected_conflicted}, got {actual_conflicted}"
        )


def test_every_situation_1_to_10_has_a_vector() -> None:
    covered = {v["situation"] for v in _VECTORS if "situation" in v}
    assert covered == _ALL_SITUATIONS, f"missing situations: {_ALL_SITUATIONS - covered}"


def test_envelope_governance_notes_name_this_fixture() -> None:
    envelope = Path(__file__).parent.parent.parent / "docs" / "contracts" / "telemetry-event-envelope.yaml"
    text = envelope.read_text(encoding="utf-8")
    assert "tests/telemetry/fixtures/dedupe_vectors.yaml" in text
