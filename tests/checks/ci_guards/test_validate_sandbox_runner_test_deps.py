"""Mirror test for scripts/checks/ci_guards/validate_sandbox_runner_test_deps.py (rec-4005 /
PLAN-backlog-health-probe-decides-pytest, the slice A inheritance guard). Every red case calls the
real check entrypoint (check_sandbox_runner_test_deps / validate_sandbox_runner_test_deps), never
a reimplemented negated assertion (rec-3952's class). Self-contained fixture helpers (No cross-
test imports -- tests/CLAUDE.md): never imported from test_validate_workflow_dependency_install.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ci_guards.validate_sandbox_runner_test_deps import (
    _module_imports_backlog_health_probe,
    check_sandbox_runner_test_deps,
    validate_sandbox_runner_test_deps,
)

_MODULE = "scripts.checks.ci_guards.validate_sandbox_runner_test_deps"
_SYSCTL = "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0"
_PROBE_INVOKE = ".venv/bin/python -m scripts.backlog_health probe --artifact-dir /tmp/backlog_health"
_INSTALL_FAST = ".venv/bin/pip install -r requirements.txt -r requirements-fast.txt"


def _write_workflow(tmp_path: Path, name: str, text: str) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(text, encoding="utf-8")


def _workflow(job_steps: str, job_id: str = "job") -> str:
    return f"name: w\non: push\njobs:\n  {job_id}:\n    runs-on: ubuntu-latest\n    steps:\n{job_steps}"


def _step(name: str, run_body: str) -> str:
    indented = "\n".join(f"          {line}" for line in run_body.splitlines())
    return f"      - name: {name}\n        run: |\n{indented}\n"


def _run(tmp_path: Path) -> tuple[list[str], int]:
    with patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path):
        return check_sandbox_runner_test_deps()


class TestSandboxRunnerTestDeps:
    def test_sysctl_job_without_test_runner_install_is_flagged(self, tmp_path: Path) -> None:
        """VP step 4's graduated node. The live-shape failure: a job carries the M1 sysctl marker
        and runs the sandbox probe, but never installs requirements-fast.txt."""
        steps = _step("Allow unprivileged user namespaces", _SYSCTL) + _step("Run probe", _PROBE_INVOKE)
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert examined == 1
        assert len(violations) == 1
        assert "requirements-fast.txt install" in violations[0]
        assert "M1" in violations[0]

    def test_positive_arm_sysctl_and_install_passes(self, tmp_path: Path) -> None:
        steps = (
            _step("Activate venv", _INSTALL_FAST)
            + _step("Allow unprivileged user namespaces", _SYSCTL)
            + _step("Run probe", _PROBE_INVOKE)
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 1

    def test_m2_arm_probe_invocation_without_sysctl_is_flagged(self, tmp_path: Path) -> None:
        """The ubuntu-22.04 / self-hosted-runner / relaxed-AppArmor-default escape and the
        Decision-162 sysctl-relocation escape: a job with NO sysctl step that still invokes the
        sandbox probe must be flagged just as strongly as the M1 case."""
        steps = _step("Run probe (no sysctl step at all)", _PROBE_INVOKE)
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert examined == 1
        assert len(violations) == 1
        assert "M2" in violations[0]

    def test_full_line_comment_does_not_arm_the_guard(self, tmp_path: Path) -> None:
        steps = _step("Commented-out sysctl", f"# {_SYSCTL}\necho noop")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_trailing_comment_does_not_arm_the_guard(self, tmp_path: Path) -> None:
        """Comment defence: a TRAILING '#'-comment mentioning the sysctl string, never executed,
        must not spoof M1 -- `_effective_lines` alone would miss this (it strips full-line
        comments only), which is why this guard carries its own comment-stripping helper."""
        steps = _step("Echo with trailing comment", f"echo hi  # {'apparmor_restrict_unprivileged_userns=0'}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_job_matching_neither_marker_is_never_required_to_install(self, tmp_path: Path) -> None:
        steps = _step(
            "Run census (structural read only)",
            ".venv/bin/python -m scripts.backlog_health census --artifact-dir /tmp/backlog_health",
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_validate_entrypoint_appends_a_failure_for_the_armed_unfixed_job(self, tmp_path: Path) -> None:
        """Calls the REGISTERED entrypoint (validate_sandbox_runner_test_deps), not the pure
        check_sandbox_runner_test_deps helper, so the red-case floor (LSA-03) sees a failing-path
        assertion derived from the registered attr itself, not only its underlying logic."""
        steps = _step("Allow unprivileged user namespaces", _SYSCTL) + _step("Run probe", _PROBE_INVOKE)
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        failed: list[str] = []
        with patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path):
            validate_sandbox_runner_test_deps(failed)
        assert len(failed) == 1
        assert "requirements-fast.txt" in failed[0]

    def test_declares_examined_on_the_non_vacuous_branch(self, tmp_path: Path) -> None:
        steps = (
            _step("Activate venv", _INSTALL_FAST)
            + _step("Allow unprivileged user namespaces", _SYSCTL)
            + _step("Run probe", _PROBE_INVOKE)
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        with (
            patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path),
            registry.outcome_scope("validate_sandbox_runner_test_deps"),
        ):
            failed: list[str] = []
            validate_sandbox_runner_test_deps(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "jobs"

    def test_declares_skipped_on_the_vacuous_branch(self, tmp_path: Path) -> None:
        steps = _step("Echo only", "echo hi")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        with (
            patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path),
            registry.outcome_scope("validate_sandbox_runner_test_deps"),
        ):
            failed: list[str] = []
            validate_sandbox_runner_test_deps(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "skipped"

    def test_live_backlog_health_workflow_carries_both_markers_and_passes(self) -> None:
        """The real .github/workflows/backlog-health.yml probe job carries BOTH M1 (:118) and
        M2 (:121) today and must pass once the combined install line lands (this plan's own
        workflow edit)."""
        violations, examined = check_sandbox_runner_test_deps()
        probe_violations = [v for v in violations if "::probe::" in v]
        assert probe_violations == []
        assert examined >= 1

    def test_module_imports_backlog_health_probe_direct_match(self) -> None:
        """The module IS scripts.backlog_health.probe -- no graph lookup needed."""
        assert _module_imports_backlog_health_probe("scripts.backlog_health.probe") is True

    def test_module_imports_backlog_health_probe_absent_from_graph(self) -> None:
        assert _module_imports_backlog_health_probe("scripts.nonexistent_module_xyz") is False

    def test_m2_transitive_arm_via_a_module_that_imports_probe(self, tmp_path: Path) -> None:
        """M2's "plus any module that imports scripts.backlog_health.probe" clause: a job
        invoking a REAL, importable module OTHER than the scripts.backlog_health package itself
        (scripts.backlog_health.__main__, which imports probe.py at module scope) is armed via
        the transitive-closure branch, not the literal `probe` verb text match."""
        steps = _step("Run via __main__", ".venv/bin/python -m scripts.backlog_health.__main__ probe")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert examined == 1
        assert len(violations) == 1
        assert "M2 (imports scripts.backlog_health.probe)" in violations[0]

    def test_malformed_workflow_yaml_is_skipped_not_crashed(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "broken.yml", "not: valid: yaml: [")
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_workflow_with_no_jobs_mapping_is_skipped(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "no-jobs.yml", "name: w\non: push\njobs: not-a-mapping\n")
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_job_with_no_steps_list_is_skipped(self, tmp_path: Path) -> None:
        _write_workflow(
            tmp_path, "no-steps.yml", "name: w\non: push\njobs:\n  job:\n    runs-on: ubuntu-latest\n    steps: not-a-list\n"
        )
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0
