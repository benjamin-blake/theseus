"""Tests for scripts/ci/branch_cleanup.py -- the branch-cleanup.yml decision logic.

This is the only automation in the repo that deletes remote refs, and a deleted ref is not
recoverable from the caller's side, so the tests below are organised around the two questions that
actually matter: does every HARD GUARD still keep a branch that must not be deleted, and does a
failure anywhere in the enumeration chain stop the run before a single deletion.

No network and no real git/gh: every subprocess call goes through an injected runner, so a command
the tests did not deliberately stub is an AssertionError rather than a silent pass.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest
import yaml

from scripts.ci.branch_cleanup import (
    ACTION_DELETE,
    ACTION_KEEP,
    CLASS_ANCESTOR_OF_MAIN,
    CLASS_EXTRA_BRANCH,
    CLASS_MERGED_PR_HEAD,
    CLASS_UNCLASSIFIED,
    DEFAULT_MIN_AGE_HOURS,
    GUARD_OPEN_PR,
    GUARD_PROTECTED_BRANCH,
    GUARD_UNKNOWN_AGE,
    GUARD_YOUNGER_THAN_MIN_AGE,
    RESULT_DELETED,
    RESULT_DRY_RUN,
    RESULT_KEPT,
    BranchDecision,
    CommandResult,
    decide_branch,
    execute_decisions,
    is_ancestor_of_main,
    list_remote_branches,
    main,
    merged_pr_heads,
    open_pr_heads,
    parse_bool,
    parse_branch_list,
    parse_min_age_hours,
    plan_decisions,
    render_summary,
    subprocess_runner,
    tip_age_hours,
)

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

_OLD_STAMP = "2026-08-01T12:00:00+00:00"  # 600 hours before NOW
_FRESH_STAMP = "2026-08-26T11:00:00+00:00"  # 1 hour before NOW


def _classify(cmd: Sequence[str]) -> str:
    parts = list(cmd)
    if parts[:2] == ["git", "ls-remote"]:
        return "ls-remote"
    if parts[:2] == ["git", "log"]:
        return f"log:{parts[-1]}"
    if parts[:2] == ["git", "merge-base"]:
        return f"ancestor:{parts[3]}"
    if parts[:3] == ["gh", "pr", "list"]:
        return f"pr-list:{parts[parts.index('--state') + 1]}"
    if parts[:2] == ["gh", "api"]:
        return f"delete:{parts[-1].rsplit('/', 1)[-1]}"
    return "unknown:" + " ".join(parts)


class FakeRunner:
    """A programmable runner. An unstubbed command raises rather than defaulting to success."""

    def __init__(self, responses: dict[str, CommandResult]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str]) -> CommandResult:
        parts = list(cmd)
        self.calls.append(parts)
        kind = _classify(parts)
        if kind not in self.responses:
            raise AssertionError(f"unstubbed command {parts!r} (kind {kind!r})")
        return self.responses[kind]

    def kinds(self) -> list[str]:
        return [_classify(call) for call in self.calls]

    def deleted_branches(self) -> list[str]:
        return [kind.split(":", 1)[1] for kind in self.kinds() if kind.startswith("delete:")]


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout)


def _fail(returncode: int = 1, stderr: str = "boom") -> CommandResult:
    return CommandResult(returncode=returncode, stdout="", stderr=stderr)


def _decide(**overrides: object) -> BranchDecision:
    kwargs: dict = {
        "age_hours": 500.0,
        "min_age_hours": 48.0,
        "has_open_pr": False,
        "is_merged_pr_head": False,
        "is_ancestor": False,
        "is_extra": False,
    }
    kwargs.update(overrides)
    branch = str(kwargs.pop("branch", "claude/feature-x"))
    return decide_branch(branch, "sha-x", **kwargs)  # type: ignore[arg-type]


class TestHardGuards:
    """Each guard must keep the branch on its own, even when every delete class also matches."""

    def test_main_is_never_deleted_even_when_every_class_matches(self) -> None:
        decision = _decide(branch="main", is_merged_pr_head=True, is_ancestor=True, is_extra=True)
        assert decision.action == ACTION_KEEP
        assert decision.classification == GUARD_PROTECTED_BRANCH

    def test_open_pr_beats_every_delete_class(self) -> None:
        decision = _decide(has_open_pr=True, is_merged_pr_head=True, is_ancestor=True, is_extra=True)
        assert decision.action == ACTION_KEEP
        assert decision.classification == GUARD_OPEN_PR

    def test_branch_younger_than_min_age_is_kept(self) -> None:
        decision = _decide(age_hours=47.9, min_age_hours=48.0, is_merged_pr_head=True)
        assert decision.action == ACTION_KEEP
        assert decision.classification == GUARD_YOUNGER_THAN_MIN_AGE

    def test_branch_exactly_at_min_age_is_eligible(self) -> None:
        """The floor is exclusive: `<` keeps, `==` does not -- pinned so a refactor cannot flip it."""
        decision = _decide(age_hours=48.0, min_age_hours=48.0, is_merged_pr_head=True)
        assert decision.action == ACTION_DELETE

    def test_unknown_age_is_never_old_enough(self) -> None:
        decision = _decide(age_hours=None, is_merged_pr_head=True, is_ancestor=True, is_extra=True)
        assert decision.action == ACTION_KEEP
        assert decision.classification == GUARD_UNKNOWN_AGE

    def test_extra_branches_does_not_bypass_the_guards(self) -> None:
        """Explicit operator intent widens the candidate set; it never overrides a hard guard."""
        assert _decide(is_extra=True, has_open_pr=True).action == ACTION_KEEP
        assert _decide(is_extra=True, age_hours=1.0).action == ACTION_KEEP
        assert _decide(branch="main", is_extra=True).action == ACTION_KEEP


class TestDeleteClasses:
    def test_merged_pr_head_is_deleted(self) -> None:
        decision = _decide(is_merged_pr_head=True)
        assert decision.action == ACTION_DELETE
        assert decision.classification == CLASS_MERGED_PR_HEAD

    def test_ancestor_of_main_is_deleted(self) -> None:
        decision = _decide(is_ancestor=True)
        assert decision.action == ACTION_DELETE
        assert decision.classification == CLASS_ANCESTOR_OF_MAIN

    def test_extra_branch_is_deleted(self) -> None:
        decision = _decide(is_extra=True)
        assert decision.action == ACTION_DELETE
        assert decision.classification == CLASS_EXTRA_BRANCH

    def test_merged_pr_head_wins_over_ancestor_for_reporting(self) -> None:
        assert _decide(is_merged_pr_head=True, is_ancestor=True).classification == CLASS_MERGED_PR_HEAD

    def test_unmatched_branch_is_kept(self) -> None:
        decision = _decide()
        assert decision.action == ACTION_KEEP
        assert decision.classification == CLASS_UNCLASSIFIED


class TestInputParsing:
    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off", " false "])
    def test_falsey_values_disable_dry_run(self, raw: str) -> None:
        assert parse_bool(raw) is False

    @pytest.mark.parametrize("raw", ["true", "True", "1", "yes", "", None, "garbage"])
    def test_everything_else_stays_in_dry_run(self, raw: str | None) -> None:
        """Fail-safe: an unparseable DRY_RUN must never be read as permission to delete."""
        assert parse_bool(raw) is True

    def test_min_age_hours_parses_a_number(self) -> None:
        assert parse_min_age_hours("48") == 48.0
        assert parse_min_age_hours(" 0.5 ") == 0.5
        assert parse_min_age_hours("0") == 0.0

    @pytest.mark.parametrize("raw", ["", None, "abc", "-1"])
    def test_min_age_hours_falls_back_to_the_default(self, raw: str | None) -> None:
        assert parse_min_age_hours(raw) == DEFAULT_MIN_AGE_HOURS

    def test_branch_list_splits_and_strips(self) -> None:
        assert parse_branch_list(" a , b,\nc ,, ") == ("a", "b", "c")
        assert parse_branch_list("") == ()
        assert parse_branch_list(None) == ()


class TestGitAndGhProbes:
    def test_list_remote_branches_parses_ref_lines(self) -> None:
        stdout = "sha1\trefs/heads/main\nsha2\trefs/heads/claude/foo\nsha3\trefs/tags/v1\ngarbage\n"
        runner = FakeRunner({"ls-remote": _ok(stdout)})
        assert list_remote_branches(runner) == {"main": "sha1", "claude/foo": "sha2"}

    def test_list_remote_branches_returns_none_on_failure(self) -> None:
        """Never a partial or empty map: an unknown branch set must stop the run, not shrink it."""
        assert list_remote_branches(FakeRunner({"ls-remote": _fail()})) is None

    def test_open_and_merged_pr_heads_parse_line_lists(self) -> None:
        runner = FakeRunner({"pr-list:open": _ok("claude/a\n\nclaude/b\n"), "pr-list:merged": _ok("claude/c\n")})
        assert open_pr_heads(runner) == {"claude/a", "claude/b"}
        assert merged_pr_heads(runner) == {"claude/c"}

    def test_pr_head_queries_return_none_on_failure(self) -> None:
        runner = FakeRunner({"pr-list:open": _fail(), "pr-list:merged": _fail()})
        assert open_pr_heads(runner) is None
        assert merged_pr_heads(runner) is None

    def test_tip_age_hours_computes_from_committer_date(self) -> None:
        runner = FakeRunner({"log:old1": _ok(f"{_OLD_STAMP}\n")})
        assert tip_age_hours(runner, "old1", NOW) == pytest.approx(600.0)

    def test_tip_age_hours_treats_a_naive_stamp_as_utc(self) -> None:
        runner = FakeRunner({"log:old1": _ok("2026-08-26T11:00:00\n")})
        assert tip_age_hours(runner, "old1", NOW) == pytest.approx(1.0)

    @pytest.mark.parametrize("response", [_fail(128), _ok(""), _ok("not-a-timestamp")])
    def test_tip_age_hours_is_none_when_git_cannot_answer(self, response: CommandResult) -> None:
        assert tip_age_hours(FakeRunner({"log:x": response}), "x", NOW) is None

    def test_is_ancestor_only_on_a_clean_exit_zero(self) -> None:
        assert is_ancestor_of_main(FakeRunner({"ancestor:a": _ok()}), "a") is True
        assert is_ancestor_of_main(FakeRunner({"ancestor:a": _fail(1)}), "a") is False
        assert is_ancestor_of_main(FakeRunner({"ancestor:a": _fail(128)}), "a") is False


class TestPlanDecisions:
    def test_merged_head_short_circuits_the_ancestor_probe(self) -> None:
        """A branch already classified by a merged PR needs no git merge-base call at all."""
        runner = FakeRunner({"log:sha-m": _ok(_OLD_STAMP)})
        decisions = plan_decisions(
            runner,
            {"claude/merged": "sha-m"},
            open_heads=set(),
            merged_heads={"claude/merged"},
            extra_branches=(),
            min_age_hours=48.0,
            now=NOW,
        )
        assert [d.classification for d in decisions] == [CLASS_MERGED_PR_HEAD]
        assert not any(kind.startswith("ancestor:") for kind in runner.kinds())

    def test_decisions_are_returned_in_branch_name_order(self) -> None:
        runner = FakeRunner(
            {
                "log:sha-a": _ok(_OLD_STAMP),
                "log:sha-b": _ok(_OLD_STAMP),
                "ancestor:sha-a": _fail(1),
                "ancestor:sha-b": _fail(1),
            }
        )
        decisions = plan_decisions(
            runner,
            {"zeta": "sha-b", "alpha": "sha-a"},
            open_heads=set(),
            merged_heads=set(),
            extra_branches=(),
            min_age_hours=48.0,
            now=NOW,
        )
        assert [d.branch for d in decisions] == ["alpha", "zeta"]


class TestExecuteDecisions:
    @staticmethod
    def _delete_decision(branch: str = "claude/gone") -> BranchDecision:
        return BranchDecision(branch, "sha", CLASS_MERGED_PR_HEAD, ACTION_DELETE, "merged", 600.0)

    def test_dry_run_issues_no_gh_call(self) -> None:
        runner = FakeRunner({})
        rows = execute_decisions(runner, [self._delete_decision()], dry_run=True, repo="o/r")
        assert rows == [(self._delete_decision(), RESULT_DRY_RUN)]
        assert runner.calls == []

    def test_live_run_deletes_and_reports(self) -> None:
        runner = FakeRunner({"delete:gone": _ok()})
        rows = execute_decisions(runner, [self._delete_decision("claude/gone")], dry_run=False, repo="o/r")
        assert rows[0][1] == RESULT_DELETED
        assert runner.calls[0] == ["gh", "api", "-X", "DELETE", "repos/o/r/git/refs/heads/claude/gone"]

    def test_live_run_records_a_failed_deletion(self) -> None:
        runner = FakeRunner({"delete:gone": _fail(1)})
        rows = execute_decisions(runner, [self._delete_decision("claude/gone")], dry_run=False, repo="o/r")
        assert rows[0][1].startswith("FAILED")

    def test_kept_decisions_never_reach_gh_even_in_a_live_run(self) -> None:
        keep = BranchDecision("main", "sha", GUARD_PROTECTED_BRANCH, ACTION_KEEP, "protected", 900.0)
        runner = FakeRunner({})
        rows = execute_decisions(runner, [keep], dry_run=False, repo="o/r")
        assert rows == [(keep, RESULT_KEPT)]
        assert runner.calls == []


class TestRenderSummary:
    def test_summary_reports_mode_and_every_row(self) -> None:
        rows = [
            (BranchDecision("main", "s1", GUARD_PROTECTED_BRANCH, ACTION_KEEP, "protected", 900.0), RESULT_KEPT),
            (BranchDecision("claude/x", "s2", CLASS_MERGED_PR_HEAD, ACTION_DELETE, "merged", 600.0), RESULT_DRY_RUN),
        ]
        text = render_summary(rows, dry_run=True)
        assert "DRY RUN (nothing deleted)" in text
        assert "| main | protected-branch | 900.0h | keep | kept |" in text
        assert "| claude/x | merged-pr-head | 600.0h | delete | dry-run |" in text

    def test_unknown_age_renders_as_unknown(self) -> None:
        rows = [(BranchDecision("claude/y", "s", GUARD_UNKNOWN_AGE, ACTION_KEEP, "?", None), RESULT_KEPT)]
        assert "| unknown |" in render_summary(rows, dry_run=False)

    def test_live_mode_is_labelled_distinctly(self) -> None:
        assert "LIVE" in render_summary([], dry_run=False)


def _full_repo_runner(**overrides: CommandResult) -> FakeRunner:
    """A repo with: main, an open-PR branch, a merged branch, a fresh branch and an unmatched one."""
    responses: dict[str, CommandResult] = {
        "ls-remote": _ok(
            "s-main\trefs/heads/main\n"
            "s-open\trefs/heads/claude/open\n"
            "s-merged\trefs/heads/claude/merged\n"
            "s-fresh\trefs/heads/claude/fresh\n"
            "s-other\trefs/heads/claude/other\n"
        ),
        "pr-list:open": _ok("claude/open\n"),
        "pr-list:merged": _ok("claude/merged\n"),
        "log:s-main": _ok(_OLD_STAMP),
        "log:s-open": _ok(_OLD_STAMP),
        "log:s-merged": _ok(_OLD_STAMP),
        "log:s-fresh": _ok(_FRESH_STAMP),
        "log:s-other": _ok(_OLD_STAMP),
        "ancestor:s-main": _ok(),
        "ancestor:s-open": _fail(1),
        "ancestor:s-fresh": _fail(1),
        "ancestor:s-other": _fail(1),
        "delete:merged": _ok(),
    }
    responses.update(overrides)
    return FakeRunner(responses)


@pytest.fixture
def cleanup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GH_REPO", "example-org/example-repo")
    monkeypatch.setenv("MIN_AGE_HOURS", "48")
    monkeypatch.setenv("EXTRA_BRANCHES", "")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    return summary


class TestMainDryRunVersusLive:
    def test_dry_run_decides_everything_and_deletes_nothing(self, cleanup_env: Path) -> None:
        runner = _full_repo_runner()
        assert main(runner=runner, now=NOW) == 0
        assert runner.deleted_branches() == []
        summary = cleanup_env.read_text(encoding="utf-8")
        assert "DRY RUN (nothing deleted)" in summary
        assert "| claude/merged | merged-pr-head |" in summary
        assert "| main | protected-branch |" in summary

    def test_live_run_deletes_only_the_eligible_branch(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        runner = _full_repo_runner()
        assert main(runner=runner, now=NOW) == 0
        assert runner.deleted_branches() == ["merged"]
        summary = cleanup_env.read_text(encoding="utf-8")
        assert "LIVE" in summary
        assert "| claude/open | open-pr | 600.0h | keep | kept |" in summary
        assert "| claude/fresh | younger-than-min-age | 1.0h | keep | kept |" in summary
        assert "| claude/other | unclassified | 600.0h | keep | kept |" in summary

    def test_extra_branches_widens_the_candidate_set_in_a_live_run(
        self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path
    ) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("EXTRA_BRANCHES", "claude/other,claude/open,main")
        runner = _full_repo_runner(**{"delete:other": _ok()})
        assert main(runner=runner, now=NOW) == 0
        # claude/open (open PR) and main (protected) are named explicitly and still survive.
        assert sorted(runner.deleted_branches()) == ["merged", "other"]

    def test_min_age_floor_keeps_a_named_but_young_branch(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("EXTRA_BRANCHES", "claude/fresh")
        runner = _full_repo_runner()
        assert main(runner=runner, now=NOW) == 0
        assert runner.deleted_branches() == ["merged"]
        assert "| claude/fresh | younger-than-min-age | 1.0h | keep | kept |" in cleanup_env.read_text(encoding="utf-8")

    def test_lowering_min_age_hours_releases_that_same_branch(
        self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path
    ) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("EXTRA_BRANCHES", "claude/fresh")
        monkeypatch.setenv("MIN_AGE_HOURS", "0")
        runner = _full_repo_runner(**{"delete:fresh": _ok()})
        assert main(runner=runner, now=NOW) == 0
        assert sorted(runner.deleted_branches()) == ["fresh", "merged"]


class TestMainFailureHandling:
    def test_ls_remote_failure_aborts_before_any_deletion(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        runner = FakeRunner({"ls-remote": _fail(128)})
        assert main(runner=runner, now=NOW) == 1
        assert runner.deleted_branches() == []
        assert "[BRANCH-CLEANUP] FAILURE" in cleanup_env.read_text(encoding="utf-8")

    def test_open_pr_query_failure_aborts_before_any_deletion(
        self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path
    ) -> None:
        """The open-PR guard is only as good as its query: a failed query must never read as 'none'."""
        monkeypatch.setenv("DRY_RUN", "false")
        runner = _full_repo_runner(**{"pr-list:open": _fail()})
        assert main(runner=runner, now=NOW) == 1
        assert runner.deleted_branches() == []
        assert "open-PR hard guard cannot be evaluated" in cleanup_env.read_text(encoding="utf-8")

    def test_merged_pr_query_failure_aborts_before_any_deletion(
        self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path
    ) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        runner = _full_repo_runner(**{"pr-list:merged": _fail()})
        assert main(runner=runner, now=NOW) == 1
        assert runner.deleted_branches() == []

    def test_deletion_failure_is_reported_and_reds_the_run(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        runner = _full_repo_runner(**{"delete:merged": _fail(422)})
        assert main(runner=runner, now=NOW) == 1
        summary = cleanup_env.read_text(encoding="utf-8")
        assert "FAILED (exit 422)" in summary
        assert "deletion failed for: claude/merged" in summary

    def test_live_run_without_a_repo_aborts(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.delenv("GH_REPO", raising=False)
        runner = _full_repo_runner()
        assert main(runner=runner, now=NOW) == 1
        assert runner.calls == []

    def test_dry_run_without_a_repo_still_reports(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        """No repo is only fatal when something would actually be deleted."""
        monkeypatch.delenv("GH_REPO", raising=False)
        runner = _full_repo_runner()
        assert main(runner=runner, now=NOW) == 0

    def test_missing_step_summary_env_is_not_fatal(self, monkeypatch: pytest.MonkeyPatch, cleanup_env: Path) -> None:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        runner = _full_repo_runner()
        assert main(runner=runner, now=NOW) == 0


class TestSubprocessRunner:
    """The default runner never raises on a failing or missing command -- callers read returncode."""

    def test_non_zero_exit_is_returned_not_raised(self) -> None:
        result = subprocess_runner([sys.executable, "-c", "import sys; sys.exit(3)"])
        assert result.returncode == 3

    def test_stdout_is_captured_as_text(self) -> None:
        result = subprocess_runner([sys.executable, "-c", "print('hello')"])
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_missing_binary_yields_a_result_not_an_exception(self) -> None:
        result = subprocess_runner(["definitely-not-a-real-binary-9f3a"])
        assert result.returncode == 127
        assert result.stderr

    def test_timeout_yields_a_result_not_an_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="git", timeout=120)

        monkeypatch.setattr(subprocess, "run", _raise)
        assert subprocess_runner(["git", "status"]).returncode == 127


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "branch-cleanup.yml"

PRODUCTION_ARGV = ("bash",)
HOSTILE_ARGV = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")
ARGVS = {"production": PRODUCTION_ARGV, "hostile": HOSTILE_ARGV}

# Shims for the two binaries the module shells out to. python3 is deliberately NOT shimmed: the
# point of this test is that the real workflow body reaches the real decision module.
_GIT_SHIM = """#!{python}
import sys

