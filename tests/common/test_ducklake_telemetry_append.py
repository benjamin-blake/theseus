"""Mirror test for src/common/ducklake_telemetry_append.py (recording fake connection and fake part 1 primitives)."""

from __future__ import annotations

from typing import Any

import pytest

from src.common import ducklake_telemetry_append as adapter
from src.common.ducklake_scd2_schema import DuckLakeRuntimeError, load_field_semantics
from src.common.ducklake_telemetry_txn import TelemetryRequestError
from src.telemetry.gate import GateError, GrainConflictError
from tests.fixtures.telemetry_append_fakes import (
    NOW,
    RESOLVED,
    TENANT,
    AdapterKit,
    parse,
    session_row,
    specs,
    transcript_row,
)

SEMANTICS = load_field_semantics()
REAL_REF = "repo:example"


def run(request: Any) -> adapter.AppendOutcome:
    return adapter.append_request(object(), request, tenant_id=TENANT, specs=specs(), semantics=SEMANTICS, now=NOW)


def test_rule_rejection_opens_no_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    kit = AdapterKit(lookup_result=("01CRZ3NDEKTSV4RRFFQ69G5FCX", "registered")).install(monkeypatch)
    bad = parse(REAL_REF, ("telemetry_sessions", [session_row(workflow=None)]))
    with pytest.raises(GateError):
        run(bad)
    conflict = parse(REAL_REF, ("telemetry_sessions", [session_row(), session_row(workflow="plan")]))
    with pytest.raises(GrainConflictError):
        run(conflict)
    assert "BEGIN" not in kit.events and not [e for e in kit.events if e.startswith("execute")]


def test_first_sight_reprepares_only_when_the_id_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = adapter.prepare_batch

    def counting(spec: Any, rows: Any, **kw: Any) -> Any:
        calls.append(kw["project_id"])
        return real(spec, rows, **kw)

    monkeypatch.setattr(adapter, "prepare_batch", counting)
    AdapterKit().install(monkeypatch)
    out = run(parse(REAL_REF, ("telemetry_sessions", [session_row()])))
    assert calls == [adapter.SENTINEL_PROJECT_ID, RESOLVED] and out.project_registration == "created"
    calls.clear()
    AdapterKit(lookup_result=(RESOLVED, "registered")).install(monkeypatch)
    out = run(parse(REAL_REF, ("telemetry_sessions", [session_row()])))
    assert calls == [RESOLVED] and out.project_registration == "existing" and out.project_id == RESOLVED


def test_sentinel_never_reaches_execute_prepared(monkeypatch: pytest.MonkeyPatch) -> None:
    kit = AdapterKit().install(monkeypatch)
    run(parse(REAL_REF, ("telemetry_transcripts", [transcript_row()]), ("telemetry_sessions", [session_row()])))
    assert kit.executed_project_ids and all(ids == {RESOLVED} for _, ids in kit.executed_project_ids)
    kit = AdapterKit().install(monkeypatch)
    conflict = parse(REAL_REF, ("telemetry_sessions", [session_row(), session_row(workflow="plan")]))
    with pytest.raises(GrainConflictError) as caught:
        run(conflict)
    assert caught.value.event_id is None and caught.value.row == 1

    real = adapter._prepare_all
    monkeypatch.setattr(
        adapter,
        "_prepare_all",
        lambda request, specs, **kw: real(request, specs, **{**kw, "project_id": adapter.SENTINEL_PROJECT_ID}),
    )
    guarded = AdapterKit().install(monkeypatch)
    with pytest.raises(DuckLakeRuntimeError, match="resolved project id"):
        run(parse(REAL_REF, ("telemetry_sessions", [session_row()])))
    assert not [e for e in guarded.events if e.startswith("execute")]


def test_batches_execute_in_request_order_in_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    kit = AdapterKit().install(monkeypatch)
    out = run(parse(REAL_REF, ("telemetry_transcripts", [transcript_row()]), ("telemetry_sessions", [session_row()])))
    begin = kit.events.index("BEGIN")
    assert kit.events[begin:] == ["BEGIN", "resolve", "execute:telemetry_transcripts", "execute:telemetry_sessions", "COMMIT"]
    assert (
        list(out.tables) == ["telemetry_transcripts", "telemetry_sessions"] and out.tables["telemetry_sessions"].inserted == 1
    )
    kit = AdapterKit(fail_on_table="telemetry_sessions").install(monkeypatch)
    with pytest.raises(RuntimeError, match="injected"):
        run(parse(REAL_REF, ("telemetry_transcripts", [transcript_row()]), ("telemetry_sessions", [session_row()])))
    assert "COMMIT" not in kit.events and kit.cache == {}


def test_binding_cached_only_after_the_transaction_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    kit = AdapterKit().install(monkeypatch)
    run(parse(REAL_REF, ("telemetry_sessions", [session_row()])))
    assert kit.cache_at_commit == [{}]
    assert kit.cache == {(TENANT, REAL_REF): RESOLVED}
    kit.events.clear()
    run(parse(REAL_REF, ("telemetry_sessions", [session_row()])))
    assert "lookup" not in kit.events and "resolve" not in kit.events
    hit = AdapterKit(lookup_result=(RESOLVED, "registered")).install(monkeypatch)
    run(parse(REAL_REF, ("telemetry_sessions", [session_row()])))
    assert hit.cache == {(TENANT, REAL_REF): RESOLVED} and "resolve" not in hit.events


def test_unregistered_reserved_ref_is_refused_before_any_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    kit = AdapterKit().install(monkeypatch)
    for ref in ("drill:fresh", "synthetic:deploy-smoke-x"):
        with pytest.raises(TelemetryRequestError) as caught:
            run(parse(ref, ("telemetry_sessions", [session_row()])))
        assert (caught.value.status, caught.value.error_type, caught.value.fields) == (
            403,
            "project_unregistered",
            {"remedy": "register_project"},
        )
    assert kit.events == ["lookup", "lookup"]
    registered = AdapterKit(lookup_result=(RESOLVED, "registered")).install(monkeypatch)
    assert run(parse("drill:registered", ("telemetry_sessions", [session_row()]))).project_id == RESOLVED
    assert "BEGIN" in registered.events
