"""Mirror test for the telemetry writer's edge: caps, translation, response shape, adversarial bodies."""

from __future__ import annotations

from typing import Any

import pytest

from src.common import ducklake_telemetry_registration as reg
from src.common.ducklake_scd2_schema import load_field_semantics
from src.common.ducklake_telemetry_txn import TelemetryRequestError
from src.lambdas.ducklake_telemetry_writer import telemetry_actions as actions
from src.lambdas.ducklake_telemetry_writer import telemetry_edge as edge
from src.lambdas.ducklake_telemetry_writer.telemetry_log import RequestStats
from src.telemetry.gate import GateError, GrainConflictError
from tests.fixtures.telemetry_append_fakes import RESOLVED, TENANT, AdapterKit, session_row, transcript_row

SEMANTICS = load_field_semantics()
SECRET = "SECRET-VALUE-9f3a"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> AdapterKit:
    edge.reset_cache()
    reg.clear_telemetry_caches()
    monkeypatch.setattr(reg, "lookup_tenant", lambda con, kind, ref, semantics=None: TENANT)
    return AdapterKit().install(monkeypatch)


def make(body: dict[str, Any], invoke_bytes: int = 100) -> tuple[actions.TelemetryRequest, actions.Deps]:
    principal = reg.CallerPrincipal(kind="aws_account", ref="acct-under-test", role_name="Some")
    request = actions.TelemetryRequest("append_telemetry", body, principal, invoke_bytes, invoke_bytes)
    deps = actions.Deps(SEMANTICS, None, "ducklake_smoke", True, "login", "neon", True, stats=RequestStats())
    return request, deps


def body_of(*batches: tuple[str, list[dict[str, Any]]], **over: Any) -> dict[str, Any]:
    base = {
        "action": "append_telemetry",
        "project_ref": "repo:example",
        "batches": [{"table": t, "rows": r} for t, r in batches],
    }
    return {**base, **over}


def run(body: dict[str, Any], invoke_bytes: int = 100) -> dict[str, Any]:
    request, deps = make(body, invoke_bytes)
    return edge.action_append_telemetry(request, object(), deps)


def refused(body: dict[str, Any], invoke_bytes: int = 100) -> TelemetryRequestError:
    with pytest.raises(TelemetryRequestError) as caught:
        run(body, invoke_bytes)
    return caught.value


def test_caps_are_413_at_the_boundaries() -> None:
    ok = body_of(("telemetry_transcripts", [transcript_row()]))
    assert run(ok, edge.MAX_INVOKE_BODY_BYTES)["ok"] is True
    err = refused(ok, edge.MAX_INVOKE_BODY_BYTES + 1)
    assert (err.status, err.error_type, err.fields["measure"]) == (413, "payload_too_large", "invoke_bytes")
    rows = [transcript_row(external_ref=f"t#{i}", entity_ref=f"t#{i}") for i in range(edge.MAX_ROWS_PER_TABLE)]
    assert run(body_of(("telemetry_transcripts", rows)))["tables"]["telemetry_transcripts"]["submitted"] == 2000
    over = refused(body_of(("telemetry_transcripts", [*rows, rows[0]])))
    assert (over.status, over.error_type, over.fields) == (
        413,
        "too_many_rows",
        {"measure": "rows_per_table", "max": 2000, "table": "telemetry_transcripts"},
    )
    many = dict.fromkeys(("telemetry_transcripts", "telemetry_observations", "telemetry_agents"), rows[:2000])
    total = refused(body_of(*many.items()))
    assert total.fields == {"measure": "rows_per_request", "max": 5000}
    unknown = refused(body_of((SECRET, [{}] * 2001)))
    assert unknown.status == 413 and "table" not in unknown.fields and SECRET not in str(unknown.fields)
    assert refused(body_of(("telemetry_sessions", "x")), 100).status == 400
    assert refused({"action": "append_telemetry", "project_ref": "p", "batches": "x"}).status == 400


def test_request_errors_translate_by_type() -> None:
    cases = [
        (body_of(("telemetry_sessions", [session_row()]), **{SECRET: 1}), 400, "bad_request", "unknown_key"),
        (body_of(("telemetry_sessions", [session_row()]), project_ref=""), 400, "bad_request", "project_ref"),
        (
            body_of(("telemetry_sessions", [session_row()]), ("telemetry_transcripts", [transcript_row()])),
            400,
            "write_order",
            None,
        ),
        (
            body_of(("telemetry_transcripts", [transcript_row(), transcript_row(producer="other")])),
            400,
            "mixed_producer",
            "producer",
        ),
        (body_of(("telemetry_transcripts", [transcript_row(content="x" * 65537)])), 413, "payload_too_large", None),
        (body_of(("telemetry_sessions", [session_row(session_started_at="nope")])), 422, "schema_gate", "wire_timestamp"),
    ]
    for body, status, error_type, reason in cases:
        err = refused(body)
        assert (err.status, err.error_type) == (status, error_type)
        assert err.fields.get("reason") == reason or reason is None
        assert SECRET not in str(err) + str(err.fields)
    large = refused(cases[4][0])
    assert large.fields["rule"] == "inline_within_threshold" and large.fields["threshold"] == 65536


