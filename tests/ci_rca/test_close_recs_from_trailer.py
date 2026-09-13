"""PRE-DECLARED decomposition target (Decision 186 / PLAN-escape-closure-obligation): hosts the
new close_recs_from_trailer threading tests from the start, keeping tests/test_ci_rca_lifecycle.py
(431 SLOC pre-plan, 69 headroom) clear of its 500-SLOC ceiling. The refusal-contract mirror
(catch-skip-mark, exit-code behaviour, the workflow-delegation shape pin) lives in
tests/test_ci_rca_lifecycle.py::TestCloseRecsFromTrailerRefusalContract.

PLAN-closure-stamp-applicability: the seam contract cases below drive close_recs_from_trailer
against the REAL update_rec with only the warehouse boundary stubbed (the shape
tests/test_ci_rca_inactivity_sweep.py::test_sweep_closes_escape_classified_rec_end_to_end already
established) -- #1133's mocked tests all patched update_rec with a bare MagicMock, so none of them
could catch the production defect where a blob-less rec's closure hit update_rec's real
closure-stamp precondition and reddened main. RecNotFound is resolved LAZILY (inside a test body)
so this module stays importable on origin/main, where the symbol does not exist yet.
"""

from __future__ import annotations

import json
from unittest.mock import patch

_FIX_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_closes_rec_lacking_context_v2_json(tmp_path) -> None:
    """rec-3738's own acceptance predicate: a trailer-named rec carrying no context_v2_json
    closes cleanly through the REAL update_rec (only the warehouse boundary stubbed) -- exit code
    0, exactly one warehouse write. Red before this plan's fix: update_rec's own closure-stamp
    precondition raised ValueError for the unconditionally-threaded closure_fix_sha kwarg, which
    the broad `except Exception` in close_recs_from_trailer caught and turned into exit_code=1."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    existing = {"id": "rec-1", "status": "open"}  # no context_v2_json key at all
    recs_file = tmp_path / "recs.jsonl"
    with (
        patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=existing),
        patch("scripts.ops_data_portal._ducklake_write", return_value={"ok": True}) as mock_write,
        patch("scripts.ops_data_portal._sync_table"),
        patch("scripts.ops_data_portal.RECS_JSONL", recs_file),
    ):
        rc = close_recs_from_trailer(["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "open"}})

    assert rc == 0
    mock_write.assert_called_once()


def test_trailer_closure_with_blob_passes_commit_sha_into_the_gated_write() -> None:
    """A trailer-named rec whose cached row carries a stampable context_v2_json blob gets
    closure_fix_sha=commit_sha threaded into the closing update_rec call, so the fix-commit
    binding is satisfiable on the automated route without a second write -- rec-autoclose is not
    wedged by its own gate."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
        rc = close_recs_from_trailer(
            ["rec-1"],
            _FIX_SHA,
            "https://x/runs/1",
            {"rec-1": {"status": "open", "context_v2_json": json.dumps({"escape_class": "no-edge"})}},
        )

    assert rc == 0
    mock_update.assert_called_once()
    args, kwargs = mock_update.call_args
    assert args[0] == "rec-1"
    assert kwargs.get("closure_fix_sha") == _FIX_SHA


def test_trailer_closure_without_blob_omits_closure_fix_sha() -> None:
    """A trailer-named rec whose cached row carries NO context_v2_json omits closure_fix_sha
    entirely from the update_rec call -- update_rec's own closure-stamp precondition is never
    even reached, since the kwarg is never threaded for an inapplicable blob."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
        rc = close_recs_from_trailer(["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "open"}})

    assert rc == 0
    mock_update.assert_called_once()
    args, kwargs = mock_update.call_args
    assert args[0] == "rec-1"
    assert "closure_fix_sha" not in kwargs


def test_already_closed_rec_is_skipped_idempotently() -> None:
    """A rec the cache already shows closed is skipped entirely -- no update_rec call at all."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with patch("scripts.ops_data_portal.update_rec") as mock_update:
        rc = close_recs_from_trailer(["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "closed"}})

    assert rc == 0
    mock_update.assert_not_called()


def test_ci_rca_rec_still_gets_stamp_fixed_by_sha_call() -> None:
    """The existing post-close stamp_fixed_by_sha call is kept for ci_rca recs and runs
    alongside closure_fix_sha -- idempotent (both write the same key), never removed."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with (
        patch("scripts.ops_data_portal.update_rec", return_value=True),
        patch("scripts.ops_portal.ci_rca_lifecycle.stamp_fixed_by_sha") as mock_stamp,
    ):
        rc = close_recs_from_trailer(
            ["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "open", "source": "ci_rca"}}
        )

    assert rc == 0
    mock_stamp.assert_called_once_with("rec-1", _FIX_SHA, profile=None)


def test_writer_transport_failure_sets_exit_code() -> None:
    """A writer-transport RuntimeError (reader-unreachable, a referential 409, an HTTP failure --
    anything that is not RecNotFound) during closure sets exit_code=1. Never discriminated by
    message substring -- the fixture's message deliberately does not resemble a 'not found'
    phrase, so a substring-matching implementation would fail this test."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with patch(
        "scripts.ops_data_portal.update_rec",
        side_effect=RuntimeError("writer transport: 502 Bad Gateway"),
    ):
        rc = close_recs_from_trailer(["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "open"}})

    assert rc == 1


def test_absent_rec_skips_without_exit_code() -> None:
    """RecNotFound (an absent rec) is the ONLY RuntimeError treated as a skip -- exit_code stays
    0, distinguished by TYPE from every other RuntimeError, never by message substring. Resolved
    lazily (function-local import) so this module still imports cleanly on origin/main, where
    RecNotFound does not exist yet."""
    from scripts.ops_data_portal import RecNotFound
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with patch("scripts.ops_data_portal.update_rec", side_effect=RecNotFound("rec-1 does not exist")):
        rc = close_recs_from_trailer(["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "open"}})

    assert rc == 0
