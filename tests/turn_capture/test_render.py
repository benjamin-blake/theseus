"""Wire form: three fraction digits, Z, sorted keys."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.telemetry.timestamps import TimestampError
from src.turn_capture.render import render_datetime, render_rows_json


def test_three_fraction_digits_and_z_never_rounds_up() -> None:
    assert render_datetime(datetime(2026, 1, 1, 0, 0, 0, 999999, tzinfo=timezone.utc)) == "2026-01-01T00:00:00.999Z"
    assert render_datetime(datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)) == "2026-01-01T00:00:05.000Z"
    assert render_datetime(datetime(2026, 1, 1, 0, 0, 0, 1500, tzinfo=timezone.utc)) == "2026-01-01T00:00:00.001Z"


def test_non_utc_offset_is_converted() -> None:
    plus_two = timezone(timedelta(hours=2))
    assert render_datetime(datetime(2026, 1, 1, 2, 0, 0, tzinfo=plus_two)) == "2026-01-01T00:00:00.000Z"


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(TimestampError):
        render_datetime(datetime(2026, 1, 1))


def test_rows_render_with_sorted_keys() -> None:
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    text = render_rows_json([{"b": 1, "a": when, "c": None}])
    assert text == '[{"a":"2026-01-01T00:00:00.000Z","b":1,"c":null}]'
    assert json.loads(text)[0]["a"].endswith("Z")


def test_unserialisable_value_raises() -> None:
    with pytest.raises(TypeError):
        render_rows_json([{"x": object()}])
