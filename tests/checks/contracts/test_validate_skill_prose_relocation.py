"""Tests for validate_skill_prose_relocation() -- PLAN-skills-layer-prose-relocation.

Covers the green path (every map row resolves, every stub carries its anchored pointer and tier
wording, no agent_surface anchor lost) and the three failure modes test_obligations names: a
re-inlined relocated sentence (using a REAL production stub_heading/marker pair so the module's
own _REINLINE_MARKERS dict is genuinely exercised), a stub whose body never names its destination
file (bare-filename-pointer style miss), and a map row whose destination anchor does not resolve
in the parsed destination YAML -- plus missing-file, malformed-YAML, and agent_surface-anchor
edge cases.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks.contracts.validate_skill_prose_relocation import validate_skill_prose_relocation

_IA_REL_PATH = "docs/contracts/instruction-architecture.yaml"
_WIDGET_REL_PATH = "docs/contracts/widget-contract.yaml"

_PLANNING_STUB = (
    "See `docs/contracts/widget-contract.yaml#widget_walk` for the full walk "
    "(MANDATORY read-trigger -- read this before scoping).\n"
)
_IMPLEMENT_STUB = (
    "See `docs/contracts/widget-contract.yaml#gadget_steps` for the full procedure "
    "(conditional read-trigger -- read only when this step fires).\n"
)

_PLANNING_TEXT = (
    "# Planning\n\n"
    "## Widget Assessment (Workflow Step 4)\n"
    f"{_PLANNING_STUB}\n"
    "## Next Section\n"
    "Consult docs/contracts/_joins.yaml for join keys.\n"
)

_IMPLEMENT_TEXT = (
    "# Implement\n\n"
    "## Gadget Bookkeeping (Workflow Step 6)\n"
    f"{_IMPLEMENT_STUB}\n"
    "## Next Section\n"
    "See docs/contracts/candidate-decision-ratification.yaml for the ratification lane.\n"
)

_WIDGET_CONTRACT_BODY = {
    "contract": {"id": "widget-contract", "class": "D", "contract_version": 1, "status": "ratified"},
    "widget_walk": "the full widget walk text",
    "gadget_steps": "the full gadget steps text",
}

_DEFAULT_MAP = [
    {
        "stub_heading": "## Widget Assessment (Workflow Step 4)",
        "surface": "planning",
        "destination": f"{_WIDGET_REL_PATH}#widget_walk",
        "enforcing_check": "validate_skill_prose_relocation",
        "tier": "mandatory",
    },
    {
        "stub_heading": "## Gadget Bookkeeping (Workflow Step 6)",
        "surface": "implement",
        "destination": f"{_WIDGET_REL_PATH}#gadget_steps",
        "enforcing_check": "validate_skill_prose_relocation",
        "tier": "conditional",
    },
]


_UNSET: list[dict] = []


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_repo(
    tmp_path: Path,
    *,
    relocation_map: list[dict] | None = _UNSET,
    planning_text: str | None = _PLANNING_TEXT,
    implement_text: str | None = _IMPLEMENT_TEXT,
    write_ia: bool = True,
    write_widget_contract: bool = True,
    widget_contract_body: dict | None = None,
    write_tier_item_lifecycle: bool = True,
) -> Path:
    if relocation_map is _UNSET:
        relocation_map = _DEFAULT_MAP

    if write_ia:
        ia_body: dict = {"contract": {"id": "instruction-architecture", "class": "D"}}
        if relocation_map is not None:
            ia_body["layer4_relocation_map"] = relocation_map
        _write(tmp_path / _IA_REL_PATH, yaml.safe_dump(ia_body))

    if write_widget_contract:
        body = widget_contract_body if widget_contract_body is not None else _WIDGET_CONTRACT_BODY
        _write(tmp_path / _WIDGET_REL_PATH, yaml.safe_dump(body))

    # tier-item-lifecycle.yaml existence is asserted independently of the map.
    if write_tier_item_lifecycle:
        _write(
            tmp_path / "docs" / "contracts" / "tier-item-lifecycle.yaml",
            yaml.safe_dump({"contract": {"id": "tier-item-lifecycle", "class": "D"}}),
        )

    if planning_text is not None:
        _write(tmp_path / ".claude" / "skills" / "planning" / "SKILL.md", planning_text)
    if implement_text is not None:
        _write(tmp_path / ".claude" / "skills" / "implement" / "SKILL.md", implement_text)

    return tmp_path


class TestGreenPath:
    def test_default_fixture_passes(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert failed == []


class TestReInlinedRelocationRedPath:
    def test_reinlined_giveaway_phrase_fails(self, tmp_path: Path) -> None:
        """Uses a REAL production stub_heading (Data-Model Assessment) so the module's own
        _REINLINE_MARKERS dict is genuinely exercised, not a fixture-local dict."""
        real_heading = "## Data-Model Assessment (Workflow Step 4)"
        relocation_map = [
            {
                "stub_heading": real_heading,
                "surface": "planning",
                "destination": f"{_WIDGET_REL_PATH}#widget_walk",
                "enforcing_check": "validate_skill_prose_relocation",
                "tier": "mandatory",
            },
        ]
        planning_text = (
            "# Planning\n\n"
            f"{real_heading}\n"
            "See `docs/contracts/widget-contract.yaml#widget_walk` (mandatory read-trigger).\n"
            "Fable escalation: for load-bearing/novel calls only -- re-inlined verbatim here.\n\n"
            "## Next Section\n"
        )
        _write_repo(tmp_path, relocation_map=relocation_map, planning_text=planning_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("re-inlines relocated content" in f for f in failed)

    def test_same_heading_without_giveaway_phrase_passes(self, tmp_path: Path) -> None:
        """Non-vacuity companion: the SAME real heading, genuinely relocated (no giveaway
        phrase), passes -- proves the red case above is about the phrase, not the heading."""
        real_heading = "## Data-Model Assessment (Workflow Step 4)"
        relocation_map = [
            {
                "stub_heading": real_heading,
                "surface": "planning",
                "destination": f"{_WIDGET_REL_PATH}#widget_walk",
                "enforcing_check": "validate_skill_prose_relocation",
                "tier": "mandatory",
            },
        ]
        planning_text = (
            "# Planning\n\n"
            f"{real_heading}\n"
            "See `docs/contracts/widget-contract.yaml#widget_walk` (mandatory read-trigger).\n\n"
            "## Next Section\n"
            "Consult docs/contracts/_joins.yaml for join keys.\n"
        )
        _write_repo(tmp_path, relocation_map=relocation_map, planning_text=planning_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert failed == []


class TestBareFilenamePointerRedPath:
    def test_stub_missing_destination_basename_fails(self, tmp_path: Path) -> None:
        planning_text = (
            "# Planning\n\n"
            "## Widget Assessment (Workflow Step 4)\n"
            "This step is mandatory but never names its destination.\n\n"
            "## Next Section\n"
            "Consult docs/contracts/_joins.yaml for join keys.\n"
        )
        _write_repo(tmp_path, planning_text=planning_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("does not name its anchored pointer" in f for f in failed)

    def test_stub_missing_tier_wording_fails(self, tmp_path: Path) -> None:
        planning_text = (
            "# Planning\n\n"
            "## Widget Assessment (Workflow Step 4)\n"
            "See `docs/contracts/widget-contract.yaml#widget_walk` for the walk.\n\n"
            "## Next Section\n"
            "Consult docs/contracts/_joins.yaml for join keys.\n"
        )
        _write_repo(tmp_path, planning_text=planning_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("does not carry tier wording" in f for f in failed)


class TestUnresolvedMapRowRedPath:
    def test_unresolved_anchor_key_fails(self, tmp_path: Path) -> None:
        relocation_map = [
            {
                "stub_heading": "## Widget Assessment (Workflow Step 4)",
                "surface": "planning",
                "destination": f"{_WIDGET_REL_PATH}#does_not_exist",
                "enforcing_check": "validate_skill_prose_relocation",
                "tier": "mandatory",
            },
        ]
        _write_repo(tmp_path, relocation_map=relocation_map)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("does not resolve in" in f for f in failed)

    def test_missing_stub_heading_fails(self, tmp_path: Path) -> None:
        planning_text = "# Planning\n\nNo such heading here at all.\n"
        _write_repo(tmp_path, planning_text=planning_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("not found in" in f for f in failed)


class TestAgentSurfaceAnchorRedPath:
    def test_joins_yaml_missing_from_planning_fails(self, tmp_path: Path) -> None:
        planning_text = (
            "# Planning\n\n"
            "## Widget Assessment (Workflow Step 4)\n"
            f"{_PLANNING_STUB}\n"
            "## Next Section\n"
            "No join-key pointer here.\n"
        )
        _write_repo(tmp_path, planning_text=planning_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("_joins.yaml" in f for f in failed)

    def test_candidate_decision_ratification_missing_from_implement_fails(self, tmp_path: Path) -> None:
        implement_text = (
            "# Implement\n\n"
            "## Gadget Bookkeeping (Workflow Step 6)\n"
            f"{_IMPLEMENT_STUB}\n"
            "## Next Section\n"
            "No ratification pointer here.\n"
        )
        _write_repo(tmp_path, implement_text=implement_text)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("candidate-decision-ratification.yaml" in f for f in failed)


class TestShapeEdgeCases:
    def test_missing_instruction_architecture_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, write_ia=False)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any(_IA_REL_PATH in f for f in failed)

    def test_malformed_instruction_architecture_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        _write(tmp_path / _IA_REL_PATH, "key: [unterminated\n")

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("could not parse" in f for f in failed)

    def test_missing_tier_item_lifecycle_contract_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, write_tier_item_lifecycle=False)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("tier-item-lifecycle.yaml" in f and "not found" in f for f in failed)

    def test_non_mapping_row_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, relocation_map=["not-a-mapping"])  # type: ignore[list-item]

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("map row is not a mapping" in f for f in failed)

    def test_malformed_destination_yaml_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        _write(tmp_path / _WIDGET_REL_PATH, "key: [unterminated\n")

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("could not parse destination" in f for f in failed)

    def test_missing_relocation_map_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, relocation_map=None)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("no layer4_relocation_map" in f for f in failed)

    def test_missing_destination_file_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, write_widget_contract=False)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("does not exist" in f for f in failed)

    def test_missing_surface_file_fails(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, planning_text=None)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("surface" in f and "not found" in f for f in failed)

    def test_map_row_missing_field_fails(self, tmp_path: Path) -> None:
        relocation_map = [
            {
                "stub_heading": "## Widget Assessment (Workflow Step 4)",
                "surface": "planning",
                "destination": f"{_WIDGET_REL_PATH}#widget_walk",
                # enforcing_check and tier omitted.
            },
        ]
        _write_repo(tmp_path, relocation_map=relocation_map)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("missing field" in f for f in failed)

    def test_unanchored_destination_fails(self, tmp_path: Path) -> None:
        relocation_map = [
            {
                "stub_heading": "## Widget Assessment (Workflow Step 4)",
                "surface": "planning",
                "destination": _WIDGET_REL_PATH,  # no '#anchor'
                "enforcing_check": "validate_skill_prose_relocation",
                "tier": "mandatory",
            },
        ]
        _write_repo(tmp_path, relocation_map=relocation_map)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("unanchored" in f for f in failed)

    def test_invalid_tier_fails(self, tmp_path: Path) -> None:
        relocation_map = [
            {
                "stub_heading": "## Widget Assessment (Workflow Step 4)",
                "surface": "planning",
                "destination": f"{_WIDGET_REL_PATH}#widget_walk",
                "enforcing_check": "validate_skill_prose_relocation",
                "tier": "sometimes",
            },
        ]
        _write_repo(tmp_path, relocation_map=relocation_map)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("invalid tier" in f for f in failed)

    def test_wrong_enforcing_check_fails(self, tmp_path: Path) -> None:
        relocation_map = [
            {
                "stub_heading": "## Widget Assessment (Workflow Step 4)",
                "surface": "planning",
                "destination": f"{_WIDGET_REL_PATH}#widget_walk",
                "enforcing_check": "validate_something_else",
                "tier": "mandatory",
            },
        ]
        _write_repo(tmp_path, relocation_map=relocation_map)

        failed: list[str] = []
        validate_skill_prose_relocation(failed, repo_root=tmp_path)

        assert any("wrong check" in f for f in failed)
