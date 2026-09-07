"""Backlog-health defect classification (PLAN-backlog-health-detection).

Joins census.py's open-rec rows to probe.py's verdicts and COMPOSES scripts/rec_relevance.py for
exactly two of its deterministic signals -- target_existence and open_duplicate -- rather than
re-deriving them (Decision 103 names rec_relevance.py THE relevance evaluator). Every call here
passes `run_acceptance_probe=False` (the default) and never `recent_commits=`/`closed_recs=`/
`decisions=`, so only those two signals are reachable; the acceptance-probe signal for class 1
comes exclusively from probe.py's own verdict join, never from rec_relevance's
`_run_acceptance_probe` (a bare, unisolated `subprocess.run(..., shell=True)` that would defeat
the whole three-job credential split -- see the plan's constraints).

This module runs inside the CREDENTIALED escalate job: it is pure joining and predicate
evaluation over data already in hand (census.json + probe.json), executes nothing itself, and has
no CLI subcommand of its own (see __main__.py, which owns the census/probe/escalate wiring).

Four defect classes (one source per class, one rec_episode.run_episode call each in escalate.py):
  1. probe split       -- among probe verdicts that PASSED, a rec is a satisfied_candidate if a
                           commit touched rec.file since rec creation, else vacuous (a probe that
                           passed without the target ever changing proves nothing).
  2. acceptance quality -- an acceptance command the same banned-pattern linter
                           (validate_recommendations_schema.py) would reject, or one that
                           discriminates nothing (no construct whose outcome could ever differ
                           between a fixed and a broken tree).
  3. dependency refs    -- a `dependencies` entry that is not a bare `rec-<digits>` string
                           (malformed) or that names an id absent from the known corpus
                           (dangling). Measured empty on today's open backlog by design (Bundle 1
                           / #1007 added write-time array_element_format) -- an empty population
                           here is a clean pass, not a detector defect.
  4. premise-dead/dup   -- rec_relevance's stale_target verdict (split at the Decision 64
                           2026-05-01 bootstrap-cohort anchor) and its duplicate verdict
                           (title Jaccard >= 0.7 on the same file).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from scripts.backlog_health import census
from scripts.backlog_health import probe as probe_mod
from scripts.rec_relevance import evaluate_rec_relevance

_BOOTSTRAP_ANCHOR = "2026-05-01"

_LINT_REJECT_PATTERNS: tuple[re.Pattern[str], ...] = (re.compile(r"--pre\b"),)

_DISCRIMINATING_MARKERS: tuple[str, ...] = (
    "grep",
    "test ",
    "test(",
    "[ ",
    "[[",
    "pytest",
    "assert",
    "diff",
    "!=",
    "==",
    "&&",
    "||",
    "-eq",
    "-ne",
    "-q",
    "exit 1",
    "!",
)

_REC_ID_RE = re.compile(r"^rec-\d+$")


def _is_lint_reject(acceptance: str) -> bool:
    if "python -c" in acceptance and "'python -c'" not in acceptance:
        return True
    return any(p.search(acceptance) for p in _LINT_REJECT_PATTERNS)


def _is_non_discriminating(acceptance: str) -> bool:
    return not any(marker in acceptance for marker in _DISCRIMINATING_MARKERS)


def classify_acceptance_quality(open_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Class 2. Every open rec's acceptance command sorted into lint_reject xor
    non_discriminating (never both -- a lint-rejected command is reported as that, not also
    flagged non-discriminating). Empty/prose acceptance is census.py's PROSE_ONLY concern, not
    this class's."""
    lint_reject: list[str] = []
    non_discriminating: list[str] = []
    for row in open_rows:
        acceptance = (row.get("acceptance") or "").strip()
        if census.is_prose(acceptance):
            continue
        if _is_lint_reject(acceptance):
            lint_reject.append(row["id"])
        elif _is_non_discriminating(acceptance):
            non_discriminating.append(row["id"])
    return {"lint_reject": lint_reject, "non_discriminating": non_discriminating}