_REFS = (
    "s-main\\trefs/heads/main\\n"
    "s-merged\\trefs/heads/claude/merged\\n"
)

argv = sys.argv[1:]
if argv[:2] == ["ls-remote", "--heads"]:
    sys.stdout.write(_REFS)
elif argv[:1] == ["log"]:
    sys.stdout.write("2026-01-01T00:00:00+00:00\\n")
elif argv[:2] == ["merge-base", "--is-ancestor"]:
    sys.exit(0 if argv[2] == "s-main" else 1)
else:
    sys.stderr.write("git shim: unrecognised argv %r\\n" % (argv,))
    sys.exit(99)
"""

_GH_SHIM = """#!{python}
import sys

argv = sys.argv[1:]
if argv[:2] == ["pr", "list"]:
    state = argv[argv.index("--state") + 1]
    sys.stdout.write("claude/merged\\n" if state == "merged" else "")
else:
    sys.stderr.write("gh shim: unrecognised argv %r\\n" % (argv,))
    sys.exit(99)
"""


class TestRealWorkflowBodyWiring:
    """Production fidelity: parse the REAL workflow YAML, extract its actual run: body and EXECUTE
    it (never a substring assertion), so the workflow -> shell delegate -> decision module chain is
    proven end to end. Parameterised over both argvs for the same reason
    tests/test_pr_conflict_signal_wiring.py is: PRODUCTION_ARGV is today's real child-bash
    invocation, HOSTILE_ARGV is the literal GitHub run-step invocation that would catch a
    re-inlining regression."""

    @staticmethod
    def _shim_env(tmp_path: Path, summary: Path) -> dict[str, str]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name, source in (("git", _GIT_SHIM), ("gh", _GH_SHIM)):
            path = bin_dir / name
            path.write_text(source.format(python=sys.executable), encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["DRY_RUN"] = "true"
        env["MIN_AGE_HOURS"] = "48"
        env["EXTRA_BRANCHES"] = ""
        env["GH_TOKEN"] = "stub-token"
        env["GH_REPO"] = "example-org/example-repo"
        env["GITHUB_STEP_SUMMARY"] = str(summary)
        return env

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_real_workflow_body_reaches_the_decision_module(self, tmp_path: Path, argv_name: str) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job = workflow["jobs"]["cleanup"]
        delegating_step = next(step for step in job["steps"] if isinstance(step.get("run"), str))

        assert "shell" not in delegating_step
        assert "shell" not in job
        assert "shell" not in workflow.get("defaults", {}).get("run", {})

        body_file = tmp_path / "run_body.sh"
        body_file.write_text(delegating_step["run"], encoding="utf-8")
        summary = tmp_path / "step_summary.md"

        # cwd=ROOT: the run body's path is repo-root-relative, exactly as it is in the real job.
        result = subprocess.run(
            [*ARGVS[argv_name], str(body_file)],
            cwd=str(ROOT),
            env=self._shim_env(tmp_path, summary),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )

        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "DRY RUN (nothing deleted)" in result.stdout
        assert "| main | protected-branch |" in result.stdout
        assert "| claude/merged | merged-pr-head |" in result.stdout
        assert "| claude/merged | merged-pr-head |" in summary.read_text(encoding="utf-8")
