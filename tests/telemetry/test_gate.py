"""Mirror test for src/telemetry/gate.py: strict-type rejections, NOT NULL, derived-column
rejection, intra-batch collapse/conflict.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.telemetry.gate import (
    AppendError,
    check_and_normalize_value,
    check_not_null,
    collapse_or_reject_duplicates,
    reject_unknown_or_derived_columns,
)


class TestRejectUnknownOrDerivedColumns:
    def test_accepts_known_columns(self) -> None:
        reject_unknown_or_derived_columns({"a": 1, "b": 2}, frozenset({"a", "b"}), frozenset({"c"}))

    def test_rejects_unknown_column(self) -> None:
        with pytest.raises(AppendError):
            reject_unknown_or_derived_columns({"z": 1}, frozenset({"a"}), frozenset({"c"}))

    def test_rejects_caller_supplied_derived_column(self) -> None:
        with pytest.raises(AppendError):
            reject_unknown_or_derived_columns({"event_id": "x"}, frozenset({"event_id"}), frozenset({"event_id"}))


class TestCheckNotNull:
    def test_passes_when_present(self) -> None:
        check_not_null({"a": 1}, frozenset({"a"}))

    def test_rejects_missing_key(self) -> None:
        with pytest.raises(AppendError):
            check_not_null({}, frozenset({"a"}))

    def test_rejects_none_value(self) -> None:
        with pytest.raises(AppendError):
            check_not_null({"a": None}, frozenset({"a"}))


class TestCheckAndNormalizeValue:
    def test_varchar_accepts_str(self) -> None:
        assert check_and_normalize_value("c", "hello", "VARCHAR") == "hello"

    def test_varchar_rejects_non_str(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", 1, "VARCHAR")

    def test_bigint_accepts_int(self) -> None:
        assert check_and_normalize_value("c", 5, "BIGINT") == 5

    def test_bigint_rejects_bool(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", True, "BIGINT")

    def test_bigint_rejects_float(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", 1.5, "BIGINT")

    def test_bigint_rejects_out_of_int64_range(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", 2**63, "BIGINT")
        with pytest.raises(AppendError):
            check_and_normalize_value("c", -(2**63) - 1, "BIGINT")

    def test_double_accepts_int_and_float(self) -> None:
        assert check_and_normalize_value("c", 1, "DOUBLE") == 1.0
        assert check_and_normalize_value("c", 1.5, "DOUBLE") == 1.5

    def test_double_rejects_bool(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", False, "DOUBLE")

    def test_double_rejects_nan_and_inf(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", float("nan"), "DOUBLE")
        with pytest.raises(AppendError):
            check_and_normalize_value("c", float("inf"), "DOUBLE")

    def test_boolean_accepts_bool_only(self) -> None:
        assert check_and_normalize_value("c", True, "BOOLEAN") is True
        with pytest.raises(AppendError):
            check_and_normalize_value("c", 1, "BOOLEAN")

    def test_varchar_array_accepts_list_of_str(self) -> None:
        assert check_and_normalize_value("c", ["a", "b"], "VARCHAR[]") == ["a", "b"]

    def test_varchar_array_rejects_non_list(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", "a", "VARCHAR[]")

    def test_varchar_array_rejects_non_str_elements(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", ["a", 1], "VARCHAR[]")

    def test_timestamp_accepts_aware_datetime_and_normalises(self) -> None:
        dt = datetime(2026, 9, 25, 10, 0, 0, 999999, tzinfo=timezone.utc)
        result = check_and_normalize_value("c", dt, "TIMESTAMP WITH TIME ZONE")
        assert result.microsecond == 999000
        assert result.tzinfo == timezone.utc

    def test_timestamp_rejects_naive(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", datetime(2026, 9, 25), "TIMESTAMP WITH TIME ZONE")

    def test_timestamp_rejects_non_datetime(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", "2026-09-25", "TIMESTAMP WITH TIME ZONE")

    def test_unsupported_sql_type_rejected(self) -> None:
        with pytest.raises(AppendError):
            check_and_normalize_value("c", 1, "JSON")


class TestCollapseOrRejectDuplicates:
    def test_no_duplicates_passthrough(self) -> None:
        rows = [{"event_id": "a", "parser_version": 1, "x": 1}, {"event_id": "b", "parser_version": 1, "x": 2}]
        deduped, collapsed = collapse_or_reject_duplicates(rows, ("event_id", "parser_version"))
        assert deduped == rows
        assert collapsed == 0

    def test_identical_duplicates_collapse(self) -> None:
        row = {"event_id": "a", "parser_version": 1, "x": 1}
        deduped, collapsed = collapse_or_reject_duplicates([row, dict(row)], ("event_id", "parser_version"))
        assert deduped == [row]
        assert collapsed == 1

    def test_conflicting_duplicates_reject(self) -> None:
        rows = [
            {"event_id": "a", "parser_version": 1, "x": 1},
            {"event_id": "a", "parser_version": 1, "x": 2},
        ]
        with pytest.raises(AppendError):
            collapse_or_reject_duplicates(rows, ("event_id", "parser_version"))

    def test_differing_parser_version_is_not_a_duplicate(self) -> None:
        rows = [
            {"event_id": "a", "parser_version": 1, "x": 1},
            {"event_id": "a", "parser_version": 2, "x": 1},
        ]
        deduped, collapsed = collapse_or_reject_duplicates(rows, ("event_id", "parser_version"))
        assert len(deduped) == 2
        assert collapsed == 0
