"""Unit tests for scripts/dependency_graph.py over a fixture module tree."""

import ast
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

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
reachable_from_roots = _dg.reachable_from_roots
to_export_dict = _dg.to_export_dict
check_export_freshness = _dg.check_export_freshness
KNOWN_UNSOUND = _dg.KNOWN_UNSOUND
_file_to_module = _dg._file_to_module
_has_entry_point = _dg._has_entry_point
_gather_roots = _dg._gather_roots


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


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


class TestBuildGraph:
    """Tests for build_graph() over the fixture tree."""

    def test_module_nodes_present(self, tmp_path: Path) -> None:
        """Nodes for all .py files in src/ scripts/ tests/ are present."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "src.pkg.module_a" in graph
        assert "src.pkg.module_b" in graph
        assert "scripts.helper" in graph
        assert "scripts.entrypoint" in graph
        assert "tests.test_stuff" in graph

    def test_absolute_import_edge(self, tmp_path: Path) -> None:
        """module_a -> scripts.helper edge from absolute 'from scripts.helper import ...'."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("src.pkg.module_a", "scripts.helper")

    def test_relative_import_edge(self, tmp_path: Path) -> None:
        """module_b -> src.pkg.module_a edge from relative 'from . import module_a'."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("src.pkg.module_b", "src.pkg.module_a")

    def test_scripts_star_edge(self, tmp_path: Path) -> None:
        """entrypoint -> scripts.helper edge from 'from scripts.helper import ...'."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("scripts.entrypoint", "scripts.helper")

    def test_no_self_edges(self, tmp_path: Path) -> None:
        """No module has an edge to itself."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        for u, v in graph.edges():
            assert u != v

    def test_kind_attribute(self, tmp_path: Path) -> None:
        """All nodes added by build_graph have kind='module' in module granularity."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        for n, data in graph.nodes(data=True):
            assert data.get("kind") == "module", f"{n} has kind={data.get('kind')!r}"


