"""Decision 131 mirror home for scripts/ops_data_portal.py's update_rec write-boundary changes in
PLAN-ops-portal-enforcement-gaps: dependencies joins _UPDATE_CONTENT_VALIDATED_FIELDS (rec-3307),
and update_rec's YAML-driven acceptance lint now requires a discriminating probe shape too,
matching file_rec (rec-3306 core).

Module-level test functions (not class-nested) so the node ids match the plan's Verification Plan
commands verbatim (tests/ops_data_portal/test_update_rec_content_validation.py::test_<name>).

Defines its own minimal valid-fields fixture locally rather than importing
tests/fixtures/ops_portal_records.VALID_FIELDS, following the local-fixture precedent in
tests/ops_data_portal/test_acceptance_discrimination.py.

No `duckdb = pytest.importorskip("duckdb")` guard: _fetch_rec_from_reader / _ducklake_write /
_sync_table are mocked throughout, so this module never touches a real DuckLake connection and
scripts.ops_data_portal itself has no duckdb import at module scope -- see
tests/test_ops_data_portal_validators.py and test_acceptance_discrimination.py for the same
unguarded-import precedent (the guard would also break VP-step replay under
requirements-fast.txt, which carries no duckdb).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

_EXISTING = {
    "id": "rec-4001",
    "title": "Existing recommendation under test for the update_rec content boundary",
    "file": "scripts/ops_data_portal.py",
    "context": "A sufficiently long context string so the write-time content validators are satisfied here.",
    "acceptance": "grep -q ops_data_portal scripts/ops_data_portal.py && grep -q update_rec scripts/ops_data_portal.py",
    "effort": "XS",
    "priority": "Low",
    "source": "planning",
    "risk": "low",
    "status": "open",
    "automatable": True,
    "dependencies": None,
    "date": "2026-01-01",
}


def test_dependencies_reject_malformed_element(tmp_path: Path) -> None:
    """dependencies joins _UPDATE_CONTENT_VALIDATED_FIELDS -- an update setting a malformed
    element is rejected through update_rec's write-time gate (rec-3307)."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="dependencies"):
            update_rec("rec-4001", {"dependencies": ["rec-1", "nonsense"]})
    mock_write.assert_not_called()


def test_dependencies_accept_valid_list(tmp_path: Path) -> None:
    """The same write-time gate accepts a well-formed dependencies list through update_rec."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec("rec-4001", {"dependencies": ["rec-1", "rec-2"]})

    assert result is True
    mock_write.assert_called_once()


def test_update_rec_acceptance_requires_discrimination(tmp_path: Path) -> None:
    """update_rec()'s YAML-driven acceptance_lint validator now requires a discriminating probe
    shape too (rec-3306 core; write_validators.py's _check_acceptance closure gains
    require_discrimination=True) -- the same rule file_rec already applies at its explicit call
    site. VP steps 4-7 guard this keystone change."""
    recs_file = tmp_path / "recs.jsonl"

    # A lone literal grep -- non-discriminating.
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="does not discriminate"):
            update_rec("rec-4001", {"acceptance": "grep -q ops_data_portal scripts/ops_data_portal.py"})
    mock_write.assert_not_called()

    # A bare pytest path against an already-existing test file -- non-discriminating.
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write2,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="does not discriminate"):
            update_rec(
                "rec-4001",
                {"acceptance": "bin/venv-python -m pytest tests/test_executor_acceptance_lint.py -q"},
            )
    mock_write2.assert_not_called()

    # A chained second assertion -- genuinely discriminating -- must still be accepted.
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write3,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec(
            "rec-4001",
            {
                "acceptance": (
                    "grep -q ops_data_portal scripts/ops_data_portal.py && grep -q update_rec scripts/ops_data_portal.py"
                )
            },
        )
    assert result is True
    mock_write3.assert_called_once()


# -- Decision 184 closure-time artifact obligation (PLAN-escape-closure-obligation) -------------

_ESCAPE_EXISTING = {
    **_EXISTING,
    "id": "rec-5001",
    "status": "open",
    "context_v2_json": json.dumps({"escape_class": "no-edge"}),
}


def test_rec_3131_replay_is_refused(tmp_path: Path) -> None:
    """The historical rec-3131 case, replayed verbatim: status closed, resolution 'Duplicate of
    rec-3132...', no closure_artifact, no waiver. Refused -- this single refusal IS audit finding
    LSA-04, not a defect in the mechanism (Decision 184 Problem statement)."""
    existing = {
        **_EXISTING,
        "id": "rec-3131",
        "status": "open",
        "context_v2_json": json.dumps({"detection_gap": {"escape_mode": "tier_misplaced"}}),
    }
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(existing)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import ClosureArtifactRequired, update_rec

        with pytest.raises(ClosureArtifactRequired):
            update_rec(
                "rec-3131",
                {"status": "closed", "resolution": "Duplicate of rec-3132, which carries the full RCA and is closed"},
            )
    mock_write.assert_not_called()


def test_named_artifact_absent_is_refused(tmp_path: Path) -> None:
    """A closure_artifact naming a shard id that does not exist in the tree is refused -- the
    write-boundary integration of the known-bad-fixture case."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import ClosureArtifactRequired, update_rec

        with pytest.raises(ClosureArtifactRequired):
            update_rec(
                "rec-5001",
                {"status": "closed", "resolution": "fixed"},
                closure_artifact="shard:this-shard-id-does-not-exist-anywhere",
                closure_fix_sha="cafef00dcafef00dcafef00dcafef00cafef00d",
            )
    mock_write.assert_not_called()


