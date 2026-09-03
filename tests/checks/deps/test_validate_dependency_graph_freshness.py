"""Tests for validate_dependency_graph_freshness() -- the Decision 80 freshness gate."""

from pathlib import Path

from scripts.checks.deps.validate_dependency_graph_freshness import validate_dependency_graph_freshness


class TestDependencyGraphFreshness:
    """Tests for validate_dependency_graph_freshness() -- the Decision 80 freshness gate."""

    def test_no_op_when_export_absent(self, tmp_path: Path) -> None:
        """No failure when docs/dependency-graph.json does not exist."""
        from unittest.mock import patch as _patch

        missing = tmp_path / "nonexistent.json"
        with _patch("scripts.dependency_graph._EXPORT_PATH", missing):
            failed: list[str] = []
            validate_dependency_graph_freshness(failed)
        assert not failed

    def test_fails_when_export_is_stale(self, tmp_path: Path) -> None:
        """A failure is appended when the committed export differs from the current graph."""
        import json
        from unittest.mock import patch as _patch

        export_path = tmp_path / "dependency-graph.json"
        stale = {"nodes": ["stale.module"], "edges": [], "roots": [], "metadata": {}, "symbol_nodes": []}
        export_path.write_text(json.dumps(stale), encoding="utf-8")
        with _patch("scripts.dependency_graph._EXPORT_PATH", export_path):
            failed: list[str] = []
            validate_dependency_graph_freshness(failed)
        assert len(failed) == 1
        msg = failed[0].lower()
        assert "stale" in msg or "drift" in msg or "dependency graph" in msg


class TestDependencyGraphFreshnessReporting:
    """The import-failure arm and the PASS summary line -- neither is reached by the two
    incumbent tests, both of which only inspect `failed`."""

    def test_import_failure_appends_a_failure(self, capsys) -> None:
        """A dependency_graph import that raises drives the except-branch append."""
        import sys
        from unittest.mock import patch as _patch

        with _patch.dict(sys.modules, {"scripts.dependency_graph": None}):
            failed: list[str] = []
            validate_dependency_graph_freshness(failed)

        assert failed == ["Dependency graph freshness"]
        assert "Could not import dependency_graph" in capsys.readouterr().out

    def test_clean_run_prints_the_pass_summary(self, tmp_path: Path, capsys) -> None:
        """No new failure -> the PASS summary line is printed."""
        from unittest.mock import patch as _patch

        missing = tmp_path / "nonexistent.json"
        with _patch("scripts.dependency_graph._EXPORT_PATH", missing):
            failed: list[str] = []
            validate_dependency_graph_freshness(failed)

        assert failed == []
        assert "PASS: dependency graph export is current" in capsys.readouterr().out
