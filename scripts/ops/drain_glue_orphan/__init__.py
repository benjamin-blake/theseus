"""Facade for the Decision 178 clause 4 drain runbook (Decision 124 / 80 pt 3 / 104 pattern).

Re-exports the full carried-forward surface of the single-file module this package replaced so
`from scripts.ops.drain_glue_orphan import X` and `python -m scripts.ops.drain_glue_orphan` both
keep resolving unchanged, and so tests/fixtures/drain_glue_orphan.py's imports of private names
(_TFSTATE_BUCKET, _TFSTATE_KEY) keep working.

NOT re-exported -- eleven names from the pre-split module, each superseded by this restructure rather
than dropped by accident (tests/ops/test_drain_glue_orphan_cli.py::TestFacadeSurface asserts this
list against origin/main's actual symbol table, so an UNDOCUMENTED drop still reds):
  - wait_for_terminal, correlate_dispatch: both slept in a loop; superseded by the re-invokable
    verify CLI step (Decision 76 -- no agent-side polling, the container hibernates between turns).
  - phase_remove, phase_converge: the old all-in-one orchestrators drove GitHub I/O themselves,
    which no longer compiles once GitHub I/O is agent-mediated -- superseded by
    remove_gate/remove_correlate/remove_verify and converge_gate/converge_correlate/converge_verify.
  - CorrelationResult: was correlate_dispatch's return type; every step now returns PhaseOutcome.
  - _gh_json, _live_run_lister_for, _live_run_viewer, _live_converge_run_viewer,
    _live_dispatch_reconcile, _live_dispatch_apply_sandbox: the retired shell-CLI transport VP1
    forbids outright (no shell-out import, no CLI-invocation literal anywhere in this package) --
    superseded by the mcp__github__ payload normalizers in _github.py plus the agent-mediated CLI
    steps.
"""

from __future__ import annotations

from scripts.ops.drain_glue_orphan.__main__ import (
    _build_parser,
    _dispatch,
    _live_clock,
    _load_json,
    main,
)
from scripts.ops.drain_glue_orphan._github import (
    _APPLY_SANDBOX_DISPATCH_FILE,
    _APPLY_SANDBOX_JOB_NAME,
    _DESTRUCTION_LINE,
    _GLUE_ORPHAN_ADDRESS,
    _NON_TERMINAL_STATUSES,
    _PLAN_STEP_NAME,
    _RECONCILE_DISPATCH_FILE,
    _REPO_NAME,
    _REPO_OWNER,
    _REVIEW_STEP_NAME,
    assert_log_matches_job,
    assert_plan_step_present,
    converge_guard_review_facts,
    destruction_complete,
    find_in_flight_dispatch,
    find_job,
    is_terminal,
    job_log_lines,
    no_remaining_glue_delete,
    normalize_run,
    normalize_runs,
    plan_shows_zero_destroys,
    resolve_apply_sandbox_job,
    select_dispatch_candidate,
    unwrap_jobs_payload,
)
from scripts.ops.drain_glue_orphan._phases import (
    _REMOVAL_REC_ACCEPTANCE,
    _REMOVAL_REC_CONTEXT,
    _REMOVAL_REC_TITLE,
    PhaseOutcome,
    converge_correlate,
    converge_gate,
    converge_verify,
    phase_close,
    remove_correlate,
    remove_gate,
    remove_verify,
)
from scripts.ops.drain_glue_orphan._world import (
    _APPLY_SANDBOX_WORKFLOW_REL,
    _AUTHORITY_BUDGET_REL,
    _BUNDLED_REC_IDS,
    _ORPHAN_NAME,
    _ORPHAN_TYPE,
    _RECONCILE_WORKFLOW_REL,
    _ROOT,
    _TFSTATE_BUCKET,
    _TFSTATE_KEY,
    RemoveState,
    WorldMovedError,
    assert_workflow_invariants,
    derive_remove_state,
    gate_converge_preconditions,
    gate_remove_preconditions,
    tfstate_has_orphan,
)

__all__ = [
    "_APPLY_SANDBOX_DISPATCH_FILE",
    "_APPLY_SANDBOX_JOB_NAME",
    "_APPLY_SANDBOX_WORKFLOW_REL",
    "_AUTHORITY_BUDGET_REL",
    "_BUNDLED_REC_IDS",
    "_DESTRUCTION_LINE",
    "_GLUE_ORPHAN_ADDRESS",
    "_NON_TERMINAL_STATUSES",
    "_ORPHAN_NAME",
    "_ORPHAN_TYPE",
    "_PLAN_STEP_NAME",
    "_RECONCILE_DISPATCH_FILE",
    "_RECONCILE_WORKFLOW_REL",
    "_REMOVAL_REC_ACCEPTANCE",
    "_REMOVAL_REC_CONTEXT",
    "_REMOVAL_REC_TITLE",
    "_REPO_NAME",
    "_REPO_OWNER",
    "_REVIEW_STEP_NAME",
    "_ROOT",
    "_TFSTATE_BUCKET",
    "_TFSTATE_KEY",
    "_build_parser",
    "_dispatch",
    "_live_clock",
    "_load_json",
    "PhaseOutcome",
    "RemoveState",
    "WorldMovedError",
    "assert_log_matches_job",
    "assert_plan_step_present",
    "assert_workflow_invariants",
    "converge_correlate",
    "converge_gate",
    "converge_guard_review_facts",
    "converge_verify",
    "derive_remove_state",
    "destruction_complete",
    "find_in_flight_dispatch",
    "find_job",
    "gate_converge_preconditions",
    "gate_remove_preconditions",
    "is_terminal",
    "job_log_lines",
    "main",
    "no_remaining_glue_delete",
    "normalize_run",
    "normalize_runs",
    "phase_close",
    "plan_shows_zero_destroys",
    "remove_correlate",
    "remove_gate",
    "remove_verify",
    "resolve_apply_sandbox_job",
    "select_dispatch_candidate",
    "tfstate_has_orphan",
    "unwrap_jobs_payload",
]
