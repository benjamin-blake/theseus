"""Mirror test for scripts/checks/decisions/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib

import pytest

from scripts.checks import registry
from scripts.checks.decisions import _manifest


class TestDecisionsManifest:
    """Every decisions Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.decisions.")

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


# Membership FLOOR, not an exhaustive roster (tests/CLAUDE.md count-coupling rules): naming the
# checks this domain must not silently lose keeps the parametrized tests above honest -- they
# assert properties of whatever ENTRIES happens to contain, so an accidentally-dropped Entry
# would leave them green with nothing to iterate over. A NEW check may be added freely without
# touching this list; removing one named here must be a deliberate edit.
_REQUIRED_ENTRY_NAMES = frozenset(
    {
        "validate_decisions_size",
        "validate_decisions_index_freshness",
        "validate_decision_entry_conformance",
        "validate_supersession_annotations",
        "validate_decision_currency",
    }
)


class TestRequiredEntryMembership:
    def test_every_required_check_is_registered_in_this_manifest(self) -> None:
        present = {entry.name for entry in _manifest.ENTRIES}
        assert _REQUIRED_ENTRY_NAMES <= present, f"missing from ENTRIES: {sorted(_REQUIRED_ENTRY_NAMES - present)}"

    def test_entry_conformance_runs_in_both_tiers(self) -> None:
        """Corpus conformance is a both-tier gate: a --pre-only registration would let a
        nonconforming edit reach main through any path that skips the fast tier."""
        entry = next(e for e in _manifest.ENTRIES if e.name == "validate_decision_entry_conformance")
        assert entry.pre is True
        assert entry.full_segment == "full_after_lint"

    def test_entry_conformance_pre_globs_cover_both_corpus_files(self) -> None:
        entry = next(e for e in _manifest.ENTRIES if e.name == "validate_decision_entry_conformance")
        assert set(entry.pre_globs) == {"docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md"}
