"""Tests for validate_terraform_cc_web_operations() -- PLAN-ambient-prose-contract-relocation.

Mirrors test_validate_git_ops_contract.py's coverage against the terraform-side pair: green
path (terraform/CLAUDE.md points at the contract, every referenced_repo_paths entry exists),
the pointer-removed red path, and the dangling-path red path -- the two failure modes
test_obligations names for this check -- plus missing-contract, missing-terraform/CLAUDE.md,
malformed-YAML, and missing/empty referenced_repo_paths edge cases.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks.contracts.validate_terraform_cc_web_operations import validate_terraform_cc_web_operations

_CONTRACT_REL_PATH = "docs/contracts/terraform-cc-web-operations.yaml"
_TERRAFORM_CLAUDE_MD_REL_PATH = "terraform/CLAUDE.md"


def _write_repo(
    tmp_path: Path,
    *,
    terraform_claude_md_text: str = f"See `{_CONTRACT_REL_PATH}` for the full CC-web operating procedure.\n",
    referenced_repo_paths: list[str] | None = None,
    create_referenced_files: bool = True,
    write_contract: bool = True,
    write_terraform_claude_md: bool = True,
) -> Path:
    if referenced_repo_paths is None:
        referenced_repo_paths = ["some/real/file.py", "another/real-file.yaml"]

    if create_referenced_files:
        for rel in referenced_repo_paths:
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("placeholder\n", encoding="utf-8")

    if write_contract:
        contract_dir = tmp_path / "docs" / "contracts"
        contract_dir.mkdir(parents=True, exist_ok=True)
        contract_body = {
            "contract": {
                "id": "terraform-cc-web-operations",
                "class": "D",
                "contract_version": 1,
                "status": "ratified",
            },
            "referenced_repo_paths": referenced_repo_paths,
        }
        (contract_dir / "terraform-cc-web-operations.yaml").write_text(yaml.safe_dump(contract_body), encoding="utf-8")

    if write_terraform_claude_md:
        terraform_dir = tmp_path / "terraform"
        terraform_dir.mkdir(parents=True, exist_ok=True)
        (terraform_dir / "CLAUDE.md").write_text(terraform_claude_md_text, encoding="utf-8")

    return tmp_path


class TestGreenPath:
    def test_pointer_present_and_all_paths_exist_passes(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert failed == []


class TestPointerRemovedRedPath:
    def test_terraform_claude_md_missing_pointer_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, terraform_claude_md_text="Some unrelated content with no pointer.\n")

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("no longer points at" in f for f in failed)

    def test_terraform_claude_md_missing_file_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, write_terraform_claude_md=False)

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("terraform/CLAUDE.md not found" in f for f in failed)


class TestDanglingPathRedPath:
    def test_named_path_that_does_not_exist_fails(self, tmp_path: Path) -> None:
        _write_repo(
            tmp_path,
            referenced_repo_paths=["real/file.py", "ghost/does-not-exist.py"],
            create_referenced_files=False,
        )
        (tmp_path / "real").mkdir(parents=True)
        (tmp_path / "real" / "file.py").write_text("x\n", encoding="utf-8")

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("ghost/does-not-exist.py" in f for f in failed)

    def test_all_named_paths_missing_fails_with_full_list(self, tmp_path: Path) -> None:
        _write_repo(
            tmp_path,
            referenced_repo_paths=["missing/one.py", "missing/two.yaml"],
            create_referenced_files=False,
        )

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("missing/one.py" in f and "missing/two.yaml" in f for f in failed)


class TestContractShapeEdgeCases:
    def test_contract_missing_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, write_contract=False)

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any(_CONTRACT_REL_PATH in f and "not found" in f for f in failed)

    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        (tmp_path / "docs" / "contracts" / "terraform-cc-web-operations.yaml").write_text(
            "key: [unterminated\n", encoding="utf-8"
        )

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("could not parse" in f for f in failed)

    def test_missing_referenced_repo_paths_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        contract_dir = tmp_path / "docs" / "contracts"
        contract_body = {
            "contract": {
                "id": "terraform-cc-web-operations",
                "class": "D",
                "contract_version": 1,
                "status": "ratified",
            }
        }
        (contract_dir / "terraform-cc-web-operations.yaml").write_text(yaml.safe_dump(contract_body), encoding="utf-8")

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("missing or empty" in f for f in failed)

    def test_empty_referenced_repo_paths_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, referenced_repo_paths=[], create_referenced_files=False)

        failed: list[str] = []
        validate_terraform_cc_web_operations(failed, repo_root=tmp_path)

        assert any("missing or empty" in f for f in failed)
