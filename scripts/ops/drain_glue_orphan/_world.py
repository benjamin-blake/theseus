"""World-state derivation and gating for the Decision 178 clause 4 drain runbook.

Behaviour-preserving move from the single-file module this package replaced: parses the two
workflow YAMLs plus authority_budget.json for the four routing invariants, reads the raw tfstate
object and the convergence record, and gates the remove/converge preconditions. Nothing here
performs GitHub I/O -- that lives in _github.py; nothing here orchestrates a CLI step -- that
lives in _phases.py and __main__.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from scripts.ci import reconcile_target

_ROOT = Path(__file__).resolve().parents[3]
_TFSTATE_BUCKET = "agent-platform-data-lake"
_TFSTATE_KEY = "tfstate/personal/sandbox/terraform.tfstate"
_ORPHAN_TYPE = "aws_glue_catalog_database"
_ORPHAN_NAME = "ops"
_BUNDLED_REC_IDS = ("rec-3348", "rec-3328")
_APPLY_SANDBOX_WORKFLOW_REL = ".github/workflows/terraform-apply-sandbox.yml"
_RECONCILE_WORKFLOW_REL = ".github/workflows/reconcile.yml"
_AUTHORITY_BUDGET_REL = "terraform/bootstrap/authority_budget.json"


class WorldMovedError(RuntimeError):
    """A step's runtime-derived precondition no longer holds -- fail closed, never proceed stale."""


# ---------------------------------------------------------------------------
# ASSERT: the four routing invariants, parsed from committed STRUCTURED source (never grep).
# ---------------------------------------------------------------------------


def assert_workflow_invariants(repo_root: Path = _ROOT) -> None:
    """Parse (never grep/substring) the two workflow YAMLs + authority_budget.json for the four
    facts this drain's routing depends on. A substring test for "aws_iam_role" against
    in_budget_resource_types INVERTS the verdict (matches the aws_iam_role_policy prefix); a
    file-level grep for event_name false-positives on reconcile.yml's own comment about
    apply-sandbox. Raises WorldMovedError naming every violated invariant, never silently."""
    apply_sandbox = yaml.safe_load((repo_root / _APPLY_SANDBOX_WORKFLOW_REL).read_text(encoding="utf-8"))
    reconcile_wf = yaml.safe_load((repo_root / _RECONCILE_WORKFLOW_REL).read_text(encoding="utf-8"))
    budget = json.loads((repo_root / _AUTHORITY_BUDGET_REL).read_text(encoding="utf-8"))

    violations: list[str] = []

    gated_apply_if = str(apply_sandbox.get("jobs", {}).get("gated-apply", {}).get("if", ""))
    if "github.event_name == 'push'" in gated_apply_if:
        violations.append(
            "(a) terraform-apply-sandbox.yml gated-apply is still push-gated; the dispatch-routed gated apply is unreachable"
        )

    gar_if = str(reconcile_wf.get("jobs", {}).get("gated-apply-reconcile", {}).get("if", ""))
    if "github.event_name == 'push'" in gar_if:
        violations.append("(b) reconcile.yml gated-apply-reconcile now carries a push condition")

    in_budget_types = budget.get("in_budget_resource_types", [])
    if "aws_iam_role" in in_budget_types:
        violations.append("(c) authority_budget.json in_budget_resource_types now exact-lists aws_iam_role")

    apply_steps = apply_sandbox.get("jobs", {}).get("apply-sandbox", {}).get("steps", [])
    checkout = apply_steps[0] if apply_steps else {}
    if "ref" in (checkout.get("with") or {}):
        violations.append("(d) apply-sandbox's checkout step now pins a ref:")
    fresh_plan: dict[str, Any] = next((s for s in apply_steps if s.get("id") == "plan"), {})
    if "github.event_name == 'workflow_dispatch'" not in str(fresh_plan.get("if", "")):
        violations.append("(d) apply-sandbox's fresh-plan step is no longer gated on workflow_dispatch")

    if violations:
        raise WorldMovedError("world has moved -- re-assess: " + "; ".join(violations))


