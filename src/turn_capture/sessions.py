"""Pure builders for telemetry_sessions and telemetry_agents rows (root and every sub-agent session).

Session rows are the generation marker (Decision 207 R3): the open row is emitted once a closed turn holding an
assistant record exists, or at finalize; resume and compact rows wait for their stream's open row. Every agents
column comes from TRANSCRIPT RECORDS only; a sub-agent's meta.json is never read for row content.
"""

from __future__ import annotations

import re
from typing import Any

from src.turn_capture.refs import role_ref, session_marker_ref
from src.turn_capture.scrub import scrub_text
from src.turn_capture.streams import ParsedTree, Rec, Spawn, Stream, emitting_streams
from src.turn_capture.transcripts import Ctx, text_of

AGENT_TYPE = "claude-code-subagent"
WORKFLOWS = ("orient", "plan", "implement", "develop-executor", "audit", "overseer")
SESSION_COLUMNS = (
    "event_kind",
    "event_timestamp",
    "session_started_at",
    "source_ordinal",
    "external_ref",
    "entity_ref",
    "parent_session_ref",
    "producer",
    "producer_version",
    "parser_version",
    "workflow",
    "outcome",
    "execution_attempt",
    "branch",
    "rec_ids",
    "plan_slug",
    "failure_reason",
    "failure_phase",
    "files_changed",
    "lines_added",
    "lines_removed",
    "steps_total",
    "scope_drift_files",
    "pr_url",
    "ci_outcome",
    "model_primary",
    "coverage_before",
    "coverage_after",
)
AGENT_COLUMNS = (
    "event_kind",
    "event_timestamp",
    "session_started_at",
    "source_ordinal",
    "external_ref",
    "entity_ref",
    "session_ref",
    "observation_ref",
    "producer",
    "producer_version",
    "parser_version",
    "agent_type",
    "agent_name",
    "model",
    "provider",
    "version",
    "trigger",
    "outcome",
    "findings_count",
    "recs_created",
    "queue_entries_written",
    "error",
    "lambda_request_id",
    "workflow_run_id",
)
_COMMAND_NAME = re.compile(r"<command-name>/?([A-Za-z][A-Za-z0-9_-]*)</command-name>")


def _first_model(stream: Stream) -> str | None:
    for rec in stream.recs:
        if rec.kind == "assistant":
            model = rec.data["message"].get("model")
            return model if isinstance(model, str) else None
    return None


def _workflow(stream: Stream) -> str:
    first = next((r for r in stream.recs if r.kind == "prompt"), None)
    match = _COMMAND_NAME.search(text_of(first.data["message"]["content"])) if first is not None else None
    name = match.group(1).lower() if match else ""
    return name if name in WORKFLOWS else "claude_code"


def _open_bound(stream: Stream, final: bool) -> tuple[bool, int | None]:
    """(open row is due, last record line the branch may be read from -- None means every record)."""
    for turn in stream.turns:
        if turn.closed and turn.last_assistant is not None:
            return True, max(r.line for r in turn.recs)
    return final, None


def _branch(stream: Stream, bound: int | None) -> str | None:
    for rec in stream.recs:
        branch = rec.data.get("gitBranch")
        if (bound is None or rec.line <= bound) and isinstance(branch, str) and branch:
            return branch
    return None


def _row(
    ctx: Ctx, rec: Rec | None, stream: Stream, ext: str, kind: str, when: Any, ordinal: int, parent: str | None, **cols: Any
) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(SESSION_COLUMNS)
    row.update(
        event_kind=kind,
        event_timestamp=when,
        session_started_at=ctx.started,
        source_ordinal=ordinal,
        external_ref=ext,
        entity_ref=stream.session_ref,
        parent_session_ref=parent,
        producer=ctx.producer,
        producer_version=ctx.producer_version,
        parser_version=ctx.parser_version,
    )
    row.update(cols)
    return {k: v for k, v in row.items() if v is not None}


def build_sessions(parsed: ParsedTree, ctx: Ctx) -> list[dict[str, Any]]:
    parents = {sp.agent_id: parsed.streams[sp.parent].session_ref for sp in parsed.spawns}
    rows: list[dict[str, Any]] = []
    for stream in emitting_streams(parsed):
        due, bound = _open_bound(stream, parsed.final)
        if not due:
            continue
        pin = next((r for r in stream.recs if r.ts is not None), None)
        child = stream.key in parents
        rows.append(
            _row(
                ctx,
                None,
                stream,
                session_marker_ref(stream.session_ref),
                "open",
                ctx.started,
                0 if child or pin is None else pin.line,
                parents.get(stream.key),
                workflow="subagent" if child else _workflow(stream),
                execution_attempt=1,
                branch=_branch(stream, bound),
                model_primary=_first_model(stream),
            )
        )
        for n, rec in enumerate(stream.resumes):
            rows.append(
                _row(
                    ctx,
                    rec,
                    stream,
                    role_ref(rec.uuid, 0, "resume"),
                    "resume",
                    rec.ts,
                    rec.line,
                    parents.get(stream.key),
                    execution_attempt=n + 2,
                )
            )
        for rec in stream.compacts:
            rows.append(
                _row(ctx, rec, stream, role_ref(rec.uuid, 0, "compact"), "compact", rec.ts, rec.line, parents.get(stream.key))
            )
    return rows


def _agent_row(ctx: Ctx, spawn: Spawn, child: Stream, ext: str, kind: str, rec: Rec, **cols: Any) -> dict[str, Any]:
    use = spawn.tool_use
    spec = use.block_body.get("input")
    spec = spec if isinstance(spec, dict) else {}
    name = spec.get("subagent_type")
    version = use.rec.data.get("version")
    row: dict[str, Any] = dict.fromkeys(AGENT_COLUMNS)
    row.update(
        event_kind=kind,
        event_timestamp=rec.ts,
        session_started_at=ctx.started,
        source_ordinal=rec.line,
        external_ref=ext,
        entity_ref=use.tool_id,
        session_ref=child.session_ref,
        observation_ref=use.tool_id,
        producer=ctx.producer,
        producer_version=ctx.producer_version,
        parser_version=ctx.parser_version,
        agent_type=AGENT_TYPE,
        agent_name=name if isinstance(name, str) else None,
        model=_first_model(child),
        version=version if isinstance(version, str) else None,
        trigger="subagent_background" if spec.get("run_in_background") is True else "subagent_sync",
    )
    row.update(cols)
    return {k: v for k, v in row.items() if v is not None}


def build_agents(parsed: ParsedTree, ctx: Ctx) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spawn in parsed.spawns:
        child = parsed.streams.get(spawn.agent_id)
        if child is None or not (spawn.complete or parsed.final):
            continue
        use = spawn.tool_use
        rows.append(_agent_row(ctx, spawn, child, role_ref(use.rec.uuid, use.block, "agent_open"), "open", use.rec))
        if spawn.close_rec is None:
            continue
        res = spawn.close_result
        info = res.use_result if res is not None else None
        failed = res is not None and (
            res.body.get("is_error") is True or (isinstance(info, dict) and info.get("interrupted") is True)
        )
        error = None
        if res is not None and res.body.get("is_error") is True:
            error = scrub_text(text_of(res.body.get("content"))[:2000]).text
        ext = role_ref(spawn.close_rec.uuid, spawn.close_block, "agent_close")
        rows.append(
            _agent_row(
                ctx, spawn, child, ext, "close", spawn.close_rec, outcome="failed" if failed else "success", error=error
            )
        )
    return rows
