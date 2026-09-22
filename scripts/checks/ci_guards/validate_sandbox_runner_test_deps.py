"""Slice A inheritance guard (rec-4005 / PLAN-backlog-health-probe-decides-pytest): a workflow job
that engages the backlog-health sandbox and runs a rec-authored acceptance command must install a
test runner, or every pytest-shaped acceptance command silently exits 4 ("unrecognized arguments"
against pyproject.toml's --randomly-seed/--disable-socket addopts) instead of deciding pass/fail.

Armed on POSITIVE EVIDENCE by EITHER of two markers in a job's step bodies -- never only the
first:

  M1: the unprivileged-user-namespace sysctl string `apparmor_restrict_unprivileged_userns=0`
      (live today at .github/workflows/backlog-health.yml:118). An Ubuntu 23.10/24.04
      AppArmor-default PRECONDITION for `unshare -rmn`, not the sandbox itself.
  M2: a step body invoking the `scripts.backlog_health` package specifically via its `probe`
      verb (live today at :121), OR invoking any OTHER module whose first-party import closure
      transitively imports `scripts.backlog_health.probe` (scripts.dependency_graph forward
      closure -- the same NEED-resolution idiom validate_workflow_dependency_install.py uses).
      `scripts.backlog_health`'s own package import closure ALWAYS reaches probe.py regardless of
      which CLI verb is invoked (__main__.py imports all three subcommand modules unconditionally
      at module scope), so the package invocation is armed ONLY when the literal `probe` token
      follows it in the same run body -- otherwise the census and escalate jobs (which invoke the
      same package with `census`/`escalate`) would be wrongly flagged.

Neither marker's absence is ever read as "nothing needed": M1 alone is an OS-version-scoped fact
(ubuntu-22.04, a self-hosted runner, or a future relaxed ubuntu-latest default all engage
`unshare -rmn` with no sysctl step, returning REAL verdicts with pytest absent), and Decision 162's
R3 ratchet can push a sysctl step out of `.github/workflows/` into scripts/ci/ or a composite
action, walking it out of an M1-only guard's view while the job still needs a test runner. M2
keeps the guard armed across both escapes, and also fires on PLAN-trailer-acceptance-static-gate's
(slice A) evaluator job by construction, since that evaluator reuses this same probe module.

Comment defence: `_workflow_shell_bodies._effective_lines` drops blank and FULL-LINE comments
only, never TRAILING ones, so `run: echo hi  # apparmor_restrict_unprivileged_userns=0` would
still spoof M1 if this guard scanned raw text. `_strip_shell_comments` below is this guard's own
narrow copy of that blanking logic (never imported from validate_workflow_dependency_install.py's
module-private `_blank_shell_comments` -- relocating it would trip Decision 162 R3's
touch-it-fix-it obligation on a module this plan otherwise does not touch) -- it blanks both
full-line and trailing unquoted `#` comments before either marker or install regex is applied.

Declares examined()/skipped() (Decision 170): examined(n, unit="jobs") over the ARMED job
population on the non-vacuous branch; skipped(reason) when no job in the corpus carries either
marker today -- this check is absent from config/check_accounting_baseline.yaml (Decision 165,
shrink-only, frozen _BASELINE_SEED) and cannot be added there, so the declaration is mandatory on
both branches from its first commit.
"""

from __future__ import annotations

import functools
import re

import yaml

from scripts import dependency_graph
from scripts.checks import registry
from scripts.checks.ci_guards import _workflow_shell_bodies

_M1_MARKER = "apparmor_restrict_unprivileged_userns=0"
_BACKLOG_HEALTH_PACKAGE = "scripts.backlog_health"
_BACKLOG_HEALTH_PROBE_MODULE = "scripts.backlog_health.probe"
_INVOKED_MODULE_RE = re.compile(r"-m\s+(scripts(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")
_PROBE_VERB_RE = re.compile(r"\bprobe\b")
_INSTALL_FAST_RE = re.compile(r"pip\s+install\b[^\n]*requirements-fast\.txt")

_FAILURE_TEMPLATE = (
    "sandbox-runner-test-deps guard: {key} is armed by {marker} (it engages the backlog-health "
    "sandbox / executes a rec-authored acceptance command) but has no requirements-fast.txt "
    "install in the same job at or before this step -- pytest-shaped acceptance commands cannot "
    "be decided without it (pyproject.toml addopts reject a bare pytest-only install with "
    "'unrecognized arguments'). Add `pip install -r requirements.txt -r requirements-fast.txt` "
    "(or an equivalent combined install) at or before this step."
)


def _strip_shell_comments(text: str) -> str:
    """Blank both full-line and TRAILING unquoted '#' shell comments, preserving every other
    character's line/offset -- see module docstring's Comment defence paragraph."""
    out_lines: list[str] = []
    for line in text.split("\n"):
        chars: list[str] = []
        in_single = False
        in_double = False
        i = 0
        length = len(line)
        while i < length:
            ch = line[i]
            if ch == "'" and not in_double:
                in_single = not in_single
                chars.append(ch)
            elif ch == '"' and not in_single:
                in_double = not in_double
                chars.append(ch)
            elif ch == "#" and not in_single and not in_double:
                chars.append(" " * (length - i))
                break
            else:
                chars.append(ch)
            i += 1
        out_lines.append("".join(chars))
    return "\n".join(out_lines)


