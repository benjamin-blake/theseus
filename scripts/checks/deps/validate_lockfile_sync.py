"""Compiled requirements-output sync validation (Decision 104)."""

from __future__ import annotations

from scripts.checks import registry


@registry.register("validate_lockfile_sync", owner="platform")
def validate_lockfile_sync(failed: list[str]) -> None:
    """Thin wrapper: verify the compiled requirements*.txt outputs pin every requirements*.in floor
    (Decision 80 / T3.11). Delegates to scripts.import_governance."""
    print("\n=== Lockfile sync (Decision 80 / T3.11) ===")
    from scripts import import_governance  # noqa: PLC0415

    in_sync, message = import_governance.check_lockfile_sync()
    print(f"  {'PASS' if in_sync else 'FAIL'}: {message}")
    registry.examined(import_governance.count_declared_requirements(), unit="declared_requirements")
    if not in_sync:
        failed.append("Lockfile sync (Decision 80)")
