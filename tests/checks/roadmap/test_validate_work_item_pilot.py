"""Mirror tests for scripts/checks/roadmap/validate_work_item_pilot.py and its model module -- the CD.45
work-item pilot fixture evaluator (PLAN-work-item-pilot-fixture-evaluator). Each leg has a red-before case
that fails on its own broken input; the model-driven budget case derives the worst-case item from
model_fields so a field added to any model grows the generated item and reddens the budget."""

from __future__ import annotations

import copy
import json
import types
import typing
from datetime import date

import pytest
import yaml
from annotated_types import MaxLen
from pydantic import BaseModel

from scripts.checks import _common, registry
from scripts.checks.roadmap import _manifest
from scripts.checks.roadmap import _work_item_pilot_model as model
from scripts.checks.roadmap.validate_work_item_pilot import validate_work_item_pilot
from scripts.checks.structural._classify import classify_path, effective_lines, longest_line

_LABEL = "Work-item pilot fixture"
_HEAD = "# test fixture comment\n"
_DECISIONS = "## Decision 197: Work-item boundary (Decided)\nbody\n"
_ROADMAP = {
    "candidate_decisions": [{"id": "CD.45", "state": "pending"}],
    "tier_items": [
        {"id": "T4.23", "exit_criteria": [{"id": "c6", "text": "target model", "status": "open"}]},
        {"id": "T3.3", "exit_criteria": ["a bare string criterion"]},
        {"id": "T9.1", "exit_criteria": [{"id": "c1", "text": "structured", "status": "open"}]},
    ],
}


def _reg(n):
    return {
        "why": "Capture turns so friction is observable without transcript reading.",
        "how": "Wire record_turn to the writer and derive metrics at read time.",
        "planes": ["data_plane"],
        "maturity": {
            "rung": "read_all",
            "transitions": [
                {"from": a, "to": b, "trigger": {"metric": "coverage ratio over window", "comparator": ">=", "threshold": 0.9}}
                for a, b in zip(model.RUNGS, model.RUNGS[1:])
            ],
        },
        "failure_signal": {
            "signal": f"capture rate drops for item {n}",
            "metric": f"capture_rate_{n}",
            "source": "ops reader",
        },
        "verification": ["c1"],
        "rollback": "Disable the producer wiring flag and fall back to manual review.",
        "evidence": [{"kind": "decision", "ref": "197"}],
        "settled": [{"id": "s1", "text": "Capture is data-plane only."}],
        "contested": [],
        "open_questions": [],
    }


def _item(n=1):
    ext = {"consideration_register": _reg(n)}
    return {"id": f"pwi-item-{n}", "kind": "epic", "title": "Capture producer wiring item", "extension": ext}


def _crit(n=1, cid="c1", method=None):
    method = method or {"kind": "execution", "check": "validate_placement"}
    return {
        "work_item": f"pwi-item-{n}",
        "criterion_id": cid,
        "text": "Capture rate is measured per turn.",
        "method": method,
        "status": "open",
    }


def _fixture(n_items=1, edges=(), **header):
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
    head.update(header)
    return {
        "fixture": head,
        "work_items": [_item(n) for n in range(1, n_items + 1)],
        "work_item_criteria": [_crit(n) for n in range(1, n_items + 1)],
        "work_item_edges": list(edges),
    }


def _reg_of(data, i=0):
    return data["work_items"][i]["extension"]["consideration_register"]


