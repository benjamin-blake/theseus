"""Marker-gate removal/disable of a workflow's `on:.schedule` trigger (LSA-01 leg c).

Closes the third LSA-01 residue left by PLAN-verifier-weakening-guards (leg a, Decision 187,
PR #1142): that plan gated check-fleet tier demotion, but a scheduled-workflow's OWN trigger --
the population `scripts.convergence_health.sensor_liveness` alarms over -- had no change-control
of its own. Removing, emptying or commenting out a workflow's `on:.schedule` block silently
shrinks the sensor-liveness population with no gate, marker or detector.

Population is DERIVED, never declared (Decision 187 point 1): every `.github/workflows/*.yml` path
present at HEAD (disk glob) or BASE (`git ls-tree` against origin/main) is walked, so a workflow
added or removed mid-diff is covered without a second edit. Keyed on the BARE workflow FILENAME
(never the path) -- a Decision naming `.github/workflows` generically therefore authorizes no
specific workflow's removal, only a marker whose cited Decision body names that exact filename.

Binds to the shared marker-authorization mechanism (scripts/checks/_marker_guard.py) via its
check_state_diff/check_present_markers pair, mirroring validate_tier_demotion_markers's own
per-file-scoped use of that mechanism -- never a copy of it. The governed STATE is a single bool
per workflow file (does its `on:` block declare a non-empty `schedule:` list of cron entries), so
each workflow's `check_state_diff` call sees a one-entry state map keyed by that file's own bare
name. `weakened()` fires only on a True -> False transition (a schedule that existed at base is
gone at head); adding a schedule (False -> True) is always free, matching Decision 187's
tightening-stays-free rule. Deletion of a whole schedule-bearing workflow file has no head line to
carry a marker, so `gates_deletion` fires unconditionally for a base state of True -- mirroring
`check_state_diff`'s own deletion branch, which never consults marker text on that path.

The `on:.schedule` parse is REPLICATED, not imported, from
`scripts.convergence_health.sensor_liveness.peers_from_workflow_docs` -- including its PyYAML
bare-`on:`-parses-as-`True` normalisation (`data.get("on", data.get(True, {}))`) -- for the same
closure reason `validate_pre_glob_closure._glob_match` replicates `scripts/validate.py::
_pre_glob_match` rather than importing it: `sensor_liveness` pulls in a ~56-module subtree this
--pre-gated check must not inherit into its own coverage obligation. The two derivations are
pinned equal on the live tree by this module's own mirror test (test_validate_schedule_removal_
markers.py::TestTighteningFree), the same replicate-and-pin shape the closure auditor already
uses.

A COMMENTED-OUT `schedule:` block needs no separate detection branch: PyYAML strips comments
during parse, so a commented-out block and a structurally-removed one both read as "no schedule"
to `_schedule_present` -- one function covers both known-bad shapes the plan enumerates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import yaml

from scripts.checks import _common, _marker_guard, registry

TOKEN = "schedule-removal-approved"

_WORKFLOWS_DIR_REL = ".github/workflows"
_WORKFLOW_GLOB = "*.yml"
_MARKER_RE = re.compile(rf"#\s*{re.escape(TOKEN)}:\s*dec-(\d+)\s*(.*)$")


def _schedule_present(data: object) -> bool:
    """Replica of sensor_liveness.peers_from_workflow_docs' own on:.schedule parse, including its
    bare-`on:`-as-`True` PyYAML normalisation. True iff `data` declares a non-empty `schedule:`
    list carrying at least one dict entry with a `cron` key."""
    if not isinstance(data, dict):
        return False
    on_block = data.get("on", data.get(True, {}))
    schedule = on_block.get("schedule") if isinstance(on_block, dict) else None
    if not isinstance(schedule, list):
        return False
    return any(isinstance(entry, dict) and entry.get("cron") for entry in schedule)


def _extract_marker(text: str) -> tuple[str | None, str | None]:
    """The `# schedule-removal-approved: dec-NNN <reason>` marker, scanned anywhere in the file --
    there is no AST call node to anchor a line span to (unlike validate_tier_demotion_markers'
    `Entry(...)` calls), since this registry's single governed key is the WHOLE FILE. A marker with
    no reason text parses as no marker at all (this token's reason_required: true)."""
    for line in text.splitlines():
        match = _MARKER_RE.search(line)
        if match:
            reason = match.group(2).strip()
            if reason:
                return f"dec-{match.group(1)}", reason
    return None, None


def _state_extractor_for(filename: str) -> Callable[[str], dict[str, _marker_guard.StateEntry]]:
    """spec.state_extractor for one workflow file's RegistrySpec -- always resolves to exactly one
    key (`filename`), since a workflow's schedule presence is a whole-file property."""

    def _extract(text: str) -> dict[str, _marker_guard.StateEntry]:
        try:
            data = yaml.safe_load(text) if text else None
        except yaml.YAMLError:
            data = None
        marker, reason = _extract_marker(text)
        return {filename: _marker_guard.StateEntry(state=_schedule_present(data), marker=marker, reason=reason)}

    return _extract


def _marker_entries_view_for(filename: str) -> Callable[[str], dict[str, _marker_guard.MarkerEntry]]:
    """spec.extractor -- the check_present_markers-facing projection of the state extractor above,
    mirroring validate_tier_demotion_markers._marker_entries_view. `value` is a dummy float:
    check_present_markers never reads it."""

    def _view(text: str) -> dict[str, _marker_guard.MarkerEntry]:
        return {
            key: _marker_guard.MarkerEntry(0.0, entry.marker, entry.reason)
            for key, entry in _state_extractor_for(filename)(text).items()
        }

    return _view


def weakened(base: object, head: object) -> bool:
    """True iff a schedule present at base is gone at head. Adding a schedule (False -> True) or
    no change is always free -- Decision 187's tightening-stays-free rule."""
    if not (isinstance(base, bool) and isinstance(head, bool)):
        raise TypeError(f"weakened() expects bool state, got {type(base)!r}/{type(head)!r}")
    return base and not head


def gates_deletion(base: object) -> bool:
    """True iff the deleted workflow file carried a schedule at base -- there is no head line to
    carry a marker, so a schedule-bearing workflow's outright deletion is gated unconditionally."""
    if not isinstance(base, bool):
        raise TypeError(f"gates_deletion() expects bool state, got {type(base)!r}")
    return base


def _head_workflow_paths(root: Path) -> list[str]:
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in workflows_dir.glob(_WORKFLOW_GLOB))


