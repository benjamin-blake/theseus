"""rec-4158's acceptance node and the writer-adapter proof (Decision 210; Decisions 187, 191 derived, never enumerated).

test_every_write_decidable_rule_has_a_writer_validator runs the registered conformance check on the real tree. The
adapter test then derives the writer's handlers from every Lambda manifest and, for each row-writing action and each
table it writes, breaks a rule-clean record in exactly each rule (kind, column) the table's RowRules enforce and asserts
the adapter refuses it naming that rule and column. An action, handler or rule it cannot classify fails.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
import yaml

from scripts.checks import registry
from scripts.checks.contracts import validate_write_time_enforcement_conformance as conformance
from src.common import ducklake_control_tables as control
from src.common import ducklake_runtime as rt
from tests.fixtures import writer_rule_adapters as w

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS = _ROOT / "docs" / "contracts"
_FS = yaml.safe_load((_ROOT / "config/lambda/ducklake/field_semantics.yaml").read_text(encoding="utf-8"))

# handler module -> {action: (adapter, table filter)} for every row-writing action; the test exercises exactly these
_ROW_WRITING = {
    "src/lambdas/ducklake_writer/handler.py": {"write_ops": w.write_ops, "update_ops": w.update_ops, "file_ops": w.file_ops},
    "src/lambdas/ducklake_telemetry_writer/handler.py": {
        "register_tenant": w.register,
        "register_project": w.register,
        "append_telemetry": w.append_telemetry,
    },
}
_NON_ROW_WRITING: dict[str, dict[str, str]] = {
    "src/lambdas/ducklake_writer/handler.py": {
        "attach_check": "probe",
        "create_tables": "provisioning: the smoke pair",
        "write": "the smoke pair's write (ops_smoke_events and the history/current pair carry no row rules)",
        "create_ops_tables": "provisioning, refused for dormant-free tables only; writes no row",
        "idempotency_probe": "probe",
        "partition_probe": "probe",
        "inlining_probe": "probe",
        "inlining": "probe",
        "loudfail_probe": "probe",
        "churn": "load probe on the smoke pair",
        "churn_single": "load probe on the smoke pair",
        "connect_probe": "probe",
        "reset_warm_connection": "maintenance",
        "describe": "read",
    },
    "src/lambdas/ducklake_telemetry_writer/handler.py": {
        "attach_check": "probe",
        "describe": "read",
        "provision_telemetry": "provisioning: tables and counter seeds, no caller row",
        "telemetry_probe": "probe",
        "begin_blobs": "issues claim-check upload grants; writes no row (the row arrives through append_telemetry)",
    },
    "src/lambdas/ducklake_reader/handler.py": dict.fromkeys(
        (
            "attach_check read_current partition_prune_check write_probe read_ops_current "
            "read_ops_history named_read query_ops connect_probe reset_warm_connection describe"
        ).split(),
        "read or probe: the reader holds no write grant",
    ),
    "src/lambdas/ducklake_maintenance/handler.py": dict.fromkeys(
        (
            "catalog_reinit restore_drill merge_ops gc_ops catalog_stats reconcile_columns "
            "clone_catalog control_health reconcile_partitions rewrite_partition_layout "
            "provision_telemetry_login ensure_catalog_indexes"
        ).split(),
        "maintenance: moves or removes files, writes no caller row",
    ),
    "src/lambdas/ducklake_maintenance_smoke/handler.py": dict.fromkeys(
        "merge gc hot_merge breaker_probe create_telemetry_tables".split(),
        "disposable ducklake_smoke catalog maintenance or provisioning, no caller row",
    ),
}
_REGISTRY_LESS = {
    "src/lambdas/ducklake_catalog_dr/handler.py": "catalog disaster-recovery job: dump and restore, no row write",
    "src/data/handlers/scheduled_agent_handler.py": "dispatches scheduled agents, writes no warehouse row through the writer",
    "src/data/handlers/findings_processor_handler.py": "findings processor, writes through the portal, not a writer verb",
}
_REGISTRATION_VERBS = {"register_tenant": "ops_tenants", "register_project": "ops_projects"}


def _manifest_handlers() -> list[str]:
    handlers: list[str] = []
    for manifest in sorted((_ROOT / "src" / "lambdas").glob("*/manifest.yaml")):
        handlers.extend(yaml.safe_load(manifest.read_text(encoding="utf-8")).get("handlers") or [])
    return handlers


def _has_registry(handler: str) -> bool:
    tree = ast.parse((_ROOT / handler).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_all_actions":
            return True
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "_ACTIONS" for t in targets):
            return True
    return False


def _actions(handler: str) -> list[str]:
    module = importlib.import_module(handler.removesuffix(".py").replace("/", "."))
    return list(module._all_actions()) if hasattr(module, "_all_actions") else sorted(module._ACTIONS)


def test_every_write_decidable_rule_has_a_writer_validator(capsys: pytest.CaptureFixture[str]) -> None:
    failed: list[str] = []
    registry.pop_declaration()
    conformance.validate_write_time_enforcement_conformance(failed)
    declaration = registry.pop_declaration()
    assert failed == []
    inventory = set(_FS["ops_tables"]) | set(control.control_table_names())
    assert f"{len(_FS['ops_tables'])} writer tables each match one arm" in capsys.readouterr().out
    assert declaration is not None and declaration.kind == "examined" and declaration.count > 100
    assert inventory >= {"ops_recommendations", "ops_entity_counters", "ops_priority_queue", "ops_smoke_events"}


def test_every_action_and_handler_is_classified() -> None:
    handlers = _manifest_handlers()
    assert len(handlers) >= 8 and set(_REGISTRY_LESS) <= set(handlers)
    for handler in handlers:
        if handler in _REGISTRY_LESS:
            assert not _has_registry(handler), f"{handler} gained an action registry: classify its actions"
            continue
        assert _has_registry(handler), f"{handler} has no action registry and is not in the declared registry-less map"
        actions = _actions(handler)
        row_writing, other = _ROW_WRITING.get(handler, {}), _NON_ROW_WRITING.get(handler, {})
        unclassified = sorted(set(actions) - set(row_writing) - set(other))
        assert not unclassified, f"{handler}: classify {unclassified} as row-writing (with a case) or not (with a reason)"
        stale = sorted((set(row_writing) | set(other)) - set(actions))
        assert not stale and not (set(row_writing) & set(other)), (handler, stale)
    assert set(_ROW_WRITING) | set(_NON_ROW_WRITING) <= set(handlers)


def _tables(action: str) -> list[str]:
    ops = _FS["ops_tables"]
    generic = [
        t
        for t, entry in ops.items()
        if (_CONTRACTS / f"{t}.yaml").is_file()
        and entry.get("write_mode") != "control"
        and entry.get("table_class") != "event"
        and entry.get("write_boundary") is None
    ]
    if action in ("write_ops", "update_ops"):
        return generic
    if action == "file_ops":
        return [t for t in generic if rt.resolve_table_spec(t).id_keyspace == "writer"]
    if action in _REGISTRATION_VERBS:
        return [_REGISTRATION_VERBS[action]]
    return [t for t, entry in ops.items() if entry.get("write_boundary") == "telemetry_append"]


def test_registration_and_append_verbs_cover_their_boundaries() -> None:
    ops = _FS["ops_tables"]
    assert set(_REGISTRATION_VERBS.values()) == {t for t, e in ops.items() if e.get("write_boundary") == "registration"}
    assert {t for t, e in ops.items() if e.get("write_boundary") == "telemetry_append"} == {
        t for t, e in ops.items() if e.get("table_class") == "event"
    }
    assert set(_tables("write_ops")) == set(w.SCENARIOS) & set(_tables("write_ops")) and len(_tables("write_ops")) >= 2


_REFUSED_AS_NOT_NULL = {"not_null", "schema_gate", "type", "required_ref", "grain_key_null"}


def _accepted_refusal(kind: str, column: str, refusal: tuple[str, str | None] | None) -> bool:
    if refusal is None:
        return False
    rule, named = refusal
    if kind == "not_null":
        return rule in _REFUSED_AS_NOT_NULL and column in str(named)
    return rule == kind and named == column


def _cases() -> list[tuple[str, str, str]]:
    return [
        (action, table, handler) for handler, verbs in _ROW_WRITING.items() for action in verbs for table in _tables(action)
    ]


@pytest.mark.parametrize(("action", "table", "handler"), _cases(), ids=lambda v: str(v).rsplit("/", 2)[-2:][0])
def test_each_writer_adapter_rejects_every_declared_kind(action: str, table: str, handler: str) -> None:
    adapter = _ROW_WRITING[handler][action]
    scenarios = w.SCENARIOS[table]
    for scenario in scenarios:
        assert w.outcome(adapter, table, scenario) is None, f"{table}: a rule-clean scenario was refused by {action}"
    rules, columns = w.rules_of(table), w.columns_of(table)
    merge_key = rt.resolve_table_spec(table).merge_key if table in _FS["ops_tables"] and table not in w.specs() else None
    expected = {
        (kind, column)
        for kind, column in w.kind_columns(rules)
        if (columns.get(column) or {}).get("role") != "derived" and not (action == "file_ops" and column == merge_key)
    }
    exercised: set[tuple[str, str]] = set()
    for kind, column in sorted(expected):
        for scenario in scenarios:
            broken = w.mutation(rules, scenario, kind, column)
            if broken is None:
                continue
            refusal = w.outcome(adapter, table, broken)
            assert _accepted_refusal(kind, column, refusal), f"{action} on {table}: breaking {kind} on {column} -> {refusal}"
            exercised.add((kind, column))
    assert exercised == expected, f"{action} on {table}: no scenario exercises {sorted(expected - exercised)}"
    assert expected, f"{table} declares no enforceable rule at all"
