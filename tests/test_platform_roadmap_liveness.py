"""Tests for scripts/platform_roadmap_liveness.py -- the roadmap blocking-graph liveness
detector's pure graph module (PLAN-roadmap-blocking-liveness-detector).

Synthetic fixtures only -- the live-roadmap census (2 toxic SCCs, 19 node ids) is pinned by
scripts/checks/roadmap/validate_roadmap_liveness.py's own mirror test
(TestTranscription::test_cd41_ratified_edge_adds_no_toxic_scc and the check's leg A), not here.
"""

from __future__ import annotations

import yaml

from scripts.platform_roadmap_liveness import BlockingEdge, _safe_load, build_blocking_graph, main, toxic_node_ids, toxic_sccs
from scripts.platform_roadmap_models import RoadmapDocument

_DOC_META = {"id": "ROADMAP-TEST", "version": 1, "status": "draft", "filed_via": "pending_log_decision_lambda"}


def _item(
    item_id: str,
    tier: str = "T9",
    depends_on: list | None = None,
    status: str = "not_started",
    exit_criteria: list | None = None,
    decision_required_before: list | None = None,
) -> dict:
    d = {
        "id": item_id,
        "tier": tier,
        "name": f"Test item {item_id}",
        "depends_on": depends_on or [],
        "files_in_scope": [],
        "exit_criteria": exit_criteria or [],
        "effort": "S",
        "status": status,
    }
    if decision_required_before is not None:
        d["decision_required_before"] = decision_required_before
    return d


def _cd(cd_id: str, state: str = "pending", gates: list | None = None, affects: list | None = None) -> dict:
    d = {"id": cd_id, "title": f"Decision {cd_id}", "state": state, "gates": gates or []}
    if affects is not None:
        d["affects"] = affects
    return d


def _criterion(crit_id: str, text: str = "criterion text", status: str = "open", met_by=None, blocked_by=None) -> dict:
    d: dict = {"id": crit_id, "text": text, "status": status}
    if met_by is not None:
        d["met_by"] = met_by
    if blocked_by is not None:
        d["blocked_by"] = blocked_by
    return d


def _doc_dict(tier_items: list | None = None, candidate_decisions: list | None = None) -> dict:
    return {"document": _DOC_META, "tier_items": tier_items or [], "candidate_decisions": candidate_decisions or []}


def _build(tier_items: list | None = None, candidate_decisions: list | None = None) -> RoadmapDocument:
    return RoadmapDocument.model_validate(_doc_dict(tier_items, candidate_decisions))


class TestToxicClassification:
    def test_ratified_only_ring_is_benign(self) -> None:
        """A pending-CD build-then-ratify 2-cycle (item demands the CD ratified; the CD demands
        evidence back) is benign -- red if the until value is ignored so every blocked_by edge is
        treated as completion-demanding."""
        doc = _build(
            tier_items=[_item("T9.a", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "CD.90", "until": "ratified"}])])],
            candidate_decisions=[_cd("CD.90", gates=["T9.a"])],
        )
        assert toxic_sccs(doc) == []
        assert toxic_node_ids(doc) == []

    def test_completion_demanding_ring_is_toxic(self) -> None:
        """A ring carrying an internal completion-demanding edge is toxic."""
        doc = _build(
            tier_items=[
                _item("T9.b", depends_on=["T9.c"]),
                _item("T9.c", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "T9.b", "until": "complete"}])]),
            ]
        )
        sccs = toxic_sccs(doc)
        assert sccs == [frozenset({"T9.b", "T9.c"})]
        assert toxic_node_ids(doc) == ["T9.b", "T9.c"]

    def test_blocked_by_until_ratified_alone_never_makes_a_ring_toxic(self) -> None:
        doc = _build(
            tier_items=[
                _item("T9.p", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "CD.91", "until": "ratified"}])]),
            ],
            candidate_decisions=[_cd("CD.91", gates=["T9.p"])],
        )
        assert toxic_sccs(doc) == []

    def test_rec_3394_shape_yields_no_toxic_scc(self) -> None:
        """A rehome-out criterion plus a blocked_by-until-ratified edge to a CD that gates the
        rehome SOURCE (not the target) yields no toxic SCC -- mirrors T2.51/T2.53/CD.41's shape."""
        doc = _build(
            tier_items=[
                _item("T9.d", exit_criteria=[_criterion("c1", status="rehomed", met_by="T9.e")]),
                _item("T9.e", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "CD.91", "until": "ratified"}])]),
            ],
            candidate_decisions=[_cd("CD.91", gates=["T9.d"])],
        )
        assert toxic_sccs(doc) == []

    def test_deferred_post_mvp_item_participates_in_toxic_ring(self) -> None:
        """NON_TERMINAL admits deferred_post_mvp -- a parked item's toxic ring is still reported."""
        doc = _build(
            tier_items=[
                _item("T9.f", depends_on=["T9.g"], status="deferred_post_mvp"),
                _item("T9.g", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "T9.f", "until": "complete"}])]),
            ]
        )
        assert toxic_node_ids(doc) == ["T9.f", "T9.g"]

    def test_reserved_item_prunes_edges_entirely(self) -> None:
        doc = _build(tier_items=[_item("T9.h", depends_on=["T9.i"]), _item("T9.i", status="reserved")])
        assert build_blocking_graph(doc) == []

    def test_complete_status_prunes_depends_on_edge(self) -> None:
        doc = _build(tier_items=[_item("T9.j", depends_on=["T9.k"]), _item("T9.k", status="complete")])
        assert build_blocking_graph(doc) == []

    def test_criterion_blocked_by_its_own_owning_item_is_a_toxic_self_loop(self) -> None:
        """Unlike depends_on, blocked_by is deliberately excluded from RoadmapDocument's own
        load-time cycle DFS (scripts/platform_roadmap_models.py), so a criterion blocked_by its
        own owning item is a legitimate, reachable shape -- and a true self-loop deadlock."""
        doc = _build(
            tier_items=[_item("T9.m", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "T9.m", "until": "complete"}])])]
        )
        assert toxic_node_ids(doc) == ["T9.m"]


