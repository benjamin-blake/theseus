"""Degraded-input branches of the tests-tree scans: unparseable files, cache artifacts, and
paths that resolve to no module at all.

These are the guards that keep one malformed file in tests/ from taking the whole --pre gate
down the loud edited-set fallback path (Decision 55: degrade loudly and narrowly, never crash
the gate) -- they are only reachable with inputs the normal derivation never produces, so they
are exercised at the helper boundary rather than through derive_affected_tests().
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks.deps import affected_tests as at
from tests.fixtures.affected_tests_helpers import write_file as _write


class TestTestsTreeImportClosureResilience:
    """_tests_tree_import_closure_channel walks and parses every tests/**/test_*.py itself."""

    def test_candidate_outside_the_search_dirs_yields_no_scan(self, tmp_path: Path) -> None:
        """A candidate that maps to no dotted module name leaves nothing to match against, so
        the scan is skipped entirely rather than matching every file against an empty set."""
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        assert at._tests_tree_import_closure_channel(["notes.txt"], tmp_path) == set()

    def test_pycache_artifacts_are_never_selected(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/fixtures/helper.py", "VALUE = 1\n")
        importer = "from tests.fixtures.helper import VALUE\n\ndef test_x():\n    assert VALUE\n"
        _write(tmp_path, "tests/test_real_importer.py", importer)
        _write(tmp_path, "tests/__pycache__/test_stale_importer.py", importer)

        assert at._tests_tree_import_closure_channel(["tests/fixtures/helper.py"], tmp_path) == {"tests/test_real_importer.py"}

    def test_unparseable_test_file_is_skipped_without_losing_its_siblings(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/fixtures/helper.py", "VALUE = 1\n")
        _write(tmp_path, "tests/test_broken.py", "def test_x(:\n")
        _write(
            tmp_path,
            "tests/test_good.py",
            "from tests.fixtures.helper import VALUE\n\ndef test_x():\n    assert VALUE\n",
        )

        assert at._tests_tree_import_closure_channel(["tests/fixtures/helper.py"], tmp_path) == {"tests/test_good.py"}


class TestForcingConftestResilience:
    """_is_forcing_conftest reads the conftest's text; the diff can name a path that is no longer
    on disk (a rename lands as D+A under --no-renames, and a stale index can name either half)."""

    def test_absent_conftest_is_not_forcing(self, tmp_path: Path) -> None:
        assert at._is_forcing_conftest("tests/gone/conftest.py", tmp_path) is False

    def test_absent_conftest_in_a_diff_selects_nothing_and_does_not_force(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/gone/conftest.py")], repo_root=tmp_path)

        assert result["selected"] == []
        assert result["manifest"]["full_suite_forced"] is False
        assert result["manifest"].get("fallback") is None
