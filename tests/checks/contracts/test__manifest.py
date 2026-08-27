"""Mirror test for scripts/checks/contracts/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib
from fnmatch import fnmatch

import pytest

from scripts.checks import registry
from scripts.checks.contracts import _manifest


class TestContractsManifest:
    """Every contracts Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.contracts.")

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_resolves_to_a_callable_named_its_own_attr(self, entry) -> None:
        module = importlib.import_module(entry.module)
        fn = getattr(module, entry.attr)
        assert callable(fn)
        assert fn.__name__ == entry.attr

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_registry_resolve_matches_the_manifest_entry(self, entry) -> None:
        module = importlib.import_module(entry.module)
        assert registry.resolve(entry.name) is getattr(module, entry.attr)


# One row per promoted gated Entry: repo-relative paths in that check's read set (transitive
# first-party import closure plus every data/config path the body opens).
_CLOSURE_INPUTS: dict[str, tuple[str, ...]] = {
    # One Path.exists() on the Decision 38 ghost file: creating it is necessarily a .github/ diff.
    "validate_no_underscore_instructions": (
        ".github/copilot_instructions.md",
        "scripts/checks/contracts/validate_no_underscore_instructions.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # Reads root CLAUDE.md only -- AGENTS.md is the pointer TARGET, never opened by this check.
    "validate_claude_md_pointer_invariant": (
        "CLAUDE.md",
        "scripts/checks/contracts/validate_claude_md_pointer_invariant.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # The invariant-source globs come from the contract's behavioural_invariant_sources key, so
    # the contract is an input alongside the SKILL.md files it currently resolves to.
    "validate_prompt_compliance": (
        ".claude/skills/planning/SKILL.md",
        "docs/contracts/instruction-architecture.yaml",
        "scripts/prompt_compliance.py",
        "logs/.retro-lite-log.jsonl",
        "logs/.execution-state.json",
        "scripts/checks/contracts/_shared.py",
        "scripts/checks/contracts/validate_prompt_compliance.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # Every layer's content_locations must resolve, so the union of today's declared locations is
    # part of the read set -- a DELETION inside one of them is exactly what this check catches,
    # and such a diff names no other closure member.
    "validate_instruction_architecture_layers": (
        "docs/contracts/instruction-architecture.yaml",
        "scripts/prompt_compliance.py",
        "CLAUDE.md",
        "scripts/CLAUDE.md",
        "AGENTS.md",
        "docs/PROJECT_CONTEXT.md",
        ".claude/commands/plan.md",
        ".claude/skills/planning/SKILL.md",
        "config/agent/executor/prompts/implement.prompt.md",
        "config/agent/executor/instructions/python.instructions.md",
        "scripts/checks/contracts/_shared.py",
        "scripts/checks/contracts/validate_instruction_architecture_layers.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
}


class TestPromotedGateClosures:
    """Each promoted check's read-set member is asserted MATCHED by its patterns, not present in
    them as a literal.

    Bare fnmatch, not scripts.validate._pre_glob_match, for the reason
    tests/checks/decisions/test__manifest.py::TestClosureMembersAreCovered states: the production
    matcher is fnmatch PLUS a leading-'**/' retry that can only ADD matches. That retry is why
    "scripts/CLAUDE.md" is asserted here but repo-root "CLAUDE.md" is carried as its own literal
    glob -- bare "**/CLAUDE.md" never matches a root-level file.
    """

    @staticmethod
    def _covered(name: str, path: str) -> bool:
        globs = next(e for e in _manifest.ENTRIES if e.name == name).pre_globs or ()
        return any(fnmatch(path, glob) for glob in globs)

    @pytest.mark.parametrize(
        ("name", "path"),
        [(name, path) for name, paths in _CLOSURE_INPUTS.items() for path in paths],
        ids=[f"{name}-{path}" for name, paths in _CLOSURE_INPUTS.items() for path in paths],
    )
    def test_a_diff_touching_only_this_closure_member_still_matches_the_gate(self, name: str, path: str) -> None:
        assert self._covered(name, path)

    @pytest.mark.parametrize("name", sorted(_CLOSURE_INPUTS))
    def test_an_unrelated_path_is_not_matched(self, name: str) -> None:
        """Anti-vacuity: the rows above would also pass against a catch-all pattern."""
        assert not self._covered(name, "terraform/personal/main.tf")


class TestPortalDriftPromotedUngated:
    """Promoted into --pre WITHOUT globs, deliberately. Every answer_loci path it resolves comes
    OUT of EVALUATION-PROMPTS.yaml at run time and may name any path in the repo, so no static
    glob encloses the read set: gating on the three portal files would silently skip the
    deleted-locus case (Decision 101 public-content boundary) this gate exists to catch."""

    def test_is_dispatched_in_pre(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        assert "validate_portal_drift" in pre_names

    def test_declares_no_pre_globs(self) -> None:
        entry = next(e for e in _manifest.ENTRIES if e.name == "validate_portal_drift")
        assert entry.pre_globs is None
