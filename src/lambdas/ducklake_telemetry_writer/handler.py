"""ducklake_telemetry_writer Lambda entrypoint (T2.36, slice 2a-2, option D part 1).

The function exists so telemetry identities never reach ops verbs (Decision 143 cl.3, Decision 213): it has
its own role and connects to the catalog as its own scoped login. It is env-pinned to the telemetry catalog
and never reads data_path or meta_schema from the event. It serves `describe`, `attach_check` (gate
instrumentation) and the telemetry verbs of telemetry_actions (docs/contracts/ducklake_telemetry_writer.yaml).

Caller identity comes from the Function URL authorizer context; neither the account id nor the user ARN, nor
any hash of them, is logged or returned (Decision 101). There is no direct-invoke fallback.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from collections.abc import Callable
from typing import Any

from src.common import ducklake_runtime as rt
from src.common.ducklake_metrics import make_metric_sink
from src.common.ducklake_scd2_schema import SchemaGateError, load_field_semantics
from src.common.ducklake_telemetry_registration import CallerPrincipal, clear_telemetry_caches
from src.common.ducklake_telemetry_txn import TelemetryRequestError
from src.common.ducklake_write_rules import RowRuleViolationError
from src.common.ducklake_writes import OCCRetryExhaustedError
from src.lambdas.ducklake_telemetry_writer import telemetry_actions as actions

METRIC_NAMESPACE = "DuckLakeTelemetryWriter"


class _ClientError(Exception):
    def __init__(self, status: int, error_type: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.extra = extra


class _EnvUnsetError(_ClientError):
    def __init__(self, name: str) -> None:
        super().__init__(500, "telemetry_env_unset", f"required environment variable {name} is not set")


_CATALOG_LOGIN: dict[str, str] = {}


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise _EnvUnsetError(name)
    return value


def _is_smoke(data_path: str) -> bool:
    return data_path.rstrip("/") == rt.SMOKE_DATA_PATH.rstrip("/")


def _require_caller(event: dict[str, Any]) -> None:
    ctx = event.get("requestContext") if isinstance(event, dict) else None
    auth = ctx.get("authorizer") if isinstance(ctx, dict) else None
    iam = auth.get("iam") if isinstance(auth, dict) else None
    if not isinstance(iam, dict) or not iam.get("accountId") or not iam.get("userArn"):
        raise _ClientError(403, "missing_caller_identity", "caller identity is required")


def _principal(event: dict[str, Any]) -> CallerPrincipal:
    """The signed caller as the registration port sees it; no AWS event shape crosses into src/common (Decision 184 cl.2)."""
    iam = event["requestContext"]["authorizer"]["iam"]
    segments = str(iam["userArn"]).split(":", 5)[-1].split("/")
    return CallerPrincipal(kind="aws_account", ref=str(iam["accountId"]), role_name=segments[1] if len(segments) > 1 else "")


def _parse_body(event: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """The JSON object body and its raw (decoded) byte length."""
    body: Any = event.get("body")
    if body is None or body == "":
        return {}, 0
    nbytes = len(body.encode("utf-8")) if isinstance(body, str) else 0
    try:
        if isinstance(body, str):
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(body, validate=True)
                nbytes = len(raw)
                body = raw.decode("utf-8")
            body = json.loads(body)
    except (ValueError, binascii.Error) as exc:
        raise _ClientError(400, "bad_request", "request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise _ClientError(400, "bad_request", "request body must be a JSON object")
    return body, nbytes


def action_describe(_payload: dict[str, Any]) -> dict[str, Any]:
    meta_schema = _env("TELEMETRY_META_SCHEMA")
    data_path = _env("TELEMETRY_DATA_PATH")
    return {
        "ok": True,
        "function": "ducklake_telemetry_writer",
        "actions": _all_actions(),
        "catalog": {"meta_schema": meta_schema, "data_path_is_smoke": _is_smoke(data_path)},
    }


def _warm_connection() -> tuple[Any, dict[str, Any]]:
    """The pinned warm connection on the scoped login; captures the login and backend class from the secret's host only."""
    meta_schema = _env("TELEMETRY_META_SCHEMA")
    data_path = _env("TELEMETRY_DATA_PATH")
    secret_id = _env("TELEMETRY_DSN_SECRET_ID")
    extension_directory = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY") or rt.LAMBDA_EXTENSION_DIRECTORY

    def opener() -> Any:
        dsn = rt.fetch_dsn(secret_id=secret_id)
        _CATALOG_LOGIN["login"] = str(dsn.get("username", ""))
        _CATALOG_LOGIN["backend"] = actions.classify_backend(str(dsn.get("host", "")))
        return rt.open_connection(
            dsn=dsn, data_path=data_path, meta_schema=meta_schema, extension_directory=extension_directory
        )

    con, meta = rt.get_warm_connection(
        opener=opener, data_path=data_path, meta_schema=meta_schema, extension_directory=extension_directory
    )
    if meta.get("reopened"):
        clear_telemetry_caches()
    return con, meta