class TestBuildBlockingGraph:
    def test_depends_on_produces_complete_demand_edge(self) -> None:
        doc = _build(tier_items=[_item("T9.a", depends_on=["T9.b"]), _item("T9.b")])
        assert BlockingEdge("T9.a", "T9.b", "complete", "depends_on") in build_blocking_graph(doc)

    def test_cd_gates_produces_ratified_and_reverse_evidence_edges(self) -> None:
        doc = _build(tier_items=[_item("T9.a")], candidate_decisions=[_cd("CD.1", gates=["T9.a"])])
        edges = build_blocking_graph(doc)
        assert BlockingEdge("T9.a", "CD.1", "ratified", "cd_gates") in edges
        assert BlockingEdge("CD.1", "T9.a", "evidence", "cd_reverse_evidence") in edges

    def test_decision_required_before_produces_ratified_edge(self) -> None:
        doc = _build(
            tier_items=[_item("T9.a", decision_required_before=["decision_required_before(CD.2 ratified)"])],
            candidate_decisions=[_cd("CD.2")],
        )
        assert BlockingEdge("T9.a", "CD.2", "ratified", "decision_required_before") in build_blocking_graph(doc)

    def test_decision_required_before_ignores_a_terminal_cd(self) -> None:
        doc = _build(
            tier_items=[_item("T9.a", decision_required_before=["needs CD.2"])],
            candidate_decisions=[_cd("CD.2", state="ratified")],
        )
        assert build_blocking_graph(doc) == []

    def test_blocked_by_demand_matches_literal_until_complete(self) -> None:
        doc = _build(
            tier_items=[
                _item("T9.a", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "T9.b", "until": "complete"}])]),
                _item("T9.b"),
            ]
        )
        assert BlockingEdge("T9.a", "T9.b", "complete", "criterion_blocked_by") in build_blocking_graph(doc)

    def test_blocked_by_demand_matches_literal_until_ratified(self) -> None:
        doc = _build(
            tier_items=[_item("T9.a", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "CD.3", "until": "ratified"}])])],
            candidate_decisions=[_cd("CD.3")],
        )
        assert BlockingEdge("T9.a", "CD.3", "ratified", "criterion_blocked_by") in build_blocking_graph(doc)

    def test_affects_is_excluded_from_the_graph(self) -> None:
        doc = _build(tier_items=[_item("T9.a")], candidate_decisions=[_cd("CD.4", affects=["T9.a"])])
        assert build_blocking_graph(doc) == []

    def test_tier_shortcut_depends_on_resolves_to_non_terminal_members_only(self) -> None:
        doc = _build(
            tier_items=[
                _item("T8.z", tier="T8", depends_on=["T9"]),
                _item("T9.member", tier="T9"),
                _item("T9.done", tier="T9", status="complete"),
            ]
        )
        targets = {e.target for e in build_blocking_graph(doc) if e.source == "T8.z"}
        assert targets == {"T9.member"}


class TestToxicNodeIds:
    def test_returns_sorted_flat_union_of_toxic_sccs(self) -> None:
        doc = _build(
            tier_items=[
                _item("T9.z", depends_on=["T9.y"]),
                _item("T9.y", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "T9.z", "until": "complete"}])]),
            ]
        )
        assert toxic_node_ids(doc) == ["T9.y", "T9.z"]

    def test_empty_document_yields_no_toxic_ids(self) -> None:
        doc = _build()
        assert toxic_node_ids(doc) == []
        assert toxic_sccs(doc) == []


class TestSafeLoadAndCli:
    def test_safe_load_returns_document_on_success(self, tmp_path) -> None:
        path = tmp_path / "roadmap.yaml"
        path.write_text(yaml.safe_dump(_doc_dict()), encoding="utf-8")
        doc = _safe_load(path)
        assert isinstance(doc, RoadmapDocument)

    def test_safe_load_returns_none_on_malformed_yaml(self, tmp_path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("not: [valid, yaml", encoding="utf-8")
        assert _safe_load(path) is None

    def test_safe_load_returns_none_on_schema_validation_failure(self, tmp_path) -> None:
        path = tmp_path / "invalid_schema.yaml"
        path.write_text(yaml.safe_dump({"document": {"id": "x"}}), encoding="utf-8")
        assert _safe_load(path) is None

    def test_report_prints_census_and_returns_zero(self, tmp_path, capsys) -> None:
        path = tmp_path / "roadmap.yaml"
        path.write_text(
            yaml.safe_dump(
                _doc_dict(
                    tier_items=[
                        _item("T9.a", depends_on=["T9.b"]),
                        _item("T9.b", exit_criteria=[_criterion("c1", blocked_by=[{"ref": "T9.a", "until": "complete"}])]),
                    ]
                )
            ),
            encoding="utf-8",
        )
        exit_code = main(["--report", "--roadmap-path", str(path)])
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "Toxic SCCs: 1" in out
        assert "T9.a" in out and "T9.b" in out

    def test_report_returns_one_on_load_failure(self, tmp_path, capsys) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("not: [valid, yaml", encoding="utf-8")
        exit_code = main(["--report", "--roadmap-path", str(path)])
        assert exit_code == 1
        assert "did not load" in capsys.readouterr().out

    def test_main_without_report_flag_prints_help(self, capsys) -> None:
        exit_code = main([])
        assert exit_code == 0
        assert "usage" in capsys.readouterr().out.lower()
