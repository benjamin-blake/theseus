"""Strip fixture dicts to the shape a NAMED_READS verb actually emits (rec-3563).

A hand-authored test fixture can express any dict shape, including keys the ducklake_reader never
returns for a given verb -- the mechanism by which a call site filtering on an unprojected field
(e.g. open_recs' missing source/status) can pass its tests while being permanently blind in
production. verb_rows() forces every fixture row through the verb's declared projection
(src.common.ducklake_reader_client.VERB_FIELDS), so a fixture cannot silently exercise a shape
production never produces.

Lives in tests/fixtures/ (Decision 131): its name never starts with `test_`, so it is exempt from
the no-cross-test-import guard and importable from any test module.
"""

from __future__ import annotations

from typing import Any

from src.common.ducklake_reader_client import ALL_TABLE_COLUMNS, VERB_FIELDS
from src.common.ducklake_scd2_schema import NAMED_READS, resolve_table_spec


def _verb_columns(verb: str) -> tuple[str, ...]:
    """Resolve *verb*'s declared column tuple, resolving the ALL_TABLE_COLUMNS sentinel via the table spec."""
    if verb not in VERB_FIELDS:
        raise ValueError(f"verb_rows: unregistered verb {verb!r} (known: {sorted(VERB_FIELDS)})")
    fields = VERB_FIELDS[verb]
    if fields is not ALL_TABLE_COLUMNS:
        return fields
    table = NAMED_READS[verb].table
    return tuple(name for name, _ in resolve_table_spec(table).ordered_columns)


def verb_rows(verb: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip each dict in *rows* to *verb*'s declared projection (extra keys dropped).

    Raises ValueError on an unregistered verb name -- a typo must never silently pass a fixture
    through unstripped.
    """
    columns = _verb_columns(verb)
    return [{k: v for k, v in row.items() if k in columns} for row in rows]
