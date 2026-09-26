"""Shared identifier/path guards for the ducklake_maintenance Lambda (Decision 204 extraction).

EXTENSION_DIRECTORY and _require_identifier (+ its regex) moved here out of handler.py so
partition_actions.py can use them without an import cycle: handler.py imports partition_actions
for its dispatch entries, so partition_actions.py can never import handler.py back (Decision 80
acyclic-import discipline). handler.py re-binds both moved names from here, so its existing tests
and callers are unaffected. Also carries a NEW s3:// data_path guard used only by
partition_actions.py -- handler.py's own per-action inline data_path guards are unchanged.
"""

from __future__ import annotations

import os
import re
from typing import Any

from src.common import ducklake_runtime as rt

EXTENSION_DIRECTORY = os.environ.get("DUCKLAKE_EXTENSION_DIRECTORY", rt.LAMBDA_EXTENSION_DIRECTORY)

# A SQL identifier (meta-schema name) -- guards the few f-string-interpolated DDL sites.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_identifier(name: Any) -> str:
    """Validate *name* is a bare SQL identifier (guards the f-string-interpolated meta-schema DDL)."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise rt.DuckLakeRuntimeError(f"invalid SQL identifier {name!r} (expected [A-Za-z_][A-Za-z0-9_]*)")
    return name


def _require_data_path(value: Any) -> str:
    """Validate *value* is an s3:// data_path URI (guards partition_actions' event parsing)."""
    if not isinstance(value, str) or not value.startswith("s3://"):
        raise rt.DuckLakeRuntimeError(f"invalid data_path {value!r} -- expected an s3:// URI (the production DuckLake path)")
    return value
