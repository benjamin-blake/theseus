"""Shared helpers for the turn-capture tests: synthetic record builders, the golden corpus loader, normalisation and the
single golden-digest definition. Stdlib only (fast tier); the corpus is synthetic and no credential-shaped literal is
ever written here -- secret-shaped strings are assembled at runtime by build_secret().
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.telemetry.identity import KEY_PLANS, derive_entity_key, derive_event_id
from src.turn_capture.render import render_datetime
from src.turn_capture.transcript import MemTree

SID = "aaaaaaaa-0000-4000-8000-000000000001"
TENANT = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
PROJECT = "01BX5ZZKBKACTAV9WEVGEMMVRY"
PROJECT_REF = "example/project"
GOLDEN_DIR = Path(__file__).parent / "turn_capture" / "golden"
_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SIDE_EFFECT_KEYS = ("created_timestamp", "producer_version", "content_sha256")


def ts(seconds: float) -> str:
    stamp = _EPOCH + timedelta(milliseconds=round(seconds * 1000))
    return f"{stamp:%Y-%m-%dT%H:%M:%S}.{stamp.microsecond // 1000:03d}Z"


def _base(uuid: str, t: float, **extra: Any) -> dict[str, Any]:
    rec = {"uuid": uuid, "timestamp": ts(t), "sessionId": SID, "gitBranch": "claude/test", "version": "2.1.0", "cwd": "/w"}
    rec.update(extra)
    return rec


def queue_op(t: float, *, uuid: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(t), "sessionId": SID}
    if uuid:
        rec["uuid"] = uuid
    return rec


def prompt(uuid: str, t: float, pid: str, text: Any, **extra: Any) -> dict[str, Any]:
    return _base(uuid, t, type="user", promptId=pid, message={"role": "user", "content": text}, **extra)


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def thinking_block(text: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": text, "signature": "sig"}


def tool_use_block(tool_id: str, name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input, "caller": {"type": "direct"}}


def assistant(
    uuid: str,
    t: float,
    mid: str,
    blocks: list[Any],
    *,
    usage: dict[str, Any] | None = None,
    api_block: int | None = None,
    model: str = "claude-test-1",
    **extra: Any,
) -> dict[str, Any]:
    use = (
        {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}
        if usage is None
        else usage
    )
    message = {
        "id": mid,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": blocks,
        "stop_reason": "end_turn",
        "usage": use,
    }
    rec = _base(uuid, t, type="assistant", message=message, requestId="req_" + mid, **extra)
    if api_block is not None:
        rec["apiBlockIndex"] = api_block
    return rec


def tool_result(
    uuid: str,
    t: float,
    tool_use_id: str,
    content: Any,
    *,
    pid: str | None = None,
    is_error: bool | None = None,
    tur: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    block: dict[str, Any] = {"tool_use_id": tool_use_id, "type": "tool_result", "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    rec = _base(uuid, t, type="user", message={"role": "user", "content": [block]}, **extra)
    if pid is not None:
        rec["promptId"] = pid
    if tur is not None:
        rec["toolUseResult"] = tur
    return rec


def hook(
    uuid: str,
    t: float,
    hook_name: str,
    *,
    tool_use_id: str | None = None,
    exit_code: int | None = 0,
    command: str | None = None,
    a_type: str = "hook_success",
    **extra: Any,
) -> dict[str, Any]:
    att: dict[str, Any] = {"type": a_type, "hookName": hook_name, "hookEvent": hook_name.split(":")[0]}
    if tool_use_id is not None:
        att["toolUseID"] = tool_use_id
    if exit_code is not None:
        att["exitCode"] = exit_code
    if command is not None:
        att["command"] = command
    att.update(extra)
    return _base(uuid, t, type="attachment", attachment=att)


def attachment(uuid: str, t: float, a_type: str, **fields: Any) -> dict[str, Any]:
    return _base(uuid, t, type="attachment", attachment={"type": a_type, **fields})


def child(rec: dict[str, Any], agent_id: str) -> dict[str, Any]:
    return {**rec, "agentId": agent_id, "isSidechain": True}


def jsonl(records: list[dict[str, Any]], tail: str = "") -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in records) + tail


def make_files(
    root: list[dict[str, Any]],
    children: dict[str, list[dict[str, Any]]] | None = None,
    sidecars: dict[str, str] | None = None,
    root_tail: str = "",
) -> dict[str, str]:
    files = {f"{SID}.jsonl": jsonl(root, root_tail)}
    for agent_id, records in (children or {}).items():
        files[f"{SID}/subagents/agent-{agent_id}.jsonl"] = jsonl(records)
    for name, body in (sidecars or {}).items():
        files[f"{SID}/tool-results/{name}"] = body
    return files


def build_secret(kind: str) -> str:
    """Secret-shaped strings assembled by concatenation, so no credential-shaped literal is committed."""
    filler = "abcdefghijklmnopqrstuvwxyz0123456789"
    parts = {
        "aws_access": ("AK" + "IA", "ABCDEFGHIJKLMNOP"),
        "aws_secret": ("wJalrXUtnFEMI/K7MDENG", "/bPxRfiCYEXAMPLEKEY"),
        "aws_session": ("FwoGZXIvYXdzE" + "JDH", "//////////wEaDExampleSessionTokenValue+/=="),
        "anthropic": ("sk-" + "ant-", "api03-" + filler + "_-" + filler[:8]),
        "github": ("gh" + "p_", filler + filler[:8]),
        "github_pat": ("github" + "_pat_", (filler + "_") * 3),
        "bearer": ("Bear" + "er ", "abcdef0123456789abcdef0123456789xyz"),
    }
    head, tail = parts[kind]
    return head + tail


def case_names() -> list[str]:
    return list(json.loads((GOLDEN_DIR / "index.json").read_text(encoding="utf-8"))["cases"])


def load_case(name: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    body = json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))
    return (secrets_files() if name == "secrets.json" else body["files"]), body["expected_rows"]


def mem_tree(files: dict[str, str]) -> MemTree:
    return MemTree(files)


def _render(value: Any) -> Any:
    return render_datetime(value) if isinstance(value, datetime) else value


def assert_content_hashes(batches: list[tuple[str, list[dict[str, Any]]]]) -> None:
    """content_sha256 is the sha256 of the UTF-8 bytes of content and content_bytes their length. The digest is dropped
    from the committed golden rows (64-hex strings trip detect-secrets and bloat .secrets.baseline past its size budget)
    and asserted here for every emitted row instead."""
    for _, rows in batches:
        for row in rows:
            if "content" in row:
                data = row["content"].encode("utf-8")
                assert row["content_sha256"] == hashlib.sha256(data).hexdigest(), row["external_ref"]
                assert row["content_bytes"] == len(data), row["external_ref"]


def normalise(batches: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Canonical rows: derived ids added with the fixed test tenant/project; None columns and the excluded columns
    (created_timestamp, producer_version, content_sha256) dropped; datetimes rendered; sorted by table then event_id."""
    out: list[dict[str, Any]] = []
    for table, rows in batches:
        for row in rows:
            norm = {k: _render(v) for k, v in row.items() if v is not None and k not in _SIDE_EFFECT_KEYS}
            for column, plan in KEY_PLANS[table].items():
                ref = row.get(plan.ref_field)
                if ref is not None:
                    norm[column] = derive_entity_key(plan.domain_tag, TENANT, PROJECT, ref, row["session_started_at"])
            norm["event_id"] = derive_event_id(table, TENANT, PROJECT, row["external_ref"], row["event_timestamp"])
            norm["table"] = table
            out.append(norm)
    return sorted(out, key=lambda r: (r["table"], r["event_id"]))


