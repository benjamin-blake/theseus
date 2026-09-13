"""Table-registration admission control (Decision 170).

A CREATE TABLE under src/ that targets the shared ops_catalog namespace must resolve to a table
name present in the live registry (ops_table_names() union control_table_names()). Landed
alongside the control-table-class-and-counter-conformance plan (T2.26) because its own root cause
was exactly this admission gap: ensure_entity_counters_table's `CREATE TABLE IF NOT EXISTS
{CATALOG_ALIAS}.{ENTITY_COUNTERS_TABLE}` shipped years before ops_entity_counters was ever
registered anywhere, and nothing would have caught a repeat.

Resolution is ONE HOP through `from X import NAME` (mirrors the contracts $ref single-hop
convention, scripts/contracts.py resolve_refs) -- module-level `NAME = "literal"` assignments are
resolved locally; an imported name is resolved by reading its origin module's own module-level
assignment. A name that resolves through neither path (a local variable built from an attribute
expression, e.g. ducklake_tables.py's `history = f"{CATALOG_ALIAS}.{spec.history_table}"`) is
silently skipped, not flagged: those names are already registry-derived by construction
(resolve_table_spec / resolve_control_spec IS the registry), so there is no admission gap there.
A CREATE TABLE whose catalog constant resolves to something OTHER than the live CATALOG_ALIAS
value (e.g. ducklake_spike.py's `_CATALOG_ALIAS = "spike_lake"` throwaway probe catalog) is
likewise skipped -- this check polices the shared GOVERNED ops_catalog namespace, not every
physical DuckDB table in the repository.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from scripts.checks import _common, registry

_CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s*\{(\w+)\}\.\{(\w+)\}", re.IGNORECASE)


def _collect_local_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level (top-level only, never inside a function/class) `NAME = "literal"` assignments."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _collect_import_sources(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """local_name -> (dotted_module, original_name) for every module-level `from X import Y [as Z]`."""
    out: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                local = alias.asname or alias.name
                out[local] = (node.module, alias.name)
    return out


def _module_dotted_to_path(root: Path, dotted: str) -> Path | None:
    candidate = root.joinpath(*dotted.split(".")).with_suffix(".py")
    return candidate if candidate.is_file() else None


def _resolve_constant(
    name: str,
    *,
    root: Path,
    local_consts: dict[str, str],
    imports: dict[str, tuple[str, str]],
) -> str | None:
    """Resolve *name* to a literal string: local assignment first, else ONE hop through its
    `from X import` origin module's own local assignment. None if unresolvable either way."""
    if name in local_consts:
        return local_consts[name]
    origin = imports.get(name)
    if origin is None:
        return None
    dotted, original = origin
    target_path = _module_dotted_to_path(root, dotted)
    if target_path is None:
        return None
    try:
        target_tree = ast.parse(target_path.read_text(encoding="utf-8"), filename=str(target_path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    return _collect_local_string_constants(target_tree).get(original)


def _live_registry(root: Path) -> tuple[set[str], str] | None:
    """(known table names, live CATALOG_ALIAS value) -- None if the live registry can't be imported."""
    root_str = str(root)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from src.common.ducklake_control_tables import control_table_names
        from src.common.ducklake_scd2_schema import CATALOG_ALIAS, ops_table_names

        return set(ops_table_names()) | set(control_table_names()), CATALOG_ALIAS
    except ImportError:
        return None
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


@registry.register("validate_table_registration", owner="platform")
def validate_table_registration(
    failed: list[str],
    *,
    src_dir: Path | None = None,
    known_tables: set[str] | None = None,
    catalog_alias: str | None = None,
    import_root: Path | None = None,
) -> None:
    """Fail when a CREATE TABLE under src/ resolves to an unregistered ops_catalog table name.

    `src_dir` / `known_tables` / `catalog_alias` / `import_root` are test-isolation overrides;
    production always scans ROOT/src against the live registry (ops_table_names() union
    control_table_names()), the live CATALOG_ALIAS value, and follows `from X import Y` one-hop
    imports rooted at ROOT (dotted paths like `src.common.ducklake_scd2_schema` are ROOT-relative).
    """
    print("\n=== Table registration admission control (Decision 170) ===")
    root = _common.ROOT
    target_dir = src_dir if src_dir is not None else root / "src"
    resolve_root = import_root if import_root is not None else root

    if known_tables is None or catalog_alias is None:
        live = _live_registry(root)
        if live is None:
            failed.append("Table registration admission control: could not import the live table registry")
            registry.skipped("live table registry unavailable")
            return
        live_tables, live_alias = live
        known_tables = known_tables if known_tables is not None else live_tables
        catalog_alias = catalog_alias if catalog_alias is not None else live_alias

    violations: list[str] = []
    examined_count = 0

    for path in sorted(target_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        matches = list(_CREATE_TABLE_RE.finditer(text))
        if not matches:
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        local_consts = _collect_local_string_constants(tree)
        imports = _collect_import_sources(tree)
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path

        for m in matches:
            catalog_name, table_name = m.group(1), m.group(2)
            resolved_catalog = _resolve_constant(catalog_name, root=resolve_root, local_consts=local_consts, imports=imports)
            if resolved_catalog != catalog_alias:
                continue  # unresolvable, or a different (non-governed) catalog -- out of scope
            resolved_table = _resolve_constant(table_name, root=resolve_root, local_consts=local_consts, imports=imports)
            if resolved_table is None:
                continue  # dynamically-built name (e.g. spec.history_table) -- registry-derived already
            examined_count += 1
            if resolved_table not in known_tables:
                violations.append(
                    f"{rel}: CREATE TABLE resolves to {resolved_table!r} (catalog {catalog_alias!r}), which "
                    "is absent from the live table registry (ops_table_names() union "
                    "control_table_names()) -- register it via a Class A contract / control-class "
                    "registry entry before landing this DDL."
                )

    registry.examined(examined_count, unit="create_table_statements")

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
        failed.append("Table registration admission control")
    else:
        print(f"  PASS: {examined_count} CREATE TABLE statement(s) resolved and registered.")
