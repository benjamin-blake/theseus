"""Wiring tests for scripts/ci/dependabot_auto_merge.sh (dependabot-automation-cleanup WS2).

The workflow step that delegates to this script declares no `shell:` key, so GitHub runs the
step's own run: body -- just `bash scripts/ci/dependabot_auto_merge.sh` -- as
"bash --noprofile --norc -e -o pipefail {0}". That OUTER invocation inherits errexit, but its one
command spawns a CHILD bash process to run this script, and a child bash does NOT inherit its
parent's shell options (SHELLOPTS is unexported). So THIS script runs WITHOUT inherited errexit in
production -- a failed `gh pr merge` yields a non-zero status that silently falls through unless
the call site checks it explicitly.

Every behavioural case below is therefore parameterised over BOTH argvs: PRODUCTION_ARGV (a plain
child `bash <script>`, errexit off -- today's real invocation) and HOSTILE_ARGV (the literal
GitHub run-step invocation, errexit on -- a deliberately hostile superset that is what would catch
a regression if this body were ever re-inlined). Neither is redundant: dropping PRODUCTION_ARGV
would make these tests vacuous with respect to today's actual behaviour, and dropping HOSTILE_ARGV
would leave the re-inlining regression unguarded.

The assertions are about the DECISION the policy engine reaches -- whether `gh pr merge` is
invoked at all, and with exactly which argv -- never about a substring of the script.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci" / "dependabot_auto_merge.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"

PRODUCTION_ARGV = ("bash",)
HOSTILE_ARGV = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")
ARGVS = {"production": PRODUCTION_ARGV, "hostile": HOSTILE_ARGV}

PR_URL = "https://github.com/example-org/example-repo/pull/123"
PR_NUMBER = "123"
EXPECTED_MERGE_ARGV = f"pr merge --auto --squash {PR_URL}"

PATCH_UPDATE = "version-update:semver-patch"
MINOR_UPDATE = "version-update:semver-minor"
MAJOR_UPDATE = "version-update:semver-major"

FAILURE_MARKER = "[DEPENDABOT-AUTO-MERGE] FAILURE"

# A gh shim keyed on call "kind" (only "merge" is legitimate for this script), driven entirely by
# env vars: GH_SHIM_CONTROL_FILE (a {kind: response | [response, ...]} JSON map), GH_SHIM_LOG_FILE
# (one "<kind>\t<argv>" line per invocation), GH_SHIM_STATE_DIR (per-kind call counters, so a list
# of responses is consumed one per successive call -- the last entry repeats once exhausted). An
# unrecognised call kind fails loudly (exit 99) rather than silently succeeding, so a gap in a
# test's control map can never masquerade as a passing scenario.
_GH_SHIM = """#!{python}
import json
import os
import sys
from pathlib import Path


def _classify(argv):
    if len(argv) >= 2 and argv[0] == "pr" and argv[1] == "merge":
        return "merge"
    return "unknown:" + " ".join(argv)


def main() -> int:
    argv = sys.argv[1:]
    control = json.loads(Path(os.environ["GH_SHIM_CONTROL_FILE"]).read_text(encoding="utf-8"))
    kind = _classify(argv)
    with open(os.environ["GH_SHIM_LOG_FILE"], "a", encoding="utf-8") as fh:
        fh.write(kind + "\\t" + " ".join(argv) + "\\n")

    responses = control.get(kind)
    if responses is None:
        sys.stderr.write("gh shim: unrecognised call kind " + repr(kind) + "\\n")
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

_MERGE_OK = {"merge": {"exit_code": 0, "stdout": ""}}
_MERGE_FAILS = {"merge": {"exit_code": 1, "stdout": "", "stderr": "gh: auto-merge is not enabled"}}
# No "merge" key at all: any gh invocation exits 99, so a scenario that must NOT merge cannot pass
# by accident -- the shim itself would red the run if the policy engine reached gh.
_MERGE_FORBIDDEN: dict[str, object] = {}


class _Harness:
    """A prepared dependabot_auto_merge.sh invocation: shimmed gh on PATH, fast retry sleeps."""

    def __init__(self, tmp_path: Path, control: dict, metadata: dict[str, str]) -> None:
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
        env["GH_SHIM_CONTROL_FILE"] = str(control_file)
        env["GH_SHIM_LOG_FILE"] = str(self.log_file)
        env["GH_SHIM_STATE_DIR"] = str(state_dir)
        env["GITHUB_STEP_SUMMARY"] = str(self.step_summary)
        env["DEPENDABOT_AUTO_MERGE_RETRY_SLEEP"] = "0"
        env["PR_URL"] = PR_URL
        env["PR_NUMBER"] = PR_NUMBER
        env["PACKAGE_ECOSYSTEM"] = "pip"
        env["UPDATE_TYPE"] = ""
        env["DEPENDENCY_NAMES"] = ""
        env.update(metadata)
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
            check=False,
            timeout=60,
        )

    @property
    def calls(self) -> list[tuple[str, str]]:
        if not self.log_file.exists():
            return []
        pairs = []
        for line in self.log_file.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                kind, argv_text = line.split("\t", 1)
                pairs.append((kind, argv_text))
        return pairs

    def call_count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)

    @property
    def summary_text(self) -> str:
        return self.step_summary.read_text(encoding="utf-8") if self.step_summary.exists() else ""


