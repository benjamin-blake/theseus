"""Unit tests for scripts/dependency_graph.py: single-parse-per-file behavior, the in-process
memoization boundary (Decision 135), the from-package-import-submodule edge, the golden
rich-fixture graph-shape pin, and the edge-kind tagging no-op pins. Split out of
tests/test_dependency_graph.py (SLOC headroom)."""

import ast
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import scripts.extract_imports  # noqa: F401  warm the lazy import so ast.parse patches are exact

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "dependency_graph.py"
_spec = importlib.util.spec_from_file_location("dependency_graph", _SCRIPT_PATH)
_dg = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_dg)  # type: ignore[union-attr]
sys.modules["dependency_graph"] = _dg

build_graph = _dg.build_graph
roots = _dg.roots
reverse_deps = _dg.reverse_deps
forward_closure = _dg.forward_closure
to_export_dict = _dg.to_export_dict


def _make_fixture(tmp_path: Path) -> Path:
    """Create a minimal fixture module tree with known edges.

    Layout:
      src/__init__.py
      src/pkg/__init__.py
      src/pkg/module_a.py  -- imports scripts.helper (absolute)
      src/pkg/module_b.py  -- imports src.pkg.module_a via relative (from . import module_a)
      scripts/__init__.py
      scripts/helper.py    -- no first-party imports
      scripts/entrypoint.py -- def main(); imports scripts.helper
      tests/test_stuff.py  -- pytest test file (for root detection)
    """
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "module_a.py").write_text("from scripts.helper import do_stuff\n", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "module_b.py").write_text("from . import module_a\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "helper.py").write_text("def do_stuff():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "entrypoint.py").write_text(
        "from scripts.helper import do_stuff\n\ndef main():\n    do_stuff()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stuff.py").write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    return tmp_path


