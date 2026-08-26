"""sync orchestration + CLI + table-map invariants + upsert concern:
tests/sync/ops/test_sync_cli.py (rec-2709 Wave 10).

Split from the former tests/test_sync_ops.py monolith: TestSync, TestMain,
TestTelemetryMappings, TestPipelineConsolidation, TestUpsertCacheRow.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# sync() tests
# ---------------------------------------------------------------------------


class TestSync:
    def test_sync_returns_pulled_counts(self):
        """sync() delegates to _rebuild_local_cache() and returns its counts under "pulled"."""
        with patch("scripts.sync.ops._rebuild_local_cache", return_value={"ops_recommendations": 50}) as mock_rebuild:
            from scripts.sync.ops import sync

            result = sync(profile="test-profile")

        mock_rebuild.assert_called_once_with("test-profile")
        assert result == {"pulled": {"ops_recommendations": 50}}


# ---------------------------------------------------------------------------
# main() / CLI tests
# ---------------------------------------------------------------------------


class TestMain:
    def test_help_exits_0(self):
        """sync_ops --help exits 0."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync.ops", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 0

    def test_drain_subcommand(self):
        """sync_ops drain subcommand is removed -- argparse exits non-zero."""
        import sys

        import pytest

        import scripts.sync.ops as _sync_ops

        old_argv = sys.argv
        sys.argv = ["sync_ops", "drain"]
        try:
            with pytest.raises(SystemExit) as exc_info:
                _sync_ops.main()
            assert exc_info.value.code != 0
        finally:
            sys.argv = old_argv


# ---------------------------------------------------------------------------
# Telemetry table mapping tests
# ---------------------------------------------------------------------------


class TestTelemetryMappings:
    """Telemetry + non-migrated ops tables were removed from the sync maps (public-migration).

    ops_recommendations / ops_decisions / ops_priority_queue / ops_execution_plans (migrated at
    T2.26 c9) are migrated to the personal account; telemetry_* and ops_session_log must NOT
    appear in the maps, or sync_ops.pull would issue TABLE_NOT_FOUND queries on every sync.
    """

    _TELEMETRY_TABLES = [
        "telemetry_sessions",
        "telemetry_phases",
        "telemetry_steps",
        "telemetry_process_events",
        "telemetry_model_calls",
        "telemetry_transcripts",
        "telemetry_agent_invocations",
    ]
    _REMOVED_OPS_TABLES = ["ops_session_log"]

    def test_telemetry_tables_absent_from_maps(self):
        """No telemetry table is mapped (they are not migrated to the personal account)."""
        from scripts.sync.ops import _TABLE_TO_LOCAL

        for table in self._TELEMETRY_TABLES:
            assert table not in _TABLE_TO_LOCAL, f"{table} should be removed from _TABLE_TO_LOCAL"

    def test_non_migrated_ops_tables_absent(self):
        """ops_session_log is not migrated and must be absent."""
        from scripts.sync.ops import _TABLE_TO_LOCAL

        for table in self._REMOVED_OPS_TABLES:
            assert table not in _TABLE_TO_LOCAL

    def test_migrated_ops_tables_present(self):
        """All four migrated tables are cached locally from the DuckLake reader (Decision 84 I-1)."""
        import scripts.sync.ops as sync_ops

        expected = {"ops_recommendations", "ops_decisions", "ops_priority_queue", "ops_execution_plans"}
        assert set(sync_ops._TABLE_TO_LOCAL) == expected


class TestPipelineConsolidation:
    """Tests for pipeline consolidation changes (Decision 69)."""

    def test_coerce_ops_rec_row_rejects_dec_ids(self):
        """_coerce_ops_rec_row returns None and writes a reject log for dec-* prefixed IDs."""
        from unittest.mock import patch

        from scripts.sync.ops import _coerce_ops_rec_row

        row = {"id": "dec-42", "title": "Test", "source": "manual", "effort": "S", "priority": "Low"}
        with patch("scripts.sync.ops._write_sync_reject") as mock_reject:
            result = _coerce_ops_rec_row(row)

        assert result is None
        mock_reject.assert_called_once()
        call_args = mock_reject.call_args[0]
        assert call_args[0] is row
        assert "invalid id prefix" in call_args[1]

    def test_coerce_ops_rec_row_accepts_valid_prefixes(self):
        """_coerce_ops_rec_row returns the row for rec-, agent-, and test- prefixes."""
        from scripts.sync.ops import _coerce_ops_rec_row

        for valid_id in ("rec-001", "agent-abc", "test-xyz"):
            row = {"id": valid_id, "dependencies": "", "tags": "", "execution_steps": "", "automatable": ""}
            result = _coerce_ops_rec_row(row)
            assert result is not None, f"expected non-None for id={valid_id!r}"
            assert result["id"] == valid_id

    def test_drain_cli_removed(self):
        """Running `python -m scripts.sync.ops drain` exits non-zero (subcommand removed)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync.ops", "drain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent.parent.parent),
        )
        assert result.returncode != 0

    def test_pull_cli_removed(self):
        """Running `python -m scripts.sync.ops pull` exits non-zero (subcommand removed)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "scripts.sync.ops", "pull"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(Path(__file__).parent.parent.parent.parent),
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# upsert_cache_row() tests
# ---------------------------------------------------------------------------


class TestUpsertCacheRow:
    def test_devnull_sentinel_returns_zero_no_tmp_written(self) -> None:
        """upsert_cache_row with path=Path(os.devnull) returns 0 and writes no .tmp file."""
        from scripts.sync import ops as sync_ops

        result = sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-9999", "title": "t"}, path=Path(os.devnull))
        assert result == 0
        assert not Path(os.devnull + ".tmp").exists()

    def test_real_path_writes_cache_row(self, tmp_path: Path) -> None:
        """upsert_cache_row with a real path writes the row and returns row count."""
        from scripts.sync import ops as sync_ops

        cache_file = tmp_path / "recs.jsonl"
        result = sync_ops.upsert_cache_row("ops_recommendations", {"id": "rec-0001", "title": "hello"}, path=cache_file)
        assert result == 1
        assert cache_file.exists()
        row = json.loads(cache_file.read_text(encoding="utf-8").strip())
        assert row["id"] == "rec-0001"
