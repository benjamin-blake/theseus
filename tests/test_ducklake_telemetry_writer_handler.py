"""Unit tests for the ducklake_telemetry_writer stub handler (no network)."""

from __future__ import annotations

import base64
import importlib
import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.common import ducklake_runtime as rt
from src.lambdas.ducklake_telemetry_writer import handler as h

ACCOUNT = "acct-under-test"
USER_ARN = "arn:aws:sts::acct-under-test:assumed-role/Some/secret-session"
SECRET_ID = "agent-platform-ducklake-telemetry-writer-dsn"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", "ducklake_smoke")
    monkeypatch.setenv("TELEMETRY_DATA_PATH", rt.SMOKE_DATA_PATH)
    monkeypatch.setenv("TELEMETRY_DSN_SECRET_ID", SECRET_ID)
    monkeypatch.setenv("DUCKLAKE_EXTENSION_DIRECTORY", "/opt/ext")
    h._CATALOG_LOGIN.clear()


def _event(body: Any, *, identity: bool = True, b64: bool = False) -> dict[str, Any]:
    raw = body if isinstance(body, str) else json.dumps(body)
    ev: dict[str, Any] = {"body": base64.b64encode(raw.encode()).decode() if b64 else raw, "isBase64Encoded": b64}
    if identity:
        ev["requestContext"] = {"authorizer": {"iam": {"accountId": ACCOUNT, "userArn": USER_ARN}}}
    return ev


def _body(resp: dict[str, Any]) -> dict[str, Any]:
    return json.loads(resp["body"])


@pytest.mark.parametrize("action", ["describe", "attach_check", "nope"])
@pytest.mark.parametrize(
    "ctx",
    [
        None,
        {},
        {"authorizer": {}},
        {"authorizer": {"iam": "x"}},
        {"authorizer": {"iam": {"accountId": ACCOUNT}}},
        {"authorizer": {"iam": {"userArn": USER_ARN}}},
        {"authorizer": {"iam": {"accountId": "", "userArn": ""}}},
    ],
)
def test_missing_or_partial_identity_is_403(action: str, ctx: Any) -> None:
    ev = _event({"action": action}, identity=False)
    if ctx is not None:
        ev["requestContext"] = ctx
    resp = h.handler(ev)
    assert resp["statusCode"] == 403
    assert _body(resp)["error_type"] == "missing_caller_identity"


def test_identity_never_in_response_or_logs(caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    caplog.set_level(logging.DEBUG)
    for ev in (_event({"action": "describe"}), _event({"action": "bogus"}), _event("{bad")):
        resp = h.handler(ev)
        assert ACCOUNT not in resp["body"] and USER_ARN not in resp["body"] and "secret-session" not in resp["body"]
    out = capsys.readouterr()
    assert ACCOUNT not in caplog.text + out.out + out.err


def test_malformed_body_is_400() -> None:
    resp = h.handler(_event("{not json"))
    assert resp["statusCode"] == 400 and _body(resp)["error_type"] == "bad_request"


@pytest.mark.parametrize("raw", ["[1, 2]", '"str"', "3"])
def test_non_object_body_is_400(raw: str) -> None:
    resp = h.handler(_event(raw))
    assert resp["statusCode"] == 400 and _body(resp)["error_type"] == "bad_request"


def test_bad_base64_is_400() -> None:
    ev = _event("x")
    ev["body"], ev["isBase64Encoded"] = "!!!notb64", True
    assert h.handler(ev)["statusCode"] == 400


def test_base64_body_is_decoded() -> None:
    resp = h.handler(_event({"action": "describe"}, b64=True))
    assert resp["statusCode"] == 200


def test_no_direct_invoke_fallback() -> None:
    resp = h.handler({"action": "describe", "requestContext": _event({})["requestContext"]})
    assert resp["statusCode"] == 400
    assert _body(resp)["error_type"] == "unknown_action"


@pytest.mark.parametrize("payload", [{}, {"action": "x"}, {"action": 5}])
def test_unknown_action_is_400_and_lists_actions(payload: dict[str, Any]) -> None:
    resp = h.handler(_event(payload))
    body = _body(resp)
    assert resp["statusCode"] == 400 and body["error_type"] == "unknown_action"
    assert body["actions"] == ["attach_check", "describe"]


def test_describe_is_connectionless(monkeypatch: pytest.MonkeyPatch) -> None:
    boom = MagicMock(side_effect=AssertionError("no connection allowed"))
    monkeypatch.setattr(rt, "get_warm_connection", boom)
    monkeypatch.setattr(rt, "open_connection", boom)
    monkeypatch.setattr(rt, "fetch_dsn", boom)
    resp = h.handler(_event({"action": "describe", "meta_schema": "ducklake", "data_path": "s3://x/"}))
    body = _body(resp)
    assert resp["statusCode"] == 200
    assert body["function"] == "ducklake_telemetry_writer"
    assert body["actions"] == ["attach_check", "describe"]
    assert body["catalog"] == {"meta_schema": "ducklake_smoke", "data_path_is_smoke": True}
    assert "s3://" not in resp["body"]


def test_describe_flags_non_smoke_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_DATA_PATH", "s3://other/ducklake/")
    assert _body(h.handler(_event({"action": "describe"})))["catalog"]["data_path_is_smoke"] is False


def test_describe_trailing_slash_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_DATA_PATH", rt.SMOKE_DATA_PATH.rstrip("/"))
    assert _body(h.handler(_event({"action": "describe"})))["catalog"]["data_path_is_smoke"] is True


def _patch_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock]:
    dsn = {
        "host": "db.example.invalid",
        "dbname": "d",
        "username": "ducklake_telemetry_writer",
        "password": "pw-value-x",  # pragma: allowlist secret
    }
    fetch = MagicMock(return_value=dsn)
    opened = MagicMock(return_value=MagicMock())
    con = MagicMock()
    state: dict[str, bool] = {"warm": False}

    def warm(*, opener: Any, **kw: Any) -> tuple[Any, dict[str, Any]]:
        warm.kwargs = kw  # type: ignore[attr-defined]
        if state["warm"]:
            return con, {"reused": True, "reopened": False, "connect_ms": 0.0}
        opener()
        state["warm"] = True
        return con, {"reused": False, "reopened": False, "connect_ms": 12.5}

    warm_mock = MagicMock(side_effect=warm)
    monkeypatch.setattr(rt, "fetch_dsn", fetch)
    monkeypatch.setattr(rt, "open_connection", opened)
    monkeypatch.setattr(rt, "get_warm_connection", warm_mock)
    return fetch, opened, warm_mock


