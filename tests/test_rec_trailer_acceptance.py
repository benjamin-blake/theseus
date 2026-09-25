"""Mirror home for scripts/rec_trailer_acceptance.py (Decision 201, slice A).

Covers the total bucket x probe-verdict map, the shared-arm parity assertions against
scripts.backlog_health.probe.VERDICTS / census.BUCKETS and docs/contracts/vp-red-before.yaml's
OUTCOME_CLASSES, the census stage's execution of the require_decidable grammar ratchet, and the
acceptance_sha256 rejoin's drop paths.
"""

from __future__ import annotations

import itertools
from unittest.mock import patch

from scripts.backlog_health import census as census_mod
from scripts.backlog_health import probe as probe_mod
from scripts.checks.verification._vp_replay_classify import OUTCOME_CLASSES
from scripts.ops_portal.closure_gate import ACCEPTANCE_VERDICTS, FAILS, HOLDS, OUT_OF_GRAMMAR, UNMEASURABLE
from scripts.rec_trailer_acceptance import census, evaluate, rejoin, verdict_for


class TestVerdictMapping:
    def test_mapping_is_total(self) -> None:
        """Every (bucket, probe_verdict) pair drawn from the upstream vocabularies at runtime
        resolves to a member of ACCEPTANCE_VERDICTS -- never raises, never resolves to None."""
        for bucket, probe_verdict in itertools.product(census_mod.BUCKETS, (*probe_mod.VERDICTS, None)):
            verdict = verdict_for(bucket, probe_verdict)
            assert verdict in ACCEPTANCE_VERDICTS

    def test_probe_vocabulary_parity(self) -> None:
        """The domains iterated above are the REAL upstream vocabularies, derived at runtime --
        never a hardcoded, potentially-stale copy."""
        assert census_mod.BUCKETS == (
            census_mod.PROBEABLE,
            census_mod.PROSE_ONLY,
            census_mod.UNPROBEABLE_UNSAFE,
            census_mod.UNPROBEABLE_SHAPE,
            census_mod.EXPECTED_FAIL_MISSING_NODE,
        )
        assert probe_mod.VERDICTS == frozenset(
            {probe_mod.PASS, probe_mod.FAIL, probe_mod.TIMEOUT, probe_mod.BUDGET_EXHAUSTED, probe_mod.ISOLATION_UNAVAILABLE}
        )

    def test_axis_parity_with_vp_red_before(self) -> None:
        """Decision 189 axis discipline: the intersection of ACCEPTANCE_VERDICTS with
        vp-red-before.yaml's OUTCOME_CLASSES is exactly the single genuinely shared arm,
        "unmeasurable" -- asserted, not merely stated in prose."""
        assert ACCEPTANCE_VERDICTS & set(OUTCOME_CLASSES) == {UNMEASURABLE}

    def test_probeable_pass_holds(self) -> None:
        assert verdict_for(census_mod.PROBEABLE, probe_mod.PASS) == HOLDS

    def test_probeable_fail_fails(self) -> None:
        assert verdict_for(census_mod.PROBEABLE, probe_mod.FAIL) == FAILS

    def test_probeable_timeout_and_budget_and_isolation_are_unmeasurable(self) -> None:
        assert verdict_for(census_mod.PROBEABLE, probe_mod.TIMEOUT) == UNMEASURABLE
        assert verdict_for(census_mod.PROBEABLE, probe_mod.BUDGET_EXHAUSTED) == UNMEASURABLE
        assert verdict_for(census_mod.PROBEABLE, probe_mod.ISOLATION_UNAVAILABLE) == UNMEASURABLE

    def test_non_probed_buckets_never_consult_probe_verdict(self) -> None:
        for bucket in (census_mod.PROSE_ONLY, census_mod.UNPROBEABLE_UNSAFE, census_mod.UNPROBEABLE_SHAPE):
            assert verdict_for(bucket, None) == OUT_OF_GRAMMAR
            assert verdict_for(bucket, probe_mod.PASS) == OUT_OF_GRAMMAR

    def test_expected_fail_missing_node_is_fails(self) -> None:
        assert verdict_for(census_mod.EXPECTED_FAIL_MISSING_NODE, None) == FAILS


