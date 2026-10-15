"""One capture pass over one transcript tree (rules RN-1..RN-8).

lock -> halt check -> cursor load and tail check -> project_ref (cursor pin, else the SessionStart pin, else defer) ->
record_turn -> describe check -> blob delivery -> chunked appends in record_turn order -> cursor persisted only after every
request is acknowledged -> one diagnostics line. Nothing is ever printed; diagnostics carry counts and fixed tokens only.
"""

from __future__ import annotations

import random
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.telemetry_capture import responses, switch
from scripts.telemetry_capture.state import LOST, TAIL_MISMATCH, CaptureState, Loaded, state_dir
from scripts.telemetry_capture.transport import (
    MAX_INVOKE_BODY_BYTES,
    MAX_ROWS_PER_REQUEST,
    MAX_ROWS_PER_TABLE,
    Budget,
    CaptureUnavailable,
    Item,
    Limits,
    WriterClient,
    append_body,
    chunk,
    make_client,
)
from src.telemetry_client.blob_delivery import (
    BlobDeliveryError,
    BlobProtocol,
    HandshakeError,
    deliver_blobs,
    protocol_from_describe,
)
from src.turn_capture.cursor import CursorError
from src.turn_capture.record_turn import record_turn
from src.turn_capture.transcript import ROOT, FsTree, project_ref_pin

TRANSCRIPTS = "telemetry_transcripts"
STOP_BUDGET_S = 600.0
ClientFactory = Callable[..., WriterClient]


@dataclass(frozen=True)
class PassResult:
    outcome: str
    diag: dict[str, Any] = field(default_factory=dict)


class SnapshotTree(FsTree):
    """An FsTree whose root file is read once, so the tail check and record_turn see the same bytes."""

    def __init__(self, root_file: Path) -> None:
        super().__init__(root_file)
        self.root_bytes: bytes | None = root_file.read_bytes() if root_file.is_file() else None

    def read(self, key: str) -> bytes | None:
        return self.root_bytes if key == ROOT else super().read(key)


