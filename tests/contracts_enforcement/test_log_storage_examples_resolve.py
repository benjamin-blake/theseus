"""Regression guard for PLAN-dead-file-cleanup: every entry in
docs/contracts/log-storage.yaml's patterns.locally_produced.examples must resolve to a real
artefact by one of three arms -- git-tracked under logs/, gitignored, or carrying a
`runtime: true` file-router route. A "tracked-only" predicate would be false for three of the
six examples today (.recommendations-log.jsonl, .session-telemetry.jsonl,
.north-star-log.jsonl), so all three arms are required for this test to ever go green. No
basename is hardcoded, so the assertion generalizes to future example additions/removals and
cannot be satisfied by deleting an example without also fixing its resolution.
"""

from pathlib import Path

import yaml

from scripts.checks._common import ROOT, run

_LOG_STORAGE_PATH = ROOT / "docs" / "contracts" / "log-storage.yaml"
_FILE_ROUTER_PATH = ROOT / "docs" / "contracts" / "file-router.yaml"


def _locally_produced_examples() -> list[str]:
    content = yaml.safe_load(_LOG_STORAGE_PATH.read_text(encoding="utf-8"))
    return list(content["patterns"]["locally_produced"]["examples"])


def _tracked_logs_files() -> set[str]:
    result = run(["git", "ls-files", "logs/"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return set(result.stdout.splitlines())


def _is_gitignored(rel_path: str) -> bool:
    result = run(["git", "check-ignore", "-q", rel_path], cwd=ROOT)
    return result.returncode == 0


def _runtime_routed_basenames() -> set[str]:
    content = yaml.safe_load(_FILE_ROUTER_PATH.read_text(encoding="utf-8"))
    basenames: set[str] = set()
    for route in content["routes"]:
        if not isinstance(route, dict) or not route.get("runtime", False):
            continue
        for target in route.get("targets", []):
            if isinstance(target, str):
                basenames.add(Path(target).name)
    return basenames


class TestLogStorageExamplesResolve:
    def test_every_example_resolves(self) -> None:
        tracked = _tracked_logs_files()
        runtime_routed = _runtime_routed_basenames()
        unresolved = []
        for example in _locally_produced_examples():
            rel_path = f"logs/{example}"
            tracked_under_logs = rel_path in tracked
            gitignored = _is_gitignored(rel_path)
            has_runtime_route = example in runtime_routed
            if not (tracked_under_logs or gitignored or has_runtime_route):
                unresolved.append(example)
        assert not unresolved, f"log-storage.yaml examples with no resolution arm: {unresolved}"
