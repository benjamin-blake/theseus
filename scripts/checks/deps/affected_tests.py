"""Live, cacheless, strictly-additive affected-set derivation for the --pre fast tier.

Decision affected-set-selection (amends Decision 73's fast-tier selection mechanism, its 2nd
amendment). Upgrades the --pre gate from an edited-set (test files literally in the diff) to a
live per-run affected-set (tests AFFECTED by the diff), so a source-only PR -- or a test broken
by a change it does not itself contain -- is caught pre-merge.

Unions the channels named in CHANNEL_NAMES over the edited-set, STRICTLY ADDITIVELY (selection
can only grow, never shrink):
  1. import-closure reverse-deps (a BFS over scripts.dependency_graph.build_graph() reversed) --
     candidates are a changed non-test .py under src/|scripts/ OR a non-test, non-conftest .py
     under tests/ (VTS-01: tests/fixtures/** shared helpers are graph nodes too, so their direct
     importers must be candidates, not silently invisible).
  2. data-edge PRECISE match (path or quoted-token reference, never a bare substring) over
     non-.py data artifacts changed in the diff PLUS the deleted-.py-bytes case (Incident B) --
     generalises and retires scripts/validate.py's old select_roadmap_guard_tests special case --
     PLUS (VTS-02) a structural identifier-boundary dotted-module-token match for D-status .py,
     so a deleted module's importer is selected even when no test text mentions its path/basename
     -- PLUS extra-tree .py candidates (a changed .py outside src/|scripts/|tests/).
  3. scripts.test_coverage_checker.map_source_to_test() mirror map (read-only use).
  4. conftest-subtree rule (a changed tests/**/conftest.py selects EVERY test_*.py under it,
     PROTECTED/uncapped) -- pytest imports a conftest for every test collected beneath it, a real
     structural dependency, not a heuristic, so this channel is unconditional (W2-D, amends
     VTS-03). The root tests/conftest.py and any autouse-declaring conftest still classify as
     FORCING (conftest_subtree_forced) for provenance, since every test's *behavior* can change
     there, not just its import graph; a plain sub-conftest now protects its subtree too
     (conftest_subtree_structural) instead of landing in the cappable residue pool.
     _is_forcing_conftest's autouse text-regex remains a valid escalation signal -- it is no
     longer the only path to protection.
  5. prose-mention and newly-added-file directory-reference edges -- see the roster and the
     escape evidence in scripts/checks/deps/affected_channels.py.

A ~35-module CAP protects against the import-closure channel's combinatorial blow-up. Every
channel in _PROTECTED_CHANNELS is NEVER deferred (the additive-only invariant); only the
TRANSITIVE residue (indirect import-closure ancestors) is subject to the cap -- W2-D removed the
conftest-subtree channel from the cappable pool entirely, since a conftest-subtree hit is now
protected regardless of forcing status. The residue holds its OWN cap-sized budget and is kept
nearest-first in whole import-distance layers (see _residue_keep_set), so protected growth can
never evict it and no layer's coverage is decided by filename. Overflow is deferred LOUDLY (never
silently dropped) -- the full tier still covers it.

On any internal exception, falls back to the edited-set and prints a loud warning (Decision 55:
fail loud, never silently shrink below the edited-set).

The emitted selection-manifest.json is an OUTPUT/observability artifact ONLY -- it is NEVER read
back as a selection input (no persisted selection cache, no coverage cache; this is what makes
the derivation "live" and "cacheless").
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import networkx as nx

from scripts.checks import _common
from scripts.checks.deps.affected_channels import is_extra_tree_py, new_file_reference_dirs, scan_reference_channels
from scripts.dependency_graph import _file_to_module, build_graph
from scripts.test_coverage_checker import map_source_to_test

CAP = 35

# How _residue_keep_set ranks the cappable residue, recorded in the manifest so a post-merge
# escape can be attributed to the ranking that produced it and not just to "the cap".
_RESIDUE_RANKING = "bfs_distance_layers_then_path"

# Defensive rank for a residue member with no measured import distance. Every residue member
# comes from the import closure, so a distance is always recorded; ranking an impossible member
# last beats a KeyError, which would drop the whole derivation to the edited-set fallback.
_UNRANKED_DISTANCE = 1 << 30

# Channels that are NEVER capped, in provenance-precedence order (a test hit by several channels
# is attributed to the first one here). Decision 135 permits deferring only the transitive
# import-closure residue; every other channel is either the edited set itself or a precise,
# bounded edge. mirror_map joins them because it is a curated exact source<->test mapping, not a
# closure -- deferring it is what let `A <new source>.py` reach main with its own mirror test
# unrun. conftest_subtree_structural joins them (W2-D): pytest importing a conftest for every
# test beneath it is a structural dependency, not a heuristic, so capping it silently drops real
# coverage (tests/checks/conftest.py alone governs 176 test files). The cappable remainder is
# just ("import_closure_transitive",).
_PROTECTED_CHANNELS = (
    "edited_set",
    "import_closure_direct",
    "data_edge",
    "mirror_map",
    "data_edge_mention",
    "directory_reference",
    "conftest_subtree_forced",
    "conftest_subtree_structural",
)

CHANNEL_NAMES = _PROTECTED_CHANNELS + ("import_closure_transitive",)

# VTS-06: emit_manifest's write target when repo_root is None (production default). A
# module-level constant (rather than an inline expression in emit_manifest) so an autouse test
# fixture (tests/conftest.py's _isolate_selection_manifest, mirroring _isolate_plans_jsonl) can
# monkeypatch it to a per-test temp path -- otherwise every tests/validate/ orchestrator test
# that drives _validate.main() --pre would clobber the tracked logs/debug/selection-manifest.json
# with fixture data. Production behaviour is unchanged: this resolves to the identical path the
# inline expression previously computed.
DEBUG_MANIFEST_PATH: Path = _common.ROOT / "logs" / "debug" / "selection-manifest.json"

# Same shape as scripts/validate.py's pre-existing edited-set regex (kept identical for
# continuity: the edited-set baseline must not itself narrow or widen on this change).
_EDITED_TEST_RE = re.compile(r"tests/.*test_[^/]+\.py$")

_ADDED_OR_MODIFIED = ("A", "M", "??")


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
    (see _residue_keep_set). One BFS per changed module yields the closure AND its distances, so
    it REPLACES the previous predecessors()+nx.ancestors() pair instead of adding a traversal.
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


def _data_edge_reference_candidates(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(basename, relpath) candidates for the data-edge channel: any changed non-.py file
    (added/modified/untracked), any DELETED .py file (Incident B: a deleted test file's bytes are
    referenced, by basename, from a surviving meta-test), and any EXTRA-TREE .py file -- one
    outside src/|scripts/|tests/ (setup.py, .claude/hooks/*.py, .claude/statusline.py), which has
    no graph node and no mirror-map entry, so a text edge is its only edge to a test at all."""
    candidates: list[tuple[str, str]] = []
    for status, path in entries:
        if path.endswith(".py") and status != "D" and not is_extra_tree_py(path):
            continue
        candidates.append((Path(path).name, path))
    return candidates


