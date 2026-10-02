"""Lambda manifest coverage validation (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_lambda_manifest_coverage", owner="platform")
def validate_lambda_manifest_coverage(failed: list[str]) -> None:
    """Every src/lambdas/<name>/ directory must have a schema-valid manifest.yaml.

    Scalability gate: each new Lambda artifact added to src/lambdas/ automatically
    fails CI until its manifest is authored. Delegates to cmd_check_coverage.
    Runs in the full presubmit tier.

    Declares examined(src/lambdas/<name>/ directories probed for a manifest.yaml, unit="lambda dirs")
    (Decision 170); a src/lambdas/ with no such directory, or no src/lambdas/ at all, is examined(0).
    """
    print("\n=== Lambda manifest coverage ===")

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import _LAMBDAS_DIR, cmd_check_coverage  # noqa: PLC0415

        rc = cmd_check_coverage(None)
        examined = 0
        if _LAMBDAS_DIR.exists():
            examined = sum(1 for child in _LAMBDAS_DIR.iterdir() if child.is_dir() and child.name != "__pycache__")
        registry.examined(examined, unit="lambda dirs")
        if rc != 0:
            failed.append("Lambda manifest coverage")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda manifest coverage")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda manifest coverage")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
