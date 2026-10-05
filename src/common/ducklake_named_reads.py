"""Named-read registry -- the pre-established read verbs the reader Lambda serves (extracted from ducklake_scd2_schema.py).

Moved by the telemetry table-registration plan (Decision 124 facade-plus-siblings, Decision 128
decompose-by-default); ducklake_scd2_schema re-exports every name here. Pure and I/O-free. This module has no
module-scope import of the facade: the one facade use (read_version's column projection for SELECT * verbs)
is a function-local deferred import, and read_version is computed at call time, never at import.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Named-read registry -- the pre-established read verbs the reader Lambda serves (Decision 84 I-3).
# Verb SQL is server-side trusted content: callers name a verb and bind params; no caller SQL
# crosses the boundary on this path. `{tbl}` = current projection, `{hist}` = history table.
# ---------------------------------------------------------------------------

NAMED_READS_VERSION = 3


@dataclass(frozen=True)
class NamedRead:
    """One pre-established read verb: fixed SQL over a fixed table with named bind params."""

    verb: str
    table: str
    sql: str
    params: tuple[str, ...] = ()
    description: str = ""
    paginable: bool = False  # True => the caller-supplied `limit` (named_read) may bound this verb's rows


NAMED_READS: dict[str, NamedRead] = {
    nr.verb: nr
    for nr in (
        NamedRead(
            verb="open_recs",
            table="ops_recommendations",
            sql=("SELECT id, title, context, created_timestamp, automatable FROM {tbl} WHERE status = 'open' ORDER BY id"),
            description="Open recommendations with the fields the preflight tally consumes.",
            paginable=True,
        ),
        NamedRead(
            verb="rec_by_id",
            table="ops_recommendations",
            sql="SELECT * FROM {tbl} WHERE id = ?",
            params=("id",),
            description="Single recommendation by id (portal fetch-before-update).",
        ),
        NamedRead(
            verb="recs_by_title_prefix",
            table="ops_recommendations",
            sql="SELECT id, title, status, source FROM {tbl} WHERE title LIKE ? ORDER BY id",
            params=("title_prefix",),
            description="Recommendations whose title starts with the bound prefix (postmortem supersede sweep).",
            paginable=True,
        ),
        NamedRead(
            verb="ci_rca_open",
            table="ops_recommendations",
            sql=(
                "SELECT id, title, priority, created_timestamp, file FROM {tbl} "
                "WHERE source = 'ci_rca' AND status IN ('open', 'in_progress') "
                "ORDER BY created_timestamp DESC, id LIMIT 5"
            ),
            description="Most recent open/in-progress CI-RCA recommendations (preflight hard-block surface).",
        ),
        NamedRead(
            verb="ci_rca_since",
            table="ops_recommendations",
            sql=("SELECT id FROM {tbl} WHERE source = 'ci_rca' AND created_timestamp > CAST(? AS TIMESTAMPTZ)"),
            params=("since_ts",),
            description="CI-RCA recommendations created after the bound timestamp (liveness alert).",
        ),
        NamedRead(
            verb="forward_fix_recursion",
            table="ops_recommendations",
            sql=(
                "SELECT file, COUNT(*) AS cnt FROM {tbl} "
                "WHERE source = 'ci_rca' AND created_timestamp > CAST(? AS TIMESTAMPTZ) "
                "GROUP BY file HAVING COUNT(*) >= 3"
            ),
            params=("since_ts",),
            description="Files targeted by >=3 CI-RCA recommendations since the bound timestamp.",
        ),
        NamedRead(
            verb="budget_bypass_recent",
            table="ops_recommendations",
            sql=(
                "SELECT id, context, created_timestamp FROM {tbl} "
                "WHERE source = 'budget_bypass' "
                "AND created_timestamp > (current_timestamp - INTERVAL 7 DAY) "
                "ORDER BY created_timestamp DESC, id LIMIT 10"
            ),
            description="budget_bypass recommendations filed in the last 7 days (fast-tier drift alert).",
        ),
        NamedRead(
            verb="rec_history",
            table="ops_recommendations",
            sql="SELECT * FROM {hist} WHERE id = ? ORDER BY last_updated_timestamp DESC, ulid DESC",
            params=("id",),
            description="Prior SCD2 history versions of a rec, newest-first (agent-facing history read).",
        ),
        NamedRead(
            verb="count_by_status",
            table="ops_recommendations",
            sql="SELECT status, COUNT(*) AS n FROM {tbl} GROUP BY status ORDER BY status",
            description="Recommendation count per lifecycle status.",
        ),
        NamedRead(
            verb="decision_by_id",
            table="ops_decisions",
            sql="SELECT * FROM {tbl} WHERE id = ?",
            params=("id",),
            description="Single decision by dec-NNN id (portal fetch-before-update).",
        ),
        NamedRead(
            verb="decisions_max_updated",
            table="ops_decisions",
            sql="SELECT max(last_updated_timestamp) AS ts FROM {tbl}",
            description="Latest decision update timestamp (roadmap freshness input).",
        ),
        NamedRead(
            verb="priority_queue_current",
            table="ops_priority_queue",
            sql=(
                "SELECT * FROM {tbl} WHERE queue_run_id = ("
                "SELECT queue_run_id FROM {tbl} ORDER BY last_updated_timestamp DESC LIMIT 1) "
                "ORDER BY rank"
            ),
            description="All entries of the latest curator run (Decision 70 correlated-subquery pattern).",
        ),
    )
}


def _params_schema(params: tuple[str, ...]) -> dict[str, Any]:
    """A minimal JSON-schema-shaped object over *params* (all bind values are strings at this boundary)."""
    return {
        "type": "object",
        "properties": {p: {"type": "string"} for p in params},
        "required": list(params),
    }


_SELECT_STAR = re.compile(r"\bSELECT\s+\*", re.IGNORECASE)


def read_version(verb: str, semantics: dict[str, Any] | None = None) -> str:
    """Opaque per-verb compatibility stamp: first 16 hex of sha256 over the verb's canonical definition.

    Covers the verb name, bound table, params, paginable flag, whitespace-normalised SQL and, for SELECT *
    verbs, the bound table's resolved column projection (so a column change re-versions them although their
    SQL text is unchanged). Computed at call time, compared by equality only (no ordering is implied); one
    verb's change never re-versions another.
    """
    nr = NAMED_READS[verb]
    sql = " ".join(nr.sql.split())
    definition: dict[str, Any] = {
        "verb": nr.verb,
        "table": nr.table,
        "params": list(nr.params),
        "paginable": nr.paginable,
        "sql": sql,
    }
    if _SELECT_STAR.search(sql):
        from src.common.ducklake_scd2_schema import resolve_table_spec  # noqa: PLC0415 -- deferred; facade imports this module

        definition["columns"] = [list(c) for c in resolve_table_spec(nr.table, semantics).ordered_columns]
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def describe_named_reads(semantics: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per-verb parameter schema for every NAMED_READS entry (agent-facing `describe`, CD.10 / CD.15)."""
    return {
        verb: {
            "table": nr.table,
            "description": nr.description,
            "params": list(nr.params),
            "paginable": nr.paginable,
            "params_schema": _params_schema(nr.params),
            "read_version": read_version(verb, semantics),
        }
        for verb, nr in NAMED_READS.items()
    }
