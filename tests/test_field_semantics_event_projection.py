"""Mapped test for scripts/field_semantics_event_projection.py: fixture-contract projection
shape, fail-closed cases, generate() accepting an event contract without merge_key, and all four
real telemetry contracts projecting (unregistered).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import scripts.field_semantics_event_projection as proj_mod
import scripts.schema_to_field_semantics as schema_mod
from scripts.contracts import load_contract, resolve_refs
from scripts.schema_to_field_semantics import _map_iceberg_type, generate
from src.telemetry.identity import KeyPlan

_ROOT = Path(__file__).parent.parent

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
        # The stored partition is the RESOLVED history spec, role-prefix stripped -- the raw
        # contract field carries "history=..." (parse_partition_by's role grammar).
        assert doc.governance.partition_by == f"history={entry['partition']['history']}"
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

    def test_missing_role_prefix_partition_by_rejected(self, fixture_resolved) -> None:
        # No 'history=' role label -- rejected by the shared parse_partition_by grammar itself,
        # before this module's own day-grain check ever runs.
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="malformed"):
            _project("fixture_events", resolved, partition_by="day(session_started_at)")

    def test_current_role_partition_by_rejected(self, fixture_resolved) -> None:
        # An append_only event table declares only the history role -- a current= role (valid SCD2
        # grammar) is fail-closed here, not silently ignored.
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="current="):
            _project(
                "fixture_events",
                resolved,
                partition_by=(
                    "history=year(session_started_at), month(session_started_at), day(session_started_at); "
                    "current=bucket(8, entity_id)"
                ),
            )

    def test_missing_history_role_partition_by_rejected(self, fixture_resolved) -> None:
        # A parseable role-prefixed spec that declares neither 'history=' nor 'current=' -- distinct
        # from the malformed-grammar and the current-role-present cases above; the "must declare a
        # 'history=' role" branch is its own guard, reached only once the current= check clears.
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="must declare a 'history=' role"):
            _project(
                "fixture_events",
                resolved,
                partition_by="bogus=year(session_started_at), month(session_started_at), day(session_started_at)",
            )

    def test_partition_check_delegates_to_validate_partition_spec(self, fixture_resolved) -> None:
        """rec-4073 acceptance node: a spec the SHARED validate_partition_spec predicate accepts
        (year-only is a valid calendar prefix on its own) but that this module's own stricter
        day-grain-triple check must still reject -- proves the shared validator actually runs
        (a locally-reimplemented regex would never see this spec as anything but 'not a triple'
        for a different reason), and that this module still tightens beyond it for event tables.
        """
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="calendar-day triple"):
            _project("fixture_events", resolved, partition_by="history=year(session_started_at)")

    def test_shared_validator_rejection_surfaces(self, fixture_resolved) -> None:
        # A spec the shared validate_partition_spec predicate itself rejects (day() without its
        # coarser year()/month() prefix) -- surfaces as this module's own ValueError, not a raw
        # PartitionSpecError leaking past the projection boundary.
        doc, resolved = fixture_resolved
        with pytest.raises(ValueError, match="history spec is invalid"):
            _project("fixture_events", resolved, partition_by="history=day(session_started_at)")

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
                partition_by="history=year(event_id), month(event_id), day(event_id)",
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


class TestGenerateMissingMergeKey:
    """Moved from tests/test_schema_to_field_semantics.py (Decision 128 decompose-by-default: that
    file was over its 500-SLOC budget). Not event-specific -- covers generate()'s existing
    non-event merge_key-required error path -- but carries no VP-step node_id reference, unlike
    that file's test_event_class_dispatches_to_event_projection, so it was the one free to move.
    """

    def test_missing_merge_key_raises(self) -> None:
        mock_doc = MagicMock()
        mock_doc.governance = MagicMock()
        mock_doc.governance.merge_key = None

        with patch("scripts.contracts.load_contract", return_value=mock_doc):
            with pytest.raises(ValueError, match="governance.merge_key is missing"):
                generate()


def test_maintenance_policy_absent_from_sidecar_raises(tmp_path: Path) -> None:
    """Moved from tests/test_schema_to_field_semantics.py (Decision 128 decompose-by-default, same
    reason as TestGenerateMissingMergeKey above). REQUIRED, not conditional: a sidecar missing
    maintenance_policy must raise (KeyError), never silently emit a projection without it."""
    sidecar_path = _ROOT / "config" / "lambda" / "ducklake" / "field_semantics.static.yaml"
    sidecar = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
    del sidecar["maintenance_policy"]
    tmp_sidecar = tmp_path / "field_semantics.static.yaml"
    tmp_sidecar.write_text(yaml.dump(sidecar), encoding="utf-8")

    with patch.object(schema_mod, "_SIDECAR_PATH", tmp_sidecar):
        with pytest.raises(KeyError, match="maintenance_policy"):
            generate()


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
