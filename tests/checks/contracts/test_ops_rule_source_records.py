"""The recorded ops rule-source choice (rec-4158 plan A): Decision annotations, the write-time-enforcement statement, the
contract's own header, the lineage note and the re-grounded roadmap items. Decision numbers resolve from headers."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_DECISIONS = (_ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
_CONTRACTS = _ROOT / "docs" / "contracts"
_DECISION_CAP_BYTES = 6144


def _norm(text: str) -> str:
    return " ".join(re.sub(r"^>\s?", "", text, flags=re.MULTILINE).split()).lower()


def _section(number: int) -> str:
    marker = f"## Decision {number}:"
    assert _DECISIONS.count(marker) == 1, f"DECISIONS.md must carry exactly one header for Decision {number}"
    start = _DECISIONS.index(marker)
    end = _DECISIONS.find("\n## Decision ", start + 1)
    return _DECISIONS[start : end if end != -1 else len(_DECISIONS)]


def _standard_statement() -> str:
    standard = yaml.safe_load((_CONTRACTS / "data-modeling-standard.yaml").read_text(encoding="utf-8"))
    return next(rule for rule in standard["rules"] if rule["id"] == "write-time-enforcement")["statement"]


def test_decision_annotations() -> None:
    number = int(re.match(r"Decision (\d+):", _standard_statement().strip()).group(1))
    body = _section(number)
    assert len(body.encode("utf-8")) <= _DECISION_CAP_BYTES
    annotation = re.search(r"^\[Amendment \d{4}-\d{2}-\d{2}, rec-4158:.*?\]$", body, re.MULTILINE | re.DOTALL)
    assert annotation, f"Decision {number} must end with a dated [Amendment ..., rec-4158: ...] annotation"
    text = _norm(annotation.group(0))
    for anchor in (
        "class a contract",
        "ops_recommendations.yaml",
        "field_semantics.yaml",
        "repository_state",
        "no date moves later",
    ):
        assert anchor in text, anchor
    assert body.rstrip().endswith("---") and body.index(annotation.group(0)) > body.index("**Related:**")
    for decision, anchors in (
        (65, ("class a contract", "parity-checked copy", "rec-4158 plan c", "t1.6 c7", "t2.29 c7")),
        (64, ("2026-05-01", "floor", "rule-effective date", "never a moved anchor", "ratchet")),
    ):
        update = re.search(r"> \*\*Update \(2026-\d{2}-\d{2}\):\*\* \(rec-4158.*?(?:\n\n|\Z)", _section(decision), re.DOTALL)
        assert update, f"Decision {decision} must carry a dated rec-4158 update"
        for anchor in anchors:
            assert anchor in _norm(update.group(0)), (decision, anchor)


def test_standard_records_the_ops_source() -> None:
    statement = _norm(_standard_statement())
    assert "is rec-4158's" not in statement and "choice among" not in statement
    for phrase in (
        "owning class a contract",
        "field_semantics.yaml is its generated projection",
        "dq-side artefacts",
        "write_time_exemptions {class, reason, owner}",
        "class cross_row or temporary names its owning rec",
        "class repository_state",
        "older rows",
        "exclude_before",
        "decision 64 anchor 2026-05-01",
        "never a moved anchor",
        "a date never moves later",
        "validate_ops_rule_source",
        "rec-4158 plan b",
        "rec-4158 plan c",
        "rec-4167",
        "rec-4166",
        "decision 181 cl.2",
    ):
        assert phrase in statement, phrase


def test_ops_recommendations_names_one_authority() -> None:
    text = (_CONTRACTS / "ops_recommendations.yaml").read_text(encoding="utf-8")
    header = text.split("\ncontract:\n", 1)[0]
    assert "rec.py" not in header
    notes = yaml.safe_load(text)["governance_notes"]
    assert "rec.py" not in notes and "ONE declared source" in notes
    doc = yaml.safe_load(text)
    log = doc["amendment_log"]
    assert any(
        e["change_class"] == "accepted_values_narrow"
        and e["semantic_break"] is True
        and "PLAN-ops-rule-source" in e["summary"]
        for e in log
    )
    status = doc["fields"]["status"]
    assert "in_progress" not in status["description"] + status["semantics"] and "deferred" not in status["description"]
    assert any(e["change_class"] == "prose_improvement" and e["semantic_break"] is False for e in status["amendment_log"])
    assert "Null for cross-cutting" not in doc["fields"]["file"]["semantics"]
    assert "write_time" not in doc["fields"]["source"]["dq_intent_local"]["not_null"]


def test_roadmap_is_regrounded() -> None:
    roadmap = yaml.safe_load((_ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
    flat = yaml.safe_dump(roadmap, width=10_000)
    assert (
        "Amendment 2026-10-04, rec-4158, Decision 210 cl.3 -- schema and write-time rules live in the owning Class A" in flat
    )
    assert (
        "Amendment 2026-10-04, rec-4158 / Decision 210 cl.3 -- for the ops tables the owning Class A contract displaces"
        in flat
    )
    items = _items_by_id(roadmap)
    t16 = items["T1.6"]
    assert "Annotated metadata" not in t16["name"] and "declared rules" in t16["name"]
    assert "Class A contracts' declared rules" in t16["intent"]
    assert "Annotated" not in t16["decomposition_hints"]["atomic_plans"][2]
    c7 = next(c for c in t16["exit_criteria"] if c.startswith("[Deferred phase]"))
    assert "Annotated" not in c7 and "scripts/contract_rules.py" in c7
    t229 = items["T2.29"]
    assert "ops_recommendations Class A contract" in t229["intent"] and "validate_ops_rule_source" in t229["intent"]
    criteria = t229["exit_criteria"]
    assert any("exclude_before 2026-09-01" in c and "rec-4158" in c for c in criteria)
    assert any("_load_write_time_validators" in c and "rec-4158 plan C" in c and "Annotated" not in c for c in criteria)
    assert any(
        c.startswith("get_rec_write_guidance()") and "Class A contract (docs/contracts/ops_recommendations.yaml)" in c
        for c in criteria
    )


def _items_by_id(node, found=None) -> dict:
    found = {} if found is None else found
    if isinstance(node, dict):
        if isinstance(node.get("id"), str) and node.get("id") in ("T1.6", "T2.29") and "exit_criteria" in node:
            found[node["id"]] = node
        for value in node.values():
            _items_by_id(value, found)
    elif isinstance(node, list):
        for value in node:
            _items_by_id(value, found)
    return found


def test_source_lineage_note_matches() -> None:
    lineage = yaml.safe_load((_CONTRACTS / "source-lineage.yaml").read_text(encoding="utf-8"))
    note = _norm(lineage["fields"]["registry_key"]["governance_notes"])
    assert "write_time:true" not in note and 'not_null enforced:true + exclude_before:"2026-05-01"' in note