@functools.lru_cache(maxsize=None)
def _module_imports_backlog_health_probe(module: str) -> bool:
    """True iff `module` IS scripts.backlog_health.probe, or transitively imports it (M2's
    "plus any module that imports scripts.backlog_health.probe" clause). Cached: the live corpus
    invokes a handful of distinct modules across a handful of workflow jobs."""
    if module == _BACKLOG_HEALTH_PROBE_MODULE:
        return True
    graph = dependency_graph.build_graph()
    if module not in graph:
        return False
    code_only = dependency_graph.import_subgraph(graph)
    return _BACKLOG_HEALTH_PROBE_MODULE in dependency_graph.forward_closure(code_only, module)


def _arming_marker(scan_text: str) -> str | None:
    """ "M1"/"M2"/None for one comment-stripped step body -- see module docstring."""
    if _M1_MARKER in scan_text:
        return "M1 (unprivileged-userns sysctl)"
    for match in _INVOKED_MODULE_RE.finditer(scan_text):
        module = match.group(1)
        if module == _BACKLOG_HEALTH_PACKAGE:
            if _PROBE_VERB_RE.search(scan_text[match.end() :]):
                return "M2 (scripts.backlog_health probe verb)"
            continue
        if _module_imports_backlog_health_probe(module):
            return "M2 (imports scripts.backlog_health.probe)"
    return None


def _iter_job_run_steps() -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(workflow_rel_path, job_id, [(step_identity, run_body), ...])] for every job carrying at
    least one string `run:` step, in step order."""
    jobs: list[tuple[str, str, list[tuple[str, str]]]] = []
    for path in _workflow_shell_bodies._iter_workflows():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Relative to the workflow's OWN repo root, never a hardcoded real root -- test fixtures
        # point _workflow_shell_bodies._common.ROOT at a tmp_path, mirroring
        # validate_workflow_dependency_install.py's _iter_job_steps.
        rel_path = str(path.relative_to(path.parents[2])).replace("\\", "/")
        raw_jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(raw_jobs, dict):
            continue
        for job_id, job in raw_jobs.items():
            steps = job.get("steps") if isinstance(job, dict) else None
            if not isinstance(steps, list):
                continue
            run_steps: list[tuple[str, str]] = []
            for index, step in enumerate(steps):
                run_body = step.get("run") if isinstance(step, dict) else None
                if isinstance(run_body, str):
                    identity = _workflow_shell_bodies._step_identity(step, index)
                    run_steps.append((identity, run_body))
            if run_steps:
                jobs.append((rel_path, job_id, run_steps))
    return jobs


def check_sandbox_runner_test_deps() -> tuple[list[str], int]:
    """(violations, examined_job_count) -- the guard's pure logic, split from registration for
    direct test-entrypoint calls."""
    violations: list[str] = []
    examined_jobs = 0

    for rel_path, job_id, run_steps in _iter_job_run_steps():
        scanned = [(identity, _strip_shell_comments(body)) for identity, body in run_steps]
        marker_index: int | None = None
        marker_label: str | None = None
        for index, (_identity, scan_text) in enumerate(scanned):
            found = _arming_marker(scan_text)
            if found is not None:
                marker_index = index
                marker_label = found
                break
        if marker_index is None:
            continue

        examined_jobs += 1
        installed = any(_INSTALL_FAST_RE.search(scan_text) for _identity, scan_text in scanned[: marker_index + 1])
        if not installed:
            key = f"{rel_path}::{job_id}::{scanned[marker_index][0]}"
            violations.append(_FAILURE_TEMPLATE.format(key=key, marker=marker_label))

    return violations, examined_jobs


@registry.register("validate_sandbox_runner_test_deps", owner="platform")
def validate_sandbox_runner_test_deps(failed: list[str]) -> None:
    """Every `.github/workflows/` job carrying either the unprivileged-userns sysctl marker or a
    scripts.backlog_health probe-verb / probe-importing invocation must install
    requirements-fast.txt at or before the matching step, in the same job. See module
    docstring."""
    print("\n=== sandbox-runner test-deps guard ===")
    violations, examined_jobs = check_sandbox_runner_test_deps()
    for violation in violations:
        print(f"  FAIL: {violation}")
        failed.append(violation)
    if examined_jobs == 0:
        print("  sandbox-runner test-deps guard: no job in .github/workflows/ carries either marker")
        registry.skipped("no job carries the unprivileged-userns sysctl marker or a scripts.backlog_health probe invocation")
        return
    if not violations:
        print(f"  PASS: every armed job installs requirements-fast.txt at or before its marker step ({examined_jobs} job(s))")
    print(f"  sandbox-runner test-deps guard: enforced over {examined_jobs} job(s)")
    registry.examined(examined_jobs, unit="jobs")
