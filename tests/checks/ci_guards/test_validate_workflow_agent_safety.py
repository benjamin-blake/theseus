"""Mirror test for scripts/checks/ci_guards/validate_workflow_agent_safety.py.

The module has exactly one emission site (validate_workflow_agent_safety.py:24) and before this
file no test called the registered wrapper at all -- its only repo-wide reference was a name
literal in tests/checks/registry/test_sequences.py. These tests drive fn(failed) over a synthetic
workflows tree and assert EXACT list equality on failed, so neutering that append cannot pass.

The check imports no scripts.checks._common: its root knob is the helper module's own global,
scripts.check_workflow_agent_safety.WORKFLOWS_DIR, which is what _run monkeypatches. The helper
itself is already fully mirrored at tests/test_check_workflow_agent_safety.py; this file covers
the WRAPPER only and deliberately does not restate the helper's detection matrix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks.ci_guards.validate_workflow_agent_safety import validate_workflow_agent_safety

_GUARDED_WORKFLOW = """\
name: guarded
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Guarded headless agent
        run: |
          claude -p "summarise the diff" > out.txt || true
          grep -q . out.txt || { echo "::error::empty agent output"; exit 1; }
"""

_MASKED_UNGUARDED_WORKFLOW = """\
name: masked
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Unguarded headless agent
        run: |
          claude -p "summarise the diff" > out.txt || true
"""

_UNPARSEABLE_WORKFLOW = "jobs: [unclosed\n"


def _run(workflows_dir: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr("scripts.check_workflow_agent_safety.WORKFLOWS_DIR", workflows_dir)
    failed: list[str] = []
    validate_workflow_agent_safety(failed)
    return failed


class TestWorkflowAgentSafetyEmission:
    """fn(failed) over a synthetic .github/workflows tree, both arms of the single emission site."""

    def test_clean_workflows_append_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "guarded.yml").write_text(_GUARDED_WORKFLOW, encoding="utf-8")
        failed = _run(tmp_path, monkeypatch)
        assert failed == []
        assert "All headless claude -p steps assert their output." in capsys.readouterr().out

    def test_masked_unguarded_step_appends_a_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "masked.yml").write_text(_MASKED_UNGUARDED_WORKFLOW, encoding="utf-8")
        failed = _run(tmp_path, monkeypatch)
        out = capsys.readouterr().out
        assert failed == ["Workflow agent-safety"]
        assert "Workflow agent-safety violations:" in out
        assert "Unguarded headless agent" in out

    def test_unparseable_workflow_appends_a_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "broken.yml").write_text(_UNPARSEABLE_WORKFLOW, encoding="utf-8")
        failed = _run(tmp_path, monkeypatch)
        out = capsys.readouterr().out
        assert failed == ["Workflow agent-safety"]
        assert "YAML parse error" in out


def test_live_workflows_pass() -> None:
    """Unpatched smoke over the REAL .github/workflows tree, which must still satisfy the check.

    A red here is a finding about a workflow, not about this mirror.
    """
    failed: list[str] = []
    validate_workflow_agent_safety(failed)
    assert failed == []
