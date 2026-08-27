"""Graph-derived recall channels for the --pre affected-set derivation (Decision 135).

Sibling of affected_tests.py, which owns the derivation, the cap and the manifest; this module
owns the STRUCTURAL half of the channel roster -- the channels whose edges come from the import
graph rather than from test text:

  * IMPORT-CLOSURE (_import_closure_channel, roster item 1) -- a BFS over
    scripts.dependency_graph.build_graph() reversed, yielding the direct importers, the deeper
    transitive residue, and the import distance the residue's cap ranks on.
  * TESTS-TREE DIRECT-IMPORTER SCAN (_tests_tree_import_closure_channel, VTS-01) -- the same
    "direct importer" signal for changed tests/**-tree helper modules, which build_graph()'s
    roots=("src", "scripts") extraction never gives predecessors for.
  * MIRROR MAP (_mirror_map_channel, roster item 3) -- read-only use of
    scripts.test_coverage_checker.map_source_to_test().

It also owns the shared _EDITED_TEST_RE test-path vocabulary and the two candidate predicates
(_is_changed_source_py, _is_changed_tests_helper_py) that decide which changed paths these
channels are allowed to follow -- they are the graph channels' admission rule, so they live with
them.

The TEXT/reference half of the roster (prose mention, directory reference, and the single shared
tests/**/*.py text scan) lives in the other sibling, scripts/checks/deps/affected_channels.py.
Two channel families, two modules, one orchestrator.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import networkx as nx

from scripts.dependency_graph import _file_to_module, build_graph
from scripts.test_coverage_checker import map_source_to_test

# Same shape as scripts/validate.py's pre-existing edited-set regex (kept identical for
# continuity: the edited-set baseline must not itself narrow or widen on this change).
_EDITED_TEST_RE = re.compile(r"tests/.*test_[^/]+\.py$")


def _is_changed_source_py(path: str) -> bool:
    """A non-test .py file under src/ or scripts/ -- the import-closure/mirror-map channels'
    candidate set."""
    return (
        path.endswith(".py") and (path.startswith("src/") or path.startswith("scripts/")) and not _EDITED_TEST_RE.match(path)
    )


def _is_changed_tests_helper_py(path: str) -> bool:
    """VTS-01: a non-test, non-conftest .py file under tests/ (e.g. tests/fixtures/*.py shared
    helpers, Decision 131's sanctioned shared-helper home) -- admitted into the SAME
    import-closure/mirror-map candidate set as _is_changed_source_py so a fixtures-only edit
    selects its direct importer tests instead of silently selecting zero. conftest.py is
    excluded here because it already has its own dedicated channel (_conftest_subtree_channel)."""
    return (
        path.endswith(".py")
        and path.startswith("tests/")
        and not _EDITED_TEST_RE.match(path)
        and Path(path).name != "conftest.py"
    )


def _module_to_test_path(module_name: str, repo_root: Path) -> str | None:
    """Map a graph module dotted-name back to an existing tests/**/test_*.py file path, or
    None (filters out package __init__ nodes and non-test modules automatically -- their
    reconstructed path either doesn't exist or doesn't match the test_ basename convention)."""
    rel = module_name.replace(".", "/") + ".py"
    if not _EDITED_TEST_RE.match(rel):
        return None
    if not (repo_root / rel).exists():
        return None
    return rel


def _import_closure_channel(changed_source_files: list[str], repo_root: Path) -> tuple[set[str], set[str], dict[str, int]]:
    """Returns (direct, transitive_only, distance) for the import-closure channel.

    direct: test modules that DIRECTLY import a changed module (one import hop).
    transitive_only: every deeper reverse-reachable test module -- the "transitive residue" the
    additive-only invariant permits deferring under the cap.
    distance: test path -> fewest import hops to ANY changed module, the residue's relevance rank
    (see affected_tests._residue_keep_set). One BFS per changed module yields the closure AND its
    distances, so it REPLACES the previous predecessors()+nx.ancestors() pair instead of adding a
    traversal.
    """
    if not changed_source_files:
        return set(), set(), {}
    graph = build_graph(repo_root=repo_root)
    importers = graph.reverse(copy=False)
    hops_by_module: dict[str, int] = {}
    for f in changed_source_files:
        mod = _file_to_module(repo_root / f, repo_root)
        if mod is None or mod not in graph:
            continue
        for node, hops in nx.single_source_shortest_path_length(importers, mod).items():
            if hops < hops_by_module.get(node, hops + 1):
                hops_by_module[node] = hops
    distance: dict[str, int] = {}
    for node, hops in hops_by_module.items():
        test_path = _module_to_test_path(node, repo_root)
        if test_path:
            distance[test_path] = hops
    direct = {p for p, hops in distance.items() if hops <= 1}
    return direct, set(distance) - direct, distance


def _module_imports_any(tree: ast.Module, dotted_names: set[str]) -> bool:
    """True if `tree` contains `import <dotted>` or `from <dotted> import ...` for any name in
    dotted_names (exact match, or a submodule of a changed package). Matches absolute and
    submodule-qualified imports only -- a relative import (`from . import x`) or a
    `from <parent_pkg> import <submodule>` __init__-re-export style is not matched; no such
    importer of a tests-tree helper exists in-repo today (grepped), so this is a known,
    currently-inert follow-up gap, not an active recall hole."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in dotted_names or any(alias.name.startswith(d + ".") for d in dotted_names):
                    return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in dotted_names or any(node.module.startswith(d + ".") for d in dotted_names):
                return True
    return False


def _tests_tree_import_closure_channel(changed_tests_helper_files: list[str], repo_root: Path) -> set[str]:
    """VTS-01: direct-importer scan for changed tests-tree helper modules (e.g.
    tests/fixtures/**, Decision 131's sanctioned shared-helper home).

    scripts.dependency_graph.build_graph()'s first-party import extraction
    (extract_first_party_imports roots=("src", "scripts")) never targets "tests." modules, so a
    tests/fixtures/x.py file IS a graph node but graph.predecessors() on it is always empty --
    _import_closure_channel above cannot see these edges no matter how its candidate set is
    widened. Fixing that root cause lives in scripts/dependency_graph.py, outside this plan's
    inline-path scope, so this self-contained ast scan supplies the same "direct importer"
    signal (channel 1's graph.predecessors() case) without touching that file: every
    tests/**/test_*.py that imports the changed helper's dotted module name directly."""
    tests_dir = repo_root / "tests"
    if not changed_tests_helper_files or not tests_dir.is_dir():
        return set()
    dotted_names = {mod for f in changed_tests_helper_files if (mod := _file_to_module(repo_root / f, repo_root))}
    if not dotted_names:
        return set()
    hits: set[str] = set()
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        if "__pycache__" in test_file.parts:
            continue
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        except (OSError, SyntaxError):
            continue
        if _module_imports_any(tree, dotted_names):
            hits.add(test_file.relative_to(repo_root).as_posix())
    return hits


def _mirror_map_channel(changed_source_files: list[str], repo_root: Path) -> set[str]:
    """Read-only use of scripts.test_coverage_checker.map_source_to_test() (channel 3).

    Concern-split mappings resolve to test package directories. Expand those packages to
    individual test modules here so the affected-set cap and downstream reactive pytest probes
    operate on their documented one-module-per-entry grain.
    """
    hits: set[str] = set()
    for f in changed_source_files:
        result = map_source_to_test(repo_root / f)
        if result is None:
            continue
        if result.suffix == ".py":
            if result.exists():
                hits.add(result.relative_to(repo_root).as_posix())
        elif result.is_dir():
            for test_file in sorted(result.rglob("test_*.py")):
                if "__pycache__" not in test_file.parts and test_file.is_file():
                    hits.add(test_file.relative_to(repo_root).as_posix())
    return hits
