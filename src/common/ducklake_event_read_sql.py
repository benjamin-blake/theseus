"""SQL templates for the telemetry event-journal reads (Decision 199, 207).

Strings only: nothing here runs SQL, reads a file or can raise at import. Placeholders ({scope}, {sessions}, {cmp_sessions},
{idle_seconds}, {rules}, ...) are SQL text rendered server-side by src.common.ducklake_event_reads; every caller value reaches
the statement as a bound named parameter ($session_id, $as_of, $part_from, $part_to, $meta_schema), never as text.

One rule, one copy: the R4/R5 dedupe, the conflict report and the session/agent-run state rule are each written once here and
shared by every verb that needs them (a named verb is a serving leaf and never calls another verb).
"""

from __future__ import annotations

SESSIONS = "telemetry_sessions"
OBSERVATIONS = "telemetry_observations"
TRANSCRIPTS = "telemetry_transcripts"
AGENTS = "telemetry_agents"

_KEY = {SESSIONS: "s", OBSERVATIONS: "o", AGENTS: "a", TRANSCRIPTS: "t"}
_PLACEHOLDER = {SESSIONS: "sessions", OBSERVATIONS: "observations", AGENTS: "agents", TRANSCRIPTS: "transcripts"}

# R4: V*(producer, session) is the highest parser_version of that producer's open rows for the session, inside the scope.
GENERATIONS_CTE = (
    "gen AS (SELECT producer, session_id, max(parser_version) AS v_star FROM {sessions} "
    "WHERE {scope} AND event_kind = 'open' GROUP BY producer, session_id)"
)

# R5c: one model_call per observation_id -- producer precedence, then the latest event_timestamp (final usage wins), then a
# total order. Only model_call rows collapse; a tool_call open and close legitimately share an observation_id.
_MODEL_CALL_COLLAPSE = (
    "o AS (SELECT * FROM o_ev QUALIFY observation_type <> 'model_call' OR observation_id IS NULL OR row_number() OVER ("
    "PARTITION BY observation_id ORDER BY CASE producer WHEN 'claude_code' THEN 0 WHEN 'litellm' THEN 1 ELSE 2 END, "
    "event_timestamp DESC, created_timestamp, producer, event_id) = 1)"
)


def dedupe_ctes(table: str) -> str:
    """R5a (retire rows below or above V*) then R5b (event collapse per producer and event_id) for one telemetry table."""
    k = _KEY[table]
    live = (
        f"{k}_live AS (SELECT x.* FROM {{{_PLACEHOLDER[table]}}} x LEFT JOIN gen USING (producer, session_id) "
        "WHERE {scope} AND (gen.v_star IS NULL OR x.parser_version = gen.v_star))"
    )
    collapse = (
        f"SELECT * FROM {k}_live QUALIFY row_number() OVER (PARTITION BY producer, event_id "
        "ORDER BY parser_version DESC, created_timestamp) = 1"
    )
    if table == OBSERVATIONS:
        return f"{live}, o_ev AS ({collapse}), {_MODEL_CALL_COLLAPSE}"
    return f"{live}, {k} AS ({collapse})"


def conflict_select(table: str) -> str:
    """Grain keys holding more than one distinct row, over the scope's rows BEFORE retirement (Decision 207 R5b).

    The compare is one row value over every compared column, never a per-column DISTINCT (which would ignore NULLs and hide a
    NULL-versus-value conflict).
    """
    return (
        f"SELECT '{table}' AS table_name, producer, event_id, parser_version, min(session_id) AS session_id "
        f"FROM {{{_PLACEHOLDER[table]}}} WHERE {{scope}} GROUP BY producer, event_id, parser_version "
        f"HAVING count(DISTINCT row({{cmp_{_PLACEHOLDER[table]}}})) > 1"
    )


