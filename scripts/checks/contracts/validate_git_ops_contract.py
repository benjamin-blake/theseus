"""git-ops contract pointer-resolution guard (PLAN-ambient-prose-contract-relocation).

Two legs: (1) AGENTS.md still carries a resolvable pointer to docs/contracts/git-ops.yaml (the
Class D contract this module itself names, satisfying evaluator_kinds.check's basename-match
rule), and (2) every repo-relative path the contract's own `referenced_repo_paths` list declares
exists in the working tree -- so a later relocation that drops or renames a target is caught
instead of silently breaking the pointer's promise.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks import _common, registry

_CONTRACT_REL_PATH = "docs/contracts/git-ops.yaml"
_AGENTS_MD_REL_PATH = "AGENTS.md"


@registry.register("validate_git_ops_contract", owner="platform")
def validate_git_ops_contract(failed: list[str], *, repo_root: Path | None = None) -> None:
    """Fail if AGENTS.md drops its pointer to git-ops.yaml, or if the contract names a repo path
    that does not exist."""
    print("\n=== git-ops contract pointer resolution ===")
    root = repo_root if repo_root is not None else _common.ROOT

    contract_path = root / _CONTRACT_REL_PATH
    agents_md_path = root / _AGENTS_MD_REL_PATH

    if not contract_path.is_file():
        failed.append(f"git-ops contract: {_CONTRACT_REL_PATH} not found")
        registry.skipped(f"{_CONTRACT_REL_PATH} not found")
        return

    if not agents_md_path.is_file():
        failed.append(f"git-ops contract: {_AGENTS_MD_REL_PATH} not found")
        registry.skipped(f"{_AGENTS_MD_REL_PATH} not found")
        return

    try:
        contract_data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"git-ops contract: could not parse {_CONTRACT_REL_PATH}: {exc}")
        registry.skipped(f"{_CONTRACT_REL_PATH} failed to parse")
        return

    agents_text = agents_md_path.read_text(encoding="utf-8")
    if _CONTRACT_REL_PATH not in agents_text:
        failed.append(f"git-ops contract: {_AGENTS_MD_REL_PATH} no longer points at {_CONTRACT_REL_PATH}")

    named_paths = contract_data.get("referenced_repo_paths") if isinstance(contract_data, dict) else None
    if not isinstance(named_paths, list) or not named_paths:
        failed.append(f"git-ops contract: {_CONTRACT_REL_PATH} missing or empty 'referenced_repo_paths'")
        named_paths = []

    missing = sorted(str(p) for p in named_paths if not (root / str(p)).exists())
    if missing:
        failed.append(f"git-ops contract: {_CONTRACT_REL_PATH} names path(s) that do not exist: {missing}")

    registry.examined(len(named_paths), unit="named paths")

    if _CONTRACT_REL_PATH in agents_text and not missing and named_paths:
        print(f"  PASS: {_AGENTS_MD_REL_PATH} points at {_CONTRACT_REL_PATH}; all {len(named_paths)} named path(s) exist.")
