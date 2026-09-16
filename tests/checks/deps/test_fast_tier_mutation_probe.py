from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from scripts.checks.deps import fast_tier_mutation_probe as probe


def test_tracked_candidate_mutation_anchors_match_current_tree() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    probes = probe.load_manifest(repo_root / "scripts/checks/deps/fast_tier_mutations.yaml")
    assert len(probes) == 10
    for row in probes:
        candidate = row["candidate"]
        subject = repo_root / candidate["subject_path"]
        assert subject.is_file(), row["id"]
        assert subject.read_text(encoding="utf-8").count(candidate["find"]) == 1, row["id"]
        test_file = repo_root / candidate["test_node"].split("::", 1)[0]
        assert test_file.is_file(), row["id"]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True, text=True, encoding="utf-8")
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_probe_requires_each_revision_to_pass_control_and_catch_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "bin").mkdir()
    runner = repo / "bin" / "venv-python"
    runner.write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n', encoding="utf-8")
    runner.chmod(0o755)
    (repo / "subject.py").write_text("VALUE = True\n", encoding="utf-8")
    (repo / "test_subject.py").write_text(
        "from subject import VALUE\n\ndef test_value():\n    assert VALUE\n", encoding="utf-8"
    )
    baseline = _commit(repo, "baseline")
    (repo / "marker.txt").write_text("candidate\n", encoding="utf-8")
    candidate = _commit(repo, "candidate")
    manifest = {
        "schema_version": 1,
        "probes": [
            {
                "id": "value_remains_true",
                "baseline": {
                    "subject_path": "subject.py",
                    "test_node": "test_subject.py::test_value",
                    "find": "VALUE = True",
                    "replace": "VALUE = False",
                },
                "candidate": {
                    "subject_path": "subject.py",
                    "test_node": "test_subject.py::test_value",
                    "find": "VALUE = True",
                    "replace": "VALUE = False",
                },
            }
        ],
    }
    manifest_path = tmp_path / "mutations.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    output = tmp_path / "result.json"
    loaded = probe.load_manifest(manifest_path)
    assert probe.run_probe(repo, loaded, baseline, candidate, output)["all_caught"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["probe_count"] == 1


def test_manifest_and_mutation_anchors_fail_loudly(tmp_path: Path) -> None:
    with pytest.raises(probe.MutationProbeError, match="must be a mapping"):
        probe._mapping([], "row")
    with pytest.raises(probe.MutationProbeError, match="non-empty string"):
        probe._string("", "value")
    with pytest.raises(probe.MutationProbeError, match="cannot load"):
        probe.load_manifest(tmp_path / "missing.yaml")
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("schema_version: 2\nprobes: []\n", encoding="utf-8")
    with pytest.raises(probe.MutationProbeError, match="schema_version"):
        probe.load_manifest(invalid)
    invalid.write_text("schema_version: 1\nprobes: []\n", encoding="utf-8")
    with pytest.raises(probe.MutationProbeError, match="non-empty list"):
        probe.load_manifest(invalid)
    duplicate: dict[str, Any] = {
        "schema_version": 1,
        "probes": [
            {"id": "same", "baseline": {}, "candidate": {}},
            {"id": "same", "baseline": {}, "candidate": {}},
        ],
    }
    invalid.write_text(yaml.safe_dump(duplicate), encoding="utf-8")
    with pytest.raises(probe.MutationProbeError, match="non-empty string"):
        probe.load_manifest(invalid)
    for row in duplicate["probes"]:
        row["baseline"] = row["candidate"] = {
            "subject_path": "subject.py",
            "test_node": "test_subject.py",
            "find": "before",
            "replace": "after",
        }
    invalid.write_text(yaml.safe_dump(duplicate), encoding="utf-8")
    with pytest.raises(probe.MutationProbeError, match="duplicate"):
        probe.load_manifest(invalid)
    with pytest.raises(probe.MutationProbeError, match="unsafe mutation path"):
        probe._safe_path(tmp_path, "../escape")
    side = {"subject_path": "subject.py", "test_node": "test_x.py", "find": "missing", "replace": "value"}
    with pytest.raises(probe.MutationProbeError, match="cannot read mutation subject"):
        probe._exercise_side(tmp_path, side)
    (tmp_path / "subject.py").write_text("content\n", encoding="utf-8")
    with pytest.raises(probe.MutationProbeError, match="exactly once"):
        probe._exercise_side(tmp_path, side)


def test_exercise_side_rejects_red_control_and_surviving_mutation(tmp_path: Path) -> None:
    subject = tmp_path / "subject.py"
    subject.write_text("before\n", encoding="utf-8")
    side = {"subject_path": "subject.py", "test_node": "test_x.py", "find": "before", "replace": "after"}
    failed = subprocess.CompletedProcess([], 1, "", "")
    passed = subprocess.CompletedProcess([], 0, "", "")
    with patch.object(probe, "_run_test", return_value=failed):
        with pytest.raises(probe.MutationProbeError, match="unmutated control failed"):
            probe._exercise_side(tmp_path, side)
    with patch.object(probe, "_run_test", side_effect=[passed, passed]):
        with pytest.raises(probe.MutationProbeError, match="mutation was not caught"):
            probe._exercise_side(tmp_path, side)
    assert subject.read_text(encoding="utf-8") == "before\n"


def test_main_loads_manifest_and_writes_report(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    row = {
        "id": "probe",
        "baseline": {"subject_path": "x", "test_node": "y", "find": "a", "replace": "b"},
        "candidate": {"subject_path": "x", "test_node": "y", "find": "a", "replace": "b"},
    }
    manifest.write_text(yaml.safe_dump({"schema_version": 1, "probes": [row]}), encoding="utf-8")
    output = tmp_path / "output.json"
    with patch.object(probe, "run_probe", return_value={"probe_count": 1}) as run:
        assert (
            probe.main(
                [
                    "--manifest",
                    str(manifest),
                    "--baseline-ref",
                    "base",
                    "--candidate-ref",
                    "head",
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
    assert run.call_args.args[2:] == ("base", "head", output)
