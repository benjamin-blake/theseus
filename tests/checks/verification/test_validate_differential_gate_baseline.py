"""Tests for validate_differential_gate_baseline(). Mirror of
scripts/checks/verification/validate_differential_gate_baseline.py.

The underlying differential/probe machinery (scripts.verification_graduation) has its own
dedicated coverage in tests/verification_graduation/test_provisioning.py -- these tests cover
this check function's OWN wiring: how it turns vg.materialize_check_in_tree/git_worktree/
run_differential outcomes into failed[] messages and registry examined()/skipped()
declarations, via mocks on the vg module rather than real worktrees.
"""

from __future__ import annotations

import contextlib
import sys
from unittest.mock import patch

from scripts import verification_graduation as vg
from scripts.checks.verification.validate_differential_gate_baseline import validate_differential_gate_baseline
from scripts.verification_checks import CheckResult, CheckStatus


def _check(status: CheckStatus) -> object:
    return type("FakeCheck", (), {"run": lambda self: CheckResult(status=status, message="x", actual="x")})()


@contextlib.contextmanager
def _fake_worktree(ref: str, repo_root: object = None):
    yield "fake-worktree-root"


class TestDifferentialGateStep:
    def test_passes_on_live_tree(self) -> None:
        """VP step 9 (pre-fix precedent): the gate baseline passes on the live code tree."""
        failed: list[str] = []
        validate_differential_gate_baseline(failed)
        assert not failed, f"Differential gate baseline failed: {failed}"

    def test_fails_when_canonical_slots_wrong_count(self) -> None:
        failed: list[str] = []
        with patch("scripts.verification_checks.CANONICAL_SLOTS", frozenset({"a", "b"})):
            validate_differential_gate_baseline(failed)
        assert any("CANONICAL_SLOTS" in f for f in failed)

    def test_fails_when_live_probe_fails(self) -> None:
        failed: list[str] = []
        with patch("scripts.verification_graduation.materialize_check_in_tree", return_value=_check(CheckStatus.FAIL)):
            validate_differential_gate_baseline(failed)
        assert any("FAILED live" in f for f in failed)

    def test_fails_when_scratch_worktree_unavailable(self) -> None:
        failed: list[str] = []
        with (
            patch("scripts.verification_graduation.materialize_check_in_tree", return_value=_check(CheckStatus.PASS)),
            patch("scripts.verification_graduation.git_worktree", side_effect=vg.GraduationError("boom")),
        ):
            validate_differential_gate_baseline(failed)
        assert any("could not materialize a scratch worktree" in f for f in failed)

    def test_fails_when_scratch_parity_broken(self) -> None:
        """Live passes but the scratch worktree probe fails -- the .venv-provisioning fix
        regressing is exactly the shape this branch guards against."""
        failed: list[str] = []
        results = iter([_check(CheckStatus.PASS), _check(CheckStatus.FAIL)])
        with (
            patch("scripts.verification_graduation.materialize_check_in_tree", side_effect=lambda *a, **k: next(results)),
            patch("scripts.verification_graduation.git_worktree", _fake_worktree),
        ):
            validate_differential_gate_baseline(failed)
        assert any("FAILS in a scratch worktree" in f for f in failed)

    def test_fails_when_run_differential_raises(self) -> None:
        failed: list[str] = []
        with (
            patch("scripts.verification_graduation.materialize_check_in_tree", return_value=_check(CheckStatus.PASS)),
            patch("scripts.verification_graduation.git_worktree", _fake_worktree),
            patch("scripts.verification_graduation.run_differential", side_effect=vg.GraduationError("boom")),
        ):
            validate_differential_gate_baseline(failed)
        assert any("raised unexpectedly" in f for f in failed)

    def test_sys_path_injection_branch_restores_path(self, tmp_path: object) -> None:
        """_common.ROOT can resolve somewhere not already on sys.path (e.g. inside a sandboxed
        subprocess) -- the defensive sys.path insert/remove dance must still leave the module
        importable and restore sys.path exactly afterward."""
        failed: list[str] = []
        root_str = str(tmp_path)
        assert root_str not in sys.path
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.verification_graduation.materialize_check_in_tree", return_value=_check(CheckStatus.PASS)),
            patch("scripts.verification_graduation.git_worktree", _fake_worktree),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=vg.DifferentialOutcome(admitted=False, reason="rejected"),
            ),
        ):
            validate_differential_gate_baseline(failed)
        assert not failed, failed
        assert root_str not in sys.path

    def test_fails_when_tautology_probe_admitted(self) -> None:
        """The defect this plan removes: a tautological probe must never be admitted."""
        failed: list[str] = []
        with (
            patch("scripts.verification_graduation.materialize_check_in_tree", return_value=_check(CheckStatus.PASS)),
            patch("scripts.verification_graduation.git_worktree", _fake_worktree),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=vg.DifferentialOutcome(admitted=True, reason="fake admit"),
            ),
        ):
            validate_differential_gate_baseline(failed)
        assert any("ADMITTED" in f for f in failed)
