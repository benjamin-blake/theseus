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

PLAN-verifier-weakening-guards (LSA-01 leg a, Decision 187) retires the four same-PR-editable
roster constants the promotion wave above left behind (a 22-name gated-check roster, a 2-name
ungated-check roster, a 2-name newly-promoted-domain roster, and a 3-name pre-only-check roster,
named in the plan and in git history, deliberately not respelled here) -- see TestDerivedGateShape
and TestOD5's own docstrings for the five-property disposition. NO ROSTER REPLACES THEM: the
protected set (which entries may
not be demoted without a marker) is derived from the git base ref by
scripts/checks/verification/validate_tier_demotion_markers.py at check time, and TestWeakeningGateFixedPoint
below pins the fixed point that makes deleting or demoting THAT gate itself impossible to do
silently -- a hand-written name list here would just be a sixth roster in a file about retiring
the first five.
"""

from __future__ import annotations

import dataclasses
import importlib
from fnmatch import fnmatch
from unittest.mock import patch

import pytest

import scripts.checks.registry as registry

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
    """test_pre_only_checks_stay_pre_only (the retired 3-name pre-only-check roster's
    parameterized leg) is RETIRED with the roster it read -- its `name not in full_names`
    property is LOST, routed to rec-3728 (Decision 187 scope row 11 property (iv)): that
    direction is a TIGHTENING guard (a pre-only check gaining a full_segment is never gated by
    this plan's own direction rule), so the gate that enforces direction cannot itself own it.
    test_terraform_try_stays_unsequenced is untouched -- _UNSEQUENCED_CHECKS is a different
    constant, not one of the four retired."""

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


def _pre_steps() -> dict[str, registry.Step]:
    return {step.name: step for step in registry.pre_sequence() if step.kind == "check"}


class TestDerivedGateShape:
    """Decision 187 (LSA-01 leg a) retires the 22-name gated-check roster, the 2-name
    ungated-check roster and the 2-name newly-promoted-domain roster along with the 3-name
    pre-only-check roster (see TestOD5's docstring) -- four same-PR-editable rosters that pinned
    27 check names + 2 domains, replaced by NOTHING (the protected set is derived from the git
    base ref by validate_tier_demotion_markers, never re-enumerated here). FIVE-PROPERTY
    DISPOSITION, none assumed: this class RE-POINTS two surviving properties at the FULL derived
    population (i, ii below) and RETAINS one VERBATIM (iii); properties (iv) and (v) are LOST --
    both are TIGHTENINGS the new gate's own direction rule declares free, so the gate that
    enforces direction cannot itself own them -- and are routed to rec-3728 rather than silently
    dropped."""

    def test_every_gated_pre_entry_covers_its_own_defining_module(self) -> None:
        """(i) RE-POINTED: every gated pre entry's globs must match its own defining module, now
        over the full derived population (51 entries at head) rather than the retired 22-name
        gated-check roster -- this is what surfaces the two scope-row-5/6 misses
        (validate_no_cross_test_imports, validate_terraform_tag_charset). RED before those two
        widenings land, GREEN after: the first live demonstration that the direction rule this
        plan installs points the right way (a glob WIDENING is a tightening, and free).

        Bare fnmatch, not scripts.validate._pre_glob_match, for the reason tests/checks/
        ops_governance/test__manifest.py::TestClosureMembersAreCovered states: an import edge from
        tests/checks/** into the driver widens the affected-test graph. Sound in the safe
        direction -- the production matcher is fnmatch PLUS a leading-'**/' retry that can only
        ADD matches, so anything green here is green there too.
        """
        misses = []
        for name, step in _pre_steps().items():
            if step.pre_globs is None:
                continue
            entry = registry._ALL_ENTRIES[name]
            own_path = entry.module.replace(".", "/") + ".py"
            if not any(fnmatch(own_path, glob) for glob in step.pre_globs):
                misses.append(name)
        assert not misses, f"{len(misses)} gated pre entries do not cover their own defining module: {misses}"

    def test_every_domain_contributing_a_pre_entry_is_declared_in_pre_domain_order(self) -> None:
        """(ii) RE-POINTED: a domain contributing a pre entry must be declared in
        _PRE_DOMAIN_ORDER, now over every domain rather than the retired 2-name
        newly-promoted-domain roster. Does NOT catch a domain declared-but-NOT-contributing
        (e.g. `product`, OBSERVED stale at
        plan time but not fixed here, Decision 59) -- that is declaration-implies-contribution's
        converse, a different direction this property does not claim."""
        by_domain = registry._entries_by_domain()
        contributing = {entry.module.split(".")[2] for entries in by_domain.values() for entry in entries if entry.pre}
        assert contributing <= set(registry._PRE_DOMAIN_ORDER)

    def test_pre_domain_order_has_no_duplicates(self) -> None:
        """(iii) RETAINED VERBATIM from the retired TestNewlyPreDomainsAreDeclared: passes
        unchanged before and after this plan -- guards future duplicate appends, not this wave's."""
        assert len(registry._PRE_DOMAIN_ORDER) == len(set(registry._PRE_DOMAIN_ORDER))


class TestWeakeningGateFixedPoint:
    """VP step 3: the self-reference hole Decision 187's design named as its sharpest structural
    finding -- without this, the PR that demotes the check-fleet tier-demotion gate is the PR
    under which the gate does not run."""

    def test_live_gate_entry_is_present_and_ungated_in_pre_sequence(self) -> None:
        steps = _pre_steps()
        assert registry._WEAKENING_GATE in steps
        assert steps[registry._WEAKENING_GATE].pre_globs is None

    def test_pre_sequence_raises_when_gate_entry_is_absent(self) -> None:
        patched = dict(registry._ALL_ENTRIES)
        del patched[registry._WEAKENING_GATE]
        with patch.object(registry, "_ALL_ENTRIES", patched), pytest.raises(registry.WeakeningGateError):
            registry.pre_sequence()

    def test_full_sequence_raises_when_gate_entry_is_absent(self) -> None:
        patched = dict(registry._ALL_ENTRIES)
        del patched[registry._WEAKENING_GATE]
        with patch.object(registry, "_ALL_ENTRIES", patched), pytest.raises(registry.WeakeningGateError):
            registry.full_sequence()

    def test_pre_sequence_raises_when_gate_entry_is_glob_gated(self) -> None:
        patched = dict(registry._ALL_ENTRIES)
        original = patched[registry._WEAKENING_GATE]
        patched[registry._WEAKENING_GATE] = dataclasses.replace(original, pre_globs=("scripts/checks/verification/**",))
        with patch.object(registry, "_ALL_ENTRIES", patched), pytest.raises(registry.WeakeningGateError):
            registry.pre_sequence()

    def test_weakening_gate_constant_resolves_to_the_token_owning_module_callable(self) -> None:
        """The carrier-constant pin (scope row 4 / VP step 3): registry._WEAKENING_GATE's VALUE
        is checked against whichever module owns a constant equal to the "tier-demotion-approved"
        token string -- DERIVED from the token's own value, never compared to a spelled-out
        check-name literal. Without this pin, a PR could re-point _WEAKENING_GATE at any other
        ungated pre entry AND delete the gate's own Entry in the same diff, and the two
        raise-based tests above -- which only see a present, ungated Step under whatever name the
        constant currently holds -- would not catch it."""
        owners = []
        for name, entry in registry._ALL_ENTRIES.items():
            module = importlib.import_module(entry.module)
            if any(value == "tier-demotion-approved" for value in vars(module).values() if isinstance(value, str)):
                owners.append(getattr(module, entry.attr))
        assert len(owners) == 1, owners
        assert registry.resolve(registry._WEAKENING_GATE) is owners[0]
