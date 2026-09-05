"""Checked-in 40-commit evidence for the roadmap span-attribution property, plus its generator.

A tests/fixtures helper, never a test module (its name does not start with test_, so pytest
never collects it and the cross-test-import guard never sees it).

GENERATION COMMAND -- the only way tests/fixtures/roadmap_touched_items.json is produced, and
the command its own header names:

    bin/venv-python -m tests.fixtures.roadmap_touched_items --generate

HYGIENE, because two invariants depend on it. (1) The git-shelling half is reachable ONLY
through main()/the __main__ guard: nothing executes at import and no exception is raised at
import time (AGENTS.md), so importing this module inside a depth-truncated clone shells nothing
and load_fixture() reads a file and nothing else. (2) Every git call passes encoding="utf-8",
errors="replace" with text=True.

WHY A CHECKED-IN FIXTURE. main-validate checks out at fetch-depth 2, where the 40 commits'
parents are unreachable, so a test reading live history would die there. The evidence is
materialized ONCE and the tests read only this file.

ENCODING BINDING. The JSON's top-level keys are `header`, `id_indexes`, `commits` and
`known_legacy_false_attributions`. Each `commits` row carries `commit`, `pre_index`,
`post_index`, `changed_pre`, `changed_post`, `expected_touched`, `legacy_regex_raw`,
`legacy_regex_true_positives` and `bare_string_criteria_ids`; `load_fixture()` exposes the last
four (and `commit`) as the row attributes `commit`, `expected`, `legacy_raw`,
`legacy_true_positives` and `bare_string_criteria`, with the two pooled id-index references
rehydrated into `pre_spans`/`post_spans` (ItemSpan lists) and the changed-line RUNS rehydrated
into `changed` (a ChangedLines).

`bare_string_criteria_ids` carries the ADVISORY-FRAMING COUNTERFACTUAL rather than a property of
the detector: the POST-image tier_item ids still holding a bare-string exit criterion, which is
exactly what criterion (ii)'s failing arm rejects on a touched item. A commit whose span
attribution meets that set is a commit a span-driven FAILING arm would have blocked, so the
count of such commits is the measured reason both new surfacings land ADVISORY -- computed by a
verification step rather than carried in plan prose.

The curated `known_legacy_false_attributions` block is (commit, item_id, mechanism) triples for
every legacy-named real tier_item that no span touches. It is CURATED: --generate refuses to
overwrite it (see generate()), because a block silently rewritten to whatever residue a run
produced would assert nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

from scripts.checks.roadmap._roadmap_spans import ChangedLines, ItemSpan, changed_lines, item_spans, legacy_regex_item_ids

FIXTURE_PATH = Path(__file__).with_name("roadmap_touched_items.json")
ROADMAP_REL_PATH = "docs/ROADMAP-PLATFORM.yaml"
GENERATION_COMMAND = "bin/venv-python -m tests.fixtures.roadmap_touched_items --generate"
COMMIT_LIMIT = 40


@dataclasses.dataclass(frozen=True)
class FixtureRow:
    """One stored commit's attribution evidence, rehydrated for direct use by the detector."""

    commit: str
    pre_spans: list[ItemSpan]
    post_spans: list[ItemSpan]
    changed: ChangedLines
    expected: list[str]
    legacy_raw: list[str]
    legacy_true_positives: list[str]
    bare_string_criteria: list[str]


def _read_json(path: Path | None) -> dict:
    """The stored fixture document. Reads a file and nothing else -- no git, no subprocess."""
    return json.loads((path or FIXTURE_PATH).read_text(encoding="utf-8"))


def _spans_from_index(index: list[list]) -> list[ItemSpan]:
    """Rehydrate one pooled id-index into ItemSpan objects."""
    return [ItemSpan(item_id=str(row[0]), start=int(row[1]), end=int(row[2])) for row in index]


def _lines_from_runs(runs: list[list[int]]) -> frozenset[int]:
    """Rehydrate [start, count] runs into the changed-line set they encode."""
    return frozenset(line for start, count in runs for line in range(int(start), int(start) + int(count)))


def load_fixture(path: Path | None = None) -> list[FixtureRow]:
    """Every stored commit as a FixtureRow, in stored order. Never touches git history."""
    data = _read_json(path)
    indexes = data["id_indexes"]
    return [
        FixtureRow(
            commit=row["commit"],
            pre_spans=_spans_from_index(indexes[row["pre_index"]]),
            post_spans=_spans_from_index(indexes[row["post_index"]]),
            changed=ChangedLines(pre=_lines_from_runs(row["changed_pre"]), post=_lines_from_runs(row["changed_post"])),
            expected=list(row["expected_touched"]),
            legacy_raw=list(row["legacy_regex_raw"]),
            legacy_true_positives=list(row["legacy_regex_true_positives"]),
            bare_string_criteria=list(row["bare_string_criteria_ids"]),
        )
        for row in data["commits"]
    ]


def known_false_attributions(path: Path | None = None) -> list[tuple[str, str, str]]:
    """The curated (commit, item_id, mechanism) triples the computed residue is asserted against."""
    return [(row["commit"], row["item_id"], row["mechanism"]) for row in _read_json(path)["known_legacy_false_attributions"]]


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    """One git invocation, always decoded as utf-8 with replacement (AGENTS.md)."""
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root), check=False
    )


