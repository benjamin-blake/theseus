"""Red/green tests for validate_trusted_plan_environment (PLAN-trusted-plan-identity, rec-4636)."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest

from scripts.checks.ci_guards import validate_trusted_plan_environment as v
from scripts.verify_ci_workflow import _load

_ROOT = Path(__file__).resolve().parents[3]
_TRUSTED = "terraform-plan-trusted.yml"


@pytest.fixture(scope="module")
def real_workflows() -> dict[str, dict[str, Any]]:
    return {p.name: _load(str(p)) for p in sorted((_ROOT / ".github" / "workflows").glob("*.yml"))}


@pytest.fixture(scope="module")
def real_terraform() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((_ROOT / "terraform" / "github").glob("*.tf"))}


@pytest.fixture(scope="module")
def real_codeowners() -> str:
    return (_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")


@pytest.fixture
def wfs(real_workflows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return copy.deepcopy(real_workflows)


def _job(workflows: dict[str, dict[str, Any]], job: str) -> dict[str, Any]:
    return workflows[_TRUSTED]["jobs"][job]


def test_real_tree_is_green(real_workflows, real_terraform, real_codeowners) -> None:
    assert v.run_all(real_workflows, real_terraform, real_codeowners) == [[]] * 8


def test_real_tree_governs_both_probe_jobs_and_skips_the_dispatch_only_job(real_workflows) -> None:
    governed = {jid for jid, _ in v._governed(_TRUSTED, real_workflows[_TRUSTED])}
    assert governed == {"claims-probe", "claims-probe-no-env", "live-assume"}
    wf = real_workflows[_TRUSTED]
    assert not v._can_run_on_prt(wf, _job(real_workflows, "live-assume"))
    assert v._can_run_on_prt(wf, _job(real_workflows, "claims-probe"))
    assert v._can_run_on_prt(wf, _job(real_workflows, "claims-probe-no-env"))


def test_a_third_workflow_naming_the_environment(wfs) -> None:
    wfs["other.yml"] = {"on": "push", "jobs": {"j": {"environment": v.ENV, "steps": []}}}
    assert any("references" in x for x in v.check_environment_references(wfs))


def test_a_name_by_expression(wfs) -> None:
    wfs["other.yml"] = {"on": "push", "jobs": {"j": {"environment": {"name": "${{ inputs.e }}"}, "steps": []}}}
    assert any("expression" in x for x in v.check_environment_references(wfs))


def test_non_trusted_pull_request_target_with_id_token(wfs) -> None:
    wfs["other.yml"] = {"on": {"pull_request_target": {}}, "jobs": {"j": {"permissions": {"id-token": "write"}, "steps": []}}}
    assert v.check_prt_minting(wfs)


def test_non_trusted_workflow_level_write_all(wfs) -> None:
    wfs["other.yml"] = {"on": ["pull_request_target"], "permissions": "write-all", "jobs": {"j": {"steps": []}}}
    assert v.check_prt_minting(wfs)


def test_workflow_level_id_token_inherited_by_job_without_permissions(wfs) -> None:
    wfs["other.yml"] = {"on": ["pull_request_target"], "permissions": {"id-token": "write"}, "jobs": {"j": {"steps": []}}}
    assert v.check_prt_minting(wfs)


def test_workflow_call_in_the_trusted_file(wfs) -> None:
    wfs[_TRUSTED]["on"]["workflow_call"] = {}
    assert any("workflow_call" in x for x in v.check_trusted_files(wfs))


def test_missing_trusted_file(wfs) -> None:
    del wfs[_TRUSTED]
    assert any("missing" in x for x in v.check_trusted_files(wfs))


def test_id_token_job_without_the_environment(wfs) -> None:
    del _job(wfs, "claims-probe")["environment"]
    assert any("without environment" in x for x in v.check_minting_jobs(wfs))


def test_no_env_job_outside_the_temp_allowlist(wfs, monkeypatch) -> None:
    monkeypatch.setattr(v, "TEMP_NO_ENV_JOBS", frozenset())
    assert any("claims-probe-no-env" in x for x in v.check_minting_jobs(wfs))


@pytest.mark.parametrize(
    "condition",
    [
        "github.event_name == 'workflow_dispatch' || true",
        "github.event.pull_request.head.repo.full_name == github.repository || true",
        "github.event_name == 'pull_request_target'",
        None,
    ],
)
def test_unguarded_if_forms(wfs, condition) -> None:
    job = _job(wfs, "claims-probe")
    if condition is None:
        del job["if"]
    else:
        job["if"] = condition
    assert any("neither" in x for x in v.check_minting_jobs(wfs))


def test_guard_forms_that_pass() -> None:
    wf = {"on": [v._PRT]}
    ok = f"${{{{ ({v._DISPATCH}) || ({v._SAME_REPO}) }}}}"
    assert v._guarded({"if": ok})
    assert v._guarded({"if": f'github.event_name == "pull_request_target" && {v._SAME_REPO}'})
    assert not v._can_run_on_prt(wf, {"if": "github.event_name == 'workflow_dispatch'"})


@pytest.mark.parametrize("expr", ["github.event.pull_request.head.ref", "github.head_ref"])
def test_run_body_interpolating_pr_controlled_value(wfs, expr) -> None:
    _job(wfs, "claims-probe")["steps"].append({"run": f"echo ${{{{ {expr} }}}}"})
    assert v.check_run_bodies(wfs)


def _mutate_tf(files: dict[str, str], old: str, new: str) -> dict[str, str]:
    out = dict(files)
    key = next(k for k, t in out.items() if old in t)
    out[key] = out[key].replace(old, new, 1)
    return out


def _trusted_block(files: dict[str, str]) -> str:
    return v._blocks("\n".join(files.values()), "github_repository_environment")["tf_trusted_plan"]


@pytest.mark.parametrize(
    ("arg", "bad"),
    [
        ("can_admins_bypass", "true"),
        ("protected_branches", "true"),
        ("custom_branch_policies", "false"),
        ("prevent_destroy", "false"),
    ],
)
def test_environment_argument_breaches(real_terraform, arg, bad) -> None:
    block = _trusted_block(real_terraform)
    mutated = re.sub(rf"(?m)^(\s*{arg}\s*=\s*).+$", rf"\g<1>{bad}", block)
    assert mutated != block
    assert v.check_terraform(_mutate_tf(real_terraform, block, mutated))


def test_environment_with_a_reviewers_block(real_terraform) -> None:
    block = _trusted_block(real_terraform)
    assert v.check_terraform(_mutate_tf(real_terraform, block, block.rstrip("}") + "  reviewers {\n    users = []\n  }\n}"))


def test_policy_branch_pattern_star(real_terraform) -> None:
    assert v.check_terraform(_mutate_tf(real_terraform, 'branch_pattern = "main"', 'branch_pattern = "*"'))


def test_second_deployment_policy(real_terraform) -> None:
    kind = "github_repository_environment_deployment_policy"
    extra = {"extra.tf": f'resource "{kind}" "again" {{\n  environment = "tf-trusted-plan"\n  branch_pattern = "main"\n}}\n'}
    assert any("exactly one deployment policy" in x for x in v.check_terraform({**real_terraform, **extra}))


def test_missing_import_block(real_terraform) -> None:
    mutated = _mutate_tf(
        real_terraform, "to = github_repository_environment.tf_trusted_plan\n", "to = github_repository_environment.gone\n"
    )
    assert any("import block" in x for x in v.check_terraform(mutated))


@pytest.mark.parametrize("key", ["ref", "repository"])
def test_checkout_with_ref_or_repository(wfs, key) -> None:
    _job(wfs, "claims-probe")["steps"][0]["with"][key] = "${{ github.event.pull_request.head.sha }}"
    assert v.check_checkouts(wfs)


def test_checkout_without_persist_credentials_false(wfs) -> None:
    del _job(wfs, "claims-probe")["steps"][0]["with"]["persist-credentials"]
    assert v.check_checkouts(wfs)


def test_unowned_script_and_unowned_action(wfs, real_codeowners) -> None:
    _job(wfs, "claims-probe")["steps"].append({"run": "python3 -I scripts/ci/unowned.py"})
    _job(wfs, "live-assume")["steps"].append({"uses": "./.github/actions/unowned"})
    out = v.check_owned_and_isolated(wfs, real_codeowners)
    assert any("scripts/ci/unowned.py" in x for x in out)
    assert any(".github/actions/unowned" in x for x in out)


@pytest.mark.parametrize("body", ["python3 scripts/ci/oidc_claims_probe.py", "python3 -m scripts.ci.oidc_claims_probe"])
def test_python_without_isolated_mode(wfs, real_codeowners, body) -> None:
    _job(wfs, "claims-probe")["steps"].append({"run": body})
    assert any("without -I" in x for x in v.check_owned_and_isolated(wfs, real_codeowners))


def test_codeowners_matching_forms() -> None:
    text = "/scripts/ci/a.py @o\n/.github/actions/x/ @o\n/.github/workflows/terraform-*.yml @o\n"
    assert v._owned("scripts/ci/a.py", text)
    assert v._owned(".github/actions/x", text)
    assert not v._owned("scripts/ci/b.py", text)


@pytest.mark.parametrize("body", ["python3 -I ./scripts/ci/unowned.py", "python3 -I $GITHUB_WORKSPACE/scripts/ci/unowned.py"])
def test_unowned_script_in_dotted_forms(wfs, real_codeowners, body) -> None:
    _job(wfs, "claims-probe")["steps"].append({"run": body})
    assert any("scripts/ci/unowned.py" in x for x in v.check_owned_and_isolated(wfs, real_codeowners))


@pytest.mark.parametrize("body", ["/usr/bin/python3 x.py", "python3.12 x.py", "env python3 x.py", "bin/venv-python x.py"])
def test_python_invocation_forms_without_isolated_mode(wfs, real_codeowners, body) -> None:
    _job(wfs, "claims-probe")["steps"].append({"run": body})
    assert any("without -I" in x for x in v.check_owned_and_isolated(wfs, real_codeowners))


def test_unreadable_input_fails_instead_of_skipping(monkeypatch) -> None:
    def boom(_path: str) -> dict[str, Any]:
        raise OSError("unreadable")

    monkeypatch.setattr(v, "_load", boom)
    failed: list[str] = []
    v.validate_trusted_plan_environment(failed)
    assert any("unreadable" in x for x in failed)
