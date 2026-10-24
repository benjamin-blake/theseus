"""close concern: tests/session/postflight/test_close.py (rec-2709 Wave 10).

Split from the former tests/test_session_postflight.py monolith: TestCloseMode.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.session_postflight_module import postflight as _postflight


class TestCloseMode:
    """Tests for session_postflight.run_close()."""

    def _mock_sanity_result(self, status: str = "PASS") -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = json.dumps({"status": status})
        r.stderr = ""
        return r

    def test_intent_verification_with_plan(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Intent text is extracted from the plan file and included in output."""
        plan = tmp_path / "PLAN-test.md"
        plan.write_text(
            "## Intent\nVerify the login feature works correctly.\n\n## Scope\n",
            encoding="utf-8",
        )
        diff_result = MagicMock(returncode=0, stdout="1 file changed, 10 insertions(+)", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=plan),
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
        ):
            rc = _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["details"]["intent_text"] == "Verify the login feature works correctly."
        assert data["sanity_status"] == "PASS"

    def test_intent_achieved_true_when_files_changed(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """intent_achieved is True when git diff shows changes."""
        plan = tmp_path / "PLAN-test.md"
        plan.write_text("## Intent\nDo something.\n\n## Scope\n", encoding="utf-8")
        diff_result = MagicMock(returncode=0, stdout="2 files changed, 5 insertions(+)", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=plan),
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["intent_achieved"] is True

    def test_session_log_entry_template_generated(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """session_log_entry contains branch, plan name, and diff summary."""
        plan = tmp_path / "PLAN-my-feature.md"
        plan.write_text("## Intent\nShip the feature.\n\n## Scope\n", encoding="utf-8")
        diff_result = MagicMock(returncode=0, stdout="3 files changed", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=plan),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
            patch("scripts.postflight._common._current_branch", return_value="agent/my-feature"),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        log = data["session_log_entry"]
        assert "agent/my-feature" in log
        assert "PLAN-my-feature.md" in log
        assert "3 files changed" in log

    def test_no_plan_file_intent_is_none(self, capsys: pytest.CaptureFixture) -> None:
        """When no plan file exists, intent_achieved is None."""
        diff_result = MagicMock(returncode=0, stdout="", stderr="")
        sanity_result = self._mock_sanity_result("PASS")

        with (
            patch("scripts.postflight._common.find_plan_file", return_value=None),
            patch("scripts.postflight._common._current_branch", return_value="agent/test"),
            patch("scripts.postflight._common._run", side_effect=[diff_result, sanity_result]),
        ):
            _postflight.run_close()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["intent_achieved"] is None
