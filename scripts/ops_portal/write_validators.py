"""Write-time rec-field content validation, driven by config/agent/data_quality/ops.yaml.

Owner-concern: the three explicit content-quality checks (path syntax, context length,
not-null) plus the YAML-driven write_time validator loader that file_rec() (kept in the
facade) runs before any write reaches the DuckLake writer.
"""

from __future__ import annotations

import re
from typing import Callable

import yaml

from scripts.executor.acceptance_lint import lint_acceptance_command
from scripts.ops_portal._common import ROOT

_OPS_YAML_PATH = ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
_write_time_validators_cache: dict[str, list] = {}


def _validate_file_path(path: str) -> None:
    """Raise ValueError if path is absolute or uses backslash separators."""
    if not path:
        return
    if path.startswith("/"):
        raise ValueError(f"file must be a repo-relative path with forward slashes (got absolute Unix path): {path!r}")
    if re.match(r"[A-Za-z]:[/\\]", path):
        raise ValueError(f"file must be a repo-relative path with forward slashes (got absolute Windows path): {path!r}")
    if "\\" in path:
        raise ValueError(f"file must use forward slashes as path separators (got backslash): {path!r}")


def _validate_context_length(text: str) -> None:
    """Raise ValueError if stripped context is shorter than 80 characters."""
    if not text:
        return
    stripped_len = len(text.strip())
    if stripped_len < 80:
        raise ValueError(
            f"context must be at least 80 stripped characters (got {stripped_len}). "
            "Answer 'what problem does this solve and why now?'"
        )


def _check_not_null(v: object, col: str) -> None:
    if v is None or not str(v).strip():
        raise ValueError(f"required field '{col}' must be non-empty")


def _build_not_null_validator(params: dict) -> Callable:
    return _check_not_null


def _build_accepted_values_validator(params: dict) -> Callable:
    allowed = list(params.get("values", []))

    def _check(v: object, col: str) -> None:
        if v is not None and str(v).strip() and str(v) not in allowed:
            raise ValueError(f"{col} must be one of {allowed!r}, got {str(v)!r}")

    return _check


def _build_path_syntax_validator(params: dict) -> Callable:
    return lambda v, col: _validate_file_path(str(v) if v else "")


def _build_acceptance_lint_validator(params: dict) -> Callable:
    def _check(v: object, col: str) -> None:
        ok, msg = lint_acceptance_command(str(v) if v else "", require_discrimination=True)
        if not ok:
            raise ValueError(msg)

    return _check


def _build_array_element_format_validator(params: dict) -> Callable:
    pattern = params.get("pattern", "")

    def _check(v: object, col: str) -> None:
        if v is None:
            return
        if not isinstance(v, list):
            raise ValueError(f"{col} must be a list of strings, got {type(v).__name__}")
        bad = [str(x) for x in v if not re.fullmatch(pattern, str(x))]
        if bad:
            raise ValueError(f"{col} elements must match {pattern!r}; invalid: {bad!r}")

    return _check


def _build_min_length_validator(params: dict) -> Callable:
    bound = params.get("value")
    if not isinstance(bound, int):
        raise ValueError(f"min_length test declares a non-integer 'value' parameter: {bound!r}")

    def _check(v: object, col: str) -> None:
        if not v or not str(v).strip():
            return
        stripped_len = len(str(v).strip())
        if stripped_len < bound:
            raise ValueError(f"{col} must be at least {bound} stripped characters (got {stripped_len})")

    return _check


def _build_expression_validator(params: dict) -> None:
    """Retired write-time branch (rec-3310).

    expression used to bind _validate_context_length to ANY column regardless of its declared
    sql/python content -- a landmine, since a column's write_time flag on expression silently
    inherited context's 80-char rule. min_length is the parameterised write-time replacement; a
    write_time: true expression now yields no validator rather than reviving that hardcoded
    binding. Recognised (present in _WRITE_TIME_VALIDATOR_BUILDERS, not an unrecognised-name
    raise) because expression remains a legitimate SQL-only test type for the compiler; only its
    write-time capability is retired.
    """
    return


# One builder per recognised write_time test name; each takes the test's params dict and returns
# either a (v, col) -> None validator callable, or None for a recognised-but-inert type
# (_build_expression_validator). A test_name outside this map is unrecognised and loud-fails
# rather than silently falling through (rec-3308 sibling gap). Kept as top-level functions rather
# than nested closures so each stays its own small AST node for the Decision 43 cyclomatic-
# complexity gate, instead of inflating _load_write_time_validators's own branch count.
_WRITE_TIME_VALIDATOR_BUILDERS: dict[str, Callable[[dict], Callable | None]] = {
    "not_null": _build_not_null_validator,
    "accepted_values": _build_accepted_values_validator,
    "path_syntax": _build_path_syntax_validator,
    "acceptance_lint": _build_acceptance_lint_validator,
    "array_element_format": _build_array_element_format_validator,
    "min_length": _build_min_length_validator,
    "expression": _build_expression_validator,
}


def _load_write_time_validators(table: str) -> list[tuple[str, Callable]]:
    """Load write-time validators from ops.yaml for the given table.

    Returns a list of (column_name, validator_fn) tuples for every test entry
    with write_time: true. Result is cached to avoid repeated YAML reads.
    """
    if table in _write_time_validators_cache:
        return _write_time_validators_cache[table]

    try:
        data = yaml.safe_load(_OPS_YAML_PATH.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        _write_time_validators_cache[table] = []
        return []

    columns = data.get("tables", {}).get(table, {}).get("columns", {})
    validators: list[tuple[str, Callable]] = []

    for col_name, col_def in columns.items():
        if not isinstance(col_def, dict):
            continue
        for test_entry in col_def.get("tests", []):
            if not isinstance(test_entry, dict):
                continue
            for test_name, params in test_entry.items():
                if not isinstance(params, dict) or not params.get("write_time"):
                    continue
                builder = _WRITE_TIME_VALIDATOR_BUILDERS.get(test_name)
                if builder is None:
                    raise ValueError(f"{col_name}: unrecognised write_time test {test_name!r}")
                validator = builder(params)
                if validator is not None:
                    validators.append((col_name, validator))

    _write_time_validators_cache[table] = validators
    return validators