def _quoted_token_pattern(basename: str) -> re.Pattern[str]:
    """PRECISE quoted-token match: the basename must appear as a whole quoted string, optionally
    with a path prefix ending in '/', e.g. "ROADMAP-PLATFORM.yaml" or "docs/ROADMAP-PLATFORM.yaml".
    Deliberately NOT a bare substring match -- a common basename (config.py, utils.py,
    __init__.py) embedded inside a longer, unrelated identifier (e.g. "myconfig.py_backup")
    must not match."""
    return re.compile(r"['\"]([^'\"]*/)?" + re.escape(basename) + r"['\"]")


def _dotted_token_pattern(dotted: str) -> re.Pattern[str]:
    """VTS-02: identifier-boundary structural match for a dotted module name -- matches
    'scripts.foo' as a whole dotted token (e.g. inside `import scripts.foo` or a
    `patch("scripts.foo.run")` string) but never inside a longer name: neither a word character
    nor '.' may immediately precede or follow the match, so 'scripts.foo' does not match
    'scripts.foobar' (blocked by the trailing word-char lookahead) or 'scripts.foo.bar' (blocked
    by the trailing '.' lookahead)."""
    return re.compile(r"(?<![\w.])" + re.escape(dotted) + r"(?![\w.])")


def _deleted_py_dotted_patterns(entries: list[tuple[str, str]], repo_root: Path) -> list[re.Pattern[str]]:
    """VTS-02: one structural dotted-module-token pattern per D-status .py path, computed purely
    from the path string via the SAME dotted-name convention as dependency_graph._file_to_module
    (repo-root-prefixed, trailing __init__ dropped) -- no filesystem access needed since a
    deleted file's dotted name is fully determined by its former path. Lets a test that imports
    a deleted module structurally (no textual path/quoted-basename mention required, unlike the
    pre-existing _quoted_token_pattern/relpath match this is purely additive alongside) still be
    selected."""
    patterns: list[re.Pattern[str]] = []
    for status, path in entries:
        if status != "D" or not path.endswith(".py"):
            continue
        dotted = _file_to_module(repo_root / path, repo_root)
        if dotted:
            patterns.append(_dotted_token_pattern(dotted))
    return patterns


