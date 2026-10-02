"""Mirror tests for scripts/checks/roadmap/_work_item_pilot_model.py -- the CD.45 pilot fixture models, frozen caps
and canonical renderer (PLAN-work-item-pilot-fixture-evaluator). Each validator has a red-before case; the
model-driven budget case derives the worst-case item from model_fields, so a field added to any model grows the
generated item and reddens the budget."""

from __future__ import annotations

import copy
import json
import types
import typing

import pytest
import yaml
from annotated_types import MaxLen
from pydantic import BaseModel, ValidationError

from scripts.checks import _common
from scripts.checks.roadmap import _work_item_pilot_model as model
from scripts.checks.structural._classify import effective_lines, longest_line


def _transitions():
    trigger = {"metric": "coverage ratio over window", "comparator": ">=", "threshold": 0.9}
    return [{"from": a, "to": b, "trigger": dict(trigger)} for a, b in zip(model.RUNGS, model.RUNGS[1:])]


def _reg():
    return {
        "why": "Capture turns so friction is observable without transcript reading.",
        "how": "Wire record_turn to the writer and derive metrics at read time.",
        "planes": ["data_plane"],
        "maturity": {"rung": "read_all", "transitions": _transitions()},
        "failure_signal": {"signal": "capture rate drops for the item", "metric": "capture_rate", "source": "ops reader"},
        "verification": ["c1"],
        "rollback": "Disable the producer wiring flag and fall back to manual review.",
        "evidence": [{"kind": "decision", "ref": "197"}],
        "settled": [{"id": "s1", "text": "Capture is data-plane only."}],
        "contested": [],
        "open_questions": [],
    }


def _fixture(n_items=1):
    head = {
        "id": "telemetry-feedback-loop",
        "status": "provisional_v0",
        "authority": "CD.45",
        "grain": "decision-197-clause-3",
        "item_count_cap": model.ITEM_COUNT_CAP,
        "sunset": {
            "first_of": [{"criterion_met": model.SUNSET_CRITERION}, {"review_on": model.SUNSET_REVIEW_DATE.isoformat()}],
            "outcome": "lift rows into the store, or restructure per the operator's review; never delete",
        },
        "edges_disposition": "pilot_only -- re-authored by the implementation merge on lift, never lifted as-is",
    }
    item = {
        "id": "pwi-item-1",
        "kind": "epic",
        "title": "Capture producer wiring item",
        "extension": {"consideration_register": _reg()},
    }
    crit = {
        "work_item": "pwi-item-1",
        "criterion_id": "c1",
        "text": "Capture rate is measured per turn.",
        "method": {"kind": "execution", "check": "validate_placement"},
        "status": "open",
    }
    return {
        "fixture": head,
        "work_items": [item] * n_items,
        "work_item_criteria": [crit] * n_items,
        "work_item_edges": [],
    }


def _reg_of(data):
    return data["work_items"][0]["extension"]["consideration_register"]


def _set(path, value=None, *, drop=False):
    def apply(d):
        target = _reg_of(d)
        *keys, last = path
        for key in keys:
            target = target[key]
        target.pop(last) if drop else target.__setitem__(last, value)

    return apply


def _crit0(**changes):
    return lambda d: d["work_item_criteria"][0].update(**changes)


