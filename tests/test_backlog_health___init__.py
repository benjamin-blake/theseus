"""Facade surface test for scripts/backlog_health/__init__.py (PLAN-backlog-health-detection)."""

from __future__ import annotations

import scripts.backlog_health as facade
from scripts.backlog_health import census, classify, escalate, probe


class TestFacadeReExports:
    def test_census_surface(self) -> None:
        assert facade.run_census is census.run_census
        assert facade.read_open_recs is census.read_open_recs
        assert facade.collect_recent_commits is census.collect_recent_commits
        assert facade.classify_command is census.classify_command
        assert facade.BUCKETS == census.BUCKETS
        assert facade.PROBEABLE == census.PROBEABLE
        assert facade.PROSE_ONLY == census.PROSE_ONLY
        assert facade.UNPROBEABLE_UNSAFE == census.UNPROBEABLE_UNSAFE
        assert facade.UNPROBEABLE_SHAPE == census.UNPROBEABLE_SHAPE
        assert facade.EXPECTED_FAIL_MISSING_NODE == census.EXPECTED_FAIL_MISSING_NODE

    def test_probe_surface(self) -> None:
        assert facade.run_all is probe.run_all
        assert facade.run_one is probe.run_one
        assert facade.isolation_available is probe.isolation_available
        assert facade.VERDICTS == probe.VERDICTS
        assert facade.PASS == probe.PASS
        assert facade.FAIL == probe.FAIL
        assert facade.TIMEOUT == probe.TIMEOUT
        assert facade.BUDGET_EXHAUSTED == probe.BUDGET_EXHAUSTED
        assert facade.ISOLATION_UNAVAILABLE == probe.ISOLATION_UNAVAILABLE

    def test_classify_surface(self) -> None:
        assert facade.classify_all is classify.classify_all
        assert facade.classify_probe_split is classify.classify_probe_split
        assert facade.classify_acceptance_quality is classify.classify_acceptance_quality
        assert facade.classify_dependency_refs is classify.classify_dependency_refs
        assert facade.classify_premise_dead_and_duplicates is classify.classify_premise_dead_and_duplicates

    def test_escalate_surface(self) -> None:
        assert facade.run_all_episodes is escalate.run_all_episodes
        assert facade.build_findings is escalate.build_findings
        assert facade.rejoin_probe_verdicts is escalate.rejoin_probe_verdicts
        assert facade.ALL_SOURCES == escalate.ALL_SOURCES
        assert facade.SOURCE_VACUOUS_PROBE == escalate.SOURCE_VACUOUS_PROBE
        assert facade.SOURCE_ACCEPTANCE_QUALITY == escalate.SOURCE_ACCEPTANCE_QUALITY
        assert facade.SOURCE_DEPENDENCY_REF == escalate.SOURCE_DEPENDENCY_REF
        assert facade.SOURCE_PREMISE_DEAD == escalate.SOURCE_PREMISE_DEAD

    def test_all_dunder_matches_declared_names(self) -> None:
        for name in facade.__all__:
            assert hasattr(facade, name), f"__all__ declares {name!r} but it is not importable from the facade"

    def test_all_sources_match_source_registry_constants(self) -> None:
        assert set(facade.ALL_SOURCES) == {
            facade.SOURCE_VACUOUS_PROBE,
            facade.SOURCE_ACCEPTANCE_QUALITY,
            facade.SOURCE_DEPENDENCY_REF,
            facade.SOURCE_PREMISE_DEAD,
        }
