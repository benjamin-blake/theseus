"""Structural regression guard for .github/workflows/backlog-health.yml's probe job
(PLAN-backlog-health-detection). Codifies the checks VP steps 3/4 run ad hoc against this file,
plus the isolation-availability fix below, so a future edit cannot silently regress them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "backlog-health.yml"


def _load_probe_job() -> dict[str, Any]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    return workflow["jobs"]["probe"]


def _step_names(job: dict[str, Any]) -> list[str]:
    return [step.get("name", "") for step in job["steps"]]


def test_probe_job_allows_unprivileged_user_namespaces_before_running_probe() -> None:
    """Regression (VP step 11, live workflow_dispatch on main): GitHub-hosted ubuntu-latest
    runners default kernel.apparmor_restrict_unprivileged_userns=1, so unshare -rmn fails
    immediately and every entry gets isolation_unavailable -- the monitor never actually probes
    anything. The mitigating sysctl step must exist and run strictly before the probe step."""
    job = _load_probe_job()
    steps = job["steps"]
    sysctl_index = next(
        (i for i, step in enumerate(steps) if "apparmor_restrict_unprivileged_userns=0" in (step.get("run") or "")),
        None,
    )
    assert sysctl_index is not None, "probe job is missing the AppArmor unprivileged-userns sysctl step"
    probe_index = next(i for i, step in enumerate(steps) if step.get("name", "").startswith("Run probe"))
    assert sysctl_index < probe_index


def test_probe_job_still_credential_free() -> None:
    """Regression guard for VP step 3: the new sysctl step must not introduce id-token or a
    secrets reference -- sudo on a GitHub-hosted runner needs no AWS/OIDC credential."""
    job = _load_probe_job()
    dumped = yaml.dump(job)
    permissions = job.get("permissions")
    assert isinstance(permissions, dict)
    assert "id-token" not in permissions
    assert "secrets." not in dumped
    assert "persist-credentials: false" in dumped
