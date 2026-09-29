"""Wire form of capture rows: RFC 3339 datetimes with exactly three fraction digits and Z, sorted keys."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.telemetry.timestamps import require_aware_utc


def render_datetime(value: datetime) -> str:
    utc = value.astimezone(timezone.utc) if value.tzinfo is not None else value
    require_aware_utc(utc)
    return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


def _default(value: Any) -> str:
    if isinstance(value, datetime):
        return render_datetime(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def render_rows_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)
