"""Terminal typed answers for the DuckLake URL-only serving handlers (telemetry writer, reader, ops writer).

An exception that no error-map row recognises must never reach a Function URL as the runtime's untyped 502: the
handler answers a typed 500 `unmapped` (class name and request id only, never the message) or, for a dead catalog
connection, a typed retryable 503 `catalog_unavailable`. One structured log line per answer carries the detail
(redacted, first line, truncated) so an operator can find it by request id. ATTACH errors embed the libpq password,
so no response body ever carries an exception message (Decision 101); the one message a handler may pass through is the
reader's named_read_input, and only through redact().

Leaf module: stdlib plus src.common.ducklake_runtime only, no import-time side effects.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.common import ducklake_runtime as rt

TRANSIENT_ERROR_TYPES = frozenset({"catalog_unavailable"})

_MESSAGE_LIMIT = 300
_FRAME_LIMIT = 10
_CHAIN_LIMIT = 3
_REDACTED = "[redacted]"
_SECRET_PATTERNS = (
    re.compile(r"password\s*=\s*[^\s&;,'\"]+", re.IGNORECASE),
    re.compile(r"X-Amz-[A-Za-z0-9-]+\s*=\s*[^\s&;,'\"]+", re.IGNORECASE),
    re.compile(r"arn:[^\s,'\"]+", re.IGNORECASE),
    re.compile(r"\d{12,}"),
)


def redact(text: str) -> str:
    """First line only, secrets and account-shaped tokens replaced by a fixed marker, truncated to 300 characters."""
    lines = text.splitlines()
    first = lines[0] if lines else ""
    for pattern in _SECRET_PATTERNS:
        first = pattern.sub(_REDACTED, first)
    return first[:_MESSAGE_LIMIT]


def request_id(context: Any) -> str | None:
    """The Lambda request id from the invocation context; None when there is no context (a direct test call)."""
    value = getattr(context, "aws_request_id", None)
    return value if isinstance(value, str) and value else None


def _chain(exc: BaseException) -> list[str]:
    names: list[str] = []
    cursor = exc.__cause__ or exc.__context__
    while cursor is not None and len(names) < _CHAIN_LIMIT:
        names.append(type(cursor).__name__)
        cursor = cursor.__cause__ or cursor.__context__
    return names


def _frames(exc: BaseException) -> list[str]:
    frames: list[str] = []
    tb = exc.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(f"{code.co_filename}:{code.co_name}:{tb.tb_lineno}")
        tb = tb.tb_next
    return frames[-_FRAME_LIMIT:]


def _log(event: str, exc: BaseException, *, function: str, action: str, request_id: str | None) -> None:
    line = {
        "event": event,
        "function": function,
        "action": action,
        "error_class": type(exc).__name__,
        "request_id": request_id,
        "chain": _chain(exc),
        "frames": _frames(exc),
        "message": redact(str(exc)),
    }
    print(json.dumps(line, separators=(",", ":")))


def unmapped(
    exc: BaseException, *, function: str, action: str, request_id: str | None, elapsed_ms: float
) -> tuple[int, dict[str, Any]]:
    """Typed 500 for an exception no error-map row recognises. The body never carries the message."""
    _log("ducklake_unmapped_error", exc, function=function, action=action, request_id=request_id)
    return 500, {
        "ok": False,
        "error_type": "unmapped",
        "error_class": type(exc).__name__,
        "request_id": request_id,
        "action": action,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def catalog_unavailable(
    exc: BaseException, *, function: str, action: str, request_id: str | None, reopened: bool
) -> tuple[int, dict[str, Any]]:
    """Typed retryable 503 for a dead catalog connection. The body never carries the message."""
    _log("ducklake_catalog_unavailable", exc, function=function, action=action, request_id=request_id)
    return 503, {
        "ok": False,
        "error_type": "catalog_unavailable",
        "error_class": type(exc).__name__,
        "request_id": request_id,
        "action": action,
        "reopened": reopened,
    }


def terminal(
    exc: BaseException,
    *,
    function: str,
    action: str,
    request_id: str | None,
    elapsed_ms: float,
    reopened: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Dispatch on the dead-connection predicate: 503 catalog_unavailable, else 500 unmapped."""
    if rt.is_dead_connection_error(exc):
        return catalog_unavailable(exc, function=function, action=action, request_id=request_id, reopened=reopened)
    return unmapped(exc, function=function, action=action, request_id=request_id, elapsed_ms=elapsed_ms)


def bad_request(function: str, action: str) -> tuple[int, dict[str, Any]]:
    """Typed 400 for a body that is not a JSON object; the invocation line carries the function and action."""
    del function, action
    return 400, {"ok": False, "error_type": "bad_request", "error": "request body is not a JSON object"}


def log_named_read_input(exc: BaseException, *, function: str, verb: str, request_id: str | None) -> None:
    """One line per named_read_input answer so a misclassified server-side InvalidInputException can be found."""
    line = {
        "event": "ducklake_named_read_input",
        "function": function,
        "verb": verb,
        "error_class": type(exc).__name__,
        "request_id": request_id,
        "message": redact(str(exc)),
    }
    print(json.dumps(line, separators=(",", ":")))
