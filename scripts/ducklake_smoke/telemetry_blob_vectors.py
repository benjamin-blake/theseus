"""Vector data for the --lambda-telemetry-smoke blob gate (the twin; T2.36, slice 2a-2). Data and pure builders only: no I/O
and imports nothing from src.telemetry beyond the shared blob protocol constants and the identity derivation: the read-back
gate derives the grain key of a row it wrote through src.telemetry.identity, the derivation the writer uses. That derivation
is proven independently by the identity golden vectors, so reusing it proves the read path, not the derivation.

A fresh above-threshold payload per run (a uuid4 inside, so every deploy creates a new content-addressed key) as one
transcript row in the append vectors' golden wire shape, and the negative cases as (name, build, expected status, error_type,
expected field and value). The live gate and its hermetic test share this module.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from scripts.ducklake_smoke import telemetry_append_vectors as base
from src.telemetry.blobs import MAX_BLOB_ITEMS
from src.telemetry.identity import derive_entity_key, derive_event_id
from src.telemetry.timestamps import parse_wire_timestamp

THRESHOLD_BYTES = base.INLINE_THRESHOLD_BYTES
CAP_BYTES = 8 * 1024 * 1024
BLOB_BYTES = THRESHOLD_BYTES + 4096
CHUNK_BYTES = 3 * 1024 * 1024
MULTI_CHUNK_BYTES = CHUNK_BYTES + 4097


def fresh_content(tag: str, size: int = BLOB_BYTES) -> str:
    """ASCII content of exactly `size` bytes with a per-call random block inside, so its SHA-256 is new every run."""
    head = f"blob-{tag}-{secrets.token_hex(16)}-"
    return (head * (size // len(head) + 1))[:size]


def multi_chunk_content(tag: str) -> str:
    """CHUNK_BYTES + 4097 UTF-8 bytes: ASCII with heavy quote, backslash and newline runs, apart from one 4-byte character
    straddling byte CHUNK_BYTES (so a chunk edge splits it). A per-call random block makes its SHA-256 new every run."""
    unit = f'"q\\\\"\n\\n"{tag}-{secrets.token_hex(16)}"\n\\\\'
    emoji = "\U0001f600"
    head_len = CHUNK_BYTES - 2
    tail_len = MULTI_CHUNK_BYTES - head_len - 4
    fill = lambda n: (unit * (n // len(unit) + 1))[:n]  # noqa: E731
    return fill(head_len) + emoji + fill(tail_len)


def content_identity(row: dict[str, Any], tenant_id: str, project_id: str) -> tuple[str, str]:
    """(session_id, event_id) the writer derives for a transcript row: the grain key transcript_content reads it by."""
    session_id = derive_entity_key(
        "telemetry_sessions:session_id",
        tenant_id,
        project_id,
        row["session_ref"],
        parse_wire_timestamp(row["session_started_at"]),
    )
    event_id = derive_event_id(
        "telemetry_transcripts", tenant_id, project_id, row["external_ref"], parse_wire_timestamp(row["event_timestamp"])
    )
    return session_id, event_id


def blob_transcript_row(tag: str, index: int, started: datetime, content: str) -> dict[str, Any]:
    """A producer-side transcript row carrying inline content above the threshold (what the helper spills)."""
    return base.transcript_row(tag, index, started, content)


def item_for(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_ref": row["session_ref"],
        "session_started_at": row["session_started_at"],
        "content_sha256": row["content_sha256"],
        "content_bytes": row["content_bytes"],
    }


def misdeclared(fields: dict[str, Any]) -> dict[str, Any]:
    """A copy of a wire row or begin_blobs item whose content_bytes is one more than the object's true length."""
    return {**fields, "content_bytes": fields["content_bytes"] + 1}


def begin_body(project_ref: str, items: list[dict[str, Any]], component: str = "deploy-smoke") -> dict[str, Any]:
    return {"action": "begin_blobs", "project_ref": project_ref, "component": component, "items": items}


def append_body(project_ref: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return base.request(project_ref, [("telemetry_transcripts", rows)])


def wire_row(row: dict[str, Any]) -> dict[str, Any]:
    """The row after delivery: content removed, digest and length kept (what append_telemetry receives)."""
    return {k: v for k, v in row.items() if k != "content"}


def tamper_same_length(content: str) -> str:
    """Same UTF-8 length, different bytes: S3 answers 400 BadDigest to a PUT of this under the original checksum."""
    return ("Z" if content[0] != "Z" else "Y") + content[1:]


def different_length(content: str) -> str:
    return content + "x"


def _fake_item(index: int, started: datetime, tag: str, size: int) -> dict[str, Any]:
    digest = hashlib.sha256(f"{tag}-{index}".encode()).hexdigest()
    return {
        "session_ref": base.session_ref(tag),
        "session_started_at": base.wire_ts(started),
        "content_sha256": digest,
        "content_bytes": size,
    }


def too_many_items(started: datetime, tag: str) -> list[dict[str, Any]]:
    return [_fake_item(i, started, tag, BLOB_BYTES) for i in range(MAX_BLOB_ITEMS + 1)]


def too_many_blob_rows(started: datetime, tag: str) -> list[dict[str, Any]]:
    rows = []
    for index in range(MAX_BLOB_ITEMS + 1):
        row = base.transcript_row(tag, index, started, "x")
        item = _fake_item(index, started, tag, BLOB_BYTES)
        row.update(content=None, content_sha256=item["content_sha256"], content_bytes=item["content_bytes"])
        rows.append(row)
    return rows


@dataclass(frozen=True)
class NegativeVector:
    """A request and what the writer must answer: status, error_type and one named body field (None to skip)."""

    name: str
    build: Callable[[], dict[str, Any]]
    status: int
    error_type: str
    field: str | None = None
    value: Any = None


def bounds_vectors(project_ref: str, tag: str, started: datetime) -> tuple[NegativeVector, ...]:
    """The static refusals that need no object: item bounds, the item cap on both verbs, an unregistered reserved ref."""
    session = base.session_ref(tag)
    at_threshold = {**_fake_item(0, started, tag, THRESHOLD_BYTES), "session_ref": session}
    above_cap = {**_fake_item(1, started, tag, CAP_BYTES + 1), "session_ref": session}
    return (
        NegativeVector(
            "item_at_threshold",
            lambda: begin_body(project_ref, [at_threshold]),
            400,
            "bad_request",
            "reason",
            "below_threshold",
        ),
        NegativeVector(
            "item_above_cap", lambda: begin_body(project_ref, [above_cap]), 400, "bad_request", "reason", "above_cap"
        ),
        NegativeVector("too_many_items", lambda: begin_body(project_ref, too_many_items(started, tag)), 413, "too_many_blobs"),
        NegativeVector(
            "too_many_blob_rows",
            lambda: append_body(project_ref, too_many_blob_rows(started, tag)),
            413,
            "too_many_blobs",
        ),
        NegativeVector(
            "unregistered_drill_ref",
            lambda: begin_body(
                f"drill:unregistered-{tag}", [item_for(blob_transcript_row(tag, 0, started, fresh_content(tag)))]
            ),
            403,
            "project_unregistered",
        ),
    )
