# complexity-waiver: decision-43
"""Rule-clean rows, the writer adapters' rule entry points and a rule-kind mutation catalogue (rec-4158).

Shared by tests/checks/contracts/test_write_time_enforcement_conformance.py. Importable (its name does not start with
test_). The mutation catalogue reads RowRules itself, so a rule kind or column the engine gains is a mutation the test
must produce -- never a list written here.
"""

from __future__ import annotations

import functools
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from src.common import ducklake_runtime as rt
from src.common import ducklake_telemetry_registration as reg
from src.common.ducklake_scd2_schema import SchemaGateError, load_field_semantics
from src.common.ducklake_write_rules import RowRuleViolationError, rules_for
from src.row_rules.rules import RowRules
from src.telemetry.append import prepare_batch
from src.telemetry.gate import GateError, RowRuleGateError
from tests.fixtures.ducklake_fakes import FakeCon, ops_rec_record
from tests.fixtures.turn_capture_ducklake import load_specs

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(seconds=30, microseconds=999_999)
TENANT = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
PROJECT = "01BX5ZZKBKACTAV9WEVGEMMVRY"
_SHA = "a" * 64  # pragma: allowlist secret


def _event(ref: str, **over: Any) -> dict[str, Any]:
    row = {
        "event_kind": "point",
        "event_timestamp": T0 + timedelta(seconds=5),
        "session_started_at": T0,
        "external_ref": ref,
        "entity_ref": ref,
        "session_ref": "sess",
        "producer": "claude_code",
        "producer_version": "t",
        "parser_version": 3,
    }
    return {**row, **over}


def _session(ref: str, **over: Any) -> dict[str, Any]:
    return {k: v for k, v in _event(ref, **over).items() if k != "session_ref"}


def _observation(**over: Any) -> dict[str, Any]:
    return _event("o#0", **over)


# Scenarios: complete rule-clean rows, one per combination of conditional rules the table declares (the first is the base).
SCENARIOS: dict[str, list[dict[str, Any]]] = {
    "ops_recommendations": [ops_rec_record()],
    "ops_decisions": [{"id": "dec-1", "title": "A decision", "status": "active"}],
    "ops_tenants": [
        {
            "tenant_id": TENANT,
            "principal_kind": "aws_account",
            "principal_ref": "placeholder",
            "status": "active",
            "canonical_tenant_id": None,
        }  # fmt: skip
    ],
    "ops_projects": [
        {
            "project_id": PROJECT,
            "tenant_id": TENANT,
            "project_ref": "proj-1",
            "registration": "registered",
            "status": "active",
            "purpose": "real",
        }  # fmt: skip
    ],
    "telemetry_sessions": [
        _session("s#0", event_kind="open", entity_ref="sess", workflow="implement", execution_attempt=1),
        _session("s#1", event_kind="close", entity_ref="sess", outcome="success"),
        _session(
            "s#2",
            event_kind="annotate",
            entity_ref="sess",
            pr_url="https://example.invalid/pr/1",
            ci_outcome="green",
            coverage_after=90.5,
        ),  # fmt: skip
    ],
    "telemetry_observations": [
        _observation(observation_type="process_event", name="hook:probe", severity="info"),
        _observation(
            observation_type="tool_call",
            event_kind="close",
            outcome="success",
            output_capture="captured",
            output_bytes=5,
            output_sha256=_SHA,
            output_lines=1,
        ),  # fmt: skip
        _observation(
            observation_type="model_call",
            tokens_input=1,
            tokens_output=2,
            tokens_cache_read=0,
            tokens_cache_creation=0,
            billing_shape="metered_marginal",
            reasoning_visibility="full",
            reasoning_tokens=1,
        ),  # fmt: skip
        _observation(
            observation_type="model_call",
            tokens_input=1,
            tokens_output=2,
            tokens_cache_read=0,
            tokens_cache_creation=0,
            billing_shape="metered_marginal",
            reasoning_visibility="none",
            reasoning_tokens=0,
        ),  # fmt: skip
    ],
    "telemetry_transcripts": [
        _event(
            "t#0",
            observation_ref="turn-1",
            purpose="prompt",
            origin="human",
            content="hello",
            content_sha256=hashlib.sha256(b"hello").hexdigest(),
            content_bytes=5,
            content_truncated=False,
        )  # fmt: skip
    ],
    "telemetry_agents": [
        _event("a#0", event_kind="open", agent_type="manual"),
        _event("a#1", event_kind="close", agent_type="manual", outcome="success"),
    ],
}


