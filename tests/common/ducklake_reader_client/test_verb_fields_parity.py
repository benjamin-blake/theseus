"""VERB_FIELDS <-> NAMED_READS SQL parity (rec-3563 substrate, Decision 84 I-3).

Every fixed-column VERB_FIELDS entry is proven against the column set its verb's REGISTERED SQL
actually produces, executed in an in-memory DuckDB -- never compared to a second hand-copied list.
The four SELECT * verbs resolve through resolve_table_spec(table).ordered_columns instead: a bare
`SELECT *` against a table this test built itself would prove nothing about the real ops_tables
contract, only that this test is internally consistent.

COPIES (never imports) the DuckDB verb-execution harness pattern from
tests/test_session_preflight_cache_serving.py (_con/_run_verb, ~lines 65-85):
validate_no_cross_test_imports forbids importing any module whose final dotted component starts
with test_, and tests/fixtures/ducklake_fakes.py's FakeCon is a connection double that cannot
execute SQL.
"""

from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from src.common.ducklake_reader_client import _NAMED_READS_VERSION_PIN, ALL_TABLE_COLUMNS, VERB_FIELDS  # noqa: E402
from src.common.ducklake_scd2_schema import NAMED_READS, NAMED_READS_VERSION, ScdTableSpec, resolve_table_spec  # noqa: E402

# The four SELECT * verbs: their VERB_FIELDS entry is the ALL_TABLE_COLUMNS sentinel, resolved
# through the table spec below rather than hand-copied (see module docstring).
_SELECT_STAR_VERBS = frozenset({"rec_by_id", "rec_history", "decision_by_id", "priority_queue_current"})

# Only `since_ts` binds need a value CAST-able to TIMESTAMPTZ; every other bound param is a plain
# string equality/LIKE/lookup value, so any non-empty string discriminates without erroring.
_PARAM_VALUES = {"since_ts": "2024-01-01T00:00:00+00:00"}


def _con() -> "duckdb.DuckDBPyConnection":
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    return con


def _create_table(con: "duckdb.DuckDBPyConnection", table_name: str, spec: ScdTableSpec) -> None:
    ddl = ", ".join(f"{name} {sql_type}" for name, sql_type in spec.ordered_columns)
    con.execute(f"CREATE TABLE {table_name} ({ddl})")


def _run_verb_sql(con: "duckdb.DuckDBPyConnection", verb: str, table_name: str, params: list) -> list[str]:
    """Execute *verb*'s registered SQL (both {tbl}/{hist} pointed at *table_name*); return its column names."""
    sql = NAMED_READS[verb].sql.replace("{tbl}", table_name).replace("{hist}", table_name)
    cur = con.execute(sql, params)
    return [d[0] for d in cur.description]


@pytest.mark.parametrize("verb", sorted(NAMED_READS))
def test_verb_fields_match_registry_sql(verb: str) -> None:
    nr = NAMED_READS[verb]
    spec = resolve_table_spec(nr.table)
    con = _con()
    _create_table(con, "t", spec)
    params = [_PARAM_VALUES.get(p, "x") for p in nr.params]
    actual_columns = _run_verb_sql(con, verb, "t", params)

    if verb in _SELECT_STAR_VERBS:
        assert VERB_FIELDS[verb] is ALL_TABLE_COLUMNS, f"{verb}: expected the ALL_TABLE_COLUMNS sentinel"
        expected = [name for name, _ in spec.ordered_columns]
    else:
        assert VERB_FIELDS[verb] is not ALL_TABLE_COLUMNS, f"{verb}: unexpected ALL_TABLE_COLUMNS sentinel"
        expected = list(VERB_FIELDS[verb])

    assert actual_columns == expected, f"{verb}: VERB_FIELDS {expected} != registry SQL columns {actual_columns}"


def test_verb_fields_covers_every_registered_verb() -> None:
    assert set(VERB_FIELDS) == set(NAMED_READS), (
        f"VERB_FIELDS/NAMED_READS drift: missing={set(NAMED_READS) - set(VERB_FIELDS)} "
        f"extra={set(VERB_FIELDS) - set(NAMED_READS)}"
    )


def test_version_pin_matches_registry() -> None:
    assert _NAMED_READS_VERSION_PIN == NAMED_READS_VERSION
