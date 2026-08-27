# complexity-waiver: decision-43
"""First-party import-graph oracle using ast + networkx (Decision 80).

Compute-on-demand; no committed output file by default.
Stable API: build_graph, clear_graph_cache, roots, reverse_deps, forward_closure,
reachable_from_roots, to_export_dict, check_export_freshness, edges_of_kind, import_subgraph.
CLI: --reverse-deps, --forward-closure, --reachable, --granularity, --export, --blind-spots.

Every edge carries a `kind` attribute (see EDGE_KIND_*): a real `import`/`from ... import`
statement is kind="import"; a bare string literal naming a first-party module is
kind="patch_string" (both a mock.patch target and Decision 169's contractual manifest
driver->check edge); a symbol-granularity call edge is kind="call". Tagging is additive -- the
patch_string edges STAY in the graph, so every default traversal (forward_closure, reverse_deps,
reachable_from_roots, to_export_dict) is byte-identical to the untagged behaviour. Only a
consumer that explicitly filters -- import_subgraph(), for a code-level-only closure -- sees a
difference.
"""

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx

_REPO_ROOT = Path(__file__).parent.parent
_SEARCH_DIRS: tuple[str, ...] = ("src", "scripts", "tests")
_FIRST_PARTY_ROOTS: tuple[str, ...] = ("src", "scripts")
_EXPORT_PATH = _REPO_ROOT / "docs" / "dependency-graph.json"
_CLI_PATTERN = re.compile(r"-m\s+(scripts(?:\.\w+)+)")
# Soundness patch (ii), Decision affected-set-selection: a string literal naming a first-party
# module or module.attribute path (e.g. a mock.patch("scripts.checks._common.run") target).
# Matched against the WHOLE string; the module edge itself resolves to the longest graph-node
# prefix of the match (see _patch_string_module_targets), so both a bare module-path string and
# a module.attribute string resolve to their owning module node.
_PATCH_STRING_RE = re.compile(r"^(src|scripts)(\.\w+)+$")

# Edge-kind vocabulary (see the module docstring). An edge is tagged exactly once, at the pass
# that first creates it, and a real import always WINS over a same-endpoint patch string -- the
# import pass runs first for each file and the string pass never overwrites an existing edge.
EDGE_KIND_IMPORT = "import"
EDGE_KIND_PATCH_STRING = "patch_string"
EDGE_KIND_CALL = "call"

KNOWN_UNSOUND: list[dict[str, str]] = [
    {
        "pattern": "getattr",
        "description": "Dynamic attribute access; the resolved attribute is invisible to ast-based analysis.",
    },
    {
        "pattern": "string-keyed dispatch",
        "description": "Dict-keyed handler dispatch (e.g. HANDLERS[name]()) cannot be traced statically.",
    },
    {
        "pattern": "importlib.spec_from_file_location",
        "description": "Dynamic module loading via importlib; the target module is invisible to ast.",
    },
    {
        "pattern": "schedule.yaml -> prompt_path -> handler indirection",
        "description": (
            "Scheduled-agent dispatch via .github/agents/schedule.yaml resolves handler modules at runtime; "
            "no static import edge exists between the dispatcher and the scheduled module."
        ),
    },
]


def _file_to_module(py_file: Path, repo_root: Path = _REPO_ROOT) -> str | None:
    """Convert a .py path to a dotted first-party module name, or None if outside search dirs."""
    for search_dir in _SEARCH_DIRS:
        base = repo_root / search_dir
        try:
            rel = py_file.relative_to(base)
        except ValueError:
            continue
        parts = [search_dir] + list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) if parts else None
    return None


def _has_entry_point(nodes: Iterable[ast.AST]) -> bool:
    """True if the walked module nodes declare if __name__ == '__main__' or def main()."""
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            return True
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            left = node.test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                for comp in node.test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        return True
    return False


def _walk_file(py_file: Path) -> list[ast.AST] | None:
    """Read, parse and walk py_file exactly once; None when unreadable or unparseable.

    Every per-file pass in build_graph (imports, patch-string constants, entry points) consumes
    this one materialized node list instead of re-reading and re-walking the file.
    """
    try:
        return list(ast.walk(ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))))
    except (OSError, SyntaxError):
        return None


