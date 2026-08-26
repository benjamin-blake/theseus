"""Entry literals for the lambda_pkg domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.

The two manifest-schema checks are now in BOTH tiers; the bundle-completeness and deploy-gating
checks stay full-only (env-blocked / advisory -- see tests/checks/lambda_pkg/test__manifest.py).
validate_lambda_manifests' and validate_lambda_manifest_coverage's own docstrings still say "full
presubmit tier"; THESE ENTRIES are the authority. The stale sentences are deliberately left alone:
both modules sit in the check-accounting grandfather baseline, whose touch-it-fix-it rule turns any
edit to them into an examined()/skipped() adoption -- a separate change.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_lambda_manifests",
        module="scripts.checks.lambda_pkg.validate_lambda_manifests",
        attr="validate_lambda_manifests",
        pre=True,
        pre_globs=(
            "src/lambdas/**",
            "scripts/lambda_manifest.py",
            "scripts/checks/lambda_pkg/**",
            "scripts/checks/_common.py",
            "scripts/checks/registry.py",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lambda_manifest_coverage",
        module="scripts.checks.lambda_pkg.validate_lambda_manifest_coverage",
        attr="validate_lambda_manifest_coverage",
        pre=True,
        pre_globs=(
            "src/lambdas/**",
            "scripts/lambda_manifest.py",
            "scripts/checks/lambda_pkg/**",
            "scripts/checks/_common.py",
            "scripts/checks/registry.py",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lambda_bundle_completeness",
        module="scripts.checks.lambda_pkg.validate_lambda_bundle_completeness",
        attr="validate_lambda_bundle_completeness",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lambda_deploy_gating",
        module="scripts.checks.lambda_pkg.validate_lambda_deploy_gating",
        attr="validate_lambda_deploy_gating",
        full_segment="full_after_lint",
    ),
)
