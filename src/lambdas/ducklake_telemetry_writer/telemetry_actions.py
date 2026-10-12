"""Verb bodies of the telemetry writer (T2.36, slice 2a-2, plan 3 part 1), called by the handler as (request, con, deps).

provision_telemetry, register_tenant and register_project are the write verbs (each runs through run_telemetry_txn with the
function's metric sink); telemetry_probe is gate instrumentation, out of contract scope like the function's other probes.
Every verb declares its allowed request keys; "component" (a string) is allowed on every verb. Every string a verb accepts
must be a str with no U+0000 and no lone surrogate, else 400 bad_request naming the FIELD, never the value, before any
catalog read (a NUL in a value DuckLake renders into its file-pruning SQL raises an unmapped ParserException that echoes the
value and pages as a Lambda error). Responses never carry principal.ref or a hash of it (Decision 101).

This module imports src.common telemetry modules; nothing under scripts/ imports it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.common import ducklake_telemetry_provision as prov
from src.common import ducklake_telemetry_registration as reg
from src.common.ducklake_scd2_schema import CATALOG_ALIAS, resolve_table_spec
from src.common.ducklake_telemetry_txn import TelemetryRequestError, invalid_string_field, run_telemetry_txn

_COMMON = frozenset({"action", "component"})
_ALLOWED: dict[str, frozenset[str]] = {
    "provision_telemetry": _COMMON,
    "register_tenant": _COMMON,
    "register_project": _COMMON | {"project_ref", "name", "remote"},
    "telemetry_probe": _COMMON,
}
_STRING_KEYS = ("component", "project_ref", "name", "remote")
_BACKEND_SUFFIXES = (("neon.tech", "neon"), ("rds.amazonaws.com", "rds"))


@dataclass(frozen=True)
class TelemetryRequest:
    action: str
    body: dict[str, Any]
    principal: reg.CallerPrincipal
    request_bytes: int


@dataclass(frozen=True)
class Deps:
    semantics: dict[str, Any]
    metric_sink: Callable[[str, float], None] | None
    meta_schema: str
    data_path_is_smoke: bool
    catalog_login: str
    catalog_backend: str
    connect_reused: bool
    sleep: Callable[[float], None] = time.sleep


def classify_backend(host: str) -> str:
    """neon, rds or other, from the catalog host's public suffix. The host itself is never returned or logged."""
    name = host.lower().rstrip(".")
    for suffix, backend in _BACKEND_SUFFIXES:
        if name == suffix or name.endswith("." + suffix):
            return backend
    return "other"


def validate_request(request: TelemetryRequest) -> None:
    """Refuse an unknown key or an invalid string with a value-free 400, before any catalog read."""
    allowed = _ALLOWED[request.action]
    if not set(request.body) <= allowed:
        raise TelemetryRequestError(400, "bad_request", {"allowed_keys": sorted(allowed - {"action"})})
    bad = invalid_string_field({k: request.body[k] for k in _STRING_KEYS if k in request.body})
    if bad is not None:
        raise TelemetryRequestError(400, "bad_request", {"field": bad})


def provision_telemetry(request: TelemetryRequest, con: Any, deps: Deps) -> dict[str, Any]:
    validate_request(request)
    outcome = run_telemetry_txn(
        con,
        lambda c: prov.provision_telemetry_catalog(c, semantics=deps.semantics),
        metric_sink=deps.metric_sink,
        sleep=deps.sleep,
    )
    result = outcome.result
    return {"ok": True, "tables": list(result.tables), "counters": result.counters}


def register_tenant(request: TelemetryRequest, con: Any, deps: Deps) -> dict[str, Any]:
    validate_request(request)
    done = reg.register_tenant(
        con, request.principal, semantics=deps.semantics, metric_sink=deps.metric_sink, sleep=deps.sleep
    )
    return {"ok": True, "tenant_id": done.entity_id, "created": done.created}


