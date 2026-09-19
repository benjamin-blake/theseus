"""Tests for scripts/roadmap/plan_document.py's schema_version 5 assertion carrier
(docs/contracts/vp-red-before.yaml#carrier_rule): authoring-time rejection of an unsatisfiable
literal, and version-gating of the new `expected_literals` field both directions.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from scripts.roadmap.plan_document import PlanDocument, main, self_satisfying_advisories
from tests.fixtures.plan_document_helpers import _mutate

_HANDOFF_POLICY = {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"}


def _v5_step(**overrides) -> dict:
    step = {
        "step": 1,
        "phase": "pre-deploy",
        "action": "Run the example check",
        "command": "echo ok",
        "expected": "prints ok",
        "fix_if": "never fails in practice",
        "hermetic": True,
    }
    step.update(overrides)
    return step


def _v5_base(**step_overrides) -> dict:
    return _mutate(
        schema_version=5,
        handoff_policy=dict(_HANDOFF_POLICY),
        verification_plan=[_v5_step(**step_overrides)],
    )


class TestHermeticExpectedLiterals:
    def test_backtick_literal_in_hermetic_expected_is_rejected(self) -> None:
        data = _v5_base(expected="stdout prints `ok`")
        with pytest.raises(ValidationError, match="must not carry a backtick literal"):
            PlanDocument.model_validate(data)

    def test_backtick_literal_in_non_hermetic_expected_is_accepted(self) -> None:
        """A non-hermetic step's `expected` is free prose no leg ever programmatically checks --
        backticks there stay harmless markdown."""
        data = _v5_base(hermetic=False, expected="stdout prints `ok`")
        doc = PlanDocument.model_validate(data)
        assert doc.verification_plan[0].expected == "stdout prints `ok`"

    def test_expected_literals_accepted_at_v5(self) -> None:
        data = _v5_base(expected_literals=["ok"])
        doc = PlanDocument.model_validate(data)
        assert doc.verification_plan[0].expected_literals == ["ok"]

    def test_unsatisfiable_literal_is_rejected(self) -> None:
        """The historical PLAN-g4-byte-source-and-post-expiry-bound VP1 shape: a fully
        output-suppressed grep chain can never emit its asserted literal."""
        data = _v5_base(command='grep -q "ok" f.py', expected_literals=["ok"])
        with pytest.raises(ValidationError, match="cannot be emitted"):
            PlanDocument.model_validate(data)

    def test_satisfiable_literal_is_accepted(self) -> None:
        data = _v5_base(command='grep -o -m1 "ok" f.py', expected_literals=["ok"])
        doc = PlanDocument.model_validate(data)
        assert doc.verification_plan[0].expected_literals == ["ok"]

    def test_non_hermetic_step_with_expected_literals_is_rejected(self) -> None:
        data = _v5_base(hermetic=False, expected_literals=["ok"])
        with pytest.raises(ValidationError, match="only valid on a hermetic step"):
            PlanDocument.model_validate(data)

    def test_pr_1202_shape_is_accepted(self) -> None:
        """The PR #1202 fix -- three quiet existence checks plus a fourth `-o -m1` call whose
        literal it actually prints -- the mirror of the unsat guard's rejection case above."""
        command = (
            'grep -q "candidate_sizes" f.py && grep -q "strict_sizes" f.py && '
            'grep -q "post_expiry" f.py && grep -o -m1 "drain" f.py'
        )
        data = _v5_base(command=command, expected_literals=["drain"])
        doc = PlanDocument.model_validate(data)
        assert doc.verification_plan[0].expected_literals == ["drain"]


class TestVersionGating:
    def test_v4_refuses_expected_literals(self) -> None:
        data = _mutate(
            schema_version=4,
            handoff_policy=dict(_HANDOFF_POLICY),
            verification_plan=[_v5_step(expected_literals=["ok"])],
        )
        with pytest.raises(ValidationError, match="requires schema_version 5 or above"):
            PlanDocument.model_validate(data)

    def test_v5_empty_expected_literals_on_hermetic_graduate_step_is_accepted(self) -> None:
        data = _v5_base(expected_literals=[], graduation="graduate", graduation_check_id="example-check")
        doc = PlanDocument.model_validate(data)
        assert doc.verification_plan[0].expected_literals == []

    def test_v5_absent_expected_literals_on_hermetic_graduate_step_is_accepted(self) -> None:
        data = _v5_base(graduation="graduate", graduation_check_id="example-check")
        doc = PlanDocument.model_validate(data)
        assert doc.verification_plan[0].expected_literals is None

    def test_v5_implementation_still_requires_handoff_policy(self) -> None:
        data = _v5_base()
        del data["handoff_policy"]
        with pytest.raises(ValidationError, match="require handoff_policy"):
            PlanDocument.model_validate(data)

    def test_v5_implementation_with_handoff_policy_validates(self) -> None:
        doc = PlanDocument.model_validate(_v5_base())
        assert doc.schema_version == 5
        assert doc.handoff_policy is not None


class TestSelfSatisfyingAdvisories:
    """self_satisfying_advisories is ADVISORY-only -- never raises; the CLI in main() is its
    sole call site (printed as WARN, never appended to a failure list)."""

    def test_below_schema_5_returns_empty(self) -> None:
        data = _mutate(
            schema_version=4,
            handoff_policy=dict(_HANDOFF_POLICY),
            verification_plan=[_v5_step()],
        )
        doc = PlanDocument.model_validate(data)
        assert self_satisfying_advisories(doc) == []

    def test_mixed_steps_report_only_the_self_satisfying_hermetic_one(self) -> None:
        """Exercises all three continue/append paths in one pass: a non-hermetic step (skipped
        regardless of its own expected_literals), a hermetic step with no expected_literals
        (skipped), and a hermetic step whose expected_literals appear verbatim in its own
        command (reported)."""
        data = _mutate(
            schema_version=5,
            handoff_policy=dict(_HANDOFF_POLICY),
            verification_plan=[
                _v5_step(step=1, command="echo ok", expected_literals=["ok"]),
                _v5_step(step=2, hermetic=False, phase="post-deploy"),
                _v5_step(step=3, command="echo something", expected_literals=None),
            ],
        )
        doc = PlanDocument.model_validate(data)
        advisories = self_satisfying_advisories(doc)
        assert len(advisories) == 1
        assert "verification step 1" in advisories[0]
        assert "verdict=self_satisfying" in advisories[0]


class TestSelfSatisfyingCliWarning:
    """The plan_document.py CLI (main()) is the sole call site that surfaces
    self_satisfying_advisories -- printed as WARN, exit code unaffected."""

    def test_main_warns_on_self_satisfying_literal(self, tmp_path, capsys) -> None:
        data = _v5_base(command="echo ok", expected_literals=["ok"])
        target = tmp_path / f"PLAN-{data['slug']}.yaml"
        target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        assert main([str(target)]) == 0
        out = capsys.readouterr().out
        assert "PASS" in out
        assert "WARN" in out and "verdict=self_satisfying" in out