def test_attach_check_pins_env_and_ignores_event(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch, opened, warm = _patch_runtime(monkeypatch)
    resp = h.handler(_event({"action": "attach_check", "data_path": "s3://evil/", "meta_schema": "ducklake"}))
    body = _body(resp)
    assert resp["statusCode"] == 200 and body["ok"] is True
    fetch.assert_called_once_with(secret_id=SECRET_ID)
    kwargs = opened.call_args.kwargs
    assert kwargs["data_path"] == rt.SMOKE_DATA_PATH and kwargs["meta_schema"] == "ducklake_smoke"
    assert kwargs["extension_directory"] == "/opt/ext"
    assert warm.call_args.kwargs["data_path"] == rt.SMOKE_DATA_PATH
    assert warm.call_args.kwargs["meta_schema"] == "ducklake_smoke"
    assert body["meta_schema"] == "ducklake_smoke" and body["data_path_is_smoke"] is True
    assert body["catalog_login"] == "ducklake_telemetry_writer"
    assert body["connect_ms"] == 12.5 and body["reused"] is False
    assert "pw-value-x" not in resp["body"] and "db.example.invalid" not in resp["body"]


def test_attach_check_reuse_returns_cached_login(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch, _opened, _warm = _patch_runtime(monkeypatch)
    h.handler(_event({"action": "attach_check"}))
    body = _body(h.handler(_event({"action": "attach_check"})))
    assert body["reused"] is True and body["catalog_login"] == "ducklake_telemetry_writer"
    assert fetch.call_count == 1


@pytest.mark.parametrize("name", ["TELEMETRY_META_SCHEMA", "TELEMETRY_DATA_PATH", "TELEMETRY_DSN_SECRET_ID"])
def test_unset_env_is_500(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _patch_runtime(monkeypatch)
    monkeypatch.delenv(name)
    resp = h.handler(_event({"action": "attach_check"}))
    assert resp["statusCode"] == 500 and _body(resp)["error_type"] == "telemetry_env_unset"


def test_describe_with_env_unset_is_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEMETRY_META_SCHEMA")
    assert _body(h.handler(_event({"action": "describe"})))["error_type"] == "telemetry_env_unset"


def test_import_with_env_unset_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TELEMETRY_META_SCHEMA", "TELEMETRY_DATA_PATH", "TELEMETRY_DSN_SECRET_ID", "DUCKLAKE_EXTENSION_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(h)


def test_runtime_error_is_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "get_warm_connection", MagicMock(side_effect=rt.DuckLakeRuntimeError("boom")))
    resp = h.handler(_event({"action": "attach_check"}))
    assert resp["statusCode"] == 500 and _body(resp)["error_type"] == "runtime"


def test_unexpected_exception_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "get_warm_connection", MagicMock(side_effect=KeyError("unmapped")))
    with pytest.raises(KeyError):
        h.handler(_event({"action": "attach_check"}))
