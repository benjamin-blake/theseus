"""CONCERN: scripts/ducklake_smoke/lambda_ops_gates.py (rec-2709 Wave 7).

Split out of the former tests/test_ducklake_neon_smoke_test.py monolith: ops_read_your_write,
ops_churn_regate (delegates to lambda_ec_gates.lambda_churn), and catalog_restore_drill.
connect_probe and lambda_append_only (also owned by lambda_ops_gates.py) have no direct unit test
in the monolith -- connect_probe is exercised only via the facade-interception test in
test_facade.py; lambda_append_only has no unit test at all (V3-only coverage).
"""

from __future__ import annotations

import pytest

import scripts.ducklake_neon_smoke_test as smoke
from scripts.ducklake_smoke import core, lambda_ec_gates, lambda_ops_gates
from tests.fixtures.ducklake_smoke_fakes import _Resp


def test_ops_read_your_write_ok(monkeypatch, capsys):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}
    written = {}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "write_ops":
            written.update(payload["record"])
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            if payload["record"]["id"].startswith("test-absent"):
                return _Resp(409, {"error_type": "referential"})
            state["status"] = payload["record"]["status"]
            return _Resp(200, {"ok": True})
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        return _Resp(200, {})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.ops_read_your_write()
    assert "OPS_RYW OK" in capsys.readouterr().out
    # The probe row persists (writer has no delete verb); it must carry the DQ NOT-NULL columns
    # so it does not red the ops_recommendations data-quality checks while it lingers.
    for col in ("automatable", "file", "context", "acceptance"):
        assert written.get(col) is not None, f"probe missing DQ-required column {col!r}"


