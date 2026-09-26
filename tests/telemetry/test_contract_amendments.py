"""Red-before/green-after invariants for the telemetry contract-risk amendments R3/R6/R7
(rec-4058, rec-4059, rec-4060; PLAN-telemetry-contract-risk-amendments).

Loads each amended contract through scripts.contracts load_contract and asserts the write-time
behaviour and amendment_log bookkeeping the recs' acceptance commands require. Phrase assertions
are case-insensitive over whitespace-normalised text. This module does not exist on the
pre-change tree (red before every test here). R8 (rec-4061, parser_version bump policy) adds its
own test to this module in a separate plan -- not covered here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.contracts import load_contract
from src.telemetry.identity import decode_time_prefix, derive_entity_key

_CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _has_governance_note_add_break(entries) -> bool:
    return any(entry.change_class.value == "governance_note_add" and entry.semantic_break for entry in entries)


def test_parent_observation_existence_is_dq_not_write_time() -> None:
    doc = load_contract(_CONTRACTS_DIR / "parent-observation-id.yaml")
    field = doc.fields["parent_observation_id"]

    validation = _norm(field.write_time_validation)
    governance = _norm(field.governance_notes)

    assert "must reference an existing telemetry_observations.observation_id" not in validation
    assert "never checks" in validation and "parent" in validation
    assert "quiescent" in validation
    assert "dangling parent" in validation and "transient" in validation and "permanent" in validation
    assert "rec-4101" in validation

    assert "rec-4101" in governance
    assert "quiescent" in governance

    raw_text = (_CONTRACTS_DIR / "_joins.yaml").read_text(encoding="utf-8")
    normalised = _norm(raw_text)
    assert "write-time + dq-relationships concern" not in normalised
    assert "referential integrity is a write-time" not in normalised
    assert "never a write-time check" in normalised

    assert _has_governance_note_add_break(field.amendment_log)


def test_project_ref_resolution_is_pinned() -> None:
    doc = load_contract(_CONTRACTS_DIR / "project-id.yaml")
    field = doc.fields["project_id"]

    semantics = _norm(field.semantics)

    assert "never re-bound to a different project_id" in semantics
    assert "canonical_project_id" in semantics and "read-side only" in semantics
    assert "root" in semantics and "project_ref" in semantics
    assert "pinned once" in semantics
    assert "first record" in semantics
    assert "never" in semantics and "per-turn" in semantics
    assert "defers emission" in semantics

    assert _has_governance_note_add_break(field.amendment_log)


def test_session_started_at_handoff_is_exact_ms() -> None:
    doc = load_contract(_CONTRACTS_DIR / "telemetry-event-envelope.yaml")
    field = doc.fields["session_started_at"]

    semantics = _norm(field.semantics)

    assert "epoch-millisecond" in semantics
    assert "decode_time_prefix" in semantics
    assert "event_id" in semantics and "never an event_id" in semantics
    assert "never seconds" in semantics or ("seconds" in semantics and "never" in semantics)
    assert "defers emission" in semantics or "defer" in semantics
    assert "full millisecond value" in semantics or "full ms value" in semantics

    assert _has_governance_note_add_break(field.amendment_log)

    session_started_at = datetime(2026, 9, 26, 12, 0, 0, 123000, tzinfo=timezone.utc)
    session_id = derive_entity_key(
        "telemetry_sessions:session_id",
        "01M3TENANTTENANTTENANTTENA",
        "01M3PRJTPRJTPRJTPRJTPRJTPZ",
        "root-session-ref",
        session_started_at,
    )
    recovered = decode_time_prefix(session_id)
    assert recovered == session_started_at
