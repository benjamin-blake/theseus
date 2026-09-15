"""Facade package for the CI-workflow structural guard suite (Decision 128 decomposition).

Re-exports the full public surface of the former flat scripts/verify_ci_workflow.py module so
every existing import site (including the private guard names ci_guards checks import by name)
keeps working unchanged.
"""

from __future__ import annotations

from scripts.verify_ci_workflow._apply import (
    _RECOVERY_FALLTHROUGH_STEP_IDS,
    _RECOVERY_FRESH_PLAN_NOT_PENDING,
    _RECOVERY_FRESH_PLAN_PENDING,
    _RECOVERY_FRESH_PLAN_SIGNAL,
    _RECOVERY_LEGACY_STALE_SIGNAL,
    _RECOVERY_STALE_DETECTION_MARKERS,
    _check_apply_rca_fallback,
    _check_recovery_workflow_topology,
    _check_terraform_apply_concurrency,
    _recovery_step_body,
)
from scripts.verify_ci_workflow._ci_rca import (
    _CI_RCA_FETCH_STEP,
    _PATTERN_MATCHING_CONSTRUCT_RE,
    _REQUIRED_CI_RCA_WORKFLOWS,
    _check_canary,
    _check_ci_rca_authority_anchor,
    _check_ci_rca_fetch_classification,
    _check_ci_rca_filter,
    _ci_rca_fetch_source_comment,
    _decision_72_entry,
    _read_ci_rca_authority_sources,
)
from scripts.verify_ci_workflow._ci_yaml import (
    _CHECK_LIKE_RE,
    _MODULE_INVOCATION_RE,
    _admits_pull_request,
    _check_concurrency,
    _check_fetch_depth,
    _check_full_tier_runtime_lock,
    _check_jobs_and_flags,
    _check_signal_green_needs,
    _check_validate_single_source,
    _is_truthy_concurrency_flag,
)
from scripts.verify_ci_workflow._cli import _COMMANDS, main
from scripts.verify_ci_workflow._shared import _assert_runtime_lock, _get_step_run_text, _get_steps_text, _load

__all__ = [
    "_CHECK_LIKE_RE",
    "_CI_RCA_FETCH_STEP",
    "_COMMANDS",
    "_MODULE_INVOCATION_RE",
    "_PATTERN_MATCHING_CONSTRUCT_RE",
    "_RECOVERY_FALLTHROUGH_STEP_IDS",
    "_RECOVERY_FRESH_PLAN_NOT_PENDING",
    "_RECOVERY_FRESH_PLAN_PENDING",
    "_RECOVERY_FRESH_PLAN_SIGNAL",
    "_RECOVERY_LEGACY_STALE_SIGNAL",
    "_RECOVERY_STALE_DETECTION_MARKERS",
    "_REQUIRED_CI_RCA_WORKFLOWS",
    "_admits_pull_request",
    "_assert_runtime_lock",
    "_check_apply_rca_fallback",
    "_check_canary",
    "_check_ci_rca_authority_anchor",
    "_check_ci_rca_fetch_classification",
    "_check_ci_rca_filter",
    "_check_concurrency",
    "_check_fetch_depth",
    "_check_full_tier_runtime_lock",
    "_check_jobs_and_flags",
    "_check_recovery_workflow_topology",
    "_check_signal_green_needs",
    "_check_terraform_apply_concurrency",
    "_check_validate_single_source",
    "_ci_rca_fetch_source_comment",
    "_decision_72_entry",
    "_get_step_run_text",
    "_get_steps_text",
    "_is_truthy_concurrency_flag",
    "_load",
    "_read_ci_rca_authority_sources",
    "_recovery_step_body",
    "main",
]
