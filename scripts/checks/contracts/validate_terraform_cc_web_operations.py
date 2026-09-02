"""terraform-cc-web-operations contract pointer-resolution guard
(PLAN-ambient-prose-contract-relocation).

Mirrors validate_git_ops_contract.py's two-leg design against the terraform-side pair: (1)
terraform/CLAUDE.md still carries a resolvable pointer to
docs/contracts/terraform-cc-web-operations.yaml, and (2) every repo-relative path the contract's
own `referenced_repo_paths` list declares exists in the working tree.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_REL_PATH = "docs/contracts/terraform-cc-web-operations.yaml"
_TERRAFORM_CLAUDE_MD_REL_PATH = "terraform/CLAUDE.md"


@registry.register("validate_terraform_cc_web_operations", owner="platform")
def validate_terraform_cc_web_operations(failed: list[str], *, repo_root: Path | None = None) -> None:
    """Fail if terraform/CLAUDE.md drops its pointer to terraform-cc-web-operations.yaml, or if
    the contract names a repo path that does not exist."""
    print("\n=== terraform-cc-web-operations contract pointer resolution ===")
    root = repo_root if repo_root is not None else _common.ROOT

    contract_path = root / _CONTRACT_REL_PATH
    terraform_claude_md_path = root / _TERRAFORM_CLAUDE_MD_REL_PATH

    if not contract_path.is_file():
        failed.append(f"terraform-cc-web-operations contract: {_CONTRACT_REL_PATH} not found")
        registry.skipped(f"{_CONTRACT_REL_PATH} not found")
        return

    if not terraform_claude_md_path.is_file():
        failed.append(f"terraform-cc-web-operations contract: {_TERRAFORM_CLAUDE_MD_REL_PATH} not found")
        registry.skipped(f"{_TERRAFORM_CLAUDE_MD_REL_PATH} not found")
        return

    try:
        contract_data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"terraform-cc-web-operations contract: could not parse {_CONTRACT_REL_PATH}: {exc}")
        registry.skipped(f"{_CONTRACT_REL_PATH} failed to parse")
        return

    terraform_claude_md_text = terraform_claude_md_path.read_text(encoding="utf-8")
    if _CONTRACT_REL_PATH not in terraform_claude_md_text:
        failed.append(
            f"terraform-cc-web-operations contract: {_TERRAFORM_CLAUDE_MD_REL_PATH} no longer points at {_CONTRACT_REL_PATH}"
        )

    named_paths = contract_data.get("referenced_repo_paths") if isinstance(contract_data, dict) else None
    if not isinstance(named_paths, list) or not named_paths:
        failed.append(f"terraform-cc-web-operations contract: {_CONTRACT_REL_PATH} missing or empty 'referenced_repo_paths'")
        named_paths = []

    missing = sorted(str(p) for p in named_paths if not (root / str(p)).exists())
    if missing:
        failed.append(f"terraform-cc-web-operations contract: {_CONTRACT_REL_PATH} names path(s) that do not exist: {missing}")

    registry.examined(len(named_paths), unit="named paths")

    if _CONTRACT_REL_PATH in terraform_claude_md_text and not missing and named_paths:
        print(
            f"  PASS: {_TERRAFORM_CLAUDE_MD_REL_PATH} points at {_CONTRACT_REL_PATH}; "
            f"all {len(named_paths)} named path(s) exist."
        )
