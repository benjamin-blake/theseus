"""Ratification guard for the telemetry writer Class B contract: status, census, every declared typed error pinned to a test.

AST and YAML only; imports no src module and no other test module.
"""

from __future__ import annotations

import ast
import re
from collections import deque
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs/contracts/ducklake_telemetry_writer.yaml"
WRITER_DIR = "src/lambdas/ducklake_telemetry_writer/"
HANDLER = WRITER_DIR + "handler.py"
EDGE = WRITER_DIR + "telemetry_edge.py"
ACTIONS = WRITER_DIR + "telemetry_actions.py"
HANDLER_ERRORS = "src/common/ducklake_handler_errors.py"
EMIT_MODULES = (
    HANDLER,
    EDGE,
    ACTIONS,
    "src/telemetry/request.py",
    "src/telemetry/blobs.py",
    "src/common/ducklake_telemetry_append.py",
    "src/common/ducklake_telemetry_blobs.py",
    "src/common/ducklake_telemetry_registration.py",
)
GRAPH_GLOBS = (
    WRITER_DIR + "*.py",
    "src/telemetry/*.py",
    "src/common/ducklake_telemetry_*.py",
    "src/common/ducklake_scd2_schema.py",
)

NOT_CONTRACT_VERBS = frozenset({"attach_check", "telemetry_probe"})
TERMINAL_ERRORS = ("unmapped", "catalog_unavailable")
STATUS_FIRST_CALLS = frozenset({"_ClientError", "TelemetryRequestError"})
TYPE_FIRST_CALLS = frozenset({"RequestError"})
ERROR_MAPS = frozenset({"_ERROR_MAP", "_KERNEL_ERRORS", "_BLOB_FAULTS"})
BASES = frozenset({"verb", "layer", "shared"})
ENTRY = {
    "append_telemetry": "action_append_telemetry",
    "begin_blobs": "action_begin_blobs",
    "describe": "action_describe",
    "provision_telemetry": "provision_telemetry",
    "register_tenant": "register_tenant",
    "register_project": "register_project",
}
CONNECTION_VERBS = tuple(v for v in ENTRY if v != "describe")
ALL_VERBS = tuple(ENTRY)
HANDLER_LEVEL_ORIGINS = frozenset({"_require_caller", "_env", "terminal"})
PASS_THROUGH = (EDGE, "_translate", "exc.error_type")

W = "tests/lambdas/ducklake_telemetry_writer/"
C = "tests/common/"
H = W + "test_handler.py::"
E = W + "test_telemetry_edge.py::"
TA = W + "test_telemetry_actions.py::"
CA = C + "test_ducklake_telemetry_append.py::"
CB = C + "test_ducklake_telemetry_blobs.py::"
CR = C + "test_ducklake_telemetry_registration.py::"

