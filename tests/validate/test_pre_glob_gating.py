"""Leading-`**/` semantics of scripts/validate.py's --pre glob gate.

Separate module rather than a new class in tests/validate/test_tiers.py: that file sits at 492
SLOC against the 500-line budget, so a new class there would breach it.
"""

from __future__ import annotations

import pytest

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
