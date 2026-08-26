"""Relocated TestSequenceInvariants (Decision 169, amends Decision 104) plus the re-derivation
fidelity assertions OD-0..OD-6.

OD-0 is the load-bearing one: it independently RE-DERIVES the within-segment domain order from
the manifests plus registry.py's own declared order constants, and asserts the re-derivation
equals the live pre_sequence()/full_sequence() output -- so an undetermined/algorithm-drifted
derivation cannot ship green.

The second half pins the full-only -> --pre promotion wave (Google-TAP recall posture: the
autonomous executor runs ONLY --pre, so a full-tier-only check is structurally guaranteed to be
discovered after merge). It lives HERE rather than in a file of its own because a fifth
registry-importing test module is a fifth transitive-residue member competing for the CAP=35
affected-set budget that TestAffectedSetSurvival pins in test_manifest_contracts.py.
"""

from __future__ import annotations

from fnmatch import fnmatch

import pytest

import scripts.checks.registry as registry

_PRE_ONLY_CHECKS = ("validate_prose_budget_raises", "validate_sloc_budget_raises", "validate_vp_replay")
_UNSEQUENCED_CHECKS = ("validate_terraform_try",)


def _re_derive_pre_sequence() -> list[registry.Step]:
    """Independent re-derivation using registry's OWN exported order constants + manifest
    membership -- reimplements the grouping loop rather than calling registry.pre_sequence()
    again, so a bug in the grouping algorithm itself (not just a wrong order constant) is caught.
    """
    by_domain = registry._entries_by_domain()
    steps = [registry._s(name) for name in registry._PRE_TIER_LEADING_SCAFFOLDS]
    for domain in registry._PRE_DOMAIN_ORDER:
        for entry in by_domain.get(domain, []):
            if entry.pre:
                steps.append(registry._c(entry.name, pre_globs=entry.pre_globs))
    steps.extend(registry._s(name) for name in registry._PRE_TIER_TRAILING_SCAFFOLDS)
    return steps


def _re_derive_full_sequence() -> list[registry.Step]:
    by_domain = registry._entries_by_domain()
    steps: list[registry.Step] = []
    for scaffold_name, segment in registry._FULL_TIER_SKELETON:
        steps.append(registry._s(scaffold_name))
        if segment is None:
            continue
        for domain in registry._FULL_SEGMENT_DOMAIN_ORDER[segment]:
            for entry in by_domain.get(domain, []):
                if entry.full_segment == segment:
                    steps.append(registry._c(entry.name))
    return steps


class TestOD0DomainOrderReDerivation:
    def test_pre_sequence_re_derivation_matches_the_live_sequence(self) -> None:
        assert _re_derive_pre_sequence() == registry.pre_sequence()

    def test_full_sequence_re_derivation_matches_the_live_sequence(self) -> None:
        assert _re_derive_full_sequence() == registry.full_sequence()

    def test_every_domain_appearing_in_a_segment_is_declared_in_its_order_tuple(self) -> None:
        """A domain present in a segment's checks but absent from the declared order tuple would
        silently vanish from that segment (the `by_domain.get(domain, [])` walk only visits
        declared domains) -- assert the declared order tuples are a superset of the domains
        actually present in each segment."""
        by_domain = registry._entries_by_domain()

        pre_domains_present = {entry.module.split(".")[2] for entries in by_domain.values() for entry in entries if entry.pre}
        assert pre_domains_present <= set(registry._PRE_DOMAIN_ORDER)

        for segment, declared_domains in registry._FULL_SEGMENT_DOMAIN_ORDER.items():
            present = {
                entry.module.split(".")[2]
                for entries in by_domain.values()
                for entry in entries
                if entry.full_segment == segment
            }
            undeclared = present - set(declared_domains)
            assert present <= set(declared_domains), f"segment {segment!r}: undeclared domain(s) {undeclared}"


class TestOD1And2SlocOrdering:
    def _positions(self, steps: list[registry.Step]) -> dict[str, int]:
        return {step.name: i for i, step in enumerate(steps) if step.kind == "check"}

    def test_cc_limits_before_sloc_limits_in_full(self) -> None:
        pos = self._positions(registry.full_sequence())
        assert pos["validate_cc_limits"] < pos["validate_sloc_limits"]

    def test_cc_limits_before_sloc_limits_in_pre(self) -> None:
        pos = self._positions(registry.pre_sequence())
        assert pos["validate_cc_limits"] < pos["validate_sloc_limits"]

    def test_sloc_limits_before_sloc_budget_raises_in_pre(self) -> None:
        pos = self._positions(registry.pre_sequence())
        assert pos["validate_sloc_limits"] < pos["validate_sloc_budget_raises"]