# ---------------------------------------------------------------------------
# DERIVE: runtime world-state (never a hardcoded SHA, rec id, or assumption).
# ---------------------------------------------------------------------------


def tfstate_has_orphan(state_s3_client: Any, bucket: str = _TFSTATE_BUCKET, key: str = _TFSTATE_KEY) -> bool:
    """Read-only S3 get_object on the tfstate object. Decision 120 reversed Decision 119's blanket
    bar on a local terraform init (the provider mirror now syncs to $HOME/.terraform-mirror on the
    ADMIN container), so a local `terraform show` is possible here today -- but the raw S3 read
    still wins on three independent grounds: no init cost, no state-lock contention against a
    concurrent operator apply, and it runs under the tfstate-reading identity alone
    (agent_platform_admin) rather than needing a provider plugin. Takes the ADMIN-profile client
    specifically -- the caller decides which profile's client to pass; this is the ONE call in the
    whole module that may receive the admin-profile client (VP5 / Decision 143 per-leg split)."""
    response = state_s3_client.get_object(Bucket=bucket, Key=key)
    state = json.loads(response["Body"].read())
    return any(r.get("type") == _ORPHAN_TYPE and r.get("name") == _ORPHAN_NAME for r in state.get("resources", []))


@dataclass
class RemoveState:
    record: Optional[dict]
    target: reconcile_target.ReconcileTarget
    orphan_in_state: bool
    rec_open: dict[str, bool]


def derive_remove_state(
    profile_s3_client: Any,
    state_s3_client: Any,
    rec_reader: Callable[[str], list[dict[str, Any]]],
) -> RemoveState:
    """Per-leg AWS identity split (Decision 143, VP5): the convergence record and the DuckLake
    reader run under profile_s3_client (agent_platform); the raw tfstate read runs under
    state_s3_client (agent_platform_admin) -- PlatformDev has no tfstate grant (DEP-13 / Decision
    113) and that deny is deliberate, never worked around by widening it."""
    record = reconcile_target.read_convergence_record(profile_s3_client)
    target = reconcile_target.resolve_reconcile_target(record)
    orphan_in_state = tfstate_has_orphan(state_s3_client)
    rec_open = {rec_id: reconcile_target.validate_rec_id_open(rec_id, rec_reader) for rec_id in _BUNDLED_REC_IDS}
    return RemoveState(record=record, target=target, orphan_in_state=orphan_in_state, rec_open=rec_open)


def gate_remove_preconditions(state: RemoveState) -> None:
    if not state.target.actionable:
        raise WorldMovedError(f"world has moved -- re-assess: convergence record is not reconcilable ({state.target.reason})")
    if not state.orphan_in_state:
        raise WorldMovedError(f"world has moved -- re-assess: {_ORPHAN_TYPE}.{_ORPHAN_NAME} is no longer in tfstate")
    # Both this gate and phase_close require the bundled recs CLOSED, and that is not a copy-paste
    # slip: rec-autoclose.yml flips them open -> closed at the merge of the PR that puts the restored
    # grant in HCL, and that merge is the precondition for the drain existing at all. Gating remove on
    # "still open" made this phase unreachable in its own intended sequence -- it could only run before
    # the merge that makes the destroy authorizable.
    still_open = sorted(rec_id for rec_id, is_open in state.rec_open.items() if is_open)
    if still_open:
        raise WorldMovedError(
            f"world has moved -- re-assess: bundled rec(s) still open: {still_open} -- the enabling PR has not "
            "merged, so the restored grant is not in HCL and the destroy would AccessDeny as the original apply did"
        )


def gate_converge_preconditions(record: Optional[dict], orphan_in_state: bool) -> None:
    if record is None or record.get("status") != "red":
        raise WorldMovedError(f"world has moved -- re-assess: convergence record is not CONVERGENCE_RED ({record!r})")
    if orphan_in_state:
        raise WorldMovedError(
            f"world has moved -- re-assess: {_ORPHAN_TYPE}.{_ORPHAN_NAME} is still in tfstate -- drain phase 1 has not landed"
        )
