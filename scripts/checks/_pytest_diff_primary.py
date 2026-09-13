"""In-session heavy-dependency classification for the pytest-diff primary run."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pytest
from coverage import Coverage

_CAPTURE_ENV = "FAST_TIER_PRIMARY_CAPTURE"
_TARGETS_ENV = "FAST_TIER_PRIMARY_TARGETS"
_EXCLUDED_ENV = "FAST_TIER_PRIMARY_EXCLUDED"
_ROOT_ENV = "FAST_TIER_PRIMARY_ROOT"
_COVERAGE_ENV = "FAST_TIER_PRIMARY_COVERAGE"
_NO_MODULE_NAMED_RE = re.compile(r"No module named ['\"]([\w.]+)['\"]")


@dataclass(frozen=True)
class PrimaryCapture:
    path: Path
    environment: dict[str, str]

    def read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"primary pytest deferral capture is missing or invalid: {exc}") from exc
        if payload.get("complete") is not True or not isinstance(payload.get("deferred"), dict):
            raise RuntimeError("primary pytest deferral capture is incomplete")
        if any(not isinstance(path, str) or not isinstance(reason, str) for path, reason in payload["deferred"].items()):
            raise RuntimeError("primary pytest deferral capture has invalid entries")
        return payload["deferred"]


@contextmanager
def capture_primary_deferrals(
    targets: list[str], excluded: set[str], *, coverage_active: bool, root: Path
) -> Iterator[PrimaryCapture]:
    debug_dir = root / "logs" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fast-tier-primary-", dir=debug_dir) as directory:
        path = Path(directory) / "deferrals.json"
        environment = dict(os.environ)
        environment.update(
            {
                _CAPTURE_ENV: str(path),
                _TARGETS_ENV: json.dumps(targets),
                _EXCLUDED_ENV: json.dumps(sorted(excluded)),
                _ROOT_ENV: str(root),
                _COVERAGE_ENV: "1" if coverage_active else "0",
            }
        )
        yield PrimaryCapture(path=path, environment=environment)


@dataclass
class _PluginState:
    root: Path
    targets: dict[Path, str]
    excluded: set[str]
    coverage_active: bool
    deferred: dict[str, str] = field(default_factory=dict)
    coverage_snapshots: dict[str, _CoverageSnapshot] = field(default_factory=dict)
    workers_seen: int = 0
    workers_complete: int = 0
    healthy: bool = True


_STATE: _PluginState | None = None


@dataclass(frozen=True)
class _CoverageSnapshot:
    data: dict[str, set[Any]]
    file_tracers: dict[str, str]


def _load_string_list(name: str) -> list[str]:
    try:
        value = json.loads(os.environ[name])
    except (KeyError, json.JSONDecodeError) as exc:
        raise pytest.UsageError(f"{name} is missing or invalid") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise pytest.UsageError(f"{name} must be a JSON string list")
    return value


def _target_path(token: str, state: _PluginState) -> str | None:
    path = Path(token)
    absolute = (path if path.is_absolute() else state.root / path).resolve()
    return state.targets.get(absolute)


def _active_coverage_snapshot() -> _CoverageSnapshot | None:
    coverage = Coverage.current()
    collector = getattr(coverage, "_collector", None)
    if collector is None:
        return None
    collector.pause()
    try:
        collector.lock_data()
        try:
            data = {filename: values.copy() for filename, values in collector.data.items()}
            file_tracers = dict(collector.file_tracers)
        finally:
            collector.unlock_data()
        return _CoverageSnapshot(data=data, file_tracers=file_tracers)
    finally:
        collector.resume()


def _restore_coverage(snapshot: _CoverageSnapshot) -> None:
    coverage = Coverage.current()
    collector = getattr(coverage, "_collector", None)
    if collector is None:
        raise RuntimeError("pytest-cov coverage disappeared before deferred-module rollback")
    collector.pause()
    try:
        collector.lock_data()
        try:
            for filename, values in collector.data.items():
                values.clear()
                values.update(snapshot.data.get(filename, ()))
            for filename, values in snapshot.data.items():
                if filename not in collector.data:
                    collector.data[filename] = values.copy()
            collector.file_tracers.clear()
            collector.file_tracers.update(snapshot.file_tracers)
        finally:
            collector.unlock_data()
    finally:
        collector.resume()


def pytest_configure(config: pytest.Config) -> None:
    global _STATE
    root = Path(os.environ.get(_ROOT_ENV, ""))
    if not root.is_absolute():
        raise pytest.UsageError(f"{_ROOT_ENV} must be an absolute path")
    targets = _load_string_list(_TARGETS_ENV)
    excluded = set(_load_string_list(_EXCLUDED_ENV))
    _STATE = _PluginState(
        root=root,
        targets={(root / target).resolve(): target for target in targets},
        excluded=excluded,
        coverage_active=os.environ.get(_COVERAGE_ENV) == "1",
    )


def pytest_collectstart(collector: pytest.Collector) -> None:
    state = _STATE
    path = getattr(collector, "path", None)
    if state is None or path is None:
        return
    target = _target_path(str(path), state)
    if target is None or not state.coverage_active:
        return
    snapshot = _active_coverage_snapshot()
    if snapshot is None:
        raise RuntimeError("pytest-cov coverage is unavailable before target collection")
    state.coverage_snapshots[target] = snapshot


def _defer_collect_report(report: pytest.CollectReport) -> None:
    state = _STATE
    if state is None or report.outcome not in {"failed", "skipped"}:
        return
    target = _target_path(report.nodeid.split("::", 1)[0], state)
    if target is None:
        return
    matches = _NO_MODULE_NAMED_RE.findall(str(report.longrepr))
    if not matches:
        return
    missing = matches[-1].split(".", 1)[0]
    if missing not in state.excluded or importlib.util.find_spec(missing) is not None:
        return
    if state.coverage_active:
        snapshot = state.coverage_snapshots.get(target)
        if snapshot is None:
            raise RuntimeError(f"coverage snapshot is missing for deferred module {target}")
        _restore_coverage(snapshot)
    state.deferred[target] = missing
    report.outcome = "passed"
    report.longrepr = None


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_make_collect_report(collector: pytest.Collector) -> Any:
    report = yield
    _defer_collect_report(report)
    return report


@pytest.hookimpl(optionalhook=True)
def pytest_testnodeready(node: Any) -> None:
    if _STATE is not None:
        _STATE.workers_seen += 1


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: object | None) -> None:
    state = _STATE
    if state is None:
        return
    output = getattr(node, "workeroutput", {})
    deferred = output.get("fast_tier_primary_deferred")
    complete = output.get("fast_tier_primary_complete")
    if error is not None or complete is not True or not isinstance(deferred, dict):
        state.healthy = False
        return
    state.workers_complete += 1
    state.deferred.update(deferred)


def pytest_sessionfinish(session: pytest.Session) -> None:
    state = _STATE
    if state is None:
        return
    worker_output = getattr(session.config, "workeroutput", None)
    if worker_output is not None:
        worker_output["fast_tier_primary_deferred"] = state.deferred
        worker_output["fast_tier_primary_complete"] = True
        return
    complete = state.healthy and (state.workers_seen == 0 or state.workers_seen == state.workers_complete)
    path = Path(os.environ[_CAPTURE_ENV])
    path.write_text(json.dumps({"complete": complete, "deferred": state.deferred}, sort_keys=True), encoding="utf-8")