def compose(tables: tuple[str, ...], body: str) -> str:
    """WITH gen, each table's deduped CTEs, the conflict report and the per-session stamps, then *body*."""
    parts = [GENERATIONS_CTE, *(dedupe_ctes(t) for t in tables)]
    parts.append("conflicts AS (" + " UNION ALL ".join(conflict_select(t) for t in tables) + ")")
    parts.append(
        "gens AS (SELECT session_id, list(struct_pack(producer := producer, parser_version := v_star) ORDER BY producer) "
        "AS generations FROM gen GROUP BY session_id)"
    )
    parts.append(
        "conf AS (SELECT session_id, list(struct_pack(table_name := table_name, producer := producer, event_id := event_id, "
        "parser_version := parser_version) ORDER BY table_name, producer, event_id, parser_version) "
        "AS conflicted_grain_keys FROM conflicts GROUP BY session_id)"
    )
    return "WITH " + ", ".join(parts) + (" " if body.startswith("SELECT") else ", ") + body


STAMPS_SELECT = (
    "coalesce(gens.generations, []) AS generations, coalesce(conf.conflicted_grain_keys, []) AS conflicted_grain_keys, "
    "conf.session_id IS NOT NULL AS derivation_conflicted"
)
STAMPS_JOIN = "LEFT JOIN gens ON gens.session_id = {sid} LEFT JOIN conf ON conf.session_id = {sid}"

_IDLE = "epoch(CAST($as_of AS TIMESTAMPTZ)) - epoch(l.last_event_timestamp) > {idle_seconds}"

# Session and agent-run state, written once (telemetry_sessions.yaml state / duration_seconds; telemetry_agents.yaml duration).
# ROOT: the latest lifecycle row (annotate excluded) by event_timestamp, source_ordinal (NULL first), close last on a tie, then
# event_id; running unless it is a close, abandoned when not terminal and idle past the threshold.
# SUB-AGENT: its agent-run pair.
STATE_CTES = (
    "sess AS (SELECT session_id, max(parent_session_id) AS parent_session_id, max(project_id) AS project_id, "
    "min(session_started_at) AS session_started_at FROM s GROUP BY session_id), "
    "lc AS (SELECT session_id, event_kind, outcome FROM s WHERE event_kind <> 'annotate' "
    "QUALIFY row_number() OVER (PARTITION BY session_id ORDER BY event_timestamp DESC, coalesce(source_ordinal, -1) DESC, "
    "(event_kind = 'close') DESC, event_id DESC) = 1), "
    "cl AS (SELECT session_id, event_timestamp FROM s WHERE event_kind = 'close' "
    "QUALIFY row_number() OVER (PARTITION BY session_id ORDER BY event_timestamp DESC, coalesce(source_ordinal, -1) DESC, "
    "event_id DESC) = 1), "
    "last_ev AS (SELECT session_id, max(event_timestamp) AS last_event_timestamp FROM ("
    "SELECT session_id, event_timestamp FROM s UNION ALL SELECT session_id, event_timestamp FROM a "
    "UNION ALL SELECT session_id, event_timestamp FROM o UNION ALL SELECT session_id, event_timestamp FROM t) "
    "GROUP BY session_id), "
    "runs AS (SELECT session_id, agent_run_id, any_value(agent_type) AS agent_type, "
    "min(event_timestamp) FILTER (WHERE event_kind = 'open') AS opened_at, "
    "max(event_timestamp) FILTER (WHERE event_kind = 'close') AS closed_at, "
    "arg_max(outcome, event_timestamp) FILTER (WHERE event_kind = 'close') AS run_outcome FROM a "
    "GROUP BY session_id, agent_run_id), "
    "run_state AS (SELECT r.session_id, r.agent_run_id, r.agent_type, r.opened_at, r.closed_at, r.run_outcome, "
    "CASE WHEN r.closed_at IS NOT NULL THEN CASE r.run_outcome WHEN 'success' THEN 'success' WHEN 'failed' THEN 'failed' "
    "WHEN 'timeout' THEN 'failed' WHEN 'throttled' THEN 'failed' END "
    f"WHEN {_IDLE} THEN 'abandoned' ELSE 'running' END AS state, "
    "CASE WHEN r.closed_at IS NOT NULL AND r.opened_at IS NOT NULL "
    "THEN CAST(trunc(epoch(r.closed_at) - epoch(r.opened_at)) AS BIGINT) END AS duration_seconds, "
    "l.last_event_timestamp AS last_event_timestamp "
    "FROM runs r LEFT JOIN last_ev l ON l.session_id = r.session_id), "
    "child AS (SELECT * FROM run_state QUALIFY row_number() OVER (PARTITION BY session_id "
    "ORDER BY opened_at DESC NULLS LAST, agent_run_id DESC) = 1)"
)

