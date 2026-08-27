"""Tests for validate_warehouse_write_sources() -- warehouse-as-source invariant."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ops_governance.validate_warehouse_write_sources import validate_warehouse_write_sources


class TestValidateWarehouseWriteSources:
    """Tests for validate_warehouse_write_sources() -- warehouse-as-source invariant."""

    def test_catches_unwhitelisted_ops_recommendations_write(self, tmp_path: Path, capsys) -> None:
        """Detects writer.write('ops_*', ...) in non-whitelisted scripts."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_replay.py"
        bad_file.write_text(
            'writer.write("ops_recommendations", entry)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_replay.py" in e for e in failed)

    def test_catches_aliased_writer_call(self, tmp_path: Path, capsys) -> None:
        """Detects writer.write('ops_*', ...) where writer is any warehouse writer handle."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "bad_alias.py"
        bad_file.write_text(
            'writer = make_writer()\nwriter.write("ops_decisions", entry)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert len(failed) > 0
        assert any("bad_alias.py" in e for e in failed)

    def test_allows_whitelisted_portal_for_non_blocked_tables(self, tmp_path: Path, capsys) -> None:
        """ops_data_portal.py stays whitelisted for ops_* tables outside the blocked set."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        portal_file.write_text(
            'writer.write("ops_session_log", merged)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []

    def test_blocked_tables_rejected_even_for_whitelisted_portal(self, tmp_path: Path, capsys) -> None:
        """Decision 84 I-1: the blocked-tables leg applies to ALL files including the whitelist.

        Even whitelisted callers (ops_data_portal.py) must not write ops_recommendations,
        ops_decisions, ops_priority_queue or ops_execution_plans anywhere but the portal's
        writer transport -- readers serve DuckLake, so any other sink is a silent split-brain.
        The guard must fire regardless of whitelist status.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        portal_file = scripts_dir / "ops_data_portal.py"
        for table in ("ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_execution_plans"):
            portal_file.write_text(
                f'ops.compact("{table}", merged)\n',
                encoding="utf-8",
            )
            with patch("scripts.checks._common.ROOT", tmp_path):
                failed: list[str] = []
                validate_warehouse_write_sources(failed)
            assert len(failed) > 0, f"blocked-table leg must fire for {table}"
            assert any("outside the portal" in e for e in failed)

    def test_declares_examined_accounting_outcome(self, tmp_path: Path, capsys) -> None:
        """The check declares an examined() outcome, satisfying the check-accounting ratchet.

        Red/green pair for this module's baseline exit (config/check_accounting_baseline.yaml):
        on origin/main the check declared nothing, so pop_declaration() returned None and the
        run's CheckOutcome status was "undeclared". The count is asserted as a positive floor,
        not an exact literal -- the scanned-file population grows.
        """
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "clean_script.py").write_text("x = 1\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path), registry.outcome_scope("test_scope"):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
            declaration = registry.pop_declaration()
        assert declaration is not None, "check declared no accounting outcome"
        assert declaration.kind == "examined"
        assert declaration.unit == "files"
        assert declaration.count is not None and declaration.count > 0

    def test_unreadable_file_is_skipped_not_flagged(self, tmp_path: Path, capsys) -> None:
        """A file that raises OSError on read (e.g. a broken symlink) is skipped, not crashed on."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        bad_file = scripts_dir / "unreadable.py"
        bad_file.write_text('writer.write("ops_recommendations", entry)\n', encoding="utf-8")
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("pathlib.Path.read_text", side_effect=OSError("simulated read failure")),
        ):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []

    def test_clean_script_with_no_warehouse_writes_passes(self, tmp_path: Path, capsys) -> None:
        """Scripts that only call portal functions (file_rec) pass cleanly."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        clean_file = scripts_dir / "clean_script.py"
        clean_file.write_text(
            "from scripts.ops_data_portal import file_rec\nfile_rec({'title': 'test'})\n",
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_warehouse_write_sources(failed)
        assert failed == []
