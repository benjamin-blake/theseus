from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.checks.deps import fast_tier_harness_capture as capture


class TestNodeCapture:
    def test_pytest_command_detection_and_instrumentation(self, tmp_path: Path, monkeypatch) -> None:
        assert capture.is_pytest_execution([sys.executable, "-m", "pytest", "tests/x.py"])
        assert not capture.is_pytest_execution([sys.executable, "-m", "pytest", "--collect-only", "tests/x.py"])
        assert not capture.is_pytest_execution(["git", "status"])
        monkeypatch.setenv("KEEP", "outer")
        stale = tmp_path / "pytest-0-nodes.jsonl"
        stale.write_text("stale", encoding="utf-8")
        command, env, junit, events = capture.instrumented_pytest_command(
            [sys.executable, "-m", "pytest", "tests/x.py"], tmp_path, 0, {"KEEP": "inner"}
        )
        assert command[-3:] == [f"--junitxml={junit}", "-p", capture.PLUGIN_NAME]
        assert env["KEEP"] == "inner"
        assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path)
        assert events == stale
        assert not stale.exists()

    def test_generated_plugin_preserves_native_parameterized_nodeid(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test_sample.py"
        test_file.write_text(
            "import pytest\n\n@pytest.mark.parametrize('value', [1])\ndef test_value(value):\n    assert value\n",
            encoding="utf-8",
        )
        (tmp_path / f"{capture.PLUGIN_NAME}.py").write_text(capture.PLUGIN_SOURCE, encoding="utf-8")
        command, env, junit, events = capture.instrumented_pytest_command(
            [sys.executable, "-m", "pytest", str(test_file), "-q"], tmp_path, 0, None
        )
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stdout + result.stderr
        capture.validate_junit(junit)
        captured = capture.read_events(events)
        assert any(row["nodeid"].endswith("test_sample.py::test_value[1]") for row in captured)

    def test_generated_plugin_creates_an_empty_event_stream_when_no_node_runs(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test_empty.py"
        test_file.write_text("", encoding="utf-8")
        (tmp_path / f"{capture.PLUGIN_NAME}.py").write_text(capture.PLUGIN_SOURCE, encoding="utf-8")
        command, env, junit, events = capture.instrumented_pytest_command(
            [sys.executable, "-m", "pytest", str(test_file), "-q"], tmp_path, 0, None
        )
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED
        capture.validate_junit(junit)
        assert capture.read_events(events) == []

    def test_junit_and_event_validation_fail_loudly(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(capture.HarnessError, match="required JUnit"):
            capture.validate_junit(missing)
        bad_xml = tmp_path / "bad.xml"
        bad_xml.write_text("<bad", encoding="utf-8")
        with pytest.raises(capture.HarnessError, match="invalid JUnit"):
            capture.validate_junit(bad_xml)
        with pytest.raises(capture.HarnessError, match="native node events"):
            capture.read_events(missing)
        bad_events = tmp_path / "bad.jsonl"
        bad_events.write_text("[]\n", encoding="utf-8")
        with pytest.raises(capture.HarnessError, match="invalid native node events"):
            capture.read_events(bad_events)

    @pytest.mark.parametrize(
        ("event", "verdict"),
        [
            ({"when": "call", "outcome": "passed"}, "pass"),
            ({"when": "call", "outcome": "failed"}, "fail"),
            ({"when": "call", "outcome": "skipped"}, "skipped"),
            ({"when": "call", "outcome": "skipped", "wasxfail": True}, "xfailed"),
            ({"when": "call", "outcome": "passed", "wasxfail": True}, "xpassed"),
            ({"when": "setup", "outcome": "failed"}, "fail"),
            ({"when": "teardown", "outcome": "failed"}, "fail"),
            ({"when": "setup", "outcome": "skipped"}, "skipped"),
            ({"when": "setup", "outcome": "passed"}, None),
        ],
    )
    def test_event_verdict_vocabulary(self, event: dict, verdict: str | None) -> None:
        assert capture.event_verdict(event) == verdict

    def test_consolidation_and_union_comparison_keep_missing_and_deferred_distinct(self) -> None:
        events = [
            {"nodeid": "tests/a.py::test_a", "when": "call", "outcome": "passed"},
            {"nodeid": "tests/a.py::test_a", "when": "call", "outcome": "failed"},
            {"nodeid": "tests/b.py::test_b", "when": "call", "outcome": "passed"},
            {"nodeid": "tests/ignored.py::test_x", "when": "setup", "outcome": "passed"},
        ]
        nodes = capture.consolidate_nodes(events, {"tests/b.py": "duckdb"})
        assert nodes == {"tests/a.py::test_a": "fail", "tests/b.py::test_b": "deferred"}
        baseline = {"nodes": nodes, "deferred_modules": {"tests/b.py": "duckdb"}, "gate_failures": []}
        candidate = {
            "nodes": {"tests/c.py::test_c": "pass"},
            "deferred_modules": {"tests/a.py": "numpy"},
            "gate_failures": ["Tests (pytest)"],
        }
        compared = capture.compare_captures(baseline, candidate)
        assert compared["union_node_count"] == 3
        assert compared["changed_node_count"] == 3
        assert compared["gate_failures_changed"] is True
        assert compared["difference_count"] == 4
        by_id = {row["nodeid"]: row for row in compared["nodes"]}
        assert by_id["tests/a.py::test_a"] == {
            "nodeid": "tests/a.py::test_a",
            "baseline": "fail",
            "candidate": "deferred",
        }
        assert by_id["tests/c.py::test_c"]["baseline"] == "not-collected"
        with pytest.raises(capture.HarnessError, match="baseline.nodes must be a mapping"):
            capture.compare_captures({"nodes": []}, candidate)
        with pytest.raises(capture.HarnessError, match="baseline.gate_failures must be a list"):
            capture.compare_captures(
                {"nodes": {}, "deferred_modules": {}, "gate_failures": "failed"},
                {"nodes": {}, "deferred_modules": {}, "gate_failures": []},
            )