class TestRoots:
    """Tests for root set assembly."""

    def test_entrypoint_is_root(self, tmp_path: Path) -> None:
        """scripts.entrypoint has def main() -> is_root=True."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.entrypoint" in roots(graph)

    def test_test_file_is_root(self, tmp_path: Path) -> None:
        """tests/test_stuff.py is a root (pytest surface)."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "tests.test_stuff" in roots(graph)

    def test_helper_not_root(self, tmp_path: Path) -> None:
        """scripts.helper has no entry point -> not a root."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.helper" not in roots(graph)

    def test_gather_roots_requires_caller_supplied_entry_points(self, tmp_path: Path) -> None:
        """The dead self-derivation branch is gone -- the sole caller (build_graph) always hands
        over the entry points from its single walk, so the argument is required and is honoured
        verbatim; _gather_roots never re-walks src/ and scripts/ to re-derive them."""
        root = _make_rich_fixture(tmp_path)
        with pytest.raises(TypeError):
            _gather_roots(root)
        assert {"scripts.consumer", "tests.test_stuff"} <= _gather_roots(root, frozenset({"scripts.consumer"}))
        assert "scripts.consumer" not in _gather_roots(root, frozenset())


class TestReverseDeps:
    """Tests for reverse_deps()."""

    def test_reverse_deps_of_helper(self, tmp_path: Path) -> None:
        """Both module_a and entrypoint import helper."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        rdeps = reverse_deps(graph, "scripts.helper")
        assert "src.pkg.module_a" in rdeps
        assert "scripts.entrypoint" in rdeps
        assert rdeps == sorted(rdeps)

    def test_reverse_deps_of_unknown_module(self, tmp_path: Path) -> None:
        """Unknown module returns empty list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert reverse_deps(graph, "nonexistent.module") == []


class TestForwardClosure:
    """Tests for forward_closure()."""

    def test_forward_closure_of_entrypoint(self, tmp_path: Path) -> None:
        """entrypoint -> helper is in its forward closure."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        closure = forward_closure(graph, "scripts.entrypoint")
        assert "scripts.helper" in closure
        assert closure == sorted(closure)

    def test_forward_closure_of_module_b(self, tmp_path: Path) -> None:
        """module_b -> module_a -> helper: transitive closure includes helper."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        closure = forward_closure(graph, "src.pkg.module_b")
        assert "src.pkg.module_a" in closure
        assert "scripts.helper" in closure

    def test_forward_closure_of_leaf(self, tmp_path: Path) -> None:
        """Leaf node with no outgoing edges has empty closure."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert forward_closure(graph, "scripts.helper") == []

    def test_forward_closure_unknown(self, tmp_path: Path) -> None:
        """Unknown module returns empty list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert forward_closure(graph, "nonexistent") == []


class TestReachableFromRoots:
    """Tests for reachable_from_roots()."""

    def test_helper_reachable_via_entrypoint_root(self, tmp_path: Path) -> None:
        """scripts.helper is reachable because scripts.entrypoint (a root) imports it."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert reachable_from_roots(graph, "scripts.helper") is True

    def test_module_a_reachable_via_module_b_chain(self, tmp_path: Path) -> None:
        """src.pkg.module_a is reachable transitively: caller -> module_b -> module_a."""
        root = _make_fixture(tmp_path)
        (tmp_path / "scripts" / "caller.py").write_text(
            "from src.pkg.module_b import something\n\ndef main():\n    pass\n", encoding="utf-8"
        )
        graph = build_graph(repo_root=root)
        assert graph.has_edge("scripts.caller", "src.pkg.module_b"), "direct edge must exist"
        assert reachable_from_roots(graph, "src.pkg.module_a") is True

    def test_root_itself_is_reachable(self, tmp_path: Path) -> None:
        """A root module is trivially reachable from the root set."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        root_set = roots(graph)
        for r in root_set:
            assert reachable_from_roots(graph, r) is True

    def test_unknown_module_not_reachable(self, tmp_path: Path) -> None:
        """A module not in the graph is not reachable."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert reachable_from_roots(graph, "nonexistent.module") is False


