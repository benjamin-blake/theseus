"""Entry literals for the deps domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_requirements",
        module="scripts.checks.deps.validate_requirements",
        attr="validate_requirements",
        full_segment="full_after_dependency_health",
    ),
    Entry(
        name="validate_import_contracts",
        module="scripts.checks.deps.validate_import_contracts",
        attr="validate_import_contracts",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lockfile_sync",
        module="scripts.checks.deps.validate_lockfile_sync",
        attr="validate_lockfile_sync",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_dependency_graph_freshness",
        module="scripts.checks.deps.validate_dependency_graph_freshness",
        attr="validate_dependency_graph_freshness",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_check_manifests",
        module="scripts.checks.deps.validate_check_manifests",
        attr="validate_check_manifests",
        pre=True,
        pre_globs=(
            "scripts/checks/**",
            "docs/contracts/check-manifest.yaml",
            "scripts/dependency_graph.py",
            "scripts/extract_imports.py",
            "scripts/lambda_manifest.py",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_pre_glob_closure",
        module="scripts.checks.deps.validate_pre_glob_closure",
        attr="validate_pre_glob_closure",
        pre=True,
        # This check's own Entry glob MUST cover its own import closure over the FULL union of
        # tracked .py files -- registry.py's fixed-point raise (Decision 187 point 6 form) refuses
        # to assemble pre_sequence() otherwise. Never narrow this below ("**/*.py",
        # "scripts/checks/**") -- see registry._assert_pre_glob_closure_gate_intact.
        pre_globs=("**/*.py", "scripts/checks/**"),
        full_segment="full_after_lint",
    ),
)