def _ignore(*_a: Any, **_k: Any) -> None:
    return None


class _ReachedCatalog(Exception):
    """The adapter passed its row-rule gate and touched the catalog: the record was accepted."""


class _NoCatalogCon:
    def execute(self, sql: str, params: Any = None) -> _NoCatalogCon:
        raise _ReachedCatalog(sql)


@functools.lru_cache(maxsize=1)
def specs() -> dict[str, Any]:
    return load_specs()


def rules_of(table: str) -> RowRules:
    """The RowRules the adapter for *table* evaluates (the event spec's own, or the SCD2 spec's rules_for)."""
    if table in specs():
        return specs()[table].rules
    rules = rules_for(rt.resolve_table_spec(table))
    assert rules is not None, table
    return rules


@functools.lru_cache(maxsize=1)
def semantics() -> dict[str, Any]:
    return load_field_semantics()


def columns_of(table: str) -> dict[str, dict[str, Any]]:
    return semantics()["ops_tables"][table]["columns"]


def write_ops(table: str, record: dict[str, Any]) -> None:
    rt.write_scd2(FakeCon(created_lookup=None), dict(record), table=table, sleep=_ignore)


def update_ops(table: str, record: dict[str, Any]) -> None:
    prior = (datetime.now(timezone.utc),)
    rt.write_scd2(FakeCon(created_lookup=[prior]), dict(record), table=table, require_exists=True, sleep=_ignore)


def file_ops(table: str, record: dict[str, Any]) -> None:
    merge_key = rt.resolve_table_spec(table).merge_key
    rt.file_scd2(_NoCatalogCon(), {k: v for k, v in record.items() if k != merge_key}, table=table)


def register(table: str, record: dict[str, Any]) -> None:
    spec = rt.resolve_table_spec(table)
    inputs = {n for n, _ in spec.ordered_columns if spec.fields[n].get("role") == "input"}
    reg._write_dimension(
        _NoCatalogCon(),
        table,
        {k: v for k, v in record.items() if k in inputs},
        derived={k: v for k, v in record.items() if k not in inputs},
        identity=rt.mint_write_identity(),
        prior=None,
        semantics=semantics(),
    )


def append_telemetry(table: str, record: dict[str, Any]) -> None:
    present = {k: v for k, v in record.items() if v is not None}  # a null is expressed by omitting the key
    prepare_batch(specs()[table], [present], tenant_id=TENANT, project_id=PROJECT, now=NOW)


def outcome(adapter: Any, table: str, record: dict[str, Any]) -> tuple[str, str | None] | None:
    """(rule, column) of the refusal, or None when the adapter accepted the record."""
    try:
        adapter(table, record)
    except RowRuleViolationError as exc:
        return exc.rule, exc.column
    except RowRuleGateError as exc:
        return exc.rule, exc.column
    except GateError as exc:
        return str(exc.reason), exc.column
    except SchemaGateError as exc:
        return "schema_gate", str(exc)
    except _ReachedCatalog:
        return None
    return None


def _bad_text(pattern_ok: Any) -> str:
    for candidate in ("~", "~ NOT A MATCH ~", "!!", "/abs/path", "a\\b", "x" * 300, "\u00e9\u00fc"):
        if pattern_ok(candidate) is None:
            return candidate
    raise AssertionError("no candidate violates the pattern")


