"""PRE-DECLARED decomposition target (Decision 186 / PLAN-escape-closure-obligation): hosts the
new close_recs_from_trailer threading tests from the start, keeping tests/test_ci_rca_lifecycle.py
(431 SLOC pre-plan, 69 headroom) clear of its 500-SLOC ceiling. The refusal-contract mirror
(catch-skip-mark, exit-code behaviour, the workflow-delegation shape pin) lives in
tests/test_ci_rca_lifecycle.py::TestCloseRecsFromTrailerRefusalContract.
"""

from __future__ import annotations

from unittest.mock import patch

_FIX_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_trailer_closure_passes_commit_sha_into_the_gated_write() -> None:
    """close_recs_from_trailer passes closure_fix_sha=commit_sha into the closing update_rec
    call, so the fix-commit binding is satisfiable on the automated route without a second write
    -- rec-autoclose is not wedged by its own gate."""
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer

    with patch("scripts.ops_data_portal.update_rec", return_value=True) as mock_update:
        rc = close_recs_from_trailer(["rec-1"], _FIX_SHA, "https://x/runs/1", {"rec-1": {"status": "open"}})

    assert rc == 0
    mock_update.assert_called_once()
    args, kwargs = mock_update.call_args
    assert args[0] == "rec-1"
    assert kwargs.get("closure_fix_sha") == _FIX_SHA


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
