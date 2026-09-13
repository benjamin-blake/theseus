"""action_control_health concern for src/lambdas/ducklake_maintenance/handler.py (T2.26
control-table-class-and-counter-conformance).

Relocated here from tests/test_ducklake_maintenance.py so this dispatch/wiring concern has its
dedicated coverage home (this is the concern-split test PACKAGE for handler.py, Decision 104) --
the control_health() invariant-assertion logic itself is covered separately in
tests/test_ducklake_control_health.py (src/common/ducklake_control_health.py's own home).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.lambdas.ducklake_maintenance.handler as h
from src.common import ducklake_runtime as rt
from tests.fixtures.ducklake_maintenance_handler import _FULL_DSN

pytestmark = pytest.mark.unit


def test_control_health_action_dispatches(monkeypatch):
    """control_health is reachable through the maintenance handler's action dispatch and emits its
    metric to the DuckLakeMaintenance namespace."""
    assert "control_health" in h._ACTIONS

    con = MagicMock()
    monkeypatch.setattr(h.rt, "fetch_dsn", lambda: _FULL_DSN)
    monkeypatch.setattr(h.rt, "open_connection", lambda **kw: con)
    emitted: list[tuple[str, float]] = []
    monkeypatch.setattr(h, "_emit_maintenance_metric", lambda name, value: emitted.append((name, value)))
    monkeypatch.setattr(
        h.ducklake_control_health, "control_health", lambda con, metric_sink=None: (metric_sink("X", 0.0), {"ok": True})[1]
    )

    out = h.action_control_health({"data_path": "s3://bucket/ducklake/", "meta_schema": "ducklake_ops"}, None)
    assert out["ok"] is True
    assert ("X", 0.0) in emitted
    con.close.assert_called_once()


def test_control_health_action_requires_data_path_or_env_default(monkeypatch):
    """Without an explicit data_path (or DUCKLAKE_DATA_PATH set on the function), control_health
    loud-fails rather than defaulting to the smoke path."""
    monkeypatch.setattr(h, "DATA_PATH", None)
    with pytest.raises(rt.DuckLakeRuntimeError, match="data_path"):
        h.action_control_health({"meta_schema": "ducklake_ops"}, None)


def test_control_health_action_requires_meta_schema(monkeypatch):
    monkeypatch.setattr(h, "DATA_PATH", "s3://bucket/ducklake/")
    with pytest.raises(rt.DuckLakeRuntimeError, match="meta_schema"):
        h.action_control_health({}, None)


def test_control_health_action_falls_back_to_env_data_path(monkeypatch):
    """When the event omits data_path, the env-pinned DATA_PATH default is used (T2.26: this
    action is read-mostly, unlike the other operational actions which refuse no-arg invokes)."""
    con = MagicMock()
    monkeypatch.setattr(h, "DATA_PATH", "s3://bucket/ducklake/")
    monkeypatch.setattr(h.rt, "fetch_dsn", lambda: _FULL_DSN)
    open_calls = []
    monkeypatch.setattr(h.rt, "open_connection", lambda **kw: (open_calls.append(kw), con)[1])
    monkeypatch.setattr(h.ducklake_control_health, "control_health", lambda con, metric_sink=None: {"ok": True})

    out = h.action_control_health({"meta_schema": "ducklake_ops"}, None)
    assert out["ok"] is True
    assert open_calls[0]["data_path"] == "s3://bucket/ducklake/"


def test_handler_dispatches_control_health_without_a_connection_arg():
    """The handler never pre-opens a connection -- control_health receives con=None too."""
    action_mock = MagicMock(return_value={"ok": True})
    with patch.dict(h._ACTIONS, {"control_health": action_mock}):
        r = h.handler({"action": "control_health", "meta_schema": "ducklake_ops"})
    assert r["statusCode"] == 200
    assert action_mock.call_args.args[1] is None
