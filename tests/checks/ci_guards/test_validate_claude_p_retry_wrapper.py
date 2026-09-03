"""Mirror for the REGISTERED validate_claude_p_retry_wrapper (its map_source_to_test path).

tests/test_ci_claude_p_retry.py drives only the pure helper _check_claude_p_raw_invocations and
the shell wrapper, so the registered check's own per-violation emission is executed by no test.
This mirror drives fn(failed) against a synthetic .github/workflows tree under a patched ROOT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks.ci_guards import validate_claude_p_retry_wrapper as subject

_UNWRAPPED = """name: agent
jobs:
  run:
    steps: [{run: 'claude -p "do the thing"'}]
"""

_CLEAN = """# a comment naming claude -p, which the guard skips

name: agent
jobs:
  run:
    steps:
      - run: command -v claude
      - run: claude --version
      - run: scripts/ci/claude_p_retry.sh claude -p "wrapped"
"""


def _workflows(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    return workflows


def _run(monkeypatch: pytest.MonkeyPatch, root: Path) -> list[str]:
    monkeypatch.setattr(subject._common, "ROOT", root)
    failed: list[str] = []
    subject.validate_claude_p_retry_wrapper(failed)
    return failed


class TestClaudePRetryWrapperEmission:
    def test_unwrapped_invocation_appends_one_failure_per_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (_workflows(tmp_path) / "agent.yml").write_text(_UNWRAPPED, encoding="utf-8")

        failed = _run(monkeypatch, tmp_path)

        assert failed == ["claude_p_retry wrapper: agent.yml:4: unwrapped `claude -p` invocation"]
        assert "FAIL: agent.yml:4: unwrapped `claude -p` invocation" in capsys.readouterr().out

    def test_clean_tree_exercising_every_skip_arm_appends_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (_workflows(tmp_path) / "agent.yml").write_text(_CLEAN, encoding="utf-8")

        failed = _run(monkeypatch, tmp_path)

        assert failed == []
        assert "PASS: all claude -p invocations route through scripts/ci/claude_p_retry.sh" in capsys.readouterr().out

    def test_unreadable_workflow_entry_is_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (_workflows(tmp_path) / "a-directory-not-a-file.yml").mkdir()

        failed = _run(monkeypatch, tmp_path)

        assert failed == []
