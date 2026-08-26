"""Wiring tests for scripts/ci/dependabot_stranded_sweep.sh (WS3 dependabot-automation-cleanup).

The workflow step that delegates to this script declares no `shell:` key, so GitHub runs the step's
own run: body -- just `bash scripts/ci/dependabot_stranded_sweep.sh` -- as
"bash --noprofile --norc -e -o pipefail {0}". That OUTER invocation inherits errexit, but its one
command spawns a CHILD bash to run the script, and a child bash does NOT inherit its parent's shell
options (SHELLOPTS is unexported). So the script runs WITHOUT inherited errexit in production, and
every gh call site has to handle its own exit status.

Every behavioural case below is therefore parameterised over BOTH argvs, exactly as
tests/test_pr_conflict_signal_wiring.py is: PRODUCTION_ARGV (a plain child `bash <script>`, errexit
off -- today's real invocation) and HOSTILE_ARGV (the literal GitHub run-step invocation, errexit
on -- the superset that would catch a regression if this body were ever re-inlined).

The assertions are about the DECISION the sweep reaches per scenario (did it update the branch, did
it fall back to the rebase comment, did it leave a clean PR alone), never about a substring of the
script.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci" / "dependabot_stranded_sweep.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "dependabot-stranded.yml"

PRODUCTION_ARGV = ("bash",)
HOSTILE_ARGV = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")
ARGVS = {"production": PRODUCTION_ARGV, "hostile": HOSTILE_ARGV}

_OLD_CREATED_AT = "2026-01-06T06:56:00Z"

# A gh shim keyed on call "kind" (list / update:<n> / comment:<n>), driven entirely by env vars:
# GH_SHIM_CONTROL_FILE (a {kind: response | [response, ...]} JSON map), GH_SHIM_LOG_FILE (one
# "<kind>\t<argv>" line per invocation), GH_SHIM_STATE_DIR (per-kind call counters, so a list of
# responses is consumed one per successive call -- the last entry repeats once exhausted). An
# unrecognised call kind fails loudly (exit 99) rather than silently succeeding, so a gap in a
# test's control map can never masquerade as a passing scenario.
_GH_SHIM = """#!{python}
import json
import os
import sys
from pathlib import Path


def _classify(argv):
    if len(argv) >= 2 and argv[0] == "pr":
        sub = argv[1]
        if sub == "list":
            return "list"
        if sub == "update-branch" and len(argv) > 2:
            return f"update:{{argv[2]}}"
        if sub == "comment" and len(argv) > 2:
            return f"comment:{{argv[2]}}"
    return "unknown:" + " ".join(argv)


