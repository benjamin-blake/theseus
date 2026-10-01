"""Tests for validate_acceptance_literals() -- repo-wide static acceptance-literal lint guard."""

import ast
from pathlib import Path
from unittest.mock import patch

from scripts.checks import _common, registry, validation_result
from scripts.checks.ops_governance.validate_acceptance_literals import (
    _find_violations,
    _resolve_string_value,
    _scan_file,
    validate_acceptance_literals,
)


class TestValidateAcceptanceLiterals:
    """Tests for validate_acceptance_literals() -- rec-2772 class-level guard."""

    def test_catches_planted_prose_acceptance_literal(self, tmp_path: Path, capsys) -> None:
        """A prose acceptance value with a stray unbalanced quote fails bash -n; the guard names
        the offending file and line, not just a bare pass/fail."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_filer.py"
        bad_file.write_text(
            "def _build_rec_fields():\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": (\n'
            '            "the rec\'s condition clears and it closes automatically."\n'
            "        ),\n"
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert len(failed) == 1
        assert "bad_filer.py" in failed[0]
        assert ":5:" in failed[0]

    def test_clean_tree_reports_nothing(self, tmp_path: Path, capsys) -> None:
        """A lint-valid static acceptance produces no violation."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        good_file = scripts_dir / "good_filer.py"
        good_file.write_text(
            "def _build_rec_fields():\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": "bin/venv-python -m scripts.ci_rca.probe_health --assert-clear",\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert failed == []

    def test_dynamic_value_is_skipped_not_guessed(self, tmp_path: Path, capsys) -> None:
        """A non-statically-resolvable acceptance (a variable/call) is skipped, not flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        dynamic_file = scripts_dir / "dynamic_filer.py"
        dynamic_file.write_text(
            "def _build_rec_fields(acceptance_text):\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": acceptance_text,\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert failed == []

    def test_fstring_placeholder_still_catches_syntax_error(self, tmp_path: Path, capsys) -> None:
        """A JoinedStr (f-string) acceptance still gets its literal segments lint-checked, with
        the interpolated {expr} substituted by a placeholder token."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_fstring_filer.py"
        bad_file.write_text(
            "def _build_rec_fields(fn):\n"
            "    return {\n"
            '        "title": "some sensor rec",\n'
            '        "acceptance": f"the rec\'s {fn} condition clears automatically.",\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert len(failed) == 1
        assert "bad_fstring_filer.py" in failed[0]

    def test_non_acceptance_dict_keys_are_ignored(self, tmp_path: Path, capsys) -> None:
        """A field-name map (e.g. cli.py's incidental literals) that happens to have a dict but
        no 'acceptance' key produces no violation -- verified-harmless per plan context."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        unrelated_file = scripts_dir / "unrelated.py"
        unrelated_file.write_text(
            'FIELD_MAP = {"title": "Title", "context": "Context"}\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_acceptance_literals(failed)
        assert failed == []

    def test_resolve_string_value_returns_none_for_non_string_joinedstr_segment(self) -> None:
        """A JoinedStr segment that is neither a str Constant nor a FormattedValue (defensive
        branch -- not reachable via any real f-string, but the resolver must not guess) resolves
        to None."""
        node = ast.JoinedStr(values=[ast.Constant(value=1)])
        assert _resolve_string_value(node) is None

    def test_scan_file_returns_empty_on_os_error(self, tmp_path: Path) -> None:
        """A path that cannot be read (e.g. deleted between glob and read) is skipped, not raised."""
        missing = tmp_path / "does-not-exist.py"
        assert _scan_file(missing) == ([], 0)

    def test_scan_file_returns_empty_on_syntax_error(self, tmp_path: Path) -> None:
        """A .py file with invalid syntax is skipped, not raised."""
        bad_syntax = tmp_path / "bad_syntax.py"
        bad_syntax.write_text("def broken(:\n", encoding="utf-8")
        assert _scan_file(bad_syntax) == ([], 0)

    def test_find_violations_includes_personal_scripts_when_present(self, tmp_path: Path) -> None:
        """personal_scripts/ is scanned too, when it exists alongside scripts/."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        personal_dir = tmp_path / "personal_scripts"
        personal_dir.mkdir()
        bad_file = personal_dir / "bad_personal_filer.py"
        bad_file.write_text(
            "def _build_rec_fields():\n"
            "    return {\n"
            '        "acceptance": "the rec\'s condition clears and it closes automatically.",\n'
            "    }\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations, linted = _find_violations()
        assert len(violations) == 1
        assert linted == 1
        assert "bad_personal_filer.py" in violations[0]


_GOOD = "bin/venv-python -m scripts.ci_rca.probe_health --assert-clear"
_BAD = "the rec's condition clears and it closes automatically."


def _write_filer(root: Path, rel: str, acceptance_values: list[str]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = "".join(f"    {{'title': 't', 'acceptance': {value!r}}},\n" for value in acceptance_values)
    path.write_text(f"RECS = [\n{entries}]\n", encoding="utf-8")


class TestAcceptanceLiteralsAccountingDeclaration:
    """The check declares how many acceptance literals it linted, so a run is never recorded as undeclared."""

    @staticmethod
    def _run(tmp_path: Path) -> tuple[list[str], registry._Declaration | None]:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_acceptance_literals(failed)
        return failed, registry.pop_declaration()

    @staticmethod
    def _outcome(tmp_path: Path) -> registry.CheckOutcome:
        validation_result._OUTCOMES.clear()
        try:
            with patch("scripts.checks._common.ROOT", tmp_path):
                validation_result.dispatch_recording("validate_acceptance_literals", [], validate_acceptance_literals)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        return outcome

    def test_declares_every_resolved_literal_across_both_trees(self, tmp_path: Path) -> None:
        _write_filer(tmp_path, "scripts/a.py", [_GOOD, _GOOD])
        _write_filer(tmp_path, "personal_scripts/b.py", [_GOOD])
        failed, declaration = self._run(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, "acceptance_literals")

    def test_declared_count_tracks_the_input(self, tmp_path: Path) -> None:
        _write_filer(tmp_path, "scripts/a.py", [_GOOD])
        _, first = self._run(tmp_path)
        _write_filer(tmp_path, "scripts/b.py", [_GOOD, _GOOD, _GOOD])
        _, second = self._run(tmp_path)
        assert first is not None and second is not None
        assert (first.count, second.count) == (1, 4)

    def test_unresolvable_values_and_non_acceptance_keys_are_not_counted(self, tmp_path: Path) -> None:
        _write_filer(tmp_path, "scripts/a.py", [_GOOD])
        (tmp_path / "scripts" / "dynamic.py").write_text(
            "def f(x):\n    return {'acceptance': x, 'title': 'not counted'}\n", encoding="utf-8"
        )
        (tmp_path / "scripts" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        _, declaration = self._run(tmp_path)
        assert declaration is not None
        assert declaration.count == 1

    def test_failing_literal_is_counted_as_examined(self, tmp_path: Path) -> None:
        _write_filer(tmp_path, "scripts/a.py", [_GOOD, _BAD])
        failed, declaration = self._run(tmp_path)
        assert len(failed) == 1
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 2, "acceptance_literals")
        assert self._outcome(tmp_path).status == "failed"

    def test_populated_tree_is_recorded_enforced(self, tmp_path: Path) -> None:
        _write_filer(tmp_path, "scripts/a.py", [_GOOD, _GOOD])
        outcome = self._outcome(tmp_path)
        assert (outcome.status, outcome.examined_count, outcome.examined_unit) == ("enforced", 2, "acceptance_literals")

    def test_tree_without_literals_is_recorded_vacuous(self, tmp_path: Path) -> None:
        """Python files with no resolvable acceptance literal are an empty domain, never an enforced pass."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "plain.py").write_text("X = {'title': 'no acceptance'}\n", encoding="utf-8")
        failed, declaration = self._run(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count) == ("examined", 0)
        assert self._outcome(tmp_path).status == "vacuous"

    def test_real_tree_declares_a_nonzero_literal_population(self) -> None:
        expected = 0
        for search_dir in (_common.ROOT / "scripts", _common.ROOT / "personal_scripts"):
            for py_file in search_dir.glob("**/*.py"):
                try:
                    tree = ast.parse(py_file.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Dict):
                        expected += sum(
                            1
                            for key, value in zip(node.keys, node.values)
                            if isinstance(key, ast.Constant)
                            and key.value == "acceptance"
                            and _resolve_string_value(value) is not None
                        )
        registry.pop_declaration()
        failed: list[str] = []
        validate_acceptance_literals(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.unit) == ("examined", "acceptance_literals")
        assert declaration.count == expected and expected > 0
