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

from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """The same write-time gate accepts a well-formed dependencies list through update_rec.

    array_element_reference resolves existence via its own make_reader/rec_by_id call (not the
    facade -- scripts.ops_portal may not import scripts.ops_data_portal, .importlinter
    no-cycles-ops-data-portal-executor), so a well-formed list also needs a reachable reader
    reporting both elements present."""
    from scripts.ops_portal.write_validators import _rec_exists_memo

    _rec_exists_memo.clear()
    recs_file = tmp_path / "recs.jsonl"
    fake_reader = MagicMock()
    fake_reader.named.return_value = [{"id": "present"}]
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("src.common.ducklake_reader_client.make_reader", return_value=fake_reader),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec("rec-4001", {"dependencies": ["rec-1", "rec-2"]})

    assert result is True
    mock_write.assert_called_once()
    _rec_exists_memo.clear()


def test_dependencies_reject_dangling_reference(tmp_path: Path) -> None:
    """FAILING-FIRST: update_rec rejects a dependencies element that is well-formed but names a
    rec id absent from the corpus (rec-3307 referential half, PLAN-dependency-referential-integrity).

    Referential existence resolves via its own make_reader/rec_by_id call, independent of the
    _fetch_rec_from_reader patch used for update_rec's own current-record fetch (see
    test_dependencies_accept_valid_list for why)."""
    from scripts.ops_portal.write_validators import _rec_exists_memo

    _rec_exists_memo.clear()
    recs_file = tmp_path / "recs.jsonl"
    fake_reader = MagicMock()
    fake_reader.named.return_value = []  # every dependency target is absent

    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("src.common.ducklake_reader_client.make_reader", return_value=fake_reader),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="dependencies"):
            update_rec("rec-4001", {"dependencies": ["rec-999999"]})
    mock_write.assert_not_called()
    _rec_exists_memo.clear()


def test_dependency_on_closed_rec_is_accepted(tmp_path: Path) -> None:
    """INVARIANT: a dependency naming a CLOSED rec is accepted -- existence resolves against the
    full corpus via rec_by_id, not the open set (guards the backlog-health Class 3 mistake)."""
    from scripts.ops_portal.write_validators import _rec_exists_memo

    _rec_exists_memo.clear()
    recs_file = tmp_path / "recs.jsonl"
    fake_reader = MagicMock()
    fake_reader.named.return_value = [{"id": "rec-1", "status": "closed"}]

    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("src.common.ducklake_reader_client.make_reader", return_value=fake_reader),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec("rec-4001", {"dependencies": ["rec-1"]})

    assert result is True
    mock_write.assert_called_once()
    _rec_exists_memo.clear()


def test_update_rec_rejects_nonconforming_tag(tmp_path: Path) -> None:
    """tags joins _UPDATE_CONTENT_VALIDATED_FIELDS -- a non-conforming tag element is rejected
    through update_rec's write-time gate (Decision 181 clause 2)."""
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(_EXISTING)),
        patch("scripts.ops_data_portal._ducklake_write") as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        with pytest.raises(ValueError, match="tags"):
            update_rec("rec-4001", {"tags": ["T2.56"]})
    mock_write.assert_not_called()


def test_legacy_nonconforming_tag_still_updates(tmp_path: Path) -> None:
    """Row-level grandfathering: an update touching another field on a rec that already carries a
    legacy non-conforming tag still succeeds, because tags is absent from that call's `updates`."""
    recs_file = tmp_path / "recs.jsonl"
    legacy = {**_EXISTING, "tags": ["T2.17"]}
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=dict(legacy)),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        from scripts.ops_data_portal import update_rec

        result = update_rec("rec-4001", {"status": "closed"})

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
