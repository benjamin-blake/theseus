"""Roadmap blocking-graph liveness detector (PLAN-roadmap-blocking-liveness-detector).

Builds the heterogeneous blocking graph over NON_TERMINAL roadmap nodes (tier_items not yet
complete/reserved, plus pending candidate_decisions), classifies every edge by the terminal
state it demands of its target, and reports which strongly connected components are TOXIC --
structurally unable to progress because some member's completion is (transitively) gated on
another member's own completion.

Pure and report-only: never raises given a validated RoadmapDocument, and these edges are
deliberately never fed into RoadmapDocument's own load-time cycle rejection
(scripts/platform_roadmap_models.py's `_validate_graph`) -- folding them in would make a real
deadlock unloadable instead of reporting it (see docs/contracts/exit-criteria-ledger.yaml's
blocked_by governance_notes).

See docs/contracts/roadmap-liveness.yaml for the full node-class / edge-demand semantics this
module implements, and scripts/checks/roadmap/validate_roadmap_liveness.py for the registered
check that ratchets the measured toxic set against config/roadmap_liveness_baseline.yaml.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import networkx as nx

from scripts.platform_roadmap_models import _TIER_SHORTCUT_RE, RoadmapDocument
from scripts.platform_roadmap_state import _CD_REF_RE
from scripts.platform_roadmap_state import load as load_roadmap_document

_DEFAULT_ROADMAP_PATH = Path(__file__).resolve().parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"

# NON_TERMINAL tier_item statuses -- everything not yet 'complete' or 'reserved'.
# 'reserved' is excluded: every reserved item measured today carries empty depends_on, nothing
# depends on one, and no criterion blocks on one, so no ring can pass through a reserved node
# (see docs/contracts/roadmap-liveness.yaml). 'deferred_post_mvp' IS admitted -- a parked item is
# reactivatable by a status flip, so a ring through it is a latent, not moot, deadlock.
_NON_TERMINAL_ITEM_STATUSES: frozenset[str] = frozenset({"not_started", "in_progress", "deferred_post_mvp"})

EdgeDemand = Literal["complete", "ratified", "evidence"]


@dataclass(frozen=True)
class BlockingEdge:
    """One directed blocking edge: `source` cannot progress until `target` reaches `demand`."""

    source: str
    target: str
    demand: EdgeDemand
    kind: str


def _non_terminal_item_ids(doc: RoadmapDocument) -> set[str]:
    return {item.id for item in doc.tier_items if item.status in _NON_TERMINAL_ITEM_STATUSES}


def _non_terminal_cd_ids(doc: RoadmapDocument) -> set[str]:
    return {cd.id for cd in doc.candidate_decisions if cd.state == "pending"}


def _resolve_item_ref(ref: str, doc: RoadmapDocument, item_ids: set[str]) -> set[str]:
    """Resolve a depends_on/gates-shaped ref (a concrete tier_item id or a tier shortcut) to the
    subset of NON_TERMINAL tier_item ids it names -- a terminal (complete/reserved) member is
    pruned, matching the module's report-only "edges with a terminal endpoint are pruned" rule."""
    if _TIER_SHORTCUT_RE.match(ref):
        return {item.id for item in doc.tier_items if item.tier == ref} & item_ids
    return {ref} & item_ids


