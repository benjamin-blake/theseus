"""Shared fakes for the append_telemetry tests (T2.36, plan 3 part 2): an adapter kit with fake part 1 primitives and
a fake telemetry writer that answers append_telemetry and the grain_counts probe. No duckdb, no network."""

from __future__ import annotations

import functools
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from src.common import ducklake_runtime as rt
from src.common import ducklake_telemetry_append as adapter
from src.common import ducklake_telemetry_registration as reg
from src.common.ducklake_telemetry_txn import TxnOutcome
from src.lambdas.ducklake_telemetry_writer import handler as h
from src.lambdas.ducklake_telemetry_writer import telemetry_edge as edge
from src.telemetry.append import AppendResult
from src.telemetry.gate import GrainConflictError
from src.telemetry.identity import derive_entity_key
from src.telemetry.request import AppendRequest, TableShape, parse_append_request
from tests.fixtures.turn_capture_ducklake import load_specs

TENANT = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RESOLVED = "01BX5ZZKBKACTAV9WEVGEMMVRY"
SESSION = "2026-01-01T12:00:00.000Z"
NOW = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)


@functools.lru_cache(maxsize=1)
def specs() -> dict[str, Any]:
    return load_specs()


def shapes() -> dict[str, TableShape]:
    return {name: TableShape.from_spec(spec) for name, spec in specs().items()}


def session_row(**over: Any) -> dict[str, Any]:
    row = {
        "event_kind": "open",
        "event_timestamp": SESSION,
        "session_started_at": SESSION,
        "external_ref": "s#0/open",
        "entity_ref": "sess",
        "producer": "claude_code",
        "producer_version": "t",
        "parser_version": 2,
        "workflow": "implement",
        "execution_attempt": 1,
    }
    return {**row, **over}


def transcript_row(**over: Any) -> dict[str, Any]:
    row = {
        "event_kind": "point",
        "event_timestamp": SESSION,
        "session_started_at": SESSION,
        "external_ref": "t#0",
        "entity_ref": "t#0",
        "session_ref": "sess",
        "observation_ref": "turn-1",
        "producer": "claude_code",
        "producer_version": "t",
        "parser_version": 2,
        "purpose": "prompt",
        "origin": "human",
        "content": "hello",
        "content_sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",  # pragma: allowlist secret
        "content_bytes": 5,
        "content_truncated": False,
    }
    return {**row, **over}


def parse(project_ref: str, *batches: tuple[str, list[dict[str, Any]]]) -> AppendRequest:
    body = {"project_ref": project_ref, "batches": [{"table": t, "rows": r} for t, r in batches]}
    return parse_append_request(body, shapes())


@dataclass
class AdapterKit:
    """Fake part 1 primitives and a recording transaction around ducklake_telemetry_append."""

    lookup_result: tuple[str, str] | None = None
    resolved_id: str = RESOLVED
    created: bool = True
    fail_on_table: str | None = None
    events: list[str] = field(default_factory=list)
    executed_project_ids: list[tuple[str, set[str]]] = field(default_factory=list)
    cache: dict[tuple[str, str], str] = field(default_factory=dict)
    cache_at_commit: list[dict[tuple[str, str], str]] = field(default_factory=list)

    def install(self, monkeypatch: Any) -> AdapterKit:
        monkeypatch.setattr(reg, "_PROJECT_CACHE", self.cache)
        monkeypatch.setattr(reg, "lookup_project", self._lookup)
        monkeypatch.setattr(reg, "resolve_or_register_project", self._resolve)
        monkeypatch.setattr(adapter, "run_telemetry_txn", self._txn)
        monkeypatch.setattr(adapter, "execute_prepared", self._execute)
        return self

    def _lookup(self, con: Any, tenant_id: str, project_ref: str, *, semantics: Any = None) -> tuple[str, str] | None:
        self.events.append("lookup")
        return self.lookup_result

    def _resolve(self, con: Any, tenant_id: str, project_ref: str, **kw: Any) -> tuple[str, bool]:
        self.events.append("resolve")
        assert kw["explicit"] is False
        return self.resolved_id, self.created

    def _txn(self, con: Any, body: Any, *, metric_sink: Any = None, **kw: Any) -> TxnOutcome:
        self.events.append("BEGIN")
        result = body(con)
        self.cache_at_commit.append(dict(self.cache))
        self.events.append("COMMIT")
        return TxnOutcome(result=result, occ_retries=0, commit_ms=1.0)

    def _execute(self, con: Any, prepared: Any, *, catalog: str) -> AppendResult:
        table = prepared.table_spec.table
        self.events.append(f"execute:{table}")
        self.executed_project_ids.append((table, {row["project_id"] for row in prepared.rows}))
        if table == self.fail_on_table:
            raise RuntimeError("injected failure")
        return AppendResult(prepared.submitted, prepared.collapsed, len(prepared.rows))


_ACCOUNT = "acct-under-test"
_USER_ARN = "arn:aws:sts::acct-under-test:assumed-role/Some/secret-session"