def _harness(tmp_path: Path, control: dict, **metadata: str) -> _Harness:
    return _Harness(tmp_path, control, metadata)


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
        assert result.returncode == 0

    def test_hostile_argv_delivers_errexit(self, tmp_path: Path) -> None:
        probe = tmp_path / "probe.sh"
        probe.write_text("set -uo pipefail\nfalse\necho REACHED\n", encoding="utf-8")
        result = subprocess.run([*HOSTILE_ARGV, str(probe)], capture_output=True, text=True, check=False)
        assert "REACHED" not in result.stdout
        assert result.returncode != 0

    def test_shim_fails_loudly_on_an_unmapped_gh_call(self, tmp_path: Path) -> None:
        """_MERGE_FORBIDDEN is only a real guard if an unmapped gh call is an error, not a no-op."""
        harness = _harness(tmp_path, _MERGE_FORBIDDEN, UPDATE_TYPE=MINOR_UPDATE, DEPENDENCY_NAMES="sympy")
        result = harness.run(PRODUCTION_ARGV)
        assert harness.call_count("merge") == 3
        assert result.returncode != 0


class TestAllowedUpdateTypesArmAutoMerge:
    """Gate 1's allow-branch: patch and minor bumps arm GitHub-native auto-merge, and the argv is
    exactly `gh pr merge --auto --squash <PR_URL>` -- --auto (never a direct merge) is what keeps
    the required checks in the loop, and --squash is the repo's merge method."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    @pytest.mark.parametrize("update_type", [MINOR_UPDATE, PATCH_UPDATE])
    def test_allowed_update_type_invokes_gh_pr_merge_with_exact_argv(
        self, tmp_path: Path, argv_name: str, update_type: str
    ) -> None:
        harness = _harness(tmp_path, _MERGE_OK, UPDATE_TYPE=update_type, DEPENDENCY_NAMES="sympy")
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == [("merge", EXPECTED_MERGE_ARGV)], f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert result.returncode == 0
        assert FAILURE_MARKER not in harness.summary_text

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_grouped_minor_pip_bump_arms_auto_merge(self, tmp_path: Path, argv_name: str) -> None:
        """The common shape: .github/dependabot.yml groups minor+patch, so a pip PR carries several
        dependency names at once and none of them is denied."""
        harness = _harness(
            tmp_path,
            _MERGE_OK,
            UPDATE_TYPE=MINOR_UPDATE,
            DEPENDENCY_NAMES="boto3, networkx, sympy",
        )
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == [("merge", EXPECTED_MERGE_ARGV)]
        assert result.returncode == 0


class TestRejectedUpdateTypesNeverMerge:
    """Gate 1's deny-branch: a major bump, or a bump fetch-metadata could not classify, is left
    for human review and for the stranded sweep -- and exits 0, because "not auto-merged" is a
    legitimate outcome, not a failure."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_major_update_type_never_invokes_gh(self, tmp_path: Path, argv_name: str) -> None:
        harness = _harness(tmp_path, _MERGE_FORBIDDEN, UPDATE_TYPE=MAJOR_UPDATE, DEPENDENCY_NAMES="actions/checkout")
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == []
        assert result.returncode == 0
        assert FAILURE_MARKER not in harness.summary_text

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_empty_update_type_never_invokes_gh(self, tmp_path: Path, argv_name: str) -> None:
        harness = _harness(tmp_path, _MERGE_FORBIDDEN, UPDATE_TYPE="", DEPENDENCY_NAMES="")
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == []
        assert result.returncode == 0

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_unrecognised_update_type_never_invokes_gh(self, tmp_path: Path, argv_name: str) -> None:
        harness = _harness(tmp_path, _MERGE_FORBIDDEN, UPDATE_TYPE="direct:production", DEPENDENCY_NAMES="ruff")
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == []
        assert result.returncode == 0