def action_attach_check(_payload: dict[str, Any]) -> dict[str, Any]:
    con, meta = _warm_connection()
    con.execute("SELECT 1").fetchall()
    return {
        "ok": True,
        "meta_schema": _env("TELEMETRY_META_SCHEMA"),
        "data_path_is_smoke": _is_smoke(_env("TELEMETRY_DATA_PATH")),
        "catalog_login": _CATALOG_LOGIN.get("login", ""),
        "connect_ms": meta["connect_ms"],
        "reused": meta["reused"],
    }


def run_verb(request: actions.TelemetryRequest) -> dict[str, Any]:
    """Validate (before any connection), open the pinned connection, run the verb with the function's metric sink."""
    actions.validate_request(request)
    con, meta = _warm_connection()
    deps = actions.Deps(
        semantics=load_field_semantics(),
        metric_sink=make_metric_sink(namespace=METRIC_NAMESPACE),
        meta_schema=_env("TELEMETRY_META_SCHEMA"),
        data_path_is_smoke=_is_smoke(_env("TELEMETRY_DATA_PATH")),
        catalog_login=_CATALOG_LOGIN.get("login", ""),
        catalog_backend=_CATALOG_LOGIN.get("backend", "other"),
        connect_reused=bool(meta["reused"]),
    )
    return actions.VERBS[request.action](request, con, deps)


_ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "describe": action_describe,
    "attach_check": action_attach_check,
}


def _all_actions() -> list[str]:
    return sorted({*_ACTIONS, *actions.VERBS})


_ERROR_MAP: tuple[tuple[type[Exception], int, str], ...] = (
    (RowRuleViolationError, 422, "row_rule"),
    (SchemaGateError, 422, "schema_gate"),
    (OCCRetryExhaustedError, 503, "occ_exhausted"),
    (rt.DuckLakeRuntimeError, 500, "runtime"),
)


def _response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(payload)}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Authenticate the caller, parse the Function URL body, dispatch `action`; unmapped errors propagate."""
    t0 = time.perf_counter()
    try:
        _require_caller(event)
        payload, nbytes = _parse_body(event)
        action = payload.get("action")
        if isinstance(action, str) and action in actions.VERBS:
            request = actions.TelemetryRequest(action, payload, _principal(event), nbytes)
            return _response(200, run_verb(request))
        fn = _ACTIONS.get(action) if isinstance(action, str) else None
        if fn is None:
            raise _ClientError(400, "unknown_action", "unknown or missing action", actions=_all_actions())
        return _response(200, fn(payload))
    except _ClientError as exc:
        return _response(exc.status, {"ok": False, "error_type": exc.error_type, "error": str(exc), **exc.extra})
    except TelemetryRequestError as exc:
        return _response(exc.status, {"ok": False, "error_type": exc.error_type, "error": str(exc), **exc.fields})
    except Exception as exc:
        for cls, status, error_type in _ERROR_MAP:
            if isinstance(exc, cls):
                return _response(
                    status,
                    {
                        "ok": False,
                        "error_type": error_type,
                        "error": str(exc),
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                    },
                )
        raise
