"""Tests for src/common/ducklake_handler_errors.py (PLAN-ducklake-typed-unmapped-errors, rec-4282)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.common import ducklake_handler_errors as he

pytestmark = pytest.mark.unit

_ACCT = "1234" + "56789012"
_SECRET = f"ATTACH failed {'pass' + 'word'}=hunter2 X-Amz-Signature=abc123 arn:aws:iam::{_ACCT}:role/r acct {_ACCT} s3://b/k"
_CONTRACTS = Path(__file__).resolve().parents[1] / "docs" / "contracts"
_CONNECTIONLESS = {"describe"}


def _lines(out: str, event: str) -> list[dict]:
    return [json.loads(ln) for ln in out.splitlines() if ln.startswith("{") and f'"{event}"' in ln]


def _raise_nested() -> None:
    secret_local = "LOCAL-SECRET-VALUE"  # noqa: F841  # pragma: allowlist secret -- must never reach the log
    try:
        raise KeyError("inner")
    except KeyError as inner:
        raise ValueError("outer") from inner


def test_unmapped_is_a_typed_500_with_class_and_request_id_only(capsys):
    status, body = he.unmapped(KeyError("x"), function="reader", action="named_read", request_id="req-1", elapsed_ms=12.345)
    assert status == 500
    assert body == {
        "ok": False,
        "error_type": "unmapped",
        "error_class": "KeyError",
        "request_id": "req-1",
        "action": "named_read",
        "elapsed_ms": 12.35,
    }
    assert [e["event"] for e in map(json.loads, capsys.readouterr().out.splitlines())] == ["ducklake_unmapped_error"]


def test_unmapped_body_never_carries_the_message(capsys):
    for exc in (Exception(_SECRET), KeyError(_SECRET)):
        _, body = he.unmapped(exc, function="writer", action="unknown", request_id=None, elapsed_ms=1.0)
        text = json.dumps(body)
        for needle in ("hunter2", "abc123", "arn:aws", _ACCT, "s3://"):
            assert needle not in text
    _, body = he.catalog_unavailable(Exception(_SECRET), function="writer", action="unknown", request_id=None, reopened=True)
    assert "hunter2" not in json.dumps(body) and "arn:aws" not in json.dumps(body)
    capsys.readouterr()


def test_log_line_redacts_truncates_and_keeps_the_first_line(capsys):
    he.unmapped(
        Exception(_SECRET + "\nsecond line must go " + "y" * 600),
        function="writer",
        action="unknown",
        request_id="r",
        elapsed_ms=1,
    )
    line = _lines(capsys.readouterr().out, "ducklake_unmapped_error")[0]
    msg = line["message"]
    assert "second line" not in msg and len(msg) <= 300
    for needle in ("hunter2", "abc123", "arn:aws", _ACCT):
        assert needle not in msg
    assert "[redacted]" in msg
    quoted = he.redact("conn failed " + "pass" + "word='sec ret' host=x " + "pass" + 'word="two words" tail')
    assert "sec" not in quoted and "two words" not in quoted and "host=x" in quoted and "tail" in quoted
    assert he.redact("a" * 900) == "a" * 300
    assert he.redact("") == ""


def test_log_line_frames_carry_no_locals_and_name_the_chain(capsys):
    try:
        _raise_nested()
    except ValueError as exc:
        he.unmapped(exc, function="reader", action="describe", request_id="r", elapsed_ms=1)
    raw = capsys.readouterr().out
    line = _lines(raw, "ducklake_unmapped_error")[0]
    assert "LOCAL-SECRET-VALUE" not in raw
    assert line["chain"] == ["KeyError"]
    assert 1 <= len(line["frames"]) <= 10
    assert all(f.count(":") >= 2 and f.rsplit(":", 1)[1].isdigit() for f in line["frames"])
    assert any(":_raise_nested:" in f for f in line["frames"])


def test_chain_is_capped_at_three_class_names(capsys):
    exc: BaseException = KeyError("0")
    for i in range(6):
        nxt = ValueError(str(i))
        nxt.__cause__ = exc
        exc = nxt
    he.unmapped(exc, function="reader", action="describe", request_id="r", elapsed_ms=1)
    assert len(_lines(capsys.readouterr().out, "ducklake_unmapped_error")[0]["chain"]) == 3


def test_dead_connection_is_a_typed_503(capsys):
    dead = RuntimeError("server closed the connection unexpectedly " + _SECRET)
    status, body = he.terminal(dead, function="reader", action="named_read", request_id="r", elapsed_ms=1.0, reopened=True)
    assert status == 503
    assert body == {
        "ok": False,
        "error_type": "catalog_unavailable",
        "error_class": "RuntimeError",
        "request_id": "r",
        "action": "named_read",
        "reopened": True,
    }
    assert _lines(capsys.readouterr().out, "ducklake_catalog_unavailable")
    status, body = he.terminal(KeyError("x"), function="reader", action="named_read", request_id="r", elapsed_ms=1.0)
    assert (status, body["error_type"]) == (500, "unmapped")
    assert he.TRANSIENT_ERROR_TYPES == {"catalog_unavailable"}


def test_bad_request_and_request_id_helpers():
    assert he.bad_request("reader", "unknown") == (
        400,
        {"ok": False, "error_type": "bad_request", "error": "request body is not a JSON object"},
    )

    class _Ctx:
        aws_request_id = "abc"

    assert he.request_id(_Ctx()) == "abc" and he.request_id(None) is None and he.request_id(object()) is None


def test_action_is_registered_or_unknown(monkeypatch, capsys):
    import src.lambdas.ducklake_reader.handler as reader
    import src.lambdas.ducklake_telemetry_writer.handler as telemetry
    import src.lambdas.ducklake_writer.handler as writer

    hostile = "evil<script>" + "z" * 50
    ident = {"requestContext": {"authorizer": {"iam": {"accountId": "a", "userArn": "arn:aws:sts::a:assumed-role/R/s"}}}}
    boom = KeyError("x")

    def _raise(*_a, **_k):
        raise boom

    monkeypatch.setattr(reader, "_handle", _raise)
    monkeypatch.setattr(writer, "_handle", _raise)
    monkeypatch.setattr(telemetry, "_parse_body", _raise)
    for handler, event in (
        (reader.handler, {"body": json.dumps({"action": hostile})}),
        (writer.handler, {"body": json.dumps({"action": hostile})}),
        (telemetry.handler, {**ident, "body": json.dumps({"action": hostile})}),
    ):
        response = handler(event)
        assert json.loads(response["body"])["action"] == "unknown"
    for handler, event, action in (
        (reader.handler, {"body": json.dumps({"action": "named_read"})}, "named_read"),
        (writer.handler, {"body": json.dumps({"action": "write_ops"})}, "write_ops"),
    ):
        assert json.loads(handler(event)["body"])["action"] == action
    out = capsys.readouterr().out
    assert hostile not in out


@pytest.mark.parametrize("name", ["ducklake_telemetry_writer", "ducklake_reader", "ducklake_writer"])
def test_serving_contracts_declare_the_terminal_answers(name):
    contract = yaml.safe_load((_CONTRACTS / f"{name}.yaml").read_text(encoding="utf-8"))
    verbs = contract["verbs"]
    assert verbs
    for verb, spec in verbs.items():
        assert "unmapped" in spec["typed_errors"], (name, verb)
        assert 500 in spec["response_codes"] and "unmapped" in spec["response_codes"][500], (name, verb)
        if verb not in _CONNECTIONLESS:
            assert "catalog_unavailable" in spec["typed_errors"], (name, verb)
            assert 503 in spec["response_codes"] and "catalog_unavailable" in spec["response_codes"][503], (name, verb)
    if name == "ducklake_reader":
        assert "named_read_input" in verbs["named_read"]["typed_errors"] and 400 in verbs["named_read"]["response_codes"]
    invariants = " ".join(contract["audit_invariants"])
    assert "502" in invariants and "unmapped" in invariants and "rec-4303" in invariants


def test_named_read_input_log_line_is_redacted_and_carries_the_request_id(capsys):
    he.log_named_read_input(
        ValueError("narrow the query " + _SECRET), function="reader", verb="recs_related", request_id="req-3"
    )
    line = _lines(capsys.readouterr().out, "ducklake_named_read_input")[0]
    assert (line["function"], line["verb"], line["error_class"], line["request_id"]) == (
        "reader",
        "recs_related",
        "ValueError",
        "req-3",
    )
    assert line["message"].startswith("narrow the query") and "hunter2" not in line["message"] and _ACCT not in line["message"]
