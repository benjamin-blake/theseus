"""Tests for src/common/ducklake_named_reads.py -- the named-read registry moved out of
ducklake_scd2_schema (telemetry table-registration plan; Decision 124 facade-plus-siblings) plus the
per-verb read_version stamp (review item C1). Pure and DB-free.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from src.common import ducklake_named_reads as nr
from src.common import ducklake_scd2_schema as schema

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# rec_history NAMED_READS entry + NAMED_READS_VERSION (T1.16 c4)
# ---------------------------------------------------------------------------


def test_named_reads_version_is_3():
    assert nr.NAMED_READS_VERSION == 3


def test_rec_history_verb_registered():
    rh = nr.NAMED_READS["rec_history"]
    assert rh.table == "ops_recommendations"
    assert rh.params == ("id",)
    assert "{hist}" in rh.sql
    assert "ORDER BY last_updated_timestamp DESC, ulid DESC" in rh.sql


# ---------------------------------------------------------------------------
# Total-order invariant (T1.16 c1): every paginable or trailing-LIMIT verb ends in a unique key
# ---------------------------------------------------------------------------


def test_named_reads_total_order_invariant():
    import re

    def lim(s: str) -> bool:
        return bool(re.search(r"\bLIMIT\s+\d+\s*$", s, re.I))

    def tot(s: str) -> bool:
        return bool(re.search(r"ORDER BY .*\b(id|ulid)\b[^,]*$", s, re.I | re.S))

    bad = [v for v, n in nr.NAMED_READS.items() if (n.paginable or lim(n.sql)) and not tot(n.sql)]
    assert not bad


def test_priority_queue_current_excluded_from_total_order_check():
    """priority_queue_current's LIMIT is a subquery bound, not a trailing output cap -- excluded."""
    entry = nr.NAMED_READS["priority_queue_current"]
    assert not entry.paginable
    import re

    assert not re.search(r"\bLIMIT\s+\d+\s*$", entry.sql, re.I)


def test_ci_rca_open_and_budget_bypass_recent_have_id_tiebreak():
    """The two trailing-LIMIT verbs' ORDER BY carries an `id` tiebreak (reproducible bounded reads)."""
    for verb in ("ci_rca_open", "budget_bypass_recent"):
        sql = nr.NAMED_READS[verb].sql
        assert ", id LIMIT" in sql


def test_open_recs_and_recs_by_title_prefix_are_paginable():
    assert nr.NAMED_READS["open_recs"].paginable is True
    assert nr.NAMED_READS["recs_by_title_prefix"].paginable is True


# ---------------------------------------------------------------------------
# describe_named_reads (CD.10 / CD.15 agent-facing describe surface)
# ---------------------------------------------------------------------------


def test_describe_named_reads_covers_every_verb():
    out = nr.describe_named_reads()
    assert set(out) == set(nr.NAMED_READS)
    entry = out["rec_by_id"]
    assert entry["params"] == ["id"]
    assert entry["params_schema"]["required"] == ["id"]
    assert "table" in entry and "description" in entry and "paginable" in entry


def test_describe_named_reads_no_params_verb():
    out = nr.describe_named_reads()
    assert out["open_recs"]["params"] == []
    assert out["open_recs"]["params_schema"]["required"] == []


# ---------------------------------------------------------------------------
# read_version -- computed, opaque, per-verb digest (review item C1)
# ---------------------------------------------------------------------------


def test_read_version_is_per_verb_digest(monkeypatch):
    before = {v: nr.read_version(v) for v in nr.NAMED_READS}
    assert before == {v: nr.read_version(v) for v in nr.NAMED_READS}  # stable across calls
    assert all(len(d) == 16 and int(d, 16) >= 0 for d in before.values())

    changed = dict(nr.NAMED_READS)
    changed["count_by_status"] = dataclasses.replace(changed["count_by_status"], sql="SELECT status FROM {tbl}")
    changed["ci_rca_since"] = dataclasses.replace(changed["ci_rca_since"], params=("since_ts", "extra"))
    monkeypatch.setattr(nr, "NAMED_READS", changed)
    after = {v: nr.read_version(v) for v in nr.NAMED_READS}
    assert {v for v in before if before[v] != after[v]} == {"count_by_status", "ci_rca_since"}  # no other verb moves


def test_read_version_ignores_sql_whitespace_but_not_paginable(monkeypatch):
    base = nr.NAMED_READS["count_by_status"]
    spaced = dataclasses.replace(base, sql="  " + base.sql.replace(" ", "   ") + "\n")
    paginable = dataclasses.replace(base, paginable=True)
    original = nr.read_version("count_by_status")
    monkeypatch.setattr(nr, "NAMED_READS", {**nr.NAMED_READS, "count_by_status": spaced})
    assert nr.read_version("count_by_status") == original
    monkeypatch.setattr(nr, "NAMED_READS", {**nr.NAMED_READS, "count_by_status": paginable})
    assert nr.read_version("count_by_status") != original


def test_select_star_verb_reversions_when_its_column_projection_changes():
    semantics = copy.deepcopy(schema.load_field_semantics())
    star = [v for v, n in nr.NAMED_READS.items() if nr._SELECT_STAR.search(n.sql)]
    assert {"rec_by_id", "rec_history", "decision_by_id", "priority_queue_current"} <= set(star)
    other = [v for v in nr.NAMED_READS if v not in star]
    before = {v: nr.read_version(v, semantics) for v in nr.NAMED_READS}

    columns = semantics["ops_tables"]["ops_recommendations"]["columns"]
    columns["brand_new"] = {"role": "input", "sql_type": "VARCHAR", "nullable": True}
    after = {v: nr.read_version(v, semantics) for v in nr.NAMED_READS}
    changed = {v for v in before if before[v] != after[v]}
    assert changed == {"rec_by_id", "rec_history"}  # the SELECT * verbs bound to the changed table only
    assert not changed & set(other)


def test_read_version_is_computed_at_call_time_not_import():
    """No module-scope facade import and no module-level digest (AGENTS.md: never raise at import)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(nr))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert node.module != "src.common.ducklake_scd2_schema"
    assert not hasattr(nr, "READ_VERSIONS")


def test_describe_named_reads_carries_read_version():
    out = nr.describe_named_reads()
    for verb, entry in out.items():
        assert entry["read_version"] == nr.read_version(verb)
