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

import re
from pathlib import Path

import pytest
import yaml

from scripts.checks import registry
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


_CHECK = "validate_workflow_agent_safety"
_UNIT = "headless_claude_steps"
_REPO_ROOT = Path(__file__).parents[3]
_INVOCATION = re.compile(r"\bclaude\s+(?:-p|--print)\b")

_UNMASKED_WORKFLOW = """\
name: unmasked
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Plain agent
        run: claude -p "summarise the diff"
      - name: Not an agent
        run: echo hi || true
      - uses: anthropics/claude-code-action@v1
"""


def _declared(workflows_dir: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], registry._Declaration | None]:
    registry.pop_declaration()
    failed = _run(workflows_dir, monkeypatch)
    return failed, registry.pop_declaration()


def _live_headless_steps() -> int:
    count = 0
    for wf_path in (_REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        workflow = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        for job in (workflow.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if isinstance(step.get("run"), str) and _INVOCATION.search(step["run"]):
                    count += 1
    return count


class TestWorkflowAgentSafetyAccountingDeclaration:
    """The check declares how many headless claude -p steps it judged, so a run records enforced with a
    count that tracks the workflows on disk -- not a constant and not the violation count."""

    def test_real_tree_declares_every_headless_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The live tree's only masked agent call goes through scripts/ci/claude_p_retry.sh, which the raw
        `claude -p` pattern does not match, so the honest live count may be 0 and the run vacuous."""
        expected = _live_headless_steps()

        failed, declaration = _declared(_REPO_ROOT / ".github" / "workflows", monkeypatch)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)
        assert outcome.status == ("enforced" if expected else "vacuous")

    def test_count_spans_files_and_ignores_non_invocations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "guarded.yml").write_text(_GUARDED_WORKFLOW, encoding="utf-8")
        (tmp_path / "unmasked.yml").write_text(_UNMASKED_WORKFLOW, encoding="utf-8")

        failed, declaration = _declared(tmp_path, monkeypatch)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 2, _UNIT)

    def test_no_headless_steps_declares_vacuous_domain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        failed, declaration = _declared(tmp_path, monkeypatch)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "vacuous"

    def test_violating_and_unparseable_workflows_still_record_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "masked.yml").write_text(_MASKED_UNGUARDED_WORKFLOW, encoding="utf-8")
        (tmp_path / "broken.yml").write_text(_UNPARSEABLE_WORKFLOW, encoding="utf-8")

        failed, declaration = _declared(tmp_path, monkeypatch)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == ["Workflow agent-safety"]
        assert declaration is not None and declaration.count == 1
        assert outcome.status == "failed"
