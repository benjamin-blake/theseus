"""Backlog-health scheduled monitor (PLAN-backlog-health-detection, Decision 62 2026-06-16
amendment / CD.12: alarm-not-gate). Facade re-exporting the package's public surface (Decision
80/104/124 pattern) -- import from here, not from the submodules directly.

Pipeline: census.run_census -> probe.run_all -> escalate.run_all_episodes, joined by
classify.classify_all. See .github/workflows/backlog-health.yml for the three-job production
wiring and __main__.py for the local/CLI wiring (`python -m scripts.backlog_health <subcommand>`).
"""

from __future__ import annotations

from scripts.backlog_health.census import (
    BUCKETS,
    EXPECTED_FAIL_MISSING_NODE,
    PROBEABLE,
    PROSE_ONLY,
    UNPROBEABLE_SHAPE,
    UNPROBEABLE_UNSAFE,
    classify_command,
    collect_recent_commits,
    read_open_recs,
    run_census,
)
from scripts.backlog_health.classify import (
    classify_acceptance_quality,
    classify_all,
    classify_dependency_refs,
    classify_premise_dead_and_duplicates,
    classify_probe_split,
)
from scripts.backlog_health.escalate import (
    ALL_SOURCES,
    SOURCE_ACCEPTANCE_QUALITY,
    SOURCE_DEPENDENCY_REF,
    SOURCE_PREMISE_DEAD,
    SOURCE_VACUOUS_PROBE,
    build_findings,
    rejoin_probe_verdicts,
    run_all_episodes,
)
from scripts.backlog_health.probe import (
    BUDGET_EXHAUSTED,
    FAIL,
    ISOLATION_UNAVAILABLE,
    PASS,
    TIMEOUT,
    VERDICTS,
    isolation_available,
    run_all,
    run_one,
)

__all__ = [
    "ALL_SOURCES",
    "BUCKETS",
    "BUDGET_EXHAUSTED",
    "EXPECTED_FAIL_MISSING_NODE",
    "FAIL",
    "ISOLATION_UNAVAILABLE",
    "PASS",
    "PROBEABLE",
    "PROSE_ONLY",
    "SOURCE_ACCEPTANCE_QUALITY",
    "SOURCE_DEPENDENCY_REF",
    "SOURCE_PREMISE_DEAD",
    "SOURCE_VACUOUS_PROBE",
    "TIMEOUT",
    "UNPROBEABLE_SHAPE",
    "UNPROBEABLE_UNSAFE",
    "VERDICTS",
    "build_findings",
    "classify_acceptance_quality",
    "classify_all",
    "classify_command",
    "classify_dependency_refs",
    "classify_premise_dead_and_duplicates",
    "classify_probe_split",
    "collect_recent_commits",
    "isolation_available",
    "read_open_recs",
    "rejoin_probe_verdicts",
    "run_all",
    "run_all_episodes",
    "run_census",
    "run_one",
]