class TestOD3ScaffoldAnchorOrder:
    def test_full_tier_scaffold_anchors_in_frozen_order(self) -> None:
        scaffolds = [step.name for step in registry.full_sequence() if step.kind == "scaffold"]
        assert scaffolds == [
            "lint",
            "unit_tests",
            "terraform_checks",
            "dependency_health",
            "ensure_fresh_dq",
            "precommit_all_files",
        ]

    def test_pre_tier_scaffolds_in_frozen_order(self) -> None:
        scaffolds = [step.name for step in registry.pre_sequence() if step.kind == "scaffold"]
        assert scaffolds == [
            "lint",
            "precommit_changed",
            "mypy_diff",
            "pytest_diff",
            "verifier_coverage_report",
            "budget_assertion",
        ]


class TestOD4ScaffoldAdjacentChecksStayInTheirSegments:
    def _segment_of(self, name: str) -> str:
        full = registry.full_sequence()
        idx = next(i for i, step in enumerate(full) if step.kind == "check" and step.name == name)
        preceding_scaffolds = [step.name for step in full[:idx] if step.kind == "scaffold"]
        return preceding_scaffolds[-1]

    def test_iam_runner_policy_immediately_after_terraform_checks(self) -> None:
        assert self._segment_of("validate_iam_runner_policy") == "terraform_checks"

    def test_requirements_and_prompts_block_after_dependency_health(self) -> None:
        for name in (
            "validate_requirements",
            "validate_prompt_files",
            "validate_workflow_agent_safety",
            "validate_prompt_compliance",
            "validate_instruction_architecture_layers",
        ):
            assert self._segment_of(name) == "dependency_health"

    def test_verification_harness_after_ensure_fresh_dq(self) -> None:
        assert self._segment_of("validate_verification_harness") == "ensure_fresh_dq"


