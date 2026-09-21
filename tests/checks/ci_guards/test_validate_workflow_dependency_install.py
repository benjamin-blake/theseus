"""Mirror test for scripts/checks/ci_guards/validate_workflow_dependency_install.py (ULF-01
forward-fix). Every red case calls the real check entrypoint
(check_workflow_dependency_installs / validate_workflow_dependency_install), never a reimplemented
negated assertion (rec-3952's class).

Fixture invocations target REAL, importable modules so the NEED predicate exercises the genuine
scripts.dependency_graph closure walk rather than a synthetic stand-in:
  - scripts.checks.misc.validate_ghas_probe: needs yaml transitively (scripts.checks.registry ->
    scripts.checks._common's module-level `import yaml`) -- the "needs install" fixture target.
  - scripts.ci.convergence_classify: stdlib-only top to bottom (verified) -- the "no install
    needed" fixture target, mirroring terraform-apply-sandbox.yml's two legitimately-bare jobs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ci_guards.validate_workflow_dependency_install import (
    _blank_shell_comments,
    _module_needs_third_party,
    _module_to_path,
    _top_level_third_party_roots,
    check_workflow_dependency_installs,
    validate_workflow_dependency_install,
)

_MODULE = "scripts.checks.ci_guards.validate_workflow_dependency_install"
_NEEDS_INSTALL = "scripts.checks.misc.validate_ghas_probe"
_NO_INSTALL_NEEDED = "scripts.ci.convergence_classify"


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
    """Point the workflow SCAN at tmp_path while leaving _REAL_ROOT (the NEED resolution's module
    lookup) pointed at the genuine repo -- fixtures invoke real, importable modules, so need
    resolution must read the real scripts/ tree regardless of where the fixture YAML lives."""
    with patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path):
        return check_workflow_dependency_installs()


class TestInstallShapesAndPositions:
    """Pass paths: all three real install shapes, at both install positions."""

    def test_pip_install_dash_r_requirements_in_a_preceding_step(self, tmp_path: Path) -> None:
        steps = _step("Install deps", "pip install -r requirements.txt") + _step("Run probe", f"python -m {_NEEDS_INSTALL}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 1

    def test_pip_install_pkgs_in_a_preceding_step(self, tmp_path: Path) -> None:
        steps = _step("Install deps", "pip install pyyaml pydantic") + _step("Run probe", f"python3 -m {_NEEDS_INSTALL}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 1

    def test_venv_shape_in_a_preceding_step(self, tmp_path: Path) -> None:
        steps = _step(
            "Activate venv",
            "python -m venv .venv\n.venv/bin/pip install --quiet --upgrade pip\n.venv/bin/pip install -r requirements.txt",
        ) + _step("Run probe", f".venv/bin/python -m {_NEEDS_INSTALL}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 1

    def test_install_in_the_same_run_body_textually_before_the_invocation(self, tmp_path: Path) -> None:
        """reconcile.yml:264-265's shape: install and invoke in ONE step's run: block."""
        steps = _step(
            "Recheck",
            f"pip install boto3 requests\nOUT=$(python3 -m {_NEEDS_INSTALL})",
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 1

    def test_stdlib_only_module_needs_no_install_anywhere(self, tmp_path: Path) -> None:
        """terraform-apply-sandbox.yml::apply-sandbox/::advisory-status shape: no install step at
        all, and no violation, because the invoked module's closure is stdlib-only."""
        steps = _step("Classify", f"python3 -m {_NO_INSTALL_NEEDED} --refusal")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 1