def test_ops_read_your_write_supersedes_probe_on_success(monkeypatch, capsys):
    """rec-2114: on success, ops_read_your_write supersedes its own test-ryw- probe via a final
    update_ops call (status=superseded) so no open probe lingers to fail the automatable
    not_null DQ check."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}
    update_statuses = []

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "write_ops":
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            if payload["record"]["id"].startswith("test-absent"):
                return _Resp(409, {"error_type": "referential"})
            state["status"] = payload["record"]["status"]
            update_statuses.append(payload["record"]["status"])
            return _Resp(200, {"ok": True})
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        return _Resp(200, {})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    smoke.ops_read_your_write()
    assert update_statuses[-1] == "superseded"
    assert "superseded=true" in capsys.readouterr().out


def test_ops_read_your_write_absent_not_409_fails(monkeypatch):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    state = {"status": "open"}

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        if action == "read_ops_current":
            return _Resp(200, {"row_count": 1, "rows": [{"status": state["status"]}]})
        if action == "update_ops" and not payload["record"]["id"].startswith("test-absent"):
            state["status"] = "closed"
            return _Resp(200, {"ok": True})
        if action == "update_ops":
            return _Resp(200, {"ok": True})  # absent update wrongly succeeds -> boundary broken
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    with pytest.raises(smoke.SmokeTestFailure, match="expected 409"):
        smoke.ops_read_your_write()


def test_ops_churn_regate_delegates(monkeypatch, capsys):
    monkeypatch.setattr(lambda_ec_gates, "lambda_churn", lambda profile=None, region="eu-west-2": None)
    smoke.ops_churn_regate()
    assert "OPS_CHURN_REGATE OK" in capsys.readouterr().out


def test_catalog_restore_drill_ok(monkeypatch, capsys):
    # T2.19: catalog_restore_drill now INVOKES the maintenance restore_drill action over 443 (the
    # pg_dump/pg_restore runs inside AWS -- no Neon 5432 from CC-web). Mock the URL + the invoke.
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(
        core,
        "_sigv4_invoke",
        lambda url, p, **kw: _Resp(200, {"ok": True, "restored": True, "probe_id": "drill-probe", "pg_version": "16"}),
    )
    smoke.catalog_restore_drill()
    assert "CATALOG_RESTORE_DRILL OK" in capsys.readouterr().out


def test_catalog_restore_drill_probe_lost_fails(monkeypatch):
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    monkeypatch.setattr(core, "_sigv4_invoke", lambda url, p, **kw: _Resp(200, {"ok": True, "restored": False}))
    with pytest.raises(smoke.SmokeTestFailure, match="did not restore"):
        smoke.catalog_restore_drill()


def _row_rules_invoke(monkeypatch, *, answer, stored=0):
    """Wire the gate to a scripted writer/reader; returns the list of (action, record) calls."""
    monkeypatch.setattr(core, "_function_url", lambda role: f"https://{role}")
    calls: list[tuple[str, dict]] = []

    def fake_invoke(url, payload, **kw):
        action = payload["action"]
        calls.append((action, payload.get("record", {})))
        if action == "write_ops":
            return answer(payload["record"])
        if action == "read_ops_current":
            return _Resp(200, {"row_count": stored, "rows": []})
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(core, "_sigv4_invoke", fake_invoke)
    return calls


def _expected_422(record):
    for rule, overrides, column in lambda_ops_gates.ROW_RULES_CASES:
        if all(record.get(k) == v for k, v in overrides.items()):
            return _Resp(422, {"ok": False, "error_type": "row_rule", "rule": rule, "column": column})
    raise AssertionError(f"record matches no case: {record}")


def test_lambda_row_rules_ok(monkeypatch, capsys):
    calls = _row_rules_invoke(monkeypatch, answer=_expected_422)
    smoke.lambda_row_rules()
    assert "LAMBDA_ROW_RULES OK 4 cases" in capsys.readouterr().out
    assert [a for a, _ in calls].count("write_ops") == 4
    assert calls[-1][0] == "read_ops_current" and "update_ops" not in [a for a, _ in calls]


def test_lambda_row_rules_fails_on_accepted_write(monkeypatch):
    first_case = lambda_ops_gates.ROW_RULES_CASES[0]
    calls = _row_rules_invoke(monkeypatch, answer=lambda record: _Resp(200, {"ok": True}), stored=1)
    with pytest.raises(smoke.SmokeTestFailure, match=f"{first_case[0]} case answered 200"):
        smoke.lambda_row_rules()
    actions = [a for a, _ in calls]
    assert actions.index("update_ops") > actions.index("write_ops")  # the repair follows the unexpected 200
    repair = next(r for a, r in calls if a == "update_ops")
    clean = lambda_ops_gates.ROW_RULES_BASE
    assert repair["status"] == "superseded" and "failed --lambda-row-rules gate" in repair["resolution"]
    assert all(repair[k] == v for k, v in clean.items() if k != "status")


def test_lambda_row_rules_fails_on_wrong_rule_or_column(monkeypatch):
    rule, overrides, column = lambda_ops_gates.ROW_RULES_CASES[0]

    def wrong_column(record):
        return _Resp(422, {"ok": False, "error_type": "row_rule", "rule": rule, "column": "title"})

    _row_rules_invoke(monkeypatch, answer=wrong_column)
    with pytest.raises(smoke.SmokeTestFailure, match="expected accepted_values/effort"):
        smoke.lambda_row_rules()

    def schema_gate(record):
        return _Resp(422, {"ok": False, "error_type": "schema_gate"})

    _row_rules_invoke(monkeypatch, answer=schema_gate)
    with pytest.raises(smoke.SmokeTestFailure, match="instead of 422 row_rule"):
        smoke.lambda_row_rules()


def test_lambda_row_rules_fails_when_a_row_is_read_back(monkeypatch):
    calls = _row_rules_invoke(monkeypatch, answer=_expected_422, stored=1)
    with pytest.raises(smoke.SmokeTestFailure, match="left a row in current"):
        smoke.lambda_row_rules()
    assert any(a == "update_ops" for a, _ in calls)