_STATE_SELECT = (
    "SELECT sess.session_id AS session_id, sess.parent_session_id AS parent_session_id, sess.project_id AS project_id, "
    "sess.session_started_at AS session_started_at, "
    "CASE WHEN sess.parent_session_id IS NULL THEN CASE WHEN lc.event_kind = 'close' THEN lc.outcome "
    f"WHEN {_IDLE} THEN 'abandoned' ELSE 'running' END "
    f"WHEN child.session_id IS NULL THEN CASE WHEN {_IDLE} THEN 'abandoned' ELSE 'running' END "
    "ELSE child.state END AS state, "
    "CASE WHEN sess.parent_session_id IS NULL THEN CASE WHEN lc.event_kind = 'close' THEN lc.outcome END "
    "ELSE child.run_outcome END AS outcome, "
    "CASE WHEN sess.parent_session_id IS NULL THEN CASE WHEN cl.event_timestamp IS NOT NULL "
    "THEN CAST(trunc(epoch(cl.event_timestamp) - epoch(sess.session_started_at)) AS BIGINT) END "
    "ELSE child.duration_seconds END AS duration_seconds, "
    "l.last_event_timestamp AS last_event_timestamp, CAST($as_of AS TIMESTAMPTZ) AS as_of, "
    "CAST({idle_seconds} AS BIGINT) AS idle_threshold_seconds, "
    f"{STAMPS_SELECT} "
    "FROM sess LEFT JOIN lc ON lc.session_id = sess.session_id LEFT JOIN cl ON cl.session_id = sess.session_id "
    "LEFT JOIN last_ev l ON l.session_id = sess.session_id LEFT JOIN child ON child.session_id = sess.session_id "
    + STAMPS_JOIN.format(sid="sess.session_id")
)

_ALL_TABLES = (SESSIONS, OBSERVATIONS, AGENTS, TRANSCRIPTS)
_ORDER_WINDOW = " ORDER BY sess.session_started_at, sess.session_id"

SESSION_STATE_SQL = compose(_ALL_TABLES, STATE_CTES + " " + _STATE_SELECT + _ORDER_WINDOW)

# A window answers root sessions only; the real-purpose variant excludes drill and synthetic projects structurally (a join on
# the shared project purpose marker), not through an opt-in parameter.
SESSIONS_WINDOW_ALL_SQL = compose(
    _ALL_TABLES, STATE_CTES + " " + _STATE_SELECT + " WHERE sess.parent_session_id IS NULL" + _ORDER_WINDOW
)
SESSIONS_WINDOW_SQL = compose(
    _ALL_TABLES,
    STATE_CTES
    + " "
    + _STATE_SELECT
    + " WHERE sess.parent_session_id IS NULL AND sess.project_id IN (SELECT project_id FROM {projects} WHERE purpose = 'real')"
    + _ORDER_WINDOW,
)

AGENT_RUN_STATE_SQL = compose(
    _ALL_TABLES,
    STATE_CTES + " SELECT rs.agent_run_id AS agent_run_id, rs.session_id AS session_id, rs.agent_type AS agent_type, "
    "rs.state AS state, rs.run_outcome AS outcome, rs.duration_seconds AS duration_seconds, "
    "rs.last_event_timestamp AS last_event_timestamp, CAST($as_of AS TIMESTAMPTZ) AS as_of, "
    "CAST({idle_seconds} AS BIGINT) AS idle_threshold_seconds, "
    + STAMPS_SELECT
    + " FROM run_state rs "
    + STAMPS_JOIN.format(sid="rs.session_id")
    + " ORDER BY rs.opened_at, rs.agent_run_id",
)

