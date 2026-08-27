#!/usr/bin/env python3
"""Remote-branch hygiene classifier for .github/workflows/branch-cleanup.yml (WS1 completion).

Deleting a remote ref is blocked for CC-web sessions at the git proxy, so branch cleanup has to run
from a runner. This module holds all of that workflow's decision logic: the shell delegate
(scripts/ci/branch_cleanup.sh) is a bare `exec python3` bridge and carries no policy.

WHY A CLASSIFIER RATHER THAN A PATTERN SWEEP. "Delete every merged claude/* branch" is the kind of
rule that is right until the one time it is not, and a wrong delete is not recoverable from the
caller's side. So every branch is decided individually and the decision is REPORTED -- branch,
class, tip age, action and result -- whether or not anything is deleted. dry_run defaults to true
in the workflow precisely so the table is the normal output and deletion is the exception.

FOUR HARD GUARDS, checked before any delete-eligible class is even considered. A branch is kept if
it is protected (main), if it has an OPEN pull request, if its tip commit is younger than
min_age_hours, or if its tip age cannot be determined at all. The last one matters: an unknown age
is not a young age and not an old age, and treating it as old would make a missing object or an
unparseable timestamp into a deletion. A branch matching no delete-eligible class is likewise kept
-- the default answer to "should this be deleted" is no.

THREE DELETE-ELIGIBLE CLASSES, in evaluation order. (A) the head of a MERGED pull request; (B) a
tip already reachable from origin/main, which covers branches merged before PRs existed, branches
squash-landed under another name, and hand-merged work; (C) an explicit operator-supplied branch in
EXTRA_BRANCHES -- which widens the candidate set and does NOT bypass the guards above.

FAIL-CLOSED ENUMERATION. The open-PR guard is only as good as the query behind it: if
`gh pr list --state open` fails and its result is read as "no open PRs", the guard silently
evaporates and a live branch gets deleted. So a failure of ANY enumeration (git ls-remote, the open
PR query, the merged PR query) aborts the run before a single deletion, rather than degrading to a
partial sweep.

Stdlib only -- the GitHub runner has no repo venv, and this module is imported by nothing in the
repo. Every subprocess call goes through an injected runner so the whole decision surface is
unit-testable without git, gh or a network (tests/test_branch_cleanup.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

PROTECTED_BRANCHES = frozenset({"main"})

DEFAULT_MIN_AGE_HOURS = 48.0
_PR_QUERY_LIMIT = "200"

# Guard and class sentinels. These strings are the classifier's vocabulary: they appear in the
# rendered decision table, in this module's tests, and in
# scripts/checks/ci_guards/validate_branch_cleanup.py, which asserts the hard guards still exist by
# name rather than by matching a line of code that any refactor would reword.
GUARD_PROTECTED_BRANCH = "protected-branch"
GUARD_OPEN_PR = "open-pr"
GUARD_YOUNGER_THAN_MIN_AGE = "younger-than-min-age"
GUARD_UNKNOWN_AGE = "unknown-age"
CLASS_MERGED_PR_HEAD = "merged-pr-head"
CLASS_ANCESTOR_OF_MAIN = "ancestor-of-main"
CLASS_EXTRA_BRANCH = "extra-branch"
CLASS_UNCLASSIFIED = "unclassified"

ACTION_DELETE = "delete"
ACTION_KEEP = "keep"

RESULT_DRY_RUN = "dry-run"
RESULT_DELETED = "deleted"
RESULT_KEPT = "kept"


@dataclass(frozen=True)
class CommandResult:
    """One completed subprocess: everything the decision logic is allowed to know about it."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str]], CommandResult]


@dataclass(frozen=True)
class BranchDecision:
    """The full, reportable answer for one branch -- never just a boolean."""

    branch: str
    sha: str
    classification: str
    action: str
    reason: str
    age_hours: float | None


