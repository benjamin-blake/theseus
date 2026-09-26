"""Delegation-shape pin for the Resolves: trailer gate (rec-3775 / rec-2922 / rec-3901 / Decision 201).

Registered --pre check (Decision 60) pinning twelve facts, never re-deriving clause text from
`docs/contracts/git-ops.yaml` or `docs/contracts/ci-rca-lifecycle.yaml` -- both of which this
module READS (Decision 168 point 2), rather than hardcoding their clauses, so the
`{check: validate_rec_autoclose_trailer_gate}` evaluator declaration genuinely resolves for every
contract edit Decision 201 makes (slice A and slice B alike):

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
  10. Decision 143 boundary, DERIVED (Decision 187 point 1 -- never a job-name literal, so a
      rename or a DUPLICATE cannot escape it): every ci.yml job that DOWNLOADS the pytest-junit
      report (the artifact name is itself derived from the upload step whose path matches
      pytest's own `--junitxml` output, never a hardcoded artifact-name literal) declares no
      `id-token` permission and touches no `secrets.` reference. "Downloads the report" is
      load-bearing: main-validate UPLOADS it while holding `id-token: write`, and trailer-closure
      downloads only the census/verdict documents, never the report itself -- neither belongs in
      this derived set.
  11. Same derived set, same-run provenance: every one of those jobs' download-artifact step for
      that artifact declares no `run-id` input, so the report it reads can only be the current
      run's.
  12. `docs/contracts/git-ops.yaml` declares the `source_admission` clause (the literal,
      underscore-spelled key the registered evaluator and VP step 10's grep both read).

Filesystem-only: no subprocess, no network, matching every sibling ci_guards module. Declares an
examined()/skipped() outcome on every reachable path (Decision 170); the derived-set assertions
(10-11) FAIL rather than pass vacuously if the derived set is ever empty.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Optional

import yaml

from scripts.checks import _common, registry

_JUNIT_REPORT_PATH = "logs/debug/pytest-junit.xml"

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
    return _job_is_credential_free(job)


def _job_is_credential_free(job: dict[str, Any]) -> bool:
    permissions = job.get("permissions") or {}
    if not isinstance(permissions, dict) or "id-token" in permissions:
        return False
    job_text = yaml.safe_dump(job)
    return "secrets." not in job_text


def _derive_pytest_junit_artifact_name(jobs: dict[str, Any]) -> Optional[str]:
    """Derive the pytest-junit artifact's NAME from the step that uploads it -- anchored on the
    real `--junitxml` output path (Decision 187 point 1: never a hardcoded artifact-name
    literal), so a rename of the artifact's `name:` is followed automatically."""
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not str(step.get("uses") or "").startswith("actions/upload-artifact"):
                continue
            with_block = step.get("with") or {}
            if isinstance(with_block, dict) and with_block.get("path") == _JUNIT_REPORT_PATH:
                name = with_block.get("name")
                return name if isinstance(name, str) else None
    return None


def _download_step_for_artifact(job: dict[str, Any], artifact_name: str) -> Optional[dict[str, Any]]:
    for step in job.get("steps") or []:
        if not isinstance(step, dict) or not str(step.get("uses") or "").startswith("actions/download-artifact"):
            continue
        with_block = step.get("with") or {}
        if not isinstance(with_block, dict):
            continue
        name_matches = with_block.get("name") == artifact_name
        pattern = with_block.get("pattern")
        pattern_matches = isinstance(pattern, str) and fnmatch.fnmatch(artifact_name, pattern)
        if name_matches or pattern_matches:
            return with_block
    return None


def _assert_clause(failed: list[str], label: str, condition: bool, fail_message: str) -> int:
    """Shared PASS/FAIL print-and-record shape for a single boolean clause -- extracted so the
    parent check's branch count stays under the Decision 43 cyclomatic-complexity limit. Always
    returns 1 (one assertion examined)."""
    print(f"  {'PASS' if condition else 'FAIL'}: {label}")
    if not condition:
        failed.append(fail_message)
    return 1


def _assert_derived_verdict_consuming_jobs(ci_workflow_text: str, failed: list[str]) -> int:
    """Assertions 10-11 (Decision 143 boundary + same-run provenance), isolated so the parent
    check's branch count stays under the Decision 43 cyclomatic-complexity limit. Returns the
    number of assertions examined (1 if the derived set is empty, 2 otherwise)."""
    derived = _verdict_consuming_jobs(ci_workflow_text)
    if derived is None or not derived[1]:
        print("  FAIL: no ci.yml job downloads the pytest-junit report -- derived set must never be empty")
        failed.append(f"{_PREFIX}: derived verdict-consuming-job set is empty (Decision 170: never pass vacuously)")
        return 1

    jobs, consuming, artifact_name = derived
    credential_free_jobs = [name for name in consuming if _job_is_credential_free(jobs[name])]
    all_credential_free = credential_free_jobs == consuming
    print(
        f"  {'PASS' if all_credential_free else 'FAIL'}: every verdict-consuming job {consuming} is credential-free "
        f"(artifact={artifact_name!r})"
    )
    if not all_credential_free:
        offenders = sorted(set(consuming) - set(credential_free_jobs))
        failed.append(f"{_PREFIX}: verdict-consuming job(s) {offenders} declare id-token or a secret (Decision 143)")

    no_run_id = [name for name in consuming if "run-id" not in (_download_step_for_artifact(jobs[name], artifact_name) or {})]
    all_no_run_id = no_run_id == consuming
    print(f"  {'PASS' if all_no_run_id else 'FAIL'}: every verdict-consuming job's download step names no run-id")
    if not all_no_run_id:
        offenders = sorted(set(consuming) - set(no_run_id))
        failed.append(f"{_PREFIX}: verdict-consuming job(s) {offenders} download by run-id (breaks same-run provenance)")
    return 2


