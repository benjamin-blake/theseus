"""Regression guard for the dead-file-cleanup sweep (PLAN-dead-file-cleanup): pins that the
friction-analysis-log and rejected-suggestions-log routes stay retired from
docs/contracts/file-router.yaml, rather than resurfacing via a copy-paste of a neighbouring
route. The runtime-vs-dead-target detector semantics this route retirement relies on are
already covered by test_validate_placement.py::test_dead_target_reports_failure and
::test_runtime_row_parent_tracked_passes -- the _dead_targets_for_route exercise below is
cheap defence-in-depth, not this module's justification.
"""

from pathlib import Path

import yaml

from scripts.checks.hygiene.validate_placement import _dead_targets_for_route

_ROUTER_PATH = Path(__file__).resolve().parents[4] / "docs" / "contracts" / "file-router.yaml"

_RETIRED_TOPICS = {"friction-analysis-log", "rejected-suggestions-log"}


class TestDeadRouteDetection:
    def test_retired_topics_absent_from_file_router(self) -> None:
        """friction-analysis-log and rejected-suggestions-log must not reappear as routes --
        asserted on topic NAME, never on the deleted files' paths (a hardcoded literal
        naming either retired log file would itself red the plan's live-code-reference
        sweep)."""
        content = yaml.safe_load(_ROUTER_PATH.read_text(encoding="utf-8"))
        topics = {route.get("topic") for route in content["routes"] if isinstance(route, dict)}
        assert not (topics & _RETIRED_TOPICS), f"retired topic(s) resurfaced: {topics & _RETIRED_TOPICS}"

    def test_retired_topics_not_exempted_as_runtime(self) -> None:
        """Neither retired topic may reappear marked runtime: true -- that marker asserts a
        gitignored/regenerated-at-runtime target (file-router.yaml:13-16), which was never true
        for either deleted log, so re-adding either as an exempted runtime row would be a false
        claim rather than a genuine retirement."""
        content = yaml.safe_load(_ROUTER_PATH.read_text(encoding="utf-8"))
        for route in content["routes"]:
            if not isinstance(route, dict):
                continue
            if route.get("topic") in _RETIRED_TOPICS:
                raise AssertionError(f"retired topic present as a route: {route!r}")

    def test_dead_targets_for_route_flags_untracked_non_runtime_target(self) -> None:
        """Defence-in-depth: exercises _dead_targets_for_route directly on a synthetic
        non-runtime route whose target the tracked snapshot omits -- the same detector the
        retired routes relied on before this sweep deleted their targets."""
        route = {"topic": "synthetic-retired-topic", "targets": ["logs/.synthetic-retired.jsonl"]}
        tracked = {"docs/ARCHITECTURE.md"}
        dead = _dead_targets_for_route(route, tracked)
        assert len(dead) == 1
        assert "synthetic-retired-topic" in dead[0]

    def test_dead_targets_for_route_runtime_exemption_still_requires_parent(self) -> None:
        """Defence-in-depth: a runtime: true route is exempt from the target-itself check but
        still requires its parent directory to be tracked -- proves the exemption this sweep
        deliberately did NOT claim for either retired route."""
        route = {"topic": "synthetic-runtime-topic", "targets": ["logs/.synthetic-runtime.jsonl"], "runtime": True}
        tracked = {"logs/.retro-lite-log.jsonl"}
        dead = _dead_targets_for_route(route, tracked)
        assert dead == []
