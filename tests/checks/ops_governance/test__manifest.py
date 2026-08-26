"""Mirror test for scripts/checks/ops_governance/_manifest.py (Decision 169, amends Decision 104)."""

from __future__ import annotations

import importlib
from fnmatch import fnmatch

import pytest

from scripts.checks import registry
from scripts.checks.ops_governance import _manifest


class TestOpsGovernanceManifest:
    """Every ops_governance Entry names a bare-literal module/attr pair resolving to the same-named
    registered check inside this package."""

    def test_entries_is_non_empty(self) -> None:
        assert _manifest.ENTRIES

    def test_no_duplicate_names_within_this_manifest(self) -> None:
        names = [entry.name for entry in _manifest.ENTRIES]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("entry", _manifest.ENTRIES, ids=[entry.name for entry in _manifest.ENTRIES])
    def test_entry_module_is_inside_this_domain_package(self, entry) -> None:
        assert entry.module.startswith("scripts.checks.ops_governance.")

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

    def test_reconcile_pending_gate_covers_its_generator_closure(self) -> None:
        """_ops_table_ids() runs scripts.schema_to_field_semantics.generate(), which resolves $refs
        across the whole docs/contracts/ directory through scripts/contracts.py -- none of which
        the ops_*.yaml-only gate covered."""
        assert {
            "docs/contracts/**",
            "config/lambda/ducklake/field_semantics.static.yaml",
            "src/schemas/**",
            "scripts/schema_to_field_semantics.py",
            "scripts/contracts.py",
            "scripts/checks/ops_governance/**",
        } <= self._globs("validate_reconcile_pending_gate")

    def test_reconcile_pending_gate_covers_the_contract_pydantic_models(self) -> None:
        """The generator chain does not stop at scripts/contracts.py: load_contract validates every
        docs/contracts/ops_*.yaml against the ContractDocument/FieldSpec models in
        scripts/contracts_schema.py, so a new required field or model_validator there reddens this
        check with no other closure member in the diff."""
        assert "scripts/contracts_schema.py" in self._globs("validate_reconcile_pending_gate")


# One row per gated Entry: repo-relative paths in that check's transitive first-party import
# closure (module-scope AND the deferred imports its body always executes).
_CLOSURE_INPUTS: dict[str, tuple[str, ...]] = {
    "validate_reconcile_pending_gate": (
        "config/lambda/ducklake/field_semantics.static.yaml",
        "docs/contracts/ops_recommendations.yaml",
        "scripts/schema_to_field_semantics.py",
        "scripts/contracts.py",
        "scripts/contracts_schema.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # No manifest change: "scripts/**" already covers this closure. acceptance_lint's src/common
    # tail hangs off _check_acceptance_on_main (the executor runtime path), which the check never
    # calls -- it imports lint_acceptance_command only.
    "validate_acceptance_literals": (
        "scripts/executor/acceptance_lint.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # --- promoted out of the full-only tier -------------------------------------------------
    # The Recommendation model this validates is defined WHOLLY in scripts/executor/jsonl_store.py;
    # that module's scripts.ops_data_portal tail is imported inside functions the check never
    # calls (update_rec/file_rec), so the ops_portal/src.common closure is pruned, not missed.
    "validate_recommendations_schema": (
        "logs/.recommendations-log.jsonl",
        "scripts/executor/jsonl_store.py",
        "scripts/s3_log_store.py",
        "scripts/checks/ops_governance/validate_recommendations_schema.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # Scan scope IS the closure: the whitelist and the write-detection regexes live in the check's
    # own module, and every scanned file plus every whitelisted file sits under scripts/.
    "validate_rec_write_paths": (
        "scripts/sync/recommendations.py",
        "scripts/ops_data_portal.py",
        "scripts/checks/ops_governance/validate_rec_write_paths.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    "validate_decisions_local_writes": (
        "scripts/sync/ops.py",
        "scripts/ops_data_portal.py",
        "scripts/checks/ops_governance/validate_decisions_local_writes.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # Scans scripts/ AND src/ -- the migrated-table block applies to every file in both roots.
    "validate_warehouse_write_sources": (
        "scripts/ops_writer.py",
        "src/common/ducklake_writes.py",
        "scripts/checks/ops_governance/validate_warehouse_write_sources.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # Symmetric-difference of the Dq* Annotated markers against the per-column tests: BOTH sides
    # are inputs, so a src/schemas/ marker edit alone must fire the gate.
    "validate_pydantic_yaml_drift": (
        "config/agent/data_quality/ops.yaml",
        "src/schemas/rec.py",
        "src/schemas/decision.py",
        "src/schemas/annotations.py",
        "scripts/checks/ops_governance/validate_pydantic_yaml_drift.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # ops.yaml supplies the enforced: true rows; the per-table decisions/ shards supply the
    # enforcement_ready states the gate matches them against.
    "validate_dq_manifest_gate": (
        "config/agent/data_quality/ops.yaml",
        "config/agent/data_quality/decisions/ops_recommendations.yaml",
        "scripts/checks/ops_governance/validate_dq_manifest_gate.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
    # Drift gate: the contract file and the RELEVANCE_VERDICTS constant it is compared against.
    "validate_rec_relevance_contract": (
        "docs/contracts/recommendation-relevance.yaml",
        "scripts/rec_relevance.py",
        "scripts/checks/ops_governance/validate_rec_relevance_contract.py",
        "scripts/checks/_common.py",
        "scripts/checks/registry.py",
    ),
}


class TestClosureMembersAreCovered:
    """Each closure member is asserted MATCHED by the entry's patterns, not present in them as a
    literal -- so rewriting a glob (or moving an input behind a wider one) keeps the row green
    while a member falling out of coverage reddens it.

    Bare fnmatch, not scripts.validate._pre_glob_match: an import edge from tests/checks/** into
    the driver widens the affected-test graph pinned by tests/checks/registry/
    test_manifest_contracts.py. The substitution is sound in the safe direction -- the production
    matcher is fnmatch PLUS a leading-'**/' retry that can only ADD matches, so anything green
    here is green there too.
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
        assert not self._covered(name, "README.md")
