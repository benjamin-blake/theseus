"""Identity gate for agent pushes and GitHub remote writes: git/evidence decisions plus a CLI.

Answers "was the pushed tree validated from this worktree?", not "is it green" -- a
validated-but-red tree passes with a warning (no wedge, no release valve; Decision 163 point 1).
Composes scripts.checks.validation_result's evidence primitives (imported, never re-implemented)
with base-ref reads of docs/contracts/git-ops.yaml's handoff_evidence_gate clause. No agent
override of any kind.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.checks import _common
from scripts.checks.validation_result import ATTEST_RULES, attests_head, evidence_path_for, load_record

GIT_OPS_PATH = "docs/contracts/git-ops.yaml"


@dataclass(frozen=True)
class Verdict:
    kind: str  # pass, warn, deny
    rule: str
    message: str


_UNREADABLE_PREFIXES_VERDICT = Verdict(
    "deny",
    "unreadable_agent_branch_prefixes",
    "cannot read branching_topology.agent_branch_prefixes from origin/main",
)


def _run(args: list[str], cwd: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        return False, ""
    return True, result.stdout.strip()


def _load_base_ref_yaml(cwd: Path) -> dict | None:
    """Read origin/main:docs/contracts/git-ops.yaml as a dict. None on any unknown (no
    origin/main ref, unreadable/malformed YAML, or non-mapping content) -- fail closed."""
    ok, text = _run(["show", "origin/main:" + GIT_OPS_PATH], cwd)
    if not ok:
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _base_ref_clause(cwd: Path) -> dict | None:
    """Read handoff_evidence_gate's base-ref clause. None on any unknown (no origin/main ref,
    unreadable/malformed YAML, or the key missing) -- fail closed to "no exemptions, no extra
    destination prefixes" (bootstrap: the base ref before this plan merges carries no clause at
    all, per R3-1)."""
    data = _load_base_ref_yaml(cwd)
    if data is None:
        return None
    clause = data.get("handoff_evidence_gate")
    return clause if isinstance(clause, dict) else None


def _base_ref_agent_branch_prefixes(cwd: Path) -> list[str] | None:
    data = _load_base_ref_yaml(cwd)
    if data is None:
        return None
    topology = data.get("branching_topology")
    if not isinstance(topology, dict):
        return None
    prefixes = topology.get("agent_branch_prefixes")
    if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
        return None
    return prefixes


def destination_prefixes(cwd: Path) -> list[str] | None:
    """agent_branch_prefixes PLUS the gate-local extra_destination_prefixes, both from the base
    ref. None means unreadable agent_branch_prefixes -- the only thing that denies at this layer;
    an absent gate clause (bootstrap) means no EXTRA prefixes, not no prefixes."""
    prefixes = _base_ref_agent_branch_prefixes(cwd)
    if prefixes is None:
        return None
    clause = _base_ref_clause(cwd)
    extra = []
    if clause is not None:
        extra = clause.get("extra_destination_prefixes") or []
        if not isinstance(extra, list) or not all(isinstance(p, str) for p in extra):
            extra = []
    return list(prefixes) + list(extra)


def _dst_allowed(dst: str, prefixes: list[str]) -> bool:
    branch = dst.removeprefix("refs/heads/")
    if branch in ("main", "master"):
        return False
    return any(branch.startswith(p) for p in prefixes)


def _changed_paths(cwd: Path, merge_base: str, pushed_sha: str) -> list[str] | None:
    ok, out = _run(["diff", "--no-renames", "--name-only", "-z", merge_base, pushed_sha], cwd)
    if not ok:
        return None
    return [p for p in out.split("\0") if p]


def _merge_base(cwd: Path, pushed_sha: str) -> str | None:
    ok, out = _run(["merge-base", "origin/main", pushed_sha], cwd)
    return out if ok else None


def _is_exempt(paths: list[str], clause: dict | None) -> bool:
    if clause is None:
        return False
    exempt_globs = clause.get("exempt_path_globs") or []
    never_exempt = clause.get("never_exempt_paths") or []
    if not isinstance(exempt_globs, list) or not isinstance(never_exempt, list):
        return False
    for path in paths:
        if any(fnmatch.fnmatchcase(path, str(pattern)) for pattern in never_exempt):
            return False
        if not any(fnmatch.fnmatchcase(path, str(pattern)) for pattern in exempt_globs):
            return False
    return True


def decide_push(worktree: Path, pushed_sha: str) -> Verdict:
    ok, tree = _run(["rev-parse", f"{pushed_sha}^{{tree}}"], worktree)
    if not ok:
        return Verdict("deny", "unresolvable_sha", f"cannot resolve tree for {pushed_sha}")

    merge_base = _merge_base(worktree, pushed_sha)
    if merge_base is not None:
        changed = _changed_paths(worktree, merge_base, pushed_sha)
        clause = _base_ref_clause(worktree)
        if changed is not None and _is_exempt(changed, clause):
            return Verdict("pass", "exempt", "every changed path is exempt")

    record, status = load_record(evidence_path_for(worktree))
    if status != "ok":
        return Verdict("deny", status, f"handoff evidence {status}: rebase onto origin/main and re-run the full tier")

    ok_attest, rule = attests_head(record, head_tree=tree, toplevel=worktree)
    assert rule in ATTEST_RULES
    if ok_attest:
        return Verdict(
            "pass",
            "ok",
            "committed, rebased tree was validated from this worktree",
        )
    if rule == "failed_run":
        return Verdict(
            "warn",
            "failed_run",
            "the pushed tree was validated from this worktree but the full tier failed (identity gate, not a verdict gate)",
        )
    sequence = "commit -> fetch + rebase -> full tier -> --verify-head -> push"
    return Verdict("deny", rule, f"evidence does not attest this tree ({rule}); handoff sequence: {sequence}")


def _decide_delete(parsed: object, prefixes: list[str]) -> Verdict:
    branch = (parsed.dst or "").removeprefix("refs/heads/")
    if branch in ("main", "master"):
        return Verdict("deny", "delete_main", "deleting main or master is human-only")
    if not any(branch.startswith(p) for p in prefixes):
        return Verdict("deny", "delete_non_agent_branch", "deleting a non-agent branch is human-only")
    return Verdict("pass", "delete", "a single agent-branch delete pushes no tree")


def _decide_bare_push(parsed: object, prefixes: list[str], resolved_worktree: Path) -> Verdict:
    ok, push_default = _run(["config", "push.default"], resolved_worktree)
    push_default = push_default if ok else ""
    if push_default not in ("", "simple", "current", "upstream"):
        return Verdict("deny", "bare_push_default", f"push.default={push_default!r} makes a bare push ambiguous")
    remote = parsed.remote or "origin"
    ok, remote_push = _run(["config", f"remote.{remote}.push"], resolved_worktree)
    if ok and remote_push:
        return Verdict("deny", "bare_push_remote_push_set", f"remote.{remote}.push is set")
    ok, remote_mirror = _run(["config", f"remote.{remote}.mirror"], resolved_worktree)
    if ok and remote_mirror.strip().lower() == "true":
        return Verdict("deny", "bare_push_remote_mirror", f"remote.{remote}.mirror is true")
    ok, upstream = _run(["rev-parse", "--symbolic-full-name", "@{push}"], resolved_worktree)
    if not ok or not upstream:
        return Verdict("deny", "bare_push_no_upstream", "@{push} does not resolve")
    dst = upstream.removeprefix(f"refs/remotes/{remote}/")
    if not _dst_allowed(dst, prefixes):
        return Verdict("deny", "destination", f"{dst} is not an agent-prefixed destination")
    ok, head_sha = _run(["rev-parse", "HEAD"], resolved_worktree)
    if not ok:
        return Verdict("deny", "unresolvable_sha", "cannot resolve HEAD")
    return decide_push(resolved_worktree, head_sha)


def _resolve_explicit_dst(parsed: object, resolved_worktree: Path) -> tuple[str | None, Verdict | None]:
    dst = parsed.dst
    if dst is not None:
        return dst, None
    src = parsed.src or "HEAD"
    if src != "HEAD":
        return src, None
    ok, dst = _run(["rev-parse", "--abbrev-ref", "HEAD"], resolved_worktree)
    if not ok or dst == "HEAD":
        return None, Verdict("deny", "unresolvable_branch", "HEAD is detached; cannot resolve a destination branch name")
    return dst, None


def _decide_explicit_push(parsed: object, prefixes: list[str], resolved_worktree: Path) -> Verdict:
    dst, error = _resolve_explicit_dst(parsed, resolved_worktree)
    if error is not None:
        return error
    if not _dst_allowed(dst, prefixes):
        return Verdict("deny", "destination", f"{dst} is not an agent-prefixed destination")

    ok, sha = _run(["rev-parse", parsed.src or "HEAD"], resolved_worktree)
    if not ok:
        return Verdict("deny", "unresolvable_sha", f"cannot resolve {parsed.src}")
    return decide_push(resolved_worktree, sha)


def decide_bash(worktree: Path, parsed: object, payload_cwd: Path) -> Verdict:
    from scripts.session.handoff_push_parse import NonCanonical, ParsedPush

    if isinstance(parsed, NonCanonical):
        return Verdict(
            "deny",
            "non_canonical",
            f"non-canonical push form ({parsed.reason}); run `git push -u origin HEAD` "
            "(or `git -C <worktree> push -u origin HEAD`) as its own tool call; to write text "
            "that contains a push command use the Write tool; a comment or echo that merely "
            "mentions git and push is a known false positive -- drop it",
        )
    assert isinstance(parsed, ParsedPush)

    if parsed.kind == "dry_run":
        return Verdict("pass", "dry_run", "dry run pushes no tree")

    resolved_worktree = worktree
    if parsed.worktree_hint is not None:
        resolved_worktree = (payload_cwd / parsed.worktree_hint).resolve()

    prefixes = destination_prefixes(resolved_worktree)
    if prefixes is None:
        return _UNREADABLE_PREFIXES_VERDICT

    if parsed.kind == "delete":
        return _decide_delete(parsed, prefixes)
    if parsed.kind == "bare_push":
        return _decide_bare_push(parsed, prefixes, resolved_worktree)
    return _decide_explicit_push(parsed, prefixes, resolved_worktree)


def decide_pr(payload_cwd: Path, head: str, base_worktree: Path) -> Verdict:
    if ":" in head:
        return Verdict("deny", "cross_repo_head", "a cross-repo head (owner:branch) is never evaluated")

    prefixes = destination_prefixes(base_worktree)
    if prefixes is None:
        return _UNREADABLE_PREFIXES_VERDICT
    if not _dst_allowed(head, prefixes):
        return Verdict("deny", "destination", f"{head} is not an agent-prefixed destination")

    ok, worktrees_raw = _run(["worktree", "list", "--porcelain"], base_worktree)
    worktree = base_worktree
    if ok:
        current_path = None
        for line in worktrees_raw.splitlines():
            if line.startswith("worktree "):
                current_path = line[len("worktree ") :]
            elif line == f"branch refs/heads/{head}" and current_path is not None:
                worktree = Path(current_path)
                break

    ok, sha = _run(["rev-parse", f"refs/remotes/origin/{head}"], worktree)
    if not ok:
        return Verdict("deny", "unpushed_head", f"push the branch first: refs/remotes/origin/{head} does not resolve")
    return decide_push(worktree, sha)


def decide_remote_write(base_worktree: Path, branch: str, paths: list[str]) -> Verdict:
    if branch in ("main", "master"):
        return Verdict("deny", "destination", "main and master are never a remote-write destination")
    prefixes = destination_prefixes(base_worktree)
    if prefixes is None:
        return _UNREADABLE_PREFIXES_VERDICT
    if not _dst_allowed(branch, prefixes):
        return Verdict("deny", "destination", f"{branch} is not an agent-prefixed destination")
    clause = _base_ref_clause(base_worktree)
    if _is_exempt(paths, clause):
        return Verdict("pass", "exempt", "every written path is exempt")
    return Verdict("deny", "remote_write_not_exempt", "a remote write of non-exempt content is refused")


def _cli_check_push(sha: str, worktree: Path) -> int:
    verdict = decide_push(worktree, sha)
    print(f"{verdict.kind}: {verdict.rule}: {verdict.message}")
    return 1 if verdict.kind == "deny" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.session.handoff_evidence")
    parser.add_argument("--check-push", action="store_true")
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--worktree", default=None)
    args = parser.parse_args(argv)
    if not args.check_push:
        parser.print_help()
        return 1
    worktree = Path(args.worktree) if args.worktree else _common.ROOT
    return _cli_check_push(args.sha, worktree)


if __name__ == "__main__":
    sys.exit(main())
