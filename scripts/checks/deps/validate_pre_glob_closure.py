"""ADVISORY auditor: does each glob-gated --pre check's pre_globs cover its own code closure?

Motivating defect class (D2-3 Finding 4, rec-3289): a `--pre` Entry declares `pre_globs`, the
check's implementation then grows a transitive first-party import that none of those globs match,
and from that moment a diff touching the new input silently SKIPS the check in the fast tier.
Under-inclusion in a gate input is fail-OPEN, which Decision 135's posture forbids. Waves 1 and 2
found 12 such defective globs BY HAND; this check finds them mechanically.

What it does NOT do (the rejected framing): it does not replace `pre_globs` with a runtime
derivation. The manifest stays the single greppable, statically-auditable declaration -- Decision
169's audit surface is untouched and no gate input becomes a runtime computation. Measured reason:
over the FULL graph `nx.descendants()` returns an identical closure for every check module in the
repo, because Decision 169's contractual manifest -> check bare-string-literal edge collapses every
gated check into one strongly-connected component. A derived glob would therefore say "every .py
under src/ and scripts/" for all of them -- selection-identical to deleting `pre_globs`.

So the closure is taken over IMPORT-KIND EDGES ONLY (scripts.dependency_graph.import_subgraph),
which leaves the driver edge in the graph for the selection derivation that needs it while giving
this auditor the code-level view it needs. Honest accounting of the trade: this substitutes one
hand-maintained surface (`_PRUNED_EDGES`) for part of another. It is justified because that list
is a tested declaration carrying a stated reason per entry, and because a wrong entry reddens a
build rather than silently narrowing selection.

Staging (D2-3 migration path). Wave 4a -- THIS stage -- is ADVISORY on BOTH channels: it prints
findings, declares Decision 170 accounting, NEVER appends to `failed`, and never lets an exception
escape (nothing wraps a check body, so a raise here would abort --pre; see the entry point's
Decision 55 loud-skip guard). Wave 4b pays the backlog down: a genuinely missing glob gets added,
an Entry.module naming no graph node gets corrected, a hub artefact gets a reviewed `_PRUNED_EDGES`
entry. Wave 4c flips it to blocking once the backlog is zero, at which point adding an uncovered
import to a check module fails the PR that adds it, with the glob to add printed.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.checks import _common, registry
from scripts.checks._schema import Entry

if TYPE_CHECKING:  # networkx is imported only by the deferred scripts.dependency_graph import
    import networkx as nx

# Reviewed hub-artefact exclusions for the pay-down (wave 4b). Maps an importing module to the
# import targets that are DROPPED from this auditor's traversal -- the pruning wave 2's prototype
# performed silently, promoted to an explicit, tested, per-edge declaration.
#
# WAVE 4b DISCHARGE: wave 4a landed advisory precisely so the real backlog was MEASURED before any
# edge was excluded (930 findings across 40 of 47 gated checks), and the two reviewed hub rows
# below are the one-time allowance that measurement authorised -- never the pay-down method, which
# is ADDING GLOBS to the checks that under-declare them. Add an entry only with an inline comment
# stating why the edge has no behavioural bearing on the importing check, and naming the condition
# that would remove the row again.
_PRUNED_EDGES: dict[str, tuple[str, ...]] = {
    # 17 _manifest targets: Decision 169 registration fan-out -- registry imports each only to assemble _ALL_ENTRIES.
    # The _schema target is a DISTINCT argument: a pure declaration module (Entry, SEGMENT_TOKENS) with no first-party
    # imports, so it drops one path and nothing behind it; 0 of the 45 checks that lose it import it directly.
    # REMOVE this row if a check is shown to need _schema or a manifest in its closure, or at the wave-4c flip.
    # COUPLING: the mirror test pins 17 targets EXACTLY, so a PR adding an 18th check domain must extend this row too.
    "scripts.checks.registry": (
        "scripts.checks._schema",
        "scripts.checks.ci_guards._manifest",
        "scripts.checks.contracts._manifest",
        "scripts.checks.decisions._manifest",
        "scripts.checks.deps._manifest",
        "scripts.checks.executor._manifest",
        "scripts.checks.hygiene._manifest",
        "scripts.checks.iam_tf._manifest",
        "scripts.checks.lambda_pkg._manifest",
        "scripts.checks.misc._manifest",
        "scripts.checks.ops_governance._manifest",
        "scripts.checks.prompts._manifest",
        "scripts.checks.prose._manifest",
        "scripts.checks.roadmap._manifest",
        "scripts.checks.sloc._manifest",
        "scripts.checks.structural._manifest",
        "scripts.checks.typing._manifest",
        "scripts.checks.verification._manifest",
    ),
    # A deferred, PLC0415-exempt function-scope import in _common.load_plan. Safe by COVERAGE, not reachability:
    # 3 of its 5 callers declare no globs at all and so always run; the other 2 already declare scripts/roadmap/** themselves.
    "scripts.checks._common": ("scripts.roadmap.plan_document",),
}

# Per-check cap on printed paths; the count is always reported in full.
_MAX_PRINTED_PATHS = 8

# Rendered in place of a path when an Entry.module names no node in the import graph -- a finding
# in its own right (see _unmatched_paths), not a silently empty closure.
_UNRESOLVABLE_TEMPLATE = "<module not in the import graph: {module}>"


def _glob_match(path: str, glob: str) -> bool:
    """Behavioural replica of scripts/validate.py::_pre_glob_match, INCLUDING its leading-`**/`
    retry, so the gate and this auditor can never disagree on matching semantics.

    Replicated rather than imported for two reasons: scripts/checks/_common.py's module docstring
    pins the no-scripts.validate-dependency rule (validate.py imports scripts.checks.*, so the
    reverse edge is a cycle); and an import edge to scripts.validate would drag validate.py's
    entire closure into THIS module's closure, which this very check then audits. Equivalence is
    pinned by tests/checks/deps/test_validate_pre_glob_closure.py::TestGlobMatcherEquivalence.
    """
    if fnmatch.fnmatch(path, glob):
        return True
    return glob.startswith("**/") and fnmatch.fnmatch(path, glob[3:])


def _module_to_repo_path(module: str, root: Path) -> str | None:
    """Inverse of scripts.dependency_graph._file_to_module for the two node shapes build_graph
    produces: a plain module, and a package node whose file is its `__init__.py`."""
    base = module.replace(".", "/")
    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        if (root / candidate).is_file():
            return candidate
    return None


def _closure_view(root: Path) -> nx.DiGraph:
    """The import-kind-only view of the first-party graph rooted at `root`.

    Reuses build_graph, which is memoized in-process (lru_cache on the resolved root), and layers
    an O(1) subgraph_view on top -- so this never builds a second graph even though
    validate_check_manifests and the affected-set derivation have usually already built the first.
    """
    from scripts.dependency_graph import build_graph, import_subgraph  # noqa: PLC0415

    return import_subgraph(build_graph(repo_root=root))


def _closure_modules(view: nx.DiGraph, module: str) -> set[str]:
    """REFLEXIVE transitive closure of `module` over `view`, minus `_PRUNED_EDGES`.

    Reflexive on purpose: a check whose own defining file is not matched by its own `pre_globs`
    is the most basic recall bug this auditor exists to catch, so the module counts as part of
    the surface it must declare. Returns the empty set for a module absent from the view.
    """
    if module not in view:
        return set()
    seen = {module}
    stack = [module]
    while stack:
        current = stack.pop()
        pruned = _PRUNED_EDGES.get(current, ())
        for successor in view.successors(current):
            if successor in pruned or successor in seen:
                continue
            seen.add(successor)
            stack.append(successor)
    return seen


def _gated_entries() -> list[Entry]:
    """Every manifest Entry that is in --pre AND declares globs, by name. An ungated entry
    (pre_globs is None) always runs, so it has no under-coverage to audit."""
    return sorted(
        (entry for entry in registry._ALL_ENTRIES.values() if entry.pre and entry.pre_globs is not None),
        key=lambda entry: entry.name,
    )


def _unmatched_paths(entry: Entry, view: nx.DiGraph, root: Path) -> list[str]:
    """Repo-relative closure paths of `entry.module` that none of `entry.pre_globs` matches.

    A module ABSENT from the view (a typo'd or relocated `Entry.module`) has NO computable
    closure, so no glob can be shown to cover it -- and the reflexivity guarantee `_closure_modules`
    documents is exactly what a wrong module identity forfeits. Reporting the module itself as the
    single unresolvable finding keeps that case out of the "clean" bucket: auditing it CLEAN would
    reproduce, inside this auditor, the same fail-open shape it exists to catch.
    """
    if entry.module not in view:
        return [_UNRESOLVABLE_TEMPLATE.format(module=entry.module)]
    globs = entry.pre_globs or ()
    paths = sorted(filter(None, (_module_to_repo_path(m, root) for m in _closure_modules(view, entry.module))))
    return [path for path in paths if not any(_glob_match(path, glob) for glob in globs)]


def _audit() -> None:
    """The audit proper. Split out so the registered check can wrap it in the Decision 55
    loud-skip guard, and so the banner still prints when that guard fires."""
    entries = _gated_entries()
    if not entries:
        print("  PASS: no --pre entry declares pre_globs.")
        registry.examined(0, unit="gated_pre_checks")
        return

    root = _common.ROOT
    view = _closure_view(root)

    total_unmatched = 0
    with_findings = 0
    for entry in entries:
        unmatched = _unmatched_paths(entry, view, root)
        if not unmatched:
            continue
        with_findings += 1
        total_unmatched += len(unmatched)
        print(f"  {entry.name}: {len(unmatched)} closure path(s)/module(s) not matched by its declared pre_globs")
        for path in unmatched[:_MAX_PRINTED_PATHS]:
            print(f"      - {path}")
        if len(unmatched) > _MAX_PRINTED_PATHS:
            print(f"      ... and {len(unmatched) - _MAX_PRINTED_PATHS} more")

    if with_findings:
        print(
            f"  ADVISORY: {with_findings} of {len(entries)} glob-gated --pre check(s) have at least one uncovered "
            f"closure path or unresolvable module ({total_unmatched} finding(s) total). Add the missing glob to the "
            "check's Entry, fix the Entry.module that names no graph node, or record a reviewed hub-artefact edge in "
            "validate_pre_glob_closure._PRUNED_EDGES. Never fails the build at this stage."
        )
    else:
        print(f"  PASS: all {len(entries)} glob-gated --pre check(s) declare globs covering their own import closure.")
    registry.examined(len(entries), unit="gated_pre_checks")


@registry.register("validate_pre_glob_closure", owner="platform")
def validate_pre_glob_closure(failed: list[str]) -> None:
    """Report, per glob-gated --pre check, the import-closure paths its pre_globs do not cover.

    ADVISORY at this stage on BOTH channels: `failed` is never appended to (see the module
    docstring's staging paragraph), and no exception escapes. The second half is not decoration --
    nothing wraps a check body (scripts/checks/validation_result.py's dispatch_recording calls
    fn(failed) bare, and validate.py's --pre loop does not wrap the dispatch either), so a raise
    from here would abort the whole fast tier before its summary ever printed. Same loud-skip
    shape as derive_affected_tests (Decision 55): print the error, declare it, carry on.

    Decision 170 accounting on all three reachable exits -- examined(0) for an empty gated roster
    (an empty DOMAIN, not a skip, per check-accounting.yaml's discrimination rule),
    examined(len(entries)) for a real run, and skipped(reason) when the audit could not complete.
    """
    print("\n=== Pre-glob closure audit (ADVISORY, D2-3 / rec-3289) ===")
    try:
        _audit()
    except Exception as exc:  # noqa: BLE001 -- Decision 55: an ADVISORY check must never abort --pre
        print(
            f"  SKIP (LOUD, Decision 55): the pre-glob closure audit raised {exc!r} and was abandoned. "
            "Nothing was audited this run; the gate is NOT failed and the fast tier continues."
        )
        registry.skipped(f"pre-glob closure audit raised {exc!r}")
