"""Secret-value-out-of-band gate (Decision 175 / docs/contracts/secret-material-handling.yaml).

Asserts that every `resource "aws_secretsmanager_secret_version"` in the terraform tree (a
RESOURCE, never a `data` source -- a data source only reads an existing value, it does not write
one into state) is a declared exception in secret-material-handling.yaml's `value_exceptions`.
An undeclared companion `_version` resource means a secret's VALUE material entered Terraform
state without the contract's sign-off (the SECRET-VALUE-OUT-OF-BAND pattern that contract names).

Credential-free (pure text parsing over this repo's own terraform tree and its own contract) --
eligible for --pre and full tiers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from scripts.checks import _common, registry

# Path-shaped literal (evaluator_kinds.check, contract-population.yaml): a full joined literal is
# admitted as STRONGER evidence of reading than a bare basename match.
_CONTRACT_REL_PATH = "docs/contracts/secret-material-handling.yaml"

_VERSION_RESOURCE_RE = re.compile(r'resource\s+"aws_secretsmanager_secret_version"\s+"([a-zA-Z0-9_]+)"\s*\{')


def _load_exceptions(contract_path: Path) -> set[str] | None:
    """Return the declared `resource` addresses from value_exceptions, or None if unreadable."""
    if not contract_path.exists():
        return None
    data: dict[str, Any] = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    exceptions = data.get("value_exceptions") or []
    return {str(e["resource"]) for e in exceptions if isinstance(e, dict) and "resource" in e}


def _find_version_resources(terraform_dir: Path) -> list[tuple[str, str]]:
    """Return (resource_address, relative_file_path) for every _version RESOURCE block found."""
    found: list[tuple[str, str]] = []
    for tf_path in sorted(terraform_dir.rglob("*.tf")):
        text = tf_path.read_text(encoding="utf-8")
        for m in _VERSION_RESOURCE_RE.finditer(text):
            local_name = m.group(1)
            address = f"aws_secretsmanager_secret_version.{local_name}"
            rel = str(tf_path.relative_to(terraform_dir.parent))
            found.append((address, rel))
    return found


@registry.register("validate_secret_material_handling", owner="platform")
def validate_secret_material_handling(failed: list[str], root: Path | None = None) -> None:
    """Every terraform aws_secretsmanager_secret_version RESOURCE is a declared exception in
    secret-material-handling.yaml's value_exceptions, read from the contract -- never hardcoded.

    Two reachable exit paths, each with exactly one Decision 170 declaration: the contract file
    missing (or the terraform tree missing) `skipped()`s -- could not examine; the fall-through
    `examined(N, ...)`s the N _version resources actually checked against the contract.
    """
    print("\n=== Secret-material-handling gate (Decision 175 -- undeclared _version resources) ===")
    key = "secret-material-handling:"
    root = root if root is not None else _common.ROOT

    contract_path = root / _CONTRACT_REL_PATH
    exceptions = _load_exceptions(contract_path)
    terraform_dir = root / "terraform"

    if exceptions is None or not terraform_dir.is_dir():
        reason = f"{contract_path} not found" if exceptions is None else f"{terraform_dir} not found"
        print(f"  SKIP: {reason}")
        registry.skipped(reason)
        return

    version_resources = _find_version_resources(terraform_dir)
    undeclared = [(addr, rel) for addr, rel in version_resources if addr not in exceptions]

    if undeclared:
        for addr, rel in undeclared:
            failed.append(
                f"{key} {addr} in {rel} is an undeclared aws_secretsmanager_secret_version resource -- "
                f"either it is a genuine SECRET-VALUE-OUT-OF-BAND violation, or it needs a "
                f"value_exceptions entry in {_CONTRACT_REL_PATH} naming why the value is legitimately "
                "in-state."
            )
        for f in failed:
            if f.startswith(key):
                print(f"  FAIL: {f}")
    else:
        print(f"  PASS: all {len(version_resources)} aws_secretsmanager_secret_version resource(s) are declared exceptions.")

    registry.examined(len(version_resources), unit="secret_version_resources")


if __name__ == "__main__":  # pragma: no cover
    _failed: list[str] = []
    validate_secret_material_handling(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
