"""TestMaterializeCheck (Decision 176 concern-split decomposition of the former
tests/test_verification_graduation.py monolith) -- the six-slot kernel materializer, moved
verbatim from the pre-decomposition module."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from scripts import verification_graduation as vg
from scripts.verification_checks import CheckStatus


class TestMaterializeCheck:
    def test_grep_count_materializes_and_matches_live_run(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("sentinel line\nother line\n", encoding="utf-8")
        row = {
            "check_id": "t-grep",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "target.txt", "pattern": "sentinel", "operator": "eq", "count": 1},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        result = check.run()
        assert result.status == CheckStatus.PASS

    def test_file_presence_exists_mode(self, tmp_path: Path) -> None:
        (tmp_path / "present.txt").write_text("x", encoding="utf-8")
        row = {"check_id": "t-fp", "primitive_slot": "file_presence", "check_spec": {"path": "present.txt", "mode": "exists"}}
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_file_presence_absent_mode(self, tmp_path: Path) -> None:
        row = {"check_id": "t-fa", "primitive_slot": "file_presence", "check_spec": {"path": "missing.txt", "mode": "absent"}}
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_command_exit_zero_materializes(self, tmp_path: Path) -> None:
        row = {"check_id": "t-cmd", "primitive_slot": "command_exit_zero", "check_spec": {"command": ["true"]}}
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_command_output_matches_materializes(self, tmp_path: Path) -> None:
        row = {
            "check_id": "t-com",
            "primitive_slot": "command_output_matches",
            "check_spec": {"command": ["echo", "hello"], "expected": "hello", "use_regex": False},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_test_selector_materializes(self, tmp_path: Path) -> None:
        row = {
            "check_id": "t-sel",
            "primitive_slot": "test_selector",
            "check_spec": {"node_id": "tests/test_fake.py::T::test_y"},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="1 passed", stderr=""),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_metric_under_threshold_materializes(self, tmp_path: Path) -> None:
        row = {
            "check_id": "t-metric",
            "primitive_slot": "metric_under_threshold",
            "check_spec": {"command": ["echo", "0.5"], "threshold": 1.0},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_materialize_check_uses_live_tree_when_no_repoint(self, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("marker\n", encoding="utf-8")
        row = {
            "check_id": "t-live",
            "primitive_slot": "grep_count",
            "check_spec": {"path": str(tmp_path / "f.txt"), "pattern": "marker", "operator": "eq", "count": 1},
        }
        check = vg.materialize_check(row)
        assert check.run().status == CheckStatus.PASS

    def test_unknown_slot_raises(self) -> None:
        row = {"check_id": "t-bad", "primitive_slot": "not_a_slot", "check_spec": {}}
        with pytest.raises(vg.GraduationError, match="unknown primitive_slot"):
            vg.materialize_check(row)

    def test_missing_required_key_raises(self) -> None:
        row = {"check_id": "t-missing", "primitive_slot": "grep_count", "check_spec": {"path": "x"}}
        with pytest.raises(vg.GraduationError, match="missing required key"):
            vg.materialize_check(row)

    def test_bad_file_presence_mode_raises(self, tmp_path: Path) -> None:
        row = {"check_id": "t-mode", "primitive_slot": "file_presence", "check_spec": {"path": "x", "mode": "bogus"}}
        with pytest.raises(vg.GraduationError, match="mode must be"):
            vg.materialize_check_in_tree(row, tmp_path)