def build_blocking_graph(doc: RoadmapDocument) -> list[BlockingEdge]:
    """Every blocking edge between two NON_TERMINAL nodes, labeled by the terminal state its
    source demands of its target. Four structural sources, plus the Decision 105 reverse edge:

      1. TierItem.depends_on            -> demands 'complete' of the dependency.
      2. CandidateDecision.gates        -> the gated item demands 'ratified' of the CD; the CD
         in turn demands 'evidence' of the gated item (Decision 105 reverse edge -- a pending
         CD accrues realization evidence from the items it gates completing).
      3. TierItem.decision_required_before (a CD id embedded in gate-grammar/prose text, the
         same _CD_REF_RE extraction scripts.platform_roadmap_state's blocked_on_cd() uses) ->
         demands 'ratified' of the named CD.
      4. ExitCriterion.blocked_by        -> demands its own literal `until` value ('complete' for
         a tier_item/tier-shortcut ref, 'ratified' for a CD ref -- already schema-enforced by
         CriterionBlocker, so no translation is needed).

    CandidateDecision.affects is DELIBERATELY excluded -- it is in-scope-of, not
    completion-blocking (PLAN-roadmap-blocking-edge-semantics split gates from affects).
    """
    item_ids = _non_terminal_item_ids(doc)
    cd_ids = _non_terminal_cd_ids(doc)
    edges: list[BlockingEdge] = []

    for item in doc.tier_items:
        if item.id not in item_ids:
            continue
        for dep in item.depends_on:
            # A depends_on self-reference (direct or via a same-tier shortcut) is unreachable
            # here -- RoadmapDocument's own load-time cycle DFS rejects it before this function
            # ever sees the document (scripts/platform_roadmap_models.py's `_validate_graph`
            # step (c) treats depends_on adjacency, tier-shortcut-expanded, as a real cycle
            # source; blocked_by is the deliberately-excluded exception -- see the criterion
            # loop below, where a self-reference is a legitimate, reachable toxic finding).
            for target in _resolve_item_ref(dep, doc, item_ids):
                edges.append(BlockingEdge(item.id, target, "complete", "depends_on"))

    for cd in doc.candidate_decisions:
        if cd.id not in cd_ids:
            continue
        for ref in cd.gates:
            for target in _resolve_item_ref(ref, doc, item_ids):
                edges.append(BlockingEdge(target, cd.id, "ratified", "cd_gates"))
                edges.append(BlockingEdge(cd.id, target, "evidence", "cd_reverse_evidence"))

    for item in doc.tier_items:
        if item.id not in item_ids:
            continue
        # TierItem.decision_required_before is list[str] | None (unlike CandidateDecision's own
        # list[str] | str | None sibling field) -- no bare-string case to handle here.
        for entry in item.decision_required_before or []:
            for match in _CD_REF_RE.finditer(entry):
                cd_id = match.group(1)
                if cd_id in cd_ids:
                    edges.append(BlockingEdge(item.id, cd_id, "ratified", "decision_required_before"))

    for item in doc.tier_items:
        if item.id not in item_ids:
            continue
        for crit in item.exit_criteria:
            for blocker in crit.blocked_by:
                targets = (
                    _resolve_item_ref(blocker.ref, doc, item_ids) if blocker.until == "complete" else ({blocker.ref} & cd_ids)
                )
                for target in targets:
                    edges.append(BlockingEdge(item.id, target, blocker.until, "criterion_blocked_by"))

    return edges


def _blocking_digraph(node_ids: set[str], edges: list[BlockingEdge]) -> nx.DiGraph:
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(node_ids)
    for edge in edges:
        graph.add_edge(edge.source, edge.target)
    return graph


def toxic_sccs(doc: RoadmapDocument) -> list[frozenset[str]]:
    """Strongly connected components (over `build_blocking_graph`'s edges, via
    networkx.strongly_connected_components) that are TOXIC: they hold at least one internal edge
    demanding 'complete' of a member. A ring built ONLY from 'ratified'/'evidence' edges (e.g. a
    pending-CD build-then-ratify 2-cycle) is benign -- structurally different from an
    `internal depends_on edge` rule, which false-negatives on a shape with empty depends_on but a
    real completion-demanding blocked_by edge (the rec-3394 shape)."""
    node_ids = _non_terminal_item_ids(doc) | _non_terminal_cd_ids(doc)
    edges = build_blocking_graph(doc)
    graph = _blocking_digraph(node_ids, edges)
    complete_pairs = {(edge.source, edge.target) for edge in edges if edge.demand == "complete"}
    return [
        frozenset(scc)
        for scc in nx.strongly_connected_components(graph)
        if any(source in scc and target in scc for source, target in complete_pairs)
    ]


def toxic_node_ids(doc: RoadmapDocument) -> list[str]:
    """The flat, sorted union of every toxic SCC's member ids -- the set config/
    roadmap_liveness_baseline.yaml keys on."""
    ids: set[str] = set()
    for scc in toxic_sccs(doc):
        ids |= scc
    return sorted(ids)


def _safe_load(path: Path) -> RoadmapDocument | None:
    """Load and validate the roadmap at `path`; return None (never raise) on any parse or
    schema-validation failure, so a malformed document degrades to an empty report instead of a
    crash -- the caller (the CLI below, or the registered check) declares the outcome."""
    try:
        return load_roadmap_document(path)
    except Exception:  # noqa: BLE001 -- deliberately broad: any load failure is report-only here.
        return None


def _report(path: Path) -> int:
    doc = _safe_load(path)
    if doc is None:
        print(f"platform_roadmap_liveness: {path} did not load (parse or schema-validation failure).")
        return 1
    sccs = toxic_sccs(doc)
    ids = toxic_node_ids(doc)
    print(f"Toxic SCCs: {len(sccs)}")
    print(f"Toxic node ids ({len(ids)}): {', '.join(ids)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Roadmap blocking-graph liveness detector.")
    parser.add_argument("--report", action="store_true", help="Print the toxic-SCC census.")
    parser.add_argument("--roadmap-path", type=Path, default=_DEFAULT_ROADMAP_PATH)
    args = parser.parse_args(argv)
    if args.report:
        return _report(args.roadmap_path)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
