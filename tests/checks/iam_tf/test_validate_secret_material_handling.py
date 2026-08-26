"""Tests for the secret-material-handling gate (Decision 175 / T2.56 migration step 7)."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks.iam_tf.validate_secret_material_handling import validate_secret_material_handling

_CONTRACT_REL = "docs/contracts/secret-material-handling.yaml"


def _write_contract(root: Path, value_exceptions: list[dict[str, str]]) -> None:
    contract_path = root / _CONTRACT_REL
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        yaml.safe_dump({"contract": {"id": "secret-material-handling"}, "value_exceptions": value_exceptions}),
        encoding="utf-8",
    )


def _write_terraform(root: Path, tf_by_relpath: dict[str, str]) -> None:
    for relpath, text in tf_by_relpath.items():
        p = root / "terraform" / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_real_tree_passes() -> None:
    """The real repository's two live exceptions are both declared -- no undeclared _version resource."""
    failed: list[str] = []
    validate_secret_material_handling(failed)
    assert failed == [], failed


def test_undeclared_version_resource_fails(tmp_path: Path) -> None:
    _write_contract(tmp_path, value_exceptions=[])
    _write_terraform(
        tmp_path,
        {
            "personal/rogue.tf": (
                'resource "aws_secretsmanager_secret_version" "rogue_value" {\n'
                '  secret_id     = "rogue"\n'
                '  secret_string = "in-state-material"\n'  # pragma: allowlist secret
                "}\n"
            )
        },
    )
    failed: list[str] = []
    validate_secret_material_handling(failed, root=tmp_path)
    assert len(failed) == 1
    assert "aws_secretsmanager_secret_version.rogue_value" in failed[0]


def test_declared_exception_passes(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        value_exceptions=[{"resource": "aws_secretsmanager_secret_version.rogue_value", "file": "x", "reason": "y"}],
    )
    _write_terraform(
        tmp_path,
        {
            "personal/rogue.tf": (
                'resource "aws_secretsmanager_secret_version" "rogue_value" {\n'
                '  secret_id     = "rogue"\n'
                '  secret_string = "in-state-material"\n'  # pragma: allowlist secret
                "}\n"
            )
        },
    )
    failed: list[str] = []
    validate_secret_material_handling(failed, root=tmp_path)
    assert failed == [], failed


def test_data_source_version_never_flagged(tmp_path: Path) -> None:
    """A `data` secret-version source only READS a value -- it never writes one into state."""
    _write_contract(tmp_path, value_exceptions=[])
    _write_terraform(
        tmp_path,
        {"personal/read_only.tf": ('data "aws_secretsmanager_secret_version" "some_api_key" {\n  secret_id = "x"\n}\n')},
    )
    failed: list[str] = []
    validate_secret_material_handling(failed, root=tmp_path)
    assert failed == [], failed


def test_missing_contract_skips(tmp_path: Path) -> None:
    (tmp_path / "terraform").mkdir()
    failed: list[str] = []
    validate_secret_material_handling(failed, root=tmp_path)
    assert failed == []


def test_contract_mutation_flips_verdict(tmp_path: Path) -> None:
    """Load-bearing case (Decision 168 clause 2): the verdict follows the CONTRACT, not hardcoded
    names. Mirrors the real tree's two live exceptions; dropping one from the fixture contract
    must make the check flag exactly that resource, proving it reads value_exceptions at runtime."""
    tf_by_relpath = {
        "personal/neon_ducklake_catalog.tf": (
            'resource "aws_secretsmanager_secret_version" "ducklake_neon_catalog_dsn" {\n'
            '  secret_id     = "ducklake-neon-catalog-dsn"\n'
            '  secret_string = "generated-by-neon-provider"\n'  # pragma: allowlist secret
            "}\n"
        ),
        "scheduled_agents.tf": (
            'resource "aws_secretsmanager_secret_version" "github_pat_placeholder" {\n'
            '  secret_id     = "agent-platform-github-pat"\n'
            '  secret_string = "PLACEHOLDER_SET_MANUALLY"\n'  # pragma: allowlist secret
            "}\n"
        ),
    }
    _write_terraform(tmp_path, tf_by_relpath)
    both_exceptions = [
        {"resource": "aws_secretsmanager_secret_version.ducklake_neon_catalog_dsn", "file": "x", "reason": "y"},
        {"resource": "aws_secretsmanager_secret_version.github_pat_placeholder", "file": "x", "reason": "y"},
    ]

    _write_contract(tmp_path, value_exceptions=both_exceptions)
    failed_before: list[str] = []
    validate_secret_material_handling(failed_before, root=tmp_path)
    assert failed_before == [], failed_before

    # Drop ducklake_neon_catalog_dsn from the fixture contract -- the verdict must flip.
    narrowed = [e for e in both_exceptions if "ducklake_neon_catalog_dsn" not in e["resource"]]
    _write_contract(tmp_path, value_exceptions=narrowed)
    failed_after: list[str] = []
    validate_secret_material_handling(failed_after, root=tmp_path)
    assert len(failed_after) == 1
    assert "ducklake_neon_catalog_dsn" in failed_after[0]
    assert "github_pat_placeholder" not in failed_after[0]