def _canon(data):
    return _HEAD + model.render(model.Fixture.model_validate(data))


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    def _run(data=None, *, text=None, roadmap=_ROADMAP, decisions=_DECISIONS, files=None, changed=(), today=None):
        data = _fixture() if data is None else data
        tree = {
            model.FIXTURE_PATH: text if text is not None else _canon(data),
            "docs/ROADMAP-PLATFORM.yaml": yaml.safe_dump(roadmap),
            "docs/DECISIONS.md": decisions,
            "docs/notes.md": "x\n" * 5,
            **(files or {}),
        }
        for rel, content in tree.items():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(content, encoding="utf-8")
        _common.run(["git", "init", "-q"], cwd=tmp_path)
        _common.run(["git", "add", "-A"], cwd=tmp_path)
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        monkeypatch.setattr(_common, "get_changed_files", lambda root=None: list(changed))
        registry.pop_declaration()
        failed: list[str] = []
        validate_work_item_pilot(failed, today=today)
        return failed, capsys.readouterr().out

    return _run


@pytest.fixture
def green(run):
    def _green(data=None, **kwargs):
        failed, out = run(data, **kwargs)
        assert failed == [], out

    return _green


@pytest.fixture
def red(run):
    def _red(needle, data=None, **kwargs):
        if "text" not in kwargs and data is not None:
            kwargs["text"] = yaml.safe_dump(data, sort_keys=False)
        failed, out = run(data, **kwargs)
        assert failed == [_LABEL], out
        assert needle in out, out

    return _red


