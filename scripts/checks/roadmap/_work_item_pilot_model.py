"""Schema, frozen caps and canonical renderer for the CD.45 work-item pilot fixture.

The one fixture (docs/work-item-pilot/telemetry-feedback-loop.yaml) is a provisional_v0 pilot in
the Decision 197 clause-3 grain; its consideration register is the clause-4 per-item extension
block. Everything an evaluator needs to be deterministic is held HERE in code: the Pydantic
extra=forbid models, the item-count cap, the line ceilings the cap is derived from, the sunset
terms, the edge vocabulary and the maturity rungs. The fixture header repeats cap and sunset only
so validate_work_item_pilot can assert header == code. render() is the one canonical-layout
renderer: the evaluator's byte-equality leg and the budget test both call it, so the line budget
is a mechanical consequence of the models, not a hand-maintained estimate.

No file I/O at import (AGENTS.md safety).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal, Union, get_args

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StringConstraints, model_validator

PILOT_DIR = "docs/work-item-pilot"
FIXTURE_PATH = f"{PILOT_DIR}/telemetry-feedback-loop.yaml"

ITEM_COUNT_CAP = 12
HEADER_LINE_CEILING = 20
PER_ITEM_LINE_CEILING = 40
MAX_CRITERIA_PER_ITEM = 3
MAX_EDGES_FROM_ITEM = 3
MAX_EVIDENCE = 4
MAX_ROWS = 3
MAX_LONG_LINE = 2000
# Hard sanity bounds on the three top-level lists; the item-count cap proper is leg L2's.
MAX_ITEMS_HARD = 64
MAX_CRITERIA_HARD = MAX_ITEMS_HARD * MAX_CRITERIA_PER_ITEM
MAX_EDGES_HARD = MAX_ITEMS_HARD * MAX_EDGES_FROM_ITEM

SUNSET_CRITERION = "T4.23:c6"
SUNSET_REVIEW_DATE = date(2027, 1, 31)
SUNSET_CD = "CD.45"

EdgeKind = Literal["depends_on", "part_of"]
EDGE_KINDS: tuple[str, ...] = get_args(EdgeKind)
Rung = Literal["read_all", "sampled", "spot_check", "anomaly_triggered"]
RUNGS: tuple[str, ...] = get_args(Rung)
Plane = Literal["data_plane", "control_plane"]
EvidenceKind = Literal["file_line", "check", "decision", "roadmap", "rec"]
CI_RESOLVABLE_KINDS = frozenset({"file_line", "check", "decision", "roadmap"})
PLACEHOLDER_TOKENS = frozenset({"tbd", "todo", "n/a", "na", "tba", "xxx", "placeholder", "none", "-"})

_PRINTABLE_ASCII = re.compile(r"[\x20-\x7e]*")


def _ascii(value: str) -> str:
    if not _PRINTABLE_ASCII.fullmatch(value):
        raise ValueError("printable ASCII only (AGENTS.md ASCII rule)")
    return value


def _ident_check(value: str) -> str:
    _ascii(value)
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _free_text_check(floor: int) -> Callable[[str], str]:
    def _check(value: str) -> str:
        _ascii(value)
        stripped = value.strip()
        if len(stripped) < floor:
            raise ValueError(f"shorter than the {floor}-character floor after stripping")
        if stripped.casefold() in PLACEHOLDER_TOKENS:
            raise ValueError("placeholder token")
        return value

    return _check


def _text(lo: int, hi: int, pattern: str | None = None) -> StringConstraints:
    return StringConstraints(min_length=lo, max_length=hi, pattern=pattern)


Number = Union[StrictInt, StrictFloat]
ItemId = Annotated[str, _text(1, 64, r"^pwi-[a-z0-9-]+$"), AfterValidator(_ident_check)]
CriterionId = Annotated[str, _text(1, 8, r"^c[0-9]+$"), AfterValidator(_ident_check)]
RowId = Annotated[str, _text(1, 8, r"^[skq][0-9]+$"), AfterValidator(_ident_check)]
TargetId = Annotated[str, _text(1, 64, r"^[A-Za-z0-9._:-]+$"), AfterValidator(_ident_check)]
DateText = Annotated[str, _text(1, 10, r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), AfterValidator(_ident_check)]
Ident16 = Annotated[str, _text(1, 16), AfterValidator(_ident_check)]
Ident64 = Annotated[str, _text(1, 64), AfterValidator(_ident_check)]
Ident200 = Annotated[str, _text(1, 200), AfterValidator(_ident_check)]
Command = Ident200
Text20_240 = Annotated[str, _text(20, 240), AfterValidator(_free_text_check(20))]
Text10_160 = Annotated[str, _text(10, 160), AfterValidator(_free_text_check(10))]
Text10_120 = Annotated[str, _text(10, 120), AfterValidator(_free_text_check(10))]
Text3_120 = Annotated[str, _text(3, 120), AfterValidator(_free_text_check(3))]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FirstOfCriterion(_Strict):
    criterion_met: Ident16


class FirstOfReview(_Strict):
    review_on: DateText


class Sunset(_Strict):
    first_of: tuple[FirstOfCriterion, FirstOfReview]
    outcome: Text20_240


class FixtureHeader(_Strict):
    id: Ident64
    status: Literal["provisional_v0"]
    authority: Literal["CD.45"]
    grain: Literal["decision-197-clause-3"]
    item_count_cap: StrictInt
    sunset: Sunset
    edges_disposition: Text20_240


class Trigger(_Strict):
    metric: Text3_120
    comparator: Literal[">=", "<=", "==", ">", "<"]
    threshold: Number

    @model_validator(mode="after")
    def _finite(self) -> "Trigger":
        if isinstance(self.threshold, float) and not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")
        return self


class Transition(_Strict):
    from_: Rung = Field(alias="from")
    to: Rung
    trigger: Trigger


class Maturity(_Strict):
    rung: Rung
    transitions: Annotated[list[Transition], Field(min_length=len(RUNGS) - 1, max_length=len(RUNGS) - 1)]

    @model_validator(mode="after")
    def _adjacent_pairs(self) -> "Maturity":
        pairs = [(t.from_, t.to) for t in self.transitions]
        expected = list(zip(RUNGS, RUNGS[1:]))
        if pairs != expected:
            raise ValueError(f"transitions must be exactly the adjacent rung pairs in order: {expected}")
        return self


class FailureSignal(_Strict):
    signal: Text10_160
    metric: Text3_120
    source: Text3_120


class Evidence(_Strict):
    kind: EvidenceKind
    ref: Ident200


class Row(_Strict):
    id: RowId
    text: Text10_160


class ConsiderationRegister(_Strict):
    why: Text20_240
    how: Text20_240
    planes: Annotated[list[Plane], Field(min_length=1, max_length=len(get_args(Plane)))]
    maturity: Maturity
    failure_signal: FailureSignal
    verification: Annotated[list[CriterionId], Field(min_length=1, max_length=MAX_CRITERIA_PER_ITEM)]
    rollback: Text20_240
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=MAX_EVIDENCE)]
    settled: Annotated[list[Row], Field(min_length=1, max_length=MAX_ROWS)]
    contested: Annotated[list[Row], Field(min_length=0, max_length=MAX_ROWS)]
    open_questions: Annotated[list[Row], Field(min_length=0, max_length=MAX_ROWS)]

    @model_validator(mode="after")
    def _register_invariants(self) -> "ConsiderationRegister":
        if len(set(self.planes)) != len(self.planes):
            raise ValueError("planes must be unique")
        if len(set(self.verification)) != len(self.verification):
            raise ValueError("verification ids must be unique")
        if not any(e.kind in CI_RESOLVABLE_KINDS for e in self.evidence):
            raise ValueError(
                f"evidence needs at least one CI-resolvable anchor (kind in {sorted(CI_RESOLVABLE_KINDS)}); "
                "a rec ref is format-checked only and never counts"
            )
        row_ids = [r.id for r in (*self.settled, *self.contested, *self.open_questions)]
        if len(set(row_ids)) != len(row_ids):
            raise ValueError("row ids must be unique across settled, contested and open_questions")
        return self


class Extension(_Strict):
    consideration_register: ConsiderationRegister


class WorkItem(_Strict):
    id: ItemId
    kind: Literal["epic", "task"]
    title: Text10_120
    extension: Extension


class ExecutionMethod(_Strict):
    kind: Literal["execution"]
    check: Ident64 | None = None
    command: Command | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ExecutionMethod":
        if (self.check is None) == (self.command is None):
            raise ValueError("execution method needs exactly one of check or command")
        return self


class ReviewMethod(_Strict):
    kind: Literal["review"]
    resolver: Text10_160
    evidence_requirement: Text10_160


Method = Annotated[Union[ExecutionMethod, ReviewMethod], Field(discriminator="kind")]


class Criterion(_Strict):
    work_item: ItemId
    criterion_id: CriterionId
    text: Text20_240
    method: Method
    status: Literal["open", "met"]


class Edge(_Strict):
    from_: ItemId = Field(alias="from")
    to: TargetId
    kind: EdgeKind


class Fixture(_Strict):
    fixture: FixtureHeader
    work_items: Annotated[list[WorkItem], Field(max_length=MAX_ITEMS_HARD)]
    work_item_criteria: Annotated[list[Criterion], Field(max_length=MAX_CRITERIA_HARD)]
    work_item_edges: Annotated[list[Edge], Field(max_length=MAX_EDGES_HARD)]


# --- canonical renderer ---------------------------------------------------------------------


def _scalar(value: object) -> str:
    out = yaml.safe_dump(value, default_flow_style=True, width=float("inf"), allow_unicode=False, sort_keys=False)
    return out.removesuffix("...\n").rstrip("\n")


def _flow(value: object) -> str:
    return _scalar(value)


def _block_rows(indent: str, key: str, rows: list) -> list[str]:
    if not rows:
        return [f"{indent}{key}: []"]
    return [f"{indent}{key}:", *(f"{indent}  - {_flow(row)}" for row in rows)]


def _render_register(reg: dict, ind: str) -> list[str]:
    maturity = reg["maturity"]
    lines = [
        f"{ind}why: {_scalar(reg['why'])}",
        f"{ind}how: {_scalar(reg['how'])}",
        f"{ind}planes: {_flow(reg['planes'])}",
        f"{ind}maturity:",
        f"{ind}  rung: {_scalar(maturity['rung'])}",
        *_block_rows(f"{ind}  ", "transitions", maturity["transitions"]),
        f"{ind}failure_signal: {_flow(reg['failure_signal'])}",
        f"{ind}verification: {_flow(reg['verification'])}",
        f"{ind}rollback: {_scalar(reg['rollback'])}",
    ]
    for key in ("evidence", "settled", "contested", "open_questions"):
        lines.extend(_block_rows(ind, key, reg[key]))
    return lines


def _render_item(item: dict) -> list[str]:
    reg = item["extension"]["consideration_register"]
    return [
        f"  - id: {_scalar(item['id'])}",
        f"    kind: {_scalar(item['kind'])}",
        f"    title: {_scalar(item['title'])}",
        "    extension:",
        "      consideration_register:",
        *_render_register(reg, "        "),
    ]


def render(fixture: Fixture) -> str:
    """The pinned canonical layout. Header, each work item, its extension, consideration_register
    and maturity are block mappings; failure_signal, planes and verification are one flow line
    each; every row of transitions, evidence, settled, contested, open_questions,
    work_item_criteria and work_item_edges is one flow line; sunset.first_of is one flow line;
    empty lists are []. Scalars are emitted by PyYAML (width=inf, so none fold)."""
    data = fixture.model_dump(by_alias=True, mode="json")
    head = data["fixture"]
    lines = [
        "fixture:",
        f"  id: {_scalar(head['id'])}",
        f"  status: {_scalar(head['status'])}",
        f"  authority: {_scalar(head['authority'])}",
        f"  grain: {_scalar(head['grain'])}",
        f"  item_count_cap: {_scalar(head['item_count_cap'])}",
        "  sunset:",
        f"    first_of: {_flow(head['sunset']['first_of'])}",
        f"    outcome: {_scalar(head['sunset']['outcome'])}",
        f"  edges_disposition: {_scalar(head['edges_disposition'])}",
    ]
    if data["work_items"]:
        lines.append("work_items:")
        for item in data["work_items"]:
            lines.extend(_render_item(item))
    else:
        lines.append("work_items: []")
    for key in ("work_item_criteria", "work_item_edges"):
        lines.extend(_block_rows("", key, data[key]))
    return "\n".join(lines) + "\n"
