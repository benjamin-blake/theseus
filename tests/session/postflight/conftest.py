"""Package conftest for tests/session/postflight/ (rec-2709 Wave 10).

Hoists the module-level autouse fixture `_mock_sync_ops_postflight` from the former
tests/test_session_postflight.py monolith VERBATIM. Layers UNDER the root tests/conftest.py
(global recursion/socket/env-clearing autouse fixtures) without redeclaring any of them.

Importing tests.fixtures.session_postflight_module here (noqa F401) guarantees
sys.modules["session_postflight"] is registered before any patch("session_postflight.*")
string-target call resolves it -- every tests/session/postflight/test_*.py module does the same
import, so Python's own import cache makes this a no-op after the first collection, but declaring
it here too keeps the conftest self-sufficient regardless of collection order.

PLAN-handoff-validates-committed-tree fail-closed guard: run_auto now commits, rebases and
verify-heads BEFORE it pushes, so a run_auto test that forgets to patch one of those seams would
otherwise reach a REAL `git fetch`/`git rebase`/`git add`/`git commit`/`git push` against this
checkout. Two independent layers close that: (1) session_postflight.run_rebase and .run_verify_head
are stubbed to raise unless a test overrides them; (2) scripts.postflight._common._run itself
refuses any mutating git verb it is asked to run for real, so a test that forgets ONLY its
run_commit/run_validate patch (not run_rebase/run_verify_head) still cannot fall through to a real
`git add`/`git commit`.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.postflight import _common
from tests.fixtures.session_postflight_module import postflight as _postflight  # noqa: F401

# Captured at conftest IMPORT time (before any fixture patches them), so `postflight_seams` always
# hands back the real function bodies -- used by the direct seam tests (TestRebaseSeam,
# TestVerifyHeadSeam) that must exercise the actual implementation, not the fail-closed stub.
_ORIGINAL_RUN_REBASE = _postflight.run_rebase
_ORIGINAL_RUN_VERIFY_HEAD = _postflight.run_verify_head
_ORIGINAL_COMMON_RUN = _common._run

_MUTATING_GIT_VERBS = frozenset({"add", "commit", "fetch", "rebase", "push"})


def _unstubbed_seam(name: str):
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"unstubbed real-git seam: patch it in this test ({name})")

    return _raise


def _guarded_run(cmd: list[str], cwd: Path | None = None, capture: bool = True):
    """Delegate to the real scripts.postflight._common._run for everything EXCEPT a mutating git
    verb (argv[0] == "git" and argv[1] in _MUTATING_GIT_VERBS), which raises instead -- so a
    run_auto test that forgets its own run_commit/run_validate patch cannot silently fall through
    to a real `git add . && git commit` now that commit precedes validate."""
    if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] in _MUTATING_GIT_VERBS:
        raise AssertionError(f"unstubbed real-git mutating call under the postflight test guard: {list(cmd)!r}")
    return _ORIGINAL_COMMON_RUN(cmd, cwd=cwd, capture=capture)


@pytest.fixture(autouse=True)
def _mock_sync_ops_postflight():
    """Prevent real AWS calls from sync_ops inside run_auto() tests.

    Step 8 of run_auto calls scripts.ops_data_portal.sync(), which pulls each table via
    scripts.sync.ops._pull_single_table -- stub the pull so no test reaches the network.
    """
    with (
        patch("scripts.sync.ops.sync", return_value={"drained": {}, "pulled": {}}),
        patch("scripts.sync.ops._pull_single_table", return_value=0),
    ):
        yield


@pytest.fixture(autouse=True)
def _fail_closed_real_git_seams():
    with (
        patch("session_postflight.run_rebase", side_effect=_unstubbed_seam("session_postflight.run_rebase")),
        patch("session_postflight.run_verify_head", side_effect=_unstubbed_seam("session_postflight.run_verify_head")),
        patch("scripts.postflight._common._run", side_effect=_guarded_run),
    ):
        yield


@pytest.fixture
def postflight_seams():
    """The ORIGINAL, unstubbed run_rebase/run_verify_head bodies, for the direct seam tests."""
    return {"run_rebase": _ORIGINAL_RUN_REBASE, "run_verify_head": _ORIGINAL_RUN_VERIFY_HEAD}
