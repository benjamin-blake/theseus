"""Plane-neutral boundary test (Decision 184 cl.2): AST scan of src/telemetry/*.py.

Asserts runtime imports are stdlib-only (duckdb only under TYPE_CHECKING), __init__.py
re-exports nothing, and both .importlinter telemetry contracts are present.
"""

from __future__ import annotations

import ast
import configparser
import sys
from pathlib import Path

_SRC_TELEMETRY = Path(__file__).resolve().parents[2] / "src" / "telemetry"
_IMPORTLINTER = Path(__file__).resolve().parents[2] / ".importlinter"


def _module_root(name: str) -> str:
    return name.split(".", 1)[0]


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _runtime_import_roots(tree: ast.Module) -> set[str]:
    """Return the top-level module roots imported OUTSIDE any `if TYPE_CHECKING:` block."""
    roots: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:  # noqa: N802
            if _is_type_checking_guard(node):
                return  # skip the guarded body entirely -- these are never runtime imports
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            for alias in node.names:
                roots.add(_module_root(alias.name))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            if node.module:
                roots.add(_module_root(node.module))

    Visitor().visit(tree)
    return roots


def _telemetry_py_files() -> list[Path]:
    return sorted(_SRC_TELEMETRY.glob("*.py"))


class TestRuntimeImportsAreStdlibOnly:
    def test_every_module_imports_only_stdlib_at_runtime(self) -> None:
        for py_file in _telemetry_py_files():
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            roots = _runtime_import_roots(tree)
            for root in roots:
                if root == "src":
                    continue  # intra-package imports (src.telemetry.*) are allowed
                assert root in sys.stdlib_module_names, f"{py_file.name}: non-stdlib runtime import {root!r}"

    def test_duckdb_is_imported_only_under_type_checking(self) -> None:
        for py_file in _telemetry_py_files():
            text = py_file.read_text(encoding="utf-8")
            if "duckdb" not in text:
                continue
            tree = ast.parse(text, filename=str(py_file))
            runtime_roots = _runtime_import_roots(tree)
            assert "duckdb" not in runtime_roots, f"{py_file.name}: duckdb imported at runtime (must be TYPE_CHECKING-only)"


class TestNoReExportFacade:
    def test_init_module_re_exports_nothing(self) -> None:
        init_path = _SRC_TELEMETRY / "__init__.py"
        tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
        for node in ast.walk(tree):
            assert not isinstance(node, (ast.Import, ast.ImportFrom)), "__init__.py must import nothing (no re-export facade)"
        assert not any(isinstance(node, ast.Assign) for node in tree.body), "__init__.py must define no names"


class TestImportLinterContractsPresent:
    def test_both_telemetry_contracts_are_declared(self) -> None:
        config = configparser.ConfigParser()
        config.read(_IMPORTLINTER, encoding="utf-8")
        sections = config.sections()

        purity = "importlinter:contract:src-telemetry-is-plane-neutral"
        assert purity in sections
        assert config[purity]["type"] == "forbidden"
        assert "src.telemetry" in config[purity]["source_modules"]
        for forbidden in ("scripts", "src.common", "src.data", "src.lambdas"):
            assert forbidden in config[purity]["forbidden_modules"]

        boundary = "importlinter:contract:scripts-never-import-telemetry-append"
        assert boundary in sections
        assert config[boundary]["type"] == "forbidden"
        assert "scripts" in config[boundary]["source_modules"]
        assert "src.telemetry.append" in config[boundary]["forbidden_modules"]
