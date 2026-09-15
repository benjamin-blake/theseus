"""VP helper: the CLI command table and dispatcher for the verify_ci_workflow package."""

from __future__ import annotations

import sys

from scripts.verify_ci_workflow._apply import (
    _check_apply_rca_fallback,
    _check_recovery_workflow_topology,
    _check_terraform_apply_concurrency,
)
from scripts.verify_ci_workflow._ci_rca import _check_canary, _check_ci_rca_fetch_classification, _check_ci_rca_filter
from scripts.verify_ci_workflow._ci_yaml import (
    _check_concurrency,
    _check_fetch_depth,
    _check_full_tier_runtime_lock,
    _check_jobs_and_flags,
    _check_signal_green_needs,
    _check_validate_single_source,
)

_COMMANDS = {
    "jobs-and-flags": _check_jobs_and_flags,
    "concurrency": _check_concurrency,
    "fetch-depth": _check_fetch_depth,
    "canary": _check_canary,
    "ci-rca-filter": _check_ci_rca_filter,
    "apply-rca-fallback": _check_apply_rca_fallback,
    "validate-single-source": _check_validate_single_source,
    "signal-green-needs": _check_signal_green_needs,
    "terraform-apply-concurrency": _check_terraform_apply_concurrency,
    "ci-rca-fetch-classification": _check_ci_rca_fetch_classification,
    "full-tier-runtime-lock": _check_full_tier_runtime_lock,
    "recovery-workflow-topology": _check_recovery_workflow_topology,
}


def main() -> None:
    if len(sys.argv) == 1:
        for fn in _COMMANDS.values():
            fn()
        print("OK")
        return
    if len(sys.argv) != 2 or sys.argv[1] not in _COMMANDS:
        print(f"Usage: verify_ci_workflow.py <{'|'.join(_COMMANDS)}>", file=sys.stderr)
        sys.exit(1)

    fn = _COMMANDS[sys.argv[1]]
    try:
        fn()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("OK")