def golden_digest(rows_by_case: dict[str, list[dict[str, Any]]], order: list[str]) -> str:
    """sha256 over, per case in index order, the case basename, a newline and the canonical expected_rows JSON."""
    parts = [
        f"{name}\n{json.dumps(rows_by_case[name], sort_keys=True, separators=(',', ':'), ensure_ascii=False)}"
        for name in order
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def secrets_files() -> dict[str, str]:
    """The secrets case inputs, assembled at runtime (never committed as literals)."""
    s = build_secret
    escaped = json.dumps({"SecretAccessKey": s("aws_secret"), "SessionToken": s("aws_session")})
    records = [
        prompt("s1", 1, "p1", f"keys {s('aws_access')} and {s('anthropic')} and {s('github')}"),
        assistant(
            "s2", 2, "ms1",
            [
                text_block(f"token {s('github_pat')} then {s('bearer')}"),
                tool_use_block("tus1", "Bash", {"command": f"echo {escaped}"}),
            ],
        ),
        tool_result(
            "s3", 3, "tus1", f"export AWS_SECRET_ACCESS_KEY={s('aws_secret')}\nexport AWS_SESSION_TOKEN={s('aws_session')}\n",
            pid="p1",
        ),
        hook("s4", 4, "PostToolUse:Bash", tool_use_id="tus1", command=f"bash -c 'curl -H \"Authorization: {s('bearer')}\"'"),
    ]  # fmt: skip
    return make_files(records)


def make_ctx(billing_shape: str = "fixed_non_rollover_allowance"):
    from src.turn_capture.transcripts import Ctx  # noqa: PLC0415

    return Ctx("claude_code", "test-build", 1, _EPOCH, billing_shape)


def parse_records(root, children=None, final=True):
    from src.turn_capture.streams import parse_tree  # noqa: PLC0415

    return parse_tree(mem_tree(make_files(root, children)), None, final)


class Row(dict):
    """A row whose omitted (NULL) columns read as None."""

    def __missing__(self, key: str) -> None:
        return None


def rows_of(rows: list[dict[str, Any]]) -> list[Row]:
    return [Row(r) for r in rows]
