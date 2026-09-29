"""Pure builders for telemetry_transcripts rows.

Content is scrubbed BEFORE content_sha256 and content_bytes; an empty payload yields no row; image/binary
blocks are replaced by a {type, media_type, sha256, bytes} stub; a tool_result is the full sidecar content when
it resolves, else the in-transcript preview with content_truncated true. Attachments emit no rows in 3a.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.turn_capture.cursor import CaptureCursor
from src.turn_capture.refs import transcript_ref, turn_entity_ref
from src.turn_capture.scrub import scrub_text
from src.turn_capture.streams import (
    HARNESS_DENIAL_PREFIXES,
    HARNESS_INTERRUPT_SENTINELS,
    ParsedTree,
    Rec,
    Result,
    block_base,
    emitting_streams,
)
from src.turn_capture.transcript import TranscriptTree

TRANSCRIPT_COLUMNS = (
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
    "purpose",
    "origin",
    "content",
    "content_uri",
    "content_sha256",
    "content_bytes",
    "content_truncated",
    "token_count",
    "model",
    "rec_id",
)


@dataclass(frozen=True)
class Ctx:
    producer: str
    producer_version: str
    parser_version: int
    started: datetime
    billing_shape: str


class Sidecars:
    """Sidecar reads under the cursor's pins: a present pin must still match, an absent pin is honoured."""

    def __init__(self, tree: TranscriptTree, cursor: CaptureCursor | None) -> None:
        self._tree = tree
        self._cursor = cursor
        self.used: dict[str, str | None] = {}

    def read(self, name: str) -> bytes | None:
        pins = self._cursor.sidecars if self._cursor is not None else {}
        if name in pins and pins[name] is None:
            return None
        data = self._tree.sidecar(name)
        sha = hashlib.sha256(data).hexdigest() if data is not None else None
        if self._cursor is not None:
            self._cursor.check_sidecar(name, sha)
        self.used[name] = sha
        return data


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stub(block: Any) -> Any:
    if not isinstance(block, dict):
        return block
    source = block.get("source")
    if block.get("type") != "image" and not (isinstance(source, dict) and "data" in source):
        return block
    source = source if isinstance(source, dict) else {}
    data = source.get("data")
    raw = data if isinstance(data, str) else ""
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        decoded = raw.encode("utf-8", "replace")
    return {
        "type": block.get("type"),
        "media_type": source.get("media_type"),
        "sha256": hashlib.sha256(decoded).hexdigest(),
        "bytes": len(decoded),
    }


def text_of(content: Any) -> str:
    """Payload text of a prompt or tool_result content value."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list) and all(
        isinstance(b, dict) and isinstance(b.get("text"), str) and b.get("type") == "text" for b in content
    ):
        return "\n".join(b["text"] for b in content)
    if isinstance(content, list):
        return canonical_json([_stub(b) for b in content])
    return canonical_json(content)


def clean(text: str) -> str:
    return scrub_text(text).text.encode("utf-8", "replace").decode("utf-8")


def is_sentinel(text: str) -> bool:
    return any(text.startswith(p) for p in HARNESS_DENIAL_PREFIXES) or text in HARNESS_INTERRUPT_SENTINELS


def _row(
    ctx: Ctx,
    rec: Rec,
    block: int,
    session_ref: str,
    obs_ref: str,
    purpose: str,
    origin: str,
    text: str,
    model: Any,
    truncated: bool = False,
) -> dict[str, Any]:
    payload = clean(text)
    ref = transcript_ref(rec.uuid, block)
    row: dict[str, Any] = dict.fromkeys(TRANSCRIPT_COLUMNS)
    row.update(
        event_kind="point",
        event_timestamp=rec.ts,
        session_started_at=ctx.started,
        source_ordinal=rec.line,
        external_ref=ref,
        entity_ref=ref,
        session_ref=session_ref,
        observation_ref=obs_ref,
        producer=ctx.producer,
        producer_version=ctx.producer_version,
        parser_version=ctx.parser_version,
        purpose=purpose,
        origin=origin,
        content=payload,
        content_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        content_bytes=len(payload.encode("utf-8")),
        content_truncated=truncated,
        model=model if isinstance(model, str) else None,
    )
    return {k: v for k, v in row.items() if v is not None}


def _prompt_like(ctx: Ctx, rec: Rec, session_ref: str, turn_ref: str, purpose: str, origin: str) -> list[dict[str, Any]]:
    content = rec.data["message"]["content"]
    blocks = [content] if isinstance(content, str) else list(content)
    rows = []
    for i, block in enumerate(blocks):
        if isinstance(block, str):
            text = block
        elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            text = block["text"]
        else:
            stub = _stub(block)
            text = canonical_json(stub) if stub is not block else ""
        if text != "":
            rows.append(_row(ctx, rec, i, session_ref, turn_ref, purpose, origin, text, None))
    return rows


def _assistant(ctx: Ctx, rec: Rec, session_ref: str, diag: Counter[str]) -> list[dict[str, Any]]:
    message = rec.data["message"]
    rows = []
    for i, block in enumerate(message["content"]):
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "thinking":
            purpose, text = "thinking", block.get("thinking")
        elif kind == "text":
            purpose, text = "response", block.get("text")
        elif kind == "tool_use":
            purpose, text = "tool_input", canonical_json(block.get("input"))
        else:
            diag[f"unknown_block_type:{kind}"] += 1
            continue
        if isinstance(text, str) and text != "":
            rows.append(
                _row(
                    ctx,
                    rec,
                    block_base(rec.data) + i,
                    session_ref,
                    message["id"],
                    purpose,
                    "agent",
                    text,
                    message.get("model"),
                )
            )
    return rows


def _tool_result(ctx: Ctx, res: Result, session_ref: str, sidecars: Sidecars, diag: Counter[str]) -> list[dict[str, Any]]:
    text = text_of(res.body.get("content"))
    truncated = False
    info = res.use_result
    path = info.get("persistedOutputPath") if isinstance(info, dict) else None
    name = re.split(r"[\\/]", path)[-1] if isinstance(path, str) else ""
    if name:
        data = sidecars.read(name)
        if data is not None:
            size = info.get("persistedOutputSize")
            if type(size) is int and size != len(data):
                diag["sidecar_size_mismatch"] += 1
            text = data.decode("utf-8", "replace")
        else:
            truncated = True
    if text == "":
        return []
    origin = "harness" if is_sentinel(text) else "tool"
    return [_row(ctx, res.rec, res.block, session_ref, res.tool_use_id, "tool_result", origin, text, None, truncated)]


def build_transcripts(parsed: ParsedTree, ctx: Ctx, sidecars: Sidecars, diag: Counter[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in emitting_streams(parsed):
        sref = stream.session_ref
        for turn in (t for t in stream.turns if t.closed):
            tref = turn_entity_ref(sref, turn.prompt_id)
            for rec in turn.recs:
                if rec.kind == "prompt":
                    harness = rec.data.get("isMeta") is True
                    rows += _prompt_like(
                        ctx, rec, sref, tref, "system" if harness else "prompt", "harness" if harness else "human"
                    )
                elif rec.kind == "companion":
                    rows += _prompt_like(ctx, rec, sref, tref, "system", "harness")
                elif rec.kind == "assistant":
                    rows += _assistant(ctx, rec, sref, diag)
            for use in turn.tool_uses:
                if use.result is not None:
                    rows += _tool_result(ctx, use.result, sref, sidecars, diag)
            for res in turn.orphan_results:
                rows += _tool_result(ctx, res, sref, sidecars, diag)
    return rows