def _gather_roots(repo_root: Path, entry_point_modules: frozenset[str]) -> frozenset[str]:
    """Assemble declared root/boundary module set (Decision 79 -- no transitive resolution).

    Sources: Lambda manifest handlers+includes (all statuses), modules with __main__/main(),
    pytest test files, and -m scripts.X CLI surfaces in .github/workflows + .claude/.
    entry_point_modules is REQUIRED and supplies the __main__/main() set already computed from
    the caller's single parse of each file (_build_graph is the sole caller) -- this function
    never re-walks src/ and scripts/ to re-derive it.
    """
    found: set[str] = set()

    try:
        from scripts.lambda_manifest import load_all  # noqa: PLC0415

        for manifest in load_all().values():
            for path_str in manifest.handlers + manifest.includes:
                p = repo_root / path_str
                if p.is_file() and p.suffix == ".py":
                    mod = _file_to_module(p, repo_root)
                    if mod:
                        found.add(mod)
    except Exception:  # noqa: BLE001
        pass

    found |= entry_point_modules

    tests_dir = repo_root / "tests"
    if tests_dir.is_dir():
        for tf in sorted(tests_dir.glob("test_*.py")):
            mod = _file_to_module(tf, repo_root)
            if mod:
                found.add(mod)

    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for wf in sorted(workflows_dir.glob("*.yml")):
            try:
                for m in _CLI_PATTERN.finditer(wf.read_text(encoding="utf-8")):
                    found.add(m.group(1))
            except OSError:
                pass

    claude_dir = repo_root / ".claude"
    if claude_dir.is_dir():
        for md in sorted(claude_dir.rglob("*.md")):
            try:
                for m in _CLI_PATTERN.finditer(md.read_text(encoding="utf-8")):
                    found.add(m.group(1))
            except OSError:
                pass

    return frozenset(found)


def _imports_for_file(py_file: Path, repo_root: Path, nodes: list[ast.AST] | None = None) -> list[str]:
    """Return first-party import names for py_file using scripts.extract_imports."""
    try:
        from scripts.extract_imports import extract_first_party_imports  # noqa: PLC0415

        return extract_first_party_imports(py_file, roots=_FIRST_PARTY_ROOTS, _repo_root=repo_root, _nodes=nodes)
    except ImportError:
        return []


