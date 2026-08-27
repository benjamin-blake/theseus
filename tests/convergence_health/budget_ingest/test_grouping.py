"""Episode grouping onto the (branch, dominant_phase) rec grain, and the rec text the group
renders -- including the worst-episode pairing and the breach rationale written into every rec.

Split out of the retired single-file test_budget_ingest.py monolith (rec-3288 wave-4 fixups).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.convergence_health import budget_ingest as bi

from .conftest import _artifact, _budget_block, _caller_for, _fetcher_for, _ingest_one


class TestGroupEpisodes:
    def _scan(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        artifacts = [_artifact(i + 1) for i in range(len(blocks))]
        archives = {i + 1: {"budget": block} for i, block in enumerate(blocks)}
        scan = bi.collect_budget_episodes(gh_caller=_caller_for(artifacts), artifact_fetcher=_fetcher_for(archives))
        return bi._group_episodes(scan["episodes"])

    def test_within_budget_and_forced_waived_outcomes_are_not_ingested(self) -> None:
        groups = self._scan([_budget_block(outcome="within_budget"), _budget_block(outcome="forced_waived")])
        assert groups == []

    def test_both_breach_class_outcomes_are_ingested(self) -> None:
        for outcome in ("breach", "forced_ceiling_breach"):
            groups = self._scan([_budget_block(outcome=outcome)])
            assert len(groups) == 1, outcome
            assert groups[0]["outcomes"] == [outcome]

    def test_bypass_is_not_an_ingested_outcome(self) -> None:
        """Correctness 3: --ignore-budget is hard-rejected when CI=true, so no CI-uploaded manifest
        can carry outcome=bypass -- and this path would file it under source=budget_breach, hiding
        it from every budget_bypass consumer."""
        assert "bypass" not in bi.INGESTED_OUTCOMES
        assert self._scan([_budget_block(outcome="bypass")]) == []

    def test_repeat_breaches_on_one_key_collapse_to_one_group(self) -> None:
        groups = self._scan([_budget_block(elapsed_s=420.0), _budget_block(elapsed_s=600.0)])
        assert len(groups) == 1
        assert groups[0]["runs"] == 2
        assert groups[0]["worst"]["elapsed_s"] == 600.0

    def test_distinct_dominant_phases_are_distinct_episodes(self) -> None:
        groups = self._scan([_budget_block(dominant_phase="pytest"), _budget_block(dominant_phase="mypy")])
        assert len(groups) == 2

    def test_distinct_branches_are_distinct_episodes(self) -> None:
        groups = self._scan([_budget_block(branch="claude/a"), _budget_block(branch="claude/b")])
        assert len(groups) == 2

    def test_mixed_outcomes_on_one_key_are_recorded_once_each(self) -> None:
        groups = self._scan(
            [
                _budget_block(outcome="breach"),
                _budget_block(outcome="breach"),
                _budget_block(outcome="forced_ceiling_breach"),
            ]
        )
        assert len(groups) == 1
        assert sorted(groups[0]["outcomes"]) == ["breach", "forced_ceiling_breach"]

    def test_the_worst_episode_is_tracked_not_the_first_seen(self) -> None:
        """Correctness 2: the worst elapsed must be paired with ITS OWN episode's limit_s and run id.
        A group can mix limits (breach 300s, forced_ceiling_breach 1500s), so the reported ratio
        must not describe a limit the worst run never had -- and must not flip with arrival order."""
        slow = _budget_block(outcome="breach", elapsed_s=400.0, limit_s=300.0, run_id="111")
        slower = _budget_block(outcome="forced_ceiling_breach", elapsed_s=1600.0, limit_s=1500.0, run_id="222")
        for blocks in ([slow, slower], [slower, slow]):
            groups = self._scan(blocks)
            assert len(groups) == 1
            assert groups[0]["worst"]["elapsed_s"] == 1600.0
            assert groups[0]["worst"]["limit_s"] == 1500.0
            assert groups[0]["worst"]["run_id"] == "222"
            context = bi._build_ingest_context(groups[0])
            assert "worst elapsed 26.7 min (limit 25.0 min)" in context
            assert "actions/runs/222" in context
            assert "actions/runs/111" not in context


class TestBreachRationale:
    """Correctness 5: the motivating scenario is NOT 'breached then merged green' -- a breach reds
    pr-validate (validate.py exits 1 right after recording the outcome). The real gap is that the
    credential-free job cannot file the warehouse rec, so the breach population is invisible to the
    warehouse, and a breach on a PR head later fixed and merged leaves no trace at all. The claim is
    written verbatim into every ingested rec, so all three copies have to say the true thing."""

    def _context(self) -> str:
        captured: dict[str, Any] = {}
        _ingest_one(portal_caller=lambda action, fields: captured.update(fields))
        return str(captured["context"])

    def test_the_filed_rec_context_states_the_true_rationale(self) -> None:
        context = self._context()
        assert "reds pr-validate, so the run never merges green" in context
        assert "leaves no warehouse trace at all" in context

    def test_the_module_docstring_states_the_true_rationale(self) -> None:
        docstring = bi.__doc__ or ""
        assert "REDS pr-validate" in docstring
        assert "leaves no warehouse trace at all" in docstring

    def test_the_workflow_header_states_the_true_rationale(self) -> None:
        workflow = Path(__file__).resolve().parents[3] / ".github/workflows/convergence-health.yml"
        header = workflow.read_text(encoding="utf-8")
        assert "which does red pr-validate" in header
        assert "leaves no warehouse trace at all" in header
