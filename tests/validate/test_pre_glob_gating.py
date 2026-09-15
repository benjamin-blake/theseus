"""scripts/validate.py's --pre glob gate: leading-`**/` semantics, plus the VTS-09 pre_globs
gate's match/should-run/end-to-end dispatch slice (PR1 decomposition, Decision 128
decompose-by-default: tests/validate/test_tiers.py sat at 492 SLOC against the 500-line budget).

TestPreGlobMatch, TestShouldRunInPre and TestPreGlobsGateEndToEnd moved here from test_tiers.py --
this EXISTING module already owns _pre_glob_match/_should_run_in_pre, so extending it avoids two
confusably-named modules for one subject (collocation doctrine).
"""

from __future__ import annotations

import itertools
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import registry
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

_pre_glob_match = _validate._pre_glob_match
_should_run_in_pre = _validate._should_run_in_pre


class TestLeadingDoubleStarMatchesZeroDirectories:
    """A leading `**/` must also match a repo-ROOT path.

    Bare fnmatch translates `**/*.py` to a pattern requiring at least one `/`, so `setup.py` did
    not match the glob that gates validate_cc_limits -- whose own scan (sloc/_shared.
    iter_gated_py_files) walks the repo root. Under-inclusion is a recall bug: the check silently
    did not run on exactly the diffs that touched a root-level module.
    """

    @pytest.mark.parametrize(
        "path,glob,expected",
        [
            ("setup.py", "**/*.py", True),
            ("conftest.py", "**/*.py", True),
            ("scripts/validate.py", "**/*.py", True),
            ("tests/validate/test_tiers.py", "**/*.py", True),
            ("AGENTS.md", "**/*.py", False),
            ("docs/DECISIONS.md", "**/*.py", False),
            ("AGENTS.md", "**/*.md", True),
            ("docs/DECISIONS.md", "**/*.md", True),
            ("setup.py", "**/*.md", False),
        ],
    )
    def test_match(self, path: str, glob: str, expected: bool) -> None:
        assert _pre_glob_match(path, glob) is expected

    def test_a_non_leading_double_star_segment_is_unaffected(self) -> None:
        assert _pre_glob_match("docs/plans/PLAN-x.yaml", "docs/plans/**") is True
        assert _pre_glob_match("plans/PLAN-x.yaml", "docs/plans/**") is False

    def test_root_python_file_admits_a_globbed_check(self) -> None:
        assert _should_run_in_pre(("**/*.py",), {"setup.py"}, True) is True

    def test_root_non_python_file_still_skips(self) -> None:
        assert _should_run_in_pre(("**/*.py",), {"AGENTS.md"}, True) is False


class TestPreGlobMatch:
    """_pre_glob_match against each of the six VTS-09 gated checks' pre_globs patterns."""

    @pytest.mark.parametrize(
        "path,glob,expected",
        [
            ("docs/plans/PLAN-foo.yaml", "docs/plans/**", True),
            ("docs/plans/nested/deep/PLAN-x.yaml", "docs/plans/**", True),
            ("scripts/validate.py", "docs/plans/**", False),
            ("docs/ROADMAP-PLATFORM.yaml", "docs/ROADMAP-*", True),
            ("docs/plans/PLAN-foo.yaml", "docs/ROADMAP-*", False),
            ("docs/DECISIONS.md", "docs/DECISIONS.md", True),
            ("docs/DECISIONS_ARCHIVE.md", "docs/DECISIONS.md", False),
            ("tests/test_validate.py", "tests/**", True),
            ("tests/validate/test_tiers.py", "tests/**", True),
            ("scripts/validate.py", "tests/**", False),
            ("scripts/validate.py", "**/*.py", True),
            ("tests/test_x.py", "**/*.py", True),
            ("docs/DECISIONS.md", "**/*.py", False),
        ],
    )
    def test_match(self, path: str, glob: str, expected: bool) -> None:
        assert _pre_glob_match(path, glob) is expected


class TestShouldRunInPre:
    """_should_run_in_pre: fail-closed gate decision (dec-55/dec-135/dec-153, VTS-09)."""

    def test_pre_globs_none_always_runs(self) -> None:
        assert _should_run_in_pre(None, set(), True) is True
        assert _should_run_in_pre(None, {"docs/DECISIONS.md"}, True) is True

    def test_matching_path_runs(self) -> None:
        assert _should_run_in_pre(("tests/**",), {"tests/test_x.py"}, True) is True

    def test_non_matching_path_skips(self) -> None:
        assert _should_run_in_pre(("tests/**",), {"scripts/validate.py"}, True) is False

    def test_derivation_not_ok_always_runs(self) -> None:
        """dec-135 fail-closed: a derivation exception/unexpected outcome never skips."""
        assert _should_run_in_pre(("tests/**",), {"scripts/validate.py"}, False) is True

    def test_empty_changed_set_always_runs(self) -> None:
        """A successful derivation with zero changed paths (clean-diff branch state) still runs."""
        assert _should_run_in_pre(("tests/**",), set(), True) is True


class TestPreGlobsGateEndToEnd:
    """End-to-end --pre dispatch tests for the VTS-09 pre_globs gate (VP step 3)."""

    _SIX_CHECKS = (
        "validate_platform_roadmap",
        "validate_plan_documents",
        "validate_tier_floor",
        "validate_test_count_coupling",
        "validate_no_cross_test_imports",
        "validate_cc_limits",
    )

    @pytest.mark.parametrize(
        "changed_path,skipped,run",
        [
            (
                # Not under docs/plans/**, not docs/ROADMAP-*, not docs/DECISIONS.md itself.
                "docs/CHANGELOG.md",
                ["validate_platform_roadmap", "validate_plan_documents", "validate_tier_floor"],
                [],
            ),
            (
                # Not under tests/**, but still **/*.py -- proves each gated check's glob is
                # evaluated independently rather than one match short-circuiting every gate.
                "scripts/foo.py",
                ["validate_test_count_coupling", "validate_no_cross_test_imports"],
                ["validate_cc_limits"],
            ),
            (
                # Under tests/** AND **/*.py -- both gates match the same diff.
                "tests/test_foo.py",
                [],
                ["validate_test_count_coupling", "validate_no_cross_test_imports", "validate_cc_limits"],
            ),
        ],
    )
    def test_gate_skips_and_runs_by_diff_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        pre_sequence_stub,
        changed_path: str,
        skipped: list[str],
        run: list[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        mocks = {name: MagicMock() for name in skipped + run}
        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=self._SIX_CHECKS)),
            patch("scripts.checks._common.get_changed_files", return_value=[changed_path]),
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", changed_path)]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            ExitStack() as stack,
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            for name, mock in mocks.items():
                defining_module = registry._ALL_ENTRIES[name].module
                stack.enter_context(patch(f"{defining_module}.{name}", mock))
            _validate.main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for name in skipped:
            mocks[name].assert_not_called()
            assert f"skipped-by-glob: {name}" in out
        for name in run:
            mocks[name].assert_called_once()
