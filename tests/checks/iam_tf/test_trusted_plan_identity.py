"""Standing guard for PLAN-trusted-plan-identity (rec-4636).

PR 1 asserts that the bootstrap apply role can refresh-read the trusted-plan role once it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_READS_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_reads.tf"
_ROLE_ARN = "arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-trusted-plan"


def _iam_roles_read_resources(text: str) -> list[str]:
    match = re.search(r'Sid\s*=\s*"IAMRolesRead".*?Resource\s*=\s*\[(.*?)\n\s*\]', text, re.DOTALL)
    assert match, "IAMRolesRead statement not found"
    body = re.sub(r"#[^\n]*", "", match.group(1))
    return re.findall(r'"([^"]+)"', body)


def test_bootstrap_iam_roles_read_lists_trusted_plan_role() -> None:
    resources = _iam_roles_read_resources(_READS_FILE.read_text(encoding="utf-8"))
    assert resources.count(_ROLE_ARN) == 1


def test_bootstrap_assertion_reddens_without_the_arn() -> None:
    text = _READS_FILE.read_text(encoding="utf-8").replace(_ROLE_ARN, "arn:aws:iam::${var.account_id}:role/other")
    assert _ROLE_ARN not in _iam_roles_read_resources(text)
