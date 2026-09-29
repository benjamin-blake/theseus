"""Pure builders for telemetry_observations rows (refs only, never ids).

Turn open/close, model_call (one per response, owned by its last record), tool_call open/close (a tool_use
with no in-span result gets ONE synthetic interrupted close anchored on the tool_use record itself) and one
process_event per hook attachment. Tool errors are the tool_call close outcome, never process_events.
Rows of a turn are built only once the turn is closed; a row outside any turn is built at once.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter
from typing import Any

from src.turn_capture.refs import model_call_ref, role_ref, turn_entity_ref
from src.turn_capture.scrub import scrub_text
from src.turn_capture.streams import (
    HARNESS_DENIAL_PREFIXES,
    HARNESS_INTERRUPT_SENTINELS,
    ParsedTree,
    Rec,
    Result,
    Stream,
    ToolUse,
    Turn,
    block_base,
    emitting_streams,
)
from src.turn_capture.transcripts import Ctx, canonical_json, text_of

OBSERVATION_COLUMNS = (
    "event_kind",
    "event_timestamp",
    "session_started_at",
    "source_ordinal",
    "external_ref",
    "entity_ref",
    "session_ref",
    "parent_observation_ref",
    "producer",
    "producer_version",
    "parser_version",
    "observation_type",
    "name",
    "sequence",
    "outcome",
    "severity",
    "model",
    "tokens_input",
    "tokens_output",
    "tokens_cache_read",
    "tokens_cache_creation",
    "cost_usd_reported",
    "attempt",
    "provider",
    "persona_backend",
    "billing_shape",
    "acceptance_passed",
    "exit_code",
    "time_lost_seconds",
    "rec_id",
    "metadata",
)
_SCRIPT = re.compile(r"[^\s]+\.(py|sh)$")
_USAGE_KEYS = (
    ("tokens_input", "input_tokens"),
    ("tokens_output", "output_tokens"),
    ("tokens_cache_read", "cache_read_input_tokens"),
    ("tokens_cache_creation", "cache_creation_input_tokens"),
)


def _row(
    ctx: Ctx, stream: Stream, rec: Rec, ext: str, ent: str, otype: str, kind: str, parent: str | None, **cols: Any
) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(OBSERVATION_COLUMNS)
    row.update(
        event_kind=kind,
        event_timestamp=rec.ts,
        session_started_at=ctx.started,
        source_ordinal=rec.line,
        external_ref=ext,
        entity_ref=ent,
        session_ref=stream.session_ref,
        parent_observation_ref=parent,
        producer=ctx.producer,
        producer_version=ctx.producer_version,
        parser_version=ctx.parser_version,
        observation_type=otype,
    )
    row.update(cols)
    return {k: v for k, v in row.items() if v is not None}


def _meta(**fields: Any) -> str:
    return canonical_json(fields)


def _int_or_zero(value: Any, diag: Counter[str]) -> int:
    if type(value) is int:
        return value
    if value is not None:
        diag["non_int_usage"] += 1
    return 0


def _model(rec: Rec) -> str | None:
    model = rec.data["message"].get("model")
    return model if isinstance(model, str) else None


def outcome_of(res: Result, stream: Stream) -> str:
    """blocked, then interrupted, then error, else success."""
    is_error = res.body.get("is_error") is True
    text = text_of(res.body.get("content"))
    hook_block = any(line < res.rec.line for line in stream.pre_tool_blocks.get(res.tool_use_id, []))
    if (is_error and text.startswith(HARNESS_DENIAL_PREFIXES)) or hook_block:
        return "blocked"
    info = res.use_result
    if (isinstance(info, dict) and info.get("interrupted") is True) or (is_error and text in HARNESS_INTERRUPT_SENTINELS):
        return "interrupted"
    return "error" if is_error else "success"


def _result_meta(res: Result) -> str:
    info = res.use_result if isinstance(res.use_result, dict) else {}
    path = info.get("persistedOutputPath")
    return _meta(
        is_error=res.body.get("is_error") is True,
        interrupted=info.get("interrupted") if isinstance(info.get("interrupted"), bool) else None,
        persisted_output=posixpath.basename(path.replace("\\", "/")) if isinstance(path, str) else None,
        persisted_output_size=info.get("persistedOutputSize") if type(info.get("persistedOutputSize")) is int else None,
        agent_id=info.get("agentId") if isinstance(info.get("agentId"), str) else None,
        is_async=info.get("isAsync") if isinstance(info.get("isAsync"), bool) else None,
        status=info.get("status") if isinstance(info.get("status"), str) else None,
    )


def _tool_rows(ctx: Ctx, stream: Stream, turn: Turn, tref: str, use: ToolUse) -> list[dict[str, Any]]:
    rec, block = use.rec, use.block_body
    caller = block.get("caller")
    tid = use.tool_id
    rows = [
        _row(
            ctx,
            stream,
            rec,
            role_ref(rec.uuid, use.block, "tool_call_open"),
            tid,
            "tool_call",
            "open",
            tref,
            name=block.get("name") if isinstance(block.get("name"), str) else None,
            sequence=use.ordinal,
            model=_model(rec),
            metadata=_meta(
                caller_type=caller.get("type") if isinstance(caller, dict) and isinstance(caller.get("type"), str) else None,
                attribution_mcp_server=rec.data.get("attributionMcpServer")
                if isinstance(rec.data.get("attributionMcpServer"), str)
                else None,
            ),
        )
    ]
    name = block.get("name") if isinstance(block.get("name"), str) else None
    if use.result is not None:
        res = use.result
        rows.append(
            _row(
                ctx,
                stream,
                res.rec,
                role_ref(res.rec.uuid, res.block, "tool_call_close"),
                tid,
                "tool_call",
                "close",
                tref,
                name=name,
                sequence=use.ordinal,
                outcome=outcome_of(res, stream),
                metadata=_result_meta(res),
            )
        )
    else:
        rows.append(
            _row(
                ctx,
                stream,
                rec,
                role_ref(rec.uuid, use.block, "tool_call_close"),
                tid,
                "tool_call",
                "close",
                tref,
                name=name,
                sequence=use.ordinal,
                outcome="interrupted",
                metadata=_meta(synthetic=True),
            )
        )
    return rows


def _turn_rows(ctx: Ctx, stream: Stream, turn: Turn, diag: Counter[str]) -> list[dict[str, Any]]:
    tref = turn_entity_ref(stream.session_ref, turn.prompt_id)
    first = turn.first
    rows = [
        _row(
            ctx,
            stream,
            first,
            role_ref(first.uuid, 0, "turn_open"),
            tref,
            "turn",
            "open",
            None,
            sequence=turn.ordinal,
            metadata=_meta(
                is_meta=first.data.get("isMeta") is True,
                prompt_source=first.data.get("promptSource") if isinstance(first.data.get("promptSource"), str) else None,
                turn_origin=first.data.get("turnOrigin") if isinstance(first.data.get("turnOrigin"), str) else None,
            ),
        )
    ]
    last = turn.last_assistant
    if last is not None:
        rows.append(
            _row(
                ctx,
                stream,
                last,
                role_ref(last.uuid, block_base(last.data), "turn_close"),
                tref,
                "turn",
                "close",
                None,
                sequence=turn.ordinal,
                metadata=_meta(response_count=len(turn.responses), tool_call_count=len(turn.tool_uses)),
            )
        )
    for resp in turn.responses:
        owner, message = resp.owner, resp.owner.data["message"]
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        details = usage.get("output_tokens_details")
        thinking = (
            details.get("thinking_tokens")
            if isinstance(details, dict) and type(details.get("thinking_tokens")) is int
            else None
        )
        tokens = {col: _int_or_zero(usage.get(key), diag) for col, key in _USAGE_KEYS}
        rows.append(
            _row(
                ctx,
                stream,
                owner,
                model_call_ref(resp.message_id),
                resp.message_id,
                "model_call",
                "point",
                tref,
                name="agent_turn",
                model=_model(owner),
                billing_shape=ctx.billing_shape,
                **tokens,
                metadata=_meta(
                    request_id=owner.data.get("requestId") if isinstance(owner.data.get("requestId"), str) else None,
                    stop_reason=message.get("stop_reason") if isinstance(message.get("stop_reason"), str) else None,
                    block_count=sum(len(r.data["message"]["content"]) for r in resp.recs),
                    thinking_tokens=thinking,
                ),
            )
        )
    for use in turn.tool_uses:
        rows += _tool_rows(ctx, stream, turn, tref, use)
    for res in turn.orphan_results:
        rows.append(
            _row(
                ctx,
                stream,
                res.rec,
                role_ref(res.rec.uuid, res.block, "tool_call_close"),
                res.tool_use_id,
                "tool_call",
                "close",
                tref,
                outcome=outcome_of(res, stream),
                metadata=_result_meta(res),
            )
        )
    return rows


def hook_name(att: dict[str, Any]) -> str:
    command = att.get("command")
    for token in command.split() if isinstance(command, str) else []:
        if _SCRIPT.match(token):
            return "hook:" + posixpath.splitext(posixpath.basename(token))[0]
    hook = att.get("hookName")
    return "hook:" + (hook.replace(":", ".") if isinstance(hook, str) and hook else "unknown")


def _hook_row(ctx: Ctx, stream: Stream, rec: Rec) -> dict[str, Any]:
    att = rec.data["attachment"]
    ext = role_ref(rec.uuid, 0, "process_event")
    code = att.get("exitCode")
    use_id = att.get("toolUseID") if isinstance(att.get("toolUseID"), str) else None
    if use_id in stream.tool_uses:
        parent = use_id
    else:
        parent = turn_entity_ref(stream.session_ref, rec.turn.prompt_id) if rec.turn is not None else None
    severity = "error" if code == 2 else "info" if code in (0, None) else "warning"
    command, stderr = att.get("command"), att.get("stderr")
    return _row(
        ctx,
        stream,
        rec,
        ext,
        ext,
        "process_event",
        "point",
        parent,
        name=hook_name(att),
        severity=severity,
        metadata=_meta(
            hook_event=att.get("hookEvent") if isinstance(att.get("hookEvent"), str) else None,
            hook_name=att.get("hookName") if isinstance(att.get("hookName"), str) else None,
            attachment_type=att.get("type"),
            exit_code=code if type(code) is int else None,
            duration_ms=att.get("durationMs") if type(att.get("durationMs")) is int else None,
            tool_use_id=use_id,
            command=scrub_text(command).text if isinstance(command, str) else None,
            stderr_head=scrub_text(stderr[:512]).text if isinstance(stderr, str) else None,
        ),
    )


def build_observations(parsed: ParsedTree, ctx: Ctx, diag: Counter[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in emitting_streams(parsed):
        for turn in stream.turns:
            if turn.closed:
                rows += _turn_rows(ctx, stream, turn, diag)
        rows += [_hook_row(ctx, stream, rec) for rec in stream.hooks if rec.turn is None or rec.turn.closed]
    return rows