class TestSkeleton:
    def test_empty_skeleton_passes_and_declares_examined(self, run):
        failed, out = run(_fixture(0))
        decl = registry.pop_declaration()
        assert failed == [] and out.count("PASS") == 6, out
        assert decl is not None and (decl.kind, decl.count, decl.unit) == ("examined", 1, "fixtures")

    def test_one_valid_item_passes(self, green):
        green()

    def test_absent_fixture_fails(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        failed: list[str] = []
        validate_work_item_pilot(failed)
        assert failed == [_LABEL] and "absent" in capsys.readouterr().out


def _mut(path, value=None, *, drop=False):
    def apply(d):
        target = _reg_of(d)
        *keys, last = path
        for key in keys:
            target = target[key]
        target.pop(last) if drop else target.__setitem__(last, value)

    return apply


def _second_item_shares(signal, metric):
    def apply(d):
        d["work_items"].append(_item(2))
        d["work_item_criteria"].append(_crit(2))
        _reg_of(d, 1)["failure_signal"].update(signal=signal, metric=metric)

    return apply


def _top(key, value):
    return lambda d: d["work_items"][0].__setitem__(key, value)


def _crit0(**changes):
    return lambda d: d["work_item_criteria"][0].update(**changes)


_PAD = " " * 10
_SCHEMA_CASES = {
    "unknown key": (_top("bogus", 1), "Extra inputs"),
    "kind plan": (_top("kind", "plan"), "epic"),
    "missing metric": (_mut(["failure_signal", "metric"], drop=True), "Field required"),
    "missing source": (_mut(["failure_signal", "source"], drop=True), "Field required"),
    "shared signal and metric": (
        _second_item_shares("capture rate drops for item 1", "capture_rate_1"),
        "shares its (failure",
    ),
    "shared pair folded": (_second_item_shares("  CAPTURE   rate drops for item 1", "Capture_Rate_1"), "shares its (failure"),
    "placeholder metric": (_mut(["failure_signal", "metric"], "TBD"), "placeholder token"),
    "under floor why": (_mut(["why"], "too short"), "at least 20 characters"),
    "padded under floor why": (_mut(["why"], _PAD + "short" + _PAD), "shorter than"),
    "over length why": (_mut(["why"], "a" * 241), "at most 240"),
    "over length metric": (_mut(["failure_signal", "metric"], "m" * 121), "at most 120"),
    "non ascii text": (_top("title", "Capture producer wiring caf\u00e9"), "printable ASCII"),
    "rec only evidence": (_mut(["evidence"], [{"kind": "rec", "ref": "rec-9999"}]), "CI-resolvable"),
    "verification names absent criterion": (_mut(["verification"], ["c1", "c2"]), "absent criterion 'c2'"),
    "duplicated verification id": (_mut(["verification"], ["c1", "c1"]), "verification ids must be unique"),
    "wrong transitions": (_mut(["maturity", "transitions"], _reg(1)["maturity"]["transitions"][::-1]), "adjacent rung pairs"),
    "duplicate planes": (_mut(["planes"], ["data_plane", "data_plane"]), "planes must be unique"),
    "duplicate row ids": (_mut(["contested"], [{"id": "s1", "text": "A contested point here."}]), "row ids must be unique"),
    "duplicate item": (lambda d: d["work_items"].append(copy.deepcopy(d["work_items"][0])), "duplicate work item id"),
    "duplicate criterion": (lambda d: d["work_item_criteria"].append(_crit()), "duplicate criterion"),
    "criterion names absent item": (_crit0(work_item="pwi-ghost"), "absent work item"),
    "too many criteria": (
        lambda d: d["work_item_criteria"].extend(_crit(1, f"c{i}") for i in range(2, 6)),
        "above MAX_CRITERIA",
    ),
    "unresolved_legacy method": (_crit0(method={"kind": "unresolved_legacy"}), "unresolved_legacy"),
    "review method without resolver": (
        _crit0(method={"kind": "review", "evidence_requirement": "A reviewer note."}),
        "Field required",
    ),
    "execution method with both arms": (_crit0(method={"kind": "execution", "check": "x", "command": "y"}), "exactly one of"),
}
_REVIEW = {"kind": "review", "resolver": "Operator reviews the report.", "evidence_requirement": "A signed review note."}


class TestSchema:
    @pytest.mark.parametrize("name", sorted(_SCHEMA_CASES))
    def test_broken_input_is_red(self, name, red):
        mutate, needle = _SCHEMA_CASES[name]
        data = _fixture()
        mutate(data)
        red(needle, data)

    def test_non_yaml_is_red(self, red):
        red("not valid YAML", text="a: [unclosed\n")

    def test_review_method_with_resolver_is_green(self, green):
        data = _fixture()
        _crit0(method=_REVIEW)(data)
        green(data)


class TestCap:
    def test_twelve_items_pass(self, green):
        green(_fixture(12))

    def test_thirteen_items_fail(self, red):
        red("ITEM_COUNT_CAP=12", _fixture(13), text=_canon(_fixture(13)))

    def test_per_item_line_ceiling(self, red, monkeypatch):
        monkeypatch.setattr(model, "PER_ITEM_LINE_CEILING", 5)
        monkeypatch.setattr(model, "HEADER_LINE_CEILING", 5)
        red("effective lines", _fixture(), text=_canon(_fixture()))

    def test_block_style_relayout_fails_render_equality(self, red):
        data = _fixture()
        red("canonical layout", data, text=_HEAD + yaml.safe_dump(data, default_flow_style=False, sort_keys=False))


_SECOND = f"{model.PILOT_DIR}/second.yaml"


class TestSingleInstance:
    @pytest.mark.parametrize(
        ("needle", "files", "decisions"),
        [
            ("second file", {_SECOND: "x: 1\n"}, _DECISIONS),
            ("column-0", {"config/other.yaml": "work_item_edges: []\n"}, _DECISIONS),
            ("second file", {_SECOND: "x: 1\n"}, _DECISIONS + f"## Decision 300: Rehome\n{_SECOND}\n"),
        ],
    )
    def test_second_fixture_is_red(self, needle, files, decisions, red):
        red(needle, files=files, decisions=decisions)

    def test_indented_key_is_not_a_second_fixture(self, green):
        green(files={"config/other.yaml": "a:\n  work_items: []\n"})

    def test_decision_naming_path_and_cd45_admits(self, green):
        green(files={_SECOND: "x: 1\n"}, decisions=_DECISIONS + f"## Decision 300: Rehome\nCD.45 moves to {_SECOND}\n")


def _edge(to, kind="depends_on"):
    return {"from": "pwi-item-1", "to": to, "kind": kind}


class TestEdges:
    def test_pilot_item_tier_item_and_cd_targets_pass(self, green):
        green(_fixture(2, edges=[_edge("pwi-item-2"), _edge("T4.23"), _edge("CD.45", "part_of")]))

    @pytest.mark.parametrize(
        ("target", "needle"),
        [("T4.23:c6", "criterion id"), ("T3.3:c1", "criterion id"), ("rec-4026", "rec id"), ("T9.99", "archived")],
    )
    def test_bad_target_is_red(self, target, needle, red):
        red(needle, _fixture(edges=[_edge(target)]))

    @pytest.mark.parametrize(
        ("edges", "needle"),
        [
            ([_edge("T4.23", "informs")], "depends_on"),
            ([_edge("pwi-item-1")], "self-edge"),
            ([_edge("T4.23"), _edge("T4.23")], "duplicate edge"),
        ],
    )
    def test_malformed_edges_are_red(self, edges, needle, red):
        red(needle, _fixture(edges=edges))

    def test_absent_roadmap_fails_closed(self, red):
        red("fail closed", _fixture(edges=[_edge("T4.23")]), roadmap={"tier_items": []})


_EVIDENCE_RED = {
    "unknown decision": ("decision", "999", "no '## Decision 999:' header"),
    "unregistered check": ("check", "no_such_check", "not a registered check"),
    "scaffold name": ("check", "lint", "not a registered check"),
    "file_line past end": ("file_line", "docs/notes.md:99", "past the end"),
    "file_line untracked": ("file_line", "docs/missing.md:1", "not a tracked file"),
    "file_line malformed": ("file_line", "docs/notes.md", "path:line"),
    "bare criterion": ("roadmap", "T3.3:c1", "bare-string"),
    "absent structured criterion": ("roadmap", "T4.23:c9", "no structured criterion"),
    "absent tier item": ("roadmap", "T9.99", "may have been archived"),
}
_EVIDENCE_GREEN = [
    ("decision", "197"),
    ("check", "validate_sloc_budget_raises"),
    ("file_line", "docs/notes.md:3"),
    ("roadmap", "T4.23:c6"),
    ("roadmap", "T9.1"),
    ("roadmap", "CD.45"),
]


def _evidence(*rows):
    data = _fixture()
    _reg_of(data)["evidence"] = [{"kind": k, "ref": r} for k, r in rows]
    return data


class TestEvidence:
    @pytest.mark.parametrize("name", sorted(_EVIDENCE_RED))
    def test_unresolvable_ref_is_red(self, name, red):
        kind, ref, needle = _EVIDENCE_RED[name]
        red(needle, _evidence((kind, ref)))

    @pytest.mark.parametrize(("kind", "ref"), _EVIDENCE_GREEN)
    def test_resolvable_ref_is_green(self, kind, ref, green):
        green(_evidence((kind, ref)))

    def test_rec_ref_is_format_checked_beside_an_anchor(self, green, red):
        green(_evidence(("decision", "197"), ("rec", "rec-12")))
        red("rec-NNNN", _evidence(("decision", "197"), ("rec", "rec-abc")))

    def test_execution_check_must_be_registered(self, red):
        data = _fixture()
        _crit0(method={"kind": "execution", "check": "lint"})(data)
        red("method check 'lint'", data)


def _moved(first_of_index, key, value):
    data = _fixture(0)
    data["fixture"]["sunset"]["first_of"][first_of_index][key] = value
    return data


class TestHeader:
    @pytest.mark.parametrize(
        ("data", "needle"),
        [
            (_fixture(0, item_count_cap=13), "item_count_cap 13"),
            (_moved(1, "review_on", "2027-02-28"), "review_on '2027-02-28'"),
            (_moved(0, "criterion_met", "T4.23:c7"), "criterion_met 'T4.23:c7'"),
        ],
    )
    def test_header_differing_from_code_is_red(self, data, needle, red):
        red(needle, data, text=_canon(data))


_TOUCHED = [model.FIXTURE_PATH]
_AFTER = date(2027, 2, 1)


def _roadmap(c6="open", cd_state="pending", drop=()):
    doc = copy.deepcopy(_ROADMAP)
    doc["tier_items"][0]["exit_criteria"][0]["status"] = c6
    doc["candidate_decisions"][0]["state"] = cd_state
    doc["candidate_decisions"] = [] if "cd" in drop else doc["candidate_decisions"]
    doc["tier_items"] = doc["tier_items"][1:] if "t423" in drop else doc["tier_items"]
    doc["tier_items"][0]["exit_criteria"] = [] if "c6" in drop else doc["tier_items"][0]["exit_criteria"]
    return doc


_RESTRUCTURE = _DECISIONS + f"## Decision 301: Restructure\nCD.45 fixture now lives under {model.PILOT_DIR}/\n"


class TestSunset:
    def test_day_before_review_touched_passes(self, green):
        green(changed=_TOUCHED, today=date(2027, 1, 30))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"changed": _TOUCHED, "today": date(2027, 1, 31)},
            {"changed": _TOUCHED, "today": date(2026, 10, 1), "roadmap": _roadmap(c6="met")},
            {"changed": [f"{model.PILOT_DIR}/other.txt"], "today": _AFTER},
            {
                "changed": _TOUCHED,
                "today": _AFTER,
                "decisions": _DECISIONS + f"## Decision 301: Other\n{model.PILOT_DIR}/ only\n",
            },
        ],
    )
    def test_triggered_and_touched_is_frozen(self, kwargs, red):
        red("write-frozen", **kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [{"roadmap": _roadmap(cd_state="ratified")}, {"decisions": _RESTRUCTURE}],
    )
    def test_operator_only_exits_release_the_freeze(self, kwargs, green):
        green(changed=_TOUCHED, today=_AFTER, **kwargs)

    def test_triggered_untouched_passes_declared_with_report(self, run):
        failed, out = run(changed=["docs/notes.md"], today=_AFTER)
        decl = registry.pop_declaration()
        assert failed == [] and "SUNSET REACHED" in out
        assert decl is not None and decl.count == 1

    @pytest.mark.parametrize("drop", [("cd",), ("t423",), ("c6",)])
    def test_archived_anchor_fails_closed(self, drop, red):
        red("fail closed", roadmap=_roadmap(drop=drop))


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

    def test_frozen_vocabularies_match_their_literals(self):
        assert model.EDGE_KINDS == ("depends_on", "part_of")
        assert model.RUNGS == ("read_all", "sampled", "spot_check", "anomaly_triggered")


