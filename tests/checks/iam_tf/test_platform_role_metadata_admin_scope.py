"""Standing guard pinning the rec-3327 / Decision 180 metadata-write scope class.

Mirrors tests/checks/iam_tf/test_iam_role_reconcile_trust_scope.py's structure. Pins BOTH
directions: IAMRoleMetadataWrite's Resource set must be exactly {role/agent-platform-*,
role/PlatformDev}, and no Allow Sid anywhere in the policy may match a concrete PlatformAdmin ARN
-- IAMRoleMetadataWrite and IAMRoleDeleteBounded carry no boundary Condition, so a matched
PlatformAdmin becomes CI-mutable/CI-deletable (a grant leak, not a test bug). A future re-widening
of either must be a reviewed edit to this assertion, never a quiet HCL comment.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_policy.tf"
_ACCOUNT_ID = "123456789012"
_AWS_REGION = "eu-west-2"

_EXPECTED_METADATA_WRITE_RESOURCES = frozenset(
    {
        "arn:aws:iam::${var.account_id}:role/agent-platform-*",
        "arn:aws:iam::${var.account_id}:role/PlatformDev",
    }
)


def _policy_text() -> str:
    return _POLICY_FILE.read_text(encoding="utf-8")


def _statement_blocks(text: str) -> dict[str, str]:
    """Split the Statement array into per-Sid text blocks, each running from its own
    `Sid = "..."` to the next one's (or end of file for the last)."""
    matches = list(re.finditer(r'Sid\s*=\s*"([^"]+)"', text))
    blocks: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks[m.group(1)] = text[start:end]
    return blocks


def _resource_list(block: str) -> list[str]:
    m = re.search(r"Resource\s*=\s*\[(?P<body>.*?)\]", block, re.S)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group("body"))


def _effect(block: str) -> str | None:
    m = re.search(r'Effect\s*=\s*"([^"]+)"', block)
    return m.group(1) if m else None


class TestIAMRoleMetadataWriteScope:
    def test_resource_set_is_exactly_agent_platform_prefix_and_platformdev(self) -> None:
        block = _statement_blocks(_policy_text())["IAMRoleMetadataWrite"]
        got = frozenset(_resource_list(block))
        assert got == _EXPECTED_METADATA_WRITE_RESOURCES, (
            f"IAMRoleMetadataWrite Resource set is {sorted(got)}, expected exactly "
            f"{sorted(_EXPECTED_METADATA_WRITE_RESOURCES)} -- a re-widening must be a reviewed "
            "edit to this assertion, never a quiet HCL comment."
        )

    def test_carries_all_four_metadata_verbs(self) -> None:
        block = _statement_blocks(_policy_text())["IAMRoleMetadataWrite"]
        action_match = re.search(r"Action\s*=\s*\[(?P<body>.*?)\]", block, re.S)
        assert action_match is not None
        actions = set(re.findall(r'"([^"]+)"', action_match.group("body")))
        assert actions == {"iam:TagRole", "iam:UntagRole", "iam:UpdateRole", "iam:UpdateRoleDescription"}


class TestPlatformAdminNeverMatchedByAnyAllowSid:
    def test_no_allow_sid_resource_pattern_matches_a_concrete_platformadmin_arn(self) -> None:
        blocks = _statement_blocks(_policy_text())
        admin_arn = f"arn:aws:iam::{_ACCOUNT_ID}:role/PlatformAdmin"
        leaks: list[tuple[str, str]] = []
        for sid, block in blocks.items():
            if _effect(block) != "Allow":
                continue
            for pattern in _resource_list(block):
                concrete = pattern.replace("${var.account_id}", _ACCOUNT_ID).replace("${var.aws_region}", _AWS_REGION)
                if fnmatch.fnmatch(admin_arn, concrete):
                    leaks.append((sid, pattern))
        assert leaks == [], f"GRANT LEAK -- PlatformAdmin matched by Allow Sid Resource pattern(s): {leaks}"