class TestLockstepDenylistNeverMerges:
    """Gate 2: duckdb / DuckLake move in lockstep with the catalog version SSOT, so a bump of
    either is never auto-merged even when its semver class is allowed -- including when it is one
    name among many in a grouped PR, and regardless of case."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    @pytest.mark.parametrize(
        "dependency_names",
        [
            "duckdb",
            "ducklake",
            "boto3, duckdb, sympy",
            "boto3\nducklake\nsympy",
            "DuckDB",
            "boto3, DuckLake",
        ],
    )
    def test_denied_dependency_never_invokes_gh(self, tmp_path: Path, argv_name: str, dependency_names: str) -> None:
        harness = _harness(tmp_path, _MERGE_FORBIDDEN, UPDATE_TYPE=MINOR_UPDATE, DEPENDENCY_NAMES=dependency_names)
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == []
        assert result.returncode == 0
        assert "lockstep" in harness.summary_text


class TestBoundedRetryAndFailureMarker:
    """Gate 3's failure handling: a terminal `gh pr merge` failure (e.g. the repo-level Allow
    auto-merge toggle is off) is retried a bounded number of times, then surfaced as a non-zero
    exit plus a greppable $GITHUB_STEP_SUMMARY marker -- never a silent no-op."""

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_repeated_merge_failure_retries_then_exits_nonzero_with_marker(self, tmp_path: Path, argv_name: str) -> None:
        harness = _harness(tmp_path, _MERGE_FAILS, UPDATE_TYPE=PATCH_UPDATE, DEPENDENCY_NAMES="ruff")
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("merge") == 3
        assert harness.calls == [("merge", EXPECTED_MERGE_ARGV)] * 3
        assert result.returncode != 0
        assert FAILURE_MARKER in harness.summary_text
        assert FAILURE_MARKER in result.stderr

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_transient_merge_failure_recovers_within_the_retry_bound(self, tmp_path: Path, argv_name: str) -> None:
        control = {
            "merge": [
                {"exit_code": 1, "stdout": "", "stderr": "transient"},
                {"exit_code": 0, "stdout": ""},
            ]
        }
        harness = _harness(tmp_path, control, UPDATE_TYPE=MINOR_UPDATE, DEPENDENCY_NAMES="sympy")
        result = harness.run(ARGVS[argv_name])
        assert harness.call_count("merge") == 2
        assert result.returncode == 0
        assert FAILURE_MARKER not in harness.summary_text

    @pytest.mark.parametrize("argv_name", sorted(ARGVS))
    def test_missing_pr_url_fails_loudly_instead_of_merging_nothing(self, tmp_path: Path, argv_name: str) -> None:
        harness = _harness(tmp_path, _MERGE_FORBIDDEN, UPDATE_TYPE=MINOR_UPDATE, DEPENDENCY_NAMES="sympy")
        harness.env["PR_URL"] = ""
        result = harness.run(ARGVS[argv_name])
        assert harness.calls == []
        assert result.returncode != 0
        assert FAILURE_MARKER in harness.summary_text


class TestRealWorkflowBodyWiring:
    """Production-fidelity: parse the REAL workflow YAML, extract its actual run: body, and
    EXECUTE that body (never a substring assertion) under the argv the YAML implies (no `shell:`
    key anywhere on the step/job/workflow -> GitHub's hostile default run-step invocation)."""

    @staticmethod
    def _delegating_step() -> tuple[dict, dict]:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job = workflow["jobs"]["auto-merge"]
        step = next(s for s in job["steps"] if isinstance(s.get("run"), str))
        return workflow, step

    def test_real_workflow_body_reaches_delegate_and_arms_auto_merge(self, tmp_path: Path) -> None:
        workflow, delegating_step = self._delegating_step()
        job = workflow["jobs"]["auto-merge"]
        run_body = delegating_step["run"]

        assert "shell" not in delegating_step
        assert "shell" not in job
        assert "shell" not in workflow.get("defaults", {}).get("run", {})

        body_file = tmp_path / "run_body.sh"
        body_file.write_text(run_body, encoding="utf-8")

        harness = _harness(tmp_path, _MERGE_OK, UPDATE_TYPE=MINOR_UPDATE, DEPENDENCY_NAMES="sympy")
        # cwd=ROOT: the run body's path (scripts/ci/dependabot_auto_merge.sh) is repo-root-relative,
        # exactly as it is in the real job (actions/checkout puts the runner's cwd at the repo root
        # before this step executes).
        result = harness.run(HOSTILE_ARGV, script=body_file, cwd=ROOT)

        assert harness.calls == [("merge", EXPECTED_MERGE_ARGV)], (
            f"the real workflow run: body ({run_body!r}) did not resolve the delegate and arm "
            f"auto-merge. stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert result.returncode == 0

    def test_real_workflow_step_supplies_every_env_var_the_policy_engine_reads(self) -> None:
        """The delegate reads its whole input surface from env; a dropped mapping here would make
        every bump look unclassifiable and silently disable auto-merge."""
        _, delegating_step = self._delegating_step()
        env = delegating_step["env"]
        assert {"UPDATE_TYPE", "DEPENDENCY_NAMES", "PACKAGE_ECOSYSTEM", "PR_URL", "PR_NUMBER", "GH_TOKEN"} <= set(env)
        assert "steps.metadata.outputs.update-type" in env["UPDATE_TYPE"]
        assert "steps.metadata.outputs.dependency-names" in env["DEPENDENCY_NAMES"]
