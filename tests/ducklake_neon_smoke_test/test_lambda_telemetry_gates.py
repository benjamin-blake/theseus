"""CONCERN: scripts/ducklake_smoke/lambda_telemetry_gates.py (T2.36 slice 2a-2, deploy wiring).

The six --lambda-telemetry checks, each with a red case, and the Decision 101 leak guards. The URL never appears.
"""

from __future__ import annotations

# boto3 is patched by string below; the import makes the heavy-dep requirement visible to the fast tier's collect pass.
import boto3  # noqa: F401
import pytest
from botocore.exceptions import ClientError

from scripts.ducklake_smoke import core, lambda_telemetry_gates
from tests.fixtures.ducklake_smoke_fakes import _Resp

FAKE_ACCT = "123456789012"
FAKE_ARN = "arn:" + f"aws:lambda:eu-west-2:{FAKE_ACCT}:function:agent-platform-ducklake-telemetry-writer"
FAKE_HOST = "abcdefghij" + ".lambda-url.eu-west-2.on.aws"
SUCCESS_LINE = "LAMBDA_TELEMETRY OK unsigned=403 describe=200 attach_check=ok unknown_action=400 direct_invoke=denied"

DESCRIBE_OK = {
    "ok": True,
    "actions": ["attach_check", "describe"],
    "catalog": {"meta_schema": core.META_SCHEMA, "data_path_is_smoke": True},
}
ATTACH_OK = {
    "ok": True,
    "meta_schema": core.META_SCHEMA,
    "data_path_is_smoke": True,
    "catalog_login": "ducklake_telemetry_writer",
}


class _Client:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"StatusCode": 204}


def _denied(code="AccessDeniedException", message="x"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "Invoke")


@pytest.fixture
def wired(monkeypatch):
    """Happy-path doubles; tests override entries of `state` to break exactly one check."""
    state = {
        "unsigned": _Resp(403, None, text='{"Message":"Forbidden"}'),
        "describe": _Resp(200, DESCRIBE_OK),
        "attach": _Resp(200, ATTACH_OK),
        "unknown": _Resp(400, {"ok": False, "error_type": "unknown_action"}),
        "client": _Client(_denied()),
        "sent": [],
    }

    def fake_invoke(url, payload, **kw):
        state["sent"].append((payload, kw.get("sign", True)))
        if kw.get("sign", True) is False:
            return state["unsigned"]
        return {"describe": state["describe"], "attach_check": state["attach"], "no_such_action": state["unknown"]}[
            payload["action"]
        ]

    class Session:
        def __init__(self, profile_name=None):
            pass

        def client(self, name, region_name=None):
            return state["client"]

    monkeypatch.setattr(core, "_function_url", lambda role: "https://fake-url.invalid")
    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    monkeypatch.setattr("boto3.Session", Session)
    return state


def test_happy_path_prints_fixed_line(wired, capsys):
    lambda_telemetry_gates.lambda_telemetry()
    out = capsys.readouterr().out
    assert out.strip() == SUCCESS_LINE
    assert "fake-url" not in out
    assert wired["client"].calls == [
        {"FunctionName": "agent-platform-ducklake-telemetry-writer", "InvocationType": "DryRun", "Payload": b"{}"}
    ]


def test_attach_check_sends_decoy_keys(wired):
    lambda_telemetry_gates.lambda_telemetry()
    payload = next(p for p, _ in wired["sent"] if p["action"] == "attach_check")
    assert payload["meta_schema"] == "ducklake_ops"
    assert payload["data_path"].startswith("s3://")


def test_check1_url_failure_propagates(monkeypatch):
    seen = []

    def boom(role):
        seen.append(role)
        raise core.SmokeTestFailure("no url")

    monkeypatch.setattr(core, "_function_url", boom)
    with pytest.raises(core.SmokeTestFailure, match="no url"):
        lambda_telemetry_gates.lambda_telemetry()
    assert seen == ["telemetry_writer"]


@pytest.mark.parametrize(
    ("key", "resp", "needle"),
    [
        ("unsigned", _Resp(200, {"ok": True}), "unsigned describe status=200"),
        ("unsigned", _Resp(403, {"ok": False, "error_type": "missing_caller_identity"}), "not AWS_IAM"),
        ("describe", _Resp(200, {**DESCRIBE_OK, "actions": ["describe"]}), "missing describe or attach_check"),
        (
            "describe",
            _Resp(200, {**DESCRIBE_OK, "catalog": {"meta_schema": "ducklake_ops", "data_path_is_smoke": True}}),
            "meta_schema is not the smoke schema",
        ),
        (
            "describe",
            _Resp(200, {**DESCRIBE_OK, "catalog": {"meta_schema": core.META_SCHEMA, "data_path_is_smoke": False}}),
            "data_path_is_smoke",
        ),
        ("attach", _Resp(200, {**ATTACH_OK, "ok": False}), "attach_check status=200"),
        ("attach", _Resp(200, {**ATTACH_OK, "meta_schema": "ducklake_ops"}), "event keys honoured"),
        ("attach", _Resp(200, {**ATTACH_OK, "data_path_is_smoke": False}), "data_path_is_smoke"),
        ("attach", _Resp(200, {**ATTACH_OK, "catalog_login": "ducklake_ops"}), "scoped telemetry login"),
        ("unknown", _Resp(200, {"ok": True}), "unknown action status=200"),
        ("unknown", _Resp(400, {"error_type": "bad_request"}), "error_type=bad_request"),
    ],
)
def test_red_cases(wired, key, resp, needle):
    wired[key] = resp
    with pytest.raises(core.SmokeTestFailure, match=needle):
        lambda_telemetry_gates.lambda_telemetry()


def test_dryrun_success_means_guard_missing(wired):
    wired["client"] = _Client()
    with pytest.raises(core.SmokeTestFailure, match="URL-only guard missing: direct invoke allowed"):
        lambda_telemetry_gates.lambda_telemetry()


def test_dryrun_other_code_is_inconclusive(wired):
    wired["client"] = _Client(_denied("ThrottlingException"))
    with pytest.raises(core.SmokeTestFailure, match="direct-invoke probe inconclusive: ThrottlingException"):
        lambda_telemetry_gates.lambda_telemetry()


def test_client_error_message_never_leaks(wired, capsys):
    leaky = f"User {FAKE_ACCT} is not authorized on {FAKE_ARN} via https://{FAKE_HOST}/"
    wired["client"] = _Client(_denied("ThrottlingException", leaky))
    with pytest.raises(core.SmokeTestFailure) as info:
        lambda_telemetry_gates.lambda_telemetry()
    captured = capsys.readouterr()
    for text in (str(info.value), captured.out, captured.err):
        assert FAKE_ACCT not in text
        assert "arn:" not in text
        assert "lambda-url" not in text


def test_http_body_never_leaks(wired, capsys):
    wired["attach"] = _Resp(500, {"ok": False, "error": f"{FAKE_ACCT} {FAKE_ARN} {FAKE_HOST}"}, text=FAKE_ARN)
    with pytest.raises(core.SmokeTestFailure) as info:
        lambda_telemetry_gates.lambda_telemetry()
    captured = capsys.readouterr()
    for text in (str(info.value), captured.out, captured.err):
        assert FAKE_ACCT not in text
        assert "arn:" not in text
        assert "lambda-url" not in text
