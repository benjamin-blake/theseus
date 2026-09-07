"""Mirror home for scripts/ops_portal/closure_gate.py (Decision 184, PLAN-escape-closure-obligation).

Exercises the gate body directly: the escape-classified predicate over existing UNION merged
context, the four `<kind>:<ref>` artifact kinds resolving present/absent, the FIX-BOUND leg (a
resolvable artifact whose defining file is untouched by the fix commit is refused), check:'s
TIER-fact requirement (never bare registry membership), the fixture: tests/fixtures/ root
constraint, the waiver grammar as CATEGORY MEMBERSHIP, and the contract-parity assertion that this
module's vocabularies equal docs/contracts/ci-rca-lifecycle.yaml::closure_obligation's.
"""

from __future__ import annotations

import yaml

from scripts.ops_portal._common import ROOT
from scripts.ops_portal.closure_gate import (
    ARTIFACT_KINDS,
    KIND_STRENGTH,
    WAIVER_CATEGORIES,
    _fixture_kind_fact,
    is_escape_classified,
    is_valid_waiver,
    resolve_closure_artifact,
)


def _head() -> str:
    from scripts.ops_portal.ci_rca_lifecycle import current_commit_sha

    sha = current_commit_sha()
    assert sha, "git rev-parse HEAD must resolve inside the test environment"
    return sha


class TestIsEscapeClassified:
    def test_escape_class_set(self) -> None:
        assert is_escape_classified({"escape_class": "no-edge"}) is True

    def test_detection_gap_escape_mode_undetermined_counts_as_set(self) -> None:
        assert is_escape_classified({"detection_gap": {"escape_mode": "undetermined"}}) is True

    def test_neither_set_is_false(self) -> None:
        assert is_escape_classified({}) is False
        assert is_escape_classified({"detection_gap": {}}) is False


class TestArtifactResolution:
    def test_named_artifact_absent_on_main_is_refused(self) -> None:
        """The known-bad fixture: a named artifact that does not exist on main never resolves,
        regardless of a well-formed fix sha."""
        assert resolve_closure_artifact("shard:this-shard-id-does-not-exist-on-main", _head()) is False

    def test_check_kind_requires_pre_tier_not_membership(self) -> None:
        """check:<name> resolves against Entry.pre, never bare _ALL_ENTRIES membership -- a
        registered entry with pre=False does not discharge the obligation. Without this the gate
        is vacuous for the 50/92 tier_misplaced escapes, whose catching check is already
        registered before any fix lands."""
        from scripts.checks import registry

        assert "validate_requirements" in registry._ALL_ENTRIES
        assert registry._ALL_ENTRIES["validate_requirements"].pre is False
        assert resolve_closure_artifact("check:validate_requirements", _head()) is False

        # A pre=True entry is a DIFFERENT refusal reason (the fix-bound leg, tested separately) --
        # this asserts the tier fact itself is real, not merely that the whole path is inert.
        assert "validate_workflow_agent_safety" in registry._ALL_ENTRIES
        assert registry._ALL_ENTRIES["validate_workflow_agent_safety"].pre is True

    def test_artifact_not_touched_by_fix_commit_is_refused(self) -> None:
        """A resolvable artifact (kind-fact holds) whose defining file was NOT touched by the
        named fix commit is refused; an unresolvable sha refuses too (fail closed, Decision 55)."""
        # kind-fact holds (the shard file exists), but HEAD never touched it.
        assert resolve_closure_artifact("shard:acceptance-literal-lint-guard", _head()) is False
        # an unresolvable / garbage sha refuses regardless of kind-fact.
        assert resolve_closure_artifact("shard:acceptance-literal-lint-guard", "0" * 40) is False
        # no fix sha at all on the artifact route is refused.
        assert resolve_closure_artifact("shard:acceptance-literal-lint-guard", None) is False
        assert resolve_closure_artifact("shard:acceptance-literal-lint-guard", "") is False

    def test_fixture_kind_requires_tests_fixtures_root(self) -> None:
        """fixture:<path> must name a path under tests/fixtures/; fixture:README.md resolves as
        a path on disk but does not discharge the obligation -- unconstrained, it would DEPRESS
        the Decision 184 reversal-condition (a) waiver rate by counting on the artifact side for
        free."""
        assert (ROOT / "README.md").is_file()
        holds, defining = _fixture_kind_fact("README.md", ROOT)
        assert holds is False
        assert defining == []

        holds, defining = _fixture_kind_fact("tests/fixtures/__init__.py", ROOT)
        assert holds is True
        assert defining == ["tests/fixtures/__init__.py"]

        assert resolve_closure_artifact("fixture:README.md", "0" * 40) is False

    def test_bare_rec_id_never_resolves(self) -> None:
        """A bare 'rec-NNN' token is not `<kind>:<ref>`-shaped and simply fails to parse -- the
        gate never dereferences a rec id, so no rec-to-rec pointer is even expressible."""
        assert resolve_closure_artifact("rec-3132", _head()) is False


class TestWaiverGrammar:
    def test_unknown_waiver_category_is_refused(self) -> None:
        """Membership, not shape, is the acceptance bar -- a well-shaped but off-vocabulary
        category is refused, or Decision 184 point 8's ratchet is defeatable by typing a new
        category into a string."""
        assert is_valid_waiver("made_up_category_nobody_ratified", "a perfectly good reason string") is False

    def test_duplicate_of_is_not_a_waiver_category(self) -> None:
        """HUMAN RULING, BINDING: duplicate_of is excluded from WAIVER_CATEGORIES entirely -- a
        duplicate asserts an artifact is OWED, never that one is infeasible."""
        assert "duplicate_of" not in WAIVER_CATEGORIES
        assert is_valid_waiver("duplicate_of", "master rec carries the fix") is False

    def test_empty_reason_is_refused(self) -> None:
        assert is_valid_waiver("environment_only", "") is False
        assert is_valid_waiver("environment_only", "   ") is False

    def test_well_formed_waiver_is_valid(self) -> None:
        assert is_valid_waiver("stale_no_recurrence", "last_seen=2026-01-01, created=2025-12-01") is True

    def test_waiver_vocabulary_is_the_ratified_seed_set(self) -> None:
        """WAIVER_CATEGORIES is EXACTLY the four-member ratified seed set -- an exact-set
        assertion, not a superset check, so a fifth category cannot be added without failing this
        test (Decision 184 point 8: adding a category is a numbered-Decision event)."""
        assert WAIVER_CATEGORIES == frozenset(
            {"stale_no_recurrence", "environment_only", "no_premerge_gate_by_design", "risk_accepted"}
        )


class TestContractParity:
    def test_closure_vocabularies_match_contract(self) -> None:
        """The kind, kind-strength and category vocabularies in closure_gate.py equal those
        declared in docs/contracts/ci-rca-lifecycle.yaml::closure_obligation -- contract-code
        drift fails rather than silently diverging."""
        contract = yaml.safe_load((ROOT / "docs" / "contracts" / "ci-rca-lifecycle.yaml").read_text(encoding="utf-8"))
        obligation = contract["closure_obligation"]

        assert set(obligation["artifact_kinds"]) == ARTIFACT_KINDS
        assert list(obligation["kind_strength"]) == list(KIND_STRENGTH)
        assert set(obligation["waiver_categories"]) == WAIVER_CATEGORIES
        assert "duplicate_of" not in obligation["waiver_categories"]
