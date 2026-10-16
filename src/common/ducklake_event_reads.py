"""Event-journal read mechanism for the ducklake_reader Lambda (Decision 199 cl.1, Decision 207, Decision 84 I-3).

The telemetry tables are event journals read through a second, isolated warm connection (the "telemetry" slot) by named
verbs whose SQL is registry content. This module owns the EventRead type, parameter validation (before any SQL or
connection), the smoke-pin refusal, the partition binding, the compared-column set behind the conflict report, the
event_read_version stamp, execution, and the routing helpers the reader handler calls.

Imported by the reader handler only. Import direction (no cycle): ducklake_event_read_verbs imports EventRead from here at
module scope; the routing helpers here import EVENT_READS function-locally. Nothing in ducklake_runtime's import closure
imports this module, so the other DuckLake bundles need no new file. Event reads use src.telemetry.identity/timestamps and
src.row_rules only, never src.telemetry.append.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from src.common import ducklake_runtime as rt
from src.common.ducklake_event_read_sql import AGENTS, OBSERVATIONS, SESSIONS, TRANSCRIPTS
from src.row_rules.rules import RowRules
from src.telemetry.identity import IdentityError, canonical_ulid, decode_time_prefix
from src.telemetry.timestamps import TimestampError, parse_iso8601_utc

TELEMETRY_SLOT = "telemetry"
TELEMETRY_MEMORY_LIMIT = "300MB"
KIND = "event_journal"
CATALOG = "telemetry"

_STRUCTURAL_EXCLUDED = frozenset({"created_timestamp", "producer_version"})
_EVENT_TABLES = (SESSIONS, OBSERVATIONS, TRANSCRIPTS, AGENTS)
_PLACEHOLDER_TABLES = {
    "sessions": SESSIONS,
    "observations": OBSERVATIONS,
    "agents": AGENTS,
    "transcripts": TRANSCRIPTS,
}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOUND_NAME = re.compile(r"\$([a-z_]+)")
_SCOPE_SESSION = "session_started_at >= $part_from AND session_started_at < $part_to AND session_id = $session_id"
_INT_MIN = {"parser_version": 1, "offset": 0, "max_bytes": 1}
_PRODUCER_MAX = 200
_SCOPE_WINDOW = "session_started_at >= $part_from AND session_started_at < $part_to"


class EventReadInputError(Exception):
    """A caller value is refused before any SQL: answered 400 named_read_input naming the parameter, never its value."""

    def __init__(self, verb: str, param: str, reason: str) -> None:
        super().__init__(f"{verb}: parameter {param!r} {reason}")
        self.verb = verb
        self.param = param
        self.error_class = type(self).__name__


@dataclass(frozen=True)
class EventRead:
    """One event-journal read verb: registry SQL over the telemetry tables, bound by a session or a day window."""

    verb: str
    tables: tuple[str, ...]
    sql: str
    params: tuple[str, ...] = ()
    binding: str = "none"  # session | window | none
    max_window_days: int | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""
    paginable: bool = False
    agent_facing: bool = True
    int_params: tuple[str, ...] = ()


def _event_reads() -> dict[str, EventRead]:
    from src.common.ducklake_event_read_verbs import (
        EVENT_READS,  # noqa: PLC0415 -- the verbs module imports EventRead from here
    )

    return EVENT_READS


def is_event_verb(verb: Any) -> bool:
    return isinstance(verb, str) and verb in _event_reads()


# ---------------------------------------------------------------------------
# Pin, validation and partition binding
# ---------------------------------------------------------------------------


def telemetry_pin() -> tuple[str, str]:
    """The pinned (meta_schema, data_path) the reader's telemetry slot attaches."""
    return os.environ.get("TELEMETRY_META_SCHEMA", ""), os.environ.get("TELEMETRY_DATA_PATH", "")


def require_smoke_pin() -> tuple[str, str]:
    """Refuse every event verb unless the pin names the single-tenant smoke catalog (Decision 200 cl.2, rec-4292)."""
    meta_schema, data_path = telemetry_pin()
    if meta_schema != rt.SMOKE_META_SCHEMA or data_path.rstrip("/") != rt.SMOKE_DATA_PATH.rstrip("/"):
        raise rt.DuckLakeRuntimeError(
            "event-journal reads are refused unless TELEMETRY_META_SCHEMA and TELEMETRY_DATA_PATH name the smoke catalog: "
            "the verbs carry no tenant predicate, so slice 2c lifts this refusal together with tenant-scoped reads (rec-4292, "
            "Decision 200 cl.2)"
        )
    return meta_schema, data_path


