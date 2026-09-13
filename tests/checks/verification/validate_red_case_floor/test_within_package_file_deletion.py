"""rec-3727 acceptance: deleting a non-last mirror-test file from a concern-split package's
directory fires validate_red_case_floor for that Entry, even when a sibling file in the same
package still stands and still carries a red case -- the any()-over-package-files disjunction in
test_red_case_signal.py cannot see this escape on its own (LSA-01 leg a sub-part 2 residue)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks import _common, registry
from scripts.checks._schema import Entry
from scripts.checks.verification.validate_red_case_floor import (
    _deleted_package_mirror_files,
    _mirror_package_dir,
    validate_red_case_floor,
)


def _entry(name: str, module: str, attr: str | None = None) -> Entry:
    return Entry(name=name, module=module, attr=attr or name)


class TestRealEntryPackageDeletionFires:
    """Drives a REAL live Entry (validate_placement) whose mirror resolves to a directory of
    three test_*.py files. Deleting one of the other two, while the one carrying its own red case
    is left standing, must still fire -- the file SET may not shrink, independent of whether the
    floor's own red-case disjunction still clears."""

    _PACKAGE_ENTRY = "validate_placement"
    _MIRROR_DIR = "tests/checks/hygiene/validate_placement"

    def test_deleting_a_sibling_file_fires_even_though_a_red_case_still_stands(self) -> None:
        deleted_path = f"{self._MIRROR_DIR}/test_root_allowlists.py"
        with patch.object(_common, "get_status_aware_diff", return_value=[("D", deleted_path)]):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                detail = registry.pop_failure_detail()
        assert failed != []
        assert detail is not None
        assert any(self._PACKAGE_ENTRY in line and deleted_path in line for line in detail)

    def test_no_deletions_in_the_diff_is_clean_for_the_package_entry(self) -> None:
        with patch.object(_common, "get_status_aware_diff", return_value=[]):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                detail = registry.pop_failure_detail()
        assert not any(self._PACKAGE_ENTRY in line for line in (detail or []))

    def test_deleting_a_file_outside_any_resolved_package_is_not_flagged_by_this_guard(self) -> None:
        with patch.object(_common, "get_status_aware_diff", return_value=[("D", "docs/plans/PLAN-unrelated.yaml")]):
            hits = _deleted_package_mirror_files(dict(registry._ALL_ENTRIES))
        assert hits == {}

    def test_deleting_the_packages_init_file_is_not_a_test_file_deletion(self) -> None:
        """`__init__.py` is not a `test_*.py` mirror file -- its deletion is not this guard's
        concern (a red-case-floor existence failure, if any, is the general mirror-resolution
        check's job, not this one)."""
        deleted_path = f"{self._MIRROR_DIR}/__init__.py"
        with patch.object(_common, "get_status_aware_diff", return_value=[("D", deleted_path)]):
            hits = _deleted_package_mirror_files(dict(registry._ALL_ENTRIES))
        assert hits == {}


class TestSyntheticPackageFixture:
    """A minimal synthetic package (two test_*.py files, one deleted) isolates the guard from the
    real repository's mirror layout."""

    def test_deletion_of_one_of_two_mirror_files_is_flagged(self, tmp_path: Path) -> None:
        pkg = tmp_path / "tests" / "checks" / "fake" / "validate_x"
        pkg.mkdir(parents=True)
        (pkg / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
        entries = {"validate_x": _entry("validate_x", "scripts.checks.fake.validate_x")}
        deleted_path = "tests/checks/fake/validate_x/test_b.py"
        with (
            patch.object(_common, "ROOT", tmp_path),
            patch("scripts.checks.verification.validate_red_case_floor.tcc.map_source_to_test", lambda p: pkg),
            patch.object(_common, "get_status_aware_diff", return_value=[("D", deleted_path)]),
        ):
            hits = _deleted_package_mirror_files(entries, tmp_path)
        assert hits == {"validate_x": [deleted_path]}

    def test_deletion_of_a_file_from_an_unrelated_package_is_not_flagged(self, tmp_path: Path) -> None:
        pkg = tmp_path / "tests" / "checks" / "fake" / "validate_x"
        pkg.mkdir(parents=True)
        entries = {"validate_x": _entry("validate_x", "scripts.checks.fake.validate_x")}
        with (
            patch.object(_common, "ROOT", tmp_path),
            patch("scripts.checks.verification.validate_red_case_floor.tcc.map_source_to_test", lambda p: pkg),
            patch.object(_common, "get_status_aware_diff", return_value=[("D", "tests/checks/fake/validate_y/test_c.py")]),
        ):
            hits = _deleted_package_mirror_files(entries, tmp_path)
        assert hits == {}


class TestMirrorPackageDirHelper:
    def test_single_file_mirror_resolves_to_none(self, tmp_path: Path) -> None:
        target = tmp_path / "test_thing.py"
        with (
            patch.object(_common, "ROOT", tmp_path),
            patch("scripts.checks.verification.validate_red_case_floor.tcc.map_source_to_test", lambda p: target),
        ):
            assert _mirror_package_dir("scripts.checks.fake.thing") is None

    def test_unresolvable_mirror_is_none(self, tmp_path: Path) -> None:
        with (
            patch.object(_common, "ROOT", tmp_path),
            patch("scripts.checks.verification.validate_red_case_floor.tcc.map_source_to_test", lambda p: None),
        ):
            assert _mirror_package_dir("scripts.checks.fake.thing") is None

    def test_package_dir_outside_scan_root_is_skipped_not_raised(self, tmp_path: Path) -> None:
        """A mirror directory that cannot be expressed relative to `scan_root` (e.g. a test
        double-patching map_source_to_test to point outside the fixture tree) is silently
        excluded rather than raising ValueError up through the guard."""
        outside_pkg = tmp_path.parent / "outside_pkg"
        outside_pkg.mkdir(exist_ok=True)
        entries = {"validate_x": _entry("validate_x", "scripts.checks.fake.validate_x")}
        with (
            patch.object(_common, "ROOT", tmp_path),
            patch("scripts.checks.verification.validate_red_case_floor.tcc.map_source_to_test", lambda p: outside_pkg),
            patch.object(_common, "get_status_aware_diff", return_value=[("D", "anything/test_z.py")]),
        ):
            hits = _deleted_package_mirror_files(entries, tmp_path)
        assert hits == {}


class TestRootThreading:
    """`root=` propagates to both `get_status_aware_diff` and the package-relative-path
    computation, mirroring validate_tier_demotion_markers' own root-threading idiom."""

    def test_explicit_root_is_forwarded_to_get_status_aware_diff(self, tmp_path: Path) -> None:
        with patch.object(_common, "get_status_aware_diff", return_value=[]) as spy:
            validate_red_case_floor([], root=tmp_path)
        spy.assert_called_once_with(tmp_path)
