"""Live-rewrite evidence for the Decision 204 partition-layout remediation (rec-4070,
PLAN-ducklake-partition-layout-remediation step 24).

Reads ONLY the committed fixture tests/fixtures/partition_rewrite_evidence.json, never the live
projection, so a later plan registering a new history table cannot redden it. The rules live in
evidence_violations so each one can be shown to fail on a mutated copy of the fixture.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "partition_rewrite_evidence.json"

_NAMED_HISTORY_TABLES = frozenset(
    {
        "ops_recommendations_history",
        "ops_decisions_history",
        "ops_priority_queue_history",
        "ops_execution_plans_history",
        "ops_smoke_events_history",
    }
)
_PROOF_FIELDS = ("pre_snapshot_id", "commit_snapshot_id", "rows_pre", "rows_commit", "digest_pre", "digest_commit")
_GAP_FIELDS = ("table", "reason", "confirming_human")
_STATS_SECTIONS = ("catalog_stats_before", "catalog_stats_after")


def _readout_tables(readout: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = dict(readout.get("layouts", {}))
    for entry in readout.get("skipped", []):
        tables[entry["table"]] = entry["layout"]
    return tables


def _has_full_proof(entry: dict[str, Any]) -> bool:
    if any(entry.get(field) in (None, "") for field in _PROOF_FIELDS):
        return False
    return (
        entry["rows_pre"] == entry["rows_commit"]
        and entry["digest_pre"] == entry["digest_commit"]
        and entry["pre_snapshot_id"] < entry["commit_snapshot_id"]
    )


def _is_gap_record(entry: dict[str, Any]) -> bool:
    gap = entry.get("human_adjudicated_gap")
    if not isinstance(gap, dict):
        return False
    if not all(isinstance(gap.get(field), str) and gap[field].strip() for field in _GAP_FIELDS):
        return False
    return gap["table"] == entry.get("physical")


def evidence_violations(fixture: dict[str, Any]) -> list[str]:
    problems: list[str] = []

    after = fixture.get("reconcile_after_rewrite") or {}
    after_tables = _readout_tables(after)
    missing_named = sorted(_NAMED_HISTORY_TABLES - set(after_tables))
    if missing_named:
        problems.append(f"post-rewrite readout omits named history tables: {missing_named}")
    if after.get("drifts"):
        problems.append(f"post-rewrite readout still reports drift: {after['drifts']}")
    for name, layout in sorted(after_tables.items()):
        if layout.get("legacy_scheme_files") != 0:
            problems.append(f"post-rewrite readout: {name} still has legacy_scheme_files={layout.get('legacy_scheme_files')}")
    for skipped in after.get("skipped", []):
        if skipped.get("drift") is not None:
            problems.append(f"post-rewrite readout: skipped table {skipped.get('table')} reports drift")

    alter = fixture.get("alter_apply") or {}
    legacy_after_alter = {
        name for name, layout in alter.get("layouts", {}).items() if (layout.get("legacy_scheme_files") or 0) > 0
    }
    entries = fixture.get("rewrites") or []
    entry_tables = [entry.get("physical") for entry in entries]
    if len(entry_tables) != len(set(entry_tables)):
        problems.append(f"duplicate rewrite entries: {entry_tables}")
    if set(entry_tables) != legacy_after_alter:
        problems.append(
            "rewrite entries differ from the tables with legacy files after the ALTER: "
            f"missing={sorted(legacy_after_alter - set(entry_tables))} extra={sorted(set(entry_tables) - legacy_after_alter)}"
        )
    for entry in entries:
        if not (_has_full_proof(entry) or _is_gap_record(entry)):
            problems.append(f"rewrite entry for {entry.get('physical')} has neither a full proof body nor a valid gap record")

    for section in _STATS_SECTIONS:
        stats = fixture.get(section)
        if not (
            isinstance(stats, dict)
            and stats.get("catalog_metadata_bytes")
            and "file_column_stats_rows_est" in stats
            and stats.get("per_ops_table")
        ):
            problems.append(f"{section} is missing or incomplete")

    return problems


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_live_rewrite_evidence_complete() -> None:
    assert evidence_violations(_fixture()) == []


def test_fixture_carries_no_confidential_identifier() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", text)
    assert "arn:aws" not in text
    assert not re.search(r"AKIA[0-9A-Z]{16}", text)


def _report_drift(fixture: dict[str, Any]) -> None:
    fixture["reconcile_after_rewrite"]["drifts"] = [{"physical": "ops_decisions_history"}]


def _leave_legacy_files(fixture: dict[str, Any]) -> None:
    fixture["reconcile_after_rewrite"]["layouts"]["ops_decisions_history"]["legacy_scheme_files"] = 1


def _leave_legacy_files_on_skipped(fixture: dict[str, Any]) -> None:
    fixture["reconcile_after_rewrite"]["skipped"][0]["layout"]["legacy_scheme_files"] = 2


def _skipped_reports_drift(fixture: dict[str, Any]) -> None:
    fixture["reconcile_after_rewrite"]["skipped"][0]["drift"] = {"physical": "x"}


def _omit_named_table(fixture: dict[str, Any]) -> None:
    del fixture["reconcile_after_rewrite"]["layouts"]["ops_priority_queue_history"]


def _digest_mismatch(fixture: dict[str, Any]) -> None:
    fixture["rewrites"][0]["digest_commit"] = "0" * 32


def _row_count_mismatch(fixture: dict[str, Any]) -> None:
    fixture["rewrites"][0]["rows_commit"] = fixture["rewrites"][0]["rows_pre"] + 1


def _snapshot_not_increasing(fixture: dict[str, Any]) -> None:
    entry = fixture["rewrites"][0]
    entry["commit_snapshot_id"] = entry["pre_snapshot_id"]


def _neither_proof_nor_gap(fixture: dict[str, Any]) -> None:
    fixture["rewrites"][0] = {"physical": fixture["rewrites"][0]["physical"]}


def _missing_rewrite_entry(fixture: dict[str, Any]) -> None:
    fixture["rewrites"].pop()


def _extra_rewrite_entry(fixture: dict[str, Any]) -> None:
    extra = copy.deepcopy(fixture["rewrites"][0])
    extra["physical"] = "ops_priority_queue_history"
    fixture["rewrites"].append(extra)


def _duplicate_rewrite_entry(fixture: dict[str, Any]) -> None:
    fixture["rewrites"].append(copy.deepcopy(fixture["rewrites"][0]))


def _no_stats_before(fixture: dict[str, Any]) -> None:
    del fixture["catalog_stats_before"]


def _empty_stats_after(fixture: dict[str, Any]) -> None:
    fixture["catalog_stats_after"] = {}


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_report_drift, "still reports drift"),
        (_leave_legacy_files, "still has legacy_scheme_files"),
        (_leave_legacy_files_on_skipped, "still has legacy_scheme_files"),
        (_skipped_reports_drift, "skipped table"),
        (_omit_named_table, "omits named history tables"),
        (_digest_mismatch, "neither a full proof body"),
        (_row_count_mismatch, "neither a full proof body"),
        (_snapshot_not_increasing, "neither a full proof body"),
        (_neither_proof_nor_gap, "neither a full proof body"),
        (_missing_rewrite_entry, "rewrite entries differ"),
        (_extra_rewrite_entry, "rewrite entries differ"),
        (_duplicate_rewrite_entry, "duplicate rewrite entries"),
        (_no_stats_before, "catalog_stats_before is missing"),
        (_empty_stats_after, "catalog_stats_after is missing"),
    ],
)
def test_each_rule_fails_on_a_mutated_fixture(mutate: Callable[[dict[str, Any]], None], expected: str) -> None:
    fixture = copy.deepcopy(_fixture())
    mutate(fixture)
    assert any(expected in problem for problem in evidence_violations(fixture))


def _as_gap(fixture: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    entry = fixture["rewrites"][0]
    physical = entry["physical"]
    fixture["rewrites"][0] = {
        "physical": physical,
        "human_adjudicated_gap": {
            "table": physical,
            "commit_snapshot_id": entry["commit_snapshot_id"],
            "reason": "Lambda timeout lost the response body; commit snapshot recovered from the commit_message token",
            "confirming_human": "operator",
            **overrides,
        },
    }
    return fixture


def test_a_complete_gap_record_is_accepted_in_place_of_a_proof_body() -> None:
    assert evidence_violations(_as_gap(copy.deepcopy(_fixture()))) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason": ""},
        {"reason": "   "},
        {"confirming_human": ""},
        {"table": ""},
        {"table": "ops_decisions_history"},
    ],
)
def test_an_incomplete_or_misaddressed_gap_record_does_not_count(overrides: dict[str, Any]) -> None:
    fixture = _as_gap(copy.deepcopy(_fixture()), **overrides)
    assert any("neither a full proof body" in problem for problem in evidence_violations(fixture))
