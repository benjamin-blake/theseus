"""Mirror test for scripts/backlog_health/escalate.py (PLAN-backlog-health-detection)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from scripts.backlog_health import escalate, probe


def _census_result(probe_payload):
    return {"probe_payload": probe_payload, "recent_commits": [], "open_rows": []}


class TestRejoinProbeVerdicts:
    def test_keeps_verdicts_for_ids_census_actually_sent(self) -> None:
        census_result = _census_result([{"id": "rec-1", "acceptance": "x", "acceptance_sha256": "h"}])
        probe_artifact = {"verdicts": {"rec-1": probe.PASS}}
        assert escalate.rejoin_probe_verdicts(census_result, probe_artifact) == {"rec-1": probe.PASS}

    def test_drops_verdict_for_id_census_never_sent(self) -> None:
        census_result = _census_result([{"id": "rec-1", "acceptance": "x", "acceptance_sha256": "h"}])
        probe_artifact = {"verdicts": {"rec-1": probe.PASS, "rec-999": probe.PASS}}
        assert escalate.rejoin_probe_verdicts(census_result, probe_artifact) == {"rec-1": probe.PASS}

    def test_drops_unrecognised_verdict_value(self) -> None:
        census_result = _census_result([{"id": "rec-1", "acceptance": "x", "acceptance_sha256": "h"}])
        probe_artifact = {"verdicts": {"rec-1": "definitely_passed_trust_me"}}
        assert escalate.rejoin_probe_verdicts(census_result, probe_artifact) == {}

    def test_malformed_artifact_yields_empty(self) -> None:
        census_result = _census_result([{"id": "rec-1", "acceptance": "x", "acceptance_sha256": "h"}])
        assert escalate.rejoin_probe_verdicts(census_result, {}) == {}
        assert escalate.rejoin_probe_verdicts(census_result, {"verdicts": "not-a-dict"}) == {}


class TestBuildFindings:
    def _classification(self):
        return {
            "probe_split": {"vacuous": ["rec-1", "rec-2"], "satisfied_candidate": []},
            "acceptance_quality": {"lint_reject": ["rec-3"], "non_discriminating": []},
            "dependency_refs": {"malformed": ["rec-4"], "dangling": []},
            "premise_dead_and_duplicates": {
                "premise_dead_bootstrap": ["rec-5"],
                "premise_dead_post_anchor": [],
                "near_duplicate": [],
            },
        }

    def test_intersects_against_fresh_open_rows(self) -> None:
        census_result = _census_result([])
        fresh_rows = [{"id": "rec-1"}, {"id": "rec-3"}, {"id": "rec-4"}, {"id": "rec-5"}]  # rec-2 now closed/gone
        findings = escalate.build_findings(census_result, self._classification(), fresh_rows)
        assert findings[escalate.SOURCE_VACUOUS_PROBE] == ["rec-1"]
        assert findings[escalate.SOURCE_ACCEPTANCE_QUALITY] == ["rec-3"]
        assert findings[escalate.SOURCE_DEPENDENCY_REF] == ["rec-4"]
        assert findings[escalate.SOURCE_PREMISE_DEAD] == ["rec-5"]

    def test_all_findings_dropped_when_none_still_open(self) -> None:
        census_result = _census_result([])
        findings = escalate.build_findings(census_result, self._classification(), fresh_open_rows=[])
        assert all(v == [] for v in findings.values())


class TestBuildFieldsAndUpdate:
    def test_build_fields_stamps_context_v2_json(self) -> None:
        fields = escalate.build_fields(escalate.SOURCE_VACUOUS_PROBE, ["rec-2", "rec-1"])
        payload = json.loads(fields["context_v2_json"])
        assert payload == {"finding_ids": ["rec-1", "rec-2"], "count": 2}
        assert fields["source"] == escalate.SOURCE_VACUOUS_PROBE
        assert fields["status"] == "open"
        assert fields["file"] == escalate._ANCHOR_FILE

    def test_build_fields_source_literal_per_branch(self) -> None:
        for source in escalate.ALL_SOURCES:
            fields = escalate.build_fields(source, ["rec-1"])
            assert fields["source"] == source

    def test_build_fields_factory_invokes_build_fields(self) -> None:
        factory = escalate._build_fields_factory(escalate.SOURCE_DEPENDENCY_REF, ["rec-1"])
        result = factory()
        assert result["source"] == escalate.SOURCE_DEPENDENCY_REF
        assert result == escalate.build_fields(escalate.SOURCE_DEPENDENCY_REF, ["rec-1"])

    def test_build_update_returns_none_when_unchanged(self) -> None:
        existing = {"context_v2_json": json.dumps({"finding_ids": ["rec-1"], "count": 1})}
        build = escalate.build_update(escalate.SOURCE_VACUOUS_PROBE, ["rec-1"])
        assert build(existing) is None

    def test_build_update_after_file_time_stamp_is_none_on_first_unchanged_tick(self) -> None:
        # Regression guard: build_fields must stamp context_v2_json so the very NEXT tick's
        # comparison has a real baseline, not an absent field read as "no findings last time".
        filed = escalate.build_fields(escalate.SOURCE_VACUOUS_PROBE, ["rec-1", "rec-2"])
        build = escalate.build_update(escalate.SOURCE_VACUOUS_PROBE, ["rec-1", "rec-2"])
        assert build(filed) is None

    def test_build_update_returns_update_when_changed(self) -> None:
        existing = {"context_v2_json": json.dumps({"finding_ids": ["rec-1"], "count": 1})}
        build = escalate.build_update(escalate.SOURCE_VACUOUS_PROBE, ["rec-1", "rec-2"])
        result = build(existing)
        assert result is not None
        payload = json.loads(result["context_v2_json"])
        assert payload["finding_ids"] == ["rec-1", "rec-2"]

    def test_build_update_handles_malformed_existing_payload(self) -> None:
        existing = {"context_v2_json": "not json"}
        build = escalate.build_update(escalate.SOURCE_VACUOUS_PROBE, ["rec-1"])
        result = build(existing)
        assert result is not None  # malformed baseline treated as "previously empty" -> changed

    def test_build_close_returns_closed_status(self) -> None:
        result = escalate.build_close({"id": "rec-1"})
        assert result["status"] == "closed"
        assert "resolution" in result


class TestRunAllEpisodes:
    def test_dry_run_never_calls_run_episode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run_episode = MagicMock()
        monkeypatch.setattr(escalate.rec_episode, "run_episode", mock_run_episode)
        census_result = _census_result([])
        classification: dict[str, dict[str, list[str]]] = {
            "probe_split": {"vacuous": ["rec-1"], "satisfied_candidate": []},
            "acceptance_quality": {"lint_reject": [], "non_discriminating": []},
            "dependency_refs": {"malformed": [], "dangling": []},
            "premise_dead_and_duplicates": {
                "premise_dead_bootstrap": [],
                "premise_dead_post_anchor": [],
                "near_duplicate": [],
            },
        }
        results = escalate.run_all_episodes(census_result, classification, [{"id": "rec-1"}], dry_run=True)
        mock_run_episode.assert_not_called()
        assert results[escalate.SOURCE_VACUOUS_PROBE]["count"] == 1
        assert results[escalate.SOURCE_ACCEPTANCE_QUALITY]["count"] == 0

    def test_calls_run_episode_once_per_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run_episode = MagicMock(return_value={"action": "none", "rec_id": None})
        monkeypatch.setattr(escalate.rec_episode, "run_episode", mock_run_episode)
        census_result = _census_result([])
        classification: dict[str, dict[str, list[str]]] = {
            "probe_split": {"vacuous": [], "satisfied_candidate": []},
            "acceptance_quality": {"lint_reject": [], "non_discriminating": []},
            "dependency_refs": {"malformed": [], "dangling": []},
            "premise_dead_and_duplicates": {
                "premise_dead_bootstrap": [],
                "premise_dead_post_anchor": [],
                "near_duplicate": [],
            },
        }
        escalate.run_all_episodes(census_result, classification, [], dry_run=False)
        assert mock_run_episode.call_count == len(escalate.ALL_SOURCES)
        called_sources = {call.kwargs["source"] for call in mock_run_episode.call_args_list}
        assert called_sources == set(escalate.ALL_SOURCES)

    def test_over_threshold_reflects_finding_presence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, bool] = {}

        def fake_run_episode(**kwargs):
            captured[kwargs["source"]] = kwargs["over_threshold"]
            return {"action": "none", "rec_id": None}

        monkeypatch.setattr(escalate.rec_episode, "run_episode", fake_run_episode)
        census_result = _census_result([])
        classification: dict[str, dict[str, list[str]]] = {
            "probe_split": {"vacuous": ["rec-1"], "satisfied_candidate": []},
            "acceptance_quality": {"lint_reject": [], "non_discriminating": []},
            "dependency_refs": {"malformed": [], "dangling": []},
            "premise_dead_and_duplicates": {
                "premise_dead_bootstrap": [],
                "premise_dead_post_anchor": [],
                "near_duplicate": [],
            },
        }
        escalate.run_all_episodes(census_result, classification, [{"id": "rec-1"}], dry_run=False)
        assert captured[escalate.SOURCE_VACUOUS_PROBE] is True
        assert captured[escalate.SOURCE_ACCEPTANCE_QUALITY] is False

    def test_never_updates_or_closes_an_individual_rec_by_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # run_episode is the ONLY portal-touching call this module makes; assert no direct
        # scripts.ops_data_portal import/usage exists in the module.
        import inspect

        source = inspect.getsource(escalate)
        assert "ops_data_portal" not in source
