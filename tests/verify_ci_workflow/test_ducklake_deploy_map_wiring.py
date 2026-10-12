"""Governed DuckLake deploy workflow wiring as data (T2.36 deploy-wiring): every function in build-lambda.yaml's deploy
map is deployed by exactly one leg's --ducklake-functions list and freshness-checked by that leg's smoke job, and the
telemetry writer's Function URL is resolved before the --lambda-telemetry gate runs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "deploy-ducklake-lambdas.yml"
_CONTRACT = _ROOT / "docs" / "contracts" / "build-lambda.yaml"
_PREFIX = "agent-platform-ducklake-"


def _jobs() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _runs(job: str) -> list[str]:
    return [step.get("run", "") for step in _jobs()[job]["steps"]]


def _deploy_list(job: str) -> set[str]:
    found = [m.group(1) for run in _runs(job) if (m := re.search(r"--ducklake-functions\s+(\S+)", run))]
    assert len(found) == 1, f"{job}: expected exactly one --ducklake-functions list, found {len(found)}"
    return set(found[0].split(","))


def _freshness_set(job: str) -> set[str]:
    found = [m.group(1) for run in _runs(job) if (m := re.search(r"for fn in ([^;]+); do", run))]
    assert len(found) == 1, f"{job}: expected exactly one freshness loop, found {len(found)}"
    return set(found[0].split())


def _map() -> set[str]:
    doc = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))
    return set(doc["deploy_targets"]["ducklake_function_zip_keys"])


def test_each_leg_deploys_exactly_what_its_smoke_job_checks() -> None:
    assert _deploy_list("deploy-maintenance") == _freshness_set("maintenance-smoke")
    assert _deploy_list("deploy-serving") == _freshness_set("smoke")


def test_every_mapped_function_is_deployed_by_exactly_one_leg() -> None:
    maintenance, serving = _deploy_list("deploy-maintenance"), _deploy_list("deploy-serving")
    assert not maintenance & serving, f"deployed by both legs: {sorted(maintenance & serving)}"
    mapped = _map()
    assert maintenance | serving == mapped, (
        f"in the deploy map but in no leg: {sorted(mapped - maintenance - serving)}; "
        f"in a leg but not in the map: {sorted((maintenance | serving) - mapped)}"
    )


def test_telemetry_writer_url_is_resolved_before_the_gate_runs() -> None:
    steps = _jobs()["smoke"]["steps"]
    url_idx = [i for i, s in enumerate(steps) if "telemetry_writer" in s.get("run", "") and "for role in" in s["run"]]
    gate_idx = [i for i, s in enumerate(steps) if "--lambda-telemetry" in s.get("run", "")]
    assert len(url_idx) == 1, "smoke: no step resolves the telemetry_writer URL"
    assert len(gate_idx) == 1, "smoke: no step runs --lambda-telemetry"
    assert url_idx[0] < gate_idx[0], "smoke: --lambda-telemetry runs before its URL is resolved"


def test_url_loop_roles_map_to_deploy_map_functions() -> None:
    run = next(r for r in _runs("smoke") if "for role in" in r)
    roles = re.search(r"for role in ([^;]+); do", run).group(1).split()
    mapped = _map()
    for role in roles:
        assert _PREFIX + role.replace("_", "-") in mapped, f"smoke: URL role {role} is not in the deploy map"
    assert "telemetry_writer" in roles
    assert "${role//_/-}" in run, "smoke: --function-name must use the ${role//_/-} expansion"
    assert "DUCKLAKE_${role^^}_URL" in run, "smoke: URL export must use DUCKLAKE_${role^^}_URL"


def test_deploy_push_paths_include_src_telemetry() -> None:
    """The telemetry kernel is bundled into a DuckLake function, so a kernel edit must trigger the governed deploy."""
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))
    assert "src/telemetry/**" in triggers["push"]["paths"]
