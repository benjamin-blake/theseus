"""Tests for validate_no_cross_test_imports() (Decision 131 no-cross-test-import guard).

Placed at its MIRROR location (tests/checks/hygiene/ mirrors scripts/checks/hygiene/) to
demonstrate the new convention -- check_test_file_exists is still satisfied by
tests/test_validate.py under the live grandfather (scripts/checks/** -> tests/test_validate.py),
exactly as the existing tests/checks/test_validate_prose_allowlist.py already relies on.

Imports only from scripts.checks.hygiene -- never from another test module (it must pass its
own guard).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry, validation_result
from scripts.checks.hygiene.validate_no_cross_test_imports import (
    _find_violations,
    validate_no_cross_test_imports,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestFindViolations:
    """Exercises the pure _find_violations(paths) core directly on synthetic temp files."""

    def test_cross_test_module_import_is_flagged(self, tmp_path: Path) -> None:
        """`from tests.test_foo import X` -- the canonical violation shape."""
        path = _write(tmp_path, "tests/test_a.py", "from tests.test_foo import X\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1
        assert "test_a.py" in violations[0]

    def test_bare_import_of_a_test_module_is_flagged(self, tmp_path: Path) -> None:
        """`import tests.test_foo` -- ast.Import, not ast.ImportFrom."""
        path = _write(tmp_path, "tests/test_b.py", "import tests.test_foo\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_relative_import_of_a_test_name_is_flagged(self, tmp_path: Path) -> None:
        """`from . import test_helper` -- module is None, the imported name itself is checked."""
        path = _write(tmp_path, "tests/checks/test_c.py", "from . import test_helper\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_conftest_import_not_flagged(self, tmp_path: Path) -> None:
        """conftest.py never starts with test_ -- exempt by construction."""
        path = _write(tmp_path, "tests/test_d.py", "from tests.conftest import Y\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_fixtures_package_import_not_flagged(self, tmp_path: Path) -> None:
        """tests/fixtures/** never starts with test_ -- exempt by construction."""
        path = _write(tmp_path, "tests/test_e.py", "from tests.fixtures.helper import Z\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_grandfathered_path_is_exempt(self, tmp_path: Path) -> None:
        """tests/test_verifier_harness.py is in _GRANDFATHERED_CROSS_TEST_IMPORTS -- exempt
        even though its content would otherwise be flagged."""
        path = _write(
            tmp_path,
            "tests/test_verifier_harness.py",
            "from tests.test_verifiers.test_harness import test_run_all_verifiers\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_non_test_module_import_not_flagged(self, tmp_path: Path) -> None:
        """An ordinary production-module import is not a cross-test import."""
        path = _write(tmp_path, "tests/test_f.py", "from scripts.checks.hygiene import validate_placement\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []


class TestValidateNoCrossTestImportsFunction:
    """Exercises the registered check function itself (failed-list wiring)."""

    def test_appends_failed_on_violation(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_g.py", "from tests.test_foo import X\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_no_cross_test_imports(failed)
        assert failed == ["No-cross-test-import guard"]

    def test_real_tree_returns_clean(self) -> None:
        """The one pre-existing violation (tests/test_verifier_harness.py) is grandfathered,
        so the guard is clean over the real repo tests/ tree (unpatched ROOT)."""
        failed: list[str] = []
        validate_no_cross_test_imports(failed)
        assert failed == []


class TestNoCrossTestImportsAccountingDeclaration:
    """The check declares how many test modules it parsed, so a run is never recorded as undeclared."""

    @staticmethod
    def _run(tmp_path: Path) -> tuple[list[str], registry._Declaration | None]:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_no_cross_test_imports(failed)
        return failed, registry.pop_declaration()

    @staticmethod
    def _outcome(tmp_path: Path) -> registry.CheckOutcome:
        validation_result._OUTCOMES.clear()
        try:
            with patch("scripts.checks._common.ROOT", tmp_path):
                validation_result.dispatch_recording("validate_no_cross_test_imports", [], validate_no_cross_test_imports)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        return outcome

    def test_declares_every_parsed_test_module(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "x = 1\n")
        _write(tmp_path, "tests/checks/test_b.py", "y = 2\n")
        _write(tmp_path, "tests/conftest.py", "z = 3\n")
        failed, declaration = self._run(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, "test_modules")

    def test_declared_count_tracks_the_input(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "x = 1\n")
        _, first = self._run(tmp_path)
        _write(tmp_path, "tests/test_b.py", "y = 2\n")
        _write(tmp_path, "tests/test_c.py", "z = 3\n")
        _, second = self._run(tmp_path)
        assert first is not None and second is not None
        assert (first.count, second.count) == (1, 3)

    def test_violating_module_is_counted_as_examined(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "x = 1\n")
        _write(tmp_path, "tests/test_g.py", "from tests.test_foo import X\n")
        failed, declaration = self._run(tmp_path)
        assert failed == ["No-cross-test-import guard"]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 2, "test_modules")

    def test_grandfathered_and_unparseable_modules_are_not_counted(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "x = 1\n")
        _write(tmp_path, "tests/test_verifier_harness.py", "from tests.test_verifiers.test_harness import t\n")
        _write(tmp_path, "tests/test_broken.py", "def (:\n")
        failed, declaration = self._run(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 1, "test_modules")

    def test_populated_tree_is_recorded_enforced(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "x = 1\n")
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("enforced", 1, "test_modules")

    def test_empty_tree_is_recorded_vacuous(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("vacuous", 0, "test_modules")

    def test_real_tree_examines_a_nonzero_population(self) -> None:
        registry.pop_declaration()
        failed: list[str] = []
        validate_no_cross_test_imports(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined" and declaration.unit == "test_modules"
        assert declaration.count is not None and declaration.count > 100