class LiveFake(AdapterKit):
    """The real handler, edge, grammar, kernel gate and adapter over an in-memory store: what a deployed telemetry writer
    answers, with stored-row grain conflicts, first-sight registration and a grain_counts probe. Registration and the
    transaction are the only fakes (the part 1 primitives touch DuckLake)."""

    def __init__(self) -> None:
        super().__init__()
        self.projects: dict[str, str] = {}
        self.stored: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.files: dict[str, int] = {}
        self.lock = threading.Lock()
        self.data_path_is_smoke = True

    def activate(self, monkeypatch: Any) -> LiveFake:
        self.install(monkeypatch)
        monkeypatch.setenv("TELEMETRY_META_SCHEMA", "ducklake_smoke")
        monkeypatch.setenv("TELEMETRY_DATA_PATH", rt.SMOKE_DATA_PATH)
        monkeypatch.setenv("TELEMETRY_DSN_SECRET_ID", "secret")
        monkeypatch.setattr(
            rt, "get_warm_connection", lambda **kw: (MagicMock(), {"reused": True, "reopened": False, "connect_ms": 0.0})
        )
        monkeypatch.setattr(reg, "lookup_tenant", lambda con, kind, ref, semantics=None: TENANT)
        monkeypatch.setitem(h.actions.VERBS, "telemetry_probe", self._probe)
        edge.reset_cache()
        reg.clear_telemetry_caches()
        return self

    def register(self, project_ref: str, project_id: str) -> None:
        self.projects[project_ref] = project_id

    def invoke(self, url: str, payload: dict[str, Any], **kw: Any) -> Any:
        from tests.fixtures.ducklake_smoke_fakes import _Resp

        if kw.get("sign", True) is False:
            return _Resp(403, {"Message": "Forbidden"})
        event = {
            "body": json.dumps(payload),
            "isBase64Encoded": False,
            "requestContext": {"authorizer": {"iam": {"accountId": _ACCOUNT, "userArn": _USER_ARN}}},
        }
        response = h.handler(event)
        return _Resp(response["statusCode"], json.loads(response["body"]))

    def _lookup(self, con: Any, tenant_id: str, project_ref: str, *, semantics: Any = None) -> tuple[str, str] | None:
        found = self.projects.get(project_ref)
        return None if found is None else (found, "registered")

    def _resolve(self, con: Any, tenant_id: str, project_ref: str, **kw: Any) -> tuple[str, bool]:
        if project_ref in self.projects:
            return self.projects[project_ref], False
        self.projects[project_ref] = "01C" + format(len(self.projects) + 1, "023d")
        return self.projects[project_ref], True

    def _txn(self, con: Any, body: Any, *, metric_sink: Any = None, **kw: Any) -> TxnOutcome:
        with self.lock:
            saved = (dict(self.projects), dict(self.stored), dict(self.files))
            try:
                result = body(con)
            except BaseException:
                self.projects, self.stored, self.files = saved
                raise
            if metric_sink is not None:
                metric_sink("OccRetryCount", 0.0)
                metric_sink("CommitLatencyMs", 12.3456)
            self.cache.update({(TENANT, ref): pid for ref, pid in self.projects.items()})
            return TxnOutcome(result=result, occ_retries=0, commit_ms=12.3456)

    def _execute(self, con: Any, prepared: Any, *, catalog: str) -> AppendResult:
        spec = prepared.table_spec
        inserted = 0
        for row in prepared.rows:
            key = (row["project_id"], spec.table, row["event_id"])
            compared = {k: v for k, v in row.items() if k not in spec.compare_excluded}
            old = self.stored.get(key)
            if old is None:
                self.stored[key] = {**compared, "_session": row["session_id"]}
                inserted += 1
            elif {k: v for k, v in old.items() if k != "_session"} != compared:
                raise GrainConflictError(
                    "TELEMETRY_GRAIN_CONFLICT: conflicting row",
                    table=spec.table,
                    event_id=row["event_id"],
                    row=prepared.source_index.get(row["event_id"]),
                )
        if inserted:
            self.files[spec.table] = self.files.get(spec.table, 0) + 1
        return AppendResult(prepared.submitted, prepared.collapsed, inserted)

    def _probe(self, request: Any, con: Any, deps: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "data_path_is_smoke": self.data_path_is_smoke}
        body = request.body
        if "project_ref" not in body:
            return out
        project_id = self.projects.get(body["project_ref"])
        started = datetime.fromisoformat(body["session_started_at"].replace("Z", "+00:00"))
        out["project_registered"] = project_id is not None
        out["data_files"] = {t: {"files": n, "bytes": 0} for t, n in self.files.items()}
        out["grain_counts"] = None
        if project_id is not None:
            session = derive_entity_key("telemetry_sessions:session_id", TENANT, project_id, body["session_ref"], started)
            counts: dict[str, dict[str, int]] = {}
            for (pid, table, _event), row in self.stored.items():
                if pid == project_id and row["_session"] == session:
                    entry = counts.setdefault(table, {"rows": 0, "keys": 0})
                    entry["rows"] += 1
                    entry["keys"] += 1
            out["grain_counts"] = counts
        return out