def classify_dependency_refs(open_rows: list[dict[str, Any]], known_ids: set[str]) -> dict[str, list[str]]:
    """Class 3. `malformed` -- a dependency entry that is not a bare `rec-<digits>` string
    (e.g. a stray-bracketed legacy value like "[rec-028]"). `dangling` -- a well-shaped id absent
    from `known_ids`. A rec with a malformed entry is reported only under `malformed`, never
    double-counted under `dangling` for the same entry."""
    malformed: list[str] = []
    dangling: list[str] = []
    for row in open_rows:
        deps = row.get("dependencies") or []
        is_malformed = any(not isinstance(dep, str) or not _REC_ID_RE.match(dep) for dep in deps)
        if is_malformed:
            malformed.append(row["id"])
            continue
        if any(dep not in known_ids for dep in deps):
            dangling.append(row["id"])
    return {"malformed": malformed, "dangling": dangling}


def classify_premise_dead_and_duplicates(open_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Class 4. Composes rec_relevance.evaluate_rec_relevance for target_existence
    (stale_target -> premise-dead, split at the bootstrap anchor) and open_duplicate
    (duplicate -> near-duplicate) ONLY -- run_acceptance_probe stays at its False default, and
    neither recent_commits/closed_recs/decisions is ever passed, so no other signal fires."""
    premise_dead_bootstrap: list[str] = []
    premise_dead_post_anchor: list[str] = []
    near_duplicate: list[str] = []
    for row in open_rows:
        others = [r for r in open_rows if r.get("id") != row.get("id")]
        verdict, _evidence = evaluate_rec_relevance(row, run_acceptance_probe=False, open_recs=others)
        if verdict == "stale_target":
            created = row.get("created_timestamp") or ""
            if created and created < _BOOTSTRAP_ANCHOR:
                premise_dead_bootstrap.append(row["id"])
            else:
                premise_dead_post_anchor.append(row["id"])
        elif verdict == "duplicate":
            near_duplicate.append(row["id"])
    return {
        "premise_dead_bootstrap": premise_dead_bootstrap,
        "premise_dead_post_anchor": premise_dead_post_anchor,
        "near_duplicate": near_duplicate,
    }


def _file_touched_since(rec_file: str, created_timestamp: str, recent_commits: list[dict[str, Any]]) -> bool:
    if not rec_file:
        return False
    for commit in recent_commits:
        commit_date = commit.get("date") or ""
        if created_timestamp and commit_date and commit_date <= created_timestamp:
            continue
        for changed in commit.get("files") or []:
            if changed == rec_file or changed.endswith(f"/{rec_file}") or rec_file.endswith(f"/{changed}"):
                return True
    return False


def classify_probe_split(census_result: dict[str, Any], probe_verdicts: dict[str, str]) -> dict[str, list[str]]:
    """Class 1. Among probe verdicts that PASSED, satisfied_candidate iff a commit touched
    rec.file since rec creation (unbounded history -- see census.collect_recent_commits),
    otherwise vacuous. Any non-PASS verdict (fail/timeout/budget_exhausted/isolation_unavailable)
    is not part of this split at all."""
    recent_commits = census_result["recent_commits"]
    rows_by_id = {row["id"]: row for row in census_result["open_rows"]}
    satisfied: list[str] = []
    vacuous: list[str] = []
    for rec_id, verdict in probe_verdicts.items():
        if verdict != probe_mod.PASS:
            continue
        row = rows_by_id.get(rec_id)
        if row is None:
            continue
        rec_file = (row.get("file") or "").strip()
        created = row.get("created_timestamp") or ""
        if _file_touched_since(rec_file, created, recent_commits):
            satisfied.append(rec_id)
        else:
            vacuous.append(rec_id)
    return {"satisfied_candidate": satisfied, "vacuous": vacuous}


def classify_all(
    census_result: dict[str, Any],
    probe_verdicts: dict[str, str],
    *,
    known_rec_ids: Optional[set[str]] = None,
) -> dict[str, dict[str, list[str]]]:
    """Run all four classifiers over one census+probe snapshot."""
    open_rows = census_result["open_rows"]
    known_ids = known_rec_ids if known_rec_ids is not None else {row["id"] for row in open_rows}
    return {
        "probe_split": classify_probe_split(census_result, probe_verdicts),
        "acceptance_quality": classify_acceptance_quality(open_rows),
        "dependency_refs": classify_dependency_refs(open_rows, known_ids),
        "premise_dead_and_duplicates": classify_premise_dead_and_duplicates(open_rows),
    }
