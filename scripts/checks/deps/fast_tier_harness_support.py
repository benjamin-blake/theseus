"""Dependency-environment and reporting support for the fast-tier audit harness."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class HarnessError(RuntimeError):
    """A fail-loud corpus or execution error."""


def _required_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HarnessError(f"required fast-tier environment input is unavailable: {path}: {exc}") from exc


def environment_fingerprint(repo_root: Path) -> str:
    digest = hashlib.sha256(f"{sys.version_info[:3]}\n".encode())
    for name in ("requirements-fast.txt", "requirements-dev.txt"):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(_required_file(repo_root / name))
        digest.update(b"\0")
    return digest.hexdigest()


def _environment_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run_environment_command(command: list[str], repo_root: Path) -> None:
    result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise HarnessError(
            f"fast-tier environment setup failed: {' '.join(command)}: {(result.stdout + result.stderr).strip()}"
        )


def ensure_fast_environment(repo_root: Path, cache_root: Path) -> tuple[Path, str]:
    fingerprint = environment_fingerprint(repo_root)
    environment = cache_root / fingerprint
    python = _environment_python(environment)
    ready = environment / ".ready"
    if ready.is_file() and ready.read_text(encoding="utf-8").strip() == fingerprint:
        if not python.is_file():
            raise HarnessError(f"cached fast-tier environment lacks its interpreter: {python}")
        return python, fingerprint
    cache_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{fingerprint}-", dir=cache_root))
    try:
        _run_environment_command([sys.executable, "-m", "virtualenv", str(staging)], repo_root)
        staging_python = _environment_python(staging)
        _run_environment_command([str(staging_python), "-m", "pip", "install", "--upgrade", "pip"], repo_root)
        _run_environment_command(
            [
                str(staging_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(repo_root / "requirements-fast.txt"),
                "-r",
                str(repo_root / "requirements-dev.txt"),
            ],
            repo_root,
        )
        (staging / ".ready").write_text(f"{fingerprint}\n", encoding="utf-8")
        try:
            staging.rename(environment)
        except FileExistsError:
            shutil.rmtree(staging)
        if not python.is_file():
            raise HarnessError(f"fast-tier environment lacks its interpreter after setup: {python}")
        return python, fingerprint
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def predictor_report(pairs: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        reported = pair["plan"]["reported"]
        observed = pair["observed"]
        low, high = reported["predicted_test_half_s"]
        rows.append(
            {
                "id": pair["id"],
                "plan_prs": pair["plan"]["prs"],
                "implementation_pr": pair["implementation"]["pr"],
                "predicted_n_selected": reported["n_selected"],
                "observed_n_selected": observed["n_selected"],
                "n_selected_delta": observed["n_selected"] - reported["n_selected"],
                "predicted_test_half_s": [low, high],
                "observed_test_s": observed["test_s"],
                "test_s_in_predicted_range": low <= observed["test_s"] <= high,
                "workflow_run_id": observed["workflow_run_id"],
                "artifact_id": observed["artifact_id"],
            }
        )
    return {
        "pair_count": len(rows),
        "n_selected_exact_count": sum(row["n_selected_delta"] == 0 for row in rows),
        "test_s_in_predicted_range_count": sum(row["test_s_in_predicted_range"] for row in rows),
        "pairs": rows,
    }
