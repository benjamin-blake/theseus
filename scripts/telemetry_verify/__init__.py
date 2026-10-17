"""Telemetry slice 4 check library: independent re-derivation of the reader verbs, Claude Code ledger reconciliation and
transcript shape counts (PLAN-telemetry-golden-harness). Pure stdlib plus the governed data modules named in each module's
docstring; the facade re-exports the public surface and holds no logic.
"""

from scripts.telemetry_verify.alarms import ALARM_MIN_INTERVAL_S, ALARM_SOURCE, AlarmOutcome, raise_alarms
from scripts.telemetry_verify.dedupe import (
    collapse_events,
    collapse_model_calls,
    compute_generations,
    conflicted_grain_keys,
    normalise_row,
    parse_timestamp,
    resolve_table,
    retire,
)
from scripts.telemetry_verify.derive import (
    ROLLUP_VERBS,
    STATE_VERBS,
    Scope,
    agent_run_state_and_duration,
    agent_run_token_rollup,
    friction_facts,
    model_call_cost_estimate,
    session_friction_rollup,
    session_process_event_rollup,
    session_state_and_duration,
    sessions_window,
)
from scripts.telemetry_verify.joins import JOINS_PATH, load_telemetry_joins
from scripts.telemetry_verify.orphans import orphan_counts
from scripts.telemetry_verify.rows import TreeMovedError, decode_rows, read_tree

__all__ = [
    "ALARM_MIN_INTERVAL_S",
    "ALARM_SOURCE",
    "JOINS_PATH",
    "ROLLUP_VERBS",
    "STATE_VERBS",
    "AlarmOutcome",
    "Scope",
    "TreeMovedError",
    "agent_run_state_and_duration",
    "agent_run_token_rollup",
    "collapse_events",
    "collapse_model_calls",
    "compute_generations",
    "conflicted_grain_keys",
    "decode_rows",
    "friction_facts",
    "load_telemetry_joins",
    "model_call_cost_estimate",
    "normalise_row",
    "orphan_counts",
    "parse_timestamp",
    "raise_alarms",
    "read_tree",
    "resolve_table",
    "retire",
    "session_friction_rollup",
    "session_process_event_rollup",
    "session_state_and_duration",
    "sessions_window",
]