# (verb, typed_error) -> (test node, basis, anchor). verb: the node drives that verb's real entry to the error, anchored by the
# quoted action literal, the verb's entry function or a same-file helper naming the literal; layer: the node calls the anchor,
# a function on the verb's path below its entry; shared: the node proves a handler-wide answer through any action or a stub.
TYPED_ERROR_TESTS: dict[tuple[str, str], tuple[str, str, str | None]] = {
    ("append_telemetry", "bad_request"): (E + "test_request_errors_translate_by_type", "verb", "body_of"),
    ("append_telemetry", "blob_grant_self_check"): (H + "test_blob_faults_answer_a_typed_500", "shared", None),
    ("append_telemetry", "blob_integrity"): (H + "test_blob_faults_answer_a_typed_500", "shared", None),
    ("append_telemetry", "blob_not_verified"): (
        CA + "test_unknown_project_blob_row_is_422_before_any_head",
        "layer",
        "run_blob",
    ),
    ("append_telemetry", "blob_store_access"): (H + "test_blob_faults_answer_a_typed_500", "shared", None),
    ("append_telemetry", "blob_store_unavailable"): (
        CA + "test_store_unavailable_is_503_and_opens_no_transaction",
        "layer",
        "run_blob",
    ),
    ("append_telemetry", "catalog_unavailable"): (H + "test_dead_connection_at_connect_is_503", "shared", None),
    ("append_telemetry", "grain_conflict"): (H + "test_error_map_rows_for_kernel_errors", "shared", None),
    ("append_telemetry", "missing_caller_identity"): (H + "test_missing_or_partial_identity_is_403", "shared", None),
    ("append_telemetry", "mixed_producer"): (E + "test_request_errors_translate_by_type", "verb", "body_of"),
    ("append_telemetry", "occ_exhausted"): (H + "test_masked_exhaustion_logs_its_retry_count", "shared", None),
    ("append_telemetry", "payload_too_large"): (E + "test_caps_are_413_at_the_boundaries", "verb", "body_of"),
    ("append_telemetry", "project_unregistered"): (
        CA + "test_unregistered_reserved_ref_is_refused_before_any_transaction",
        "layer",
        "run",
    ),
    ("append_telemetry", "row_rule"): (
        E + "test_inline_content_above_the_threshold_is_the_kernels_row_rule",
        "verb",
        "body_of",
    ),
    ("append_telemetry", "runtime"): (H + "test_runtime_error_is_500", "shared", None),
    ("append_telemetry", "schema_gate"): (E + "test_request_errors_translate_by_type", "verb", "body_of"),
    ("append_telemetry", "telemetry_env_unset"): (H + "test_unset_env_is_500", "shared", None),
    ("append_telemetry", "tenant_unresolved"): (E + "test_tenant_is_read_once_and_unresolved_is_403", "verb", "body_of"),
    ("append_telemetry", "too_many_blobs"): (CA + "test_blob_rows_over_the_cap_are_413", "layer", "run_blob"),
    ("append_telemetry", "too_many_rows"): (E + "test_caps_are_413_at_the_boundaries", "verb", "body_of"),
    ("append_telemetry", "unmapped"): (H + "test_unexpected_exception_is_a_typed_500", "shared", None),
    ("append_telemetry", "write_order"): (E + "test_request_errors_translate_by_type", "verb", "body_of"),
    ("begin_blobs", "bad_request"): (E + "test_begin_blobs_edge_response_and_refusals", "verb", "begin"),
    ("begin_blobs", "blob_grant_self_check"): (H + "test_blob_faults_answer_a_typed_500", "shared", None),
    ("begin_blobs", "blob_integrity"): (H + "test_blob_faults_answer_a_typed_500", "shared", None),
    ("begin_blobs", "blob_not_verified"): (CB + "test_begin_blobs_size_mismatch_is_422_and_grants_nothing", "layer", "run"),
    ("begin_blobs", "blob_store_access"): (H + "test_blob_faults_answer_a_typed_500", "shared", None),
    ("begin_blobs", "blob_store_unavailable"): (CB + "test_begin_blobs_dedupes_and_counts", "layer", "run"),
    ("begin_blobs", "catalog_unavailable"): (H + "test_dead_connection_at_connect_is_503", "shared", None),
    ("begin_blobs", "missing_caller_identity"): (H + "test_missing_or_partial_identity_is_403", "shared", None),
    ("begin_blobs", "occ_exhausted"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("begin_blobs", "project_unregistered"): (CB + "test_begin_blobs_reserved_ref_is_403_before_any_head", "layer", "run"),
    ("begin_blobs", "projection_defect"): (
        E + "test_describe_verbs_and_the_payload_rule_come_from_the_projection",
        "layer",
        "payload_rule",
    ),
    ("begin_blobs", "row_rule"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("begin_blobs", "runtime"): (H + "test_runtime_error_is_500", "shared", None),
    ("begin_blobs", "schema_gate"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("begin_blobs", "telemetry_env_unset"): (H + "test_unset_env_is_500", "shared", None),
    ("begin_blobs", "tenant_unresolved"): (E + "test_begin_blobs_edge_response_and_refusals", "verb", "begin"),
    ("begin_blobs", "too_many_blobs"): (E + "test_begin_blobs_edge_response_and_refusals", "verb", "begin"),
    ("begin_blobs", "unmapped"): (H + "test_unexpected_exception_is_a_typed_500", "shared", None),
    ("describe", "missing_caller_identity"): (H + "test_missing_or_partial_identity_is_403", "shared", None),
    ("describe", "projection_defect"): (
        E + "test_describe_verbs_and_the_payload_rule_come_from_the_projection",
        "layer",
        "payload_rule",
    ),
    ("describe", "telemetry_env_unset"): (H + "test_describe_with_env_unset_is_500", "verb", '"describe"'),
    ("describe", "unmapped"): (H + "test_unexpected_exception_is_a_typed_500", "shared", None),
    ("provision_telemetry", "bad_request"): (
        TA + "test_provision_refuses_force_recreate_keys",
        "verb",
        '"provision_telemetry"',
    ),
    ("provision_telemetry", "catalog_unavailable"): (H + "test_dead_connection_at_connect_is_503", "shared", None),
    ("provision_telemetry", "missing_caller_identity"): (H + "test_missing_or_partial_identity_is_403", "shared", None),
    ("provision_telemetry", "occ_exhausted"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("provision_telemetry", "runtime"): (
        H + "test_provision_absent_tables_maps_to_500_runtime",
        "verb",
        '"provision_telemetry"',
    ),
    ("provision_telemetry", "schema_gate"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("provision_telemetry", "telemetry_env_unset"): (H + "test_unset_env_is_500", "shared", None),
    ("provision_telemetry", "unmapped"): (H + "test_unexpected_exception_is_a_typed_500", "shared", None),
    ("register_tenant", "bad_request"): (
        TA + "test_register_tenant_refuses_principal_parameters",
        "verb",
        '"register_tenant"',
    ),
    ("register_tenant", "catalog_unavailable"): (H + "test_dead_connection_at_connect_is_503", "shared", None),
    ("register_tenant", "missing_caller_identity"): (H + "test_missing_or_partial_identity_is_403", "shared", None),
    ("register_tenant", "occ_exhausted"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_tenant", "row_rule"): (CR + "test_row_rule_violation_writes_nothing", "layer", "resolve_or_register_tenant"),
    ("register_tenant", "runtime"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_tenant", "schema_gate"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_tenant", "telemetry_env_unset"): (H + "test_unset_env_is_500", "shared", None),
    ("register_tenant", "unmapped"): (H + "test_unexpected_exception_is_a_typed_500", "shared", None),
    ("register_project", "bad_request"): (
        H + "test_invalid_request_is_refused_before_any_connection",
        "verb",
        '"register_project"',
    ),
    ("register_project", "catalog_unavailable"): (H + "test_dead_connection_at_connect_is_503", "shared", None),
    ("register_project", "missing_caller_identity"): (H + "test_missing_or_partial_identity_is_403", "shared", None),
    ("register_project", "occ_exhausted"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_project", "row_rule"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_project", "runtime"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_project", "schema_gate"): (H + "test_error_map_rows_for_registration_errors", "shared", None),
    ("register_project", "telemetry_env_unset"): (H + "test_unset_env_is_500", "shared", None),
    ("register_project", "tenant_unresolved"): (
        TA + "test_register_project_requires_a_registered_tenant",
        "verb",
        '"register_project"',
    ),
    ("register_project", "unmapped"): (H + "test_unexpected_exception_is_a_typed_500", "shared", None),
}

# (anchor file, anchor def, error types it originates, verbs that reach it). Handler-level origins apply to every request;
# the others are checked for a name-based call path from the verb's entry function.
ORIGINS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (HANDLER, "_require_caller", ("missing_caller_identity",), ALL_VERBS),
    (HANDLER, "_env", ("telemetry_env_unset",), ALL_VERBS),
    (HANDLER_ERRORS, "terminal", ("unmapped",), ALL_VERBS),
    (HANDLER_ERRORS, "terminal", ("catalog_unavailable",), CONNECTION_VERBS),
    (HANDLER, "_warm_connection", ("runtime",), CONNECTION_VERBS),
    ("src/common/ducklake_telemetry_txn.py", "run_telemetry_txn", ("runtime", "occ_exhausted"), CONNECTION_VERBS),
    (
        "src/common/ducklake_telemetry_registration.py",
        "_write_dimension",
        ("row_rule", "schema_gate"),
        ("append_telemetry", "begin_blobs", "register_tenant", "register_project"),
    ),
    ("src/common/ducklake_scd2_schema.py", "resolve_table_spec", ("schema_gate",), CONNECTION_VERBS),
    (EDGE, "payload_rule", ("projection_defect",), ("describe", "begin_blobs")),
)

Resolver = Callable[[str], "tuple[str, str, ast.Module] | None"]


@lru_cache(maxsize=None)
def _parse(rel: str) -> tuple[str, ast.Module]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    return text, ast.parse(text)


@lru_cache(maxsize=None)
def _contract() -> dict[str, Any]:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _def_source(text: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    start = min([d.lineno for d in node.decorator_list] + [node.lineno])
    return "\n".join(text.splitlines()[start - 1 : node.end_lineno])


def _calls(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                out.add(func.id)
            elif isinstance(func, ast.Attribute):
                out.add(func.attr)
    return out


def _str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _module_consts(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and _str(n.value) is not None:
            out.update({t.id: str(_str(n.value)) for t in n.targets if isinstance(t, ast.Name)})
    return out


def _error_arg(call: ast.Call) -> ast.expr | None:
    func = call.func
    is_super_init = (
        isinstance(func, ast.Attribute)
        and func.attr == "__init__"
        and isinstance(func.value, ast.Call)
        and getattr(func.value.func, "id", "") == "super"
    )
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    index = 1 if name in STATUS_FIRST_CALLS or is_super_init else 0 if name in TYPE_FIRST_CALLS else None
    return call.args[index] if index is not None and len(call.args) > index else None


def _map_targets(node: ast.AST) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []


def _map_rows(tree: ast.AST) -> list[tuple[list[str], str]]:
    """(exception class names, error type) for every row of the three handler maps."""
    rows: list[tuple[list[str], str]] = []
    for node in ast.walk(tree):
        if any(isinstance(t, ast.Name) and t.id in ERROR_MAPS for t in _map_targets(node)) and isinstance(
            getattr(node, "value", None), (ast.Tuple, ast.List)
        ):
            for elt in node.value.elts:
                if not isinstance(elt, ast.Tuple) or not elt.elts:
                    continue
                head = elt.elts[0]
                cls = head.id if isinstance(head, ast.Name) else head.attr if isinstance(head, ast.Attribute) else ""
                texts = [s for s in (_str(e) for e in elt.elts) if s is not None]
                if cls and texts:
                    rows.append(([cls], texts[-1]))
    return rows


def mapped_classes() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for classes, error in _map_rows(_parse(HANDLER)[1]):
        out.setdefault(error, set()).update(classes)
    return out


def _raised_in(tree: ast.Module, names: set[str], consts: Mapping[str, str]) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            for call in (c for c in ast.walk(node) if isinstance(c, ast.Call)):
                arg = _error_arg(call)
                value = _str(arg) if arg is not None else None
                if value is None and isinstance(arg, ast.Name):
                    value = consts.get(arg.id)
                if value:
                    out.add(value)
    return out


def shared_allowed() -> set[str]:
    """Error types the handler answers for any action: its maps, its terminal answers, the identity check, the env pin."""
    text, tree = _parse(HANDLER)
    types = set(mapped_classes()) | _raised_in(tree, {"_require_caller", "_EnvUnsetError"}, _module_consts(tree))
    errors_text, errors_tree = _parse(HANDLER_ERRORS)
    defs = {f.name: f for f in _functions(errors_tree)}
    terminal = _calls(defs["terminal"])
    answered = {
        t
        for t in TERMINAL_ERRORS
        if t in terminal and t in defs and f'"error_type": "{t}"' in _def_source(errors_text, defs[t])
    }
    return types | answered


def read_node(node: str) -> tuple[str, str, ast.Module] | None:
    path, name = node.split("::")
    if not (ROOT / path).exists():
        return None
    text, tree = _parse(path)
    for fn in tree.body:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
            return _def_source(text, fn), text, tree
    return None


def declared_pairs(raw: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {(verb, err) for verb, body in raw["verbs"].items() for err in body.get("typed_errors", {})}


def handler_verbs() -> set[str]:
    """Dispatchable actions by AST (telemetry_actions.VERBS, handler._EDGE_VERBS, handler._ACTIONS) minus non-contract ones."""
    found: set[str] = set()
    for rel, target in ((ACTIONS, "VERBS"), (HANDLER, "_ACTIONS"), (HANDLER, "_EDGE_VERBS")):
        for node in ast.walk(_parse(rel)[1]):
            if any(isinstance(t, ast.Name) and t.id == target for t in _map_targets(node)):
                value = node.value
                if isinstance(value, ast.Call) and value.args:
                    value = value.args[0]
                items = value.keys if isinstance(value, ast.Dict) else value.elts if isinstance(value, ast.Set) else []
                found.update(s for s in (_str(i) for i in items if i is not None) if s)
    return found - NOT_CONTRACT_VERBS


def registry_pair_problems(registry: Mapping[tuple[str, str], Any], declared: set[tuple[str, str]]) -> list[str]:
    keys = set(registry)
    return [f"declared pair has no registry row: {p}" for p in sorted(declared - keys)] + [
        f"registry row for an undeclared pair: {p}" for p in sorted(keys - declared)
    ]


def _names_error(err: str, src: str, mapped: Mapping[str, set[str]]) -> bool:
    if f'"{err}"' in src:
        return True
    return any(re.search(rf"\b(?:Telemetry)?{re.escape(c)}\b", src) for c in mapped.get(err, ()))


def registry_problems(
    registry: Mapping[tuple[str, str], tuple[str, str, str | None]],
    resolve: Resolver,
    mapped: Mapping[str, set[str]],
    allowed_shared: set[str],
) -> list[str]:
    problems: list[str] = []
    for (verb, err), (node, basis, anchor) in sorted(registry.items()):
        label = f"{verb}/{err}"
        found = resolve(node)
        if found is None:
            problems.append(f"{label}: node does not resolve {node}")
            continue
        src, text, tree = found
        if not _names_error(err, src, mapped):
            problems.append(f"{label}: node names neither the error literal nor its mapped class: {node}")
        if basis not in BASES:
            problems.append(f"{label}: basis {basis!r} is not one of {sorted(BASES)}")
        if basis == "shared" and err not in allowed_shared:
            problems.append(f"{label}: shared basis for a verb-specific error")
        if basis == "verb":
            helpers = {
                f.name
                for f in tree.body
                if isinstance(f, ast.FunctionDef) and not f.name.startswith("test_") and f'"{verb}"' in _def_source(text, f)
            }
            if anchor not in {f'"{verb}"', ENTRY.get(verb, "")} | helpers or anchor not in src:
                problems.append(
                    f"{label}: verb anchor {anchor!r} is not the action literal, the entry or a helper present in the node"
                )
        if basis in ("verb", "layer") and anchor and not anchor.startswith('"'):
            called = _calls(ast.parse(_dedent(src)))
            if anchor not in called:
                problems.append(f"{label}: anchor {anchor} is not called in the node")
        if basis == "layer" and (anchor is None or anchor not in src):
            problems.append(f"{label}: layer anchor {anchor!r} is not in the node")
    return problems


def _dedent(src: str) -> str:
    import textwrap  # noqa: PLC0415

    return textwrap.dedent(src)


def scan_emitted(sources: Mapping[str, str]) -> tuple[set[str], list[tuple[str, str, str]]]:
    """Error types the writer can emit, by AST over its raise sites, plus the non-literal error_type arguments found."""
    trees = {path: ast.parse(text) for path, text in sources.items()}
    consts: dict[str, str] = {}
    for tree in trees.values():
        consts.update(_module_consts(tree))
    found: set[str] = set()
    loose: list[tuple[str, str, str]] = []

    def visit(node: ast.AST, path: str, scope: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        if isinstance(node, ast.Call):
            arg = _error_arg(node)
            if arg is not None:
                value = _str(arg) if _str(arg) is not None else consts.get(arg.id) if isinstance(arg, ast.Name) else None
                if value is not None:
                    found.add(value)
                else:
                    loose.append((path, scope, ast.unparse(arg)))
        if any(isinstance(t, ast.Name) and t.id in ERROR_MAPS for t in _map_targets(node)):
            for elt in getattr(getattr(node, "value", None), "elts", []):
                found.update(s for s in (_str(e) for e in getattr(elt, "elts", [])) if s)
        for child in ast.iter_child_nodes(node):
            visit(child, path, scope)

    for path, tree in trees.items():
        visit(tree, path, "")
    return found, loose


def _response_text(body: Mapping[str, Any]) -> str:
    return " ".join(str(v) for v in body.get("response_codes", {}).values())


def emitted_problems(
    emitted: set[str],
    loose: list[tuple[str, str, str]],
    raw: Mapping[str, Any],
) -> list[str]:
    declared = declared_pairs(raw)
    union = {err for _, err in declared}
    invariants = " ".join(raw["audit_invariants"])
    problems = [f"writer emits an error type no verb declares: {e}" for e in sorted(emitted - union - {"unknown_action"})]
    problems += [f"declared error type nothing emits: {e}" for e in sorted(union - emitted)]
    if "unknown_action" not in emitted or "unknown_action" not in invariants:
        problems.append("unknown_action must be emitted and named in the audit invariants")
    problems += [
        f"non-literal error_type argument outside the allow-listed pass-through: {item}"
        for item in loose
        if item != PASS_THROUGH
    ]
    for verb, err in sorted(declared):
        if not re.search(rf"\b{re.escape(err)}\b", _response_text(raw["verbs"][verb])):
            problems.append(f"{verb}/{err} is declared but not named in the verb's response_codes")
    return problems


def call_graph(sources: Mapping[str, str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for text in sources.values():
        for fn in _functions(ast.parse(text)):
            graph.setdefault(fn.name, set()).update(_calls(fn))
    return graph


def reaches(graph: Mapping[str, set[str]], starts: set[str], target: str) -> bool:
    seen, queue = set(starts), deque(starts)
    while queue:
        name = queue.popleft()
        if name == target:
            return True
        for nxt in graph.get(name, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def origin_problems(
    origins: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...],
    declared: set[tuple[str, str]],
    defs: Mapping[str, set[str]],
    graph: Mapping[str, set[str]],
    entry: Mapping[str, str] = ENTRY,
) -> list[str]:
    problems: list[str] = []
    for path, anchor, errors, verbs in origins:
        if anchor not in defs.get(path, set()):
            problems.append(f"origin {anchor} is not a def in {path}")
        for verb in verbs:
            problems += [
                f"origin {anchor} implies {verb}/{e}, which the contract omits" for e in errors if (verb, e) not in declared
            ]
            if anchor in HANDLER_LEVEL_ORIGINS:
                continue
            starts = {entry[verb]} | ({"run_verb"} if verb in CONNECTION_VERBS else set())
            if not reaches(graph, starts, anchor):
                problems.append(f"{verb} has no call path to origin {anchor}")
    return problems


def _graph_sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in GRAPH_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            out[str(path.relative_to(ROOT))] = path.read_text(encoding="utf-8")
    return out


def _defs_by_file(extra: tuple[str, ...]) -> dict[str, set[str]]:
    return {rel: {f.name for f in _functions(_parse(rel)[1])} for rel in extra}


class TestWriterContractRatification:
    def test_contract_is_ratified_with_census(self) -> None:
        raw = _contract()
        c = raw["contract"]
        assert c["status"] == "ratified" and c["contract_version"] == 1
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c["ratified_at"]))
        for needle in ("Benjamin", "PLAN-ratify-telemetry-writer-contract", "Decision 118"):
            assert needle in c["ratified_via"]
        prov = c["provisional_v0"]
        assert prov["trigger_observed_at"] == "2026-10-29"
        assert "1,836" in prov["ratification_census"] and "PlatformAdmin" in prov["ratification_census"]
        invariants = " ".join(raw["audit_invariants"])
        for needle in (
            "unknown_action",
            "Both are refused before any verb is chosen",
            "Except the declared rec-4317 residual",
            "Declared residual (rec-4492)",
            "Declared residual (principal classes)",
        ):
            assert needle in invariants
        newest = [(e["change_class"], e["semantic_break"]) for e in raw["amendment_log"][:3]]
        assert newest == [("governance_note_add", False), ("field_add", False), ("prose_improvement", False)]

    def test_registry_matches_contract(self) -> None:
        raw = _contract()
        assert registry_pair_problems(TYPED_ERROR_TESTS, declared_pairs(raw)) == []
        assert len(declared_pairs(raw)) == 71
        assert set(raw["verbs"]) == handler_verbs()

    def test_registry_nodes_resolve_and_name_their_error(self) -> None:
        assert registry_problems(TYPED_ERROR_TESTS, read_node, mapped_classes(), shared_allowed()) == []

    def test_registry_bases_are_allowed(self) -> None:
        allowed = shared_allowed()
        assert {"unmapped", "catalog_unavailable", "missing_caller_identity", "telemetry_env_unset"} <= allowed
        assert {b for _, b, _ in TYPED_ERROR_TESTS.values()} <= BASES
        bad = sorted(k for k, (_, basis, _) in TYPED_ERROR_TESTS.items() if basis == "shared" and k[1] not in allowed)
        assert bad == []

    def test_emitted_errors_equal_declared(self) -> None:
        emitted, loose = scan_emitted({rel: _parse(rel)[0] for rel in EMIT_MODULES})
        assert emitted_problems(emitted | set(TERMINAL_ERRORS), loose, _contract()) == []

    def test_origin_errors_are_declared_per_verb(self) -> None:
        defs = _defs_by_file(tuple(sorted({o[0] for o in ORIGINS})))
        assert origin_problems(ORIGINS, declared_pairs(_contract()), defs, call_graph(_graph_sources())) == []

    def test_registry_checks_fail_on_drift(self) -> None:
        raw = {
            "verbs": {"v": {"typed_errors": {"a": "", "b": ""}, "response_codes": {"400": "a"}}},
            "audit_invariants": ["unknown_action"],
        }
        pairs = declared_pairs(raw)
        assert emitted_problems({"a", "b", "unknown_action"}, [], raw) == [
            "v/b is declared but not named in the verb's response_codes"
        ]
        assert any("no verb declares: z" in p for p in emitted_problems({"a", "b", "z", "unknown_action"}, [], raw))
        assert any("nothing emits: b" in p for p in emitted_problems({"a", "unknown_action"}, [], raw))
        assert any("non-literal" in p for p in emitted_problems({"a", "b", "unknown_action"}, [("x.py", "f", "e.t")], raw))
        assert registry_pair_problems({("v", "a"): ()}, pairs) == ["declared pair has no registry row: ('v', 'b')"]
        assert registry_pair_problems({("v", "a"): (), ("v", "b"): (), ("v", "c"): ()}, pairs) == [
            "registry row for an undeclared pair: ('v', 'c')"
        ]

        src = 'def test_x():\n    assert "a" and entry()\n'
        tree = ast.parse(src)
        nodes = {"n::test_x": (src, src, tree)}

        def resolve(node: str) -> tuple[str, str, ast.Module] | None:
            return nodes.get(node)

        def check(err: str, node: str, basis: str, anchor: str | None) -> list[str]:
            return registry_problems({("describe", err): (node, basis, anchor)}, resolve, {}, {"unmapped"})

        assert check("a", "n::test_x", "layer", "entry") == []
        assert any("does not resolve" in p for p in check("a", "n::gone", "layer", "entry"))
        assert any("names neither" in p for p in check("b", "n::test_x", "layer", "entry"))
        assert any("not called" in p for p in check("a", "n::test_x", "layer", "other"))
        assert any("verb anchor" in p for p in check("a", "n::test_x", "verb", "other"))
        assert any("shared basis" in p for p in check("a", "n::test_x", "shared", None))

        origins = (("m.py", "origin", ("e",), ("p", "q")),)
        graph = {"entry_p": {"mid"}, "mid": {"origin"}}
        found = origin_problems(origins, {("p", "e")}, {"m.py": {"origin"}}, graph, {"p": "entry_p", "q": "entry_q"})
        assert found == ["origin origin implies q/e, which the contract omits", "q has no call path to origin origin"]