class TestCensus:
    def test_undecidable_acceptance_is_out_of_grammar(self) -> None:
        """The census stage EXECUTES the require_decidable ratchet: a trailer-named rec whose
        acceptance carries no decidable assertion is classified out_of_grammar (via
        unprobeable_shape) and never probed."""
        rows = [{"id": "rec-1", "acceptance": "echo done"}]
        entries = census(["rec-1"], rows=rows)
        assert len(entries) == 1
        assert entries[0]["bucket"] == census_mod.UNPROBEABLE_SHAPE

    def test_decidable_probeable_acceptance_stays_probeable(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "grep -q foo bar.py"}]
        entries = census(["rec-1"], rows=rows)
        assert entries[0]["bucket"] == census_mod.PROBEABLE

    def test_prose_only_untouched_by_the_ratchet(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "Manual review"}]
        entries = census(["rec-1"], rows=rows)
        assert entries[0]["bucket"] == census_mod.PROSE_ONLY

    def test_absent_row_omitted_from_entries(self) -> None:
        assert census(["rec-missing"], rows=[]) == []


class TestEvaluate:
    def test_isolation_unavailable_resolves_every_entry_to_unmeasurable(self, tmp_path) -> None:
        """evaluate() delegates isolation_available entirely to probe.run_all's own returned
        artifact rather than deciding it itself -- an ISOLATION_UNAVAILABLE run resolves to
        `unmeasurable` for every probeable entry, never a silent pass."""
        entries = [
            {
                "rec_id": "rec-1",
                "acceptance": "grep -q foo bar.py",
                "acceptance_sha256": "abc",
                "bucket": census_mod.PROBEABLE,
            },
            {"rec_id": "rec-2", "acceptance": "Manual review", "acceptance_sha256": "def", "bucket": census_mod.PROSE_ONLY},
        ]
        unavailable_result = {
            "main_sha": "deadbeef",
            "isolation_available": False,
            "verdicts": {"rec-1": probe_mod.ISOLATION_UNAVAILABLE},
        }
        with patch("scripts.rec_trailer_acceptance.probe_mod.run_all", return_value=unavailable_result):
            doc = evaluate(entries, tmp_path, "deadbeef")
        assert doc["isolation_available"] is False
        by_id = {r["rec_id"]: r for r in doc["records"]}
        assert by_id["rec-1"]["verdict"] == UNMEASURABLE
        assert by_id["rec-2"]["verdict"] == OUT_OF_GRAMMAR

    def test_source_is_static(self, tmp_path) -> None:
        doc = evaluate([], tmp_path, "deadbeef")
        assert doc["source"] == "static"


class TestRejoin:
    _CENSUS_DOC = {"entries": [{"rec_id": "rec-1", "acceptance_sha256": "abc123"}]}

    def test_matching_record_survives(self) -> None:
        record = {"rec_id": "rec-1", "acceptance_sha256": "abc123", "verdict": HOLDS}
        verdict_doc = {"records": [record]}
        assert rejoin(self._CENSUS_DOC, verdict_doc) == {"rec-1": record}

    def test_unknown_rec_id_dropped(self) -> None:
        verdict_doc = {"records": [{"rec_id": "rec-999", "acceptance_sha256": "abc123", "verdict": HOLDS}]}
        assert rejoin(self._CENSUS_DOC, verdict_doc) == {}

    def test_changed_acceptance_sha256_dropped(self) -> None:
        verdict_doc = {"records": [{"rec_id": "rec-1", "acceptance_sha256": "stale", "verdict": HOLDS}]}
        assert rejoin(self._CENSUS_DOC, verdict_doc) == {}

    def test_malformed_verdict_dropped(self) -> None:
        verdict_doc = {"records": [{"rec_id": "rec-1", "acceptance_sha256": "abc123", "verdict": "not-a-real-verdict"}]}
        assert rejoin(self._CENSUS_DOC, verdict_doc) == {}

    def test_non_dict_record_dropped(self) -> None:
        verdict_doc = {"records": ["not-a-dict"]}
        assert rejoin(self._CENSUS_DOC, verdict_doc) == {}

    def test_absent_records_key_yields_empty(self) -> None:
        assert rejoin(self._CENSUS_DOC, {}) == {}
