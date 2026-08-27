"""Mirror test for scripts/checks/deps/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib

import pytest

from scripts.checks import registry
from scripts.checks._schema import Entry
from scripts.checks.deps import _manifest


class TestDepsManifest:
    """Every deps Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.deps.")

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


class TestGatedEntryInputClosures:
    """A gated check's pre_globs must cover EVERY path its implementation reads. Under-inclusion
    is a recall bug: a diff that touches an uncovered input silently skips the check in --pre."""

    @staticmethod
    def _globs(name: str) -> set[str]:
        return set(next(e for e in _manifest.ENTRIES if e.name == name).pre_globs or ())

    def test_check_manifests_is_gated_on_its_full_closure(self) -> None:
        """AST-scans scripts/checks/*/_manifest.py, compares SEGMENT_TOKENS against
        docs/contracts/check-manifest.yaml, and resolves every declared module through
        scripts.dependency_graph.build_graph."""
        assert {
            "scripts/checks/**",
            "docs/contracts/check-manifest.yaml",
            "scripts/dependency_graph.py",
        } <= self._globs("validate_check_manifests")

    def test_pre_glob_closure_is_gated_on_its_own_closure(self) -> None:
        """Dogfood: the closure auditor audits its own Entry, so its globs must cover its own
        transitive first-party import closure -- the manifest roster it reads through the
        registry, the graph oracle it traverses, and the two hub modules those pull in
        (scripts.lambda_manifest via _gather_roots, scripts.roadmap.plan_document via
        scripts.checks._common's function-scope import)."""
        assert {
            "scripts/checks/**",
            "scripts/checks/*/_manifest.py",
            "scripts/dependency_graph.py",
            "scripts/extract_imports.py",
            "scripts/lambda_manifest.py",
            "scripts/roadmap/plan_document.py",
        } <= self._globs("validate_pre_glob_closure")


class TestPreGlobClosureEntry:
    """The closure auditor's tier membership (D2-3 wave 4a)."""

    @staticmethod
    def _entry() -> Entry:
        return next(e for e in _manifest.ENTRIES if e.name == "validate_pre_glob_closure")

    def test_is_in_the_pre_tier_and_gated(self) -> None:
        entry = self._entry()
        assert entry.pre is True
        assert entry.pre_globs

    def test_uses_the_domain_full_segment_convention(self) -> None:
        """Every pre=True deps Entry declares full_after_lint -- derived from the domain's own
        roster, not restated as a literal."""
        siblings = {e.full_segment for e in _manifest.ENTRIES if e.pre and e.name != "validate_pre_glob_closure"}
        assert self._entry().full_segment in siblings
        assert len(siblings) == 1