def test_tenant_is_read_once_and_unresolved_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(reg, "lookup_tenant", lambda con, kind, ref, semantics=None: calls.append(ref) or TENANT)
    good = body_of(("telemetry_sessions", [session_row()]))
    run(good)
    run(good)
    assert calls == ["acct-under-test"] and reg.cached_tenant_id("aws_account", "acct-under-test") == TENANT
    reg.clear_telemetry_caches()
    monkeypatch.setattr(reg, "lookup_tenant", lambda con, kind, ref, semantics=None: None)
    err = refused(good)
    assert (err.status, err.error_type, err.fields) == (403, "tenant_unresolved", {"remedy": "register_tenant"})
    assert reg.cached_tenant_id("aws_account", "acct-under-test") is None


def test_response_shape_and_no_value_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    request, deps = make(body_of(("telemetry_transcripts", [transcript_row(content=SECRET, content_sha256="0" * 64)])))
    err = None
    try:
        edge.action_append_telemetry(request, object(), deps)
    except Exception as exc:  # noqa: BLE001 -- the row-rule refusal is mapped by the handler
        err = exc
    assert isinstance(err, GateError) and SECRET not in str(vars(err).values())
    request, deps = make(body_of(("telemetry_transcripts", [transcript_row()]), ("telemetry_sessions", [session_row()])))
    out = edge.action_append_telemetry(request, object(), deps)
    assert out == {
        "ok": True,
        "tenant_id": TENANT,
        "project_id": RESOLVED,
        "project_registration": "created",
        "tables": {
            "telemetry_transcripts": {"submitted": 1, "collapsed": 0, "inserted": 1},
            "telemetry_sessions": {"submitted": 1, "collapsed": 0, "inserted": 1},
        },
        "occ_retries": 0,
        "commit_ms": 1,
    }
    assert isinstance(out["commit_ms"], int)
    assert deps.stats.tenant_id == TENANT and deps.stats.project_id == RESOLVED
    assert deps.stats.tables == {"telemetry_transcripts": (1, 1), "telemetry_sessions": (1, 1)}
    assert "acct-under-test" not in str(out)


def test_adversarial_bodies_surface_only_mapped_errors() -> None:
    lone = "a\ud800b"
    deep: dict[str, Any] = {}
    for _ in range(5000):
        deep = {"a": deep}
    cases = [
        body_of(("telemetry_transcripts", [transcript_row(content=lone)])),
        body_of(("telemetry_sessions", [session_row()]), project_ref=lone),
        body_of(("telemetry_sessions", [session_row(workflow=lone)])),
        body_of(("telemetry_sessions", [session_row()]), project_ref="p\x00q"),
        body_of(("telemetry_sessions", [session_row(producer="p\x00q")])),
        body_of(("telemetry_sessions", [session_row(coverage_before=10**400)])),
        body_of(("telemetry_sessions", [session_row(files_changed=10**5000)])),
        body_of(("telemetry_sessions", [session_row(event_timestamp="9999-12-31T23:59:59.999-23:59")])),
        body_of(("telemetry_sessions", [session_row(workflow=deep)])),
        body_of(("telemetry_sessions", [session_row(entity_ref="a\x01b")])),
        body_of(
            (
                "telemetry_sessions",
                [session_row(session_started_at="1960-01-01T00:00:00.000Z", event_timestamp="1960-01-01T00:00:00.000Z")],
            )
        ),
    ]
    for body in cases:
        with pytest.raises((TelemetryRequestError, GateError, GrainConflictError)) as caught:
            run(body)
        assert SECRET not in repr(vars(caught.value))


def test_exclude_before_and_describe_entry() -> None:
    edge.reset_cache()
    assert edge.exclude_before("telemetry_sessions", "event_timestamp", "not_before") is None
    run(body_of(("telemetry_sessions", [session_row()])))
    assert edge.exclude_before("nope", "c", "r") is None
    entry = edge.describe_entry()
    assert entry["caps"] == {
        "max_invoke_body_bytes": 5242880,
        "max_rows_per_table": 2000,
        "max_rows_per_request": 5000,
    }
    assert set(entry) == {"description", "params_schema", "caps"}