_IDS = "ids AS (SELECT session_id FROM s UNION SELECT session_id FROM o)"
_ROLLUP_TAIL = " FROM ids LEFT JOIN cnt ON cnt.session_id = ids.session_id " + STAMPS_JOIN.format(sid="ids.session_id")

PROCESS_EVENT_ROLLUP_SQL = compose(
    (SESSIONS, OBSERVATIONS),
    _IDS + ", cnt AS (SELECT session_id, count(*) FILTER (WHERE observation_type = 'process_event') AS process_event_total, "
    "count(*) FILTER (WHERE observation_type = 'step' AND event_kind = 'close') AS steps_completed_total "
    "FROM o GROUP BY session_id) SELECT ids.session_id AS session_id, "
    "coalesce(cnt.process_event_total, 0) AS process_event_total, "
    "coalesce(cnt.steps_completed_total, 0) AS steps_completed_total, "
    + STAMPS_SELECT
    + _ROLLUP_TAIL
    + " ORDER BY ids.session_id",
)

# Token totals are NULL (not 0) when no model_call carries usage; usage_missing_count says how many calls had none.
AGENT_RUN_TOKEN_ROLLUP_SQL = compose(
    (SESSIONS, OBSERVATIONS),
    _IDS + ", cnt AS (SELECT session_id, sum(tokens_input) AS tokens_input_total, sum(tokens_output) AS tokens_output_total, "
    "count(*) AS model_call_count, "
    "count(*) FILTER (WHERE tokens_input IS NULL OR tokens_output IS NULL) AS usage_missing_count "
    "FROM o WHERE observation_type = 'model_call' GROUP BY session_id) SELECT ids.session_id AS session_id, "
    "cnt.tokens_input_total AS tokens_input_total, cnt.tokens_output_total AS tokens_output_total, "
    "coalesce(cnt.model_call_count, 0) AS model_call_count, coalesce(cnt.usage_missing_count, 0) AS usage_missing_count, "
    + STAMPS_SELECT
    + _ROLLUP_TAIL
    + " ORDER BY ids.session_id",
)

# Reported cost only (rec-4291 / rec-4031): an allowance-billed call is NULL by contract (Decision 206), a call with no
# reported cost is unpriced, never 0. The price table is rec-4031's and lands behind this same verb signature.
MODEL_CALL_COST_SQL = compose(
    (SESSIONS, OBSERVATIONS),
    "SELECT o.session_id AS session_id, o.observation_id AS observation_id, o.event_timestamp AS event_timestamp, "
    "o.model AS model, o.provider AS provider, o.billing_shape AS billing_shape, o.tokens_input AS tokens_input, "
    "o.tokens_output AS tokens_output, "
    "CASE WHEN o.billing_shape = 'fixed_non_rollover_allowance' THEN NULL ELSE o.cost_usd_reported END AS cost_usd, "
    "CASE WHEN o.billing_shape = 'fixed_non_rollover_allowance' THEN 'allowance' "
    "WHEN o.cost_usd_reported IS NOT NULL THEN 'reported' ELSE 'unpriced' END AS cost_source, "
    + STAMPS_SELECT
    + " FROM o "
    + STAMPS_JOIN.format(sid="o.session_id")
    + " WHERE o.observation_type = 'model_call' ORDER BY o.event_timestamp, o.observation_id",
)

