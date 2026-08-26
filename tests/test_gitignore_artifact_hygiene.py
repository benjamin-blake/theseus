"""Regression guard for the coverage-sidefile .gitignore fix (PLAN-coverage-sidefile-gitignore).

Confirms via ".gitignore" and 'git check-ignore' that coverage.py's parallel-mode side-files, the
coverage JSON report and the plain .coverage data file are git-ignored, while '.coveragerc' --
which shares the '.coverage' prefix -- stays trackable. The negative control is load-bearing: it
is what discriminates the correct '.coverage.*' pattern from the over-broad '.coverage*'
shorthand, which would wrongly swallow .coveragerc.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_ignore(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=_REPO_ROOT,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    assert result.returncode in (0, 1), f"git check-ignore fatal error for {relative_path!r} (returncode={result.returncode})"
    return result.returncode == 0


def test_coverage_artifacts_are_ignored() -> None:
    assert _check_ignore(".coverage"), ".coverage (plain coverage.py data file) should be git-ignored"
    assert _check_ignore(".coverage.json"), ".coverage.json (coverage_baseline.py's JSON report) should be git-ignored"
    assert _check_ignore(".coverage.host1.12345.ab12cd34"), (
        ".coverage.host1.12345.ab12cd34 (coverage.py parallel-mode side-file shape) should be git-ignored"
    )
    assert not _check_ignore(".coveragerc"), (
        ".coveragerc should stay trackable -- if this fails, the ignore pattern is the over-broad "
        "'.coverage*' shorthand instead of the narrow '.coverage.*'"
    )
