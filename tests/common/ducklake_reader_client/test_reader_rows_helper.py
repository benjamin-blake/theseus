"""tests/fixtures/reader_rows.py::verb_rows unit tests (rec-3563 substrate)."""

from __future__ import annotations

import pytest

from src.common.ducklake_reader_client import ALL_TABLE_COLUMNS, VERB_FIELDS
from tests.fixtures.reader_rows import verb_rows


def test_verb_rows_strips_extra_keys() -> None:
    rows = [{"id": "rec-1", "source": "tf_convergence_stale", "status": "open", "title": "t"}]
    stripped = verb_rows("open_recs", rows)
    assert stripped == [{"id": "rec-1", "title": "t"}]


def test_verb_rows_rejects_unknown_verb() -> None:
    with pytest.raises(ValueError, match="unregistered verb"):
        verb_rows("not_a_verb", [{"id": "rec-1"}])


def test_verb_rows_preserves_rows_already_in_projection() -> None:
    rows = [{"id": "rec-1", "title": "t", "context": "c", "created_timestamp": "2024-01-01", "automatable": True}]
    assert verb_rows("open_recs", rows) == rows


def test_verb_rows_resolves_all_table_columns_sentinel() -> None:
    """A SELECT * verb (ALL_TABLE_COLUMNS) strips to the underlying table's declared columns, not a fixed list."""
    assert VERB_FIELDS["rec_by_id"] is ALL_TABLE_COLUMNS
    rows = [{"id": "rec-1", "title": "t", "bogus_field": "dropped"}]
    stripped = verb_rows("rec_by_id", rows)
    assert stripped == [{"id": "rec-1", "title": "t"}]