def _verdict_consuming_jobs(ci_workflow_text: str) -> Optional[tuple[dict[str, Any], list[str], str]]:
    """The DERIVED set: every ci.yml job whose steps download the pytest-junit report (the verdict
    ARTIFACT a junit verdict is read from -- upload jobs and jobs downloading other artifacts are
    excluded by construction). Returns (jobs, job_names, artifact_name) or None if the workflow or
    the upload step itself could not be parsed/found."""
    try:
        data = yaml.safe_load(ci_workflow_text)
    except yaml.YAMLError:
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, dict):
        return None
    artifact_name = _derive_pytest_junit_artifact_name(jobs)
    if not artifact_name:
        return None
    consuming = [
        name
        for name, job in jobs.items()
        if isinstance(job, dict) and _download_step_for_artifact(job, artifact_name) is not None
    ]
    return jobs, consuming, artifact_name


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

    examined += _assert_clause(
        failed,
        "ci.yml delegates to rec_trailer_acceptance -> close_recs_from_trailer",
        "scripts.rec_trailer_acceptance" in ci_workflow_text and "close_recs_from_trailer" in trailer_module_text,
        f"{_PREFIX}: {_CI_WORKFLOW_PATH} / {_TRAILER_MODULE_PATH} no longer delegate closure",
    )
    examined += _assert_clause(
        failed,
        "ci_rca_lifecycle.py references the merge-leg gate",
        "trailer_closure_gate" in lifecycle_text and "merge_leg_refuses" in lifecycle_text,
        f"{_PREFIX}: {_LIFECYCLE_MODULE_PATH} no longer references the merge-leg gate",
    )
    examined += _assert_clause(
        failed,
        "git-ops.yaml states the carrier rule",
        "implementation merge" in git_ops_lower,
        f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer states the carrier rule (implementation merge)",
    )
    examined += _assert_clause(
        failed,
        "git-ops.yaml states the placement rule",
        "key: value" in git_ops_lower or "key:value" in git_ops_lower,
        f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer states the placement rule (Key: value block)",
    )
    examined += _assert_clause(
        failed,
        "rec-autoclose.yml no longer names close_recs_from_trailer",
        "close_recs_from_trailer" not in autoclose_text,
        f"{_PREFIX}: {_AUTOCLOSE_WORKFLOW_PATH} still names close_recs_from_trailer -- a re-added closure step "
        "there would bypass the Decision 201 verdict gate in silence",
    )
    examined += _assert_clause(
        failed,
        f"{_EVALUATE_JOB} job declares no id-token permission and no secret",
        _evaluator_job_is_credential_free(ci_workflow_text),
        f"{_PREFIX}: {_CI_WORKFLOW_PATH}'s {_EVALUATE_JOB} job is not credential-free (Decision 143)",
    )
    examined += _assert_clause(
        failed,
        "rec_trailer_acceptance.py's close verb passes the structural binding",
        "acceptance_verdicts=" in trailer_module_text and "require_acceptance_verdict=True" in trailer_module_text,
        f"{_PREFIX}: {_TRAILER_MODULE_PATH} no longer passes acceptance_verdicts=/require_acceptance_verdict=True",
    )
    examined += _assert_clause(
        failed,
        "git-ops.yaml declares trailer_acceptance_gate",
        "trailer_acceptance_gate" in git_ops_text,
        f"{_PREFIX}: {_GIT_OPS_CONTRACT} no longer declares trailer_acceptance_gate",
    )
    examined += _assert_clause(
        failed,
        "ci-rca-lifecycle.yaml names ci.yml",
        "ci.yml" in ci_rca_lifecycle_text,
        f"{_PREFIX}: {_CI_RCA_LIFECYCLE_CONTRACT} no longer names ci.yml",
    )
    examined += _assert_derived_verdict_consuming_jobs(ci_workflow_text, failed)
    examined += _assert_clause(
        failed,
        "git-ops.yaml declares the source_admission clause",
        "source_admission" in git_ops_text,
        f"{_PREFIX}: {_GIT_OPS_CONTRACT} does not declare the source_admission clause",
    )

    registry.examined(examined, unit="delegation_assertions")
