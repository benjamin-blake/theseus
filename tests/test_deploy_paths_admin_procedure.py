"""Regression guard for docs/contracts/deploy-paths.yaml's admin_out_of_band.procedure.

Decision 178 clause 4: the terraform/bootstrap grant-surface narrowing is already merged in HCL
but must not be applied while a dependent terraform/personal destroy or gated apply is still in
flight (Decision 156 point 2's lockout shape, generalized to any narrowing that races a dependent
operation). This guards the PRE-APPLY ordering step that mitigates that hazard, and that the
pre-existing POST-APPLY simulate step survives alongside it, in the right order.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CONTRACT_PATH = Path("docs/contracts/deploy-paths.yaml")


def _procedure_steps() -> list[str]:
    doc = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    steps = doc["admin_out_of_band"]["procedure"]["steps"]
    assert isinstance(steps, list) and steps, "admin_out_of_band.procedure.steps must be a non-empty list"
    return steps


def test_admin_procedure_has_preapply_grant_surface_step() -> None:
    """A PRE-APPLY step must name the grant-surface ordering precondition, and must precede the
    existing POST-APPLY simulate step -- the list is ordered, so a pre-apply instruction appended
    after the post-apply one reads wrong."""
    steps = _procedure_steps()

    pre_apply_idx = next((i for i, s in enumerate(steps) if s.lstrip().startswith("PRE-APPLY")), None)
    assert pre_apply_idx is not None, "no procedure step begins with the PRE-APPLY token"
    pre_apply_step = steps[pre_apply_idx]
    assert "grant surface" in pre_apply_step.lower(), "PRE-APPLY step must name the grant-surface precondition"

    post_apply_idx = next((i for i, s in enumerate(steps) if s.lstrip().startswith("POST-APPLY")), None)
    assert post_apply_idx is not None, "the existing POST-APPLY simulate step did not survive"
    assert "scripts.ci.iam_simulate" in steps[post_apply_idx], "POST-APPLY step must still name the live-simulate gate"

    assert pre_apply_idx < post_apply_idx, "PRE-APPLY step must precede the POST-APPLY step"
