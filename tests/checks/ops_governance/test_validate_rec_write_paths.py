"""Tests for validate_rec_write_paths() -- rec JSONL write-path enforcement."""

import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks import registry
from scripts.checks.ops_governance import validate_rec_write_paths as rec_write_paths_module
from scripts.checks.ops_governance.validate_rec_write_paths import validate_rec_write_paths


class TestValidateRecWritePaths:
    """Tests for validate_rec_write_paths() -- rec JSONL write-path enforcement."""

    def test_catches_direct_recs_jsonl_open_append(self, tmp_path: Path, capsys) -> None:
        """Detects RECS_JSONL.open('a') in non-whitelisted scripts."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_script.py"
        bad_file.write_text(
            'with RECS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert len(failed) > 0
        assert any("bad_script.py" in e for e in failed)

    def test_allows_whitelist_portal_file(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'with RECS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_allows_whitelist_sync_recommendations(self, tmp_path: Path, capsys) -> None:
        """scripts/sync/recommendations.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        sync_dir = scripts_dir / "sync"
        sync_dir.mkdir(parents=True)
        sync_file = sync_dir / "recommendations.py"
        sync_file.write_text(
            'with open(_LOCAL_RECS_FILE, "w", encoding="utf-8") as fh: fh.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_clean_scripts_directory_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts with no direct JSONL writes pass without failures."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_prose_mention_with_unrelated_open_not_flagged(self, tmp_path: Path, capsys) -> None:
        """Regression (rec-2844): a prose docstring mention of recommendations-log.jsonl followed
        later in the file by an unrelated open(other_path, 'a') must NOT be flagged.

        This is the exact _budget_recs.py shape: a negative-guidance docstring line naming the
        JSONL cache, plus a legitimate GITHUB_STEP_SUMMARY append far below it. The pre-fix
        pattern used re.DOTALL with an unbounded '.*', so it spanned from the prose mention all
        the way to the unrelated open() call and misfired.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        prose_file = scripts_dir / "budget_recs_like.py"
        prose_file.write_text(
            '"""Helper docstring.\n'
            "\n"
            "The dedupe lookup reads the open_recs reader boundary, never\n"
            "logs/.recommendations-log.jsonl (a read cache is never a write source). A reader\n"
            "failure loud-warns and falls through.\n"
            '"""\n'
            "\n"
            "import os\n"
            "\n"
            "\n"
            "def _write_summary(summary_path: str, message: str) -> None:\n"
            '    with open(summary_path, "a", encoding="utf-8") as f:\n'
            "        f.write(message)\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert failed == []

    def test_catches_literal_path_open_append(self, tmp_path: Path, capsys) -> None:
        """True positive preserved: a genuine open("...recommendations-log.jsonl...", "a") --
        the JSONL literal as the actual open() target within the same call -- is still flagged.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "direct_literal_write.py"
        bad_file.write_text(
            'with open("logs/.recommendations-log.jsonl", "a", encoding="utf-8") as f:\n    f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert len(failed) > 0
        assert any("direct_literal_write.py" in e for e in failed)

    def test_catches_literal_path_open_write_mode(self, tmp_path: Path, capsys) -> None:
        """True positive preserved: write mode ("w") on a literal-path open is still flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "direct_literal_overwrite.py"
        bad_file.write_text(
            'with open(".recommendations-log.jsonl", "w") as f:\n    f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_rec_write_paths(failed)
        assert len(failed) > 0
        assert any("direct_literal_overwrite.py" in e for e in failed)


_CHECK = "validate_rec_write_paths"
_UNIT = "py files"
_REPO_ROOT = Path(__file__).parents[3]
_WHITELIST_REL = (
    "scripts/ops_data_portal.py",
    "scripts/sync/recommendations.py",
    "scripts/sync/ops.py",
    "scripts/s3_log_store.py",
    "scripts/session/postflight.py",
)


class _ProbeCountingRe:
    """Stands in for the module's `re`: the first compiled pattern counts its finditer() calls, i.e. the
    files whose content the check's pattern loop actually scanned (each scanned file probes it exactly once)."""

    def __init__(self) -> None:
        self.probes = 0
        self._compiled = 0

    def compile(self, pattern: str, flags: int = 0) -> object:
        compiled = re.compile(pattern, flags)
        self._compiled += 1
        if self._compiled != 1:
            return compiled
        counter = self

        class _Counting:
            def finditer(self, content: str) -> Iterator[re.Match[str]]:
                counter.probes += 1
                return compiled.finditer(content)

        return _Counting()


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _declared(root: Path) -> tuple[list[str], registry._Declaration | None, int]:
    registry.pop_declaration()
    failed: list[str] = []
    probe = _ProbeCountingRe()
    with patch("scripts.checks._common.ROOT", root), patch.object(rec_write_paths_module, "re", probe):
        validate_rec_write_paths(failed)
    return failed, registry.pop_declaration(), probe.probes


class TestRecWritePathsAccountingDeclaration:
    """The check declares how many non-whitelisted .py files it read and pattern-scanned, so a run records
    enforced with a count that tracks the scanned tree -- not a constant and not the violation count."""

    def test_real_tree_declares_every_scanned_file(self) -> None:
        whitelist = {_REPO_ROOT / rel for rel in _WHITELIST_REL}
        expected = sum(
            1
            for top in ("scripts", "personal_scripts")
            if (_REPO_ROOT / top).exists()
            for path in (_REPO_ROOT / top).glob("**/*.py")
            if path not in whitelist and path.is_file()
        )

        failed, declaration, probes = _declared(_REPO_ROOT)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert expected > 0
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)
        assert probes == expected
        assert outcome.status == "enforced"

    @pytest.mark.parametrize("n", [1, 4])
    def test_count_tracks_files_and_excludes_whitelist(self, tmp_path: Path, n: int) -> None:
        for i in range(n):
            _write(tmp_path, f"scripts/pkg/mod_{i}.py")
        _write(tmp_path, "personal_scripts/mine.py")
        for rel in _WHITELIST_REL:
            _write(tmp_path, rel)
        _write(tmp_path, "scripts/notes.txt")

        failed, declaration, probes = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", n + 1, _UNIT)
        assert probes == n + 1
        assert outcome.status == "enforced"

    def test_violating_files_are_counted_and_record_failed(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/a_bad.py", 'with RECS_JSONL.open("a") as f: f.write("x")\n')
        _write(tmp_path, "scripts/b_clean.py")
        _write(tmp_path, "scripts/c_bad.py", 'with RECS_JSONL.open("w") as f: f.write("x")\n')

        failed, declaration, probes = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert len(failed) == 2
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert probes == 3
        assert outcome.status == "failed"

    def test_unreadable_entry_is_neither_scanned_nor_counted(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/readable.py")
        (tmp_path / "scripts" / "not_a_file.py").mkdir()

        failed, declaration, probes = _declared(tmp_path)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count) == ("examined", 1)
        assert probes == 1

    def test_scripts_dir_without_py_files_declares_vacuous_domain(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/README.md")
        _write(tmp_path, "scripts/ops_data_portal.py")

        failed, declaration, probes = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert probes == 0
        assert outcome.status == "vacuous"