def _enrich_symbol_layer(graph: nx.DiGraph, py_file: Path, module: str) -> None:
    """Add function/class-level symbol nodes and statically-resolvable cross-module call edges."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (OSError, SyntaxError):
        return

    imported_from: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                imported_from[local] = node.module

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym = f"{module}.{stmt.name}"
            if sym not in graph:
                graph.add_node(sym, kind="symbol")
            for child in ast.walk(stmt):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    src_mod = imported_from.get(child.func.id)
                    if src_mod and src_mod in graph and not graph.has_edge(sym, src_mod):
                        graph.add_edge(sym, src_mod, kind=EDGE_KIND_CALL)
        elif isinstance(stmt, ast.ClassDef):
            sym = f"{module}.{stmt.name}"
            if sym not in graph:
                graph.add_node(sym, kind="symbol")


def _patch_string_module_targets(nodes: Iterable[ast.AST], graph: nx.DiGraph) -> list[str]:
    """Soundness patch (ii), Decision affected-set-selection: AST pass over ast.Constant string
    literals matching _PATCH_STRING_RE, resolved to the LONGEST existing graph-node module
    prefix of each match.

    Handles both a bare module-path string (e.g. "scripts.checks.deps.affected_tests") and a
    module.attribute mock-patch target (e.g. "scripts.checks._common.run", where only
    "scripts.checks._common" is a real module node) -- the longest-prefix walk resolves either
    shape to its owning module without requiring the caller to know which shape a given string
    is. A candidate that resolves to no known module (e.g. an unrelated dotted string that only
    coincidentally matches the pattern) contributes no edge.

    `nodes` is the caller's single materialized walk of the file's AST (see _walk_file).
    """
    targets: list[str] = []
    for node in nodes:
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        value = node.value
        if not _PATCH_STRING_RE.match(value):
            continue
        parts = value.split(".")
        for end in range(len(parts), 1, -1):
            candidate = ".".join(parts[:end])
            if candidate in graph:
                targets.append(candidate)
                break
    return targets


def _build_graph(root: Path, granularity: str) -> nx.DiGraph:
    """Construct the graph for an already-resolved repo root (see build_graph for semantics)."""
    graph: nx.DiGraph = nx.DiGraph()

    py_files: list[tuple[Path, str]] = []
    for search_dir in _SEARCH_DIRS:
        sdir = root / search_dir
        if not sdir.is_dir():
            continue
        for py_file in sorted(sdir.rglob("*.py")):
            mod = _file_to_module(py_file, root)
            if mod:
                graph.add_node(mod, kind="module")
                py_files.append((py_file, mod))

    entry_points: set[str] = set()
    for py_file, mod in py_files:
        nodes = _walk_file(py_file)
        if nodes is None:
            continue
        for imported_mod in _imports_for_file(py_file, root, nodes):
            if imported_mod in graph and imported_mod != mod:
                graph.add_edge(mod, imported_mod, kind=EDGE_KIND_IMPORT)
        # Soundness patch (ii): union string-constant module edges (mock.patch targets etc.).
        # `not has_edge` keeps an already-tagged import edge as kind="import" -- a module that
        # both imports X and names "X.attr" in a string must not lose X from the import-only view.
        for target in _patch_string_module_targets(nodes, graph):
            if target != mod and not graph.has_edge(mod, target):
                graph.add_edge(mod, target, kind=EDGE_KIND_PATCH_STRING)
        is_first_party = mod.partition(".")[0] in _FIRST_PARTY_ROOTS
        if is_first_party and py_file.name != "__init__.py" and _has_entry_point(nodes):
            entry_points.add(mod)

    for mod in _gather_roots(root, frozenset(entry_points)):
        if mod in graph:
            graph.nodes[mod]["is_root"] = True

    if granularity == "symbol":
        for py_file, mod in py_files:
            _enrich_symbol_layer(graph, py_file, mod)

    return graph


@lru_cache(maxsize=8)
def _memoized_graph(root_key: str, granularity: str) -> nx.DiGraph:
    """Single-interpreter memo of _build_graph.

    Decision 135's KG.13-boundary paragraph is the governing clause: the affected-set derivation
    must stay LIVE and CACHELESS -- "explicitly NOT a selection cache and NOT a coverage cache".
    This memo is process-local, dies with the interpreter, and touches no disk, so it does not
    engage that boundary.
    """
    return _build_graph(Path(root_key), granularity)


def clear_graph_cache() -> None:
    """Drop the in-process memo. Call after mutating .py files inside a live interpreter."""
    _memoized_graph.cache_clear()


def build_graph(
    repo_root: Path | None = None,
    granularity: str = "module",
) -> nx.DiGraph:
    """Build and return the first-party import graph.

    Nodes: dotted module names with kind='module'. Edges: A->B means A imports B.
    Root nodes are tagged graph.nodes[mod]['is_root'] = True.
    granularity='symbol' adds function/class nodes (kind='symbol') and call edges.

    Soundness patch (i), Decision affected-set-selection: package __init__.py files ARE
    included as graph nodes (dotted package name, via _file_to_module's existing __init__
    stripping) so a facade re-export (Decision 124: `__init__.py` re-exporting a submodule's
    public surface) does not silently drop the edge from an importer of the package to the
    package node itself -- previously __init__.py was skipped entirely, so
    `from scripts.checks.deps import X` (importing the PACKAGE) had no node to land on and the
    edge was dropped.

    Each file is parsed exactly once and the AST is shared by the import, patch-string and
    entry-point passes. Repeat calls within one interpreter are served from an in-process memo
    keyed on (resolved repo root, granularity) and always hand back an independent copy, so a
    caller mutating its graph cannot corrupt another's; see clear_graph_cache().
    """
    root = repo_root if repo_root is not None else _REPO_ROOT
    return _memoized_graph(str(Path(root).resolve()), granularity).copy()


def roots(graph: nx.DiGraph) -> frozenset[str]:
    """Return the set of root/boundary module nodes tagged in the graph."""
    return frozenset(n for n, d in graph.nodes(data=True) if d.get("is_root"))


def reverse_deps(graph: nx.DiGraph, module: str) -> list[str]:
    """Return sorted list of modules that directly import module."""
    if module not in graph:
        return []
    return sorted(graph.predecessors(module))


def edges_of_kind(graph: nx.DiGraph, kind: str) -> list[tuple[str, str]]:
    """Sorted list of the graph's edges whose `kind` attribute equals `kind` (see EDGE_KIND_*)."""
    return sorted((u, v) for u, v, data in graph.edges(data=True) if data.get("kind") == kind)


