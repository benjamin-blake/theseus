"""Class D evaluator for docs/contracts/presubmit-tool-pin-escalation.yaml (Decision 168).

Derive-and-assert (rec-3861/rec-3863): the mechanism surface the contract declares -- the
whole-tree lint target set and the pre-commit base-ref config path -- must match
scripts.checks._scaffolding's live constants, so a future refactor that silently narrows either
invariant diverges from its own contract and reddens this gate, not only the unit tests.
"""

from __future__ import annotations

import yaml

from scripts.checks import _common, _scaffolding, registry

_CONTRACT_BASENAME = "presubmit-tool-pin-escalation.yaml"
_CHECK_LABEL = "Presubmit tool-pin escalation contract"


def _load_mechanism() -> dict:
    contract_path = _common.ROOT / "docs" / "contracts" / _CONTRACT_BASENAME
    data = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    mechanism = data.get("mechanism")
    if not isinstance(mechanism, dict):
        raise ValueError(f"{_CONTRACT_BASENAME}: missing or malformed top-level `mechanism:` block")
    return mechanism


@registry.register("validate_presubmit_tool_pin_escalation", owner="platform")
def validate_presubmit_tool_pin_escalation(failed: list[str]) -> None:
    """Assert the contract's declared mechanism fields agree with the live scaffolding code."""
    print(f"\n=== Presubmit tool-pin escalation contract ({_CONTRACT_BASENAME}) ===")
    try:
        mechanism = _load_mechanism()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"FAIL: could not load {_CONTRACT_BASENAME}: {type(exc).__name__}: {exc}")
        failed.append(_CHECK_LABEL)
        return

    errors: list[str] = []

    declared_targets = mechanism.get("lint_targets")
    live_targets = list(_scaffolding._LINT_TARGETS)
    if declared_targets != live_targets:
        errors.append(f"lint_targets drift: contract declares {declared_targets!r}, live is {live_targets!r}")

    declared_config_path = mechanism.get("precommit_config_path")
    live_config_path = _scaffolding._PRECOMMIT_CONFIG_PATH
    if declared_config_path != live_config_path:
        errors.append(f"precommit_config_path drift: contract declares {declared_config_path!r}, live is {live_config_path!r}")

    if errors:
        print("Contract/mechanism drift:")
        for e in errors:
            print(f"  - {e}")
        failed.append(_CHECK_LABEL)
        return

    print("Contract mechanism matches live code (lint_targets, precommit_config_path).")
    registry.examined(2, unit="mechanism_fields")
