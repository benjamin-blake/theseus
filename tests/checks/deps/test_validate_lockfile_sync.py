"""Tests for validate_lockfile_sync() -- thin wrapper around import_governance.check_lockfile_sync."""

from pathlib import Path
from unittest.mock import patch

import pytest

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
        declared = import_governance.count_declared_requirements()
        assert declared > 0, "the live tree must declare at least one floor"
        assert declaration.count == declared

    @pytest.mark.parametrize("absent_index", [0, 1, 2, 3])
    def test_a_missing_requirements_file_fails_without_raising(self, tmp_path: Path, absent_index: int) -> None:
        """REGRESSION (code-review round 1, Medium): the accounting count must not raise on exactly
        the missing-input path check_lockfile_sync was newly made to hard-fail -- raising would
        abort the registered check before it could append to `failed`."""
        from scripts import import_governance  # noqa: PLC0415

        names = ("requirements.in", "requirements-dev.in", "requirements.txt", "requirements-dev.txt")
        paths = tuple(tmp_path / name for name in names)
        for index, path in enumerate(paths):
            if index != absent_index:
                path.write_text("", encoding="utf-8")

        failed: list[str] = []
        with patch.object(import_governance, "_LOCKFILE_PATHS", paths):
            validate_lockfile_sync(failed)
        assert failed == ["Lockfile sync (Decision 80)"]

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
