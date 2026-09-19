"""Native pytest node capture and comparison for the fast-tier audit harness."""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts.checks.deps import fast_tier_harness_support

HarnessError = fast_tier_harness_support.HarnessError
PLUGIN_NAME = "fast_tier_node_capture"
PLUGIN_SOURCE = """from __future__ import annotations

import json
import os
from pathlib import Path


def pytest_configure(config):
    Path(os.environ["FAST_TIER_NODE_EVENTS"]).touch()


def pytest_runtest_logreport(report):
    payload = {
        "nodeid": report.nodeid,
        "when": report.when,
        "outcome": report.outcome,
        "wasxfail": bool(getattr(report, "wasxfail", False)),
    }
    path = Path(os.environ["FAST_TIER_NODE_EVENTS"])
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\\n")
"""


def is_pytest_execution(command: list[str]) -> bool:
    return len(command) >= 3 and command[1:3] == ["-m", "pytest"] and "--collect-only" not in command


def instrumented_pytest_command(
    command: list[str], output_dir: Path, index: int, original_env: dict[str, str] | None
) -> tuple[list[str], dict[str, str], Path, Path]:
    junit_path = output_dir / f"pytest-{index}.xml"
    event_path = output_dir / f"pytest-{index}-nodes.jsonl"
    junit_path.unlink(missing_ok=True)
    event_path.unlink(missing_ok=True)
    env = dict(os.environ)
    env.update(original_env or {})
    env["FAST_TIER_NODE_EVENTS"] = str(event_path)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(output_dir), env.get("PYTHONPATH", ""))))
    augmented = [*command, f"--junitxml={junit_path}", "-p", PLUGIN_NAME]
    return augmented, env, junit_path, event_path


def validate_junit(path: Path) -> None:
    if not path.is_file():
        raise HarnessError(f"pytest did not produce required JUnit XML: {path}")
    try:
        ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise HarnessError(f"invalid JUnit XML {path}: {exc}") from exc


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise HarnessError(f"pytest did not produce native node events: {path}")
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("nodeid"), str):
                raise ValueError("event is not a node mapping")
            events.append(row)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HarnessError(f"invalid native node events {path}: {exc}") from exc
    return events


def event_verdict(event: dict[str, Any]) -> str | None:
    when = event.get("when")
    outcome = event.get("outcome")
    wasxfail = bool(event.get("wasxfail"))
    if when == "call":
        if wasxfail:
            return "xfailed" if outcome == "skipped" else "xpassed"
        verdicts: dict[Any, str] = {"passed": "pass", "failed": "fail", "skipped": "skipped"}
        return verdicts.get(outcome)
    if when in {"setup", "teardown"} and outcome == "failed":
        return "fail"
    if when == "setup" and outcome == "skipped":
        return "skipped"
    return None


def consolidate_nodes(events: list[dict[str, Any]], deferred: dict[str, str]) -> dict[str, str]:
    priority = {"skipped": 0, "xfailed": 1, "pass": 2, "xpassed": 3, "fail": 4}
    nodes: dict[str, str] = {}
    for event in events:
        verdict = event_verdict(event)
        nodeid = event["nodeid"]
        if verdict is not None and (nodeid not in nodes or priority[verdict] > priority[nodes[nodeid]]):
            nodes[nodeid] = verdict
    for nodeid in tuple(nodes):
        if nodeid.split("::", 1)[0] in deferred:
            nodes[nodeid] = "deferred"
    return dict(sorted(nodes.items()))


def compare_captures(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_nodes = _mapping(baseline.get("nodes"), "baseline.nodes")
    candidate_nodes = _mapping(candidate.get("nodes"), "candidate.nodes")
    baseline_deferred = _mapping(baseline.get("deferred_modules"), "baseline.deferred_modules")
    candidate_deferred = _mapping(candidate.get("deferred_modules"), "candidate.deferred_modules")
    baseline_failures = list(_sequence(baseline.get("gate_failures"), "baseline.gate_failures"))
    candidate_failures = list(_sequence(candidate.get("gate_failures"), "candidate.gate_failures"))
    rows: list[dict[str, str]] = []
    for nodeid in sorted(set(baseline_nodes) | set(candidate_nodes)):
        path = nodeid.split("::", 1)[0]
        before = baseline_nodes.get(nodeid, "deferred" if path in baseline_deferred else "not-collected")
        after = candidate_nodes.get(nodeid, "deferred" if path in candidate_deferred else "not-collected")
        rows.append({"nodeid": nodeid, "baseline": before, "candidate": after})
    changed = [row for row in rows if row["baseline"] != row["candidate"]]
    failures_changed = baseline_failures != candidate_failures
    return {
        "union_node_count": len(rows),
        "changed_node_count": len(changed),
        "nodes": rows,
        "changed_nodes": changed,
        "deferred_modules": {"baseline": baseline_deferred, "candidate": candidate_deferred},
        "gate_failures": {"baseline": baseline_failures, "candidate": candidate_failures},
        "gate_failures_changed": failures_changed,
        "difference_count": len(changed) + int(failures_changed),
    }


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HarnessError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise HarnessError(f"{label} must be a list")
    return value
