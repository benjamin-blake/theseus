"""Verification registry schema validation (T3.1, Decision 104; re-grained to
config/agent/verification_registry/entries/<check_id>.yaml shards, Decision 176).

Reads exclusively through scripts.verification_graduation's loader (load_entries/entries_at_ref)
-- never a hand-rolled path join to the pre-migration flat file, which is now a rejected shape
(see the flat-file-resurrection leg below).
"""

from __future__ import annotations

from scripts import verification_graduation
from scripts.checks import _common, registry


def _added_entries(current_entries: list[dict]) -> list[dict]:
    """Entries present now but absent from origin/main, matched by check_id (VF-06 c2).

    Returns [] when origin/main does not resolve (advisory -- the caller's own reachability
    check is what decides whether to skip the whole differential leg, not this helper)."""
    baseline = verification_graduation.entries_at_ref("origin/main", repo_root=_common.ROOT)
    if baseline is None:
        return []
    baseline_ids = {e.get("check_id") for e in baseline if isinstance(e, dict)}
    return [e for e in current_entries if isinstance(e, dict) and e.get("check_id") not in baseline_ids]


def _modified_entries(current_entries: list[dict]) -> list[dict]:
    """Entries present in BOTH current and origin/main (same check_id) whose parsed record
    mapping differs from the baseline -- closes the silent-modification hole: a record whose
    check_spec is edited in place, without a new check_id, was previously invisible to the
    differential gate (a neutered check could pass unnoticed).

    Compares PARSED MAPPINGS, never bytes or text: the sharding migration itself re-renders
    every record at width=200, so a byte/text-based detector would select all 476 records instead
    of only the ones whose content genuinely changed. Returns [] when origin/main does not
    resolve (mirrors _added_entries)."""
    baseline = verification_graduation.entries_at_ref("origin/main", repo_root=_common.ROOT)
    if baseline is None:
        return []
    baseline_by_id = {e.get("check_id"): e for e in baseline if isinstance(e, dict)}
    modified: list[dict] = []
    for entry in current_entries:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("check_id")
        if cid in baseline_by_id and baseline_by_id[cid] != entry:
            modified.append(entry)
    return modified


def _run_added_entry_differentials(candidates: list[dict], failed: list[str]) -> None:
    """VF-06 c2 (added) + the modified-record close (c2'): for each added-or-modified entry in
    this diff, run the REAL differential admission gate.

    Materializes each entry's check_spec and asserts it FAILS on origin/main (real git worktree
    revert) and PASSES on HEAD/live. Refuses tautological/non-admitted outcomes and any
    materialize/worktree/revert error with a clear failure message (Decision 55 fail-loud) --
    never a silent pass.
    """
    plural = "y" if len(candidates) == 1 else "ies"
    print(f"  Differential admission gate: {len(candidates)} added-or-modified entr{plural} in this diff.")

    for row in candidates:
        cid = row.get("check_id", "?")
        try:
            outcome = verification_graduation.run_differential(row, repo_root=_common.ROOT)
        except verification_graduation.GraduationError as exc:
            failed.append(f"verification-registry differential: check_id={cid}: error -- {exc}")
            continue
        if outcome.skipped:
            print(f"    skipped (non-fatal): {cid} ({outcome.reason})")
        elif not outcome.admitted:
            failed.append(f"verification-registry differential: check_id={cid}: not admitted -- {outcome.reason}")
        else:
            print(f"    admitted: {cid} ({outcome.reason})")


def _schema_errors(entries: list, canonical_slots: frozenset[str]) -> list[str]:
    """Per-entry schema checks: required fields, known primitive_slot, unique check_id."""
    required_fields = {"check_id", "primitive_slot", "guard_target", "plan_slug", "graduated_at"}
    seen_ids: set[str] = set()
    errors: list[str] = []
    for entry in entries:
        cid_hint = entry.get("check_id", "?") if isinstance(entry, dict) else "?"
        if not isinstance(entry, dict):
            errors.append(f"  {cid_hint}: not a mapping")
            continue
        missing = required_fields - entry.keys()
        if missing:
            errors.append(f"  {cid_hint}: missing fields: {sorted(missing)}")
        slot = entry.get("primitive_slot")
        if slot is not None and slot not in canonical_slots:
            errors.append(f"  {cid_hint}: unknown primitive_slot {slot!r} (not in CD.29 vocabulary)")
        cid = entry.get("check_id")
        if cid is not None:
            if cid in seen_ids:
                errors.append(f"  duplicate check_id: {cid!r}")
            seen_ids.add(cid)
    return errors


