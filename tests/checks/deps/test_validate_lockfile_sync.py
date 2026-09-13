"""Tests for validate_lockfile_sync() -- thin wrapper around import_governance.check_lockfile_sync."""

from unittest.mock import patch

from scripts.checks.deps.validate_lockfile_sync import validate_lockfile_sync


class TestValidateLockfileSync:
    """Tests for validate_lockfile_sync() -- thin wrapper around import_governance.check_lockfile_sync."""

    def test_passes_on_committed_lockfile(self) -> None:
        """Compiled outputs are in sync on the unmodified repository tree (integration smoke)."""
        failed: list[str] = []
        validate_lockfile_sync(failed)
        assert not failed, f"Unexpected lockfile-sync failures: {failed}"

    def test_appends_to_failed_on_drift(self) -> None:
        """When check_lockfile_sync returns (False, ...), failure is appended."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "check_lockfile_sync", return_value=(False, "mypackage missing from lock")):
            validate_lockfile_sync(failed)
        assert any("Lockfile" in f for f in failed)

    def test_no_failure_on_in_sync(self) -> None:
        """When check_lockfile_sync returns (True, ...), nothing is appended."""
        from scripts import import_governance  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(import_governance, "check_lockfile_sync", return_value=(True, "pins all packages")):
            validate_lockfile_sync(failed)
        assert not failed

    def test_declares_examined_declared_requirements(self) -> None:
        """Decision 170 touch-it-fix-it: the wrapper declares the count of floors it checked, sourced
        from the shared import_governance helper rather than re-parsed out of the message string."""
        from scripts import import_governance  # noqa: PLC0415
        from scripts.checks import registry  # noqa: PLC0415

        registry.examined(-1, unit="sentinel")
        validate_lockfile_sync([])
        declaration = registry._CURRENT_DECLARATION
        assert declaration.kind == "examined"
        assert declaration.unit == "declared_requirements"
        assert declaration.count == import_governance.count_declared_requirements() > 0

    def test_wired_in_both_tiers(self) -> None:
        """validate_lockfile_sync is a registered check in both the --pre and full-tier sequences.

        Decision 104: dispatch is registry-driven (scripts/checks/registry.py), not a literal
        `validate_lockfile_sync(failed)` call site in scripts/validate.py -- so tier membership
        is verified via the registry's declared sequences, not AST call-site counting.
        """
        from scripts.checks import registry  # noqa: PLC0415

        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_lockfile_sync" in pre_names, "validate_lockfile_sync missing from pre_sequence()"
        assert "validate_lockfile_sync" in full_names, "validate_lockfile_sync missing from full_sequence()"
