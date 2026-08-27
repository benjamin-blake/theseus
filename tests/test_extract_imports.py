"""Tests for scripts/extract_imports.py - AST-based src.* import extraction."""

import ast
import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "extract_imports.py"
_spec = importlib.util.spec_from_file_location("extract_imports", _SCRIPT_PATH)
_extract_imports = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_extract_imports)  # type: ignore[union-attr]
sys.modules["extract_imports"] = _extract_imports  # register so patch() can find it

extract_src_imports = _extract_imports.extract_src_imports
extract_first_party_imports = _extract_imports.extract_first_party_imports
_resolve_relative_import = _extract_imports._resolve_relative_import
_walk_source = _extract_imports._walk_source
_import_from_targets = _extract_imports._import_from_targets


class TestExtractSrcImports:
    """Tests for extract_src_imports()."""

    def test_plain_import_src_module(self, tmp_path: Path) -> None:
        """``import src.common.config`` is extracted as ``src.common.config``."""
        f = tmp_path / "sample.py"
        f.write_text("import src.common.config\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.common.config"]

    def test_from_src_import(self, tmp_path: Path) -> None:
        """``from src.common.ducklake import DuckLakeRuntime`` yields ``src.common.ducklake``."""
        f = tmp_path / "sample.py"
        f.write_text("from src.common.ducklake import DuckLakeRuntime\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.common.ducklake"]

    def test_no_src_imports_returns_empty(self, tmp_path: Path) -> None:
        """A file with no src.* imports returns an empty list."""
        f = tmp_path / "sample.py"
        f.write_text("import os\nfrom pathlib import Path\n", encoding="utf-8")
        assert extract_src_imports(f) == []

    def test_syntax_error_file_skipped(self, tmp_path: Path) -> None:
        """A file with a syntax error is skipped; returns an empty list."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n    pass\n", encoding="utf-8")
        assert extract_src_imports(f) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """A file that does not exist returns an empty list."""
        f = tmp_path / "nonexistent.py"
        assert extract_src_imports(f) == []

    def test_duplicate_imports_deduplicated(self, tmp_path: Path) -> None:
        """The same module imported twice appears only once in the output."""
        f = tmp_path / "sample.py"
        f.write_text("import src.common.config\nimport src.common.config\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.common.config"]

    def test_multiple_src_imports(self, tmp_path: Path) -> None:
        """Multiple distinct src.* imports are all returned."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import src.common.config\nfrom src.common.ducklake import DuckLakeRuntime\n",
            encoding="utf-8",
        )
        assert extract_src_imports(f) == ["src.common.config", "src.common.ducklake"]

    def test_non_src_import_ignored(self, tmp_path: Path) -> None:
        """Imports not starting with ``src`` are not returned."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import pandas\nfrom collections import defaultdict\nimport src.schemas\n",
            encoding="utf-8",
        )
        assert extract_src_imports(f) == ["src.schemas"]


class TestExtractFirstPartyImports:
    """Tests for extract_first_party_imports() including relative import resolution."""

    def test_absolute_src_import(self, tmp_path: Path) -> None:
        """from src.common.config import X yields src.common.config."""
        f = tmp_path / "sample.py"
        f.write_text("from src.common.config import X\n", encoding="utf-8")
        assert extract_first_party_imports(f) == ["src.common.config"]

    def test_absolute_scripts_import(self, tmp_path: Path) -> None:
        """from scripts.helper import do_stuff yields scripts.helper."""
        f = tmp_path / "sample.py"
        f.write_text("from scripts.helper import do_stuff\n", encoding="utf-8")
        assert extract_first_party_imports(f) == ["scripts.helper"]

    def test_both_src_and_scripts(self, tmp_path: Path) -> None:
        """Both src.* and scripts.* are returned when present."""
        f = tmp_path / "sample.py"
        f.write_text(
            "from src.pkg.mod import A\nfrom scripts.helper import B\n",
            encoding="utf-8",
        )
        assert extract_first_party_imports(f) == ["src.pkg.mod", "scripts.helper"]

    def test_relative_import_same_package(self, tmp_path: Path) -> None:
        """'from . import module_a' resolves to the containing package's absolute name."""
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
        f = tmp_path / "scripts" / "module_b.py"
        f.write_text("from . import module_a\n", encoding="utf-8")
        result = extract_first_party_imports(f, _repo_root=tmp_path)
        assert result == ["scripts.module_a"]

    def test_relative_import_with_submodule(self, tmp_path: Path) -> None:
        """'from .sub import X' resolves to the submodule path."""
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        f = tmp_path / "src" / "pkg" / "module_b.py"
        f.write_text("from .sub import thing\n", encoding="utf-8")
        result = extract_first_party_imports(f, _repo_root=tmp_path)
        assert result == ["src.pkg.sub"]

    def test_deduplicated_output(self, tmp_path: Path) -> None:
        """Duplicate imports appear only once."""
        f = tmp_path / "sample.py"
        f.write_text(
            "from scripts.helper import A\nfrom scripts.helper import B\n",
            encoding="utf-8",
        )
        assert extract_first_party_imports(f) == ["scripts.helper"]

    def test_non_first_party_ignored(self, tmp_path: Path) -> None:
        """Third-party and stdlib imports are not returned."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import os\nimport pandas\nfrom pathlib import Path\nfrom scripts.x import y\n",
            encoding="utf-8",
        )
        assert extract_first_party_imports(f) == ["scripts.x"]

    def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
        """Syntax error file returns empty list."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n    pass\n", encoding="utf-8")
        assert extract_first_party_imports(f) == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing file returns empty list."""
        assert extract_first_party_imports(tmp_path / "ghost.py") == []

    def test_custom_roots_param(self, tmp_path: Path) -> None:
        """Only imports matching the supplied roots tuple are returned."""
        f = tmp_path / "sample.py"
        f.write_text("from src.pkg import A\nfrom scripts.helper import B\n", encoding="utf-8")
        result = extract_first_party_imports(f, roots=("scripts",))
        assert result == ["scripts.helper"]
        assert "src.pkg" not in result

    def test_backward_compat_extract_src_imports_unchanged(self, tmp_path: Path) -> None:
        """extract_src_imports still works and is unaffected by the new function."""
        f = tmp_path / "sample.py"
        f.write_text("from src.common.config import X\nfrom scripts.helper import Y\n", encoding="utf-8")
        assert extract_src_imports(f) == ["src.common.config"]


class TestAbsoluteFromImportSubmoduleTargets:
    """`from <pkg> import <sub>` must land the edge on the SUBMODULE, not only the package.

    The package edge is kept as well: Python executes `<pkg>/__init__.py` on the way to the
    submodule, and a facade `__init__` (Decision 124) may itself be the re-exporting body the
    importer depends on -- so both edges are real and the union is the recall-safe (strictly
    additive) answer.
    """

    @staticmethod
    def _pkg(tmp_path: Path) -> Path:
        (tmp_path / "src" / "pkg" / "child").mkdir(parents=True)
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "sub.py").write_text("", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "child" / "__init__.py").write_text("", encoding="utf-8")
        return tmp_path

    def test_from_package_import_module_records_the_module(self, tmp_path: Path) -> None:
        """A resolvable submodule target yields the dotted submodule name."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import sub\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg", "src.pkg.sub"]

    def test_from_package_import_subpackage_records_the_subpackage(self, tmp_path: Path) -> None:
        """A submodule that is itself a package (dir with __init__.py) resolves too."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import child\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg", "src.pkg.child"]

    def test_from_package_import_symbol_keeps_package_only(self, tmp_path: Path) -> None:
        """A name that is a symbol, not a module on disk, keeps the pre-existing behaviour."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import VALUE\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg"]

    def test_mixed_names_record_only_the_module_ones(self, tmp_path: Path) -> None:
        """One statement importing a module and a symbol contributes exactly one extra name."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import VALUE, sub\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg", "src.pkg.sub"]

    def test_aliased_submodule_resolves_the_real_name(self, tmp_path: Path) -> None:
        """`import sub as s` resolves the imported name, never the local alias."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import sub as s\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg", "src.pkg.sub"]

    def test_star_import_records_the_package_only(self, tmp_path: Path) -> None:
        """`from src.pkg import *` has no module target -- '*' is not a module name."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import *\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg"]

    def test_absent_submodule_is_not_invented(self, tmp_path: Path) -> None:
        """A name resolving to no file on disk contributes nothing (no phantom modules)."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import ghost\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg"]

    def test_namespace_dir_without_init_is_not_a_module(self, tmp_path: Path) -> None:
        """A directory with no __init__.py is not a graph module, so it is not recorded."""
        root = self._pkg(tmp_path)
        (root / "src" / "pkg" / "nsdir").mkdir()
        f = root / "src" / "consumer.py"
        f.write_text("from src.pkg import nsdir\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg"]

    def test_relative_from_import_is_unchanged(self, tmp_path: Path) -> None:
        """A relative `from . import sub` still resolves to the submodule alone -- no package edge."""
        root = self._pkg(tmp_path)
        f = root / "src" / "pkg" / "mod.py"
        f.write_text("from . import sub\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg.sub"]

    def test_relative_submodule_from_import_is_unchanged(self, tmp_path: Path) -> None:
        """`from .child import thing` still resolves to src.pkg.child alone."""
        root = self._pkg(tmp_path)
        f = root / "src" / "pkg" / "mod.py"
        f.write_text("from .child import thing\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root) == ["src.pkg.child"]

    def test_live_repo_root_is_the_default_resolution_base(self, tmp_path: Path) -> None:
        """With no _repo_root the real repository tree resolves the target (build_graph's case)."""
        f = tmp_path / "sample.py"
        f.write_text("from scripts.checks import registry\n", encoding="utf-8")
        assert extract_first_party_imports(f) == ["scripts.checks", "scripts.checks.registry"]

    def test_pre_walked_nodes_resolve_submodules_identically(self, tmp_path: Path) -> None:
        """The `_nodes` fast path (build_graph) gets the same submodule targets."""
        root = self._pkg(tmp_path)
        source = "from src.pkg import sub\n"
        nodes = list(ast.walk(ast.parse(source)))
        f = root / "src" / "consumer.py"
        assert extract_first_party_imports(f, roots=("src",), _repo_root=root, _nodes=nodes) == [
            "src.pkg",
            "src.pkg.sub",
        ]


class TestResolveRelativeImport:
    """Tests for _resolve_relative_import() edge cases."""

    def test_level1_no_module(self, tmp_path: Path) -> None:
        """'from . import foo' (level=1, module=None) returns the package itself."""
        (tmp_path / "scripts").mkdir()
        f = tmp_path / "scripts" / "mod.py"
        result = _resolve_relative_import(f, level=1, module=None, roots=("scripts",), repo_root=tmp_path)
        assert result == "scripts"

    def test_level1_with_module(self, tmp_path: Path) -> None:
        """'from .sub import x' resolves to parent-package.sub."""
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        f = tmp_path / "src" / "pkg" / "mod.py"
        result = _resolve_relative_import(f, level=1, module="sub", roots=("src",), repo_root=tmp_path)
        assert result == "src.pkg.sub"

    def test_level2_parent_package(self, tmp_path: Path) -> None:
        """'from .. import sibling' (level=2) goes up one package level."""
        (tmp_path / "src" / "pkg" / "sub").mkdir(parents=True)
        f = tmp_path / "src" / "pkg" / "sub" / "mod.py"
        result = _resolve_relative_import(f, level=2, module="sibling", roots=("src",), repo_root=tmp_path)
        assert result == "src.pkg.sibling"

    def test_outside_roots_returns_none(self, tmp_path: Path) -> None:
        """File outside every root returns None."""
        f = tmp_path / "some_other_dir" / "mod.py"
        result = _resolve_relative_import(f, level=1, module="sub", roots=("src", "scripts"), repo_root=tmp_path)
        assert result is None

    def test_level_above_the_root_package_returns_none(self, tmp_path: Path) -> None:
        """'from .. import x' in a top-level module of a root escapes the root -- no resolution.

        src/mod.py sits directly under the 'src' root, so its package chain is just ['src'];
        level=2 asks for src's own parent, which is not a first-party module.
        """
        (tmp_path / "src").mkdir()
        f = tmp_path / "src" / "mod.py"
        result = _resolve_relative_import(f, level=2, module="sibling", roots=("src",), repo_root=tmp_path)
        assert result is None

    def test_level_above_the_root_package_is_dropped_end_to_end(self, tmp_path: Path) -> None:
        """The unresolvable relative import contributes no module name to the extraction."""
        (tmp_path / "src").mkdir()
        f = tmp_path / "src" / "mod.py"
        f.write_text("from .. import sibling\nfrom src.other import thing\n", encoding="utf-8")
        assert extract_first_party_imports(f, roots=("src",), _repo_root=tmp_path) == ["src.other"]


class TestMain:
    """Tests for the CLI entry point."""

    def test_main_no_args_returns_zero(self) -> None:
        """main() with no file arguments exits with code 0 and prints nothing."""
        original_argv = sys.argv[:]
        try:
            sys.argv = ["extract_imports.py"]
            result = _extract_imports.main()
        finally:
            sys.argv = original_argv
        assert result == 0

    def test_main_outputs_imports(self, tmp_path: Path, capsys) -> None:
        """main() prints one import per line for each file argument."""
        f = tmp_path / "sample.py"
        f.write_text(
            "import src.common.config\nfrom src.schemas.rec import Rec\n",
            encoding="utf-8",
        )
        original_argv = sys.argv[:]
        try:
            sys.argv = ["extract_imports.py", str(f)]
            _extract_imports.main()
        finally:
            sys.argv = original_argv
        captured = capsys.readouterr()
        assert captured.out.strip() == "src.common.config\nsrc.schemas.rec"


class TestWalkSource:
    """_walk_source is the read+parse+walk seam split out of extract_first_party_imports so that
    function's own branch count stays under the Decision 43 cyclomatic limit."""

    def test_returns_walked_nodes_for_a_readable_file(self, tmp_path: Path) -> None:
        """A parseable file yields its walked AST nodes."""
        f = tmp_path / "sample.py"
        f.write_text("import src.common.config\n", encoding="utf-8")
        assert any(isinstance(n, ast.Import) for n in _walk_source(f))

    def test_returns_none_for_a_missing_file(self, tmp_path: Path) -> None:
        """An unreadable path is reported as None, not an empty walk."""
        assert _walk_source(tmp_path / "ghost.py") is None

    def test_returns_none_for_an_unparseable_file(self, tmp_path: Path) -> None:
        """A syntax error is reported as None, not an empty walk."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n    pass\n", encoding="utf-8")
        assert _walk_source(f) is None


class TestImportFromTargets:
    """_import_from_targets is the whole `ast.ImportFrom` arm split out of
    extract_first_party_imports so that function's own branch count stays under the Decision 43
    cyclomatic limit -- the same seam _walk_source already carves for the two try/except pairs.

    It returns candidate module names in first-appearance order; a None entry is a non-resolving
    submodule and is a no-op at the caller's _add() site.
    """

    @staticmethod
    def _pkg(tmp_path: Path) -> Path:
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "sub.py").write_text("", encoding="utf-8")
        return tmp_path

    @staticmethod
    def _node(source: str) -> ast.ImportFrom:
        return next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom))

    def test_relative_with_module_yields_the_resolved_submodule(self, tmp_path: Path) -> None:
        """`from .sub import X` resolves to the one submodule target."""
        root = self._pkg(tmp_path)
        f = root / "src" / "pkg" / "mod.py"
        node = self._node("from .sub import X\n")
        assert _import_from_targets(node, f, ("src",), root) == ["src.pkg.sub"]

    def test_relative_bare_yields_one_target_per_imported_name(self, tmp_path: Path) -> None:
        """`from . import a, b` yields the package-qualified name of each imported name."""
        root = self._pkg(tmp_path)
        f = root / "src" / "pkg" / "mod.py"
        node = self._node("from . import a, b\n")
        assert _import_from_targets(node, f, ("src",), root) == ["src.pkg.a", "src.pkg.b"]

    def test_relative_bare_above_the_root_yields_nothing(self, tmp_path: Path) -> None:
        """An unresolvable base (level escapes the root package) contributes no target at all."""
        root = self._pkg(tmp_path)
        f = root / "src" / "mod.py"
        node = self._node("from .. import sibling\n")
        assert _import_from_targets(node, f, ("src",), root) == []

    def test_absolute_first_party_yields_package_and_submodule(self, tmp_path: Path) -> None:
        """`from <pkg> import <sub>` yields BOTH edges -- the package body runs on the way."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        node = self._node("from src.pkg import sub\n")
        assert _import_from_targets(node, f, ("src",), root) == ["src.pkg", "src.pkg.sub"]

    def test_absolute_third_party_yields_nothing(self, tmp_path: Path) -> None:
        """A module matching no root contributes no target."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        node = self._node("from os.path import join\n")
        assert _import_from_targets(node, f, ("src",), root) == []

    def test_absolute_non_resolving_submodule_is_a_none_entry(self, tmp_path: Path) -> None:
        """A name that is a symbol, not a module on disk, is a None entry the caller drops."""
        root = self._pkg(tmp_path)
        f = root / "src" / "consumer.py"
        node = self._node("from src.pkg import VALUE\n")
        assert _import_from_targets(node, f, ("src",), root) == ["src.pkg", None]


class TestPreWalkedNodes:
    """The `_nodes` seam lets a caller that already read, parsed and walked the file
    (build_graph) skip a second read+parse+walk of the same bytes."""

    def test_pre_walked_nodes_are_used_instead_of_reading_the_file(self, tmp_path: Path) -> None:
        """No file is written: the walked nodes alone drive extraction."""
        absent = tmp_path / "never_written.py"
        nodes = list(ast.walk(ast.parse("import src.common.config\nfrom scripts.helper import do\n")))
        assert extract_first_party_imports(absent, _nodes=nodes) == ["src.common.config", "scripts.helper"]

    def test_pre_walked_nodes_yield_the_same_result_as_reading(self, tmp_path: Path) -> None:
        """Relative imports still resolve against file_path when the nodes are supplied."""
        pkg = tmp_path / "src" / "pkg"
        pkg.mkdir(parents=True)
        f = pkg / "mod.py"
        source = "from . import sibling\nfrom src.other import thing\n"
        f.write_text(source, encoding="utf-8")
        from_disk = extract_first_party_imports(f, _repo_root=tmp_path)
        from_nodes = extract_first_party_imports(f, _repo_root=tmp_path, _nodes=list(ast.walk(ast.parse(source))))
        assert from_nodes == from_disk
        assert "src.pkg.sibling" in from_nodes
