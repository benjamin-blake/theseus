"""Warehouse-as-source-of-truth write-source whitelist enforcement (Decision 104)."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_warehouse_write_sources", owner="platform")
def validate_warehouse_write_sources(failed: list[str]) -> None:
    """Enforce the warehouse-as-source-of-truth invariant.

    Every write into an ops_* table must originate from a whitelisted file. The whitelist
    captures the two legitimate write paths (Decision 84 I-1/I-4):
    1. Portal calls (file_rec/update_rec/file_decision/update_decision) through the
       DuckLake writer transport.
    2. Canonical ETL from a non-warehouse source of truth (DECISIONS.md -> ops_decisions).

    Any new file that writes to an ops_* table must be reviewed against the
    warehouse-as-source invariant in AGENTS.md before being added to the whitelist.
    Replaying a read cache (e.g. logs/.recommendations-log.jsonl) into the warehouse is the
    resurrection anti-pattern: the cache is downstream of the warehouse, so re-staging it
    re-inserts rows a closure already retired and the SCD2 current projection then surfaces
    the resurrected row as current.
    """
    print("\n=== Warehouse write-source whitelist ===")
    scripts_dir = _common.ROOT / "scripts"
    src_dir = _common.ROOT / "src"
    _self_path = Path(__file__)

    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "session" / "postflight.py",
        scripts_dir / "sync" / "ops.py",
        _self_path,  # this module's own docstring demonstrates the write call and matches the rule
    }

    _PATTERNS = [
        re.compile(r'\b(?:writer|ops|_writer)\.write\(\s*["\']ops_'),
    ]

    # Table-specific block: the DuckLake ops tables must NEVER be written by anything but the
    # portal's writer transport (Decision 84 I-1) -- readers serve DuckLake, so any other sink
    # is a silent split-brain. Catches any site, including whitelisted files.
    # Self-excluded: this module's docstring demonstrates the write call and would otherwise self-flag.
    _MIGRATED = r"ops_(?:recommendations|decisions|priority_queue|execution_plans)"
    _MIGRATED_BLOCK_PATTERNS = [
        re.compile(r'\b(?:writer|ops|_writer)\.write\(\s*["\']' + _MIGRATED),
        re.compile(r'\b(?:writer|ops|_writer)\.compact\(\s*["\']' + _MIGRATED),
    ]

    errors: list[str] = []
    file_count = 0
    for search_dir in [scripts_dir, src_dir]:
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            file_count += 1
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue

            # Table-specific block (applies to ALL files, including the whitelist).
            if py_file != _self_path:
                for recs_pat in _MIGRATED_BLOCK_PATTERNS:
                    if recs_pat.search(content):
                        rel = py_file.relative_to(_common.ROOT)
                        errors.append(
                            f"{rel}: writes/compacts a DuckLake ops table outside the portal -- "
                            "recs/decisions/priority_queue/execution_plans transit the closed boundary "
                            "(Decision 84 I-1). Use the ops_data_portal surface."
                        )
                        break

            if py_file in _WHITELIST:
                continue
            for pattern in _PATTERNS:
                if pattern.search(content):
                    rel = py_file.relative_to(_common.ROOT)
                    errors.append(
                        f"{rel}: writes to ops_* table but not on warehouse-write whitelist. "
                        f"See validate_warehouse_write_sources docstring."
                    )
                    break

    registry.examined(file_count, unit="files")
    if errors:
        print("Warehouse write-source violations:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("All ops_* writes originate from whitelisted files.")
