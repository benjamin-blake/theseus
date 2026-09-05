"""print_endstate_drift_advisory: every line it prints names WHY, and SILENCE means in-sync alone.

Named test_summary_context_docs.py rather than test_summary.py so it cannot collide with the
sibling sub-plan that may land its own summary-renderer module for the gh-dependent signals.
_ENDSTATE_SKIPPED_REASONS is reached as a module ATTRIBUTE, never as a symbol-level from-import,
so this module still COLLECTS on an origin/main worktree.
"""

from __future__ import annotations

import pytest

from scripts.preflight import summary

boto3 = pytest.importorskip("boto3")


def _render(advisory: dict, capsys: pytest.CaptureFixture) -> str:
    summary.print_endstate_drift_advisory(advisory)
    return capsys.readouterr().err


def _stale(reason: str, ref: str | None = None, new_ids: list[str] | None = None) -> dict:
    return {"stale": True, "new_ids": new_ids or [], "stamp_ref": ref, "reason": reason}


class TestEndstateAdvisory:
    def test_stale_not_a_commit_names_its_reason(self, capsys: pytest.CaptureFixture) -> None:
        line = _render(_stale("stamp_ref_not_a_commit"), capsys)
        assert "reason=stamp_ref_not_a_commit" in line
        assert "stamp_ref=none" in line

    def test_stale_unresolvable_names_its_reason_and_ref(self, capsys: pytest.CaptureFixture) -> None:
        line = _render(_stale("stamp_ref_unresolvable", "deadbeef"), capsys)
        assert "reason=stamp_ref_unresolvable" in line
        assert "stamp_ref=deadbeef" in line

    def test_stale_hash_mismatch_names_its_reason_and_ref(self, capsys: pytest.CaptureFixture) -> None:
        line = _render(_stale("stamp_ref_hash_mismatch", "abc1234"), capsys)
        assert "reason=stamp_ref_hash_mismatch" in line
        assert "stamp_ref=abc1234" in line

    def test_three_stale_causes_are_mutually_distinct(self, capsys: pytest.CaptureFixture) -> None:
        """The defect stated as a property, not as three literals: the three causes used to render
        byte-identically, so a consumer could not tell which one had happened."""
        rendered = {
            _render(_stale("stamp_ref_not_a_commit"), capsys),
            _render(_stale("stamp_ref_unresolvable", "deadbeef"), capsys),
            _render(_stale("stamp_ref_hash_mismatch", "abc1234"), capsys),
        }
        assert len(rendered) == 3, rendered

    def test_attributed_drift_still_names_the_new_ids(self, capsys: pytest.CaptureFixture) -> None:
        line = _render(_stale("stamp_ref_new_ids_named", "abc1234", ["ZZ9.99"]), capsys)
        assert "new ids: ['ZZ9.99']" in line
        assert "reason=stamp_ref_new_ids_named" in line

    def test_both_fail_open_branches_print_a_skipped_line(self, capsys: pytest.CaptureFixture) -> None:
        assert summary._ENDSTATE_SKIPPED_REASONS == frozenset({"stamp_absent", "parse_error"})
        for reason in sorted(summary._ENDSTATE_SKIPPED_REASONS):
            line = _render({"stale": False, "reason": reason}, capsys)
            assert "SKIPPED" in line, (reason, line)
            assert "drift is UNKNOWN, not clean" in line, (reason, line)
            assert reason in line, (reason, line)

    def test_in_sync_result_is_the_only_silence(self, capsys: pytest.CaptureFixture) -> None:
        assert _render({"stale": False, "reason": "ok", "new_ids": []}, capsys) == ""
        assert _render({"stale": False, "reason": "stamp_absent"}, capsys) != ""

    def test_unrecognized_reason_and_legacy_note_still_print_skipped(self, capsys: pytest.CaptureFixture) -> None:
        """A legacy space-separated note from an older context_docs, and a token no vocabulary
        names, must not render as silence -- a consumer reads silence as clean."""
        for advisory in ({"stale": False, "note": "stamp absent"}, {"stale": False, "reason": "invented_token"}):
            line = _render(advisory, capsys)
            assert "SKIPPED" in line, (advisory, line)
            assert "drift is UNKNOWN, not clean" in line, (advisory, line)


class TestAdvisoryTotality:
    """Nine advisory shapes; every cell asserts a rendered value, never an exception. This
    renderer runs on main()'s thread, so a TypeError here aborts session open."""

    def test_empty_dict(self, capsys: pytest.CaptureFixture) -> None:
        assert "SKIPPED" in _render({}, capsys)

    def test_stale_only(self, capsys: pytest.CaptureFixture) -> None:
        assert "stale" in _render({"stale": True}, capsys)

    def test_not_stale_only(self, capsys: pytest.CaptureFixture) -> None:
        assert "SKIPPED" in _render({"stale": False}, capsys)

    def test_stale_with_none_new_ids(self, capsys: pytest.CaptureFixture) -> None:
        line = _render({"stale": True, "new_ids": None, "reason": "stamp_ref_unresolvable"}, capsys)
        assert "new ids" not in line, line

    def test_reason_ok_without_a_stale_key(self, capsys: pytest.CaptureFixture) -> None:
        assert _render({"reason": "ok"}, capsys) == ""

    def test_legacy_note_only(self, capsys: pytest.CaptureFixture) -> None:
        assert "parse error" in _render({"note": "parse error"}, capsys)

    def test_stale_with_null_reason_and_ref(self, capsys: pytest.CaptureFixture) -> None:
        line = _render({"stale": True, "stamp_ref": None, "reason": None}, capsys)
        assert "reason=unspecified" in line, line

    def test_unrecognized_reason_token(self, capsys: pytest.CaptureFixture) -> None:
        assert "SKIPPED" in _render({"stale": False, "reason": "no_vocabulary_names_this"}, capsys)

    def test_list_valued_reason_does_not_raise_on_the_membership_test(self, capsys: pytest.CaptureFixture) -> None:
        assert "SKIPPED" in _render({"stale": False, "reason": ["a", "list"]}, capsys)