def register_project(request: TelemetryRequest, con: Any, deps: Deps) -> dict[str, Any]:
    validate_request(request)
    project_ref = request.body.get("project_ref")
    if not project_ref:
        raise TelemetryRequestError(400, "bad_request", {"field": "project_ref"})
    attributes: dict[str, Any] = {k: request.body[k] for k in ("name", "remote") if k in request.body}
    done = reg.register_project(
        con,
        request.principal,
        project_ref,
        attributes=attributes,
        semantics=deps.semantics,
        metric_sink=deps.metric_sink,
        sleep=deps.sleep,
    )
    purpose = reg.purpose_for(project_ref, reg.purpose_derivation(deps.semantics))
    return {
        "ok": True,
        "project_id": done.entity_id,
        "created": done.created,
        "purpose": purpose,
        "registration": "registered",
    }


def _count_sessions(con: Any) -> tuple[int | None, str | None]:
    """The scoped login's session count from pg_stat_activity through the catalog's postgres database, or (None, reason)."""
    try:
        row = con.execute("SELECT database_name FROM duckdb_databases() WHERE type = 'postgres' LIMIT 1").fetchone()
        if row is None:
            return None, "no_postgres_catalog"
        database = str(row[0]).replace("'", "''")
        count = con.execute(
            f"SELECT * FROM postgres_query('{database}', 'SELECT count(*) FROM pg_stat_activity WHERE usename = current_user')"
        ).fetchone()
        return int(count[0]), None
    except Exception as exc:  # noqa: BLE001 -- a measurement: never fails the probe, never echoes the message
        return None, type(exc).__name__


def _scalar(con: Any, sql: str, params: list[Any] | None = None) -> int:
    return int(con.execute(sql, params or []).fetchone()[0])


def telemetry_probe(request: TelemetryRequest, con: Any, deps: Deps) -> dict[str, Any]:
    validate_request(request)
    existing = prov.existing_tables(con)
    partitions = prov.inspect_partitions(con, existing, deps.semantics)
    tables = {
        name: {"present": name in existing, "partitioned_as_declared": partitions.get(name, False)}
        for name in prov.target_tables(deps.semantics)
    }
    counters: dict[str, int | None] = {}
    counter_rows: dict[str, int] = {}
    current_counts: dict[str, int | None] = {}
    have_counters = prov.ENTITY_COUNTERS_TABLE in existing
    for name in prov.SEEDED_COUNTERS:
        current = str(resolve_table_spec(name, deps.semantics).current_table)
        current_counts[name] = _scalar(con, f"SELECT count(*) FROM {CATALOG_ALIAS}.{current}") if current in existing else None
        counter_rows[name] = 0
        counters[name] = None
        if have_counters:
            where = f"FROM {CATALOG_ALIAS}.{prov.ENTITY_COUNTERS_TABLE} WHERE counter_name = ?"
            counter_rows[name] = _scalar(con, f"SELECT count(*) {where}", [name])
            if counter_rows[name] == 1:
                counters[name] = _scalar(con, f"SELECT current_value {where}", [name])
    sessions, reason = _count_sessions(con)
    return {
        "ok": True,
        "meta_schema": deps.meta_schema,
        "data_path_is_smoke": deps.data_path_is_smoke,
        "connect_reused": deps.connect_reused,
        "catalog_login": deps.catalog_login,
        "catalog_backend": deps.catalog_backend,
        "catalog_sessions": sessions,
        "catalog_sessions_reason": reason,
        "tables": tables,
        "counters": counters,
        "counter_rows": counter_rows,
        "current_counts": current_counts,
    }


VERBS: dict[str, Callable[[TelemetryRequest, Any, Deps], dict[str, Any]]] = {
    "provision_telemetry": provision_telemetry,
    "register_tenant": register_tenant,
    "register_project": register_project,
    "telemetry_probe": telemetry_probe,
}