class TestRedCases:
    """Every red case calls check_workflow_dependency_installs() -- the real entrypoint."""

    def test_install_after_invoke_with_no_same_body_install_fails(self, tmp_path: Path) -> None:
        steps = _step("Run probe", f"python -m {_NEEDS_INSTALL}") + _step("Install deps (too late)", "pip install pyyaml")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        result = _run(tmp_path)
        assert result[0]
        violations, examined = result
        assert examined == 1
        assert len(violations) == 1
        assert "invokes scripts with no preceding install step" in violations[0]
        assert _NEEDS_INSTALL in violations[0]

    def test_install_in_a_different_job_fails(self, tmp_path: Path) -> None:
        text = (
            "name: w\non: push\njobs:\n"
            "  installer:\n    runs-on: ubuntu-latest\n    steps:\n" + _step("Install deps", "pip install pyyaml") + "\n"
            "  runner:\n    runs-on: ubuntu-latest\n    steps:\n" + _step("Run probe", f"python -m {_NEEDS_INSTALL}")
        )
        _write_workflow(tmp_path, "w.yml", text)
        violations, examined = _run(tmp_path)
        assert examined == 1
        assert len(violations) == 1
        assert "invokes scripts with no preceding install step" in violations[0]

    def test_no_install_at_all_fails(self, tmp_path: Path) -> None:
        steps = _step("Run probe", f"python -m {_NEEDS_INSTALL}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert examined == 1
        assert len(violations) == 1
        assert "invokes scripts with no preceding install step" in violations[0]

    def test_permission_token_match_is_not_an_invocation(self, tmp_path: Path) -> None:
        """ci-rca.yml:464's shape: a `-m scripts.` lookalike inside a Bash(...) permission token
        nested in --allowedTools is a permission STRING, not an invocation. No install anywhere in
        this job, and no OTHER real invocation either -- if this were misdetected as an
        invocation, it would fail; the guard must find nothing to examine at all."""
        steps = _step(
            "Dispatch subagent",
            f'claude -p --allowedTools "Read,Bash(bin/venv-python -m {_NEEDS_INSTALL}:*)" || true',
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_comment_only_install_text_does_not_suppress_the_violation(self, tmp_path: Path) -> None:
        """A `#`-comment merely MENTIONING install text is never executed -- it must not spoof the
        install scan and suppress a real, uninstalled invocation (code-review finding)."""
        steps = _step(
            "Run probe",
            f"# pip install pyyaml (not real, just a note)\npython -m {_NEEDS_INSTALL}",
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        result = _run(tmp_path)
        assert result[0]
        violations, examined = result
        assert examined == 1
        assert len(violations) == 1
        assert "invokes scripts with no preceding install step" in violations[0]

    def test_disallowed_tools_value_is_also_excluded(self, tmp_path: Path) -> None:
        steps = _step(
            "Dispatch subagent",
            f'claude -p --disallowedTools "Bash(bin/venv-python -m {_NEEDS_INSTALL}:*)"',
        )
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0


class TestWorkflowShapeEdgeCases:
    """Malformed / atypical workflow shapes the walk must tolerate, not just the well-formed
    fixtures above -- each is a distinct `continue` branch in _iter_job_steps."""

    def test_unparseable_yaml_is_skipped(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "broken.yml", "jobs: [this is not\n  valid: yaml: at all")
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_workflow_with_no_jobs_mapping_is_skipped(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "nojobs.yml", "name: w\non: push\n")
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0

    def test_job_with_no_steps_list_is_skipped(self, tmp_path: Path) -> None:
        _write_workflow(tmp_path, "nosteps.yml", "name: w\non: push\njobs:\n  job:\n    runs-on: ubuntu-latest\n")
        violations, examined = _run(tmp_path)
        assert violations == []
        assert examined == 0


class TestBlankShellComments:
    """Direct unit coverage of the comment-blanking helper, including quote tracking."""

    def test_hash_outside_quotes_is_blanked_to_end_of_line(self) -> None:
        original = "echo hi # a comment\necho bye"
        out = _blank_shell_comments(original)
        assert "#" not in out.split("\n")[0]
        assert len(out) == len(original)
        assert out == "echo hi " + " " * len("# a comment") + "\necho bye"

    def test_hash_inside_single_quotes_is_preserved(self) -> None:
        out = _blank_shell_comments("echo 'not a # comment'")
        assert "#" in out
        assert out == "echo 'not a # comment'"

    def test_hash_inside_double_quotes_is_preserved(self) -> None:
        out = _blank_shell_comments('echo "not a # comment"')
        assert "#" in out
        assert out == 'echo "not a # comment"'


class TestNeedResolutionHelpers:
    """Direct unit coverage of the NEED predicate's helpers -- branches only reachable via a
    closure member that doesn't correspond to any real repo module or file."""

    def test_module_to_path_returns_none_for_an_unresolvable_module(self, tmp_path: Path) -> None:
        assert _module_to_path("scripts.this_module_does_not_exist_xyz", tmp_path) is None

    def test_top_level_third_party_roots_returns_empty_for_a_missing_file(self, tmp_path: Path) -> None:
        assert _top_level_third_party_roots(tmp_path / "absent.py") == frozenset()

    def test_top_level_third_party_roots_returns_empty_for_unparseable_source(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        assert _top_level_third_party_roots(bad) == frozenset()

    def test_top_level_third_party_roots_skips_relative_imports(self, tmp_path: Path) -> None:
        src = tmp_path / "rel.py"
        src.write_text("from . import sibling\nimport os\n", encoding="utf-8")
        assert _top_level_third_party_roots(src) == frozenset()

    def test_module_needs_third_party_is_false_for_a_module_outside_the_graph(self) -> None:
        assert _module_needs_third_party("scripts.this_module_does_not_exist_xyz") is False


class TestAccountingDeclaration:
    """Decision 170: examined()/skipped() on every reachable exit path, with a non-vacuous branch
    printing a literal distinct from the vacuous one (VP step 3's non-vacuity assertion)."""

    def test_examined_is_declared_on_a_real_corpus(self, tmp_path: Path) -> None:
        steps = _step("Run probe", f"python -m {_NEEDS_INSTALL}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        with patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path):
            with registry.outcome_scope("validate_workflow_dependency_install"):
                failed: list[str] = []
                validate_workflow_dependency_install(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert failed

    def test_pass_branch_prints_a_distinct_message_and_declares_examined(self, tmp_path: Path, capsys) -> None:
        steps = _step("Install deps", "pip install pyyaml") + _step("Run probe", f"python -m {_NEEDS_INSTALL}")
        _write_workflow(tmp_path, "w.yml", _workflow(steps))
        with patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path):
            with registry.outcome_scope("validate_workflow_dependency_install"):
                failed: list[str] = []
                validate_workflow_dependency_install(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.count == 1
        assert failed == []
        out = capsys.readouterr().out
        assert "PASS: every third-party-needing invocation has a preceding same-job install" in out
        assert "dependency-install guard: enforced over 1 job(s)" in out

    def test_vacuous_branch_declares_zero_and_is_distinct(self, tmp_path: Path, capsys) -> None:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        with patch(f"{_MODULE}._workflow_shell_bodies._common.ROOT", tmp_path):
            with registry.outcome_scope("validate_workflow_dependency_install"):
                failed: list[str] = []
                validate_workflow_dependency_install(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert not failed
        out = capsys.readouterr().out
        assert "no script-invoking job found" in out
        assert "dependency-install guard: enforced over" not in out
