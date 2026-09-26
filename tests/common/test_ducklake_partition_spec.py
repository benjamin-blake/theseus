"""MIRROR for src/common/ducklake_partition_spec.py (rec-4068).

Covers the calendar-prefix predicate (validate_partition_spec), the partition_by parser
(parse_partition_by), the resolver (resolve_partition_block), the whole-projection sweep
(validate_projection_partitions), and the generator's contract-derived emission (rec-4068's
per-site rejection coverage lives here, not in scripts/schema_to_field_semantics.py's own
479-SLOC mirror test).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from src.common.ducklake_partition_spec import (
    PartitionSpecError,
    parse_partition_by,
    resolve_partition_block,
    validate_partition_spec,
    validate_projection_partitions,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_GEN_PATH = _ROOT / "scripts" / "schema_to_field_semantics.py"


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("schema_to_field_semantics_ptest", _GEN_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# validate_partition_spec -- green cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        "year(created_timestamp), month(created_timestamp), day(created_timestamp)",
        "year(created_timestamp)",
        "year(created_timestamp), month(created_timestamp)",
        "year(created_timestamp), month(created_timestamp), day(created_timestamp), hour(created_timestamp)",
        "bucket(8, id)",
        "counter_name",
        "year(created_timestamp), month(created_timestamp), day(created_timestamp), bucket(4, id)",
    ],
)
def test_validate_partition_spec_accepts(spec: str) -> None:
    validate_partition_spec(spec)  # must not raise


# ---------------------------------------------------------------------------
# validate_partition_spec -- red cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        "day(created_timestamp)",
        "month(created_timestamp)",
        "hour(created_timestamp)",
        "month(created_timestamp), day(created_timestamp)",
        "day(created_timestamp), month(created_timestamp)",
        "year(a), day(b)",
        "",
        "frobnicate(created_timestamp)",
    ],
)
def test_validate_partition_spec_rejects(spec: str) -> None:
    with pytest.raises(PartitionSpecError):
        validate_partition_spec(spec)


def test_validate_partition_spec_rejects_non_string() -> None:
    with pytest.raises(PartitionSpecError):
        validate_partition_spec(None)  # type: ignore[arg-type]


def test_validate_partition_spec_rejects_empty_entry_between_commas() -> None:
    with pytest.raises(PartitionSpecError, match="empty partition-spec entry"):
        validate_partition_spec("year(c),,day(c)")


# ---------------------------------------------------------------------------
# parse_partition_by
# ---------------------------------------------------------------------------


def test_parse_partition_by_splits_roles_on_semicolon() -> None:
    value = "history=year(c), month(c), day(c); current=bucket(8, id)"
    assert parse_partition_by(value) == {
        "history": "year(c), month(c), day(c)",
        "current": "bucket(8, id)",
    }


def test_parse_partition_by_single_role() -> None:
    assert parse_partition_by("history=year(c), month(c), day(c)") == {"history": "year(c), month(c), day(c)"}


def test_parse_partition_by_skips_empty_segment_from_trailing_semicolon() -> None:
    assert parse_partition_by("history=year(c);") == {"history": "year(c)"}


@pytest.mark.parametrize("value", ["", "history", "history=", "=bucket(8,id)"])
def test_parse_partition_by_rejects_malformed(value: str) -> None:
    with pytest.raises(PartitionSpecError):
        parse_partition_by(value)


# ---------------------------------------------------------------------------
# resolve_partition_block
# ---------------------------------------------------------------------------


def test_resolve_partition_block_scd2_requires_both() -> None:
    block = {"history": "year(c), month(c), day(c)", "current": "bucket(8, id)"}
    history, current = resolve_partition_block(block, "scd2")
    assert history == "year(c), month(c), day(c)"
    assert current == "bucket(8, id)"


def test_resolve_partition_block_scd2_missing_current_raises() -> None:
    with pytest.raises(PartitionSpecError):
        resolve_partition_block({"history": "year(c), month(c), day(c)"}, "scd2")


def test_resolve_partition_block_missing_history_raises() -> None:
    with pytest.raises(PartitionSpecError):
        resolve_partition_block({"current": "bucket(8, id)"}, "scd2")
    with pytest.raises(PartitionSpecError):
        resolve_partition_block({}, "append_only")


def test_resolve_partition_block_append_only_needs_no_current() -> None:
    history, current = resolve_partition_block({"history": "year(c), month(c), day(c)"}, "append_only")
    assert history == "year(c), month(c), day(c)"
    assert current is None


def test_resolve_partition_block_append_only_validates_current_when_present() -> None:
    block = {"history": "year(c), month(c), day(c)", "current": "bucket(8, id)"}
    history, current = resolve_partition_block(block, "append_only")
    assert current == "bucket(8, id)"
    with pytest.raises(PartitionSpecError):
        resolve_partition_block({"history": "year(c), month(c), day(c)", "current": "day(c)"}, "append_only")


# ---------------------------------------------------------------------------
# validate_projection_partitions
# ---------------------------------------------------------------------------


def test_validate_projection_partitions_skips_table_with_no_partition_key() -> None:
    doc: dict[str, Any] = {"partition_transforms": {}, "tables": {"no_partition": {}}, "ops_tables": {}}
    validate_projection_partitions(doc)  # must not raise


def test_validate_projection_partitions_accepts_calendar_projection() -> None:
    doc: dict[str, Any] = {
        "partition_transforms": {"history": "year(c), month(c), day(c)", "current": "bucket(8, id)"},
        "tables": {"history": {"partition": "year(c), month(c), day(c)"}},
        "ops_tables": {
            "ops_recommendations": {"partition": {"history": "year(c), month(c), day(c)", "current": "bucket(8, id)"}},
        },
    }
    validate_projection_partitions(doc)  # must not raise


@pytest.mark.parametrize(
    "site",
    ["partition_transforms", "tables", "ops_tables"],
)
def test_validate_projection_partitions_rejects_day_of_month_per_site(site: str) -> None:
    doc: dict[str, Any] = {
        "partition_transforms": {"history": "year(c), month(c), day(c)", "current": "bucket(8, id)"},
        "tables": {"history": {"partition": "year(c), month(c), day(c)"}},
        "ops_tables": {
            "ops_recommendations": {"partition": {"history": "year(c), month(c), day(c)", "current": "bucket(8, id)"}},
        },
    }
    if site == "partition_transforms":
        doc["partition_transforms"]["history"] = "day(c)"
    elif site == "tables":
        doc["tables"]["history"]["partition"] = "day(c)"
    else:
        doc["ops_tables"]["ops_recommendations"]["partition"]["history"] = "day(c)"
    with pytest.raises(PartitionSpecError):
        validate_projection_partitions(doc)


# ---------------------------------------------------------------------------
# Generator contract-derivation (R5): six-site rejection + contract-derived emission
# ---------------------------------------------------------------------------


def test_partition_derived_from_contract_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    """generate() derives the emitted partition from the contract's governance.partition_by."""
    mod = _load_generator_module()

    from scripts import contracts as contracts_mod

    real_load_contract = contracts_mod.load_contract

    def _patched_load_contract(path: Path):
        doc = real_load_contract(path)
        if path.stem == "ops_recommendations" and doc.governance is not None:
            doc.governance.partition_by = "history=year(created_timestamp); current=bucket(8, id)"
        return doc

    monkeypatch.setattr(mod, "generate", mod.generate)  # keep target module bound for patch below
    monkeypatch.setattr("scripts.contracts.load_contract", _patched_load_contract)

    doc = mod.generate()
    rec_partition = doc["ops_tables"]["ops_recommendations"]["partition"]
    assert rec_partition["history"] == "year(created_timestamp)"


