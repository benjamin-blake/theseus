"""Tests for validate_log_storage_registry() -- PLAN-class-d-contract-enforcers.

Covers: green path against a fixture matching s3_log_store.py's FALLBACK constants, a drift red
path, an ABSENT/EMPTY-target red path, a missing-file red path, and a malformed-YAML red path.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts import s3_log_store
from scripts.checks import registry
from scripts.checks.contracts.validate_log_storage_registry import validate_log_storage_registry

_CONTRACT_NAME = "log-storage.yaml"


def _write_contract(contracts_dir: Path, queue_key: str) -> None:
    doc = {"routing": {"priority_queue_key": queue_key}}
    (contracts_dir / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")


class TestGreenPath:
    def test_matching_routing_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, s3_log_store.FALLBACK_PRIORITY_QUEUE_KEY)

        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert failed == []


class TestDriftRedPath:
    def test_divergent_queue_key_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "wrong/key.jsonl")

        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert any("declares priority_queue_key=" in f for f in failed)


class TestAbsentEmptyTarget:
    def test_missing_routing_block_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text(yaml.dump({"version": 1}), encoding="utf-8")

        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert any("missing or empty" in f for f in failed)

    def test_empty_routing_block_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text(yaml.dump({"routing": {}}), encoding="utf-8")

        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert any("missing or empty" in f for f in failed)

    def test_missing_queue_key_fails(self, tmp_path: Path) -> None:
        doc = {"routing": {"note": "no priority_queue_key here"}}
        (tmp_path / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")

        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert any("missing a non-empty priority_queue_key" in f for f in failed)


class TestMissingFile:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert any("not found" in f for f in failed)


class TestMalformedYaml:
    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("routing: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_log_storage_registry(failed, contracts_dir=tmp_path)

        assert any("could not read/parse" in f for f in failed)


class TestWiring:
    def test_wiring_registered_in_pre_and_full(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}

        assert "validate_log_storage_registry" in pre_names
        assert "validate_log_storage_registry" in full_names

    def test_wiring_resolves_via_registry(self) -> None:
        resolved = registry.resolve("validate_log_storage_registry")

        assert callable(resolved)
        assert resolved is validate_log_storage_registry
