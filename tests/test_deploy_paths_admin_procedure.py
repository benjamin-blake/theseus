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


def test_admin_procedure_has_self_access_isolation_step() -> None:
    """A step must name both BootstrapStateProvisioning and IAMFull, forbid bundling them with any
    other change, and sit before the POST-APPLY simulate step (PLAN-platform-iam-bootstrap-adopt)."""
    steps = _procedure_steps()

    isolation_idx = next(
        (i for i, s in enumerate(steps) if "BootstrapStateProvisioning" in s and "IAMFull" in s),
        None,
    )
    assert isolation_idx is not None, "no procedure step names both BootstrapStateProvisioning and IAMFull"
    isolation_step = steps[isolation_idx]
    assert "no other change" in isolation_step, "the self-access isolation step must forbid bundling other changes"

    post_apply_idx = next((i for i, s in enumerate(steps) if s.lstrip().startswith("POST-APPLY")), None)
    assert post_apply_idx is not None, "the existing POST-APPLY simulate step did not survive"
    assert isolation_idx < post_apply_idx, "the self-access isolation step must precede the POST-APPLY step"


def test_split_apply_step_excludes_platform_iam() -> None:
    """PLAN-platform-iam-personal-release (Decision 219): the SPLIT-APPLY step no longer names
    PlatformDev/PlatformAdmin IAM as its trigger -- that IAM now lives in terraform/bootstrap and
    changes through this loop with no split and no -target -- and the PRE-APPLY, self-access
    isolation and POST-APPLY steps survive in order around it."""
    steps = _procedure_steps()

    split_apply_idx = next((i for i, s in enumerate(steps) if s.lstrip().startswith("SPLIT-APPLY")), None)
    assert split_apply_idx is not None, "no procedure step begins with the SPLIT-APPLY token"
    split_apply_step = steps[split_apply_idx]
    assert "terraform/bootstrap" in split_apply_step
    assert "no split" in split_apply_step
    assert "any inline-policy write on PlatformDev" not in split_apply_step

    pre_apply_idx = next((i for i, s in enumerate(steps) if s.lstrip().startswith("PRE-APPLY")), None)
    isolation_idx = next((i for i, s in enumerate(steps) if "BootstrapStateProvisioning" in s and "IAMFull" in s), None)
    post_apply_idx = next((i for i, s in enumerate(steps) if s.lstrip().startswith("POST-APPLY")), None)
    assert None not in (pre_apply_idx, isolation_idx, post_apply_idx), "a surrounding step did not survive"
    assert split_apply_idx < pre_apply_idx < isolation_idx < post_apply_idx, (
        "SPLIT-APPLY, PRE-APPLY, the self-access isolation step and POST-APPLY must stay in that order"
    )


class TestPreMergeLivePlan:
    """rec-4140 / admin_out_of_band.pre_merge_live_plan: the standing rule's contract key, its
    amendment_log entry, and the four skill pointers (planning, implement, code-review,
    plan-critique). No exact rule-length assertion (tests/CLAUDE.md count-coupling rule)."""

    SKILL_PATHS = (
        Path(".claude/skills/planning/SKILL.md"),
        Path(".claude/skills/implement/SKILL.md"),
        Path(".claude/skills/code-review/SKILL.md"),
        Path(".claude/skills/plan-critique/SKILL.md"),
    )

    def _doc(self) -> dict:
        return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_key_exists_with_description(self) -> None:
        key = self._doc()["admin_out_of_band"]["pre_merge_live_plan"]
        assert isinstance(key.get("description"), str) and key["description"].strip()

    def test_rule_clause_order(self) -> None:
        rule = self._doc()["admin_out_of_band"]["pre_merge_live_plan"]["rule"]
        assert isinstance(rule, list) and len(rule) >= 3
        assert rule[0].lstrip().startswith("PRE-MERGE GATE (ADMIN)")
        assert rule[1].lstrip().startswith("ENVIRONMENT CHECK")
        assert rule[2].lstrip().startswith("V3 RESOLUTION")

    def test_rule_has_decision_101_counts_only_entry(self) -> None:
        rule = self._doc()["admin_out_of_band"]["pre_merge_live_plan"]["rule"]
        assert any("Decision 101" in entry for entry in rule), "no rule entry names Decision 101"

    def test_enforcement_names_the_validator(self) -> None:
        key = self._doc()["admin_out_of_band"]["pre_merge_live_plan"]
        assert "validate_admin_root_premerge_gate" in key.get("enforcement", "")

    def test_precedent_present(self) -> None:
        key = self._doc()["admin_out_of_band"]["pre_merge_live_plan"]
        assert isinstance(key.get("precedent"), str) and key["precedent"].strip()

    def test_an_amendment_log_entry_names_the_key(self) -> None:
        """Presence, not position: a later plan (e.g. bootstrap-adopt, personal-release) may
        prepend its own amendment_log entry, which would otherwise displace this one from index
        0 without this plan's own entry ever having gone missing."""
        amendments = self._doc()["amendment_log"]
        assert isinstance(amendments, list) and amendments
        assert any("pre_merge_live_plan" in entry.get("summary", "") for entry in amendments)

    def test_pre_existing_pre_apply_test_unchanged(self) -> None:
        """Confirms this class's addition did not disturb the pre-existing PRE-APPLY test."""
        test_admin_procedure_has_preapply_grant_surface_step()

    def test_each_skill_points_at_the_rule(self) -> None:
        for path in self.SKILL_PATHS:
            text = path.read_text(encoding="utf-8")
            assert "admin_out_of_band.pre_merge_live_plan" in text, f"{path} missing the pointer"