_PAD = " " * 10
_ROW = {"id": "s1", "text": "A contested point here."}
_REVIEW = {"kind": "review", "evidence_requirement": "A reviewer note."}
_CASES = {
    "unknown key": (lambda d: d["work_items"][0].__setitem__("bogus", 1), "Extra inputs"),
    "kind plan": (lambda d: d["work_items"][0].__setitem__("kind", "plan"), "epic"),
    "missing metric": (_set(["failure_signal", "metric"], drop=True), "Field required"),
    "missing source": (_set(["failure_signal", "source"], drop=True), "Field required"),
    "placeholder metric": (_set(["failure_signal", "metric"], "TBD"), "placeholder token"),
    "under floor why": (_set(["why"], "too short"), "at least 20 characters"),
    "padded under floor why": (_set(["why"], _PAD + "short" + _PAD), "shorter than"),
    "over length why": (_set(["why"], "a" * 241), "at most 240"),
    "over length metric": (_set(["failure_signal", "metric"], "m" * 121), "at most 120"),
    "non ascii text": (lambda d: d["work_items"][0].__setitem__("title", "Capture producer wiring café"), "printable ASCII"),
    "blank ref": (_set(["evidence"], [{"kind": "decision", "ref": " "}]), "must not be blank"),
    "rec only evidence": (_set(["evidence"], [{"kind": "rec", "ref": "rec-9999"}]), "CI-resolvable"),
    "duplicated verification id": (_set(["verification"], ["c1", "c1"]), "verification ids must be unique"),
    "wrong transitions": (_set(["maturity", "transitions"], _transitions()[::-1]), "adjacent rung pairs"),
    "non finite threshold": (_set(["maturity", "transitions", 0, "trigger", "threshold"], float("inf")), "must be finite"),
    "duplicate planes": (_set(["planes"], ["data_plane", "data_plane"]), "planes must be unique"),
    "duplicate row ids": (_set(["contested"], [_ROW]), "row ids must be unique"),
    "unresolved_legacy method": (_crit0(method={"kind": "unresolved_legacy"}), "unresolved_legacy"),
    "review method without resolver": (_crit0(method=_REVIEW), "Field required"),
    "execution method with both arms": (_crit0(method={"kind": "execution", "check": "x", "command": "y"}), "exactly one of"),
    "edge kind outside the vocabulary": (
        lambda d: d["work_item_edges"].append({"from": "pwi-item-1", "to": "T4.23", "kind": "informs"}),
        "depends_on",
    ),
}


class TestModel:
    @pytest.mark.parametrize("name", sorted(_CASES))
    def test_broken_input_is_rejected(self, name):
        mutate, needle = _CASES[name]
        data = _fixture()
        mutate(data)
        with pytest.raises(ValidationError, match=needle):
            model.Fixture.model_validate(data)

    def test_valid_review_and_command_methods_are_accepted(self):
        data = _fixture()
        _crit0(method={**_REVIEW, "resolver": "Operator reviews the report."})(data)
        model.Fixture.model_validate(data)
        _crit0(method={"kind": "execution", "command": "true"})(data)
        model.Fixture.model_validate(data)

    def test_render_of_empty_and_sparse_fixtures_is_canonical_and_round_trips(self):
        for data in (_fixture(0), _fixture()):
            fixture = model.Fixture.model_validate(data)
            rendered = model.render(fixture)
            assert yaml.safe_load(rendered) == fixture.model_dump(by_alias=True, mode="json")
        assert "contested: []" in rendered and "work_item_edges: []" in rendered

    def test_frozen_vocabularies_match_their_literals(self):
        assert model.EDGE_KINDS == ("depends_on", "part_of")
        assert model.RUNGS == ("read_all", "sampled", "spot_check", "anomaly_triggered")


def _max_len(meta):
    return next((m.max_length for m in meta if getattr(m, "max_length", None) is not None), None)


def _pattern(meta):
    return next((m.pattern for m in meta if getattr(m, "pattern", None)), None)


_PATTERN_SAMPLES = {
    r"^pwi-[a-z0-9-]+$": lambda n, i: "pwi-" + "a" * (n - 4),
    r"^c[0-9]+$": lambda n, i: f"c{i + 1}",
    r"^[skq][0-9]+$": lambda n, i: f"s{i + 1}",
    r"^[A-Za-z0-9._:-]+$": lambda n, i: "a" * n,
}
_ROW_PREFIX = {"settled": "s", "contested": "k", "open_questions": "q"}


