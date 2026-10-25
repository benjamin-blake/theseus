"""Governed DuckLake deploy workflow wiring as data (T2.36 deploy-wiring, Decision 236): every function in
build-lambda.yaml's deploy map is deployed by exactly one leg's --ducklake-functions list and freshness-checked by that
leg's smoke job, the telemetry Function URLs are resolved before their gates run, and the production telemetry deploy
waits on the twin's gate."""

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


_LEGS = (
    ("deploy-maintenance", "maintenance-smoke"),
    ("deploy-serving", "smoke"),
    ("deploy-telemetry-twin", "telemetry-twin-smoke"),
    ("deploy-telemetry", "telemetry-smoke"),
)


def _needs(job: str) -> list[str]:
    needs = _jobs()[job].get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _transitive_needs(job: str) -> set[str]:
    seen: set[str] = set()
    stack = _needs(job)
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(_needs(current))
    return seen


def _gate_flags(job: str) -> set[str]:
    return {m for run in _runs(job) for m in re.findall(r"--(lambda-telemetry(?:-smoke|-reader)?)\b", run)}


def test_each_leg_deploys_exactly_what_its_smoke_job_checks() -> None:
    for deploy, smoke in _LEGS:
        assert _deploy_list(deploy) == _freshness_set(smoke), (deploy, smoke)


def test_every_mapped_function_is_deployed_by_exactly_one_leg() -> None:
    lists = [_deploy_list(deploy) for deploy, _ in _LEGS]
    seen: set[str] = set()
    for deploys in lists:
        assert not seen & deploys, f"deployed by two legs: {sorted(seen & deploys)}"
        seen |= deploys
    mapped = _map()
    assert seen == mapped, (
        f"in the deploy map but in no leg: {sorted(mapped - seen)}; in a leg but not in the map: {sorted(seen - mapped)}"
    )


def test_telemetry_urls_are_resolved_before_their_gates_run() -> None:
    expected = {
        "telemetry-twin-smoke": ("telemetry_writer_smoke", "--lambda-telemetry-smoke"),
        "telemetry-smoke": ("telemetry_reader", "--lambda-telemetry-reader"),
    }
    for job, (role, flag) in expected.items():
        steps = _jobs()[job]["steps"]
        url_idx = [i for i, s in enumerate(steps) if role in s.get("run", "") and "for role in" in s["run"]]
        gate_idx = [i for i, s in enumerate(steps) if flag in s.get("run", "")]
        assert len(url_idx) == 1, f"{job}: no step resolves the {role} URL"
        assert len(gate_idx) == 1, f"{job}: no step runs {flag}"
        assert url_idx[0] < gate_idx[0], f"{job}: {flag} runs before its URL is resolved"
    steps = _jobs()["telemetry-smoke"]["steps"]
    writer_gate = [i for i, s in enumerate(steps) if re.search(r"--lambda-telemetry(\s|$)", s.get("run", ""))]
    url_loop = [i for i, s in enumerate(steps) if "telemetry_writer" in s.get("run", "") and "for role in" in s["run"]]
    assert len(writer_gate) == 1 and len(url_loop) == 1 and url_loop[0] < writer_gate[0]


def test_url_loop_roles_map_to_deploy_map_functions() -> None:
    mapped = _map()
    for job in _jobs():
        loops = [r for r in _runs(job) if "for role in" in r]
        if not loops:
            continue
        assert len(loops) == 1, f"{job}: more than one URL loop"
        run = loops[0]
        roles = re.search(r"for role in ([^;]+); do", run).group(1).split()
        for role in roles:
            assert _PREFIX + role.replace("_", "-") in mapped, f"{job}: URL role {role} is not in the deploy map"
        assert "${role//_/-}" in run, f"{job}: --function-name must use the ${{role//_/-}} expansion"
        assert "DUCKLAKE_${role^^}_URL" in run, f"{job}: URL export must use DUCKLAKE_${{role^^}}_URL"
    smoke_run = next(r for r in _runs("smoke") if "for role in" in r)
    assert "telemetry" not in smoke_run, "smoke: telemetry URLs moved to the telemetry legs"
    assert "telemetry_writer" in next(r for r in _runs("telemetry-smoke") if "for role in" in r)


def test_deploy_push_paths_include_src_telemetry() -> None:
    """The telemetry kernel is bundled into a DuckLake function, so a kernel edit must trigger the governed deploy."""
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))
    assert "src/telemetry/**" in triggers["push"]["paths"]


def test_create_telemetry_step_is_last_in_maintenance_smoke_and_not_cancelled() -> None:
    """The owner-login DDL step runs after the four maintenance gates, whatever they did, and nothing runs after it."""
    steps = _jobs()["maintenance-smoke"]["steps"]
    assert steps[-1].get("id") == "create-telemetry-tables"
    assert steps[-1]["if"].replace(" ", "") == "${{!cancelled()}}"
    assert "--lambda-maintenance-create-telemetry" in steps[-1]["run"]
    gates = [s["run"] for s in steps[:-1] if "--lambda-maintenance-" in s.get("run", "")]
    assert len(gates) == 4 and all("create-telemetry" not in g for g in gates)
    assert "if" not in steps[-2] or "cancelled" not in str(steps[-2]["if"])


def test_smoke_job_waits_for_maintenance_smoke() -> None:
    """The shared smoke gates run after the owner step and the twin's gate; deploy-serving never waits on a smoke step."""
    jobs = _jobs()
    smoke = jobs["smoke"]
    assert set(smoke["needs"]) == {"deploy-serving", "maintenance-smoke", "telemetry-twin-smoke"}
    condition = str(smoke["if"]).replace(" ", "")
    assert "!cancelled()" in condition and "needs.deploy-serving.outputs.deployed=='true'" in condition
    assert not {"maintenance-smoke", "telemetry-twin-smoke"} & set(jobs["deploy-serving"].get("needs", []))
    assert not _gate_flags("smoke")


def test_production_telemetry_deploy_waits_on_the_twin_gate() -> None:
    """deploy-telemetry needs the twin gate (success only); that gate follows the serving deploy; the reader gate runs."""
    jobs = _jobs()
    assert {"reconcile-gate", "telemetry-twin-smoke", "maintenance-smoke", "deploy-serving"} <= set(_needs("deploy-telemetry"))
    assert "!cancelled()" not in str(jobs["deploy-telemetry"].get("if", ""))
    twin = jobs["telemetry-twin-smoke"]
    assert {"deploy-telemetry-twin", "maintenance-smoke", "deploy-serving"} <= set(_needs("telemetry-twin-smoke"))
    assert "!cancelled()" in str(twin["if"]) and _gate_flags("telemetry-twin-smoke") == {"lambda-telemetry-smoke"}
    assert _gate_flags("telemetry-smoke") == {"lambda-telemetry", "lambda-telemetry-reader"}
    assert not {"telemetry-twin-smoke", "deploy-telemetry", "telemetry-smoke"} & _transitive_needs("deploy-serving")


def test_every_writer_gate_job_runs_after_maintenance_smoke() -> None:
    """Every job running a telemetry writer gate has maintenance-smoke among its transitive needs (Decision 216 cl.2)."""
    gated = [job for job in _jobs() if _gate_flags(job) & {"lambda-telemetry", "lambda-telemetry-smoke"}]
    assert set(gated) == {"telemetry-twin-smoke", "telemetry-smoke"}
    for job in gated:
        assert "maintenance-smoke" in _transitive_needs(job), job