def _data_edge_channel(entries: list[tuple[str, str]], repo_root: Path) -> tuple[set[str], set[str], set[str]]:
    """Single-pass scan of tests/**/*.py yielding (precise, mention, directory_reference) hits.

    precise: the full candidate PATH appears literally in the text, the candidate's basename
    appears as a whole quoted token (never a bare substring, see _quoted_token_pattern), or --
    VTS-02 -- a deleted .py path's dotted module name appears as a structural identifier-boundary
    token (see _dotted_token_pattern).
    mention / directory_reference: see scripts/checks/deps/affected_channels.py.
    """
    candidates = _data_edge_reference_candidates(entries)
    dotted_patterns = _deleted_py_dotted_patterns(entries, repo_root)
    directory_paths = new_file_reference_dirs(entries)
    if not candidates and not dotted_patterns and not directory_paths:
        return set(), set(), set()
    return scan_reference_channels(
        repo_root,
        path_literals=[relpath for _basename, relpath in candidates],
        quoted_patterns=[_quoted_token_pattern(basename) for basename, _relpath in candidates] + dotted_patterns,
        mention_basenames=[basename for basename, _relpath in candidates],
        directory_paths=directory_paths,
    )


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


_AUTOUSE_RE = re.compile(r"autouse\s*=\s*True")


def _is_forcing_conftest(path: str, repo_root: Path) -> bool:
    """VTS-03: a conftest FORCES its subtree into protected/uncapped scope if it is the root
    tests/conftest.py (whose fixtures apply repo-wide, so its subtree IS the whole suite) or its
    text declares an autouse fixture (autouse=True applies to every test collected under it, so a
    change can alter EVERY test's behavior in its subtree, not just tests that import it)."""
    if path == "tests/conftest.py":
        return True
    try:
        text = (repo_root / path).read_text(encoding="utf-8")
    except OSError:
        return False
    return _AUTOUSE_RE.search(text) is not None


def _conftest_subtree_channel(entries: list[tuple[str, str]], repo_root: Path) -> tuple[set[str], set[str]]:
    """A changed (added/modified) tests/**/conftest.py selects every test_*.py in its subtree --
    pytest imports a conftest for every test collected beneath it, a real structural dependency,
    not a heuristic, so BOTH buckets returned here are protected/uncapped by the caller (W2-D,
    amends VTS-03).

    Returns (forcing_hits, structural_hits), split purely for PROVENANCE: forcing_hits come from
    the root tests/conftest.py or an autouse-fixture-bearing conftest, where every test's
    *behavior* (not just its import graph) can change -- kept as its own channel
    (conftest_subtree_forced) since that distinction stays meaningful even though both buckets
    are now equally uncapped. structural_hits are every other (non-forcing) sub-conftest --
    previously the cappable "ordinary" channel; W2-D promotes it because a change there can still
    break every test file that imports it, autouse or not."""
    forcing: set[str] = set()
    structural: set[str] = set()
    for status, path in entries:
        if status not in _ADDED_OR_MODIFIED:
            continue
        if Path(path).name != "conftest.py":
            continue
        if not (path == "tests/conftest.py" or path.startswith("tests/")):
            continue
        conftest_dir = (repo_root / path).parent
        if not conftest_dir.is_dir():
            continue
        bucket = forcing if _is_forcing_conftest(path, repo_root) else structural
        for test_file in sorted(conftest_dir.rglob("test_*.py")):
            bucket.add(test_file.relative_to(repo_root).as_posix())
    return forcing, structural