class TestRegistration:
    def test_manifest_entry_is_ungated_in_pre_and_full(self):
        entry = next(e for e in _manifest.ENTRIES if e.name == "validate_work_item_pilot")
        assert entry.pre is True and entry.pre_globs is None and entry.full_segment == "full_after_lint"
        assert entry.module == "scripts.checks.roadmap.validate_work_item_pilot" and entry.attr == "validate_work_item_pilot"
        assert "validate_work_item_pilot" in [s.name for s in registry.pre_sequence()]
        assert "validate_work_item_pilot" in [s.name for s in registry.full_sequence()]
        assert registry.resolve("validate_work_item_pilot") is validate_work_item_pilot

    def test_taxonomy_row_is_schema_drift(self):
        table = yaml.safe_load((_common.ROOT / "config/ci_rca_taxonomy.yaml").read_text(encoding="utf-8"))[
            "function_to_category"
        ]
        assert table["validate_work_item_pilot"] == "schema_drift"


class TestShippedFixture:
    def test_shipped_fixture_passes_every_leg_and_classifies_residual(self, capsys):
        failed: list[str] = []
        registry.pop_declaration()
        validate_work_item_pilot(failed)
        decl = registry.pop_declaration()
        assert failed == [], capsys.readouterr().out
        assert decl is not None and decl.count == 1
        assert classify_path(model.FIXTURE_PATH) == "residual"