def test_closing_write_that_blanks_context_is_still_refused(tmp_path: Path) -> None:
    """D-B3: a closing write that also blanks context_v2_json in the SAME update_rec call is
    still refused -- the predicate reads existing UNION merged, so the write cannot erase the
    classification that gates it (context_v2_json is not in _UPDATE_CONTENT_VALIDATED_FIELDS and
    carries no monotonicity guard)."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import ClosureArtifactRequired, update_rec

        with pytest.raises(ClosureArtifactRequired):
            update_rec("rec-5001", {"status": "closed", "context_v2_json": "{}"})
    mock_write.assert_not_called()


def test_open_to_declined_is_gated(tmp_path: Path) -> None:
    """D-B2: open -> declined is gated too (the bound set is {closed, declined, superseded}),
    closing the two-step open -> declined -> superseded route a closed-alone gate would leave
    open."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import ClosureArtifactRequired, update_rec

        with pytest.raises(ClosureArtifactRequired):
            update_rec("rec-5001", {"status": "declined", "resolution": "not pursuing"})
    mock_write.assert_not_called()


def test_closure_fix_sha_stamps_fixed_by_sha_in_the_gated_write(tmp_path: Path) -> None:
    """closure_fix_sha stamps the EXISTING context_v2_json.fixed_by_sha key into the SAME merged
    payload the gate evaluates -- the artifact route is satisfiable in one call."""
    fix_sha = "cafef00dcafef00dcafef00dcafef00cafef00d"
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        patch("scripts.ops_portal.closure_gate.resolve_closure_artifact") as mock_resolve,
    ):
        mock_resolve.return_value = True
        from scripts.ops_data_portal import update_rec

        result = update_rec(
            "rec-5001",
            {"status": "closed", "resolution": "fixed"},
            closure_artifact="pytest:tests/some_test.py::test_thing",
            closure_fix_sha=fix_sha,
        )

    assert result is True
    # the resolver was handed the SAME sha the written payload carries
    _, called_fix_sha = mock_resolve.call_args[0][:2]
    assert called_fix_sha == fix_sha
    _, written_rec = mock_write.call_args[0]
    written_ctx = json.loads(written_rec["context_v2_json"])
    assert written_ctx["fixed_by_sha"] == fix_sha


def test_resolvable_artifact_closes(tmp_path: Path) -> None:
    """A closure supplying a resolvable artifact succeeds and writes."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        patch("scripts.ops_portal.closure_gate.resolve_closure_artifact", return_value=True),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec(
            "rec-5001",
            {"status": "closed", "resolution": "fixed"},
            closure_artifact="shard:some-shard",
            closure_fix_sha="cafef00dcafef00dcafef00dcafef00cafef00d",
        )

    assert result is True
    mock_write.assert_called_once()


def test_waived_closure_closes(tmp_path: Path) -> None:
    """A closure supplying a well-formed categorised waiver (category is a member of
    WAIVER_CATEGORIES, reason non-empty) succeeds without any artifact -- no fix commit needed."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec(
            "rec-5001",
            {"status": "closed", "resolution": "environment flake, not reproducible"},
            closure_waiver_category="environment_only",
            closure_waiver_reason="sandbox-only failure with no premerge signal; see run 12345",
        )

    assert result is True
    mock_write.assert_called_once()


def test_duplicate_citing_master_artifact_closes(tmp_path: Path) -> None:
    """A duplicate closure passes only by citing a FIX-BOUND closure_artifact token (never a rec
    id) -- no promise transfer, no rec-to-rec pointer resolved, no reader egress added."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_ESCAPE_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
        patch("scripts.ops_portal.closure_gate.resolve_closure_artifact", return_value=True) as mock_resolve,
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec(
            "rec-5001",
            {"status": "closed", "resolution": "Duplicate of rec-9999, which carries the full RCA and is closed"},
            closure_artifact="check:validate_workflow_agent_safety",
            closure_fix_sha="cafef00dcafef00dcafef00dcafef00cafef00d",
        )

    assert result is True
    mock_write.assert_called_once()
    # the token resolved is the CLASS artifact, never a rec id
    called_token = mock_resolve.call_args[0][0]
    assert called_token == "check:validate_workflow_agent_safety"


def test_status_preserving_write_on_closed_escape_rec_is_not_gated(tmp_path: Path) -> None:
    """A status-preserving write on an already-closed escape rec (stamp_fixed_by_sha, occurrence
    bump, context correction) is NOT gated -- 'terminal' is defined on the FROM side, and the
    obligation was already discharged when the rec first closed."""
    already_closed = {
        **_EXISTING,
        "id": "rec-5001",
        "status": "closed",
        "context_v2_json": json.dumps({"escape_class": "no-edge"}),
    }
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(already_closed)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec(
            "rec-5001",
            {"context_v2_json": json.dumps({"escape_class": "no-edge", "fixed_by_sha": "abc1234"})},
        )

    assert result is True
    mock_write.assert_called_once()
