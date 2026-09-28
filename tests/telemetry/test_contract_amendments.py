"""Red-before/green-after invariants for the telemetry contract-risk amendments R3/R6/R7
(rec-4058, rec-4059, rec-4060; PLAN-telemetry-contract-risk-amendments).

Loads each amended contract through scripts.contracts load_contract and asserts the write-time
behaviour and amendment_log bookkeeping the recs' acceptance commands require. Phrase assertions
are case-insensitive over whitespace-normalised text. This module does not exist on the
pre-change tree (red before every test here). R8 (rec-4061 parser_version bump policy, rec-4062
model_call tiebreak, and the grain-enforced-at-write data-modeling rule, Decision 207) adds its
own three tests to this module (PLAN-telemetry-grain-and-generations).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.contracts import load_contract
from src.telemetry.identity import decode_time_prefix, derive_entity_key

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACTS_DIR = _REPO_ROOT / "docs" / "contracts"


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


def test_parser_version_bump_policy_declared() -> None:
    envelope = load_contract(_CONTRACTS_DIR / "telemetry-event-envelope.yaml")
    parser_version = envelope.fields["parser_version"]
    producer = envelope.fields["producer"]

    pv_description = _norm(parser_version.description)
    pv_semantics = _norm(parser_version.semantics)
    assert "hand-maintained" in pv_description and "per-producer" in pv_description
    assert "increments iff" in pv_description
    assert "never decrements" in pv_description and "never reused" in pv_description
    assert "identity-spec change" in pv_description and "bumps every producer" in pv_description
    assert "from its own build/version identity" not in _norm(parser_version.populated_by)
    assert "replayable producer" in pv_semantics and "cursor" in pv_semantics

    for table_name in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
        doc = load_contract(_CONTRACTS_DIR / f"{table_name}.yaml")
        producer_field = doc.fields["producer"]
        assert producer_field.dq_intent_local is not None
        assert producer_field.dq_intent_local["not_null"]["enforced"] is True
        assert any(entry.semantic_break for entry in producer_field.amendment_log)

    assert "part of the telemetry grain key" in _norm(producer.description) or "grain key" in _norm(producer.description)


def test_model_call_tiebreak_prefers_final_usage() -> None:
    envelope = load_contract(_CONTRACTS_DIR / "telemetry-event-envelope.yaml")
    governance = _norm(envelope.governance_notes)

    assert "event_timestamp desc" in governance
    assert "final usage wins" in governance or "final usage numbers win" in governance
    assert "then created_timestamp asc" in governance or "created_timestamp asc" in governance
    assert "then producer asc" in governance
    assert "then event_id asc" in governance
    assert "model_call dedupe" not in governance

    from tests.fixtures.telemetry_dedupe_reference import compute_generations, resolve_table

    generations = compute_generations(
        [
            {
                "producer": "claude_code",
                "event_id": "sess-open",
                "parser_version": 1,
                "session_id": "s1",
                "event_kind": "open",
                "created_timestamp": "2026-09-25T10:00:00+00:00",
                "content": "v1",
            }
        ]
    )
    rows = [
        {
            "producer": "claude_code",
            "event_id": "mc-partial",
            "parser_version": 1,
            "session_id": "s1",
            "created_timestamp": "2026-09-25T10:01:00+00:00",
            "content": "partial",
            "observation_id": "obs-1",
            "event_timestamp": "2026-09-25T10:01:00+00:00",
        },
        {
            "producer": "claude_code",
            "event_id": "mc-final",
            "parser_version": 1,
            "session_id": "s1",
            "created_timestamp": "2026-09-25T10:02:00+00:00",
            "content": "final",
            "observation_id": "obs-1",
            "event_timestamp": "2026-09-25T10:02:00+00:00",
        },
    ]
    survivors, _ = resolve_table(rows, generations, is_model_call=True)
    assert [row["event_id"] for row in survivors] == ["mc-final"]


def test_grain_enforced_at_write_rule_declared() -> None:
    standard_path = _CONTRACTS_DIR / "data-modeling-standard.yaml"
    standard = yaml.safe_load(standard_path.read_text(encoding="utf-8"))
    rules = {rule["id"]: rule for rule in standard["rules"]}
    assert "grain-enforced-at-write" in rules
    rule_statement = rules["grain-enforced-at-write"]["statement"]

    match = re.search(r"Decision (\d+)", rule_statement)
    assert match, "grain-enforced-at-write rule must cite its Decision number"
    decision_number = match.group(1)

    walk = standard["design_time_walk"]
    assert "grain-enforced-at-write" in walk and f"Decision {decision_number}" in walk

    decisions_text = (_REPO_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    section_marker = f"## Decision {decision_number}:"
    assert section_marker in decisions_text, f"DECISIONS.md must carry a section for Decision {decision_number}"
    section_start = decisions_text.index(section_marker)
    next_section = decisions_text.find("\n## Decision ", section_start + 1)
    section = decisions_text[section_start : next_section if next_section != -1 else len(decisions_text)]
    section_norm = _norm(section)

    for owner in ("rec-4121", "rec-4063", "rec-4024", "rec-4025"):
        assert owner in section_norm, f"Decision {decision_number} must name coverage owner {owner}"
    assert "ops_smoke_events" in section_norm
    assert "scd2 history readers" in section_norm and "exempt" in section_norm

    for anchor in ("decision 81", "decision 84"):
        assert anchor in decisions_text.lower()
    assert decisions_text.count(f"Decision {decision_number}") >= 2  # the section itself plus the two dated annotations
