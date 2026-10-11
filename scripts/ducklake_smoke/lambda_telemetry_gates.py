"""Telemetry writer URL-only proof for the DuckLake Neon smoke suite (T2.36, slice 2a-2, option D part 2).

One post-deploy gate, --lambda-telemetry, proves the telemetry writer serves only signed Function URL calls on the
ducklake_smoke catalog and that its caller cannot direct-invoke it (the live check behind Decision 213). Gates call
core._function_url / core._sigv4_invoke through the module object (Decision 104). Plan 3 part 1 appends its verb
vectors to this module.

Failure text carries only a status code, a handler error_type or a botocore error code; never a response body, an
error message, an ARN, an account id or a URL (Decision 101).
"""

from __future__ import annotations

from typing import Any

from scripts.ducklake_smoke import core

_FUNCTION_NAME = "agent-platform-ducklake-telemetry-writer"
_DECOY = {"meta_schema": "ducklake_ops", "data_path": "s3://example-invalid/ducklake/"}


def _fail(message: str) -> core.SmokeTestFailure:
    return core.SmokeTestFailure(f"LAMBDA_TELEMETRY FAIL: {message}")


def _body(resp: Any) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _error_type(resp: Any) -> str:
    value = _body(resp).get("error_type")
    return value if isinstance(value, str) else "none"


def _expect_ok(resp: Any, check: str) -> dict[str, Any]:
    body = _body(resp)
    if resp.status_code != 200 or body.get("ok") is not True:
        raise _fail(f"{check} status={resp.status_code} error_type={_error_type(resp)}")
    return body


def _check_unsigned(url: str, profile: str | None, region: str) -> None:
    resp = core._sigv4_invoke(url, {"action": "describe"}, sign=False, profile=profile, region=region)
    if resp.status_code == 403 and _error_type(resp) == "missing_caller_identity":
        raise _fail("telemetry writer URL is not AWS_IAM")
    if resp.status_code != 403:
        raise _fail(f"unsigned describe status={resp.status_code} (want 403)")


def _check_describe(url: str, profile: str | None, region: str) -> None:
    body = _expect_ok(core._sigv4_invoke(url, {"action": "describe"}, profile=profile, region=region), "describe")
    actions = body.get("actions")
    catalog = body.get("catalog")
    if not isinstance(actions, list) or not {"describe", "attach_check"} <= set(actions):
        raise _fail("describe actions missing describe or attach_check")
    if not isinstance(catalog, dict) or catalog.get("meta_schema") != core.META_SCHEMA:
        raise _fail("describe meta_schema is not the smoke schema")
    if catalog.get("data_path_is_smoke") is not True:
        raise _fail("describe data_path_is_smoke is not true")


def _check_attach(url: str, profile: str | None, region: str) -> None:
    resp = core._sigv4_invoke(url, {"action": "attach_check", **_DECOY}, profile=profile, region=region)
    body = _expect_ok(resp, "attach_check")
    if body.get("meta_schema") != core.META_SCHEMA:
        raise _fail("attach_check meta_schema is not the smoke schema (event keys honoured)")
    if body.get("data_path_is_smoke") is not True:
        raise _fail("attach_check data_path_is_smoke is not true")
    if body.get("catalog_login") != "ducklake_telemetry_writer":
        raise _fail("attach_check catalog_login is not the scoped telemetry login")


def _check_unknown_action(url: str, profile: str | None, region: str) -> None:
    resp = core._sigv4_invoke(url, {"action": "no_such_action"}, profile=profile, region=region)
    if resp.status_code != 400 or _error_type(resp) != "unknown_action":
        raise _fail(f"unknown action status={resp.status_code} error_type={_error_type(resp)} (want 400 unknown_action)")


def _check_direct_invoke_denied(profile: str | None, region: str) -> None:
    import boto3  # noqa: PLC0415
    from botocore.exceptions import ClientError  # noqa: PLC0415

    from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

    client = boto3.Session(profile_name=resolve_aws_profile(profile)).client("lambda", region_name=region)
    try:
        client.invoke(FunctionName=_FUNCTION_NAME, InvocationType="DryRun", Payload=b"{}")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "unknown"))
        if code == "AccessDeniedException":
            return
        raise _fail(f"direct-invoke probe inconclusive: {code}") from None
    raise _fail("URL-only guard missing: direct invoke allowed")


def lambda_telemetry(*, profile: str | None = None, region: str = "eu-west-2") -> None:
    """Prove the telemetry writer is URL-only, env-pinned to the smoke catalog and direct-invoke denied."""
    url = core._function_url("telemetry_writer")
    _check_unsigned(url, profile, region)
    _check_describe(url, profile, region)
    _check_attach(url, profile, region)
    _check_unknown_action(url, profile, region)
    _check_direct_invoke_denied(profile, region)
    print("LAMBDA_TELEMETRY OK unsigned=403 describe=200 attach_check=ok unknown_action=400 direct_invoke=denied")
