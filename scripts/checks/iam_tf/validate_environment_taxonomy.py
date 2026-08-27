from __future__ import annotations

import re

from scripts.checks import _common, registry


@registry.register("validate_environment_taxonomy", owner="platform")
def validate_environment_taxonomy(failed: list[str]) -> None:
    """Enforce the environment vocabulary reservation (docs/contracts/environment-taxonomy.yaml).

    On changed docs, flag a PLATFORM environment tier (sandbox/SIT/PROD) written as a "phase" --
    platform tiers are environments, and "phase" is not a platform-axis word. Compound tokens
    (production_ensemble) are safe via word boundaries. The canonical contract, decisions and the
    roadmap are allowlisted -- they define the vocabulary; workflow and test files are skipped.
    """
    print("\n=== Environment/phase taxonomy lint ===")
    allowlist_files = {
        "docs/contracts/environment-taxonomy.yaml",
        "docs/DECISIONS.md",
        "docs/ROADMAP-PLATFORM.yaml",
    }
    platform_tiers = ("sandbox", "sit", "prod", "production", "staging")
    tier_as_phase = re.compile(r"\b(" + "|".join(platform_tiers) + r")[ \t]+phase\b", re.IGNORECASE)
    errors: list[str] = []
    candidates: list[str] = []
    for rel in _common.get_changed_files():
        if not rel.endswith((".md", ".yaml", ".yml")):
            continue
        if rel in allowlist_files or rel.startswith(".github/") or rel.startswith("tests/"):
            continue
        try:
            text = (_common.ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        candidates.append(rel)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if tier_as_phase.search(line):
                errors.append(f"{rel}:{lineno}: platform tier used as a 'phase' (platform tiers are environments)")
    registry.examined(len(candidates), unit="candidate_docs")
    if errors:
        print("Environment/phase taxonomy violations (see docs/contracts/environment-taxonomy.yaml):")
        for e in errors:
            print(f"  - {e}")
        failed.append("Environment/phase taxonomy")
    else:
        print("No environment/phase taxonomy violations in changed docs.")