def _base_workflow_paths(root: Path) -> list[str]:
    result = _common.run(
        ["git", "ls-tree", "-r", "--name-only", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=root,
    )
    if result.returncode != 0:
        return []
    prefix = f"{_WORKFLOWS_DIR_REL}/"
    return sorted(
        {
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip().startswith(prefix) and line.strip().endswith(".yml")
        }
    )


def _batched_base_reader(root: Path, rel_paths: list[str]) -> Callable[[str], str] | None:
    """ONE `git cat-file --batch` call fetching every `rel_paths` entry's origin/main blob (or ""
    when the path is absent at that ref -- a brand-new workflow, not an unreachable base). Mirrors
    validate_tier_demotion_markers._batched_base_reader byte-for-byte in shape (the same batching
    and missing-path rationale applies to this registry's per-file grain), replicated rather than
    imported to keep this module's own closure independent of the verification domain's.

    Returns None -- never a reader -- when the subprocess itself fails, which the caller turns into
    a loud SKIP (Decision 55: a missing oracle must not look like a satisfied one)."""
    if not rel_paths:
        return lambda _rel_path: ""
    stdin_payload = "".join(f"origin/main:{p}\n" for p in rel_paths).encode("utf-8")
    result = _common.run(["git", "cat-file", "--batch"], input=stdin_payload, capture_output=True, cwd=root)
    if result.returncode != 0:
        return None
    output = result.stdout if isinstance(result.stdout, bytes) else b""
    contents: dict[str, str] = {}
    pos = 0
    for rel_path in rel_paths:
        newline = output.find(b"\n", pos)
        if newline == -1:
            contents[rel_path] = ""
            continue
        header = output[pos:newline].decode("utf-8", errors="replace")
        pos = newline + 1
        parts = header.split()
        if len(parts) == 3 and parts[1] == "blob":
            size = int(parts[2])
            contents[rel_path] = output[pos : pos + size].decode("utf-8", errors="replace")
            pos += size + 1
        else:
            contents[rel_path] = ""
    return lambda rel_path: contents.get(rel_path, "")


@registry.register("validate_schedule_removal_markers", owner="platform")
def validate_schedule_removal_markers(failed: list[str], root: Path | None = None) -> None:
    """Fail on an unauthorized schedule removal/disable, or the deletion of a still-scheduled
    workflow file. See module docstring."""
    print("\n=== Schedule-removal marker gate (LSA-01 leg c) ===")
    target_root = root if root is not None else _common.ROOT

    if not _common.origin_main_reachable(target_root):
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI).")
        registry.skipped("origin/main unreachable")
        return

    all_paths = sorted(set(_head_workflow_paths(target_root)) | set(_base_workflow_paths(target_root)))
    base_reader = _batched_base_reader(target_root, all_paths)
    if base_reader is None:
        print("  SKIP: `git cat-file --batch` failed -- no base blob was read (advisory locally, authoritative in CI).")
        registry.skipped("git cat-file --batch failed")
        return

    violations: list[str] = []
    examined_count = 0

    for rel_path in all_paths:
        filename = Path(rel_path).name
        examined_count += 1
        spec = _marker_guard.RegistrySpec(
            rel_path=rel_path,
            token=TOKEN,
            gated_direction="down",
            extractor=_marker_entries_view_for(filename),
            gates_new_entry=lambda _value: False,
            label="Schedule-removal marker gate (LSA-01 leg c)",
            reason_required=True,
            state_extractor=_state_extractor_for(filename),
            weakened=weakened,
            gates_deletion=gates_deletion,
        )
        violations.extend(_marker_guard.check_state_diff(spec, base_reader=base_reader))
        violations.extend(_marker_guard.check_present_markers(spec))

    if violations:
        print("Schedule-removal violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Schedule-removal marker gate")
    else:
        print(f"  PASS: {examined_count} workflow(s) clean.")

    registry.examined(examined_count, unit="workflows")
