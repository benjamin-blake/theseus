"""The --pre summary must SURFACE an affected-set derivation fallback.

derive_affected_tests()'s blanket `except Exception` degrades selection to the edited-set and
sets manifest['fallback'], but nothing consumed that flag: validate.py read only
'full_suite_forced'. A persistent derivation bug would therefore hold the gate at
pre-Decision-135 recall indefinitely while still exiting 0 -- loud inside the derivation, silent
in the summary the operator (and CI's step log) actually reads.
"""

import itertools
import sys
from unittest.mock import patch

import pytest

from scripts.checks import registry
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

_WARNING = "AFFECTED-SET SELECTION DEGRADED"


def _manifest(**overrides):
    manifest = {
        "sha": "deadbeef",
        "diff": [],
        "edited_set": [],
        "selected": [],
        "provenance": {},
        "channels": {},
        "capped": False,
        "deferred": [],
        "cap": 35,
        "full_suite_forced": False,
        "timings": {"total_s": 0.0},
    }
    manifest.update(overrides)
    return manifest


def _run_pre(monkeypatch: pytest.MonkeyPatch, pre_sequence_stub, manifest, elapsed: float):
    monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
    monkeypatch.setenv("_VALIDATE_DEPTH", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CI", raising=False)

    selection = {"selected": manifest["selected"], "manifest": manifest}
    with (
        patch("scripts.checks._common.get_changed_files", return_value=[]),
        patch("scripts.checks._common.run", side_effect=_pre_mock_run),
        patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
        patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=selection),
        patch("scripts.checks.deps.affected_tests.emit_manifest"),
        patch("validate._file_budget_breach_rec"),
        patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(elapsed))),
        pytest.raises(SystemExit) as exc_info,
    ):
        _validate.main()
    return exc_info.value.code


class TestFallbackSurfacing:
    """A fallback manifest produces a loud, single-line warning; a healthy one produces none."""

    def test_fallback_manifest_prints_loud_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        manifest = _manifest(fallback=True, fallback_reason="RuntimeError('graph exploded')", selected=["tests/test_a.py"])
        code = _run_pre(monkeypatch, pre_sequence_stub, manifest, elapsed=60.0)

        out = capsys.readouterr().out
        assert code == 0
        assert _WARNING in out
        assert "RuntimeError('graph exploded')" in out
        assert "1 test file(s)" in out

    def test_healthy_manifest_prints_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code = _run_pre(monkeypatch, pre_sequence_stub, _manifest(), elapsed=60.0)

        assert code == 0
        assert _WARNING not in capsys.readouterr().out

    def test_budget_breach_context_names_the_fallback(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        """A breach diagnosed off phase timings is misleading when selection was degraded --
        the dominant-phase report must say so rather than reading as ordinary drift."""
        manifest = _manifest(fallback=True, fallback_reason="RuntimeError('boom')")
        code = _run_pre(monkeypatch, pre_sequence_stub, manifest, elapsed=400.0)

        out = capsys.readouterr().out
        assert code == 1
        assert "Fast tier exceeded budget" in out
        assert "affected-set derivation fell back" in out

    def test_healthy_budget_breach_has_no_fallback_note(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        code = _run_pre(monkeypatch, pre_sequence_stub, _manifest(), elapsed=400.0)

        out = capsys.readouterr().out
        assert code == 1
        assert "affected-set derivation fell back" not in out