def import_subgraph(graph: nx.DiGraph) -> nx.DiGraph:
    """A read-only VIEW of `graph` restricted to kind="import" edges; every node is retained.

    The code-level closure accessor. Decision 169's manifest bare-string-literal driver edges are
    deliberately in the graph -- they are what makes a manifest edit select its own check -- but
    they collapse every registered check into one 148-module strongly-connected component, so a
    consumer asking "what code does this module actually depend on?" must exclude them. This is a
    networkx subgraph_view: O(1) to construct, sharing the memoized graph's storage, so a caller
    never pays a second build_graph.
    """
    return nx.subgraph_view(graph, filter_edge=lambda u, v: graph.edges[u, v].get("kind") == EDGE_KIND_IMPORT)


def forward_closure(graph: nx.DiGraph, module: str) -> list[str]:
    """Return sorted list of all transitive imports of module (excluding itself)."""
    if module not in graph:
        return []
    return sorted(nx.descendants(graph, module))


def reachable_from_roots(graph: nx.DiGraph, module: str) -> bool:
    """True if module is reachable from any declared root node in the graph."""
    if module not in graph:
        return False
    root_set = roots(graph)
    if module in root_set:
        return True
    return any(r in graph and nx.has_path(graph, r, module) for r in root_set)


def to_export_dict(graph: nx.DiGraph) -> dict[str, Any]:
    """Return a deterministic JSON-serializable representation of the graph."""
    module_nodes = sorted(n for n, d in graph.nodes(data=True) if d.get("kind") == "module")
    symbol_nodes = sorted(n for n, d in graph.nodes(data=True) if d.get("kind") == "symbol")
    edges = [{"from": u, "to": v} for u, v in sorted(graph.edges())]
    return {
        "edges": edges,
        "metadata": {
            "generated_by": "scripts.dependency_graph",
            "known_unsound": KNOWN_UNSOUND,
        },
        "nodes": module_nodes,
        "roots": sorted(roots(graph)),
        "symbol_nodes": symbol_nodes,
    }


def check_export_freshness(failed: list[str], repo_root: Path | None = None) -> None:
    """No-op when no committed export exists; fails if the committed export drifts from current.

    Decision 80 lean posture: no file committed by default. Registered in the full
    presubmit tier only (Decision 73 non-wedging).
    repo_root defaults to _REPO_ROOT when None (normal validate.py invocation).
    """
    if not _EXPORT_PATH.exists():
        return
    try:
        committed = json.loads(_EXPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failed.append(f"Dependency graph freshness: cannot read committed export: {exc}")
        return
    current = to_export_dict(build_graph(repo_root=repo_root))
    if committed != current:
        try:
            path_display = _EXPORT_PATH.relative_to(_REPO_ROOT)
        except ValueError:
            path_display = _EXPORT_PATH
        failed.append(
            f"Dependency graph export {path_display} is stale. "
            "Re-run: bin/venv-python -m scripts.dependency_graph --export docs/dependency-graph.json"
        )


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="First-party import-graph oracle (ast + networkx). Decision 80.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--reverse-deps", metavar="MODULE", help="List modules that import MODULE.")
    parser.add_argument("--forward-closure", metavar="MODULE", help="List transitive imports of MODULE.")
    parser.add_argument("--reachable", metavar="MODULE", help="Report if MODULE is reachable from declared roots.")
    parser.add_argument(
        "--granularity",
        choices=["module", "symbol"],
        default="module",
        help="module (default) or symbol (adds function/class nodes and call edges).",
    )
    parser.add_argument("--export", metavar="PATH", help="Write graph JSON to PATH (deterministic).")
    parser.add_argument("--blind-spots", action="store_true", help="Print KNOWN_UNSOUND dynamic-dispatch blind spots.")
    args = parser.parse_args()

    if args.blind_spots:
        _print_json(KNOWN_UNSOUND)
        return

    graph = build_graph(granularity=args.granularity)

    if args.reverse_deps:
        _print_json(reverse_deps(graph, args.reverse_deps))
    elif args.forward_closure:
        _print_json(forward_closure(graph, args.forward_closure))
    elif args.reachable:
        _print_json({"module": args.reachable, "reachable": reachable_from_roots(graph, args.reachable)})
    elif args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(to_export_dict(graph), indent=2, sort_keys=True), encoding="utf-8")
        print(f"Graph exported to {export_path}", file=sys.stderr)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