def _placement_errors(shard_files: list, entries_by_path: dict) -> list[str]:
    """Placement leg: a shard's filename must equal its own check_id (Decision 55 -- structural,
    not documented convention). Each message is failure-detail-shaped (naming the file and the
    check_id it disagrees with), not only a generic label -- appended to `failed` directly."""
    errors: list[str] = []
    for path in shard_files:
        data = entries_by_path.get(path)
        cid = data.get("check_id") if isinstance(data, dict) else None
        expected_name = f"{cid}.yaml" if cid else None
        if expected_name != path.name:
            errors.append(f"verification-registry: {path.name}: filename does not equal check_id (check_id={cid!r})")
    return errors


@registry.register("validate_verification_registry", owner="platform")
def validate_verification_registry(failed: list[str]) -> None:
    """Validate config/agent/verification_registry/entries/*.yaml against the CD.29 contract
    (--pre, T3.1).

    Checks:
    1. entries/ directory exists (and the retired flat registry.yaml has NOT resurrected).
    2. Every shard's filename equals its own check_id (placement leg).
    3. Every shard is valid YAML, a mapping, with required fields and a known primitive_slot.
    4. check_id values are unique across the corpus.
    5. VF-06 c2/c2': entries ADDED or MODIFIED in this diff pass the REAL differential admission
       gate (git-worktree revert against origin/main) -- diff-gated no-op when neither happened;
       advisory-skips the whole leg when origin/main is unreachable (Decision 55 -- never an
       empty-baseline misread of every live record as newly added).
    """
    print("\n=== Verification registry (T3.1) ===")
    entries_dir = _common.ROOT / verification_graduation.REGISTRY_ENTRIES_REL

    flat_path = _common.ROOT / verification_graduation.REGISTRY_DIR_REL / verification_graduation.LEGACY_FLAT_BASENAME
    if flat_path.exists():
        failed.append(
            f"verification-registry: {flat_path.relative_to(_common.ROOT)} has resurrected -- "
            "records belong one-per-file under entries/<check_id>.yaml, never a flat monolith"
        )

    if not entries_dir.is_dir():
        failed.append("verification-registry: config/agent/verification_registry/entries/ not found")
        registry.skipped("entries directory missing")
        return

    import yaml  # noqa: PLC0415

    shard_files = sorted(p for p in entries_dir.glob("*.yaml"))
    entries_by_path: dict = {}
    for path in shard_files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failed.append(f"verification-registry: {path.name}: YAML parse error: {exc}")
            continue
        entries_by_path[path] = data

    placement_errors = _placement_errors(shard_files, entries_by_path)
    for e in placement_errors:
        print(f"  {e}")
        failed.append(e)

    entries = list(entries_by_path.values())

    # Lazy-import CANONICAL_SLOTS to avoid a module-level import of scripts.verification_checks.
    root_str = str(_common.ROOT)
    import sys as _sys  # noqa: PLC0415

    injected = root_str not in _sys.path
    if injected:
        _sys.path.insert(0, root_str)
    try:
        from scripts.verification_checks import CANONICAL_SLOTS  # noqa: PLC0415
    finally:
        if injected and root_str in _sys.path:
            _sys.path.remove(root_str)

    errors = _schema_errors(entries, CANONICAL_SLOTS)

    if errors:
        for e in errors:
            print(e)
        failed.append("Verification registry")
        registry.examined(len(entries), unit="graduated_checks")
        return

    print(f"  OK: {len(entries)} graduated checks, all valid.")

    if not _common.origin_main_reachable(_common.ROOT):
        print("  SKIP (differential gate): origin/main unreachable (advisory locally, authoritative in CI).")
        registry.skipped("origin/main unreachable")
        return

    added = _added_entries(entries)
    modified = _modified_entries(entries)
    candidates = added + modified
    if candidates:
        _run_added_entry_differentials(candidates, failed)

    registry.examined(len(entries), unit="graduated_checks")
