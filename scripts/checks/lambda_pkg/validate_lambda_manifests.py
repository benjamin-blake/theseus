"""Lambda manifest schema validation (Decision 104)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry


@registry.register("validate_lambda_manifests", owner="platform")
def validate_lambda_manifests(failed: list[str]) -> None:
    """Schema-validate all src/lambdas/<name>/manifest.yaml files.

    Delegates to scripts.lambda_manifest.cmd_validate. Parallel to
    validate_platform_roadmap; runs in the full presubmit tier (NOT --pre).
    Rejects structural drift: unknown fields, missing artifact, invalid status.

    Declares examined(manifest.yaml files schema-validated, unit="manifests") (Decision 170); a
    src/lambdas/ with no manifests, or no src/lambdas/ at all, is examined(0).
    """
    print("\n=== Lambda manifest schema validation ===")

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import _LAMBDAS_DIR, cmd_validate  # noqa: PLC0415

        rc = cmd_validate(None)
        examined = 0
        if _LAMBDAS_DIR.exists():
            examined = sum(
                1
                for child in _LAMBDAS_DIR.iterdir()
                if child.is_dir() and child.name != "__pycache__" and (child / "manifest.yaml").exists()
            )
        registry.examined(examined, unit="manifests")
        if rc != 0:
            failed.append("Lambda manifest schema validation")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda manifest schema validation")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda manifest schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
