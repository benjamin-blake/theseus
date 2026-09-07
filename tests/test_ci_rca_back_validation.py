"""Unit tests for scripts.ci_rca.back_validation.

All tests are free of live AWS, network, and DuckLake-reader dependencies: cache_rows is
always injected (never fetched). A dedicated test asserts no reader is constructed, guarding
the Decision-88 zero-egress claim.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from scripts.ci_rca.back_validation import (
    DEFAULT_WINDOW_DAYS,
    _parse_ts_utc,
    _row_context_v2,
    _row_ts,
    find_preventive_regressions,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _rec(
    rec_id: str,
    source: str = "ci_rca",
    status: str = "open",
    file: str = "scripts/validate.py",
    created_days_ago: float = 1,
    closed_days_ago: float | None = None,
    preventive_action: str | None = None,
    closure_artifact: str | None = None,
    closure_waiver_category: str | None = None,
) -> dict:
    created_ts = NOW - timedelta(days=created_days_ago)
    ctx = {}
    if preventive_action is not None:
        ctx["preventive_action"] = preventive_action
    if closure_artifact is not None:
        ctx["closure_artifact"] = closure_artifact
    if closure_waiver_category is not None:
        ctx["closure_waiver_category"] = closure_waiver_category
    row = {
        "id": rec_id,
        "source": source,
        "status": status,
        "file": file,
        "created_timestamp": created_ts.isoformat(),
        "context_v2_json": json.dumps(ctx) if ctx else "",
    }
    if closed_days_ago is not None:
        row["last_updated_timestamp"] = (NOW - timedelta(days=closed_days_ago)).isoformat()
    return row


class TestFindPreventiveRegressions:
    def test_flags_open_rec_matching_closed_prior_with_preventive_action(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, window_days=DEFAULT_WINDOW_DAYS, now=NOW)
        assert flags == [
            {
                "new_rec_id": "rec-200",
                "prior_rec_id": "rec-100",
                "file": "scripts/validate.py",
                "preventive_action_excerpt": "Promote the check to --pre tier.",
                "closure_artifact": None,
                "artifact_status": None,
                "grade": "CANDIDATE",
            }
        ]

    def test_no_flag_when_prior_rec_is_open(self) -> None:
        rows = [
            _rec("rec-100", status="open", created_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_no_flag_when_files_differ(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, file="scripts/a.py", preventive_action="Fix a.py."),
            _rec("rec-200", status="open", created_days_ago=1, file="scripts/b.py"),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_no_flag_when_prior_rec_has_no_preventive_action(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action=None),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_no_flag_when_prior_rec_is_different_source(self) -> None:
        rows = [
            _rec("rec-100", source="ci_rca_probe_health", status="closed", closed_days_ago=10, preventive_action="Fix it."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_window_filtering_excludes_old_open_recs(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=20, preventive_action="Fix it."),
            _rec("rec-200", status="open", created_days_ago=30),  # outside 14d window
        ]
        assert find_preventive_regressions(rows, window_days=14, now=NOW) == []

    def test_empty_on_no_matches(self) -> None:
        assert find_preventive_regressions([], now=NOW) == []

    def test_picks_most_recently_closed_prior_when_multiple_match(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=20, preventive_action="Older fix."),
            _rec("rec-101", status="closed", closed_days_ago=5, preventive_action="Newer fix."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["prior_rec_id"] == "rec-101"
        assert flags[0]["preventive_action_excerpt"] == "Newer fix."

    def test_no_reader_constructed_in_read_path(self) -> None:
        """Critical Decision-88 guard: find_preventive_regressions never builds a DuckLake reader.

        Patches make_reader to raise; the function must still run correctly from the
        injected cache_rows list without ever touching the reader.
        """

        def _boom(*args, **kwargs):
            raise AssertionError("find_preventive_regressions() must not construct a DuckLake reader")

        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        with patch("src.common.ducklake_reader_client.make_reader", side_effect=_boom):
            flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1

    # -- Decision 184 artifact-existence grading (PLAN-escape-closure-obligation) ---------------

    def test_verified_present_grades_existing_artifact(self) -> None:
        """A prior rec naming a closure_artifact that still statically exists grades
        VERIFIED-PRESENT."""
        rows = [
            _rec(
                "rec-100",
                status="closed",
                closed_days_ago=10,
                preventive_action="Add a fixture.",
                closure_artifact="fixture:tests/fixtures/__init__.py",
            ),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["grade"] == "VERIFIED-PRESENT"
        assert flags[0]["closure_artifact"] == "fixture:tests/fixtures/__init__.py"
        assert flags[0]["artifact_status"] == "present"

    def test_named_but_absent_artifact_grades_confirmed_absent(self) -> None:
        """The known-bad fixture: a prior rec naming a closure_artifact that no longer resolves
        grades CONFIRMED-ABSENT."""
        rows = [
            _rec(
                "rec-100",
                status="closed",
                closed_days_ago=10,
                preventive_action="Add a shard.",
                closure_artifact="shard:this-shard-id-does-not-exist-anywhere",
            ),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["grade"] == "CONFIRMED-ABSENT"
        assert flags[0]["artifact_status"] == "absent"

    def test_waiver_grades_waived(self) -> None:
        """A prior rec naming a closure_waiver_category (no artifact) grades WAIVED."""
        rows = [
            _rec(
                "rec-100",
                status="closed",
                closed_days_ago=10,
                preventive_action="Environment-only, no fix landed.",
                closure_waiver_category="environment_only",
            ),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["grade"] == "WAIVED"
        assert flags[0]["closure_artifact"] is None
        assert flags[0]["artifact_status"] is None

    def test_historical_row_with_neither_field_grades_candidate(self) -> None:
        """A prior rec carrying neither closure_artifact nor closure_waiver_category (every
        historical row filed before Decision 184) still grades CANDIDATE -- the unchanged
        file-only pairing fallback."""
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["grade"] == "CANDIDATE"

    def test_superseded_prior_rec_now_pairs(self) -> None:
        """D-N6: Decision 184 point 3 binds closed AND superseded -- a superseded prior rec
        carrying a preventive_action now pairs too (widened from closed-only)."""
        rows = [
            _rec("rec-100", status="superseded", closed_days_ago=10, preventive_action="Superseded, but claimed a fix."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["prior_rec_id"] == "rec-100"
        assert flags[0]["grade"] == "CANDIDATE"

    def test_grading_uses_no_reader_either(self) -> None:
        """The Decision-88 zero-egress guard extends to the new grading path: artifact_exists
        is a pure filesystem check, never a DuckLake reader."""

        def _boom(*args, **kwargs):
            raise AssertionError("grading must not construct a DuckLake reader")

        rows = [
            _rec(
                "rec-100",
                status="closed",
                closed_days_ago=10,
                preventive_action="Add a fixture.",
                closure_artifact="fixture:tests/fixtures/__init__.py",
            ),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        with patch("src.common.ducklake_reader_client.make_reader", side_effect=_boom):
            flags = find_preventive_regressions(rows, now=NOW)
        assert flags[0]["grade"] == "VERIFIED-PRESENT"


class TestTimestampParseFallbacksAndMalformedContext:
    """Closes this module's pre-existing 79.7% coverage gap (unbaselined 100% standard): the
    timestamp-parse fallback branches and the malformed-context branch, none of which the
    Decision 184 grading tests above happen to exercise."""

    def test_parse_ts_utc_naive_datetime_treated_as_utc(self) -> None:
        assert _parse_ts_utc("2026-01-01 00:00:00") == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_parse_ts_utc_unparseable_string_returns_none(self) -> None:
        assert _parse_ts_utc("definitely not a timestamp") is None

    def test_row_ts_missing_field_returns_none(self) -> None:
        assert _row_ts({}) is None

    def test_row_ts_datetime_instance_naive_gets_utc_attached(self) -> None:
        assert _row_ts({"created_timestamp": datetime(2026, 1, 1)}) == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_row_ts_datetime_instance_aware_passed_through(self) -> None:
        aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _row_ts({"created_timestamp": aware}) == aware

    def test_row_ts_duck_typed_isoformat_object(self) -> None:
        """A date object has .isoformat() but is NOT a datetime instance -- the duck-typed
        branch, distinct from the datetime-instance branch above."""
        assert _row_ts({"created_timestamp": date(2026, 1, 1)}) == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_row_ts_duck_typed_isoformat_raising_returns_none(self) -> None:
        class _BadIsoformat:
            def isoformat(self) -> str:
                raise ValueError("boom")

        assert _row_ts({"created_timestamp": _BadIsoformat()}) is None

    def test_row_context_v2_malformed_json_returns_empty_dict(self) -> None:
        assert _row_context_v2({"context_v2_json": "{not valid json"}) == {}

    def test_find_preventive_regressions_defaults_now_when_omitted(self) -> None:
        """The now=None default path (real UTC clock) is reachable and does not raise."""
        assert find_preventive_regressions([]) == []

    def test_ci_rca_row_with_no_file_is_skipped(self) -> None:
        """A source=ci_rca row carrying no file at all is silently skipped -- neither an
        AttributeError nor a false pairing against the empty-string key."""
        rows = [
            {"id": "rec-050", "source": "ci_rca", "status": "closed", "file": ""},
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["prior_rec_id"] == "rec-100"
