"""Maintenance policy matrix exhaustiveness gate (compaction-scope-policy-matrix, Decision 191).

The matrix (config/lambda/ducklake/field_semantics.static.yaml -> maintenance_policy) must declare
a cell for every (class, verb) pair, and any apply=false cell must carry a reason. Both universes
are DECLARED independently of the matrix itself:

  - class universe: every distinct write_mode value across the live field_semantics ops_tables
    registry (scripts/schema_to_field_semantics.py's generated projection, read via
    src.common.ducklake_scd2_schema.load_field_semantics) -- never the matrix's own top-level keys.
  - verb universe: src.common.ducklake_maintenance_scope.VERB_UNIVERSE, an explicit list -- never
    the matrix's own per-class keys.

A matrix that supplied its own universe from either source would be a blind oracle: it would be
trivially exhaustive against itself and could never fail -- exactly the failure mode this plan
exists to close.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts.checks import _common, registry
from src.common.ducklake_maintenance_scope import VERB_UNIVERSE

_SIDECAR_PATH = _common.ROOT / "config" / "lambda" / "ducklake" / "field_semantics.static.yaml"


def _declared_class_universe() -> set[str]:
    """The live table-class universe, derived from write_mode across field_semantics ops_tables."""
    from src.common.ducklake_scd2_schema import load_field_semantics

    semantics = load_field_semantics()
    ops_tables = semantics.get("ops_tables", {})
    return {spec.get("write_mode", "scd2") for spec in ops_tables.values()}


def _load_matrix(sidecar_path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
    return doc.get("maintenance_policy") or {}


@registry.register("validate_maintenance_policy_matrix", owner="platform")
def validate_maintenance_policy_matrix(
    failed: list[str],
    *,
    sidecar_path: Path | None = None,
    class_universe: set[str] | None = None,
    verb_universe: tuple[str, ...] | None = None,
) -> None:
    """Fail unless the sidecar's maintenance_policy matrix is exhaustive over the DECLARED class x
    verb universe, with a reason on every apply=false cell, and no cell for an undeclared class."""
    print("\n=== Maintenance policy matrix exhaustiveness (compaction-scope-policy-matrix) ===")
    path = sidecar_path if sidecar_path is not None else _SIDECAR_PATH
    classes = class_universe if class_universe is not None else _declared_class_universe()
    verbs = verb_universe if verb_universe is not None else VERB_UNIVERSE

    try:
        matrix = _load_matrix(path)
    except OSError as exc:
        failed.append(f"Maintenance policy matrix: could not read {path}: {exc}")
        return

    violations: list[str] = []
    examined = 0

    for cls in matrix:
        if cls not in classes:
            violations.append(
                f"class {cls!r} appears in maintenance_policy but not in the declared class universe (unknown class)"
            )

    for cls in sorted(classes):
        cell_row = matrix.get(cls)
        if not isinstance(cell_row, dict):
            violations.append(f"class {cls!r}: no row in maintenance_policy")
            continue
        for verb in verbs:
            examined += 1
            cell = cell_row.get(verb)
            if not isinstance(cell, dict) or "apply" not in cell:
                violations.append(f"class {cls!r} verb {verb!r}: missing cell or missing 'apply'")
                continue
            if cell["apply"] is False and not cell.get("reason"):
                violations.append(f"class {cls!r} verb {verb!r}: apply=false but no 'reason'")

    registry.examined(examined, unit="matrix_cells")

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
        failed.append("Maintenance policy matrix exhaustiveness")
    else:
        print(f"  PASS: matrix exhaustive over {len(classes)} class(es) x {len(verbs)} verb(s).")
