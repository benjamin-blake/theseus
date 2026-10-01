"""Tests for validate_subprocess_encoding()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry, validation_result
from scripts.checks.hygiene.validate_subprocess_encoding import validate_subprocess_encoding


class TestValidateSubprocessEncoding:
    """Tests for validate_subprocess_encoding()."""

    validate_subprocess_encoding = staticmethod(validate_subprocess_encoding)

    def test_passes_when_encoding_present(self, tmp_path: Path) -> None:
        """No failure when subprocess.run with text=True also has encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "good.py").write_text('subprocess.run(["cmd"], text=True, encoding="utf-8")\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_fails_when_encoding_missing(self, tmp_path: Path) -> None:
        """Fails when subprocess.run with text=True has no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad.py").write_text('subprocess.run(["cmd"], capture_output=True, text=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed

    def test_passes_when_no_text_true(self, tmp_path: Path) -> None:
        """No failure when subprocess.run does not use text=True."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "ok.py").write_text('subprocess.run(["cmd"], capture_output=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert failed == []

    def test_catches_popen_without_encoding(self, tmp_path: Path) -> None:
        """Fails for subprocess.Popen with text=True and no encoding=."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_popen.py").write_text('subprocess.Popen(["cmd"], text=True)\n', encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        assert "Subprocess encoding lint" in failed


class TestCallBodyBoundary:
    """The paren-depth scanner must stop at the call's own closing paren: the incumbent
    fixtures are all single-call, single-line files, so a scanner that never terminates
    produced identical verdicts."""

    validate_subprocess_encoding = staticmethod(validate_subprocess_encoding)

    def _run(self, tmp_path: Path, body: str) -> list[str]:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "mod.py").write_text(body, encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_subprocess_encoding(failed)
        return failed

    def test_text_true_after_the_call_is_not_attributed_to_it(self, tmp_path: Path) -> None:
        """A clean call followed by an unrelated `text=True` later in the file stays clean."""
        failed = self._run(tmp_path, 'subprocess.run(["cmd"], check=True)\nhelper(text=True)\n')
        assert failed == []

    def test_encoding_after_the_call_does_not_absolve_it(self, tmp_path: Path) -> None:
        """A genuine violation is still reported when a later line mentions encoding=."""
        failed = self._run(tmp_path, 'subprocess.run(fmt("a"), text=True)\nprint("encoding=utf-8")\n')
        assert failed == ["Subprocess encoding lint"]


class TestSubprocessEncodingAccountingDeclaration:
    """The check declares how many python files it scanned, so a run is never recorded as undeclared."""

    @staticmethod
    def _run(root: Path) -> tuple[list[str], registry._Declaration | None]:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", root):
            validate_subprocess_encoding(failed)
        return failed, registry.pop_declaration()

    @staticmethod
    def _outcome(root: Path) -> registry.CheckOutcome:
        validation_result._OUTCOMES.clear()
        try:
            with patch("scripts.checks._common.ROOT", root):
                validation_result.dispatch_recording("validate_subprocess_encoding", [], validate_subprocess_encoding)
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
        (scripts_dir / "bad.py").write_text('subprocess.Popen(["cmd"], text=True)\n', encoding="utf-8")
        failed, declaration = self._run(tmp_path)
        assert failed == ["Subprocess encoding lint"]
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
        (scripts_dir / "good.py").write_text('subprocess.run(["cmd"], text=True, encoding="utf-8")\n', encoding="utf-8")
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("enforced", 1, "python_files")

    def test_empty_scripts_tree_is_recorded_vacuous(self, tmp_path: Path) -> None:
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("vacuous", 0, "python_files")
