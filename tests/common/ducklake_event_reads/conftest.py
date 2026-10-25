"""Fixtures for the src/common/ducklake_event_reads.py concern-split tests."""

from __future__ import annotations

from typing import Any

import pytest

from src.common import ducklake_event_reads as ev
from src.common import ducklake_runtime as rt


@pytest.fixture
def smoke_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_META_SCHEMA", rt.SMOKE_META_SCHEMA)
    monkeypatch.setenv("TELEMETRY_DATA_PATH", rt.SMOKE_DATA_PATH)


@pytest.fixture(autouse=True)
def _reset_slots() -> Any:
    rt.reset_warm_connection()
    ev._INTERRUPTED_SLOTS.clear()
    yield
    rt.reset_warm_connection()
    ev._INTERRUPTED_SLOTS.clear()
