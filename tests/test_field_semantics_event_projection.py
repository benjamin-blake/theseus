"""Mapped test for scripts/field_semantics_event_projection.py: fixture-contract projection
shape, fail-closed cases, generate() accepting an event contract without merge_key, and all four
real telemetry contracts projecting (unregistered).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.field_semantics_event_projection as proj_mod
from scripts.contracts import load_contract, resolve_refs
from scripts.schema_to_field_semantics import _map_iceberg_type
from src.telemetry.identity import KeyPlan

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "event_contracts"
_CONTRACTS_DIR = Path(__file__).parent.parent / "docs" / "contracts"

_FIXTURE_KEY_PLAN = {"fixture_events": {"entity_id": KeyPlan("fixture_events:entity_id", "entity_ref", True)}}


@pytest.fixture
def fixture_resolved():
    doc = load_contract(_FIXTURES_DIR / "fixture_events.yaml")
    return doc, resolve_refs(doc, _FIXTURES_DIR)


@pytest.fixture(autouse=True)
def _patch_key_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.telemetry.identity import KEY_PLANS as REAL_KEY_PLANS

    monkeypatch.setattr(proj_mod, "KEY_PLANS", {**REAL_KEY_PLANS, **_FIXTURE_KEY_PLAN})


def _project(table_id, resolved, ops_config=None, partition_by=None, **kwargs):
    return proj_mod.project_event_table(
        table_id, resolved, ops_config or {}, partition_by, map_iceberg_type=_map_iceberg_type, **kwargs
    )


class TestFixtureContractProjectionShape:
    def test_shape(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by, include_prose=True)

        assert entry["write_mode"] == "append_only"
        assert entry["history_table"] == "fixture_events"
        assert "merge_key" not in entry
        assert "current_table" not in entry
        assert "entity_id_prefix" not in entry
        assert "id_keyspace" not in entry
        assert entry["dedupe_key"] == ["event_id", "parser_version"]
        assert entry["entity_key"] == "entity_id"
        assert entry["partition"]["history"] == doc.governance.partition_by
        assert entry["partition_column"] == "session_started_at"

    def test_read_derived_field_has_no_column(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by)
        assert "duration_seconds" not in entry["columns"]

    def test_derived_role_set(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by)
        derived = {name for name, spec in entry["columns"].items() if spec["role"] == "derived"}
        assert derived == {"event_id", "created_timestamp", "tenant_id", "project_id", "entity_id"}

    def test_bigint_double_list_types(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by)
        assert entry["columns"]["retry_count"]["sql_type"] == "BIGINT"
        assert entry["columns"]["cost_estimate"]["sql_type"] == "DOUBLE"
        assert entry["columns"]["labels"]["sql_type"] == "VARCHAR[]"

    def test_required_when_takes_precedence_over_nullable_false(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by)
        outcome = entry["columns"]["outcome"]
        assert outcome["nullable"] is True
        assert outcome["required_when"] == {"event_kind": ["close"]}

    def test_plain_not_null_field_stays_not_null(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by)
        assert entry["columns"]["workflow"]["nullable"] is False
        assert "required_when" not in entry["columns"]["workflow"]

    def test_include_prose_false_omits_description_and_semantics(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        entry = _project("fixture_events", resolved, partition_by=doc.governance.partition_by, include_prose=False)
        assert "description" not in entry["columns"]["workflow"]
        assert "semantics" not in entry["columns"]["workflow"]


class TestFailClosedCases:
    def test_missing_envelope_column_raises(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        truncated = dict(resolved)
        del truncated["event_id"]
        with pytest.raises(ValueError, match="missing required envelope column"):
            _project("fixture_events", truncated, partition_by=doc.governance.partition_by)

    def test_bare_day_partition_by_rejected(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="calendar-day triple"):
            _project("fixture_events", resolved, partition_by="day(session_started_at)")

    def test_missing_partition_by_rejected(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError):
            _project("fixture_events", resolved, partition_by=None)

    def test_partition_column_not_projected_as_timestamptz_rejected(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError):
            _project(
                "fixture_events",
                resolved,
                partition_by="year(event_id), month(event_id), day(event_id)",
            )

    def test_migration_columns_in_ops_config_rejected(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="migration_columns"):
            _project(
                "fixture_events",
                resolved,
                ops_config={"migration_columns": {"history": {}}},
                partition_by=doc.governance.partition_by,
            )

    def test_derivation_read_with_realized_true_raises(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        mutated = dict(resolved)
        bad_field = mutated["session_started_at"].model_copy(update={"derivation": {"timing": "read", "realized": True}})
        mutated["session_started_at"] = bad_field
        with pytest.raises(ValueError, match="realized=true"):
            _project("fixture_events", mutated, partition_by=doc.governance.partition_by)

    def test_unregistered_table_raises(self, fixture_resolved) -> None:
        doc, resolved = fixture_resolved
        with pytest.raises(KeyError):
            _project("not_a_registered_table", resolved, partition_by=doc.governance.partition_by)

    def test_table_with_no_entity_ref_key_plan_raises(self, fixture_resolved, monkeypatch: pytest.MonkeyPatch) -> None:
        doc, resolved = fixture_resolved
        # A table registered in KEY_PLANS but with no plan whose ref_field == "entity_ref" (every
        # plan is an FK-only reference) -- _entity_key_column's own defensive fail-closed branch.
        monkeypatch.setattr(
            proj_mod,
            "KEY_PLANS",
            {"fixture_events": {"parent_id": KeyPlan("fixture_events:parent_id", "parent_ref", False)}},
        )
        with pytest.raises(ValueError, match="no entity-key column"):
            _project("fixture_events", resolved, partition_by=doc.governance.partition_by)


class TestGenerateAcceptsEventContractWithoutMergeKey:
    def test_dispatch_via_project_contract_table_needs_no_merge_key(self, fixture_resolved) -> None:
        # scripts.schema_to_field_semantics._project_contract_table is the single dispatch point
        # generate() calls per table; exercising it directly (table_class="event", merge_key=None)
        # is what "generate() accepts an event contract with no merge_key" means in practice, since
        # _CONTRACT_TABLE_IDS never names an event table (Nothing ships this slice).
        from scripts.schema_to_field_semantics import _project_contract_table

        doc, resolved = fixture_resolved
        assert doc.governance.merge_key is None
        entry = _project_contract_table(
            "fixture_events",
            resolved,
            None,
            {},
            table_class="event",
            partition_by=doc.governance.partition_by,
        )
        assert entry["write_mode"] == "append_only"
        assert "merge_key" not in entry


class TestRealTelemetryContractsProject:
    @pytest.mark.parametrize(
        "table_id",
        ["telemetry_sessions", "telemetry_observations", "telemetry_transcripts", "telemetry_agents"],
    )
    def test_real_contract_projects_without_error(self, table_id: str) -> None:
        doc = load_contract(_CONTRACTS_DIR / f"{table_id}.yaml")
        resolved = resolve_refs(doc, _CONTRACTS_DIR)
        entry = _project(table_id, resolved, partition_by=doc.governance.partition_by)
        assert entry["write_mode"] == "append_only"
        assert "merge_key" not in entry

    def test_telemetry_sessions_has_no_duration_seconds_column(self) -> None:
        doc = load_contract(_CONTRACTS_DIR / "telemetry_sessions.yaml")
        resolved = resolve_refs(doc, _CONTRACTS_DIR)
        entry = _project("telemetry_sessions", resolved, partition_by=doc.governance.partition_by)
        assert "duration_seconds" not in entry["columns"]

    def test_telemetry_sessions_workflow_projects_nullable(self) -> None:
        doc = load_contract(_CONTRACTS_DIR / "telemetry_sessions.yaml")
        resolved = resolve_refs(doc, _CONTRACTS_DIR)
        entry = _project("telemetry_sessions", resolved, partition_by=doc.governance.partition_by)
        # workflow is nullable:false but carries required_when (open only) -> projects nullable.
        assert entry["columns"]["workflow"]["nullable"] is True
        assert entry["columns"]["workflow"]["required_when"] == {"event_kind": ["open"]}
