from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks import _pytest_diff_primary as primary
from scripts.checks._pytest_diff import STATE_ALL_DEFERRED, run_pytest_diff

_MISSING_HEAVY = "definitely_missing_fast_tier_dep"


def _run_primary(
    root: Path,
    targets: list[str],
    *,
    coverage_active: bool = False,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    with primary.capture_primary_deferrals(targets, {_MISSING_HEAVY}, coverage_active=coverage_active, root=root) as capture:
        environment = dict(capture.environment)
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (str(Path.cwd()), environment.get("PYTHONPATH", ""))))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *targets,
                "-q",
                *(extra_args or []),
                "-p",
                "scripts.checks._pytest_diff_primary",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result, capture.read()


def test_capture_reader_rejects_missing_incomplete_and_invalid_payloads(tmp_path: Path) -> None:
    capture = primary.PrimaryCapture(tmp_path / "capture.json", {})
    with pytest.raises(RuntimeError, match="missing or invalid"):
        capture.read()
    capture.path.write_text('{"complete": false, "deferred": {}}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete"):
        capture.read()
    capture.path.write_text('{"complete": true, "deferred": {"test.py": 3}}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid entries"):
        capture.read()


def test_primary_session_defers_heavy_collection_and_executes_good_node_under_xdist(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_good.py").write_text("def test_good():\n    assert True\n", encoding="utf-8")
    (tests / "test_heavy.py").write_text(f"import {_MISSING_HEAVY}\n", encoding="utf-8")
    targets = ["tests/test_heavy.py", "tests/test_good.py"]

    result, deferred = _run_primary(tmp_path, targets, extra_args=["-n", "2"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert deferred == {"tests/test_heavy.py": _MISSING_HEAVY}
    assert "1 passed" in result.stdout
    assert "ERROR collecting" not in result.stdout


def test_primary_session_keeps_nonheavy_collection_errors_hard_red(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_broken.py").write_text("import missing_repo_module\n", encoding="utf-8")

    result, deferred = _run_primary(tmp_path, ["tests/test_broken.py"])

    assert result.returncode == pytest.ExitCode.INTERRUPTED
    assert deferred == {}
    assert "ERROR collecting" in result.stdout


def test_primary_session_reports_all_deferred_separately_from_not_collected(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_heavy.py").write_text(f'import pytest\npytest.importorskip("{_MISSING_HEAVY}")\n', encoding="utf-8")

    result, deferred = _run_primary(tmp_path, ["tests/test_heavy.py"], extra_args=["-n", "2"])

    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED
    assert deferred == {"tests/test_heavy.py": _MISSING_HEAVY}
    assert "ERROR collecting" not in result.stdout


def test_run_pytest_diff_consumes_real_all_deferred_capture_without_reddening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    target = "tests/test_heavy.py"
    (tmp_path / target).write_text(f"import {_MISSING_HEAVY}\n", encoding="utf-8")
    failed: list[str] = []
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd()))

    with (
        patch("scripts.checks._common.ROOT", tmp_path),
        patch("scripts.checks._pytest_diff._derive_changed_sources", return_value=([], True)),
        patch("scripts.checks._pytest_diff._excluded_heavy_import_names", return_value={_MISSING_HEAVY}),
        patch("scripts.checks._pytest_diff._PYTEST_FLAGS", ["-n", "2"]),
        patch("scripts.checks._pytest_diff._write_deferral_map") as write_map,
    ):
        run_pytest_diff([target], failed)

    assert failed == []
    write_map.assert_called_once_with(STATE_ALL_DEFERRED, {target: _MISSING_HEAVY})


def test_deferred_collection_rolls_back_only_its_scoped_coverage(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "good_subject.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "heavy_subject.py").write_text("TOUCHED_BEFORE_MISSING_IMPORT = True\n", encoding="utf-8")
    (tests / "test_good.py").write_text(
        "from good_subject import VALUE\n\ndef test_good():\n    assert VALUE == 1\n", encoding="utf-8"
    )
    (tests / "test_heavy.py").write_text(f"import heavy_subject\nimport {_MISSING_HEAVY}\n", encoding="utf-8")
    config = tmp_path / "coverage.ini"
    config.write_text("[run]\ninclude =\n    */good_subject.py\n    */heavy_subject.py\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    coverage_args = [
        "--cov",
        f"--cov-config={config}",
        "--cov-fail-under=0",
        f"--cov-report=json:{baseline}",
        "-n",
        "2",
    ]
    baseline_result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_good.py", "-q", *coverage_args],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(tmp_path), str(Path.cwd())))},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert baseline_result.returncode == 0, baseline_result.stdout + baseline_result.stderr
    coverage_args[3] = f"--cov-report=json:{candidate}"

    candidate_result, deferred = _run_primary(
        tmp_path,
        ["tests/test_good.py", "tests/test_heavy.py"],
        coverage_active=True,
        extra_args=coverage_args,
    )

    assert candidate_result.returncode == 0, candidate_result.stdout + candidate_result.stderr
    assert deferred == {"tests/test_heavy.py": _MISSING_HEAVY}
    baseline_files = json.loads(baseline.read_text(encoding="utf-8"))["files"]
    candidate_files = json.loads(candidate.read_text(encoding="utf-8"))["files"]
    assert candidate_files == baseline_files
