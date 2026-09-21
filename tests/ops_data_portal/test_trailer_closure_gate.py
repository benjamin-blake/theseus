"""Mirror home for scripts/ops_portal/trailer_closure_gate.py (rec-3775, PLAN-trailer-closure-
evidence-gate). Decision 131 point 1 returns None for scripts/ops_portal/** on both mapping
rules, so there is no mirror obligation here and no mirror-derived path -- this is where
closure_gate and the ci_rca lifecycle modules are already tested (Decision 124 preserved).

Covers merge_leg_refuses over a plan-only set (refuses), a mixed set (proceeds), a code-only set
(proceeds), and the empty / None sets (refuse, fail-closed).
"""

from __future__ import annotations

from scripts.ops_portal.trailer_closure_gate import merge_leg_refuses


class TestMergeLegRefuses:
    def test_none_refuses(self) -> None:
        assert merge_leg_refuses(None) is True

    def test_empty_set_refuses(self) -> None:
        """A true (non-squash) merge commit's `git diff-tree -r` lists nothing -- an empty set
        must refuse, or the fail-open case this gate exists to close would be reinstated."""
        assert merge_leg_refuses(set()) is True

    def test_plan_only_set_refuses(self) -> None:
        assert merge_leg_refuses({"docs/plans/PLAN-example.yaml"}) is True

    def test_plan_only_multiple_files_refuses(self) -> None:
        assert merge_leg_refuses({"docs/plans/PLAN-example.yaml", "docs/plans/PLAN-other.yaml"}) is True

    def test_code_only_set_proceeds(self) -> None:
        assert merge_leg_refuses({"scripts/rec_trailer.py"}) is False

    def test_mixed_set_proceeds(self) -> None:
        """A merge carrying code AND a plan document proceeds -- ANY non-plan path in the changed
        set is sufficient; the refusal is only for a diff confined ENTIRELY to docs/plans/."""
        assert merge_leg_refuses({"docs/plans/PLAN-example.yaml", "scripts/rec_trailer.py"}) is False

    def test_docs_plans_prefix_is_not_a_substring_match(self) -> None:
        """A path merely CONTAINING 'docs/plans' but not rooted there (e.g. a file under a
        differently-named sibling directory) must not be treated as plan-only."""
        assert merge_leg_refuses({"other/docs/plans/PLAN-example.yaml"}) is False