def main() -> int:
    argv = sys.argv[1:]
    control = json.loads(Path(os.environ["GH_SHIM_CONTROL_FILE"]).read_text(encoding="utf-8"))
    kind = _classify(argv)
    with open(os.environ["GH_SHIM_LOG_FILE"], "a", encoding="utf-8") as fh:
        fh.write(kind + "\\t" + " ".join(argv) + "\\n")

    responses = control.get(kind)
    if responses is None:
        print(f"gh shim: unrecognised call kind {{kind!r}} for argv {{argv!r}}", file=sys.stderr)
        return 99

    if isinstance(responses, list):
        state_dir = Path(os.environ["GH_SHIM_STATE_DIR"])
        counter_path = state_dir / (kind.replace(":", "_").replace("/", "_") + ".count")
        idx = int(counter_path.read_text()) if counter_path.exists() else 0
        counter_path.write_text(str(idx + 1))
        response = responses[min(idx, len(responses) - 1)]
    else:
        response = responses

    stdout = response.get("stdout", "")
    stderr = response.get("stderr", "")
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return int(response.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
"""


def _pr_row(number: str, title: str, merge_state: str, created_at: str = _OLD_CREATED_AT, auto_merge: str = "no") -> str:
    """One line of the TSV `gh pr list --jq` projection the sweep consumes."""
    return "\t".join([number, title, merge_state, created_at, auto_merge]) + "\n"


class _Harness:
    """A prepared dependabot_stranded_sweep.sh invocation: shimmed gh on PATH, fast retry sleeps."""

    def __init__(self, tmp_path: Path, control: dict) -> None:
        self.tmp_path = tmp_path
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        self.workdir = tmp_path / "work"
        self.workdir.mkdir(exist_ok=True)
        state_dir = tmp_path / "state"
        state_dir.mkdir(exist_ok=True)
        self.log_file = tmp_path / "gh_calls.log"
        self.log_file.write_text("", encoding="utf-8")
        self.step_summary = tmp_path / "step_summary.md"

        gh_path = bin_dir / "gh"
        gh_path.write_text(_GH_SHIM.format(python=sys.executable), encoding="utf-8")
        gh_path.chmod(gh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        control_file = tmp_path / "control.json"
        control_file.write_text(json.dumps(control), encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["GH_TOKEN"] = "stub-token"
        env["GH_REPO"] = "example-org/example-repo"
        env["GH_SHIM_CONTROL_FILE"] = str(control_file)
        env["GH_SHIM_LOG_FILE"] = str(self.log_file)
        env["GH_SHIM_STATE_DIR"] = str(state_dir)
        env["GITHUB_STEP_SUMMARY"] = str(self.step_summary)
        env["DEPENDABOT_STRANDED_RETRY_SLEEP"] = "0"
        self.env = env

    def run(
        self, argv: tuple[str, ...], script: Path | None = None, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*argv, str(script or SCRIPT)],
            cwd=str(cwd or self.workdir),
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )

    @property
    def calls(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for line in self.log_file.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                kind, argv_text = line.split("\t", 1)
                pairs.append((kind, argv_text))
        return pairs

    def call_count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    def comment_bodies(self, number: str) -> list[str]:
        return [argv for kind, argv in self.calls if kind == f"comment:{number}"]

    @property
    def summary_text(self) -> str:
        return self.step_summary.read_text(encoding="utf-8") if self.step_summary.exists() else ""


class TestArgvFidelity:
    """The harness must reproduce each named invocation's errexit state faithfully -- guards
    against a vacuous suite (mirrors tests/test_pr_conflict_signal_wiring.py's own such class)."""

    def test_hostile_argv_is_the_documented_github_run_step_invocation(self) -> None:
        assert HOSTILE_ARGV == ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")

    def test_production_argv_has_no_inherited_errexit(self, tmp_path: Path) -> None:
        probe = tmp_path / "probe.sh"
        probe.write_text("set -uo pipefail\nfalse\necho REACHED\n", encoding="utf-8")
        result = subprocess.run([*PRODUCTION_ARGV, str(probe)], capture_output=True, text=True, check=False)
        assert "REACHED" in result.stdout

    def test_hostile_argv_delivers_errexit(self, tmp_path: Path) -> None:
        probe = tmp_path / "probe.sh"
        probe.write_text("set -uo pipefail\nfalse\necho REACHED\n", encoding="utf-8")
        result = subprocess.run([*HOSTILE_ARGV, str(probe)], capture_output=True, text=True, check=False)
        assert "REACHED" not in result.stdout


class TestBehindPrIsUpdated:
    """The pathology the sweep exists for: a BEHIND PR never re-runs CI on its own, because
    nothing pushes to its branch. update-branch is what fires the synchronize event."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_behind_pr_gets_update_branch(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("101", "Bump sympy", "BEHIND")},
            "update:101": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("update:101") == 1
        assert harness.comment_bodies("101") == []
        assert result.returncode == 0
        assert "| #101 | Bump sympy |" in harness.summary_text
        assert "| update-branch |" in harness.summary_text

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_dirty_pr_also_gets_update_branch_attempted_first(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("102", "Bump ruff", "DIRTY")},
            "update:102": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("update:102") == 1
        assert result.returncode == 0


class TestRebaseFallback:
    """A DIRTY branch cannot be resolved by update-branch; only dependabot can recreate it."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_update_branch_failure_falls_back_to_a_rebase_comment(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("103", "Bump boto3", "DIRTY")},
            "update:103": {"exit_code": 1, "stdout": "", "stderr": "merge conflict"},
            "comment:103": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("update:103") == 1
        bodies = harness.comment_bodies("103")
        assert len(bodies) == 1
        assert "@dependabot rebase" in bodies[0]
        assert result.returncode == 0
        assert "| rebase-comment |" in harness.summary_text

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_comment_fallback_is_retried_then_recorded_as_failed(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("104", "Bump pysr", "BEHIND")},
            "update:104": {"exit_code": 1, "stdout": "", "stderr": "no"},
            "comment:104": {"exit_code": 1, "stdout": "", "stderr": "rate limited"},
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("comment:104") == 3
        assert "| FAILED |" in harness.summary_text
        assert "[DEPENDABOT-STRANDED] FAILURE" in result.stderr
        # A per-PR failure is reported, never a red run: only a total gh failure exits non-zero.
        assert result.returncode == 0

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_comment_fallback_recovers_within_the_retry_bound(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("105", "Bump networkx", "BEHIND")},
            "update:105": {"exit_code": 1, "stdout": ""},
            "comment:105": [
                {"exit_code": 1, "stdout": "", "stderr": "transient"},
                {"exit_code": 0, "stdout": ""},
            ],
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("comment:105") == 2
        assert "| rebase-comment |" in harness.summary_text
        assert result.returncode == 0


class TestCleanPrIsLeftAlone:
    """Everything that is not BEHIND or DIRTY is reported and untouched -- BLOCKED in particular
    is a code-owner wait that updating the branch would not change."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    @pytest.mark.parametrize("merge_state", ["CLEAN", "BLOCKED", "UNSTABLE", "UNKNOWN"])
    def test_no_action_taken(self, tmp_path: Path, argv_name: str, merge_state: str) -> None:
        control = {"list": {"exit_code": 0, "stdout": _pr_row("106", "Bump pip-tools", merge_state)}}
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("update:106") == 0
        assert harness.comment_bodies("106") == []
        assert result.returncode == 0
        assert f"| {merge_state} |" in harness.summary_text
        assert "| none |" in harness.summary_text


class TestStepSummaryTable:
    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_table_header_and_one_row_per_pr(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {
                "exit_code": 0,
                "stdout": (
                    _pr_row("201", "Bump a", "CLEAN", auto_merge="yes")
                    + _pr_row("202", "Bump b", "BEHIND")
                    + _pr_row("203", "Bump c", "BLOCKED")
                ),
            },
            "update:202": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        harness.run(ARGVS[argv_name])
        summary = harness.summary_text
        assert "| PR | Title | Age (days) | Merge state | Auto-merge | Action |" in summary
        for number in ("201", "202", "203"):
            assert f"| #{number} |" in summary
        assert "| yes |" in summary

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_age_days_is_computed_from_created_at(self, tmp_path: Path, argv_name: str) -> None:
        control = {"list": {"exit_code": 0, "stdout": _pr_row("204", "Bump d", "CLEAN")}}
        harness = _Harness(tmp_path, control)
        harness.run(ARGVS[argv_name])
        row = next(line for line in harness.summary_text.splitlines() if line.startswith("| #204 "))
        age = row.split("|")[3].strip()
        assert re.fullmatch(r"-?\d+", age), row
        # Derived from the same createdAt against the current clock rather than pinned to a literal,
        # so this asserts the arithmetic ran without going stale as the fixture PR ages. The 1-day
        # tolerance absorbs a day boundary crossed between the shell's `date` and this comparison.
        created = datetime(2026, 1, 6, 6, 56, tzinfo=timezone.utc)
        expected = int((datetime.now(timezone.utc) - created).total_seconds() // 86400)
        assert abs(int(age) - expected) <= 1, f"{age!r} is not the age of {_OLD_CREATED_AT}"

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_unparseable_created_at_degrades_to_a_question_mark(self, tmp_path: Path, argv_name: str) -> None:
        """Age is reporting-only, so a bad timestamp must never abort the sweep."""
        control = {"list": {"exit_code": 0, "stdout": _pr_row("205", "Bump e", "CLEAN", created_at="not-a-date")}}
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert "| ? |" in harness.summary_text
        assert result.returncode == 0

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_a_pipe_in_a_title_does_not_break_the_table(self, tmp_path: Path, argv_name: str) -> None:
        control = {"list": {"exit_code": 0, "stdout": _pr_row("206", "Bump a|b", "CLEAN")}}
        harness = _Harness(tmp_path, control)
        harness.run(ARGVS[argv_name])
        row = next(line for line in harness.summary_text.splitlines() if line.startswith("| #206 "))
        # Six columns means seven UNESCAPED cell separators; the title's own pipe is escaped and
        # must not be one of them, or the row silently gains a seventh column in the rendered table.
        assert len(re.findall(r"(?<!\\)\|", row)) == 7, row
        assert "a\\|b" in row

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_empty_backlog_reports_and_exits_zero(self, tmp_path: Path, argv_name: str) -> None:
        control = {"list": {"exit_code": 0, "stdout": ""}}
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert "No open dependabot PRs." in harness.summary_text
        assert result.returncode == 0


class TestSweepContinuationAndExitStatus:
    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_a_failure_on_the_first_pr_still_sweeps_the_second(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("301", "Bump x", "DIRTY") + _pr_row("302", "Bump y", "BEHIND")},
            "update:301": {"exit_code": 1, "stdout": ""},
            "comment:301": {"exit_code": 1, "stdout": "", "stderr": "boom"},
            "update:302": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("update:302") == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_pr_list_failure_is_the_only_non_zero_exit(self, tmp_path: Path, argv_name: str) -> None:
        control = {"list": {"exit_code": 1, "stdout": "", "stderr": "gh: rate limited"}}
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("list") == 3
        assert result.returncode != 0
        assert "[DEPENDABOT-STRANDED] FAILURE" in harness.summary_text

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_pr_list_recovers_within_the_retry_bound(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "list": [
                {"exit_code": 1, "stdout": "", "stderr": "transient"},
                {"exit_code": 0, "stdout": _pr_row("303", "Bump z", "BEHIND")},
            ],
            "update:303": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("list") == 2
        assert harness.call_count("update:303") == 1
        assert result.returncode == 0


class TestRealWorkflowBodyWiring:
    """Production fidelity: parse the REAL workflow YAML, extract its actual run: body, and EXECUTE
    that body (never a substring assertion) under the argv the YAML implies (no `shell:` key
    anywhere on the step/job/workflow -> GitHub's hostile default run-step invocation)."""

    def test_real_workflow_body_reaches_delegate_and_sweeps(self, tmp_path: Path) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job = workflow["jobs"]["sweep"]
        delegating_step = next(step for step in job["steps"] if isinstance(step.get("run"), str))
        run_body = delegating_step["run"]

        assert "shell" not in delegating_step
        assert "shell" not in job
        assert "shell" not in workflow.get("defaults", {}).get("run", {})

        body_file = tmp_path / "run_body.sh"
        body_file.write_text(run_body, encoding="utf-8")

        control = {
            "list": {"exit_code": 0, "stdout": _pr_row("401", "Bump wired", "BEHIND")},
            "update:401": {"exit_code": 0, "stdout": ""},
        }
        harness = _Harness(tmp_path, control)
        # cwd=ROOT: the run body's path is repo-root-relative, exactly as it is in the real job
        # (actions/checkout puts the runner's cwd at the repo root before this step executes).
        result = harness.run(HOSTILE_ARGV, script=body_file, cwd=ROOT)

        assert harness.call_count("update:401") == 1, (
            f"the real workflow run: body ({run_body!r}) did not resolve the delegate and complete "
            f"the sweep. stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert result.returncode == 0
