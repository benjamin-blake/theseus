"""Packaging scope for the telemetry writer: its own artifact, never bundled into data-pipeline."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.lambda_manifest import compute_affected_artifacts

_ROOT = Path(__file__).resolve().parents[3]
_HANDLER = "src/lambdas/ducklake_telemetry_writer/handler.py"


def test_handler_edit_affects_only_the_telemetry_writer_artifact() -> None:
    assert sorted(compute_affected_artifacts([_HANDLER])) == ["ducklake_telemetry_writer"]


def test_data_pipeline_manifest_excludes_the_directory() -> None:
    manifest = yaml.safe_load((_ROOT / "src" / "lambdas" / "data-pipeline" / "manifest.yaml").read_text(encoding="utf-8"))
    assert "src/lambdas/ducklake_telemetry_writer" in manifest["excludes"]


def test_telemetry_manifest_bundles_no_telemetry_kernel_or_maintenance_modules() -> None:
    manifest = yaml.safe_load(
        (_ROOT / "src" / "lambdas" / "ducklake_telemetry_writer" / "manifest.yaml").read_text(encoding="utf-8")
    )
    includes = manifest["includes"]
    assert not any(i.startswith("src/telemetry") for i in includes)
    assert "src/common/ducklake_maintenance.py" not in includes
    assert manifest["functions"] == ["agent-platform-ducklake-telemetry-writer"]
