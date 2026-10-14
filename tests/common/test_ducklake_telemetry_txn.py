"""Coverage home for src/common/ducklake_telemetry_txn.py (fake connection, no duckdb)."""

from __future__ import annotations

import pytest

from src.common import ducklake_telemetry_txn as txn
from src.common.ducklake_scd2_schema import DuckLakeRuntimeError, SchemaGateError
from src.common.ducklake_writes import OCCRetryExhaustedError
from src.telemetry.gate import GrainConflictError


class Con:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.sql.append(sql)


def _no_sleep(_s: float) -> None:
    return None


def test_commits_once_and_reports_metrics() -> None:
    con, metrics = Con(), []
    out = txn.run_telemetry_txn(con, lambda c: "r", metric_sink=lambda n, v: metrics.append(n))
    assert out.result == "r" and out.occ_retries == 0 and out.commit_ms >= 0
    assert con.sql == ["BEGIN TRANSACTION", "COMMIT"]
    assert metrics == ["OccRetryCount", "CommitLatencyMs"]


def test_retries_an_occ_collision_then_commits() -> None:
    con, calls = Con(), []

    def body(_c: object) -> str:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("write-write conflict on commit")
        return "won"

    out = txn.run_telemetry_txn(con, body, sleep=_no_sleep)
    assert out.result == "won" and out.occ_retries == 2 and len(calls) == 3
    assert con.sql.count("ROLLBACK") == 2 and con.sql[-1] == "COMMIT"


@pytest.mark.parametrize(
    "exc",
    [
        GrainConflictError("TELEMETRY_GRAIN_CONFLICT: conflicting row"),
        SchemaGateError("conflict in schema"),
        DuckLakeRuntimeError("conflict"),
        txn.TelemetryRequestError(403, "tenant_unresolved", message="conflict"),
    ],
)
def test_terminal_error_with_conflict_text_is_not_retried(exc: Exception) -> None:
    con, calls = Con(), []

    def body(_c: object) -> None:
        calls.append(1)
        raise exc

    with pytest.raises(type(exc)):
        txn.run_telemetry_txn(con, body, sleep=_no_sleep)
    assert len(calls) == 1 and con.sql == ["BEGIN TRANSACTION", "ROLLBACK"]


def test_caller_extra_terminal_class_is_not_retried() -> None:
    class Mine(Exception):
        pass

    calls = []

    def body(_c: object) -> None:
        calls.append(1)
        raise Mine("conflict")

    with pytest.raises(Mine):
        txn.run_telemetry_txn(Con(), body, terminal=(Mine,), sleep=_no_sleep)
    assert len(calls) == 1


def test_request_error_is_terminal_and_rolled_back() -> None:
    con = Con()

    def body(_c: object) -> None:
        raise txn.TelemetryRequestError(403, "project_unregistered", {"remedy": "register_project"})

    with pytest.raises(txn.TelemetryRequestError) as info:
        txn.run_telemetry_txn(con, body)
    assert (info.value.status, info.value.error_type, info.value.fields) == (
        403,
        "project_unregistered",
        {"remedy": "register_project"},
    )
    assert con.sql[-1] == "ROLLBACK"


def test_exhaustion_raises_occ_retry_exhausted() -> None:
    con, metrics = Con(), []

    def body(_c: object) -> None:
        raise RuntimeError("could not serialize access")

    with pytest.raises(OCCRetryExhaustedError):
        txn.run_telemetry_txn(con, body, max_attempts=3, metric_sink=lambda n, v: metrics.append(n), sleep=_no_sleep)
    assert con.sql.count("BEGIN TRANSACTION") == 3 and metrics == ["OccRetryCount", "CommitLatencyMs"]


def test_non_occ_error_propagates_after_rollback() -> None:
    con = Con()

    def body(_c: object) -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        txn.run_telemetry_txn(con, body)
    assert con.sql == ["BEGIN TRANSACTION", "ROLLBACK"]


def test_request_error_str_carries_no_value() -> None:
    err = txn.TelemetryRequestError(400, "bad_request", {"field": "project_ref"})
    assert str(err) == "bad_request" and "sentinel" not in repr(err.fields)
    assert str(txn.TelemetryRequestError(400, "bad_request", message="field named")) == "field named"


@pytest.mark.parametrize("bad", ["\x00", "a\x00b", "\ud800", "x\udfffy", 5, None, b"x", ["a"]])
def test_invalid_string_field_names_the_field_never_the_value(bad: object) -> None:
    assert txn.invalid_string_field({"ok": "fine", "project_ref": bad}) == "project_ref"


def test_invalid_string_field_accepts_clean_and_astral_strings() -> None:
    assert txn.invalid_string_field({}) is None
    assert txn.invalid_string_field({"a": "plain", "b": "", "c": "\U0001f600", "d": "café"}) is None
    assert txn.invalid_string_field({"a": "x", "b": 1, "c": "\x00"}) == "b"
