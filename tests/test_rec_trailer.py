"""Unit tests for scripts/rec_trailer.py."""

from __future__ import annotations

from unittest.mock import patch

from scripts.rec_trailer import parse_resolves_trailer


class TestParseResolvesTrailer:
    """Tests for parse_resolves_trailer()."""

    # --- happy paths ---

    def test_single_id(self) -> None:
        msg = "feat: fix thing\n\nResolves: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_multiple_ids_comma_separated(self) -> None:
        msg = "Resolves: rec-2187, rec-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    def test_multiple_ids_space_separated(self) -> None:
        msg = "Resolves: rec-2187 rec-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    def test_multiple_ids_mixed_separator(self) -> None:
        msg = "Resolves: rec-100, rec-200 rec-300"
        assert parse_resolves_trailer(msg) == ["rec-100", "rec-200", "rec-300"]

    # --- no trailer ---

    def test_no_trailer_returns_empty(self) -> None:
        msg = "feat: nothing special\n\nThis commit does not resolve anything."
        assert parse_resolves_trailer(msg) == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_resolves_trailer("") == []

    # --- deduplication ---

    def test_dedup_same_id_twice(self) -> None:
        msg = "Resolves: rec-2187, rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_dedup_preserves_first_seen_order(self) -> None:
        msg = "Resolves: rec-200, rec-100, rec-200"
        assert parse_resolves_trailer(msg) == ["rec-200", "rec-100"]

    # --- malformed tokens ---

    def test_malformed_token_ignored(self) -> None:
        msg = "Resolves: rec-abc, rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_malformed_token_letters_only_ignored(self) -> None:
        msg = "Resolves: recfoo, rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_pure_number_not_a_rec_id(self) -> None:
        msg = "Resolves: 2187"
        assert parse_resolves_trailer(msg) == []

    def test_rec_followed_by_empty_string(self) -> None:
        msg = "Resolves: rec-"
        assert parse_resolves_trailer(msg) == []

    # --- case insensitivity on keyword ---

    def test_uppercase_keyword(self) -> None:
        msg = "RESOLVES: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_titlecase_keyword(self) -> None:
        msg = "Resolves: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_mixed_case_keyword(self) -> None:
        msg = "rEsOlVeS: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    # --- output is always lowercase ---

    def test_uppercase_rec_token_normalized(self) -> None:
        msg = "Resolves: REC-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    def test_mixed_case_rec_token_normalized(self) -> None:
        msg = "Resolves: Rec-2187, REC-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    # --- multiline body ---

    def test_trailer_at_end_of_multiline_commit(self) -> None:
        msg = "feat(scope): summary line\n\nBody paragraph explaining the change.\n\nResolves: rec-2187, rec-2179"
        assert parse_resolves_trailer(msg) == ["rec-2187", "rec-2179"]

    def test_non_resolves_trailers_ignored(self) -> None:
        msg = "Fix: something\nSee-also: rec-9999\nResolves: rec-2187"
        assert parse_resolves_trailer(msg) == ["rec-2187"]

    # --- edge cases ---

    def test_resolves_in_body_prose_not_picked_up_as_trailer(self) -> None:
        # "Resolves:" must appear at the START of a line to count as a trailer
        msg = "This change resolves: the old problem. rec-9999"
        # "resolves:" in the middle of a sentence does appear at start of a "line" in MULTILINE
        # Only if it's literally at line start. "resolves" in "This change resolves:" is not.
        result = parse_resolves_trailer(msg)
        # "resolves:" does NOT start the line -- "This change..." does. So no match.
        assert result == []

    def test_multiple_trailer_lines(self) -> None:
        msg = "Resolves: rec-100\nResolves: rec-200"
        assert parse_resolves_trailer(msg) == ["rec-100", "rec-200"]

    def test_colon_with_no_following_whitespace_no_longer_parses(self) -> None:
        """rec-2922's ONE deliberate behaviour change beyond the block rule: the old
        `^resolves\\s*:\\s*` accepted a colon with no following whitespace; the new
        `^[A-Za-z][A-Za-z-]*:\\s` block-line shape requires it. Fail-safe direction: a trailer
        that no longer parses is a non-closure, not a false closure (Decision 103)."""
        assert parse_resolves_trailer("Resolves:rec-2187") == []


class TestWrappedProseNotATrailer:
    """rec-2922's named selector. #803's shape (commit 73387861): a `Resolves:` line wrapped
    inside a prose paragraph is never a trailer under the any-Key:value-block rule -- the whole
    block (paragraph) is rejected because its OTHER lines are not `Key: value`-shaped."""

    def test_wrapped_prose_yields_no_ids(self) -> None:
        msg = (
            "fix: address the flaky retry path\n\n"
            "This change reworks the retry loop so that a transient failure no longer\n"
            "Resolves: the underlying race by itself; it only masks it under load. rec-9999\n"
            "is unrelated and should not be picked up either.\n"
        )
        assert parse_resolves_trailer(msg) == []

    def test_resolves_line_with_prose_siblings_in_same_block_rejected(self) -> None:
        msg = "Body prose line one.\nResolves: rec-100\nBody prose line three."
        assert parse_resolves_trailer(msg) == []


class TestAttributionFooterStillParses:
    """REGRESSION guard pinning this repository's own commit convention: a `Resolves:` block
    followed by a blank line and the mandated `Co-Authored-By:` / `Claude-Session:` attribution
    footer must still parse under the any-block rule -- it must not silently regress to
    final-block-only, which would break 79 of 122 historical Resolves commits."""

    def test_resolves_block_then_attribution_footer(self) -> None:
        msg = (
            "feat(slug): implement thing\n\n"
            "Resolves: rec-3775, rec-3901, rec-2922\n\n"
            "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n"
            "Claude-Session: https://claude.ai/code/session_abc123\n"
        )
        assert parse_resolves_trailer(msg) == ["rec-3775", "rec-3901", "rec-2922"]


class TestPlanOnlyMergeRefusesTrailer:
    """rec-3901's own acceptance predicate. NON-VACUITY: parse_resolves_trailer is a pure parser
    with no notion of a merge leg, and a plan merge's trailer is well-formed and SHOULD parse --
    so this asserts the END-TO-END outcome via the gate (imported here, never re-tested as a
    parser concern): given a well-formed trailer AND a plan-only changed set, merge_leg_refuses
    returns True and close_recs_from_trailer attempts no close."""

    def test_well_formed_trailer_but_plan_only_diff_refuses_close(self) -> None:
        from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer
        from scripts.ops_portal.trailer_closure_gate import merge_leg_refuses

        msg = "docs(plan): author PLAN-example\n\nResolves: rec-1234"
        ids = parse_resolves_trailer(msg)
        assert ids == ["rec-1234"]  # the trailer itself is well-formed and parses

        changed = {"docs/plans/PLAN-example.yaml"}
        assert merge_leg_refuses(changed) is True  # but the merge-leg gate refuses to act on it

        with (
            patch("scripts.ops_portal.ci_rca_lifecycle.changed_files", return_value=changed),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            rc = close_recs_from_trailer(ids, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "https://x/runs/1", {})

        assert rc == 0
        mock_update.assert_not_called()


# VP7 autoclose test marker
