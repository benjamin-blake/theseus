"""Mirror for the REGISTERED validate_claude_p_retry_wrapper (its map_source_to_test path).

tests/test_ci_claude_p_retry.py drives only the pure helper _check_claude_p_raw_invocations and
the shell wrapper, so the registered check's own per-violation emission is executed by no test.
This mirror drives fn(failed) against a synthetic .github/workflows tree under a patched ROOT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import registry
from scripts.checks.ci_guards import validate_claude_p_retry_wrapper as subject

_REPO_ROOT = Path(__file__).parents[3]
_UNIT = "workflow_files"

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


def _declared(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[list[str], registry._Declaration | None]:
    registry.pop_declaration()
    failed = _run(monkeypatch, root)
    return failed, registry.pop_declaration()


class TestClaudePRetryWrapperAccountingDeclaration:
    """The guard declares how many workflow files it read, so a run records enforced with a count
    that tracks the readable .github/workflows/*.yml set -- not a constant and not the glob size."""

    def test_real_tree_declares_every_readable_workflow_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = sum(1 for p in (_REPO_ROOT / ".github" / "workflows").glob("*.yml") if p.is_file())

        failed, declaration = _declared(monkeypatch, _REPO_ROOT)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)

    def test_count_excludes_unreadable_and_non_yml_entries(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workflows = _workflows(tmp_path)
        (workflows / "a.yml").write_text(_CLEAN, encoding="utf-8")
        (workflows / "b.yml").write_text(_CLEAN, encoding="utf-8")
        (workflows / "c.yaml").write_text(_UNWRAPPED, encoding="utf-8")
        (workflows / "d-directory.yml").mkdir()

        failed, declaration = _declared(monkeypatch, tmp_path)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count) == ("examined", 2)

    def test_empty_workflows_dir_declares_vacuous_domain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _workflows(tmp_path)

        failed, declaration = _declared(monkeypatch, tmp_path)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)

    def test_violation_still_records_failed_over_examined(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (_workflows(tmp_path) / "agent.yml").write_text(_UNWRAPPED, encoding="utf-8")

        failed, declaration = _declared(monkeypatch, tmp_path)
        outcome = registry.build_outcome("validate_claude_p_retry_wrapper", "check", declaration, bool(failed))

        assert declaration is not None and declaration.count == 1
        assert outcome.status == "failed"

    def test_list_helper_returns_violations_without_read_count(self, tmp_path: Path) -> None:
        workflows = _workflows(tmp_path)
        (workflows / "agent.yml").write_text(_UNWRAPPED, encoding="utf-8")
        (workflows / "clean.yml").write_text(_CLEAN, encoding="utf-8")

        assert subject._check_claude_p_raw_invocations(workflows) == ["agent.yml:4: unwrapped `claude -p` invocation"]
