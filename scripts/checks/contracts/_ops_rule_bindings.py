"""The ops_recommendations-only legs of validate_ops_rule_source (rec-4158; moved from the entry module).

Two surviving copies of the contract's rules stay honest here: config/agent/data_quality/ops.yaml's write_time tests
(until the portal row-rule gate plan retires them with the flags) and the three status vocabularies the portal, the
executor store and the Pydantic model carry. The status sources are read by ast, never imported.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import yaml

from scripts import contract_rules
from src.row_rules.rules import PRODUCER_SIDE_KINDS

_OPS_YAML_REL = "config/agent/data_quality/ops.yaml"
_STATUS_SOURCES = (
    "src/common/ducklake_scd2_schema.py",
    "scripts/executor/jsonl_store.py",
)


def _leg(intent: dict[str, Any], kind: str) -> dict[str, Any]:
    value = intent.get(kind)
    return value if isinstance(value, dict) else {}


def _ops_yaml_tests(root: Path) -> tuple[dict[str, list[tuple[str, dict[str, Any]]]], list[str]]:
    doc = yaml.safe_load((root / _OPS_YAML_REL).read_text(encoding="utf-8")) or {}
    columns = (((doc.get("tables") or {}).get("ops_recommendations") or {}).get("columns")) or {}
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    malformed: list[str] = []
    for column, spec in columns.items():
        for test in (spec or {}).get("tests") or []:
            params: Any
            if isinstance(test, str):
                name, params = test, {}
            elif isinstance(test, dict) and len(test) == 1:
                name, params = next(iter(test.items()))
            else:
                malformed.append(f"ops.yaml {column}: test entry {test!r} must be a name or a single-key mapping")
                continue
            if isinstance(params, dict) and params.get("write_time") is True:
                out.setdefault(column, []).append((name, params))
    return out, malformed


def _blank_rejecting(intent: dict[str, Any]) -> bool:
    min_length = _leg(intent, "min_length")
    if isinstance(min_length.get("value"), int) and min_length["value"] >= 1:
        return True
    return "accepted_values" in intent


def _parity_not_null(where: str, column: str, intent: dict[str, Any], raw_fields: dict[str, Any], params: dict) -> list[str]:
    errors = []
    if not contract_rules.not_null_declared(intent.get("not_null")):
        errors.append(f"{where}: no equal not_null rule in the contract")
    is_string = (raw_fields.get(column) or {}).get("iceberg_type", "string") == "string"
    if is_string and not _blank_rejecting(intent):
        errors.append(f"{where}: a VARCHAR column needs a blank-rejecting rule (min_length >= 1, accepted values)")
    return errors


def _parity_accepted_values(where: str, intent: dict[str, Any], params: dict) -> list[str]:
    declared = _leg(intent, "accepted_values").get("values")
    if declared is None or set(declared) != set(params.get("values") or []):
        return [f"{where}: values differ from the contract's accepted_values"]
    return []


def _parity_scalar(where: str, intent: dict[str, Any], name: str, key: str, params: dict) -> list[str]:
    declared = _leg(intent, name).get(key)
    if declared != params.get(key if name != "min_length" else "value"):
        return [f"{where}: {key} differs from the contract's {name} ({declared!r})"]
    return []


def _parity_test(
    where: str, column: str, name: str, params: dict, intent: dict[str, Any], raw_fields: dict[str, Any]
) -> list[str]:
    if name == "not_null":
        return _parity_not_null(where, column, intent, raw_fields, params)
    if name == "accepted_values":
        return _parity_accepted_values(where, intent, params)
    if name == "min_length":
        return _parity_scalar(where, intent, "min_length", "value", params)
    if name == "array_element_format":
        return _parity_scalar(where, intent, "array_element_format", "pattern", params)
    if name == "path_syntax":
        return [] if "pattern" in intent else [f"{where}: no equal pattern rule in the contract"]
    if name in PRODUCER_SIDE_KINDS:
        return [] if name in intent else [f"{where}: no declared {name} in the contract"]
    if name != "expression":
        return [f"{where}: write_time test kind {name!r} has no contract mapping"]
    return []


def _parity_errors(root: Path, raw_fields: dict[str, Any], intents: dict[str, dict[str, Any]]) -> list[str]:
    tests_by_column, errors = _ops_yaml_tests(root)
    for column, tests in tests_by_column.items():
        intent = intents.get(column)
        if intent is None:
            errors.append(f"ops.yaml {column}: write_time test on a column the contract does not declare")
            continue
        for name, params in tests:
            errors.extend(_parity_test(f"ops.yaml {column}.{name}", column, name, params, intent, raw_fields))
    return errors


def _literal_strings(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Call) and node.args:
        node = node.args[0]
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None
    return sorted(str(v) for v in value) if isinstance(value, (set, frozenset, list, tuple)) else None


def _module_assign(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    return None


def _scd2_status(root: Path) -> list[str] | None:
    tree = ast.parse((root / _STATUS_SOURCES[0]).read_text(encoding="utf-8"))
    table = _module_assign(tree, "STATUS_TRANSITIONS")
    if not isinstance(table, ast.Dict):
        return None
    for key, value in zip(table.keys, table.values):
        if isinstance(key, ast.Constant) and key.value == "ops_recommendations" and isinstance(value, ast.Dict):
            for inner_key, inner in zip(value.keys, value.values):
                if isinstance(inner_key, ast.Constant) and inner_key.value == "enforced" and isinstance(inner, ast.Name):
                    target = _module_assign(tree, inner.id)
                    return _literal_strings(target) if target is not None else None
    return None


def _store_status(root: Path) -> list[str] | None:
    target = _module_assign(ast.parse((root / _STATUS_SOURCES[1]).read_text(encoding="utf-8")), "_VALID_STATUSES")
    return _literal_strings(target) if target is not None else None


def _model_status(root: Path) -> list[str] | None:
    tree = ast.parse((root / _STATUS_SOURCES[1]).read_text(encoding="utf-8"))
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Recommendation"):
        for stmt in cls.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "status":
                for node in ast.walk(stmt.annotation):
                    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Literal":
                        members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
                        return _literal_strings(ast.List(members))
    return None


def _status_errors(root: Path, intents: dict[str, dict[str, Any]]) -> list[str]:
    declared = sorted(_leg(intents.get("status", {}), "accepted_values").get("values") or [])
    errors = []
    for label, reader in (
        ("STATUS_TRANSITIONS enforced set", _scd2_status),
        ("jsonl_store._VALID_STATUSES", _store_status),
        ("Recommendation status Literal", _model_status),
    ):
        found = reader(root)
        if found is None:
            errors.append(f"status vocabulary: could not read the {label} by ast")
        elif found != declared:
            errors.append(f"status vocabulary: the contract's {declared} differs from the {label} {found}")
    return errors


def binding_errors(root: Path, raw_fields: dict[str, Any], intents: dict[str, dict[str, Any]]) -> list[str]:
    return [*_parity_errors(root, raw_fields, intents), *_status_errors(root, intents)]
