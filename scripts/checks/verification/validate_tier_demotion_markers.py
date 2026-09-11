"""Verifier-weakening control for check-fleet tier membership (Decision 187, LSA-01 leg a).

Protects a manifest Entry's tier membership -- `pre`, `full_segment`, `pre_globs` -- against a
silent demotion: losing `pre`, losing `full_segment`, or narrowing `pre_globs` below its prior
coverage. The protected set is DERIVED from the git base ref every run, never a committed roster:
the manifest path set is the union of head-disk (`scripts/checks/*/_manifest.py`) and base
(`git ls-tree` against origin/main), so a check added tomorrow is protected the moment it merges
and a whole domain manifest deleted mid-diff cannot hide its entries. Base text for all domains
arrives through ONE batched `git cat-file --batch` closure, so the subprocess count this check
pays is independent of the domain count.

Binds to the shared marker-authorization mechanism (scripts/checks/_marker_guard.py, Decision
165 point 1's consolidation) via its check_state_diff/check_present_markers sibling pair, never a
copy of it. `TierState` carries the strength relation; `weakened`/`gates_deletion` are this gate's
own implementations of the two generic hooks RegistrySpec declares. Authorization is CHECK-NAME
level: every key this gate hands to the shared mechanism is a bare check name (no "/"), so
`_expand_ancestor_candidates` yields only the name itself -- a Decision naming `scripts/checks`
generically can never authorize a specific check's demotion.

Deletion has no marker escape by construction: a removed entry has no head line to carry one, and
check_state_diff's deletion branch never consults any marker text. Retirement is mark-then-drop
across two PRs (demote-with-marker, merge, then delete the now-unsequenced entry for free).

Runs UNGATED in --pre (pre_globs=None) by design: the fixed-point raise in
scripts/checks/registry.py refuses a glob-gated Entry for this check specifically, because a gated
gate is one narrow-the-globs edit away from not running on the diff that demotes it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

from scripts.checks import _common, _marker_guard, registry

# The marker token this gate binds to (docs/contracts/marker-grammar.yaml). A plain module-level
# string constant, never a check-name roster -- and the ONE thing scanned for at derivation time
# by tests/checks/registry/test_sequences.py::TestWeakeningGateFixedPoint's carrier-constant pin
# (which module owns a constant equal to this token's value), so registry._WEAKENING_GATE's value
# is proven by derivation rather than compared to a literal.
TOKEN = "tier-demotion-approved"

_MANIFEST_GLOB = "*/_manifest.py"
_MANIFEST_PATH_RE = re.compile(r"^scripts/checks/[^/]+/_manifest\.py$")
_MARKER_RE = re.compile(rf"#\s*{re.escape(TOKEN)}:\s*dec-(\d+)\s*(.*)$")


@dataclass(frozen=True)
class TierState:
    """The strength relation this gate's `weakened`/`gates_deletion` hooks compare: `pre` and
    `full_segment` are DIRECTION-GATED transitions (a legitimate weaker state exists -- 12 live
    entries are deliberately full-only), and `pre_globs` is a coverage set rather than a scalar."""

    pre: bool
    full_segment: str | None
    pre_globs: tuple[str, ...] | None


def _bool_literal(node: ast.expr | None, *, default: bool) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return default


def _str_or_none_literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, str)):
        return node.value
    return None


def _str_tuple_or_none_literal(node: ast.expr | None) -> tuple[str, ...] | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    if isinstance(node, ast.Tuple):
        return tuple(elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str))
    return None


def _marker_on_span(lines: list[str], start: int, end: int) -> tuple[str | None, str | None]:
    """Scan an AST call's own line span [start, end] (1-indexed, inclusive) for a `# {TOKEN}:
    dec-NNN <reason>` marker -- the entry-line-span placement rule (mirrors
    validate_root_scoped_diff_base.py's `_call_has_waiver` lineno..end_lineno idiom). A marker
    with no reason text parses as no marker at all (this token's declared reason_required: true),
    matching _marker_guard's own require_reason semantics without importing its private helper."""
    for lineno in range(start, end + 1):
        if not (1 <= lineno <= len(lines)):
            continue
        match = _MARKER_RE.search(lines[lineno - 1])
        if not match:
            continue
        reason = match.group(2).strip()
        if not reason:
            continue
        return f"dec-{match.group(1)}", reason
    return None, None


def extract_tier_states(text: str) -> dict[str, _marker_guard.StateEntry]:
    """spec.state_extractor: one StateEntry per `Entry(...)` call found anywhere in `text` (a
    domain _manifest.py's content), keyed by its own `name=` literal. Never raises on malformed
    input -- an unparseable file, or an Entry call whose `name=` is not a bare string literal,
    contributes no entries rather than crashing the gate."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    lines = text.splitlines()
    entries: dict[str, _marker_guard.StateEntry] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Entry"):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        name = _str_or_none_literal(kwargs.get("name"))
        if not name:
            continue
        state = TierState(
            pre=_bool_literal(kwargs.get("pre"), default=False),
            full_segment=_str_or_none_literal(kwargs.get("full_segment")),
            pre_globs=_str_tuple_or_none_literal(kwargs.get("pre_globs")),
        )
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        marker, reason = _marker_on_span(lines, node.lineno, end)
        entries[name] = _marker_guard.StateEntry(state=state, marker=marker, reason=reason)
    return entries


def _marker_entries_view(text: str) -> dict[str, _marker_guard.MarkerEntry]:
    """spec.extractor -- the check_present_markers-facing projection of extract_tier_states, so
    the retroactive scan (which reads spec.extractor, never spec.state_extractor) sees the same
    marker/reason pairs. `value` is a dummy float: check_present_markers never reads it."""
    return {
        key: _marker_guard.MarkerEntry(0.0, entry.marker, entry.reason) for key, entry in extract_tier_states(text).items()
    }


def _globs_narrowed(base_globs: tuple[str, ...] | None, head_globs: tuple[str, ...] | None, head_files: list[str]) -> bool:
    """MEASURED fnmatch coverage superset over `head_files` (one `git ls-files` at HEAD, never
    the base file list -- the reading that lets a glob re-pointed across a same-PR rename pass
    unmarked: the base glob's matched set, evaluated against files that exist at HEAD, is empty
    once the old directory is gone, and the empty set is trivially a subset of anything). `None`
    is maximal coverage (ungated matches everything): losing it (some tuple replacing `None`) is
    always a narrowing; gaining it (`None` replacing some tuple) is never one."""
    if head_globs is None:
        return False
    if base_globs is None:
        return True
    base_matched = {f for f in head_files if any(fnmatch(f, g) for g in base_globs)}
    head_matched = {f for f in head_files if any(fnmatch(f, g) for g in head_globs)}
    return not (base_matched <= head_matched)


def _make_weakened(head_files: list[str]) -> Callable[[object, object], bool]:
    def weakened(base: object, head: object) -> bool:
        if not (isinstance(base, TierState) and isinstance(head, TierState)):
            raise TypeError(f"weakened() expects TierState, got {type(base)!r}/{type(head)!r}")
        if base.pre and not head.pre:
            return True
        if base.full_segment is not None and head.full_segment is None:
            return True
        return _globs_narrowed(base.pre_globs, head.pre_globs, head_files)

    return weakened


def gates_deletion(base: object) -> bool:
    """True iff `base` was sequenced at all (pre OR full_segment) -- a deletion at head then has
    no marker able to rescue it. An already-unsequenced entry (both False) deletes for free."""
    if not isinstance(base, TierState):
        raise TypeError(f"gates_deletion() expects TierState, got {type(base)!r}")
    return base.pre or base.full_segment is not None


def _head_manifest_paths(root: Path) -> list[str]:
    checks_dir = root / "scripts" / "checks"
    if not checks_dir.exists():
        return []
    return sorted(p.relative_to(root).as_posix() for p in checks_dir.glob(_MANIFEST_GLOB))


def _base_manifest_paths(root: Path) -> list[str]:
    result = _common.run(
        ["git", "ls-tree", "-r", "--name-only", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
    )
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if _MANIFEST_PATH_RE.fullmatch(line.strip())})


def _batched_base_reader(root: Path, rel_paths: list[str]) -> Callable[[str], str]:
    """ONE `git cat-file --batch` call fetching every `rel_paths` entry's origin/main blob (or ""
    when the path does not exist at that ref -- a brand-new manifest domain, not an unreachable
    base) -- so the subprocess count check_state_diff pays does not fan out with the domain count.
    Byte-precise slicing (bytes in, bytes out, decoded per-blob) so a multi-byte UTF-8 character
    straddling a chunk boundary is never mis-sliced."""
    if not rel_paths:
        return lambda _rel_path: ""
    stdin_payload = "".join(f"origin/main:{p}\n" for p in rel_paths).encode("utf-8")
    result = _common.run(["git", "cat-file", "--batch"], input=stdin_payload, capture_output=True, cwd=root)
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


@registry.register("validate_tier_demotion_markers", owner="platform")
def validate_tier_demotion_markers(failed: list[str], root: Path | None = None) -> None:
    """Fail on an unauthorized check-fleet tier demotion (pre lost, full_segment lost, pre_globs
    coverage narrowed) or the removal of a still-sequenced manifest Entry. See module docstring.
    """
    print("\n=== Check-fleet tier-demotion gate (Decision 187, LSA-01 leg a) ===")
    target_root = root if root is not None else _common.ROOT

    if not _common.origin_main_reachable(target_root):
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI).")
        registry.skipped("origin/main unreachable")
        return

    all_paths = sorted(set(_head_manifest_paths(target_root)) | set(_base_manifest_paths(target_root)))
    base_reader = _batched_base_reader(target_root, all_paths)

    ls_files = _common.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", cwd=target_root)
    head_files = ls_files.stdout.splitlines() if ls_files.returncode == 0 else []
    weakened = _make_weakened(head_files)

    violations: list[str] = []
    union_of_keys: set[str] = set()

    for rel_path in all_paths:
        current_path = target_root / rel_path
        current_text = current_path.read_text(encoding="utf-8") if current_path.exists() else ""
        base_text = base_reader(rel_path)
        union_of_keys |= set(extract_tier_states(current_text)) | set(extract_tier_states(base_text))

        spec = _marker_guard.RegistrySpec(
            rel_path=rel_path,
            token=TOKEN,
            gated_direction="down",
            extractor=_marker_entries_view,
            gates_new_entry=lambda _value: False,
            label="Check-fleet tier-demotion gate (Decision 187)",
            reason_required=True,
            state_extractor=extract_tier_states,
            weakened=weakened,
            gates_deletion=gates_deletion,
        )
        violations.extend(_marker_guard.check_state_diff(spec, base_reader=base_reader))
        violations.extend(_marker_guard.check_present_markers(spec))

    if violations:
        print("Tier-demotion violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Check-fleet tier-demotion gate")
    else:
        print(f"  PASS: {len(union_of_keys)} manifest entries clean across {len(all_paths)} domain(s).")

    registry.examined(len(union_of_keys), unit="manifest_entries")
