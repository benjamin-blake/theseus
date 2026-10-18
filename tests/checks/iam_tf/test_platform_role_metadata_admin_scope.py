"""Standing guard for Decision 225 (rec-4049): no CI identity holds an IAM grant on PlatformDev or
PlatformAdmin.

Mirrors tests/checks/iam_tf/test_iam_role_reconcile_trust_scope.py's structure. Pins THREE things:
(1) IAMRoleMetadataWrite's Resource set is exactly {role/agent-platform-*} (Decision 225 clause 2
narrowed it once Decision 223 moved PlatformDev to terraform/bootstrap); (2) no Allow Sid anywhere
in the apply-role policy matches a concrete PlatformDev or PlatformAdmin ARN -- IAMRoleMetadataWrite
and IAMRoleDeleteBounded carry no boundary Condition, so a matched role becomes CI-mutable/
CI-deletable (a grant leak, not a test bug); (3) no Allow statement carrying an iam: action, in
terraform/bootstrap's two apply-role policy files or ANY terraform/personal/*.tf file (all of it
CI-applied), matches either role -- the real predicate, driven against mutated HCL per Decision
187 (tests/checks/iam_tf/_ci_platform_role_iam.py).
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from tests.checks.iam_tf._ci_platform_role_iam import (
    ci_platform_role_iam_leaks,
    independent_jsonencode_counts,
    independent_statement_counts,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_policy.tf"
_READS_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_reads.tf"
_PERSONAL_DIR = _REPO_ROOT / "terraform" / "personal"
_ACCOUNT_ID = "123456789012"
_AWS_REGION = "eu-west-2"

# The guard's fail-closed scanned-file list (literal paths -- this is what makes --pre select
# this module for an edit to any of these files; see test_platform_iam_admin_root_only.py for the
# oidc.tf -> Decision 223 guard edge, kept by a docstring mention there, not here).
_SCANNED_BOOTSTRAP_FILES = (_POLICY_FILE, _READS_FILE)
_SCANNED_PERSONAL_GLOB = "*.tf"

_EXPECTED_METADATA_WRITE_RESOURCES = frozenset(
    {
        "arn:aws:iam::${var.account_id}:role/agent-platform-*",
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


def _scanned_texts() -> dict[str, str]:
    texts = {str(f.relative_to(_REPO_ROOT)): f.read_text(encoding="utf-8") for f in _SCANNED_BOOTSTRAP_FILES}
    for f in sorted(_PERSONAL_DIR.glob(_SCANNED_PERSONAL_GLOB)):
        texts[str(f.relative_to(_REPO_ROOT))] = f.read_text(encoding="utf-8")
    return texts


class TestIAMRoleMetadataWriteScope:
    def test_resource_set_is_exactly_agent_platform_prefix(self) -> None:
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

    def test_no_allow_sid_resource_pattern_matches_a_concrete_platformdev_arn(self) -> None:
        blocks = _statement_blocks(_policy_text())
        dev_arn = f"arn:aws:iam::{_ACCOUNT_ID}:role/PlatformDev"
        leaks: list[tuple[str, str]] = []
        for sid, block in blocks.items():
            if _effect(block) != "Allow":
                continue
            for pattern in _resource_list(block):
                concrete = pattern.replace("${var.account_id}", _ACCOUNT_ID).replace("${var.aws_region}", _AWS_REGION)
                if fnmatch.fnmatch(dev_arn, concrete):
                    leaks.append((sid, pattern))
        assert leaks == [], f"GRANT LEAK -- PlatformDev matched by Allow Sid Resource pattern(s): {leaks}"


class TestNoCIIamGrantOnPlatformRoles:
    def test_real_tree_has_no_leak(self) -> None:
        assert ci_platform_role_iam_leaks(_scanned_texts()) == []

    def test_fail_closed_counts_agree_on_every_scanned_file(self) -> None:
        for name, text in _scanned_texts().items():
            parsed_hcl, raw_hcl = independent_statement_counts(text)
            assert parsed_hcl == raw_hcl, f"{name}: parsed {parsed_hcl} statement{{}} blocks, raw count {raw_hcl}"
            parsed_json, raw_json = independent_jsonencode_counts(text)
            assert parsed_json == raw_json, f"{name}: parsed {parsed_json} jsonencode statements, raw count {raw_json}"

    def test_scanned_set_is_non_empty_and_every_expected_file_present(self) -> None:
        texts = _scanned_texts()
        assert texts
        for required in (
            "terraform/bootstrap/github_ci_apply_policy.tf",
            "terraform/bootstrap/github_ci_apply_reads.tf",
            "terraform/personal/oidc.tf",
            "terraform/personal/oidc_ci_roles.tf",
            "terraform/personal/oidc_pipeline_roles.tf",
        ):
            assert required in texts and texts[required].strip()

    def test_empty_scanned_file_fails_closed(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc.tf"] = ""
        import pytest

        with pytest.raises(ValueError, match="empty"):
            ci_platform_role_iam_leaks(texts)

    def test_platformdev_readded_to_iam_role_metadata_write_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/bootstrap/github_ci_apply_policy.tf"] = texts[
            "terraform/bootstrap/github_ci_apply_policy.tf"
        ].replace(
            'Resource = [\n          "arn:aws:iam::${var.account_id}:role/agent-platform-*",\n        ]\n      },\n      {\n        # In-budget CreateRole',
            'Resource = [\n          "arn:aws:iam::${var.account_id}:role/agent-platform-*",\n          "arn:aws:iam::${var.account_id}:role/PlatformDev",\n        ]\n      },\n      {\n        # In-budget CreateRole',
            1,
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformDev" for _, _, role in leaks)

    def test_platformadmin_added_to_bootstrap_iamrolesread_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/bootstrap/github_ci_apply_reads.tf"] = texts[
            "terraform/bootstrap/github_ci_apply_reads.tf"
        ].replace(
            '"arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-deploy",\n',
            '"arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-deploy",\n'
            '          "arn:aws:iam::${var.account_id}:role/PlatformAdmin",\n',
            1,
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformAdmin" for _, _, role in leaks)

    def test_platformdev_added_to_oidc_iamplatformrolesread_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc.tf"] = texts["terraform/personal/oidc.tf"].replace(
            'resources = [\n      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",',
            'resources = [\n      "arn:aws:iam::${var.account_id}:role/PlatformDev",\n'
            '      "arn:aws:iam::${var.account_id}:role/agent-platform-ducklake-catalog-dr",',
            1,
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformDev" for _, _, role in leaks)

    def test_role_wildcard_resource_in_oidc_pipeline_roles_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky" {\n'
            "  statement {\n"
            '    sid       = "Sneaky"\n'
            '    effect    = "Allow"\n'
            '    actions   = ["iam:GetRole"]\n'
            '    resources = ["arn:aws:iam::${var.account_id}:role/*"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert {role for _, _, role in leaks} == {"PlatformDev", "PlatformAdmin"}

    def test_non_iam_statement_with_resource_star_is_not_flagged(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "fine" {\n'
            "  statement {\n"
            '    sid       = "Fine"\n'
            '    effect    = "Allow"\n'
            '    actions   = ["s3:ListAllMyBuckets"]\n'
            '    resources = ["*"]\n'
            "  }\n}\n"
        )
        assert ci_platform_role_iam_leaks(texts) == []

    def test_scalar_resource_naming_platformdev_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky2" {\n'
            "  statement {\n"
            '    sid       = "Sneaky2"\n'
            '    effect    = "Allow"\n'
            '    actions   = ["iam:GetRole"]\n'
            '    resources = "arn:aws:iam::${var.account_id}:role/PlatformDev"\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformDev" for _, _, role in leaks)

    def test_sidless_jsonencode_statement_naming_platformadmin_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/bootstrap/github_ci_apply_policy.tf"] += (
            '\n\nresource "aws_iam_role_policy" "sneaky" {\n'
            "  policy = jsonencode({\n"
            '    Version = "2012-10-17"\n'
            "    Statement = [{\n"
            '      Effect   = "Allow"\n'
            '      Action   = ["iam:GetRolePolicy"]\n'
            '      Resource = ["arn:aws:iam::${var.account_id}:role/PlatformAdmin"]\n'
            "    }]\n"
            "  })\n"
            "}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformAdmin" and sid is None for _, sid, role in leaks)

    def test_effectless_hcl_statement_block_defaults_to_allow(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky3" {\n'
            "  statement {\n"
            '    sid       = "Sneaky3"\n'
            '    actions   = ["iam:GetRole"]\n'
            '    resources = ["arn:aws:iam::${var.account_id}:role/PlatformDev"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformDev" for _, _, role in leaks)

    def test_not_action_on_allow_is_detected_whatever_its_list(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky4" {\n'
            "  statement {\n"
            '    sid           = "Sneaky4"\n'
            '    effect        = "Allow"\n'
            '    not_actions   = ["s3:GetObject"]\n'
            '    resources     = ["arn:aws:iam::${var.account_id}:role/PlatformDev"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformDev" for _, _, role in leaks)

    def test_not_resource_on_iam_allow_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky5" {\n'
            "  statement {\n"
            '    sid           = "Sneaky5"\n'
            '    effect        = "Allow"\n'
            '    actions       = ["iam:GetRole"]\n'
            '    not_resources = ["arn:aws:iam::${var.account_id}:role/agent-platform-github-ci-apply"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert {role for _, _, role in leaks} >= {"PlatformDev", "PlatformAdmin"}

    def test_case_folded_action_pattern_covering_iam_is_detected(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky6" {\n'
            "  statement {\n"
            '    sid       = "Sneaky6"\n'
            '    effect    = "Allow"\n'
            '    actions   = ["IAM:Get*"]\n'
            '    resources = ["arn:aws:iam::${var.account_id}:role/PlatformAdmin"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformAdmin" for _, _, role in leaks)

    def test_unresolved_resource_on_iam_allow_fails_closed(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky7" {\n'
            "  statement {\n"
            '    sid       = "Sneaky7"\n'
            '    effect    = "Allow"\n'
            '    actions   = ["iam:GetRole"]\n'
            '    resources = ["arn:aws:iam::${var.account_id}:role/${local.mystery}"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert {role for _, _, role in leaks} == {"PlatformDev", "PlatformAdmin"}

    def test_lowercase_role_name_is_detected_case_insensitively(self) -> None:
        texts = dict(_scanned_texts())
        texts["terraform/personal/oidc_pipeline_roles.tf"] += (
            '\n\ndata "aws_iam_policy_document" "sneaky8" {\n'
            "  statement {\n"
            '    sid       = "Sneaky8"\n'
            '    effect    = "Allow"\n'
            '    actions   = ["iam:GetRole"]\n'
            '    resources = ["arn:aws:iam::${var.account_id}:role/platformdev"]\n'
            "  }\n}\n"
        )
        leaks = ci_platform_role_iam_leaks(texts)
        assert any(role == "PlatformDev" for _, _, role in leaks)