_SIX_SITES = [
    "contract_partition_by",
    "smoke_tables_history",
    "smoke_partition_transforms_history",
    "dormant_ops_priority_queue",
    "dormant_ops_execution_plans",
    "smoke_ops_tables_ops_smoke_events",
]


@pytest.mark.parametrize("site", _SIX_SITES)
def test_generate_rejects_day_of_month_at_every_emission_site(site: str, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_generator_module()

    if site == "contract_partition_by":
        from scripts import contracts as contracts_mod

        real_load_contract = contracts_mod.load_contract

        def _patched_load_contract(path: Path):
            doc = real_load_contract(path)
            if path.stem == "ops_recommendations" and doc.governance is not None:
                doc.governance.partition_by = "history=day(created_timestamp); current=bucket(8, id)"
            return doc

        monkeypatch.setattr("scripts.contracts.load_contract", _patched_load_contract)
    else:
        import yaml as yaml_mod

        real_safe_load = yaml_mod.safe_load

        def _patched_safe_load(stream):
            doc = real_safe_load(stream)
            if not isinstance(doc, dict) or "tables" not in doc:
                return doc
            if site == "smoke_tables_history":
                doc["tables"]["history"]["partition"] = "day(created_timestamp)"
            elif site == "smoke_partition_transforms_history":
                doc["partition_transforms"]["history"] = "day(created_timestamp)"
            elif site == "dormant_ops_priority_queue":
                doc["dormant_ops_tables"]["ops_priority_queue"]["partition"]["history"] = "day(created_timestamp)"
            elif site == "dormant_ops_execution_plans":
                doc["dormant_ops_tables"]["ops_execution_plans"]["partition"]["history"] = "day(created_timestamp)"
            elif site == "smoke_ops_tables_ops_smoke_events":
                doc["smoke_ops_tables"]["ops_smoke_events"]["partition"]["history"] = "day(created_timestamp)"
            return doc

        monkeypatch.setattr(yaml_mod, "safe_load", _patched_safe_load)

    with pytest.raises(PartitionSpecError):
        mod.generate()