def _make_rich_fixture(tmp_path: Path) -> Path:
    """_make_fixture plus a package facade, a patch-string test, a __main__ entry point and an
    unparseable file: one tree exercising every edge- and root-producing pass."""
    root = _make_fixture(tmp_path)
    (root / "src" / "pkg" / "impl.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    (root / "src" / "pkg" / "__init__.py").write_text("from src.pkg.impl import helper\n", encoding="utf-8")
    (root / "src" / "broken.py").write_text("def (:\n", encoding="utf-8")
    (root / "scripts" / "consumer.py").write_text(
        'from src.pkg import helper\n\nif __name__ == "__main__":\n    helper()\n', encoding="utf-8"
    )
    (root / "tests" / "test_patching.py").write_text(
        'from unittest.mock import patch\n\ndef test_x():\n    with patch("scripts.helper.do_stuff"):\n        pass\n',
        encoding="utf-8",
    )
    return root


_RICH_NODES = (
    "scripts scripts.consumer scripts.entrypoint scripts.helper src src.broken src.pkg "
    "src.pkg.impl src.pkg.module_a src.pkg.module_b tests.test_patching tests.test_stuff"
).split()
_RICH_EDGES = [
    tuple(edge.split(">"))
    for edge in (
        "scripts.consumer>src.pkg scripts.entrypoint>scripts.helper src.pkg>src.pkg.impl "
        "src.pkg.module_a>scripts.helper src.pkg.module_b>src.pkg.module_a tests.test_patching>scripts.helper"
    ).split()
]
_RICH_SYMBOL_NODES = (
    "scripts.entrypoint.main scripts.helper.do_stuff src.pkg.impl.helper "
    "tests.test_patching.test_x tests.test_stuff.test_placeholder"
).split()


class TestGraphShapeIsPinned:
    """Golden pin on the whole fixture-tree graph shape: the single-parse rewrite must not move
    a single node, edge or entry-point tag."""

    def test_module_nodes_and_edges_exact(self, tmp_path: Path) -> None:
        exported = to_export_dict(build_graph(repo_root=_make_rich_fixture(tmp_path)))
        assert exported["nodes"] == _RICH_NODES
        assert [(e["from"], e["to"]) for e in exported["edges"]] == _RICH_EDGES

    def test_entry_point_roots_exact(self, tmp_path: Path) -> None:
        """Membership in both directions, not equality: the fixture's package __init__ nodes are
        also tagged from the real repo's Lambda-manifest includes, which this must not couple to."""
        root_set = set(to_export_dict(build_graph(repo_root=_make_rich_fixture(tmp_path)))["roots"])
        assert {"scripts.consumer", "scripts.entrypoint", "tests.test_patching", "tests.test_stuff"} <= root_set
        assert not root_set & {"scripts.helper", "src.broken", "src.pkg.impl", "src.pkg.module_a", "src.pkg.module_b"}

    def test_symbol_granularity_shape_exact(self, tmp_path: Path) -> None:
        exported = to_export_dict(build_graph(repo_root=_make_rich_fixture(tmp_path), granularity="symbol"))
        assert exported["symbol_nodes"] == _RICH_SYMBOL_NODES
        expected = sorted(_RICH_EDGES + [("scripts.entrypoint.main", "scripts.helper")])
        assert [(e["from"], e["to"]) for e in exported["edges"]] == expected


class TestDefaultTraversalsUnchangedByEdgeKindTagging:
    """Decision 169's contract: the manifest driver edges must remain IN the graph, so every
    DEFAULT (unfiltered) accessor still crosses them after edge-kind tagging. Only a consumer
    that explicitly filters (dependency_graph.import_subgraph) sees a difference."""

    def test_forward_closure_still_crosses_a_patch_string_edge(self, tmp_path: Path) -> None:
        graph = build_graph(repo_root=_make_rich_fixture(tmp_path))
        assert "scripts.helper" in forward_closure(graph, "tests.test_patching")

    def test_reverse_deps_still_report_a_patch_string_predecessor(self, tmp_path: Path) -> None:
        graph = build_graph(repo_root=_make_rich_fixture(tmp_path))
        assert "tests.test_patching" in reverse_deps(graph, "scripts.helper")

    def test_export_dict_is_unaffected_by_edge_kinds(self, tmp_path: Path) -> None:
        """to_export_dict emits {"from","to"} only -- tagging must not change the committed
        export shape that check_export_freshness compares byte-for-byte."""
        exported = to_export_dict(build_graph(repo_root=_make_rich_fixture(tmp_path)))
        assert all(set(edge) == {"from", "to"} for edge in exported["edges"])


def _parsed_filenames(parse_mock) -> list[str]:
    return [str(call.kwargs.get("filename")) for call in parse_mock.call_args_list]


class TestSingleParsePerFile:
    """Import extraction, patch-string extraction and entry-point detection each used to
    re-read, re-parse and re-walk the same file; build_graph now does each once."""

    def test_ast_parse_called_at_most_once_per_file(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        with patch("ast.parse", side_effect=ast.parse) as parse:
            build_graph(repo_root=root)
        names = _parsed_filenames(parse)
        assert names, "build_graph parsed nothing -- the mock is not wired to the real call"
        assert sorted(names) == sorted(set(names))

    def test_ast_walk_called_once_per_parsed_file(self, tmp_path: Path) -> None:
        """The import, patch-string and entry-point passes share one materialized walk."""
        root = _make_rich_fixture(tmp_path)
        with patch("ast.parse", side_effect=ast.parse) as parse, patch("ast.walk", side_effect=ast.walk) as walk:
            build_graph(repo_root=root)
        assert walk.call_count == len(_parsed_filenames(parse)) - 1, "src/broken.py parses but never walks"


class TestInProcessGraphMemo:
    """Decision 135's KG.13-boundary paragraph ("LIVE, CACHELESS ... NOT a selection cache"):
    single-interpreter reuse is allowed; nothing may persist to disk, and no caller may observe
    another caller's mutation."""

    def test_second_call_reuses_the_graph_without_reparsing(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        first = build_graph(repo_root=root)
        with patch("ast.parse", side_effect=ast.parse) as parse:
            second = build_graph(repo_root=root)
        assert parse.call_count == 0
        assert sorted(second.nodes) == sorted(first.nodes)
        assert sorted(second.edges) == sorted(first.edges)
        assert dict(second.nodes(data=True)) == dict(first.nodes(data=True))

    def test_callers_get_independent_graph_objects(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        first = build_graph(repo_root=root)
        first.add_node("mutated.by.a.caller")
        first.nodes["scripts.helper"]["is_root"] = True
        second = build_graph(repo_root=root)
        assert "mutated.by.a.caller" not in second
        assert "scripts.helper" not in roots(second)

    def test_nothing_is_persisted_to_disk(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        build_graph(repo_root=root)
        build_graph(repo_root=root)
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before

    def test_clear_graph_cache_forces_a_rebuild(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        build_graph(repo_root=root)
        _dg.clear_graph_cache()
        with patch("ast.parse", side_effect=ast.parse) as parse:
            build_graph(repo_root=root)
        assert parse.call_count > 0

    def test_granularity_is_part_of_the_memo_key(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        build_graph(repo_root=root)
        symbol_graph = build_graph(repo_root=root, granularity="symbol")
        assert "scripts.entrypoint.main" in symbol_graph


class TestFromPackageImportSubmoduleEdge:
    """`from <pkg> import <submodule>` lands on the submodule and keeps the package edge."""

    def test_submodule_import_is_a_reverse_dep_of_both_submodule_and_package(self, tmp_path: Path) -> None:
        root = _make_rich_fixture(tmp_path)
        (root / "scripts" / "importer.py").write_text("from src.pkg import impl\n", encoding="utf-8")
        graph = build_graph(repo_root=root)
        assert reverse_deps(graph, "src.pkg.impl") == ["scripts.importer", "src.pkg"]
        assert reverse_deps(graph, "src.pkg") == ["scripts.consumer", "scripts.importer"]