def subprocess_runner(cmd: Sequence[str]) -> CommandResult:
    """Default runner. Never raises on a non-zero exit -- the caller inspects returncode."""
    try:
        completed = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandResult(returncode=127, stdout="", stderr=str(exc))
    return CommandResult(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def parse_bool(raw: str | None) -> bool:
    """Fail-safe truthiness: anything that is not explicitly falsey means dry run.

    A garbled or absent DRY_RUN must never be read as "go ahead and delete", so the unknown case
    resolves to True rather than to False.
    """
    return (raw or "").strip().lower() not in {"false", "0", "no", "off"}


def parse_min_age_hours(raw: str | None) -> float:
    try:
        value = float((raw or "").strip())
    except ValueError:
        return DEFAULT_MIN_AGE_HOURS
    return value if value >= 0 else DEFAULT_MIN_AGE_HOURS


def parse_branch_list(raw: str | None) -> tuple[str, ...]:
    return tuple(token.strip() for token in (raw or "").replace("\n", ",").split(",") if token.strip())


def list_remote_branches(runner: Runner) -> dict[str, str] | None:
    """{branch: tip_sha} from the remote itself. None on failure -- never a partial or empty map."""
    result = runner(["git", "ls-remote", "--heads", "origin"])
    if result.returncode != 0:
        return None
    branches: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/heads/"):
            continue
        branches[parts[1][len("refs/heads/") :]] = parts[0]
    return branches


def _pr_head_refs(runner: Runner, state: str) -> set[str] | None:
    result = runner(
        [
            "gh",
            "pr",
            "list",
            "--state",
            state,
            "--limit",
            _PR_QUERY_LIMIT,
            "--json",
            "headRefName",
            "--jq",
            ".[].headRefName",
        ]
    )
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def open_pr_heads(runner: Runner) -> set[str] | None:
    return _pr_head_refs(runner, "open")


def merged_pr_heads(runner: Runner) -> set[str] | None:
    return _pr_head_refs(runner, "merged")


def tip_age_hours(runner: Runner, sha: str, now: datetime) -> float | None:
    """Hours since the tip commit's committer date. None when git cannot answer at all."""
    result = runner(["git", "log", "-1", "--format=%cI", sha])
    if result.returncode != 0:
        return None
    stamp = result.stdout.strip()
    if not stamp:
        return None
    try:
        committed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if committed.tzinfo is None:
        committed = committed.replace(tzinfo=timezone.utc)
    return (now - committed).total_seconds() / 3600.0


def is_ancestor_of_main(runner: Runner, sha: str) -> bool:
    """True only on a clean exit 0. A git error is NOT reachability -- it resolves to "keep"."""
    return runner(["git", "merge-base", "--is-ancestor", sha, "origin/main"]).returncode == 0


def decide_branch(
    branch: str,
    sha: str,
    *,
    age_hours: float | None,
    min_age_hours: float,
    has_open_pr: bool,
    is_merged_pr_head: bool,
    is_ancestor: bool,
    is_extra: bool,
) -> BranchDecision:
    """The whole delete/keep policy, as one pure function over already-gathered facts."""

    def keep(classification: str, reason: str) -> BranchDecision:
        return BranchDecision(branch, sha, classification, ACTION_KEEP, reason, age_hours)

    if branch in PROTECTED_BRANCHES:
        return keep(GUARD_PROTECTED_BRANCH, f"{branch} is protected and is never deleted")
    if has_open_pr:
        return keep(GUARD_OPEN_PR, "an open pull request still points at this branch")
    if age_hours is None:
        return keep(GUARD_UNKNOWN_AGE, "tip commit age could not be determined; unknown age is never old enough")
    if age_hours < min_age_hours:
        return keep(GUARD_YOUNGER_THAN_MIN_AGE, f"tip is {age_hours:.1f}h old, under the {min_age_hours:.1f}h floor")

    if is_merged_pr_head:
        return BranchDecision(branch, sha, CLASS_MERGED_PR_HEAD, ACTION_DELETE, "head of a merged pull request", age_hours)
    if is_ancestor:
        return BranchDecision(
            branch, sha, CLASS_ANCESTOR_OF_MAIN, ACTION_DELETE, "tip is already reachable from origin/main", age_hours
        )
    if is_extra:
        return BranchDecision(branch, sha, CLASS_EXTRA_BRANCH, ACTION_DELETE, "named explicitly in extra_branches", age_hours)
    return keep(CLASS_UNCLASSIFIED, "matches no delete-eligible class")


def plan_decisions(
    runner: Runner,
    branches: dict[str, str],
    *,
    open_heads: set[str],
    merged_heads: set[str],
    extra_branches: Sequence[str],
    min_age_hours: float,
    now: datetime,
) -> list[BranchDecision]:
    extra = set(extra_branches)
    decisions: list[BranchDecision] = []
    for branch in sorted(branches):
        sha = branches[branch]
        age = tip_age_hours(runner, sha, now)
        merged = branch in merged_heads
        ancestor = False if merged else is_ancestor_of_main(runner, sha)
        decisions.append(
            decide_branch(
                branch,
                sha,
                age_hours=age,
                min_age_hours=min_age_hours,
                has_open_pr=branch in open_heads,
                is_merged_pr_head=merged,
                is_ancestor=ancestor,
                is_extra=branch in extra,
            )
        )
    return decisions


def delete_remote_branch(runner: Runner, repo: str, branch: str) -> CommandResult:
    return runner(["gh", "api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{branch}"])


def execute_decisions(
    runner: Runner,
    decisions: Sequence[BranchDecision],
    *,
    dry_run: bool,
    repo: str,
) -> list[tuple[BranchDecision, str]]:
    """Apply each decision. Returns (decision, result) pairs in the order given."""
    rows: list[tuple[BranchDecision, str]] = []
    for decision in decisions:
        if decision.action != ACTION_DELETE:
            rows.append((decision, RESULT_KEPT))
            continue
        if dry_run:
            rows.append((decision, RESULT_DRY_RUN))
            continue
        result = delete_remote_branch(runner, repo, decision.branch)
        if result.returncode == 0:
            rows.append((decision, RESULT_DELETED))
        else:
            rows.append((decision, f"FAILED (exit {result.returncode})"))
    return rows


def _format_age(age_hours: float | None) -> str:
    return "unknown" if age_hours is None else f"{age_hours:.1f}h"


def render_summary(rows: Sequence[tuple[BranchDecision, str]], *, dry_run: bool) -> str:
    mode = "DRY RUN (nothing deleted)" if dry_run else "LIVE"
    lines = [
        "",
        "## branch-cleanup",
        "",
        f"Mode: {mode}",
        "",
        "| Branch | Class | Age | Action | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for decision, result in rows:
        lines.append(
            f"| {decision.branch} | {decision.classification} | {_format_age(decision.age_hours)} "
            f"| {decision.action} | {result} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as exc:
        print(f"[BRANCH-CLEANUP] could not write the step summary: {exc}", file=sys.stderr)


def _abort(reason: str) -> int:
    message = f"[BRANCH-CLEANUP] FAILURE: {reason}"
    print(message, file=sys.stderr)
    _write_step_summary(f"\n## branch-cleanup FAILURE\n\n{message}\n")
    return 1


def main(runner: Runner | None = None, now: datetime | None = None) -> int:
    run = runner or subprocess_runner
    moment = now or datetime.now(timezone.utc)

    dry_run = parse_bool(os.environ.get("DRY_RUN"))
    min_age_hours = parse_min_age_hours(os.environ.get("MIN_AGE_HOURS"))
    extra_branches = parse_branch_list(os.environ.get("EXTRA_BRANCHES"))
    repo = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""

    if not dry_run and not repo:
        return _abort("no GH_REPO/GITHUB_REPOSITORY is set, so no deletion endpoint can be addressed.")

    branches = list_remote_branches(run)
    if branches is None:
        return _abort("git ls-remote --heads origin failed; the branch set is unknown, so nothing is deleted.")

    open_heads = open_pr_heads(run)
    if open_heads is None:
        return _abort("the open-PR query failed; the open-PR hard guard cannot be evaluated, so nothing is deleted.")

    merged_heads = merged_pr_heads(run)
    if merged_heads is None:
        return _abort("the merged-PR query failed; branch classification would be partial, so nothing is deleted.")

    decisions = plan_decisions(
        run,
        branches,
        open_heads=open_heads,
        merged_heads=merged_heads,
        extra_branches=extra_branches,
        min_age_hours=min_age_hours,
        now=moment,
    )
    rows = execute_decisions(run, decisions, dry_run=dry_run, repo=repo)

    summary = render_summary(rows, dry_run=dry_run)
    print(summary)
    _write_step_summary(summary)

    failures = [decision.branch for decision, result in rows if result.startswith("FAILED")]
    if failures:
        return _abort(f"deletion failed for: {', '.join(failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