def _residue_keep_set(
    residue_pool: set[str], distance: dict[str, int], protected_size: int, cap: int
) -> tuple[set[str], int | None]:
    """Which transitive-residue members survive the cap, and the deepest import distance kept.

    Decision 135 fixes WHICH channel is cappable (only this one) and that overflow defers loudly;
    the budget arithmetic below is the implementation's.

    1. FIXED BUDGET -- the residue holds its OWN cap-sized budget, not `cap - protected_size`. The
       cap bounds the transitive tail; it must not shrink as the protected channels' recall
       improves, because that EVICTS residue an earlier revision kept (measured: promoting one
       channel plus a graph edge fix dropped 3 of 4 pinned registry driver tests).
    2. LAYER-ATOMIC, NEAREST-FIRST -- members rank by import distance and the budget cuts on a
       DISTANCE boundary, whole BFS layers at a time. One layer's members carry identical relevance
       evidence, so splitting a layer decides coverage by filename.
    3. NO-REGRESSION FLOOR -- what the superseded `cap - protected_size` alphabetical accounting
       would have kept is kept too, making the switch additive by construction, not by measurement.
    """
    if not residue_pool:
        return set(), None
    by_distance: dict[int, list[str]] = {}
    for path in residue_pool:
        by_distance.setdefault(distance.get(path, _UNRANKED_DISTANCE), []).append(path)
    kept: set[str] = set()
    depth = max(by_distance)
    for layer in sorted(by_distance):
        kept.update(by_distance[layer])
        if len(kept) >= cap:
            depth = layer
            break
    return kept | set(sorted(residue_pool)[: max(cap - protected_size, 0)]), depth


def _current_sha(repo_root: Path) -> str:
    result = _common.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _empty_manifest(
    sha: str, entries: list[tuple[str, str]], edited_set: list[str], elapsed: float, cap: int
) -> dict[str, Any]:
    return {
        "sha": sha,
        "diff": [{"status": status, "path": path} for status, path in entries],
        "edited_set": edited_set,
        "selected": edited_set,
        "provenance": dict.fromkeys(edited_set, "edited_set"),
        "channels": {name: len(edited_set) if name == "edited_set" else 0 for name in CHANNEL_NAMES},
        "capped": False,
        "deferred": [],
        "cap": cap,
        "residue_budget": cap,
        "residue_ranking": _RESIDUE_RANKING,
        "residue_kept_depth": None,
        "full_suite_forced": False,
        "timings": {"total_s": elapsed},
    }


def derive_affected_tests(
    diff_entries: list[tuple[str, str]],
    *,
    repo_root: Path | None = None,
    cap: int = CAP,
) -> dict[str, Any]:
    """Derive the live affected test-selection set for one --pre run.

    diff_entries: the status-aware diff (scripts.checks._common.get_status_aware_diff()) --
    (status, path) tuples covering A/M/D and untracked ("??") paths.

    Returns {"selected": [...], "manifest": {...}}. NEVER reads any prior manifest (the manifest
    is output-only); on an internal exception, falls back to the edited-set with a loud warning.
    """
    t0 = time.monotonic()
    root = repo_root if repo_root is not None else _common.ROOT
    entries = list(diff_entries)
    sha = _current_sha(root)

    edited_set = sorted({path for status, path in entries if status in _ADDED_OR_MODIFIED and _EDITED_TEST_RE.match(path)})

    if not entries:
        manifest = _empty_manifest(sha, entries, edited_set, time.monotonic() - t0, cap)
        return {"selected": edited_set, "manifest": manifest}

    try:
        changed_tests_helper_files = [
            path for status, path in entries if status in _ADDED_OR_MODIFIED and _is_changed_tests_helper_py(path)
        ]
        changed_source_files = [
            path for status, path in entries if status in _ADDED_OR_MODIFIED and _is_changed_source_py(path)
        ] + changed_tests_helper_files

        direct, transitive, residue_distance = _import_closure_channel(changed_source_files, root)
        direct |= _tests_tree_import_closure_channel(changed_tests_helper_files, root)
        precise_hits, mention_hits, directory_hits = _data_edge_channel(entries, root)
        mirror_hits = _mirror_map_channel(changed_source_files, root)
        conftest_forced_hits, conftest_structural_hits = _conftest_subtree_channel(entries, root)

        channel_sets: dict[str, set[str]] = {
            "edited_set": set(edited_set),
            "import_closure_direct": direct,
            "data_edge": precise_hits,
            "mirror_map": mirror_hits,
            "data_edge_mention": mention_hits,
            "directory_reference": directory_hits,
            "conftest_subtree_forced": conftest_forced_hits,
            "conftest_subtree_structural": conftest_structural_hits,
            "import_closure_transitive": transitive,
        }
        protected = set().union(*(channel_sets[name] for name in _PROTECTED_CHANNELS))
        residue_pool = transitive - protected

        kept_set, kept_depth = _residue_keep_set(residue_pool, residue_distance, len(protected), cap)
        kept_residue = sorted(kept_set)
        deferred_residue = sorted(residue_pool - kept_set)

        provenance: dict[str, str] = {}
        for name in _PROTECTED_CHANNELS:
            for p in sorted(channel_sets[name]):
                provenance.setdefault(p, name)
        for p in kept_residue:
            provenance.setdefault(p, "import_closure_transitive")

        selected = sorted(protected | kept_set)
        capped = bool(deferred_residue)
        full_suite_forced = any(status in _ADDED_OR_MODIFIED and path == "tests/conftest.py" for status, path in entries)

        if capped:
            print(
                f"\n=== AFFECTED-SET CAP: deferring {len(deferred_residue)} transitive-residue "
                f"test module(s) beyond import distance {kept_depth} (residue budget={cap}, "
                f"ranked {_RESIDUE_RANKING}) -- the full post-merge tier still covers these ==="
            )
            for p in deferred_residue:
                print(f"  DEFERRED (transitive residue): {p}")

        manifest = {
            "sha": sha,
            "diff": [{"status": status, "path": path} for status, path in entries],
            "edited_set": edited_set,
            "selected": selected,
            "provenance": provenance,
            "channels": {name: len(hits) for name, hits in channel_sets.items()},
            "capped": capped,
            "deferred": deferred_residue,
            "cap": cap,
            "residue_budget": cap,
            "residue_ranking": _RESIDUE_RANKING,
            "residue_kept_depth": kept_depth,
            "full_suite_forced": full_suite_forced,
            "timings": {"total_s": time.monotonic() - t0},
        }
        return {"selected": selected, "manifest": manifest}
    except Exception as exc:  # noqa: BLE001 -- Decision 55: fail loud, fall back, never crash --pre
        print(
            f"\n=== AFFECTED-SET DERIVATION FAILED -- FALLING BACK TO EDITED-SET (Decision 55) ===\n"
            f"{exc!r}\nSelection: the edited-set only ({len(edited_set)} file(s)). "
            "This is a LOUD fallback, not a silent shrink."
        )
        manifest = _empty_manifest(sha, entries, edited_set, time.monotonic() - t0, cap)
        manifest["fallback"] = True
        manifest["fallback_reason"] = repr(exc)
        return {"selected": edited_set, "manifest": manifest}


