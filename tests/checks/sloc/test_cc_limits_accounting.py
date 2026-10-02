"""Check-accounting declaration tests for validate_cc_limits() (Decision 170)."""

import ast
import io
import os
import re
import tokenize
from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry, validation_result
from scripts.checks.sloc.cc_limits import validate_cc_limits

_REPO_ROOT = Path(__file__).parents[3]
_ORACLE_PRUNED_DIRS = frozenset(
    {"pip", "lambda-packages", "docker", "terraform", ".venv", "node_modules", ".git", "personal_scripts"}
)
_ORACLE_WAIVER = re.compile(r"#\s*complexity-waiver:\s*decision-43")


def _oracle_def_count(source: str) -> int:
    """Counts `def` keyword tokens -- one per FunctionDef/AsyncFunctionDef -- without the ast walk."""
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return sum(1 for tok in tokens if tok.type == tokenize.NAME and tok.string == "def")


def _oracle_real_tree_functions() -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _ORACLE_PRUNED_DIRS]
        for filename in filenames:
            if filename == "__init__.py" or not filename.endswith(".py"):
                continue
            source = (Path(dirpath) / filename).read_text(encoding="utf-8", errors="replace")
            if _ORACLE_WAIVER.search("\n".join(source.splitlines()[:10])):
                continue
            try:
                compile(source, filename, "exec", dont_inherit=True, flags=ast.PyCF_ONLY_AST)
            except SyntaxError:
                continue
            total += _oracle_def_count(source)
    return total


class TestCcLimitsAccountingDeclaration:
    """The gate declares how many functions it measured for branch count (functions in waivered or
    unparsable files are outside its domain), so a run is recorded enforced with a count that tracks
    the tree instead of undeclared."""

    _UNIT = "functions"
    _HEAVY = "def heavy(x):\n" + "\n".join(f"    if x == {i}: pass" for i in range(21)) + "\n"

    @staticmethod
    def _declare(root: Path) -> tuple[list[str], registry._Declaration | None]:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", root):
            validate_cc_limits(failed)
        return failed, registry.pop_declaration()

    def test_real_tree_declares_every_measured_function(self) -> None:
        expected = _oracle_real_tree_functions()
        failed, declaration = self._declare(_REPO_ROOT)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, self._UNIT)

    def test_declared_count_tracks_functions_not_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
        _, base = self._declare(tmp_path)
        (tmp_path / "a.py").write_text(
            "def f():\n    def inner():\n        pass\n\n"
            "async def g():\n    pass\n\n"
            "class C:\n    def m(self):\n        pass\n",
            encoding="utf-8",
        )
        failed, grown = self._declare(tmp_path)
        assert failed == []
        assert base is not None and grown is not None
        assert (base.count, grown.count) == (1, 4)

    def test_waivered_unparsable_and_excluded_files_not_counted(self, tmp_path: Path) -> None:
        (tmp_path / "kept.py").write_text("def kept():\n    pass\n", encoding="utf-8")
        (tmp_path / "waived.py").write_text("# complexity-waiver: decision-43\n" + self._HEAVY, encoding="utf-8")
        (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        (tmp_path / "__init__.py").write_text("def init_fn():\n    pass\n", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "vendored.py").write_text("def vendored():\n    pass\n", encoding="utf-8")
        failed, declaration = self._declare(tmp_path)
        assert failed == []
        assert declaration is not None and declaration.count == 1

    def test_failing_function_still_counted(self, tmp_path: Path) -> None:
        (tmp_path / "big.py").write_text(self._HEAVY + "\ndef small():\n    pass\n", encoding="utf-8")
        failed, declaration = self._declare(tmp_path)
        assert failed == ["Cyclomatic complexity limits (Decision 43)"]
        assert declaration is not None and declaration.count == 2

    def test_no_function_declares_empty_domain(self, tmp_path: Path) -> None:
        (tmp_path / "consts.py").write_text("X = 1\n", encoding="utf-8")
        failed, declaration = self._declare(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, self._UNIT)

    def test_real_tree_is_recorded_enforced(self) -> None:
        validation_result._OUTCOMES.clear()
        try:
            validation_result.dispatch_recording("validate_cc_limits", [], validate_cc_limits)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert (outcome.status, outcome.examined_unit) == ("enforced", self._UNIT)
        assert outcome.examined_count is not None and outcome.examined_count > 0