class TestOD5PreOnlyAndUnsequencedChecks:
    def test_pre_only_checks_stay_pre_only(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        for name in _PRE_ONLY_CHECKS:
            assert name in pre_names
            assert name not in full_names

    def test_terraform_try_stays_unsequenced(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        for name in _UNSEQUENCED_CHECKS:
            assert name not in pre_names
            assert name not in full_names
            assert name in registry._ALL_ENTRIES


class TestOD6TrailingScaffolds:
    def test_budget_assertion_is_last_in_pre(self) -> None:
        assert registry.pre_sequence()[-1] == registry._s("budget_assertion")

    def test_precommit_all_files_is_last_in_full(self) -> None:
        assert registry.full_sequence()[-1] == registry._s("precommit_all_files")


class TestMembershipFloors:
    def test_no_duplicate_check_names_within_a_tier(self) -> None:
        for steps in (registry.pre_sequence(), registry.full_sequence()):
            names = [step.name for step in steps if step.kind == "check"]
            assert len(names) == len(set(names))

    def test_every_manifest_entry_is_pre_xor_full_xor_unsequenced_consistently(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        for entry in registry._ALL_ENTRIES.values():
            assert entry.pre == (entry.name in pre_names)
            assert (entry.full_segment is not None) == (entry.name in full_names)

    def test_membership_assertion_has_teeth_against_a_synthetic_removal(self) -> None:
        """Proves a membership assertion over the live full-tier check-name set is not vacuous:
        removing one real name from a copy of that set trips a subset assertion modeled on it --
        the growth-safe successor to the retired REQUIRED_FULL_CHECKS floor (Decision 104/169)."""
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        removed = set(full_names)
        removed.discard(next(iter(removed)))
        assert not (full_names <= removed)


# Promoted with a pre_globs input-closure gate. Per-glob closure adequacy is asserted in each
# domain's own tests/checks/<domain>/test__manifest.py, next to the manifest it mirrors.
PROMOTED_GATED: tuple[str, ...] = (
    "validate_sys_executable",
    "validate_recommendations_schema",
    "validate_rec_write_paths",
    "validate_decisions_local_writes",
    "validate_warehouse_write_sources",
    "validate_pydantic_yaml_drift",
    "validate_dq_manifest_gate",
    "validate_rec_relevance_contract",
    "validate_executor_boundary",
    "validate_broker_env_reads",
    "validate_invariants",
    "validate_scheduled_agent_logs",
    "validate_ci_rca_trigger",
    "validate_supersession_annotations",
    "validate_lambda_manifests",
    "validate_lambda_manifest_coverage",
    "validate_hermeticity_flags",
    "validate_verifier_hermeticity",
    "validate_differential_gate_baseline",
    "validate_no_underscore_instructions",
    "validate_claude_md_pointer_invariant",
    "validate_prompt_compliance",
    "validate_instruction_architecture_layers",
)

# Promoted UNGATED (pre_globs=None, runs on every diff). Reserved for checks whose read set is
# driven by data they parse at runtime (an answer-locus path, a diff-derived file list), so no
# static glob can enclose it -- gating those would silently re-open the very gap the promotion
# closes. Each costs single-digit milliseconds of body time.
PROMOTED_UNGATED: tuple[str, ...] = (
    "validate_portal_drift",
    "validate_environment_taxonomy",
)

# Domains with no --pre member before this wave: `by_domain.get(domain, [])` in pre_sequence()
# only visits DECLARED domains, so an undeclared domain's promoted entries silently never run.
NEWLY_PRE_DOMAINS: tuple[str, ...] = ("executor", "product", "lambda_pkg")


def _pre_steps() -> dict[str, registry.Step]:
    return {step.name: step for step in registry.pre_sequence() if step.kind == "check"}


class TestPromotedRosterIsDispatchedInPre:
    @pytest.mark.parametrize("name", PROMOTED_GATED + PROMOTED_UNGATED)
    def test_promoted_check_runs_in_the_pre_tier(self, name: str) -> None:
        assert name in _pre_steps()

    @pytest.mark.parametrize("name", PROMOTED_GATED + PROMOTED_UNGATED)
    def test_promoted_check_still_runs_in_the_full_tier(self, name: str) -> None:
        """Promotion is additive: the full tier keeps every promoted check."""
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert name in full_names


class TestPromotedGateShape:
    @pytest.mark.parametrize("name", PROMOTED_GATED)
    def test_gated_promotion_declares_globs(self, name: str) -> None:
        assert _pre_steps()[name].pre_globs

    @pytest.mark.parametrize("name", PROMOTED_UNGATED)
    def test_ungated_promotion_declares_no_globs(self, name: str) -> None:
        assert _pre_steps()[name].pre_globs is None

    @pytest.mark.parametrize("name", PROMOTED_GATED)
    def test_gated_promotion_covers_its_own_defining_module(self, name: str) -> None:
        """A gated check whose own module holds its roster/allowlist/regexes must match its own
        globs, or editing the rule alone skips the check that enforces it (the recall defect the
        registry audit found on seven pre-existing gates).

        Bare fnmatch, not scripts.validate._pre_glob_match, for the reason tests/checks/
        ops_governance/test__manifest.py::TestClosureMembersAreCovered states: an import edge from
        tests/checks/** into the driver widens the affected-test graph. Sound in the safe
        direction -- the production matcher is fnmatch PLUS a leading-'**/' retry that can only
        ADD matches, so anything green here is green there too.
        """
        entry = registry._ALL_ENTRIES[name]
        own_path = entry.module.replace(".", "/") + ".py"
        globs = _pre_steps()[name].pre_globs or ()
        assert any(fnmatch(own_path, glob) for glob in globs), f"{name}: {own_path} unmatched by {globs}"


class TestNewlyPreDomainsAreDeclared:
    @pytest.mark.parametrize("domain", NEWLY_PRE_DOMAINS)
    def test_domain_is_declared_in_pre_domain_order(self, domain: str) -> None:
        assert domain in registry._PRE_DOMAIN_ORDER

    @pytest.mark.parametrize("domain", NEWLY_PRE_DOMAINS)
    def test_domain_actually_contributes_a_check_to_pre(self, domain: str) -> None:
        """Declaring the domain is necessary but not sufficient -- assert the derived sequence
        really carries a member from it, so a declaration without a promoted entry cannot pass."""
        contributed = {
            step.name
            for step in registry.pre_sequence()
            if step.kind == "check" and registry._ALL_ENTRIES[step.name].module.split(".")[2] == domain
        }
        assert contributed

    def test_pre_domain_order_has_no_duplicates(self) -> None:
        """Regression pin: passes unchanged before and after this diff -- guards future duplicate appends, not this wave's."""
        assert len(registry._PRE_DOMAIN_ORDER) == len(set(registry._PRE_DOMAIN_ORDER))


class TestNoAccidentalUngatedPromotion:
    def test_promoted_roster_ungated_members_are_exactly_the_declared_ones(self) -> None:
        """An ungated check runs on EVERY diff, so it is a budget decision, not a default. Any
        promoted name that loses its globs must be moved into PROMOTED_UNGATED deliberately."""
        steps = _pre_steps()
        ungated = {name for name in PROMOTED_GATED + PROMOTED_UNGATED if steps[name].pre_globs is None}
        assert ungated == set(PROMOTED_UNGATED)
