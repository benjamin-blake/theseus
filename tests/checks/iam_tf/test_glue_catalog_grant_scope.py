"""Standing guard pinning the PLAN-glue-delete-database-grant restore (Decision 178 clause 4 drain).

Mirrors tests/checks/iam_tf/test_platform_role_metadata_admin_scope.py's _statement_blocks
per-Sid structure -- so "right token in the wrong Sid" fails, not just "right token somewhere in
the file". Pins the resource axis (exactly the four ARNs, including the userDefinedFunction ARN
run 33323201848 denied on), the verb axis (destroy-path only, Decision 143 worst-verb scoping --
no create/update verb survives the cleanse's HCL), the boundary ceiling (glue admitted, athena
never re-admitted at either layer, Decision 178 clause 2), and the iam-simulate-fixture's
multi-resource-type arming (both the database and userDefinedFunction axes carry a live triple,
not just a declared-but-inert map entry).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_policy.tf"
_BOUNDARY_FILE = _REPO_ROOT / "terraform" / "bootstrap" / "github_ci_apply_boundary.tf"
_FIXTURE_FILE = _REPO_ROOT / "docs" / "contracts" / "iam-simulate-fixture.yaml"

_EXPECTED_RESOURCES = frozenset(
    {
        "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
        "arn:aws:glue:${var.aws_region}:${var.account_id}:database/agent_platform",
        "arn:aws:glue:${var.aws_region}:${var.account_id}:table/agent_platform/*",
        "arn:aws:glue:${var.aws_region}:${var.account_id}:userDefinedFunction/agent_platform/*",
    }
)
_FORBIDDEN_CREATE_UPDATE_VERBS = frozenset(
    {"glue:CreateDatabase", "glue:UpdateDatabase", "glue:CreateTable", "glue:UpdateTable"}
)


def _statement_blocks(text: str) -> dict[str, str]:
    """Split a Statement array into per-Sid text blocks, each running from its own
    `Sid = "..."` to the next one's (or end of file for the last)."""
    matches = list(re.finditer(r'Sid\s*=\s*"([^"]+)"', text))
    blocks: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks[m.group(1)] = text[start:end]
    return blocks


def _bracket_list(block: str, field: str) -> list[str]:
    m = re.search(rf"{field}\s*=\s*\[(?P<body>.*?)\]", block, re.S)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group("body"))


class TestGlueCatalogGrantScope:
    def test_resource_set_is_exactly_the_four_arns(self) -> None:
        block = _statement_blocks(_POLICY_FILE.read_text(encoding="utf-8"))["GlueCatalog"]
        got = frozenset(_bracket_list(block, "Resource"))
        assert got == _EXPECTED_RESOURCES, (
            f"GlueCatalog Resource set is {sorted(got)}, expected exactly {sorted(_EXPECTED_RESOURCES)} -- "
            "including userDefinedFunction/agent_platform/*, the axis run 33323201848 denied on."
        )

    def test_no_create_or_update_verbs_present(self) -> None:
        block = _statement_blocks(_POLICY_FILE.read_text(encoding="utf-8"))["GlueCatalog"]
        actions = set(_bracket_list(block, "Action"))
        assert "glue:DeleteDatabase" in actions, actions
        leaked = actions & _FORBIDDEN_CREATE_UPDATE_VERBS
        assert not leaked, (
            f"GlueCatalog grants create/update verb(s) {sorted(leaked)} -- Decision 143 worst-verb "
            "scoping restores the destroy path only; no remaining HCL can reach them."
        )

    def test_boundary_ceiling_permits_glue_and_excludes_athena(self) -> None:
        policy_blocks = _statement_blocks(_POLICY_FILE.read_text(encoding="utf-8"))
        boundary_blocks = _statement_blocks(_BOUNDARY_FILE.read_text(encoding="utf-8"))
        boundary_actions = _bracket_list(boundary_blocks["DataPlaneAllow"], "Action")
        assert "glue:*" in boundary_actions, boundary_actions
        # Decision 178 clause 2: athena stays absent at BOTH layers. STRUCTURAL, per-Sid Action-array
        # parse -- never a raw-text grep: the boundary's own top-of-file comment legitimately MENTIONS
        # "athena" while explaining its deliberate non-restoration, so a bare substring search over
        # the whole file would false-positive on that documentation.
        all_blocks = (*policy_blocks.values(), *boundary_blocks.values())
        all_actions = [a for block in all_blocks for a in _bracket_list(block, "Action")]
        leaked = [a for a in all_actions if a.lower().startswith("athena")]
        assert not leaked, f"athena action(s) present in an identity/boundary Sid: {leaked}"

    def test_fixture_arms_both_resource_axes(self) -> None:
        data = yaml.safe_load(_FIXTURE_FILE.read_text(encoding="utf-8"))
        assert data["multi_resource_type_verbs"]["glue:DeleteDatabase"] == ["database", "userDefinedFunction"]
        glue_rows = [t for t in data["triples"] if t["verb"] == "glue:DeleteDatabase"]
        axes = {"database" if "database/" in t["target_arn_template"] else "userDefinedFunction" for t in glue_rows}
        assert axes == {"database", "userDefinedFunction"}, (
            f"glue:DeleteDatabase fixture rows cover axes {sorted(axes)}, expected both -- an "
            "armed-but-inert map entry with a missing axis row is exactly the rec-3325 failure mode."
        )
        assert all(t["expected_decision"] == "allowed" for t in glue_rows), glue_rows
