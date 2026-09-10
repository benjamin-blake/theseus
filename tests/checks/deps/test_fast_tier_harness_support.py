from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.deps import fast_tier_harness_support as support


def _requirements(root: Path, fast: str = "fast\n", dev: str = "dev\n") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements-fast.txt").write_text(fast, encoding="utf-8")
    (root / "requirements-dev.txt").write_text(dev, encoding="utf-8")


def test_environment_fingerprint_is_content_addressed_and_requires_both_inputs(tmp_path: Path) -> None:
    _requirements(tmp_path)
    first = support.environment_fingerprint(tmp_path)
    _requirements(tmp_path, fast="changed\n")
    assert support.environment_fingerprint(tmp_path) != first
    (tmp_path / "requirements-dev.txt").unlink()
    with pytest.raises(support.HarnessError, match="required fast-tier environment input"):
        support.environment_fingerprint(tmp_path)


def test_environment_python_is_platform_aware(tmp_path: Path) -> None:
    expected = Path("Scripts/python.exe") if support.os.name == "nt" else Path("bin/python")
    assert support._environment_python(tmp_path) == tmp_path / expected


def test_environment_command_fails_loudly(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess([], 2, "out", "err")
    with patch.object(support.subprocess, "run", return_value=completed):
        with pytest.raises(support.HarnessError, match="environment setup failed.*outerr"):
            support._run_environment_command(["tool", "arg"], tmp_path)


def test_environment_command_accepts_success(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess([], 0, "", "")
    with patch.object(support.subprocess, "run", return_value=completed):
        support._run_environment_command(["tool"], tmp_path)


def test_ensure_fast_environment_builds_reuses_and_rejects_broken_cache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    _requirements(repo)

    def fake_run(command: list[str], repo_root: Path) -> None:
        assert repo_root == repo
        if command[1:3] == ["-m", "virtualenv"]:
            python = support._environment_python(Path(command[3]))
            python.parent.mkdir(parents=True)
            python.write_text("python", encoding="utf-8")

    with patch.object(support, "_run_environment_command", side_effect=fake_run) as run:
        python, fingerprint = support.ensure_fast_environment(repo, cache)
        assert python.is_file()
        assert run.call_count == 3
        assert support.ensure_fast_environment(repo, cache) == (python, fingerprint)
        assert run.call_count == 3
    python.unlink()
    with pytest.raises(support.HarnessError, match="cached fast-tier environment lacks"):
        support.ensure_fast_environment(repo, cache)


def test_ensure_fast_environment_cleans_failed_staging(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    _requirements(repo)
    with patch.object(support, "_run_environment_command", side_effect=support.HarnessError("failed")):
        with pytest.raises(support.HarnessError, match="failed"):
            support.ensure_fast_environment(repo, cache)
    assert list(cache.iterdir()) == []


def test_ensure_fast_environment_rejects_setup_without_interpreter(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    _requirements(repo)
    with patch.object(support, "_run_environment_command"):
        with pytest.raises(support.HarnessError, match="lacks its interpreter after setup"):
            support.ensure_fast_environment(repo, cache)


def test_ensure_fast_environment_accepts_concurrent_completed_cache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    _requirements(repo)
    fingerprint = support.environment_fingerprint(repo)
    final = cache / fingerprint

    def fake_rename(self: Path, target: Path) -> Path:
        target.mkdir(parents=True)
        python = support._environment_python(target)
        python.parent.mkdir(parents=True)
        python.write_text("python", encoding="utf-8")
        (target / ".ready").write_text(f"{fingerprint}\n", encoding="utf-8")
        raise FileExistsError

    def fake_run(command: list[str], repo_root: Path) -> None:
        if command[1:3] == ["-m", "virtualenv"]:
            python = support._environment_python(Path(command[3]))
            python.parent.mkdir(parents=True)
            python.write_text("python", encoding="utf-8")

    with patch.object(support, "_run_environment_command", side_effect=fake_run), patch.object(Path, "rename", fake_rename):
        assert support.ensure_fast_environment(repo, cache) == (support._environment_python(final), fingerprint)


def test_predictor_report_recomputes_both_calibration_dimensions() -> None:
    pairs = (
        {
            "id": "one",
            "plan": {"prs": [1], "reported": {"n_selected": 4, "predicted_test_half_s": [10.0, 20.0]}},
            "implementation": {"pr": 2},
            "observed": {"n_selected": 4, "test_s": 15.0, "workflow_run_id": 3, "artifact_id": 4},
        },
        {
            "id": "two",
            "plan": {"prs": [5], "reported": {"n_selected": 6, "predicted_test_half_s": [10.0, 20.0]}},
            "implementation": {"pr": 6},
            "observed": {"n_selected": 8, "test_s": 25.0, "workflow_run_id": 7, "artifact_id": 8},
        },
    )
    report = support.predictor_report(pairs)
    assert report["pair_count"] == 2
    assert report["n_selected_exact_count"] == 1
    assert report["test_s_in_predicted_range_count"] == 1
    assert report["pairs"][1]["n_selected_delta"] == 2
    assert report["pairs"][1]["test_s_in_predicted_range"] is False