def matches(row: dict[str, Any], condition: Any) -> bool:
    return all(row.get(column) in allowed for column, allowed in condition.items())


def kind_columns(rules: RowRules) -> set[tuple[str, str]]:
    """Every (kind, column) the engine enforces for this table, derived from the RowRules fields."""
    out = {("not_null", c) for c in rules.not_null}
    for kind, mapping in (
        ("accepted_values", rules.accepted_values),
        ("min_length", rules.min_length),
        ("pattern", rules.patterns),
        ("pattern_when", rules.pattern_when),
        ("array_element_format", rules.element_formats),
        ("required_when", rules.required_when),
        ("not_before", rules.not_before),
        ("at_most", rules.at_most),
        ("null_or_zero_when", rules.null_or_zero_when),
        ("max_after_write_seconds", rules.max_after_write_seconds),
    ):
        out |= {(kind, column) for column in mapping}
    out |= {("exactly_one_of", group[0]) for group in rules.exactly_one_of}
    content = rules.content
    if content is not None:
        for leg, column in (
            ("integrity", content.inline),
            ("uri_above_threshold", content.uri),
            ("within_cap", content.uri),
        ):
            if leg not in rules.exemptions and (leg != "within_cap" or content.cap is not None):
                if leg != "integrity" or content.integrity:
                    out.add((leg, column))
    return out


def mutation(rules: RowRules, row: dict[str, Any], kind: str, column: str) -> dict[str, Any] | None:
    """*row* broken in exactly the rule (kind, column), or None when this scenario cannot exercise it."""
    out = dict(row)
    if kind == "not_null":
        out[column] = None
    elif kind == "accepted_values":
        out[column] = "zz-not-an-accepted-value"
    elif kind == "min_length":
        floor, pattern = rules.min_length[column], rules.patterns.get(column)
        shortest = ("x" * (floor - 1), " " * floor, "")
        out[column] = next(c for c in shortest if len(c.strip()) < floor and (pattern is None or pattern.fullmatch(c)))
    elif kind == "pattern":
        out[column] = _bad_text(rules.patterns[column].fullmatch)
    elif kind == "array_element_format":
        out[column] = ["~ bad element ~"]
    elif kind == "pattern_when":
        for condition, pattern in rules.pattern_when[column]:
            if matches(row, condition) and row.get(column) is not None:
                out[column] = _bad_text(pattern.fullmatch)
                return out
        return None
    elif kind == "required_when":
        if row.get(column) is None or not matches(row, rules.required_when[column]):
            return None
        out[column] = None
    elif kind == "null_or_zero_when":
        if not matches(row, rules.null_or_zero_when[column]):
            return None
        out[column] = 1
    elif kind == "not_before":
        other = rules.not_before[column]
        if row.get(column) is None or row.get(other) is None:
            return None
        out[column] = row[other] - timedelta(days=1)
    elif kind == "at_most":
        other = rules.at_most[column]
        if row.get(column) is None or row.get(other) is None:
            return None
        out[column] = row[other] + 1
    elif kind == "max_after_write_seconds":
        out[column] = NOW + timedelta(seconds=rules.max_after_write_seconds[column] + 60)
    elif kind == "exactly_one_of":
        group = next(g for g in rules.exactly_one_of if g[0] == column)
        if all(row.get(c) is None for c in group):
            return None
        for member in group:
            out[member] = None
    elif rules.content is not None and kind == "integrity":
        if row.get(rules.content.inline) is None:
            return None
        out[rules.content.sha] = "f" * 64
    elif rules.content is not None and kind in ("uri_above_threshold", "within_cap"):
        threshold, cap = rules.content.threshold, rules.content.cap
        out.update({rules.content.inline: None, rules.content.uri: "s3://placeholder/object"})
        out[rules.content.size] = threshold if kind == "uri_above_threshold" else (cap or threshold) + 1
        out[rules.content.sha] = _SHA
    else:
        raise AssertionError(f"no mutation for {kind} on {column}")
    return out