def _upload_manifest_best_effort(manifest: dict[str, Any]) -> None:
    """Best-effort S3 upload of the selection manifest (Decision 55: LOUD skip, never silent,
    never raising -- and never counted against the 5-min fast-tier budget assertion). Lazily
    imports boto3 so the no-creds fast tier (requirements-fast.txt omits boto3) degrades
    gracefully instead of breaking --pre."""
    bucket = os.environ.get("S3_LOG_BUCKET", "").strip()
    if not bucket:
        print("Selection manifest: S3_LOG_BUCKET not set -- skipping best-effort S3 upload (loud skip).")
        return
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        print("Selection manifest: boto3 not installed -- skipping best-effort S3 upload (loud skip, Decision 55).")
        return
    try:
        from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

        profile = resolve_aws_profile(default="agent_platform")
        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        client = session.client("s3", region_name="eu-west-2")
        sha = manifest.get("sha", "unknown")
        key = f"ci/selection/{sha}/selection-manifest.json"
        client.put_object(Bucket=bucket, Key=key, Body=json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        print(f"Selection manifest uploaded to s3://{bucket}/{key}")
    except Exception as exc:  # noqa: BLE001 -- Decision 55: loud skip, never raise (best-effort/async)
        print(f"Selection manifest: best-effort S3 upload failed -- loud skip (Decision 55): {exc!r}")


def emit_manifest(manifest: dict[str, Any], *, repo_root: Path | None = None) -> Path:
    """Print, write (gitignored path), and best-effort-upload the selection manifest.

    The manifest is NEVER read back as a selection input -- this function is write/print-only.
    The local write is best-effort (Decision 55: LOUD skip, never silent, never raising) --
    an observability artifact must never crash the --pre gate on a local disk I/O error, the
    same philosophy already applied to the S3 upload leg below.

    repo_root=None (the production default) resolves the write target through the patchable
    DEBUG_MANIFEST_PATH module constant (VTS-06), so a test fixture can redirect it without
    touching this function. An explicit repo_root (existing callers, e.g.
    tests/checks/deps/test_affected_tests.py) is honoured verbatim, unaffected by the constant.
    """
    print("\n=== Affected-set selection manifest ===")
    rendered = json.dumps(manifest, indent=2, sort_keys=True)
    print(rendered)
    manifest_path = DEBUG_MANIFEST_PATH if repo_root is None else repo_root / "logs" / "debug" / "selection-manifest.json"
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"Selection manifest: local write to {manifest_path} failed -- loud skip (Decision 55): {exc!r}")
    _upload_manifest_best_effort(manifest)
    return manifest_path
