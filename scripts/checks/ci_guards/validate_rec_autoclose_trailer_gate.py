"""Delegation-shape pin for the Resolves: trailer gate (rec-3775 / rec-2922 / rec-3901 / Decision 201).

Registered --pre check (Decision 60) pinning nine facts, never re-deriving clause text from
`docs/contracts/git-ops.yaml` or `docs/contracts/ci-rca-lifecycle.yaml` -- both of which this
module READS (Decision 168 point 2), rather than hardcoding their clauses, so the
`{check: validate_rec_autoclose_trailer_gate}` evaluator declaration genuinely resolves for BOTH
contract edits Decision 201 makes:

  1. `.github/workflows/ci.yml`'s trailer-closure job delegates to the
     `scripts.rec_trailer_acceptance` thin adapter (Decision 162 spirit), which itself imports
     `close_recs_from_trailer` -- the two-hop delegation Decision 201's relocation replaced the
     direct rec-autoclose.yml delegation with.
  2. `scripts/ops_portal/ci_rca_lifecycle.py` references the merge-leg gate module
     (`trailer_closure_gate`) and its predicate (`merge_leg_refuses`).
  3. `docs/contracts/git-ops.yaml`'s `resolves_trailer` clause states the carrier rule (names
     "implementation merge").
  4. `docs/contracts/git-ops.yaml`'s `resolves_trailer` clause states the placement rule (names a
     `Key: value`-shaped block).
  5. RETIRED-DELEGATION: `.github/workflows/rec-autoclose.yml` no longer names
     `close_recs_from_trailer` -- the cutover's standing stale-reference guard. Without this, a
     re-added closure step in rec-autoclose.yml would close recs while bypassing the Decision 201
     verdict gate in silence (assert_acceptance_verdict returns None when no record is supplied),
     and a VP step alone evaporates at merge.
  6. Decision 143 discharge, ESCAPE-FREE (no marker, no config allowlist, no skip path): the
     `trailer-acceptance-evaluate` job in ci.yml declares no `id-token` permission and touches no
     `secrets.` reference anywhere in its steps.
  7. `scripts/rec_trailer_acceptance.py`'s `close` verb passes `acceptance_verdicts=` AND
     `require_acceptance_verdict=True` into `close_recs_from_trailer` -- the STRUCTURAL binding
     (Decision 163) that keeps the trailer path from failing open on an absent verdict.
  8. `docs/contracts/git-ops.yaml` declares the `trailer_acceptance_gate` key.
  9. `docs/contracts/ci-rca-lifecycle.yaml` states its Decision 201 clause (names ci.yml).

Filesystem-only: no subprocess, no network, matching every sibling ci_guards module. Declares an
examined()/skipped() outcome on every reachable path (Decision 170).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from scripts.checks import _common, registry

_GIT_OPS_CONTRACT = "docs/contracts/git-ops.yaml"
_CI_RCA_LIFECYCLE_CONTRACT = "docs/contracts/ci-rca-lifecycle.yaml"
_AUTOCLOSE_WORKFLOW_PATH = ".github/workflows/rec-autoclose.yml"
_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
_TRAILER_MODULE_PATH = "scripts/rec_trailer_acceptance.py"
_LIFECYCLE_MODULE_PATH = "scripts/ops_portal/ci_rca_lifecycle.py"
_EVALUATE_JOB = "trailer-acceptance-evaluate"
_PREFIX = "rec-autoclose-trailer-gate"

_ALL_SOURCES = (
    _GIT_OPS_CONTRACT,
    _CI_RCA_LIFECYCLE_CONTRACT,
    _AUTOCLOSE_WORKFLOW_PATH,
    _CI_WORKFLOW_PATH,
    _TRAILER_MODULE_PATH,
    _LIFECYCLE_MODULE_PATH,
)


def _read(root: Path, rel: str) -> Optional[str]:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def _evaluator_job_is_credential_free(ci_workflow_text: str) -> bool:
    """Decision 143 discharge, ESCAPE-FREE: the evaluator job declares no `id-token` permission
    and no step touches a `secrets.` reference anywhere in the job body."""
    try:
        data = yaml.safe_load(ci_workflow_text)
    except yaml.YAMLError:
        return False
    jobs = data.get("jobs") if isinstance(data, dict) else None
    job = jobs.get(_EVALUATE_JOB) if isinstance(jobs, dict) else None
    if not isinstance(job, dict):
        return False
    permissions = job.get("permissions") or {}
    if not isinstance(permissions, dict) or "id-token" in permissions:
        return False
    job_text = yaml.safe_dump(job)
    return "secrets." not in job_text


@registry.register("validate_rec_autoclose_trailer_gate", owner="platform")
def validate_rec_autoclose_trailer_gate(failed: list[str]) -> None:
    """Pin the trailer gate's delegation shape post-Decision-201-relocation. See module docstring
    for the nine assertions."""
    print("\n=== rec-autoclose / ci.yml trailer gate delegation shape (Decision 201) ===")
    root = _common.ROOT

    sources = {rel: _read(root, rel) for rel in _ALL_SOURCES}
    missing = [rel for rel, text in sources.items() if text is None]
    if missing:
        print(f"  FAIL: could not read {missing}")
        failed.append(f"{_PREFIX}: could not read {missing}")
        registry.skipped(f"unreadable source(s): {missing}")
        return

    autoclose_text = sources[_AUTOCLOSE_WORKFLOW_PATH] or ""
    ci_workflow_text = sources[_CI_WORKFLOW_PATH] or ""
    trailer_module_text = sources[_TRAILER_MODULE_PATH] or ""
    lifecycle_text = sources[_LIFECYCLE_MODULE_PATH] or ""
    git_ops_text = sources[_GIT_OPS_CONTRACT] or ""
    git_ops_lower = git_ops_text.lower()
    ci_rca_lifecycle_text = sources[_CI_RCA_LIFECYCLE_CONTRACT] or ""
    examined = 0

    examined += 1
    delegates = "scripts.rec_trailer_acceptance" in ci_workflow_text and "close_recs_from_trailer" in trailer_module_text
    print(f"  {'PASS' if delegates else 'FAIL'}: ci.yml delegates to rec_trailer_acceptance -> close_recs_from_trailer")
    if not delegates:
        failed.append(f"{_PREFIX}: {_CI_WORKFLOW_PATH} / {_TRAILER_MODULE_PATH} no longer delegate closure")

    examined += 1
    references_gate = "trailer_closure_gate" in lifecycle_text and "merge_leg_refuses" in lifecycle_text
    print(f"  {'PASS' if references_gate else 'FAIL'}: ci_rca_lifecycle.py references the merge-leg gate")
    if not references_gate:
        failed.append(f"{_PREFIX}: {_LIFECYCLE_MODULE_PATH} no longer references the merge-leg gate")

    examined += 1
    states_carrier = "implementation merge" in git_ops_lower
    print(f"  {'PASS' if states_carrier else 'FAIL'}: git-ops.yaml states the carrier rule")
    if not states_carrier:
        failed.append(f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer states the carrier rule (implementation merge)")

    examined += 1
    states_placement = "key: value" in git_ops_lower or "key:value" in git_ops_lower
    print(f"  {'PASS' if states_placement else 'FAIL'}: git-ops.yaml states the placement rule")
    if not states_placement:
        failed.append(f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer states the placement rule (Key: value block)")

    examined += 1
    retired = "close_recs_from_trailer" not in autoclose_text
    print(f"  {'PASS' if retired else 'FAIL'}: rec-autoclose.yml no longer names close_recs_from_trailer")
    if not retired:
        failed.append(
            f"{_PREFIX}: {_AUTOCLOSE_WORKFLOW_PATH} still names close_recs_from_trailer -- a re-added closure "
            "step there would bypass the Decision 201 verdict gate in silence"
        )

    examined += 1
    credential_free = _evaluator_job_is_credential_free(ci_workflow_text)
    print(f"  {'PASS' if credential_free else 'FAIL'}: {_EVALUATE_JOB} job declares no id-token permission and no secret")
    if not credential_free:
        failed.append(f"{_PREFIX}: {_CI_WORKFLOW_PATH}'s {_EVALUATE_JOB} job is not credential-free (Decision 143)")

    examined += 1
    structural_binding = (
        "acceptance_verdicts=" in trailer_module_text and "require_acceptance_verdict=True" in trailer_module_text
    )
    print(
        f"  {'PASS' if structural_binding else 'FAIL'}: rec_trailer_acceptance.py's close verb passes the structural binding"
    )
    if not structural_binding:
        failed.append(
            f"{_PREFIX}: {_TRAILER_MODULE_PATH} no longer passes acceptance_verdicts=/require_acceptance_verdict=True"
        )

    examined += 1
    declares_gate = "trailer_acceptance_gate" in git_ops_text
    print(f"  {'PASS' if declares_gate else 'FAIL'}: git-ops.yaml declares trailer_acceptance_gate")
    if not declares_gate:
        failed.append(f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer declares trailer_acceptance_gate")

    examined += 1
    lifecycle_contract_updated = "ci.yml" in ci_rca_lifecycle_text
    print(f"  {'PASS' if lifecycle_contract_updated else 'FAIL'}: ci-rca-lifecycle.yaml names ci.yml")
    if not lifecycle_contract_updated:
        failed.append(f"{_PREFIX}: {_CI_RCA_LIFECYCLE_CONTRACT} no longer names ci.yml")

    registry.examined(examined, unit="delegation_assertions")
