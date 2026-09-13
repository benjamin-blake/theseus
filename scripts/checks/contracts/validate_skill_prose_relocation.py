"""Skills-layer prose relocation guard (PLAN-skills-layer-prose-relocation, T2.56 c1's
skills-layer conjunct).

Driven by docs/contracts/instruction-architecture.yaml's `layer4_relocation_map` (never a
duplicated, hardcoded sentence list): for every declared row, the named stub heading must still
exist in its surface SKILL.md, the stub's body must carry the destination's anchored pointer and
its declared tier wording, and the stub must NOT carry back one of the known giveaway phrases that
only appear in the ORIGINAL (pre-relocation) body -- the signal a relocated sentence was re-inlined
rather than genuinely moved. Also asserts the two agent_surface evaluator anchors
(_joins.yaml in planning, candidate-decision-ratification.yaml in implement) still resolve, and
that every map row's destination anchor resolves to a real key in its destination contract.

Replaces the weaker agent_surface-only evaluator the decision-scout gate flagged under
Decision 181 -- this module both NAMES docs/contracts/instruction-architecture.yaml (to read the
map) and docs/contracts/tier-item-lifecycle.yaml (so THAT contract's own {check: ...} evaluator
resolves under scripts/checks/contracts/_population.py::resolve_evaluator, which requires an
executable-context literal, not merely a map value) as module-level literals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts.checks import _common, registry

_INSTRUCTION_ARCHITECTURE_REL_PATH = "docs/contracts/instruction-architecture.yaml"
_TIER_ITEM_LIFECYCLE_REL_PATH = "docs/contracts/tier-item-lifecycle.yaml"

_SURFACE_PATHS: dict[str, str] = {
    "planning": ".claude/skills/planning/SKILL.md",
    "implement": ".claude/skills/implement/SKILL.md",
}

# One giveaway phrase (or more) per relocated stub_heading -- each phrase is drawn verbatim from
# the content that MOVED to a destination contract, never from the short stub text itself. Its
# presence inside a stub's slice means the original body was pasted back rather than relocated.
_REINLINE_MARKERS: dict[str, tuple[str, ...]] = {
    "## Follow-on /plan mode (in_progress items with open criteria)": ("most items take N follow-on plans",),
    "## Tier Item Freshness Gate (Workflow Step 3, fires once intent resolves to tier_items)": (
        "Run four checks, cheapest first",
    ),
    "## Recommendation Relevance Gate (Workflow Step 3, fires before bundling any rec)": (
        "Never call `_make_reader()` inside this gate",
        "Never call _make_reader() inside this gate",
    ),
    "## Data-Model Assessment (Workflow Step 4)": ("Fable escalation: for load-bearing/novel calls only",),
    "## Main Divergence Assessment (Workflow Step 4)": (
        "Planning against the stale branch view risks decisions that conflict",
    ),
    "## Candidate Decision Ratification (Workflow Step 5b, when the plan realizes/ratifies a CD)": (
        "Wave bundling: when >=2 same-session PURE gate-clear CDs realize together",
    ),
    "## Tier_item bookkeeping (post-verification, pre-merge)": (
        "under-counting (false in_progress) rather than over-counting",
        'entry.strip().split()[0] == "PLAN-{slug}"',
    ),
    "## CD Ratification Bookkeeping (Workflow Step 6 -- CONDITIONAL, fires when the plan has a ratification block)": (
        "Re-present the drafted Decision text verbatim and wait for an explicit go-ahead",
    ),
}

# The two agent_surface evaluator anchors a surviving stub must keep resolvable (Decision 181):
# docs/contracts/_joins.yaml names planning/SKILL.md as its evaluator, and
# docs/contracts/candidate-decision-ratification.yaml names implement/SKILL.md.
_AGENT_SURFACE_BASENAMES: dict[str, str] = {
    "planning": "_joins.yaml",
    "implement": "candidate-decision-ratification.yaml",
}

_REQUIRED_MAP_FIELDS = ("stub_heading", "surface", "destination", "enforcing_check", "tier")
_VALID_TIERS = ("mandatory", "conditional")
_EXPECTED_CHECK_NAME = "validate_skill_prose_relocation"


def _slice_section(text: str, heading: str) -> str | None:
    start = text.find(heading)
    if start == -1:
        return None
    next_heading = text.find("\n## ", start + len(heading))
    return text[start:] if next_heading == -1 else text[start:next_heading]


def _resolve_anchor(doc: Any, keys: list[str]) -> Any:
    if not keys:
        return doc
    if not isinstance(doc, dict) or keys[0] not in doc:
        return None
    return _resolve_anchor(doc[keys[0]], keys[1:])


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _validate_row(
    row: Any,
    *,
    surface_texts: dict[str, str],
    slice_cache: dict[tuple[str, str], str | None],
    root: Path,
    failed: list[str],
) -> bool:
    """Validate one layer4_relocation_map row; append to `failed` for every violation found.
    Returns True iff the row was well-shaped enough to count as examined."""
    if not isinstance(row, dict):
        failed.append(f"skill-prose-relocation: map row is not a mapping: {row!r}")
        return False
    missing_fields = [f for f in _REQUIRED_MAP_FIELDS if f not in row]
    if missing_fields:
        failed.append(f"skill-prose-relocation: map row {row!r} missing field(s) {missing_fields}")
        return False

    stub_heading = str(row["stub_heading"])
    surface = str(row["surface"])
    destination = str(row["destination"])
    enforcing_check = str(row["enforcing_check"])
    tier = str(row["tier"])

    if enforcing_check != _EXPECTED_CHECK_NAME:
        failed.append(f"skill-prose-relocation: row {stub_heading!r} names wrong check {enforcing_check!r}")
    if tier not in _VALID_TIERS:
        failed.append(f"skill-prose-relocation: row {stub_heading!r} has invalid tier {tier!r}")
    if "#" not in destination:
        failed.append(f"skill-prose-relocation: row {stub_heading!r} destination {destination!r} is unanchored")
        return True
    if surface not in surface_texts:
        failed.append(f"skill-prose-relocation: row {stub_heading!r} names unknown/unreadable surface {surface!r}")
        return True

    section = _section_for(surface, stub_heading, surface_texts=surface_texts, slice_cache=slice_cache)
    if section is None:
        failed.append(f"skill-prose-relocation: stub heading {stub_heading!r} not found in {_SURFACE_PATHS[surface]}")
        return True

    dest_file, dest_anchor = destination.split("#", 1)
    _check_stub_body(section, stub_heading, surface, dest_file, tier, failed)
    _check_destination_resolves(root, dest_file, dest_anchor, stub_heading, failed)
    return True


def _section_for(
    surface: str,
    stub_heading: str,
    *,
    surface_texts: dict[str, str],
    slice_cache: dict[tuple[str, str], str | None],
) -> str | None:
    cache_key = (surface, stub_heading)
    if cache_key not in slice_cache:
        slice_cache[cache_key] = _slice_section(surface_texts[surface], stub_heading)
    return slice_cache[cache_key]


def _check_stub_body(section: str, stub_heading: str, surface: str, dest_file: str, tier: str, failed: list[str]) -> None:
    dest_basename = Path(dest_file).name
    if dest_basename not in section:
        failed.append(
            f"skill-prose-relocation: stub {stub_heading!r} in {surface} does not name its anchored pointer {dest_basename!r}"
        )
    if tier not in section.lower():
        failed.append(f"skill-prose-relocation: stub {stub_heading!r} in {surface} does not carry tier wording {tier!r}")
    for marker in _REINLINE_MARKERS.get(stub_heading, ()):
        if marker in section:
            failed.append(
                f"skill-prose-relocation: stub {stub_heading!r} in {surface} re-inlines relocated content (found {marker!r})"
            )


def _check_destination_resolves(root: Path, dest_file: str, dest_anchor: str, stub_heading: str, failed: list[str]) -> None:
    dest_path = root / dest_file
    if not dest_path.is_file():
        failed.append(f"skill-prose-relocation: row {stub_heading!r} destination file {dest_file!r} does not exist")
        return
    dest_data = _load_yaml(dest_path)
    if dest_data is None:
        failed.append(f"skill-prose-relocation: could not parse destination {dest_file!r}")
        return
    resolved = _resolve_anchor(dest_data, dest_anchor.split("."))
    if resolved is None:
        failed.append(
            f"skill-prose-relocation: row {stub_heading!r} destination anchor {dest_anchor!r} "
            f"does not resolve in {dest_file!r}"
        )


def _check_agent_surface_anchors(surface_texts: dict[str, str], failed: list[str]) -> int:
    examined = 0
    for surface, basename in _AGENT_SURFACE_BASENAMES.items():
        text = surface_texts.get(surface)
        if text is None:
            continue
        if basename not in text:
            failed.append(f"skill-prose-relocation: {surface} no longer names agent_surface anchor basename {basename!r}")
        else:
            examined += 1
    return examined


def _load_surface_texts(root: Path, failed: list[str]) -> dict[str, str]:
    surface_texts: dict[str, str] = {}
    for surface, rel_path in _SURFACE_PATHS.items():
        p = root / rel_path
        if not p.is_file():
            failed.append(f"skill-prose-relocation: surface {rel_path} not found")
            continue
        surface_texts[surface] = p.read_text(encoding="utf-8")
    return surface_texts


@registry.register("validate_skill_prose_relocation", owner="platform")
def validate_skill_prose_relocation(failed: list[str], *, repo_root: Path | None = None) -> None:
    """Fail on a missing/malformed layer4_relocation_map row, a stub that lost its heading,
    anchored pointer, or tier wording, a re-inlined relocated sentence, a missing agent_surface
    basename, or a destination anchor that does not resolve."""
    print("\n=== Skills-layer prose relocation guard ===")
    root = repo_root if repo_root is not None else _common.ROOT

    ia_data = _load_yaml(root / _INSTRUCTION_ARCHITECTURE_REL_PATH)
    if ia_data is None:
        failed.append(f"skill-prose-relocation: could not parse {_INSTRUCTION_ARCHITECTURE_REL_PATH}")
        registry.skipped(f"{_INSTRUCTION_ARCHITECTURE_REL_PATH} missing or malformed")
        return

    rows = ia_data.get("layer4_relocation_map")
    if not isinstance(rows, list) or not rows:
        failed.append(f"skill-prose-relocation: {_INSTRUCTION_ARCHITECTURE_REL_PATH} carries no layer4_relocation_map")
        registry.skipped("layer4_relocation_map absent or empty")
        return

    if not (root / _TIER_ITEM_LIFECYCLE_REL_PATH).is_file():
        failed.append(f"skill-prose-relocation: {_TIER_ITEM_LIFECYCLE_REL_PATH} not found")

    surface_texts = _load_surface_texts(root, failed)
    slice_cache: dict[tuple[str, str], str | None] = {}

    examined_count = sum(
        1 for row in rows if _validate_row(row, surface_texts=surface_texts, slice_cache=slice_cache, root=root, failed=failed)
    )
    examined_count += _check_agent_surface_anchors(surface_texts, failed)

    registry.examined(examined_count, unit="relocation map rows + agent_surface anchors")
    print(f"  Examined {examined_count} relocation-map/anchor item(s).")