# Friction (REPORT-w1-friction-classifier.md section 2): facts are process_events at severity error/warning/critical and
# tool_call closes with outcome error/blocked; one label per fact (an exact signature beats the generic rule); a blocked
# tool_call whose own hook block is already a fact is not counted twice; rework is the repeat-run rule.
FRICTION_CTES = (
    "f AS (SELECT * FROM o WHERE (observation_type = 'process_event' AND severity IN ('error', 'warning', 'critical')) "
    "OR (observation_type = 'tool_call' AND event_kind = 'close' AND outcome IN ('error', 'blocked'))), "
    "rules AS (SELECT * FROM {rules}), "
    "labelled AS (SELECT f.session_id AS session_id, f.observation_id AS ref, r.label AS label, r.class AS class, "
    "row_number() OVER (PARTITION BY f.observation_id ORDER BY r.signature IS NULL, r.rule_id) AS rk "
    "FROM f JOIN rules r ON r.observation_type = f.observation_type AND r.disposition = coalesce(f.severity, f.outcome) "
    "AND (r.signature IS NULL OR r.signature = f.name) "
    "WHERE NOT (f.observation_type = 'tool_call' AND f.outcome = 'blocked' AND EXISTS ("
    "SELECT 1 FROM f h WHERE h.observation_type = 'process_event' AND h.severity = 'error' "
    "AND h.parent_observation_id = f.observation_id))), "
    "seq0 AS (SELECT session_id, observation_id, parent_observation_id, name, outcome, "
    "row_number() OVER (PARTITION BY parent_observation_id, name ORDER BY event_timestamp, source_ordinal) AS pos, "
    "row_number() OVER (PARTITION BY parent_observation_id, name, outcome ORDER BY event_timestamp, source_ordinal) AS pos_o "
    "FROM o WHERE observation_type = 'tool_call' AND event_kind = 'close'), "
    "seq AS (SELECT *, pos - pos_o AS run FROM seq0), "
    "friction AS (SELECT session_id, ref, label, class FROM labelled WHERE rk = 1 UNION ALL "
    "SELECT min(session_id), min_by(observation_id, pos), '{run_label}', '{run_class}' FROM seq WHERE outcome = 'error' "
    "GROUP BY parent_observation_id, name, run HAVING count(*) >= {repeat_threshold})"
)

# Facts only (ref, label, class): the test seam for the 17 committed friction vectors, sharing FRICTION_CTES with the verb.
FRICTION_FACTS_SQL = compose((SESSIONS, OBSERVATIONS), FRICTION_CTES + " SELECT ref, label, class FROM friction")

FRICTION_ROLLUP_SQL = compose(
    (SESSIONS, OBSERVATIONS),
    FRICTION_CTES + ", ids AS (SELECT session_id FROM s UNION SELECT session_id FROM o), "
    "by_label AS (SELECT session_id, label, count(*) AS n FROM friction GROUP BY session_id, label), "
    "cnt AS (SELECT session_id, count(*) FILTER (WHERE class = 'rework') AS rework_total, "
    "count(*) FILTER (WHERE class = 'exception') AS exception_total, "
    "count(*) FILTER (WHERE label = 'unmapped_block') AS unmapped_count FROM friction GROUP BY session_id), "
    "labels AS (SELECT session_id, list(struct_pack(label := label, n := n) ORDER BY label) AS label_counts "
    "FROM by_label GROUP BY session_id) "
    "SELECT ids.session_id AS session_id, coalesce(cnt.rework_total, 0) AS rework_total, "
    "coalesce(cnt.exception_total, 0) AS exception_total, coalesce(labels.label_counts, []) AS label_counts, "
    "coalesce(cnt.unmapped_count, 0) AS unmapped_count, CAST({classifier_version} AS BIGINT) AS classifier_version, "
    + STAMPS_SELECT
    + _ROLLUP_TAIL.replace("LEFT JOIN gens", "LEFT JOIN labels ON labels.session_id = ids.session_id LEFT JOIN gens", 1)
    + " ORDER BY ids.session_id",
)

# Catalog metadata only (no data file): per-table committed record counts and the pinned meta schema as a bound value.
TELEMETRY_HEALTH_SQL = (
    "SELECT t.table_name AS table_name, coalesce(st.record_count, 0) AS record_count, "
    "CAST($meta_schema AS VARCHAR) AS meta_schema FROM {metadata}.ducklake_table t "
    "LEFT JOIN {metadata}.ducklake_table_stats st ON st.table_id = t.table_id "
    "WHERE t.end_snapshot IS NULL AND t.table_name IN ('telemetry_sessions', 'telemetry_observations', "
    "'telemetry_transcripts', 'telemetry_agents') ORDER BY t.table_name"
)