def _runs(lines: frozenset[int]) -> list[list[int]]:
    """Contiguous [start, count] runs of a changed-line set, in ascending order."""
    runs: list[list[int]] = []
    for line in sorted(lines):
        if runs and runs[-1][0] + runs[-1][1] == line:
            runs[-1][1] += 1
        else:
            runs.append([line, 1])
    return runs


def bare_string_criteria_ids(text: str) -> list[str]:
    """POST-image tier_item ids still holding at least one BARE-STRING exit criterion.

    The counterfactual input: criterion (ii)'s failing arm rejects exactly this shape on a
    TOUCHED item, so a commit whose span attribution meets this set is one a span-driven failing
    arm would have blocked. Decision 136 is the authority for the paydown that would clear it.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    items = document.get("tier_items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        return []
    return sorted(
        str(item.get("id"))
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("exit_criteria"), list)
        and any(isinstance(criterion, str) for criterion in item["exit_criteria"])
    )


def _pool(index: list[ItemSpan], indexes: dict[str, list[list]]) -> str:
    """Store one image's id-index in the pool under a content key and return that key."""
    payload = [[span.item_id, span.start, span.end] for span in index]
    key = hashlib.sha1(json.dumps(payload).encode("utf-8")).hexdigest()[:12]
    indexes.setdefault(key, payload)
    return key


def generate(root: Path, limit: int = COMMIT_LIMIT, previous: dict | None = None) -> dict:
    """Build the fixture document from the last `limit` commits touching the roadmap.

    The curated known_legacy_false_attributions block is CARRIED OVER from `previous` verbatim
    when one is given -- a regeneration never silently rewrites a curated mechanism, which is the
    whole point of enumerating the residue by name rather than recomputing it.
    """
    log = _git(["log", f"-{limit}", "--format=%h", "--", ROADMAP_REL_PATH], root)
    commits = [line.strip() for line in log.stdout.splitlines() if line.strip()]
    indexes: dict[str, list[list]] = {}
    rows: list[dict] = []
    for commit in commits:
        pre = _git(["show", f"{commit}^:{ROADMAP_REL_PATH}"], root)
        post = _git(["show", f"{commit}:{ROADMAP_REL_PATH}"], root)
        diff = _git(["diff", f"{commit}^", commit, "--", ROADMAP_REL_PATH], root)
        pre_text = pre.stdout if pre.returncode == 0 else ""
        pre_spans = item_spans(pre_text)
        post_spans = item_spans(post.stdout)
        changed = changed_lines(diff.stdout)
        expected = sorted(
            {span.item_id for span in pre_spans if any(span.start <= n <= span.end for n in changed.pre)}
            | {span.item_id for span in post_spans if any(span.start <= n <= span.end for n in changed.post)}
        )
        raw = sorted(legacy_regex_item_ids(diff.stdout))
        rows.append(
            {
                "commit": commit,
                "pre_index": _pool(pre_spans, indexes),
                "post_index": _pool(post_spans, indexes),
                "changed_pre": _runs(changed.pre),
                "changed_post": _runs(changed.post),
                "expected_touched": expected,
                "legacy_regex_raw": raw,
                "legacy_regex_true_positives": sorted(set(raw) & set(expected)),
                "bare_string_criteria_ids": bare_string_criteria_ids(post.stdout),
            }
        )
    head = _git(["rev-parse", "origin/main"], root).stdout.strip()
    curated = (previous or {}).get("known_legacy_false_attributions", [])
    return {
        "header": {
            "generation_command": GENERATION_COMMAND,
            "source": ROADMAP_REL_PATH,
            "commit_limit": limit,
            "base": head,
            "note": "Materialized once from real history; no test reads live git. Regenerate only via the command above.",
        },
        "id_indexes": indexes,
        "commits": rows,
        "known_legacy_false_attributions": curated,
    }


def dumps(document: dict) -> str:
    """Serialize the fixture document with ONE LINE PER RECORD -- each pooled id-index, each
    commit row and each curated triple compact on its own line. Plain json.dumps(indent=...)
    would render every three-element span across five lines and triple the checked-in size for
    no readability a reader of 6,000 spans would ever use.
    """
    compact = {"separators": (",", ":")}
    indexes = ",\n  ".join(
        f"{json.dumps(key)}: {json.dumps(value, **compact)}" for key, value in document["id_indexes"].items()
    )
    commits = ",\n  ".join(json.dumps(row, **compact) for row in document["commits"])
    curated = ",\n  ".join(json.dumps(row, **compact) for row in document["known_legacy_false_attributions"])
    return (
        "{\n"
        f' "header": {json.dumps(document["header"], **compact)},\n'
        f' "id_indexes": {{\n  {indexes}\n }},\n'
        f' "commits": [\n  {commits}\n ],\n'
        f' "known_legacy_false_attributions": [\n  {curated}\n ]\n'
        "}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for --generate. Nothing here runs at import."""
    parser = argparse.ArgumentParser(description="Generate tests/fixtures/roadmap_touched_items.json")
    parser.add_argument("--generate", action="store_true", help="write the fixture JSON")
    parser.add_argument("--limit", type=int, default=COMMIT_LIMIT, help="commits to sample")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="repository root")
    args = parser.parse_args(argv)
    if not args.generate:
        parser.error("nothing to do: pass --generate")
    previous = _read_json(None) if FIXTURE_PATH.exists() else None
    document = generate(args.root, args.limit, previous)
    FIXTURE_PATH.write_text(dumps(document), encoding="utf-8")
    print(f"WROTE {FIXTURE_PATH} commits={len(document['commits'])} id_indexes={len(document['id_indexes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
