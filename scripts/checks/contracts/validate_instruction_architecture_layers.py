"""Instruction architecture layer-claims check (instruction-architecture.yaml content_locations)."""

from __future__ import annotations

from scripts.checks import _common, registry
from scripts.checks.contracts._shared import _load_prompt_compliance

# Full-path literal (migration-step-3-grandfathering): makes this module's own
# {check: validate_instruction_architecture_layers} evaluator declaration resolve honestly --
# scripts/prompt_compliance.py's dynamic importlib load (via _load_prompt_compliance) is two
# hops out and invisible to the one-hop AST import scan, so without this literal the evaluator
# would not resolve at all. Also backs the presence assertion below, closing a real
# silent-fallback hole: _load_instruction_architecture() degrades a missing/unparseable contract
# to a stub dict with empty layers, which would otherwise let this check pass VACUOUSLY.
_CONTRACT_REL_PATH = "docs/contracts/instruction-architecture.yaml"


@registry.register("validate_instruction_architecture_layers", owner="platform")
def validate_instruction_architecture_layers(failed: list[str]) -> None:
    """Check that every layer in instruction-architecture.yaml resolves to at least one file.

    Declares examined(content_locations globs judged across all layers, unit="content_locations")
    (Decision 170); a contract with no globs (including the loader's empty-layers fallback) is
    examined(0). An absent prompt_compliance.py declares skipped().
    """
    print("\n=== Instruction architecture layer claims ===")
    contract_path = _common.ROOT / _CONTRACT_REL_PATH
    if not contract_path.is_file():
        failed.append(
            f"Instruction architecture layer claims: {_CONTRACT_REL_PATH} does not exist -- cannot check layer claims."
        )
        return

    compliance = _load_prompt_compliance()
    if compliance is None:
        print("prompt_compliance.py not found — skipping layer claims check.")
        registry.skipped("scripts/prompt_compliance.py not found")
        return

    contract = compliance._load_instruction_architecture()
    violations = compliance.check_layer_compliance(contract)
    layers = contract.get("layers", [])
    examined = sum(1 for layer in layers for _ in layer.get("content_locations", []))
    registry.examined(examined, unit="content_locations")
    if violations:
        print("Layer claims violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Instruction architecture layer claims")
    else:
        print(f"Layer claims: {len(layers)} layer(s), {examined} content_locations checked, all resolve.")
