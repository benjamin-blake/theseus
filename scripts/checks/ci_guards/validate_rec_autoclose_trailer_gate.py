"""Delegation-shape pin for the Resolves: trailer merge-leg gate (rec-3775 / rec-2922 / rec-3901).

Registered --pre check (Decision 60) pinning three facts, never re-deriving clause text from
`docs/contracts/git-ops.yaml` -- which this module READS (Decision 168 point 2), rather than
hardcoding its clauses, so the `{check: validate_rec_autoclose_trailer_gate}` evaluator
declaration genuinely resolves:

  1. `.github/workflows/rec-autoclose.yml` still delegates its closure step to
     `close_recs_from_trailer` -- the workflow's inline `run:` body is pinned at 37 lines by the
     Decision 162 R3 ratchet and stays untouched, so logic here belongs in importable Python.
  2. `scripts/ops_portal/ci_rca_lifecycle.py` references the merge-leg gate module
     (`trailer_closure_gate`) and its predicate (`merge_leg_refuses`).
  3. `docs/contracts/git-ops.yaml`'s `resolves_trailer` clause states BOTH the carrier rule
     (names "implementation merge") and the placement rule (names a `Key: value`-shaped block) --
     so the contract and the tightened parser never contradict each other.

Filesystem-only: no subprocess, no network, matching every sibling ci_guards module. Declares an
examined()/skipped() outcome on every reachable path (Decision 170).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from scripts.checks import _common, registry

_GIT_OPS_CONTRACT = "docs/contracts/git-ops.yaml"
_WORKFLOW_PATH = ".github/workflows/rec-autoclose.yml"
_LIFECYCLE_MODULE_PATH = "scripts/ops_portal/ci_rca_lifecycle.py"
_PREFIX = "rec-autoclose-trailer-gate"


def _read(root: Path, rel: str) -> Optional[str]:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError:
        return None


@registry.register("validate_rec_autoclose_trailer_gate", owner="platform")
def validate_rec_autoclose_trailer_gate(failed: list[str]) -> None:
    """Pin the merge-leg gate's delegation shape. See module docstring for the three assertions."""
    print("\n=== rec-autoclose trailer merge-leg gate delegation shape ===")
    root = _common.ROOT

    sources = {
        _WORKFLOW_PATH: _read(root, _WORKFLOW_PATH),
        _LIFECYCLE_MODULE_PATH: _read(root, _LIFECYCLE_MODULE_PATH),
        _GIT_OPS_CONTRACT: _read(root, _GIT_OPS_CONTRACT),
    }
    missing = [rel for rel, text in sources.items() if text is None]
    if missing:
        print(f"  FAIL: could not read {missing}")
        failed.append(f"{_PREFIX}: could not read {missing}")
        registry.skipped(f"unreadable source(s): {missing}")
        return

    workflow_text = sources[_WORKFLOW_PATH] or ""
    lifecycle_text = sources[_LIFECYCLE_MODULE_PATH] or ""
    contract_lower = (sources[_GIT_OPS_CONTRACT] or "").lower()
    examined = 0

    examined += 1
    delegates = "close_recs_from_trailer" in workflow_text
    print(f"  {'PASS' if delegates else 'FAIL'}: rec-autoclose.yml delegates to close_recs_from_trailer")
    if not delegates:
        failed.append(f"{_PREFIX}: {_WORKFLOW_PATH} no longer delegates to close_recs_from_trailer")

    examined += 1
    references_gate = "trailer_closure_gate" in lifecycle_text and "merge_leg_refuses" in lifecycle_text
    print(f"  {'PASS' if references_gate else 'FAIL'}: ci_rca_lifecycle.py references the merge-leg gate")
    if not references_gate:
        failed.append(f"{_PREFIX}: {_LIFECYCLE_MODULE_PATH} no longer references the merge-leg gate")

    examined += 1
    states_carrier = "implementation merge" in contract_lower
    print(f"  {'PASS' if states_carrier else 'FAIL'}: git-ops.yaml states the carrier rule")
    if not states_carrier:
        failed.append(f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer states the carrier rule (implementation merge)")

    examined += 1
    states_placement = "key: value" in contract_lower or "key:value" in contract_lower
    print(f"  {'PASS' if states_placement else 'FAIL'}: git-ops.yaml states the placement rule")
    if not states_placement:
        failed.append(f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer states the placement rule (Key: value block)")

    registry.examined(examined, unit="delegation_assertions")