def _worst(tp, meta=(), name="", index=0):
    """The longest valid value for a type, derived from model_fields: raises on any unbounded str or list."""
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        return _worst(typing.get_args(tp)[0], (*meta, *typing.get_args(tp)[1:]), name, index)
    if origin in (typing.Union, types.UnionType):
        arms = [a for a in typing.get_args(tp) if a is not type(None)]
        return max((_worst(a, meta, name, index) for a in arms), key=lambda v: len(json.dumps(v)))
    if origin is typing.Literal:
        return max(typing.get_args(tp), key=lambda v: len(str(v)))
    if origin is list:
        (elem,) = typing.get_args(tp)
        cap = _max_len(meta)
        assert cap is not None, f"unbounded list field {name!r}"
        if typing.get_origin(elem) is typing.Literal:
            return list(typing.get_args(elem))[:cap]
        rows = [_worst(elem, (), name, i) for i in range(cap)]
        for i, row in enumerate(rows):
            if name in _ROW_PREFIX:
                row["id"] = f"{_ROW_PREFIX[name]}{i + 1}"
        return rows
    if tp is str:
        cap = _max_len(meta)
        assert cap is not None, f"unbounded str field {name!r}"
        pattern = _pattern(meta)
        if pattern is None:
            return "a" * cap
        assert pattern in _PATTERN_SAMPLES, f"no sample for pattern {pattern!r} on {name!r}"
        return _PATTERN_SAMPLES[pattern](cap, index)
    if tp is int or tp is float:
        return -1.2345678901234567e-300
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return _worst_model(tp, index)
    raise AssertionError(f"unhandled annotation {tp!r} on {name!r}")


def _worst_model(cls, index=0):
    out = {}
    for fname, info in cls.model_fields.items():
        out[info.alias or fname] = _worst(info.annotation, tuple(info.metadata), fname, index)
    if cls is model.Maturity:
        pairs = list(zip(model.RUNGS, model.RUNGS[1:]))
        for row, (a, b) in zip(out["transitions"], pairs):
            row["from"], row["to"] = a, b
    if cls is model.ExecutionMethod:
        out["command"] = None
    return out


def _worst_item_fixture():
    item = _worst_model(model.WorkItem)
    crits = [_worst_model(model.Criterion, i) for i in range(model.MAX_CRITERIA_PER_ITEM)]
    edges = [_worst_model(model.Edge, i) for i in range(model.MAX_EDGES_FROM_ITEM)]
    for crit in crits:
        crit["work_item"] = item["id"]
    for edge in edges:
        edge["from"] = item["id"]
    # the exactly-one-of validator rejects both arms at once: build once with check, once with command, keep the longer
    with_command = copy.deepcopy(crits[0])
    with_command["method"] = {"kind": "execution", "command": "c" * 200}
    if len(json.dumps(with_command["method"])) > len(json.dumps(crits[0]["method"])):
        crits = [{**c, "method": with_command["method"]} for c in crits]
    base = _fixture(0)
    base.update(work_items=[item], work_item_criteria=crits, work_item_edges=edges)
    return base


class TestBudget:
    def test_worst_case_item_round_trips_and_fits_the_ceiling(self):
        data = _worst_item_fixture()
        fixture = model.Fixture.model_validate(data)
        rendered = model.render(fixture)
        assert yaml.safe_load(rendered) == fixture.model_dump(by_alias=True, mode="json")
        header = effective_lines(model.render(model.Fixture.model_validate(_fixture(0))))
        assert effective_lines(rendered) - header <= model.PER_ITEM_LINE_CEILING
        assert longest_line(rendered) <= model.MAX_LONG_LINE
        assert "failure_signal: {signal: " in rendered and "- {id: s1, text: " in rendered and "- {from: " in rendered

    def test_ceilings_reconcile_with_the_residual_limit(self):
        shipped = (_common.ROOT / model.FIXTURE_PATH).read_text(encoding="utf-8")
        assert model.HEADER_LINE_CEILING + model.ITEM_COUNT_CAP * model.PER_ITEM_LINE_CEILING <= 500
        assert effective_lines(shipped) <= model.HEADER_LINE_CEILING

    def test_generator_raises_on_an_unbounded_field(self):
        class Unbounded(BaseModel):
            text: str

        with pytest.raises(AssertionError, match="unbounded str"):
            _worst_model(Unbounded)

    def test_generator_grows_with_a_new_bounded_field(self):
        class Wider(BaseModel):
            extra: typing.Annotated[str, MaxLen(7)]

        assert _worst_model(Wider) == {"extra": "a" * 7}
