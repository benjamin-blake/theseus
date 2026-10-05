"""Ops rule-source check (rec-4158 plan A; Decision 210 cl.3).

The ops_recommendations Class A contract is the ONE declared source of every write-time data rule its rows must satisfy.
This check keeps that declaration well-formed (grammar, exemptions, regex subset), keeps its dates one-way (the
ratchet), and keeps the two surviving copies of the rules honest: config/agent/data_quality/ops.yaml's write_time tests
and the three status vocabularies the portal, the executor store and the Pydantic model carry.

Transitional by design: rec-4158 plan C folds this into the all-writer conformance check. The import closure is
scripts.contract_rules plus PyYAML -- the status sources are read by ast, never imported.
"""

from __future__ import annotations

import ast
import datetime
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from scripts import contract_rules
from scripts.checks import _common, registry

OPS_TABLES = ("ops_recommendations", "ops_decisions")
RULE_VOCABULARY = frozenset(
    {
        "not_null",
        "accepted_values",
        "min_length",
        "pattern",
        "array_element_format",
        "array_element_reference",
        "acceptance_lint",
        "not_before",
        "write_time_exemptions",
    }
)
_SUBKEYS: dict[str, frozenset[str]] = {
    "not_null": frozenset({"enforced", "exclude_before"}),
    "accepted_values": frozenset({"values", "enforced", "exclude_before"}),
    "min_length": frozenset({"value", "enforced", "exclude_before"}),
    "pattern": frozenset({"value", "enforced", "exclude_before"}),
    "array_element_format": frozenset({"pattern", "enforced", "exclude_before"}),
    "array_element_reference": frozenset({"enforced", "exclude_before"}),
    "acceptance_lint": frozenset({"require_discrimination", "enforced", "exclude_before"}),
}
PRODUCER_SIDE_KINDS = frozenset({"acceptance_lint", "array_element_reference"})
EXEMPTION_CLASSES = frozenset({"cross_row", "repository_state", "temporary"})
RECS_DATE_FLOOR = "2026-05-01"
_REC_ID = re.compile(r"^rec-[0-9]+$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_LOOKAROUND = ("(?=", "(?!", "(?<=", "(?<!", "(?P=")

CHECK_REL = "scripts/checks/contracts/validate_ops_rule_source.py"
_CONTRACTS_REL = "docs/contracts"
_REGISTRY_REL = "config/agent/data_quality/source_registry.yaml"
_OPS_YAML_REL = "config/agent/data_quality/ops.yaml"
_STATUS_SOURCES = (
    "src/common/ducklake_scd2_schema.py",
    "scripts/executor/jsonl_store.py",
)
_BASE_FILES = (
    f"{_CONTRACTS_REL}/ops_recommendations.yaml",
    f"{_CONTRACTS_REL}/ops_decisions.yaml",
    f"{_CONTRACTS_REL}/source-lineage.yaml",
    _REGISTRY_REL,
)


def _regex_subset_error(pattern: str) -> str | None:
    """Lookaround and backreferences are outside the subset RE2 and Python share."""
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"is not a valid regex ({exc})"
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            if i + 1 < len(pattern) and pattern[i + 1] in "123456789k":
                return "uses a backreference (outside the RE2-and-Python subset)"
            i += 2
            continue
        if any(pattern.startswith(token, i) for token in _LOOKAROUND):
            return "uses lookaround or a named backreference (outside the RE2-and-Python subset)"
        i += 1
    return None


def _date_error(table: str, value: Any) -> str | None:
    if not (isinstance(value, str) and _ISO_DATE.match(value)):
        return f"exclude_before {value!r} is not an ISO date string"
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return f"exclude_before {value!r} is not a real calendar date"
    if table == "ops_recommendations" and value < RECS_DATE_FLOOR:
        return f"exclude_before {value} is earlier than the Decision 64 anchor {RECS_DATE_FLOOR}"
    return None


def _leg_well_formed(kind: str, value: Any) -> bool:
    if kind == "not_before":
        return isinstance(value, str) and bool(value)
    if kind == "pattern":
        return isinstance(value, (str, dict))
    return isinstance(value, dict)


def _leg_shape(kind: str) -> str:
    return {"not_before": "a column name", "pattern": "a regex string or a mapping"}.get(kind, "a mapping")


def _leg(intent: dict[str, Any], kind: str) -> dict[str, Any]:
    value = intent.get(kind)
    return value if isinstance(value, dict) else {}


def _leg_value(kind: str, value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {"value": value}


def _patterns_of(kind: str, value: Any) -> list[str]:
    leg = _leg_value(kind, value)
    if kind == "pattern":
        pat = leg.get("value")
    elif kind == "array_element_format":
        pat = leg.get("pattern")
    else:
        return []
    return [pat] if isinstance(pat, str) else []


def _exemption_errors(where: str, kind: str, why: Any, root: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(why, dict):
        return [f"{where}: exemption {kind!r} must be a mapping with class, reason and owner"]
    cls, reason, owner = why.get("class"), why.get("reason"), why.get("owner")
    if cls not in EXEMPTION_CLASSES:
        errors.append(f"{where}: exemption {kind!r} class {cls!r} is not one of {sorted(EXEMPTION_CLASSES)}")
    if not (isinstance(reason, str) and reason.strip()):
        errors.append(f"{where}: exemption {kind!r} needs a reason")
    if not isinstance(owner, str) or not owner:
        errors.append(f"{where}: exemption {kind!r} needs an owner")
    elif cls in ("cross_row", "temporary") and not _REC_ID.match(owner):
        errors.append(f"{where}: exemption {kind!r} owner {owner!r} must be a rec id")
    elif cls == "repository_state" and not (root / owner).is_file():
        errors.append(f"{where}: exemption {kind!r} owner {owner!r} must be an existing repository path")
    return errors


def _leg_errors(table: str, where: str, kind: str, value: Any, exemptions: dict[str, Any]) -> list[str]:
    if not _leg_well_formed(kind, value):
        return [f"{where}: {kind} leg must be {_leg_shape(kind)}, got {type(value).__name__}"]
    errors: list[str] = []
    if isinstance(value, dict):
        extra = set(value) - _SUBKEYS.get(kind, frozenset())
        if extra:
            errors.append(f"{where}: {kind} carries unknown sub-key(s) {sorted(extra)}")
        if "exclude_before" in value:
            err = _date_error(table, value["exclude_before"])
            if err:
                errors.append(f"{where}: {kind} {err}")
    for pat in _patterns_of(kind, value):
        err = _regex_subset_error(pat)
        if err:
            errors.append(f"{where}: {kind} pattern {err}")
    if kind in PRODUCER_SIDE_KINDS and kind not in exemptions:
        errors.append(f"{where}: producer-side rule {kind!r} needs a write_time_exemptions entry")
    return errors


def _grammar_errors(table: str, raw_fields: dict[str, Any], intents: dict[str, dict[str, Any]], root: Path) -> list[str]:
    errors: list[str] = []
    for column, intent in intents.items():
        where = f"{table}.{column}"
        unknown = set(intent) - RULE_VOCABULARY
        if unknown:
            errors.append(f"{where}: rule key(s) {sorted(unknown)} outside the ops vocabulary")
        exemptions = intent.get("write_time_exemptions") or {}
        for kind, value in intent.items():
            if kind not in unknown and kind != "write_time_exemptions":
                errors.extend(_leg_errors(table, where, kind, value, exemptions))
        for kind, why in exemptions.items():
            if kind not in intent:
                errors.append(f"{where}: exemption {kind!r} names a rule the field does not declare")
            errors.extend(_exemption_errors(where, kind, why, root))
        nn = intent.get("not_null")
        if (raw_fields.get(column) or {}).get("nullable") is False and isinstance(nn, dict) and not nn.get("enforced"):
            errors.append(f"{where}: not_null enforced false on a nullable false field")
    return errors


def _read_table(table: str, contracts_dir: Path, repo_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    raw = contract_rules.load_yaml(contracts_dir / f"{table}.yaml")
    intents = contract_rules.read_intents(
        table,
        {},
        contracts_dir=contracts_dir,
        repo_root=repo_root,
        registry_key_ref=contract_rules.REGISTRY_KEY_REF,
    )
    return raw.get("fields") or {}, intents


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
    if not _leg(intent, "not_null").get("enforced"):
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


def _git(root: Path, *args: str) -> Any:
    return _common.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=root)


def resolve_base(root: Path) -> tuple[str | None, str]:
    result = _git(root, "merge-base", "HEAD", "origin/main")
    sha = result.stdout.strip()
    if result.returncode != 0 or not sha:
        return None, "no merge-base with origin/main resolves"
    return sha, ""


def _base_snapshot(root: Path, base: str, dest: Path) -> None:
    for rel in _BASE_FILES:
        shown = _git(root, "show", f"{base}:{rel}")
        if shown.returncode == 0:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_text(shown.stdout, encoding="utf-8")


def _registry_ids(root: Path) -> set[str]:
    path = root / _REGISTRY_REL
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    entries = (doc or {}).get("entries") or []
    return {e["canonical_id"] for e in entries if isinstance(e, dict) and "canonical_id" in e}


def _legs(root: Path) -> dict[tuple[str, str, str], str | None]:
    legs: dict[tuple[str, str, str], str | None] = {}
    contracts = root / _CONTRACTS_REL
    for table in OPS_TABLES:
        if not (contracts / f"{table}.yaml").is_file():
            continue
        for rule in contract_rules.declared_rules(table, contracts_dir=contracts, repo_root=root):
            legs[(table, rule.column, rule.kind)] = rule.exclude_before
    return legs


def _ratchet_errors(root: Path, base: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        _base_snapshot(root, base, Path(tmp))
        base_legs, base_ids = _legs(Path(tmp)), _registry_ids(Path(tmp))
    head_legs = _legs(root)
    errors = [
        f"ratchet: source {removed!r} was removed from the source registry; a removal strands every row carrying it "
        "(Decision 70) -- a redefinition needing its own plan"
        for removed in sorted(base_ids - _registry_ids(root))
    ]
    for key, base_date in base_legs.items():
        where = ".".join(key)
        if key not in head_legs:
            errors.append(
                f"ratchet: {where} was removed; a removal is a redefinition (Decision 210 cl.4) needing its own plan"
            )
            continue
        head_date = head_legs[key]
        if head_date is not None and head_date > (base_date or ""):
            errors.append(f"ratchet: {where} exclude_before moved later ({base_date or 'undated'} -> {head_date})")
    return errors


def _base_has_check(root: Path, base: str) -> bool:
    return _git(root, "cat-file", "-e", f"{base}:{CHECK_REL}").returncode == 0


@registry.register("validate_ops_rule_source", owner="platform")
def validate_ops_rule_source(failed: list[str], *, root: Path | None = None) -> None:
    """Fail on a malformed or one-way-violating ops rule declaration, ops.yaml parity drift or status vocabulary drift."""
    print("\n=== Ops rule source ===")
    root = root if root is not None else _common.ROOT
    errors: list[str] = []
    examined = 0
    recs_fields: dict[str, Any] = {}
    recs_intents: dict[str, dict[str, Any]] = {}
    for table in OPS_TABLES:
        try:
            fields, intents = _read_table(table, root / _CONTRACTS_REL, root)
        except (ValueError, OSError) as exc:
            errors.append(f"{table}: contract unreadable: {exc}")
            continue
        errors.extend(_grammar_errors(table, fields, intents, root))
        examined += sum(len(i) for i in intents.values())
        if table == "ops_recommendations":
            recs_fields, recs_intents = fields, intents
    if recs_intents:
        try:
            errors.extend(_parity_errors(root, recs_fields, recs_intents))
            errors.extend(_status_errors(root, recs_intents))
        except (OSError, SyntaxError, yaml.YAMLError) as exc:
            errors.append(f"parity inputs unreadable: {exc}")
    base, why = resolve_base(root)
    if base is None:
        print(f"  ratchet leg skipped: {why}")
    elif not _base_has_check(root, base):
        print("  ratchet dormant: the merge-base predates this check (installing PR, Decision 208 cl.1 absent arm)")
    else:
        try:
            errors.extend(_ratchet_errors(root, base))
        except ValueError as exc:
            errors.append(f"ratchet: could not read the rule legs: {exc}")
    registry.examined(examined, unit="declared_rules")
    for err in errors:
        print(f"  FAIL: {err}")
        failed.append(f"Ops rule source: {err}")
    if not errors:
        print(f"  PASS: {examined} declared rule legs well-formed, ops.yaml and status vocabularies agree.")