def _ulid(entry: EventRead, name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise EventReadInputError(entry.verb, name, "must be a string")
    try:
        canonical = canonical_ulid(value)
    except IdentityError:
        raise EventReadInputError(entry.verb, name, "must be a canonical 26-character ULID") from None
    if canonical != value:
        raise EventReadInputError(entry.verb, name, "must be a canonical 26-character ULID")
    return value


def _producer(entry: EventRead, value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > _PRODUCER_MAX or "\x00" in value:
        raise EventReadInputError(entry.verb, "producer", f"must be a non-empty string of at most {_PRODUCER_MAX} characters")
    return value


def _integer(entry: EventRead, name: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise EventReadInputError(entry.verb, name, "must be an integer")
    if value < _INT_MIN.get(name, 0):
        raise EventReadInputError(entry.verb, name, f"must be at least {_INT_MIN.get(name, 0)}")
    return value


def _as_of(entry: EventRead, value: Any) -> datetime:
    try:
        return parse_iso8601_utc(value)
    except TimestampError:
        raise EventReadInputError(entry.verb, "as_of", "must be a timezone-aware ISO-8601 timestamp") from None


def _day(entry: EventRead, name: str, value: Any) -> date:
    if not isinstance(value, str) or _DAY.match(value) is None:
        raise EventReadInputError(entry.verb, name, "must be an ISO-8601 date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise EventReadInputError(entry.verb, name, "must be an ISO-8601 date (YYYY-MM-DD)") from None


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def bind_values(entry: EventRead, params: Any) -> dict[str, Any]:
    """Validate the caller's params and return the named bind values (never text spliced into SQL)."""
    if not isinstance(params, dict):
        raise EventReadInputError(entry.verb, "params", "must be an object")
    if set(params) != set(entry.params):
        raise EventReadInputError(entry.verb, "params", f"must be exactly {list(entry.params)}")
    values: dict[str, Any] = {}
    if "session_id" in entry.params:
        session_id = _ulid(entry, "session_id", params["session_id"])
        start = _midnight(decode_time_prefix(session_id).date())
        values.update(session_id=session_id, part_from=start, part_to=start + timedelta(days=1))
    if "producer" in entry.params:
        values["producer"] = _producer(entry, params["producer"])
    if "event_id" in entry.params:
        values["event_id"] = _ulid(entry, "event_id", params["event_id"])
    for name in entry.int_params:
        values[name] = _integer(entry, name, params[name])
    if "as_of" in entry.params:
        values["as_of"] = _as_of(entry, params["as_of"])
    if "day_from" in entry.params:
        first, last = _day(entry, "day_from", params["day_from"]), _day(entry, "day_to", params["day_to"])
        span = (last - first).days + 1
        if span < 1 or span > (entry.max_window_days or 1):
            raise EventReadInputError(entry.verb, "day_to", f"window must span 1 to {entry.max_window_days} days")
        values.update(part_from=_midnight(first), part_to=_midnight(last) + timedelta(days=1))
    if entry.binding == "none":
        values["meta_schema"] = telemetry_pin()[0]
    return values


# ---------------------------------------------------------------------------
# Compared columns, rendering and versioning
# ---------------------------------------------------------------------------


def compared_columns(table: str, semantics: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Every stored column except created_timestamp, producer_version and the row rules' representation-only columns.

    Same set the writer's grain check compares (EventTableSpec.compare_excluded), derived from the same projection.
    """
    semantics = semantics if semantics is not None else rt.load_field_semantics()
    projection = semantics["ops_tables"][table]
    columns = projection["columns"]
    excluded = _STRUCTURAL_EXCLUDED | RowRules.from_projection(columns, projection.get("table_rules")).representation_only
    return tuple(name for name in columns if name not in excluded)


def render_sql(entry: EventRead, semantics: dict[str, Any] | None = None) -> str:
    """Render the verb's template: table names under the telemetry alias, scope, compared columns and registry data."""
    from src.common.ducklake_event_read_verbs import render_data  # noqa: PLC0415

    semantics = semantics if semantics is not None else rt.load_field_semantics()
    alias = rt.TELEMETRY_CATALOG_ALIAS
    projects = rt.resolve_table_spec("ops_projects", semantics).current_table
    sql = entry.sql
    replacements: dict[str, str] = {
        "scope": _SCOPE_SESSION if entry.binding == "session" else _SCOPE_WINDOW,
        "projects": f"{alias}.{projects}",
        "metadata": f"__ducklake_metadata_{alias}",
        **{name: f"{alias}.{table}" for name, table in _PLACEHOLDER_TABLES.items()},
        **{f"cmp_{name}": ", ".join(compared_columns(table, semantics)) for name, table in _PLACEHOLDER_TABLES.items()},
        **render_data(entry.data),
    }
    for key, text in replacements.items():
        sql = sql.replace("{" + key + "}", text)
    leftover = re.findall(r"\{[a-z_]+\}", sql)
    if leftover:
        raise rt.DuckLakeRuntimeError(f"event verb {entry.verb!r} has unbound template placeholder(s) {sorted(set(leftover))}")
    return sql


def event_read_version(verb: str, semantics: dict[str, Any] | None = None) -> str:
    """Opaque stamp: first 16 hex of sha256 over the verb's definition, registry data and compared columns.

    Moves with the SQL, any datum of the verb's data block, and any compared column, so a before/after delta is never read
    across a derivation change.
    """
    entry = _event_reads()[verb]
    semantics = semantics if semantics is not None else rt.load_field_semantics()
    definition = {
        "verb": entry.verb,
        "tables": list(entry.tables),
        "params": list(entry.params),
        "binding": entry.binding,
        "max_window_days": entry.max_window_days,
        "paginable": entry.paginable,
        "sql": " ".join(entry.sql.split()),
        "data": entry.data,
        "compared": {t: list(compared_columns(t, semantics)) for t in _EVENT_TABLES},
    }
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Execution and routing
# ---------------------------------------------------------------------------


def execute(con: Any, *, verb: str, params: Any, limit: Any = None) -> list[dict[str, Any]]:
    """Run one registered event verb: validated, one SQL statement, every value bound."""
    return execute_entry(con, _event_reads()[verb], params, limit)


def execute_entry(con: Any, entry: EventRead, params: Any, limit: Any = None) -> list[dict[str, Any]]:
    values = bind_values(entry, params)
    sql = render_sql(entry)
    content = entry.data.get("response") == "content"
    if limit is not None:
        if not entry.paginable:
            raise rt.DuckLakeRuntimeError(f"read verb {entry.verb!r} is not paginable: `limit` is not accepted")
        sql += f" LIMIT {int(limit)}"
    used = set(_BOUND_NAME.findall(sql))
    cursor = con.execute(sql, {name: value for name, value in values.items() if name in used})
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    if content:
        from src.common.ducklake_event_content import serve_content  # noqa: PLC0415 -- reader bundle only

        return serve_content(rows, values)
    return rows


def serve_named_read(con: Any, *, verb: str, params: dict[str, Any], limit: Any) -> tuple[list[dict[str, Any]], str]:
    """Rows and read_version for a named verb: ops verbs through the unchanged runtime path, event verbs through execute."""
    if is_event_verb(verb):
        return execute(con, verb=verb, params=params, limit=limit), event_read_version(verb)
    return rt.named_read(con, verb=verb, params=params, limit=limit), rt.read_version(verb)


def _telemetry_opener(meta_schema: str, data_path: str, extension_directory: str) -> Callable[[], Any]:
    def opener() -> Any:
        con = rt.open_connection(
            dsn=rt.fetch_dsn(),
            data_path=data_path,
            meta_schema=meta_schema,
            extension_directory=extension_directory,
            alias=rt.TELEMETRY_CATALOG_ALIAS,
        )
        con.execute(f"SET memory_limit='{TELEMETRY_MEMORY_LIMIT}'")
        return con

    return opener


def acquirer_for(
    action: Any, payload: dict[str, Any], ops: Callable[..., tuple[Any, dict[str, Any]]], extension_directory: str
) -> Callable[..., tuple[Any, dict[str, Any]]]:
    """The connection acquirer for this request: the handler's own ops acquirer, unchanged, for everything but an event verb.

    An event verb first passes the smoke-pin refusal and parameter validation, so a refused request never pays an ATTACH,
    then binds the telemetry slot (opened lazily on its first verb).
    """
    verb = payload.get("verb") if action == "named_read" else None
    if not isinstance(verb, str) or verb not in _event_reads():
        return ops
    meta_schema, data_path = require_smoke_pin()
    params = payload.get("params")
    bind_values(_event_reads()[verb], {} if params is None else params)
    opener = _telemetry_opener(meta_schema, data_path, extension_directory)

    def acquire(force_reopen: bool = False) -> tuple[Any, dict[str, Any]]:
        return rt.get_warm_connection(
            opener=opener,
            data_path=data_path,
            meta_schema=meta_schema,
            extension_directory=extension_directory,
            slot=TELEMETRY_SLOT,
            alias=rt.TELEMETRY_CATALOG_ALIAS,
            force_reopen=force_reopen,
        )

    return acquire


def _described_params(entry: EventRead) -> dict[str, Any]:
    from src.common.ducklake_named_reads import _params_schema  # noqa: PLC0415

    schema = _params_schema(entry.params)
    for name in entry.int_params:
        schema["properties"][name] = {"type": "integer"}
    return schema


def describe_all(semantics: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Both registries for the agent-facing `describe`: the ops rows unchanged plus one superset row per event verb."""
    verbs = rt.describe_named_reads() if semantics is None else rt.describe_named_reads(semantics)
    for verb, entry in _event_reads().items():
        verbs[verb] = {
            "table": entry.tables[0],
            "description": entry.description,
            "params": list(entry.params),
            "paginable": entry.paginable,
            "agent_facing": entry.agent_facing,
            "params_schema": _described_params(entry),
            "read_version": event_read_version(verb, semantics),
            "kind": KIND,
            "tables": list(entry.tables),
            "catalog": CATALOG,
            "binding": entry.binding,
            "max_window_days": entry.max_window_days,
        }
    return verbs
