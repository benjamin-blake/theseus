"""Mirror test for scripts/checks/verification/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib

import pytest

from scripts.checks import registry
from scripts.checks.verification import _manifest


class TestVerificationManifest:
    """Every verification Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.verification.")

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

    def test_handoff_full_tier_covers_the_plan_document_schema(self) -> None:
        assert {"scripts/roadmap/**", "scripts/checks/verification/**"} <= self._globs("validate_handoff_full_tier")

    def test_verification_registry_is_gated_on_its_full_closure(self) -> None:
        """Reads the entries/ shards and the retired flat file under
        config/agent/verification_registry/, the loader/differential engine in
        scripts/verification_graduation.py, CANONICAL_SLOTS in scripts/verification_checks.py, and
        _common/_scaffolding helpers."""
        assert {
            "config/agent/verification_registry/**",
            "scripts/verification_graduation.py",
            "scripts/verification_checks.py",
            "scripts/checks/verification/**",
            "scripts/checks/_common.py",
            "scripts/checks/_scaffolding.py",
        } <= self._globs("validate_verification_registry")
