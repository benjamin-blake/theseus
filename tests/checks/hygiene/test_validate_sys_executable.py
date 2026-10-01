"""Tests for validate_sys_executable()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry, validation_result
from scripts.checks.hygiene.validate_sys_executable import validate_sys_executable


class TestValidateSysExecutable:
    """Tests for validate_sys_executable()."""

    validate_sys_executable = staticmethod(validate_sys_executable)

    def test_passes_when_sys_executable_used(self, tmp_path: Path) -> None:
        """No failure when sys.executable is used."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run([sys.executable, "-m", "pytest"])\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert failed == []

    def test_fails_when_bare_python_used(self, tmp_path: Path) -> None:
        """Fails when bare 'python' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text("subprocess.run(['python', '-m', 'pytest'])\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed

    def test_fails_when_bare_pip_used(self, tmp_path: Path) -> None:
        """Fails when bare 'pip' string is first element in subprocess call."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_pip.py").write_text('subprocess.run(["pip", "install", "boto3"])\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_sys_executable(failed)
        assert "sys.executable lint" in failed


class TestSysExecutableAccountingDeclaration:
    """The check declares how many python files it scanned, so a run is never recorded as undeclared."""

    @staticmethod
    def _run(root: Path) -> tuple[list[str], registry._Declaration | None]:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", root):
            validate_sys_executable(failed)
        return failed, registry.pop_declaration()

    @staticmethod
    def _outcome(root: Path) -> registry.CheckOutcome:
        validation_result._OUTCOMES.clear()
        try:
            with patch("scripts.checks._common.ROOT", root):
                validation_result.dispatch_recording("validate_sys_executable", [], validate_sys_executable)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        return outcome

    def test_declares_every_scanned_python_file(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        (scripts_dir / "nested").mkdir(parents=True)
        (scripts_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
        (scripts_dir / "nested" / "b.py").write_text("y = 2\n", encoding="utf-8")
        (scripts_dir / "notes.txt").write_text("not python\n", encoding="utf-8")
        failed, declaration = self._run(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 2, "python_files")

    def test_failing_run_still_declares_the_scanned_files(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text("subprocess.run(['python', '-m', 'pytest'])\n", encoding="utf-8")
        failed, declaration = self._run(tmp_path)
        assert failed == ["sys.executable lint"]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 1, "python_files")

    def test_empty_scripts_tree_declares_zero_examined(self, tmp_path: Path) -> None:
        failed, declaration = self._run(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, "python_files")

    def test_clean_run_is_recorded_enforced(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run([sys.executable, "-m", "pytest"])\n', encoding="utf-8")
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("enforced", 1, "python_files")

    def test_empty_scripts_tree_is_recorded_vacuous(self, tmp_path: Path) -> None:
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("vacuous", 0, "python_files")
