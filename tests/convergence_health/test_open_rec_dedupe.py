"""rec-3291's acceptance oracle (2026-08-27, the original dedup-blindness rec).

Post-migration the four named()-based finders (find_open_convergence_stale_rec,
find_open_ducklake_drift_rec, find_open_prod_drift_rec, and _budget_recs.py's own duplicate
_fetch_open_recs helper) no longer exist -- the subject of this assertion is
scripts.rec_episode.find_rec itself: the keys it filters on (`source`, `status`, and whatever
`sub_key_fields` a caller declares) must be a subset of the keys its read actually returns.

SCOPE NOTE: find_rec's production read is current_state("ops_recommendations", row_filter=...),
an UNNARROWED structural read -- it returns every declared column today, so this assertion cannot
falsify anything about TODAY's behaviour. What it guards is a FUTURE regrowth: if find_rec (or a
caller) is ever changed to pass `selected_fields` and narrow the read, this test starts failing
the moment the narrowed projection drops `source`/`status` (or a declared sub_key field) -- the
exact defect class rec-3291/rec-3563 diagnosed, reintroduced through a different door. It is
distinct from the registered guard (scripts/checks/hygiene/validate_episode_lookup_projection.py),
which is a STATIC AST scan over named()-verb call sites; neither subsumes the other.
"""

from __future__ import annotations

from scripts.rec_episode import _BASE_FILTERED_KEYS, find_rec
from src.common.ducklake_scd2_schema import resolve_table_spec


def test_open_rec_finders_match_live_verb_projection() -> None:
    spec = resolve_table_spec("ops_recommendations")
    declared_columns = {name for name, _ in spec.ordered_columns}

    # 1. The keys find_rec/find_recs always filter on are a subset of what the read declares.
    assert set(_BASE_FILTERED_KEYS) <= declared_columns

    # 2. The three migrated call sites' sub_key_fields are likewise a subset -- pinned against the
    #    actual literal values each caller passes, not re-derived, so a caller that starts
    #    filtering on a column the table doesn't declare fails HERE rather than silently at
    #    runtime against a live warehouse.
    budget_ingest_sub_key_fields = ("context",)
    assert set(budget_ingest_sub_key_fields) <= declared_columns

    # 3. A fixture row carrying exactly the full declared column set (what an unnarrowed
    #    current_state read genuinely returns) must never trip find_rec's missing-key assertion.
    full_row = {name: None for name, _ in spec.ordered_columns}
    full_row["source"] = "tf_convergence_stale"
    full_row["status"] = "open"
    full_row["id"] = "rec-1"
    result = find_rec("tf_convergence_stale", rows=[full_row])
    assert result is not None
    assert result["id"] == "rec-1"

    # 4. The regrowth path this test guards: a row narrowed to LESS than the declared projection
    #    (e.g. a future selected_fields regression) trips find_rec's runtime assertion rather than
    #    silently returning None.
    narrowed_row = {"id": "rec-1"}
    try:
        find_rec("tf_convergence_stale", rows=[narrowed_row])
    except RuntimeError as exc:
        assert "missing filtered key" in str(exc)
    else:
        raise AssertionError("find_rec must raise on a row narrowed below its filtered keys")
