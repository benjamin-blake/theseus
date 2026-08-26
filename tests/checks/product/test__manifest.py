"""Mirror test for scripts/checks/product/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib
from fnmatch import fnmatch

import pytest

from scripts.checks import registry
from scripts.checks.product import _manifest


class TestProductManifest:
    """Every product Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.product.")

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


class TestPromotedGateClosures:
    """`product` had ZERO --pre membership before validate_broker_env_reads was promoted, so the
    domain also had to be declared in registry._PRE_DOMAIN_ORDER (pinned in
    tests/checks/registry/test_sequences.py). owner="trading" is consumer metadata and does
    not affect dispatch -- pre_sequence() keys on Step.name only.

    The RESOLVE-BY-KEY-ONLY scan covers scripts/ and src/; the self-exclusion set and the ALPACA_
    patterns live in the check's own module, itself under scripts/.
    """

    _CLOSURE_INPUTS: tuple[str, ...] = (
        "scripts/broker_secrets.py",
        "src/data/handlers/fetch_handler.py",
        "scripts/checks/product/trading/validate_broker_env_reads.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    )

    @staticmethod
    def _covered(path: str) -> bool:
        globs = next(e for e in _manifest.ENTRIES if e.name == "validate_broker_env_reads").pre_globs or ()
        return any(fnmatch(path, glob) for glob in globs)

    @pytest.mark.parametrize("path", _CLOSURE_INPUTS)
    def test_a_diff_touching_only_this_closure_member_still_matches_the_gate(self, path: str) -> None:
        assert self._covered(path)

    def test_an_unrelated_path_is_not_matched(self) -> None:
        """Anti-vacuity: the rows above would also pass against a catch-all pattern."""
        assert not self._covered("README.md")
