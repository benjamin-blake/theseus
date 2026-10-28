"""The speculative-plan PR comment carries the reviewer-digest fit line without ever failing the step."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "terraform-apply-sandbox.yml"
FALLBACK = "|| echo 'Reviewer digest: fit unavailable.'"


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _comment_step() -> dict:
    steps = _jobs()["speculative-plan"]["steps"]
    matches = [s for s in steps if str(s.get("name", "")).startswith("Build and post PR comment")]
    assert len(matches) == 1
    return matches[0]


def _fit_line() -> str:
    lines = [ln for ln in _comment_step()["run"].splitlines() if "--fit-report" in ln]
    assert len(lines) == 1
    return lines[0].strip()


def test_fit_report_is_wired_once_on_the_predicted_verdict_line() -> None:
    body = _comment_step()["run"]
    assert body.count("scripts/ci/terraform_plan_digest.py") == 1
    line = _fit_line()
    assert line.startswith("COMMENT+=") and "Predicted guard verdict: ${PREDICTED_VERDICT}" in line
    assert "--fit-report plan.json" in line and FALLBACK in line


def test_apply_job_never_references_fit_report() -> None:
    for name, job in _jobs().items():
        if name == "speculative-plan":
            continue
        for step in job.get("steps", []):
            assert "--fit-report" not in str(step.get("run", ""))


@pytest.mark.parametrize(
    ("shim", "expected"),
    [("echo 'Reviewer digest: 3 actionable'", "Reviewer digest: 3 actionable"), ("exit 7", "fit unavailable")],
)
def test_substitution_never_fails_the_step(tmp_path: Path, shim: str, expected: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    py = bin_dir / "python3"
    py.write_text(f"#!/usr/bin/env bash\n{shim}\n", encoding="utf-8")
    py.chmod(0o755)
    script = f"""set -euo pipefail
_NL=$'\\n'
COMMENT=""
{_fit_line()}
printf '%s' "$COMMENT"
"""
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "PREDICTED_VERDICT": "APPROVED", "GITHUB_WORKSPACE": str(ROOT)}
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout and "Predicted guard verdict: APPROVED" in result.stdout
