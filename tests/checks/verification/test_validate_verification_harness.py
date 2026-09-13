"""Mirror test for scripts/checks/verification/validate_verification_harness.py.

Before this file the registered wrapper was never called by any test -- only its NAME appeared, in
tests/checks/verification/test__manifest.py and tests/checks/registry/test_sequences.py. The module
has TWO emission sites that append the IDENTICAL string "Verification Harness" (the HARD_GATE-fail
branch at :38 and the except-Exception branch at :41), so failed[] alone cannot tell them apart:
they are discriminated here by stdout, the except branch by its "[ERROR] Verification harness
failed to run" marker and the hard-gate branch by the absence of that marker.

Root knobs: scripts.verifiers.run_all_verifiers (the check imports it at CALL time inside its try
block, so patching the attribute on the package is what intercepts it) and, for the sys.path guard
only, the check module's own _common.ROOT.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

import scripts.verifiers
from scripts.checks.verification.validate_verification_harness import validate_verification_harness
from scripts.verifiers.harness import VerifierResult, VerifierSeverity, VerifierStatus

_Harness = Callable[..., Awaitable[list[VerifierResult]]]


def _result(status: VerifierStatus, severity: VerifierSeverity = VerifierSeverity.HARD_GATE) -> VerifierResult:
    return VerifierResult(name="FakeVerifier", status=status, message="synthetic", severity=severity)


def _returning(results: list[VerifierResult]) -> _Harness:
    async def _fake(*args: object, **kwargs: object) -> list[VerifierResult]:
        return results

    return _fake


def _raising(message: str) -> _Harness:
    async def _fake(*args: object, **kwargs: object) -> list[VerifierResult]:
        raise RuntimeError(message)

    return _fake


def _run(monkeypatch: pytest.MonkeyPatch, fake: _Harness) -> list[str]:
    monkeypatch.setattr("scripts.verifiers.run_all_verifiers", fake)
    failed: list[str] = []
    validate_verification_harness(failed)
    return failed


class TestVerificationHarnessEmission:
    """fn(failed) against a faked harness: both append sites, plus the severity discriminator."""

    def test_hard_gate_failure_appends_a_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        failed = _run(monkeypatch, _returning([_result(VerifierStatus.FAIL)]))
        out = capsys.readouterr().out
        assert failed == ["Verification Harness"]
        assert "[FAIL]" in out
        assert "Verification harness failed to run" not in out

    def test_harness_exception_appends_a_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        failed = _run(monkeypatch, _raising("synthetic harness explosion"))
        out = capsys.readouterr().out
        assert failed == ["Verification Harness"]
        assert "[ERROR] Verification harness failed to run: synthetic harness explosion" in out

    def test_advisory_failure_appends_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An ADVISORY-severity FAIL is below HARD_GATE and must not fail the tier; with the
        hard-gate case above this pins the severity comparison from both sides."""
        failed = _run(monkeypatch, _returning([_result(VerifierStatus.FAIL, VerifierSeverity.ADVISORY)]))
        assert failed == []

    def test_all_pass_appends_nothing(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        failed = _run(monkeypatch, _returning([_result(VerifierStatus.PASS)]))
        out = capsys.readouterr().out
        assert failed == []
        assert "[PASS]" in out


def test_repo_root_is_injected_and_removed_when_absent_from_sys_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check injects _common.ROOT into sys.path only when absent and removes it in its finally
    block. A fresh tmp_path root is guaranteed absent, so the injection branch actually runs and
    sys.path must come back byte-identical."""
    monkeypatch.setattr("scripts.checks.verification.validate_verification_harness._common.ROOT", tmp_path)
    before = list(sys.path)
    failed: list[str] = []
    validate_verification_harness(failed)
    assert failed == []
    assert sys.path == before


def test_live_registry_passes() -> None:
    """Unpatched smoke over the REAL verifier registry.

    scripts.verifiers.REGISTRY is EMPTY today (scripts/verifiers/__init__.py:16), so this green is
    an empty-domain pass, not an enforced one -- the vacuity is asserted here explicitly rather
    than left implied (Decision 170), and the test's standing value is early warning on the day a
    verifier is registered and starts failing.
    """
    assert scripts.verifiers.REGISTRY == []
    failed: list[str] = []
    validate_verification_harness(failed)
    assert failed == []
