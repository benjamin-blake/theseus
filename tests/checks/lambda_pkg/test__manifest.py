"""Mirror test for scripts/checks/lambda_pkg/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib
from fnmatch import fnmatch

import pytest

from scripts.checks import registry
from scripts.checks.lambda_pkg import _manifest


class TestLambdaPkgManifest:
    """Every lambda_pkg Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.lambda_pkg.")

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
    """The two manifest-schema checks are promoted into --pre (they parse 7 YAML files through
    scripts/lambda_manifest.py and cost milliseconds); `lambda_pkg` therefore had to be declared
    in registry._PRE_DOMAIN_ORDER (pinned in tests/checks/registry/test_sequences.py)."""

    _PROMOTED: tuple[str, ...] = ("validate_lambda_manifests", "validate_lambda_manifest_coverage")
    _CLOSURE_INPUTS: tuple[str, ...] = (
        "src/lambdas/ducklake_reader/manifest.yaml",
        "scripts/lambda_manifest.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    )

    @staticmethod
    def _covered(name: str, path: str) -> bool:
        globs = next(e for e in _manifest.ENTRIES if e.name == name).pre_globs or ()
        return any(fnmatch(path, glob) for glob in globs)

    @pytest.mark.parametrize("name", _PROMOTED)
    @pytest.mark.parametrize("path", _CLOSURE_INPUTS)
    def test_a_diff_touching_only_this_closure_member_still_matches_the_gate(self, name: str, path: str) -> None:
        assert self._covered(name, path)

    @pytest.mark.parametrize("name", _PROMOTED)
    def test_own_defining_module_is_covered(self, name: str) -> None:
        assert self._covered(name, f"scripts/checks/lambda_pkg/{name}.py")

    @pytest.mark.parametrize("name", _PROMOTED)
    def test_an_unrelated_path_is_not_matched(self, name: str) -> None:
        """Anti-vacuity: the rows above would also pass against a catch-all pattern."""
        assert not self._covered(name, "README.md")


class TestBundleCompletenessStaysFullOnly:
    """validate_lambda_bundle_completeness must NOT follow its siblings into --pre. It import-
    resolves every ACTIVE handler in a staged subprocess, and six data-pipeline handlers import
    pandas/numpy at module scope -- neither is installed by the pr-validate job's
    requirements-fast.txt + requirements-dev.txt surface, so a promoted run would report
    'missing module' for handlers that are fine in the full tier. Env-blocked, not cost-blocked.
    """

    def test_bundle_completeness_is_absent_from_pre(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_lambda_bundle_completeness" in full_names
        assert "validate_lambda_bundle_completeness" not in pre_names

    def test_deploy_gating_is_absent_from_pre(self) -> None:
        """Advisory-only (never appends to `failed` except on import error), so promoting it buys
        reporting, not a pre-merge gate -- and nothing it reports can redden the full tier
        post-merge either, i.e. there is no escape for it to close."""
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        assert "validate_lambda_deploy_gating" not in pre_names
