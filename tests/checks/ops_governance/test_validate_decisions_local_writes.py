"""Tests for validate_decisions_local_writes() in scripts/validate.py."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks import registry
from scripts.checks.ops_governance import validate_decisions_local_writes as decisions_local_writes_module
from scripts.checks.ops_governance.validate_decisions_local_writes import validate_decisions_local_writes


class TestValidateDecisionsLocalWrites:
    """Tests for validate_decisions_local_writes() (D10)."""

    def test_catches_decisions_jsonl_open_write(self, tmp_path: Path, capsys) -> None:
        """Detects DECISIONS_JSONL.open('w') in a non-whitelisted script."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bad_script.py").write_text(
            'with DECISIONS_JSONL.open("w", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert len(failed) > 0
        assert any("bad_script.py" in e for e in failed)

    def test_catches_decisions_jsonl_open_append(self, tmp_path: Path, capsys) -> None:
        """Detects DECISIONS_JSONL.open('a') in a non-whitelisted script."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "replay_script.py").write_text(
            'with DECISIONS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert len(failed) > 0

    def test_allows_whitelist_ops_data_portal(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "ops_data_portal.py").write_text(
            'with DECISIONS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert failed == []

    def test_allows_whitelist_sync_ops(self, tmp_path: Path, capsys) -> None:
        """scripts/sync/ops.py is whitelisted and does not trigger the rule."""
        scripts_dir = tmp_path / "scripts"
        sync_dir = scripts_dir / "sync"
        sync_dir.mkdir(parents=True)
        (sync_dir / "ops.py").write_text(
            'with DECISIONS_JSONL.open("a", encoding="utf-8") as f: f.write("x")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert failed == []

    def test_clean_scripts_directory_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts that only read the decisions cache pass without failures."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "clean_reader.py").write_text(
            "from scripts.ops_data_portal import file_decision\nfile_decision({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_decisions_local_writes(failed)
        assert failed == []


_CHECK = "validate_decisions_local_writes"
_UNIT = "py files"
_REPO_ROOT = Path(__file__).parents[3]
_WHITELIST_REL = (
    "scripts/ops_data_portal.py",
    "scripts/sync/ops.py",
)


class _ProbeCountingRe:
    """Stands in for the module's `re`: the first compiled pattern counts its search() calls, i.e. the
    files whose content the check's pattern loop actually scanned (each scanned file probes it exactly once)."""

    DOTALL = re.DOTALL

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
            def search(self, content: str) -> re.Match[str] | None:
                counter.probes += 1
                return compiled.search(content)

        return _Counting()


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _declared(root: Path) -> tuple[list[str], registry._Declaration | None, int]:
    registry.pop_declaration()
    failed: list[str] = []
    probe = _ProbeCountingRe()
    with patch("scripts.checks._common.ROOT", root), patch.object(decisions_local_writes_module, "re", probe):
        validate_decisions_local_writes(failed)
    return failed, registry.pop_declaration(), probe.probes


class TestDecisionsLocalWritesAccountingDeclaration:
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
            _write(tmp_path, rel, 'with DECISIONS_JSONL.open("a") as f: f.write("x")\n')
        _write(tmp_path, "scripts/notes.txt")

        failed, declaration, probes = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", n + 1, _UNIT)
        assert probes == n + 1
        assert outcome.status == "enforced"

    def test_violating_files_are_counted_and_record_failed(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/a_bad.py", 'with DECISIONS_JSONL.open("a") as f: f.write("x")\n')
        _write(tmp_path, "scripts/b_clean.py")
        _write(tmp_path, "scripts/c_bad.py", 'with DECISIONS_JSONL.open("w") as f: f.write("x")\n')

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