class _Stop(Exception):
    def __init__(self, outcome: str, reason: str, halt: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.outcome, self.reason, self.halt = outcome, reason, halt


def default_client_factory(
    env: Mapping[str, str],
    state: CaptureState,
    budget: Budget,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> WriterClient:
    return make_client(env, state, budget, sleep=sleep, rng=rng)


def _describe(client: WriterClient) -> BlobProtocol:
    """RN-5: the writer serves append_telemetry on the smoke catalog with caps no lower than TR-3's and a blob protocol."""
    status, body = client.invoke({"action": "describe"})
    try:
        caps = body["verbs"]["append_telemetry"]["caps"]
        ok = (
            status == 200
            and "append_telemetry" in body["actions"]
            and body["catalog"]["data_path_is_smoke"] is True
            and caps["max_invoke_body_bytes"] >= MAX_INVOKE_BODY_BYTES
            and caps["max_rows_per_table"] >= MAX_ROWS_PER_TABLE
            and caps["max_rows_per_request"] >= MAX_ROWS_PER_REQUEST
        )
        protocol = protocol_from_describe(body)
    except (KeyError, TypeError, HandshakeError):
        ok = False
    if not ok:
        raise _Stop("stopped", "describe_mismatch")
    return protocol


class _Sender:
    """RN-6 and RN-7 over one pass's rows: delivery, chunked appends, the response table."""

    def __init__(
        self, client: WriterClient, protocol: BlobProtocol, project_ref: str, sleep: Callable[[float], None], diag: Counter
    ) -> None:
        self.client, self.protocol, self.project_ref, self.sleep, self.diag = client, protocol, project_ref, sleep, diag
        self.originals: dict[int, dict[str, Any]] = {}
        self.registered = False
        self.requests: list[dict[str, dict[str, int]]] = []

    def deliver(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            delivery = deliver_blobs(
                rows,
                project_ref=self.project_ref,
                invoke=self.client.invoke_once,
                protocol=self.protocol,
                component="turn_capture",
                put=self.client.put,
                sleep=self.sleep,
            )
        except BlobDeliveryError as exc:
            if exc.kind in ("refused", "defect"):
                halt = {"reason": "blob_" + exc.kind, "error_class": "BlobDeliveryError", "status": exc.status}
                raise _Stop("halted", "blob_" + exc.kind, {k: v for k, v in halt.items() if v is not None}) from None
            raise _Stop("stopped", "blob_" + exc.kind) from None
        self.diag["blobs_existed"] += delivery.existed
        self.diag["blobs_uploaded"] += delivery.uploaded
        return delivery.wire_rows

    def items(self, batches: list[tuple[str, list[dict[str, Any]]]]) -> list[Item]:
        out: list[Item] = []
        for table, rows in batches:
            wire = self.deliver(rows) if table == TRANSCRIPTS and rows else rows
            for original, row in zip(rows, wire, strict=True):
                if table == TRANSCRIPTS:
                    self.originals[id(row)] = original
                out.append((table, row))
        return out

    def redeliver(self, request: list[Item]) -> None:
        rows = [self.originals[id(row)] for table, row in request if table == TRANSCRIPTS and id(row) in self.originals]
        if rows:
            self.deliver(rows)

    def _register_tenant(self) -> bool:
        if self.registered:
            return False
        self.registered = True
        status, body = self.client.invoke({"action": "register_tenant"})
        return responses.classify(status, body) == responses.OK

    def _acknowledged(self, body: Mapping[str, Any]) -> None:
        tables = body.get("tables") if isinstance(body.get("tables"), Mapping) else {}
        counts: dict[str, dict[str, int]] = {}
        for table, numbers in tables.items():
            if isinstance(numbers, Mapping):
                counts[str(table)] = {k: int(numbers.get(k) or 0) for k in ("submitted", "inserted")}
        self.requests.append(counts)

    def send(self, items: list[Item], conflict_reason: str) -> None:
        limits = Limits(self.protocol.max_items, self.protocol.inline_threshold_bytes, self.protocol.cap_bytes)
        queue = deque(chunk(items, self.project_ref, limits))
        redelivered: set[int] = set()
        while queue:
            request = queue[0]
            if self.client.budget.remaining() <= 0:
                raise _Stop("stopped", "deadline")
            status, body = self.client.invoke(append_body(self.project_ref, request))
            action = responses.classify(status, body)
            if action == responses.OK:
                self._acknowledged(body)
                queue.popleft()
            elif action == responses.REGISTER_TENANT:
                if not self._register_tenant():
                    raise _Stop("stopped", "tenant_unresolved")
            elif action == responses.REDELIVER and id(request) not in redelivered:
                redelivered.add(id(request))
                self.redeliver(request)
            elif action == responses.RECHUNK and len(request) > 1:
                half = len(request) // 2
                queue.popleft()
                queue.extendleft([request[half:], request[:half]])
            elif action in (responses.REDELIVER, responses.RECHUNK, responses.HALT):
                reason = conflict_reason if status == 409 else "writer_refused"
                raise _Stop("halted", reason, {"reason": reason, **responses.halt_fields(status, body)})
            elif self.client.budget.remaining() <= 0:
                raise _Stop("stopped", "deadline")
            else:
                raise _Stop("stopped", f"status_{status}" if status else "transport")


def _finish(state: CaptureState, record: dict[str, Any], outcome: str, diag: Counter) -> PassResult:
    record.update(outcome=outcome, diag=dict(sorted(diag.items())))
    state.append_diagnostic(record)
    return PassResult(outcome, record)


def _locked_pass(
    root_file: Path,
    state: CaptureState,
    event: str,
    *,
    final: bool,
    budget: Budget,
    env: Mapping[str, str],
    smoke_ref: str | None,
    client_factory: ClientFactory,
    detach_below: float | None,
    sleep: Callable[[float], None],
    rng: Callable[[], float],
) -> PassResult:
    diag: Counter[str] = Counter()
    record: dict[str, Any] = {"event": event, "final": final, "at": int(time.time())}
    if state.halt() is not None:
        return _finish(state, record, "halted", diag)
    tree = SnapshotTree(root_file)
    root = tree.root_bytes or b""
    loaded = state.load_cursor(root)
    if not loaded.valid:
        diag[loaded.status] += 1
    project_ref = loaded.cursor.project_ref if loaded.cursor is not None else project_ref_pin(tree)
    if project_ref is None:
        diag["deferred_no_pin"] += 1
        return _finish(state, record, "deferred", diag)
    if smoke_ref is not None and project_ref != smoke_ref:
        diag["smoke_pin_mismatch"] += 1
        return _finish(state, record, "off", diag)
    try:
        result = record_turn(tree, loaded.cursor, project_ref=project_ref, session_final=final)
    except CursorError as exc:
        halt = {"reason": "producer_error", "error_class": type(exc).__name__}
        state.write_halt(halt)
        record["halt"] = halt
        return _finish(state, record, "halted", diag)
    record["record_turn"] = result.diagnostics
    if detach_below is not None and budget.remaining() < detach_below:
        return _finish(state, record, "short_budget", diag)
    rows = sum(len(rows) for _, rows in result.batches)
    record["rows"] = {table: len(rows) for table, rows in result.batches}
    if not rows:
        if result.next_cursor is not None:
            _persist(state, result.next_cursor, root, loaded, diag)
        return _finish(state, record, "no_rows", diag)
    conflict = "grain_conflict_after_cursor_loss" if loaded.status in (LOST, TAIL_MISMATCH) else "grain_conflict"
    sender: _Sender | None = None
    try:
        client = client_factory(env, state, budget, sleep=sleep, rng=rng)
        protocol = _describe(client)
        sender = _Sender(client, protocol, project_ref, sleep, diag)
        sender.send(sender.items(result.batches), conflict)
    except CaptureUnavailable as exc:
        diag[exc.reason] += 1
        return _finish(state, record, "stopped", diag)
    except _Stop as stop:
        diag[stop.reason] += 1
        if sender is not None:
            record["requests"] = sender.requests
        if stop.halt is not None:
            state.write_halt(stop.halt)
            record["halt"] = stop.halt
        return _finish(state, record, stop.outcome, diag)
    record["requests"] = sender.requests
    if result.next_cursor is not None:
        _persist(state, result.next_cursor, root, loaded, diag)
    return _finish(state, record, "sent", diag)


def _persist(state: CaptureState, cursor: Any, root: bytes, loaded: Loaded, diag: Counter) -> None:
    if not state.save_cursor(cursor, root, loaded):
        diag["cursor_regression"] += 1


def run_pass(
    transcript_path: Path,
    session_id: str,
    event: str,
    *,
    final: bool,
    budget: Budget,
    env: Mapping[str, str],
    repo_root: Path,
    client_factory: ClientFactory = default_client_factory,
    lock_wait: float = 0.0,
    detach_below: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> PassResult:
    """RN-1..RN-8. "off" before any state is touched; "busy" when another pass holds the tree's lock."""
    mode = switch.capture_mode(env, repo_root)
    if mode == switch.OFF:
        return PassResult("off")
    root_file = Path(transcript_path)
    smoke_ref = switch.smoke_ref(env) if mode == switch.SMOKE else None
    if smoke_ref is not None and project_ref_pin(SnapshotTree(root_file)) != smoke_ref:
        return PassResult("off", {"smoke_pin_mismatch": 1})
    state = CaptureState(state_dir(root_file, session_id))
    lock = state.acquire(min(lock_wait, budget.remaining()), sleep=sleep)
    if lock is None:
        return PassResult("busy")
    try:
        return _locked_pass(
            root_file,
            state,
            event,
            final=final,
            budget=budget,
            env=env,
            smoke_ref=smoke_ref,
            client_factory=client_factory,
            detach_below=detach_below,
            sleep=sleep,
            rng=rng,
        )
    finally:
        lock.release()
