"""Tests for the tests/fixtures/platform_roadmap_state.py process-scoped live-roadmap memo
(rec-4006): live_state_dict() computes the live ROADMAP-PLATFORM.yaml at most once per
(process, latest_decision_ts), returns an independent deep copy on every call, delegates every
non-live path uncached, never memoizes an error result, and is bound to the defining module's
compute_state_dict.

Never touches the live corpus -- every test spies on _real_compute_state_dict, so this file is
sub-second regardless of the live roadmap's own compute cost.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import scripts.platform_roadmap_state
import scripts.preflight._common as _common
import tests.fixtures.platform_roadmap_state as fixtures


@pytest.fixture
def _spy():
    calls: list[str | None] = []

    def _side_effect(yaml_path, *, latest_decision_ts=None):
        calls.append(latest_decision_ts)
        return {"echo_ts": latest_decision_ts, "nested": {"a": [1, 2, 3]}}

    with (
        patch.dict(fixtures._LIVE_STATE_MEMO, clear=True),
        patch.object(fixtures, "_real_compute_state_dict", side_effect=_side_effect) as mock,
    ):
        yield calls, mock


class TestLiveStateMemo:
    def test_live_path_computed_once(self, _spy) -> None:
        calls, mock = _spy
        fixtures.live_state_dict()
        fixtures.live_state_dict(str(fixtures._LIVE_ROADMAP))
        fixtures.live_state_dict(_common.ROADMAP_PLATFORM_PATH)
        assert mock.call_count == 1
        assert calls == [None]

    def test_each_call_returns_independent_copy(self, _spy) -> None:
        result1 = fixtures.live_state_dict()
        result1["nested"]["a"].append(4)
        result1["new_key"] = "mutated"
        result2 = fixtures.live_state_dict()
        assert result2 == {"echo_ts": None, "nested": {"a": [1, 2, 3]}}
        assert result2 is not result1

    def test_non_live_path_passes_through_uncached(self, _spy, tmp_path) -> None:
        calls, mock = _spy
        roadmap = tmp_path / "ROADMAP-PLATFORM.yaml"
        roadmap.write_text("document: {}\n")
        fixtures.live_state_dict(roadmap)
        fixtures.live_state_dict(roadmap)
        assert mock.call_count == 2

    def test_error_result_never_memoized(self, _spy) -> None:
        calls, mock = _spy
        mock.side_effect = [{"error": "boom"}, {"echo_ts": None, "nested": {"a": [1]}}]
        first = fixtures.live_state_dict()
        assert first == {"error": "boom"}
        second = fixtures.live_state_dict()
        assert second == {"echo_ts": None, "nested": {"a": [1]}}
        third = fixtures.live_state_dict()
        assert third == second
        assert mock.call_count == 2

    def test_distinct_decision_ts_are_distinct_entries(self, _spy) -> None:
        calls, mock = _spy
        ts = "2026-06-12T00:00:00+00:00"
        fixtures.live_state_dict(latest_decision_ts=None)
        fixtures.live_state_dict(latest_decision_ts=None)
        fixtures.live_state_dict(latest_decision_ts=ts)
        fixtures.live_state_dict(latest_decision_ts=ts)
        assert mock.call_count == 2
        assert calls == [None, ts]

    def test_bound_to_defining_module(self) -> None:
        assert fixtures._real_compute_state_dict is scripts.platform_roadmap_state.compute_state_dict