class TestExportDeterminism:
    """Tests for to_export_dict() determinism and structure."""

    def test_required_top_level_keys(self, tmp_path: Path) -> None:
        """Export dict has edges, metadata, nodes, roots, symbol_nodes keys."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert "edges" in exported
        assert "metadata" in exported
        assert "nodes" in exported
        assert "roots" in exported
        assert "symbol_nodes" in exported

    def test_known_unsound_in_export(self, tmp_path: Path) -> None:
        """Export metadata embeds the KNOWN_UNSOUND list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert "known_unsound" in exported["metadata"]
        assert exported["metadata"]["known_unsound"] is KNOWN_UNSOUND

    def test_nodes_sorted(self, tmp_path: Path) -> None:
        """nodes list is sorted."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert exported["nodes"] == sorted(exported["nodes"])

    def test_edges_sorted(self, tmp_path: Path) -> None:
        """edges list is sorted by (from, to)."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        edge_tuples = [(e["from"], e["to"]) for e in exported["edges"]]
        assert edge_tuples == sorted(edge_tuples)

    def test_json_byte_identical_across_runs(self, tmp_path: Path) -> None:
        """Two serializations of the same graph produce identical JSON bytes."""
        root = _make_fixture(tmp_path)
        graph1 = build_graph(repo_root=root)
        graph2 = build_graph(repo_root=root)
        j1 = json.dumps(to_export_dict(graph1), indent=2, sort_keys=True)
        j2 = json.dumps(to_export_dict(graph2), indent=2, sort_keys=True)
        assert j1 == j2

    def test_symbol_nodes_empty_in_module_granularity(self, tmp_path: Path) -> None:
        """symbol_nodes is empty when granularity is module (default)."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert exported["symbol_nodes"] == []


class TestSymbolGranularity:
    """Tests for symbol-level enrichment layer."""

    def test_symbol_nodes_added(self, tmp_path: Path) -> None:
        """Symbol granularity adds function/class nodes for top-level defs."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        symbol_nodes = [n for n, d in graph.nodes(data=True) if d.get("kind") == "symbol"]
        assert len(symbol_nodes) > 0

    def test_entrypoint_main_symbol_exists(self, tmp_path: Path) -> None:
        """scripts.entrypoint.main is a symbol node."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        assert "scripts.entrypoint.main" in graph

    def test_helper_do_stuff_symbol_exists(self, tmp_path: Path) -> None:
        """scripts.helper.do_stuff is a symbol node."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        assert "scripts.helper.do_stuff" in graph

    def test_export_symbol_nodes_populated(self, tmp_path: Path) -> None:
        """Export with symbol granularity populates symbol_nodes list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        exported = to_export_dict(graph)
        assert len(exported["symbol_nodes"]) > 0
        assert exported["symbol_nodes"] == sorted(exported["symbol_nodes"])


class TestKnownUnsound:
    """Tests for KNOWN_UNSOUND enumeration."""

    def test_known_unsound_has_four_entries(self) -> None:
        """KNOWN_UNSOUND enumerates exactly 4 blind spots."""
        assert len(KNOWN_UNSOUND) == 4

    def test_getattr_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert "getattr" in patterns

    def test_string_keyed_dispatch_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert "string-keyed dispatch" in patterns

    def test_importlib_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert "importlib.spec_from_file_location" in patterns

    def test_schedule_yaml_indirection_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert any("schedule.yaml" in p for p in patterns)


class TestFacadeInitPackageNode:
    """Soundness patch (i), Decision affected-set-selection: __init__.py facade re-exports
    (Decision 124) are graph nodes, so an importer of the PACKAGE (not a specific submodule)
    keeps its edge instead of silently dropping it."""

    def _make_facade_fixture(self, tmp_path: Path) -> Path:
        (tmp_path / "scripts" / "pkg").mkdir(parents=True)
        (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "scripts" / "pkg" / "__init__.py").write_text("from scripts.pkg.impl import helper\n", encoding="utf-8")
        (tmp_path / "scripts" / "pkg" / "impl.py").write_text("def helper():\n    pass\n", encoding="utf-8")
        (tmp_path / "scripts" / "consumer.py").write_text(
            "from scripts.pkg import helper\n\ndef main():\n    helper()\n", encoding="utf-8"
        )
        return tmp_path

    def test_package_init_is_a_graph_node(self, tmp_path: Path) -> None:
        root = self._make_facade_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.pkg" in graph

    def test_facade_reexport_edge_from_init_to_impl(self, tmp_path: Path) -> None:
        """The facade's own re-export (`from scripts.pkg.impl import helper` inside __init__.py)
        produces a real graph edge scripts.pkg -> scripts.pkg.impl."""
        root = self._make_facade_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("scripts.pkg", "scripts.pkg.impl")

    def test_consumer_of_package_facade_edge_not_dropped(self, tmp_path: Path) -> None:
        """`from scripts.pkg import helper` (importing the PACKAGE) must land an edge on the
        scripts.pkg node -- previously __init__.py was skipped entirely so this edge was lost."""
        root = self._make_facade_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("scripts.consumer", "scripts.pkg")

    def test_consumer_is_reverse_dep_of_package(self, tmp_path: Path) -> None:
        root = self._make_facade_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.consumer" in reverse_deps(graph, "scripts.pkg")

    def test_init_node_has_module_kind(self, tmp_path: Path) -> None:
        root = self._make_facade_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.nodes["scripts.pkg"].get("kind") == "module"


class TestPatchStringModuleEdges:
    """Soundness patch (ii), Decision affected-set-selection: a string-constant module path
    (e.g. a mock.patch("scripts.x.y") target) is unioned into the graph as an edge, even though
    no `import` statement exists."""

    def _make_patch_string_fixture(self, tmp_path: Path) -> Path:
        (tmp_path / "scripts").mkdir(parents=True)
        (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "scripts" / "target_module.py").write_text("def run():\n    pass\n", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "tests" / "test_target_module.py").write_text(
            'from unittest.mock import patch\n\ndef test_x():\n    with patch("scripts.target_module.run"):\n        pass\n',
            encoding="utf-8",
        )
        return tmp_path

    def test_patch_string_edge_added(self, tmp_path: Path) -> None:
        root = self._make_patch_string_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("tests.test_target_module", "scripts.target_module")

    def test_patch_string_resolves_module_attribute_to_module_node(self, tmp_path: Path) -> None:
        """The mock target string names an ATTRIBUTE (scripts.target_module.run), not the bare
        module -- the edge must resolve to the longest existing module-node prefix."""
        root = self._make_patch_string_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.target_module.run" not in graph
        assert graph.has_edge("tests.test_target_module", "scripts.target_module")

    def test_patch_string_target_is_reverse_dep(self, tmp_path: Path) -> None:
        root = self._make_patch_string_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "tests.test_target_module" in reverse_deps(graph, "scripts.target_module")

    def test_non_matching_string_constant_adds_no_edge(self, tmp_path: Path) -> None:
        """An arbitrary string constant that doesn't match the src|scripts dotted-path shape
        must not be treated as a patch-string target."""
        root = self._make_patch_string_fixture(tmp_path)
        (root / "scripts" / "consumer.py").write_text('X = "not.a.module.path.at.all.blah"\n', encoding="utf-8")
        graph = build_graph(repo_root=root)
        assert graph.out_degree("scripts.consumer") == 0

    def test_unresolvable_dotted_string_adds_no_edge(self, tmp_path: Path) -> None:
        """A string matching the src|scripts shape but naming no real module/attribute in the
        graph resolves to nothing (no phantom edge)."""
        root = self._make_patch_string_fixture(tmp_path)
        (root / "scripts" / "consumer.py").write_text('X = "scripts.nonexistent_module.some_attr"\n', encoding="utf-8")
        graph = build_graph(repo_root=root)
        assert graph.out_degree("scripts.consumer") == 0


class TestCheckExportFreshness:
    """Tests for check_export_freshness()."""

    def test_no_op_when_no_committed_export(self, tmp_path: Path) -> None:
        """Freshness check is a no-op when docs/dependency-graph.json does not exist."""
        export_path = tmp_path / "docs" / "dependency-graph.json"
        with patch.object(_dg, "_EXPORT_PATH", export_path):
            failed: list[str] = []
            check_export_freshness(failed)
        assert not failed

    def test_fails_on_drift(self, tmp_path: Path) -> None:
        """Freshness check fails when committed export content differs from current graph."""
        export_path = tmp_path / "docs" / "dependency-graph.json"
        export_path.parent.mkdir(parents=True)
        stale_content = {"nodes": ["stale.module"], "edges": [], "roots": [], "metadata": {}, "symbol_nodes": []}
        export_path.write_text(json.dumps(stale_content), encoding="utf-8")
        with patch.object(_dg, "_EXPORT_PATH", export_path):
            failed: list[str] = []
            check_export_freshness(failed)
        assert len(failed) == 1
        assert "stale" in failed[0].lower() or "drift" in failed[0].lower() or "dependency graph" in failed[0].lower()

    def test_passes_when_export_matches_current(self, tmp_path: Path) -> None:
        """Freshness check passes when the committed export matches the current graph."""
        root = _make_fixture(tmp_path / "repo")
        export_path = tmp_path / "dependency-graph.json"
        with patch.object(_dg, "_REPO_ROOT", root), patch.object(_dg, "_EXPORT_PATH", export_path):
            graph = build_graph(repo_root=root)
            current = to_export_dict(graph)
            export_path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            failed: list[str] = []
            check_export_freshness(failed)
        assert not failed


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
