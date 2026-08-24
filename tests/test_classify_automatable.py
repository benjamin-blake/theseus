"""Tests for scripts.classify_automatable."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.classify_automatable import _BOUNDARY_PATTERNS, _count_sloc, _is_boundary_file, classify, main, run
from scripts.ops_data_portal import compute_automatable, load_capabilities


def _make_rec(
    effort: str = "XS",
    risk: str = "low",
    file: str = "scripts/some_file.py",
    status: str = "open",
) -> dict:
    return {
        "id": "rec-999",
        "status": status,
        "effort": effort,
        "risk": risk,
        "file": file,
        "automatable": False,
    }


class TestClassify:
    def test_xs_low_risk_small_file(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "small.py").write_text("x = 1\n" * 100, encoding="utf-8")
        rec = _make_rec(effort="XS", risk="low", file="scripts/small.py")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is True

    def test_m_effort_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(effort="M")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_high_risk_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(risk="high")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_large_file_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "big.py").write_text("x = 1\n" * 900, encoding="utf-8")
        rec = _make_rec(file="scripts/big.py")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_boundary_file_rejected(self) -> None:
        rec = _make_rec(file="scripts/executor/plan.py")
        assert classify(rec) is False

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(file="nonexistent.py")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False

    def test_empty_file_field_rejected(self, tmp_path: Path) -> None:
        rec = _make_rec(file="")
        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            assert classify(rec) is False


class TestIsBoundaryFile:
    def test_executor_dir(self) -> None:
        assert _is_boundary_file("scripts/executor/step_runner.py") is True

    def test_non_boundary(self) -> None:
        assert _is_boundary_file("scripts/session/preflight.py") is False


class TestCountSloc:
    def test_missing_file_returns_zero(self, tmp_path: Path) -> None:
        assert _count_sloc(tmp_path / "nonexistent.py") == 0


class TestRun:
    def test_jsonl_round_trip(self, tmp_path: Path) -> None:
        # Create target files
        (tmp_path / "scripts").mkdir()
        small = tmp_path / "scripts" / "ok.py"
        small.write_text("x = 1\n" * 50, encoding="utf-8")
        big = tmp_path / "scripts" / "big.py"
        big.write_text("x = 1\n" * 900, encoding="utf-8")

        recs = [
            _make_rec(effort="XS", risk="low", file="scripts/ok.py"),
            _make_rec(effort="L", risk="low", file="scripts/big.py"),
        ]
        recs_file = tmp_path / "recs.jsonl"
        recs_file.write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n",
            encoding="utf-8",
        )

        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            auto, non_auto = run(recs_file)

        assert auto == 1
        assert non_auto == 1

        lines = [json.loads(ln) for ln in recs_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines[0]["automatable"] is True
        assert lines[1]["automatable"] is False

    def test_jsonl_round_trip_skips_blank_lines_and_non_open(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "ok.py").write_text("x = 1\n" * 50, encoding="utf-8")

        closed_rec = _make_rec(effort="XS", risk="low", file="scripts/ok.py", status="closed")
        open_rec = _make_rec(effort="XS", risk="low", file="scripts/ok.py", status="open")
        recs_file = tmp_path / "recs.jsonl"
        recs_file.write_text(
            json.dumps(closed_rec) + "\n\n" + json.dumps(open_rec) + "\n",
            encoding="utf-8",
        )

        with patch("scripts.classify_automatable._REPO_ROOT", tmp_path):
            auto, non_auto = run(recs_file)

        assert auto == 1
        assert non_auto == 0

        raw_lines = recs_file.read_text(encoding="utf-8").splitlines()
        assert raw_lines[0] == json.dumps(closed_rec, ensure_ascii=False)
        assert raw_lines[1] == ""
        assert json.loads(raw_lines[2])["automatable"] is True


class TestMain:
    def test_main_prints_summary_and_returns_zero(self, capsys) -> None:
        with patch("scripts.classify_automatable.run", return_value=(3, 5)):
            result = main()

        assert result == 0
        assert "Classified 8 open recs: 3 automatable, 5 non-automatable" in capsys.readouterr().out


def test_boundary_covers_live_supervisor_surface() -> None:
    """Decision 117 SSOT declares the live supervisor surface, closing the self-referential
    hole where capabilities.yaml did not protect itself. XS is asserted (not S) because the
    risk-ceiling formula already denies at S+ regardless of boundary declaration -- only XS
    (R=1.0 <= ceiling=1.0) isolates the boundary-pattern branch from the risk-score branch."""
    boundary_patterns = load_capabilities().get("boundary_patterns", [])
    live_surfaces = (
        ".claude/commands/develop-executor.md",
        ".claude/skills/executor-rca/SKILL.md",
        "config/agent/executor/capabilities.yaml",
    )
    for path in live_surfaces:
        assert any(pat in path for pat in boundary_patterns), f"no boundary pattern matches {path}"
        assert compute_automatable(path, "XS") is False, f"{path} is automatable at XS effort"


def test_boundary_lists_move_in_lockstep() -> None:
    """scripts/classify_automatable.py's duplicate list must track capabilities.yaml row-for-row
    for the dead/live rows this plan touches (Decision 117's reversal condition), not full parity."""
    ssot_patterns = load_capabilities().get("boundary_patterns", [])
    moved_rows = ("develop-executor", "executor-rca", "executor/capabilities.yaml")
    assert "develop-executor.prompt.md" not in ssot_patterns
    assert "develop-executor.prompt.md" not in _BOUNDARY_PATTERNS
    for row in moved_rows:
        assert row in ssot_patterns, f"{row} missing from capabilities.yaml boundary_patterns"
        assert row in _BOUNDARY_PATTERNS, f"{row} missing from _BOUNDARY_PATTERNS"
