#!/usr/bin/env python3
"""Fail-closed semver-class deriver for scripts/ci/dependabot_auto_merge.sh.

WHY THIS EXISTS. dependabot/fetch-metadata is the managed primitive that classifies a bump, and
it stays the authority: a non-empty UPDATE_TYPE passes straight through at first precedence and
SHORT-CIRCUITS every derivation branch below it (Decision 100). This script only ever classifies a
bump the primitive DECLINED to classify -- it grants no authority the primitive lacks, and
substitutes for nothing.

WHY THE PRIMITIVE'S OUTPUT CAN BE EMPTY. fetch-metadata v2's anchored title regex left update-type
empty for this repo's `update <x> requirement from <spec> to <spec>` range-update shape, and the
auto-merge gate denied every such PR -- a silent never-merge with no operator-visible reason. v3
(PR #982) populates it for that shape, so this deriver ships as defence-in-depth for the empty
values dependabot-core can still emit: grouped PRs without per-member versions, and title shapes
the relaxed regex misses.

PRECEDENCE, fail-closed at every fall-through:
  1. a non-empty UPDATE_TYPE (the managed primitive) -- short-circuits everything below;
  2. per-member UPDATED_DEPENDENCIES_JSON (each member's own updateType, else its version pair),
     taking the RISKIEST class across members, where unknown outranks major;
  3. the scalar PREVIOUS_VERSION/NEW_VERSION pair, ONLY when DEPENDENCY_NAMES holds exactly one
     token -- a multi-name group with a single scalar pair falls through rather than guessing;
  4. the PR title, matched ONLY by `update <x> requirement from <spec> to <spec>`. The grouped
     `bump X from A to B` shape is deliberately NOT matched: fetch-metadata already classifies it
     at precedence 1, and a title-only auto-merge surface is not worth widening;
  5. unknown.

Prints exactly one of patch|minor|major|unknown and ALWAYS exits 0 -- the caller decides policy
(it allows patch/minor and denies major/unknown), so an internal error here must never red the
workflow step, only deny the merge. Stdlib only; never raises at import.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping

PATCH = "patch"
MINOR = "minor"
MAJOR = "major"
UNKNOWN = "unknown"

# Risk order: the riskiest class across a group wins, and an unclassifiable member outranks a
# major one -- a group is only as classifiable as its least-classifiable member.
_RANK = {PATCH: 0, MINOR: 1, MAJOR: 2, UNKNOWN: 3}

_UPDATE_TYPE_CLASSES = {
    "version-update:semver-patch": PATCH,
    "version-update:semver-minor": MINOR,
    "version-update:semver-major": MAJOR,
}

# `update <x> requirement from <spec> to <spec>` only -- see the precedence note above.
_TITLE_RE = re.compile(
    r"\bupdate\b.*?\brequirement\b.*?\bfrom\s+(?P<previous>\S+)\s+to\s+(?P<new>\S+)",
    re.IGNORECASE,
)

# A comma-joined specifier's LOWER-BOUND clause is the one that names the version in play; the
# upper bound is a ceiling, not a version. `<2,>=1.28.0` is 1.28.0, never 2.
_LOWER_BOUND_OPERATORS = (">=", "==", "~=", ">")
_NUMERIC_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _parse_version(raw: str) -> tuple[int, int, int] | None:
    """Parse a version or specifier into a (major, minor, patch) triple, or None if unparseable.

    Strips a leading `v`, selects the lower-bound clause of a comma-joined specifier, drops the
    operator, takes the first three numeric components (missing components are 0) and discards
    every PEP 440 suffix (.postN, rcN, .devN, +local) and any other trailing text.
    """
    clauses = [clause.strip() for clause in (raw or "").split(",") if clause.strip()]
    if not clauses:
        return None

    chosen: str | None = None
    for operator in _LOWER_BOUND_OPERATORS:
        for clause in clauses:
            if clause.startswith(operator):
                chosen = clause[len(operator) :]
                break
        if chosen is not None:
            break
    if chosen is None:
        for clause in clauses:
            stripped = clause.lstrip("<>=!~ ")
            if stripped[:1].lower() == "v":
                stripped = stripped[1:]
            if stripped[:1].isdigit():
                chosen = stripped
                break
    if chosen is None:
        return None

    chosen = chosen.strip()
    if chosen[:1].lower() == "v":
        chosen = chosen[1:]
    match = _NUMERIC_PREFIX_RE.match(chosen.strip())
    if not match:
        return None
    parts = [int(part) for part in match.group(1).split(".")[:3]]
    parts += [0] * (3 - len(parts))
    return (parts[0], parts[1], parts[2])


def _class_between(previous: str, new: str) -> str | None:
    """Classify a bump from `previous` to `new`, or None if either side is unparseable."""
    before = _parse_version(previous)
    after = _parse_version(new)
    if before is None or after is None:
        return None
    if before[0] != after[0]:
        return MAJOR
    if before[1] != after[1]:
        return MINOR
    return PATCH


def _riskiest(classes: list[str]) -> str:
    return max(classes, key=lambda value: _RANK[value])


def _member_class(member: Mapping[str, object]) -> str:
    declared = str(member.get("updateType") or member.get("update_type") or "").strip()
    if declared:
        return _UPDATE_TYPE_CLASSES.get(declared, UNKNOWN)
    previous = str(member.get("prevVersion") or member.get("prev_version") or "")
    new = str(member.get("newVersion") or member.get("new_version") or "")
    return _class_between(previous, new) or UNKNOWN


def _from_updated_dependencies(payload: str) -> str | None:
    """Classify from fetch-metadata's updated-dependencies-json, or None if it is unusable."""
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    members = [member for member in parsed if isinstance(member, Mapping)]
    if len(members) != len(parsed):
        return None
    return _riskiest([_member_class(member) for member in members])


def _from_scalar_pair(env: Mapping[str, str]) -> str | None:
    """Classify from the scalar version pair -- only for a single dependency name."""
    names = [token for token in re.split(r"[,;\s]+", env.get("DEPENDENCY_NAMES", "") or "") if token]
    if len(names) != 1:
        return None
    return _class_between(env.get("PREVIOUS_VERSION", "") or "", env.get("NEW_VERSION", "") or "")


def _from_pr_title(title: str) -> str | None:
    match = _TITLE_RE.search(title or "")
    if not match:
        return None
    return _class_between(match.group("previous"), match.group("new"))


def derive(env: Mapping[str, str]) -> str:
    """Return exactly one of patch|minor|major|unknown for the bump described by `env`."""
    declared = str(env.get("UPDATE_TYPE", "") or "").strip()
    if declared:
        return _UPDATE_TYPE_CLASSES.get(declared, UNKNOWN)

    payload = str(env.get("UPDATED_DEPENDENCIES_JSON", "") or "").strip()
    if payload:
        from_json = _from_updated_dependencies(payload)
        if from_json is not None:
            return from_json

    from_scalar = _from_scalar_pair(env)
    if from_scalar is not None:
        return from_scalar

    return _from_pr_title(str(env.get("PR_TITLE", "") or "")) or UNKNOWN


def main() -> int:
    """Print the derived class. Always returns 0 -- the caller owns the allow/deny policy."""
    try:
        print(derive(os.environ))
    except Exception as exc:  # noqa: BLE001 - fail closed, never red the workflow step
        print(f"dependabot_semver_class: derivation failed ({exc!r}); failing closed", file=sys.stderr)
        print(UNKNOWN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
