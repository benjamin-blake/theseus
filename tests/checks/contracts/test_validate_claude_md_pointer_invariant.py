"""Tests for check_claude_md_pointer_invariant()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.contracts.validate_claude_md_pointer_invariant import (
    check_claude_md_pointer_invariant,
    validate_claude_md_pointer_invariant,
)


class TestClaudeMdPointerInvariant:
    """Tests for check_claude_md_pointer_invariant()."""

    def test_claude_md_pointer_happy_path(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@AGENTS.md\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is True

    def test_claude_md_pointer_extra_content(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@AGENTS.md\nstray content\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False

    def test_claude_md_pointer_wrong_target(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("@OTHER.md\n", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False

    def test_claude_md_pointer_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "CLAUDE.md"
        p.write_text("", encoding="utf-8")
        assert check_claude_md_pointer_invariant(str(p)) is False


class TestPointerInvariantFailureEmission:
    """The REGISTERED wrapper's own emission site, which the predicate tests above never reach.

    The tests above import only the pure helper, so validate_claude_md_pointer_invariant.py:28
    (`failed.append("CLAUDE.md pointer invariant")`) is executed by none of them and neutering it
    to `pass` survives them. These drive the wrapper itself with the check's root knob patched --
    _common is imported as a MODULE (validate_claude_md_pointer_invariant.py:7), so the target is
    that module attribute and the helper's default relative path="CLAUDE.md" resolves against it.
    Every assertion is EXACT list equality on failed, never truthiness on the predicate.
    """

    @staticmethod
    def _run(root: Path) -> list[str]:
        failed: list[str] = []
        with patch("scripts.checks.contracts.validate_claude_md_pointer_invariant._common.ROOT", root):
            validate_claude_md_pointer_invariant(failed)
        return failed

    def test_divergent_root_claude_md_appends_a_failure(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\nstray content\n", encoding="utf-8")
        assert self._run(tmp_path) == ["CLAUDE.md pointer invariant"]

    def test_missing_root_claude_md_appends_a_failure(self, tmp_path: Path) -> None:
        """No CLAUDE.md at all: the helper's OSError arm returns False and the wrapper must still
        append, not merely print."""
        assert self._run(tmp_path) == ["CLAUDE.md pointer invariant"]

    def test_clean_root_claude_md_appends_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        assert self._run(tmp_path) == []
