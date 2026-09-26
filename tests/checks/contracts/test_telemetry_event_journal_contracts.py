"""Red-before/green-after invariants for the telemetry event-journal contract re-model
(Decision 199/200, PLAN-telemetry-event-journal-contracts).

Loads every scope contract through scripts.contracts load_contract + resolve_refs and asserts
the event-journal, identity, content, dimension, lexicon and substrate invariants named in the
plan's acceptance criteria. Phrase assertions are case-insensitive over whitespace-normalised
text. This module does not exist on the pre-change tree (red before); every test below fails
importing scripts.contracts symbols that pre-date this plan only insofar as the CONTRACT bodies
themselves lacked the shapes asserted here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.contracts import load_contract, load_contract_meta, resolve_refs

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts"


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _load(name: str):
    return load_contract(_CONTRACTS_DIR / f"{name}.yaml")


def _resolved(name: str) -> dict:
    doc = _load(name)
    return resolve_refs(doc, _CONTRACTS_DIR)


class TestSessionsEventJournalShape:
    def test_sessions_event_journal_shape(self) -> None:
        doc = _load("telemetry_sessions")
        resolved = _resolved("telemetry_sessions")

        assert doc.contract.contract_version == 2
        assert doc.governance.partition_by == (
            "history=year(session_started_at), month(session_started_at), day(session_started_at)"
        )

        event_kind = resolved["event_kind"]
        assert set(event_kind.dq_intent["accepted_values"]["values"]) == {
            "open",
            "resume",
            "compact",
            "close",
            "annotate",
        }

        # Shared envelope fields present and tightened NOT NULL.
        for field in ("event_id", "event_timestamp", "session_started_at", "tenant_id", "session_id"):
            assert resolved[field].dq_intent["not_null"]["enforced"] is True, field

        # ingested_at retired in favour of the envelope's created_timestamp.
        assert "ingested_at" not in doc.fields
        assert resolved["created_timestamp"].dq_intent["not_null"]["enforced"] is True

        # outcome is stored once (per-event-kind requirement), never table-wide not-null,
        # and "running" is no longer an accepted stored value.
        outcome = doc.fields["outcome"]
        assert outcome.dq_intent["not_null"]["enforced"] is False
        assert outcome.dq_intent["required_when"] == {"event_kind": ["close"]}
        assert "running" not in outcome.dq_intent["accepted_values"]["values"]

        # start/end/duration and the roll-ups are DERIVED (timing: read), no physical column.
        derived_fields = (
            "duration_seconds",
            "process_event_total",
            "rework_total",
            "exception_total",
            "steps_completed_total",
        )
        for derived_field in derived_fields:
            derivation = doc.fields[derived_field].derivation
            assert derivation is not None, derived_field
            assert derivation["timing"] == "read", derived_field

        # steps_total is STORED (known at open), not a *_total derived roll-up.
        assert doc.fields["steps_total"].derivation is None

        # Post-close facts are owned by the annotate event_kind.
        for annotate_field in ("pr_url", "ci_outcome", "coverage_after"):
            assert doc.fields[annotate_field].dq_intent["required_when"] == {"event_kind": ["annotate"]}, annotate_field


class TestObservationsEventJournalShape:
    def test_observations_event_journal_shape(self) -> None:
        doc = _load("telemetry_observations")
        resolved = _resolved("telemetry_observations")

        assert doc.contract.contract_version == 2

        observation_type = doc.fields["observation_type"]
        values = set(observation_type.dq_intent["accepted_values"]["values"])
        assert {"turn", "tool_call"} <= values
        assert values == {"phase", "step", "turn", "tool_call", "process_event", "model_call"}

        event_kind = resolved["event_kind"]
        assert set(event_kind.dq_intent["accepted_values"]["values"]) == {"open", "close", "point"}

        # model_call grain: four token classes stored once per point row.
        for token_field in ("tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation"):
            required_when = doc.fields[token_field].dq_intent["required_when"]
            assert required_when == {"event_kind": ["point"], "observation_type": ["model_call"]}, token_field
        assert "cost_usd_reported" in doc.fields
        cost_usd = doc.fields["cost_usd"]
        assert cost_usd.derivation is not None
        assert cost_usd.derivation["timing"] == "read"
        assert "cost_usd_reported" in cost_usd.derivation["formula"]

        # outcome vocabulary and its close/tool_call scoping.
        outcome = doc.fields["outcome"]
        assert set(outcome.dq_intent["accepted_values"]["values"]) == {"success", "error", "blocked", "interrupted"}
        assert outcome.dq_intent["required_when"] == {"event_kind": ["close"], "observation_type": ["tool_call"]}

        # process_event name grammar declared.
        assert "<source>:<signature>" in doc.fields["name"].semantics

        # Retired stored friction columns absent; NO stored friction_class/classifier_version/tier.
        for retired in ("tier", "friction_class", "classifier_version", "ingested_at"):
            assert retired not in doc.fields, retired

        # session_ref NOT NULL, parent_observation_ref nullable.
        assert resolved["session_id"].dq_intent["not_null"]["enforced"] is True
        parent_obs = resolved["parent_observation_id"]
        assert parent_obs.dq_intent.get("not_null", {}).get("enforced") is not True


class TestTranscriptsContentModel:
    def test_transcripts_content_model(self) -> None:
        doc = _load("telemetry_transcripts")
        resolved = _resolved("telemetry_transcripts")

        assert doc.contract.contract_version == 2

        event_kind = resolved["event_kind"]
        assert set(event_kind.dq_intent["accepted_values"]["values"]) == {"point"}

        content = doc.fields["content"]
        content_uri = doc.fields["content_uri"]
        assert content.nullable is True
        assert content_uri.nullable is True
        assert content.dq_intent["content_inline_threshold_bytes"] == 65536

        for required_field in ("content_sha256", "content_bytes", "content_truncated"):
            assert doc.fields[required_field].nullable is False
            assert doc.fields[required_field].dq_intent["not_null"]["enforced"] is True

        purpose_values = set(doc.fields["purpose"].dq_intent["accepted_values"]["values"])
        assert purpose_values == {"prompt", "response", "thinking", "tool_input", "tool_result", "system"}
        assert "transcript" not in purpose_values

        origin_values = set(doc.fields["origin"].dq_intent["accepted_values"]["values"])
        assert origin_values == {"human", "harness", "agent", "tool"}

        assert resolved["session_id"].dq_intent["not_null"]["enforced"] is True
        assert resolved["observation_id"].dq_intent["not_null"]["enforced"] is True

        for retired in ("local_path", "s3_key", "size_bytes", "created_at", "ingested_at"):
            assert retired not in doc.fields, retired


class TestAgentsEventJournalShape:
    def test_agents_event_journal_shape(self) -> None:
        doc = _load("telemetry_agents")
        resolved = _resolved("telemetry_agents")

        assert doc.contract.contract_version == 2

        agent_run_id = doc.fields["agent_run_id"]
        assert "telemetry_agents:agent_run_id" in agent_run_id.semantics
        assert agent_run_id.nullable is False

        entity_ref_note = doc.fields["session_id"]  # sanity: session_id present
        assert entity_ref_note is not None

        assert resolved["session_id"].dq_intent["not_null"]["enforced"] is True
        observation = resolved["observation_id"]
        assert observation.dq_intent.get("not_null", {}).get("enforced") is not True

        for total_field in ("tokens_input_total", "tokens_output_total"):
            derivation = doc.fields[total_field].derivation
            assert derivation is not None, total_field
            assert derivation["timing"] == "read"
            assert "model_call" in derivation["formula"]

        assert doc.fields["duration_seconds"].derivation is not None

        assert "ingested_at" not in doc.fields


class TestEventEnvelopeSharedFields:
    def test_event_envelope_shared_fields(self) -> None:
        envelope = _load("telemetry-event-envelope")
        expected_fields = {
            "event_id",
            "event_kind",
            "event_timestamp",
            "session_started_at",
            "source_ordinal",
            "external_ref",
            "entity_ref",
            "producer",
            "producer_version",
            "parser_version",
            "created_timestamp",
        }
        assert expected_fields <= set(envelope.fields)
        for name, spec in envelope.fields.items():
            if name in expected_fields:
                assert spec.description, name
                assert spec.semantics, name
                assert spec.dq_intent is not None, name

        for table in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
            table_doc = _load(table)
            for field_name in expected_fields:
                spec = table_doc.fields.get(field_name)
                assert spec is not None, f"{table}.{field_name} missing"
                assert spec.ref == f"telemetry-event-envelope.yaml#/contract/fields/{field_name}", f"{table}.{field_name}"


class TestTenantAndProjectIdentity:
    def test_tenant_and_project_identity(self) -> None:
        tenant = _load("tenant-id")
        assert tenant.contract.status.value == "ratified"
        tenant_field = tenant.fields["tenant_id"]
        combined = f"{tenant_field.description or ''} {tenant_field.semantics or ''}".lower()
        assert "opaque" in combined
        assert "immutable" in combined
        assert "write boundary" in combined

        project = _load("project-id")
        assert project.contract.contract_version == 2
        # Live-text surfaces only (description/semantics/governance_notes) -- amendment_log and
        # previous_versions may legitimately name the retired default to explain what changed.
        live_parts = [project.contract.description or "", project.governance_notes or ""]
        for spec in project.fields.values():
            live_parts.extend([spec.description or "", spec.semantics or "", spec.governance_notes or ""])
        project_live_text = _norm(" ".join(live_parts))
        assert "theseus" not in project_live_text
        assert "git-remote" not in project_live_text and "git remote" not in project_live_text

        for table in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
            table_doc = _load(table)
            for key in ("tenant_id", "project_id"):
                spec = table_doc.fields[key]
                assert spec.dq_intent_local["not_null"]["enforced"] is True, f"{table}.{key}"


class TestEntityKeyIdentityRule:
    def test_entity_key_identity_rule(self) -> None:
        for name in ("observation-id", "parent-observation-id", "session-id"):
            doc = _load(name)
            assert doc.contract.contract_version == 2, name
            assert doc.previous_versions, name

        envelope_text = _norm(open(_CONTRACTS_DIR / "telemetry-event-envelope.yaml", encoding="utf-8").read())
        assert "sha256" in envelope_text
        assert "domain tag" in envelope_text

        # No live description/semantics field still claims mint-once-and-propagate.
        stale_pattern = re.compile(r"minted (?:exactly )?once|never re-mints", re.IGNORECASE)
        for name in ("observation-id", "parent-observation-id", "session-id"):
            doc = _load(name)
            for field_name, spec in doc.fields.items():
                for attr in ("description", "semantics", "governance_notes"):
                    text = getattr(spec, attr, None) or ""
                    assert not stale_pattern.search(text), f"{name}.{field_name}.{attr}"
            assert not stale_pattern.search(doc.governance_notes or ""), name


class TestLexiconTemporalAndIdentity:
    def test_lexicon_temporal_and_identity(self) -> None:
        lexicon = yaml.safe_load(open(_CONTRACTS_DIR / "telemetry-lexicon.yaml", encoding="utf-8"))
        temporal = lexicon["lexicon"]["temporal"]
        assert temporal["event_time_column"] == "event_timestamp"
        for table in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
            assert temporal["partition"][table] == (
                "history=year(session_started_at), month(session_started_at), day(session_started_at)"
            )

        identity = lexicon["lexicon"]["identity"]
        assert identity["normative_spec"] == "docs/contracts/telemetry-event-envelope.yaml"
        assert "hash" in identity["scheme"].lower()

        # Class D envelope still resolves (validate_telemetry_lexicon_tables reads it).
        meta = load_contract_meta(_CONTRACTS_DIR / "telemetry-lexicon.yaml")
        assert meta.evaluator.check == "validate_telemetry_lexicon_tables"


class TestStorageSubstrateDisposition:
    def test_storage_substrate_disposition(self) -> None:
        substrate = yaml.safe_load(open(_CONTRACTS_DIR / "storage-substrate.yaml", encoding="utf-8"))
        telemetry_tables = substrate["tables"]["telemetry_tables"]
        text = _norm(yaml.safe_dump(telemetry_tables))
        assert "year(session_started_at), month(session_started_at), day(session_started_at)" in text
        assert any(ref.endswith("telemetry-event-envelope.yaml") for ref in telemetry_tables["contract_ref"])
        assert "blob port" in text or "blob-port" in text


class TestDataModelingStandardNotes:
    def test_data_modeling_standard_notes(self) -> None:
        standard = yaml.safe_load(open(_CONTRACTS_DIR / "data-modeling-standard.yaml", encoding="utf-8"))
        rules_by_id = {r["id"]: r for r in standard["rules"]}

        identity_rule = rules_by_id["identity-ulid-at-boundary"]
        assert "Decision 199" in identity_rule["statement"]
        assert "telemetry" in identity_rule["statement"].lower()

        assert "identity-ulid-at-boundary's event-table carve-out, Decision 199" in standard["design_time_walk"]

        derived_rule = rules_by_id["derived-state"]
        assert "derivation.timing: read" in derived_rule["statement"]
        assert "T2.52" in derived_rule["statement"]


_CALENDAR_DAY_TRIPLE = "history=year(session_started_at), month(session_started_at), day(session_started_at)"
_BARE_DAY_RE = re.compile(r"(?<!month\(session_started_at\), )day\(session_started_at\)")
_SKIP_KEYS = ("amendment_log", "previous_versions")


def _collect_live_strings(node: object) -> list[str]:
    """Recursively collect every string leaf, skipping amendment_log/previous_versions at any depth."""
    if isinstance(node, dict):
        strings: list[str] = []
        for key, value in node.items():
            if key in _SKIP_KEYS:
                continue
            strings.extend(_collect_live_strings(value))
        return strings
    if isinstance(node, list):
        return [s for item in node for s in _collect_live_strings(item)]
    if isinstance(node, str):
        return [node]
    return []


def test_partition_by_is_calendar_day_triple() -> None:
    """rec-4065 acceptance node (module-level per the Decision 201 trailer census)."""
    for table in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
        doc = _load(table)
        assert doc.governance.partition_by == _CALENDAR_DAY_TRIPLE, table

    lexicon = yaml.safe_load(open(_CONTRACTS_DIR / "telemetry-lexicon.yaml", encoding="utf-8"))
    temporal = lexicon["lexicon"]["temporal"]
    for table in ("telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"):
        assert temporal["partition"][table] == _CALENDAR_DAY_TRIPLE, table

    for path in sorted(_CONTRACTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for raw in _collect_live_strings(data):
            text = _norm(raw)
            assert not _BARE_DAY_RE.search(text), f"{path.name}: bare day(session_started_at) in {raw!r}"
            assert "day() partition" not in text, f"{path.name}: 'day() partition' in {raw!r}"
            assert "day()-partition" not in text, f"{path.name}: 'day()-partition' in {raw!r}"
