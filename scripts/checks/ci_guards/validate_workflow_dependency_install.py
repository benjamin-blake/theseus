"""A job step invoking a scripts module whose transitive imports need a third-party distribution
must have a dependency install in the SAME job, at or before that step (ULF-01 forward-fix).

ghas-probe.yml's probe job ran `python -m scripts.checks.misc.validate_ghas_probe` with no install
step; commit 570b9a53 (PR #1169) pulled `yaml` into that module's transitive closure (via
scripts.checks.registry -> scripts.checks._common's `import yaml`), and the runner died on
ModuleNotFoundError before ever reaching the GitHub API -- six blind scheduled runs, unactioned.
This guard makes that drift class structurally impossible at PR time.

Two predicates, both DATA, not prose:

INVOCATION (four shapes -- `python3` is NOT a `python` substring match, so it needs its own entry;
omitting it would silently under-enforce over reconcile.yml/terraform-apply-sandbox.yml's whole
corpus, which invoke ONLY via python3):
    "python -m scripts.", "python3 -m scripts.", ".venv/bin/python -m scripts.", "bin/venv-python"
A `bin/venv-python`/`python*` occurrence inside a `Bash(...)` permission token or an
`--allowedTools`/`--disallowedTools` value (ci-rca.yml:464) is a permission STRING, not an
invocation -- excluded by token shape, never by "inside quotes" (quoting is fail-open: it would
suppress terraform-apply-sandbox.yml:224's genuine `$(...)` command substitution).

INSTALL (three shapes): `pip install -r requirements*.txt`, `pip install <pkgs>`, and
`python -m venv` + `.venv/bin/pip install`. May sit at or before the invoking step in the SAME
job, including textually earlier within that step's own `run:` body (reconcile.yml:264-265).

Both scans run against a COMMENT-BLANKED copy of the run: body (`_blank_shell_comments`):
unquoted shell `#`-comment text is replaced with spaces (preserving every other character's
offset) before either regex matches, so a comment merely MENTIONING `pip install` or `-m
scripts.` text -- never executed -- cannot spoof either predicate.

NEED is a coarse yes/no over the invoked module's first-party import closure (scripts.
dependency_graph.import_subgraph + forward_closure), never a precise per-package match: for each
closure member, an AST scan of ONLY that file's TOP-LEVEL (module-scope) imports -- a deferred,
function-scoped import (e.g. scripts.checks._common's `load_plan()` reaching
scripts.roadmap.plan_document/pydantic) is invisible to this scan by design, since the check only
asks "does something in this static closure need installing", not "does the probe's runtime path
reach it". Stdlib names (`sys.stdlib_module_names`) and first-party roots (src/scripts/tests) are
subtracted. A composite-action's own install is out of scope: _iter_workflows globs
`.github/workflows/` only.

Declares examined()/skipped() (Decision 170): "dependency-install guard: enforced over N job(s)"
on the non-vacuous branch (N = distinct (workflow, job) pairs carrying at least one recognized
invocation), a DIFFERENT literal on the vacuous branch -- load-bearing output, not cosmetic
(VP step 3 asserts on the former to prove the guard examined something real, not nothing).

Deferred to rec-3989: the grammar covers MODULE invocation (`-m scripts.X`) only -- a file-path or
heredoc invocation shape is invisible to it. Benign today; forward under-enforcement only.
"""

from __future__ import annotations

import ast
import functools
import re
import sys
from pathlib import Path

from scripts import dependency_graph
from scripts.checks import registry
from scripts.checks.ci_guards import _workflow_shell_bodies

_REAL_ROOT = Path(__file__).resolve().parents[3]

_INVOCATION_MARKERS: tuple[str, ...] = (
    "python -m scripts.",
    "python3 -m scripts.",
    ".venv/bin/python -m scripts.",
    "bin/venv-python",
)

_MODULE_AFTER_RE = re.compile(r"-m\s+(scripts(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_MODULE_MATCH_WINDOW = 40

_BASH_TOKEN_RE = re.compile(r"Bash\([^)]*\)")
_TOOL_FLAG_RE = re.compile(r"--(?:allowed|disallowed)Tools\s+(\"[^\"]*\"|'[^']*'|\S+)")

_INSTALL_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pip install -r requirements*.txt", re.compile(r"pip\s+install\s+-r\s+requirements\S*\.txt")),
    ("pip install <pkgs>", re.compile(r"pip\s+install\s+(?!-r\b)\S")),
    ("python -m venv + .venv/bin/pip install", re.compile(r"\.venv/bin/pip\s+install")),
)

_STDLIB: frozenset[str] = frozenset(sys.stdlib_module_names)
_SKIP_ROOTS: frozenset[str] = frozenset({"src", "scripts", "tests"})

_FAILURE_TEMPLATE = (
    "dependency-install guard: {key} invokes scripts with no preceding install step -- {module} needs a "
    "third-party distribution (scripts.dependency_graph closure). Add a `pip install <pkgs>`, "
    "`pip install -r requirements*.txt`, or `python -m venv` + `.venv/bin/pip install` step in the same "
    "job, at or before this step."
)


def _blank_shell_comments(text: str) -> str:
    """Replace unquoted shell '#'-comment text with spaces, preserving line structure and every
    other character's offset. Without this, a comment merely MENTIONING `pip install` or
    `-m scripts.` text (never executed) spoofs either regex scan -- reproduced directly against a
    `# pip install pyyaml (not real)` line preceding a real, uninstalled invocation."""
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


def _exclusion_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in _BASH_TOKEN_RE.finditer(text)]
    spans.extend(m.span(1) for m in _TOOL_FLAG_RE.finditer(text))
    return spans


def _excluded(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _find_invocations(text: str) -> list[tuple[int, str]]:
    """[(marker_start, module)] for every non-excluded MODULE invocation in `text`, deduplicated
    by the underlying `-m scripts.X` match position (a `.venv/bin/python -m scripts.X` occurrence
    also satisfies the bare `python -m scripts.X` marker at a later offset; keying on the module
    match's own start collapses both onto one invocation)."""
    spans = _exclusion_spans(text)
    by_module_pos: dict[int, tuple[int, str]] = {}
    for marker in _INVOCATION_MARKERS:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx == -1:
                break
            start = idx + 1
            if _excluded(idx, spans):
                continue
            mod_match = _MODULE_AFTER_RE.search(text, idx)
            if mod_match and mod_match.start() - idx < _MODULE_MATCH_WINDOW:
                by_module_pos[mod_match.start()] = (idx, mod_match.group(1))
    return [by_module_pos[key] for key in sorted(by_module_pos)]


def _install_positions(text: str) -> list[int]:
    positions: list[int] = []
    for label, pattern in _INSTALL_SHAPES:
        if label.startswith("python -m venv") and "python -m venv" not in text:
            continue
        positions.extend(m.start() for m in pattern.finditer(text))
    return positions


def _module_to_path(module: str, root: Path) -> Path | None:
    rel = Path(*module.split("."))
    direct = root / rel.with_suffix(".py")
    if direct.is_file():
        return direct
    package_init = root / rel / "__init__.py"
    if package_init.is_file():
        return package_init
    return None


def _top_level_third_party_roots(path: Path) -> frozenset[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return frozenset()
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if node.module:
                found.add(node.module.split(".", 1)[0])
    return frozenset(found) - _STDLIB - _SKIP_ROOTS


@functools.lru_cache(maxsize=None)
def _module_needs_third_party(module: str) -> bool:
    """Coarse yes/no over module's first-party import closure -- see module docstring's NEED
    paragraph. Cached: the live corpus invokes a handful of distinct modules dozens of times."""
    graph = dependency_graph.build_graph()
    if module not in graph:
        return False
    code_only = dependency_graph.import_subgraph(graph)
    members = [module, *dependency_graph.forward_closure(code_only, module)]
    for member in members:
        path = _module_to_path(member, _REAL_ROOT)
        if path is not None and _top_level_third_party_roots(path):
            return True
    return False


def _iter_job_steps() -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(workflow_rel_path, job_id, [(step_identity, run_body), ...])] for every job carrying at
    least one string `run:` step, in step order."""
    jobs: list[tuple[str, str, list[tuple[str, str]]]] = []
    for path in _workflow_shell_bodies._iter_workflows():
        import yaml as _yaml  # noqa: PLC0415

        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Relative to the workflow's OWN repo root (two parents up from .github/workflows/<file>),
        # never _REAL_ROOT: _iter_workflows() resolves under _common.ROOT, which a caller (test
        # fixtures) may point at a tmp_path distinct from the real repo _REAL_ROOT anchors NEED
        # resolution against.
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


def check_workflow_dependency_installs() -> tuple[list[str], int]:
    """(violations, examined_job_count) -- the guard's pure logic, split from registration for
    direct test-entrypoint calls."""
    violations: list[str] = []
    examined_jobs = 0

    for rel_path, job_id, run_steps in _iter_job_steps():
        job_examined = False
        earlier_install = False
        for step_index, (identity, run_body) in enumerate(run_steps):
            scan_text = _blank_shell_comments(run_body)
            invocations = _find_invocations(scan_text)
            if invocations:
                job_examined = True
            install_positions = _install_positions(scan_text)
            for marker_pos, module in invocations:
                same_body_install = any(pos < marker_pos for pos in install_positions)
                if earlier_install or same_body_install:
                    continue
                if not _module_needs_third_party(module):
                    continue
                key = f"{rel_path}::{job_id}::{identity}"
                violations.append(_FAILURE_TEMPLATE.format(key=key, module=module))
            if install_positions:
                earlier_install = True
        if job_examined:
            examined_jobs += 1

    return violations, examined_jobs


@registry.register("validate_workflow_dependency_install", owner="platform")
def validate_workflow_dependency_install(failed: list[str]) -> None:
    """Every `.github/workflows/` job step invoking `-m scripts.X` where X's first-party import
    closure needs a third-party distribution must have a dependency install at or before it, in
    the same job. See module docstring."""
    print("\n=== workflow dependency-install guard ===")
    violations, examined_jobs = check_workflow_dependency_installs()
    for violation in violations:
        print(f"  FAIL: {violation}")
        failed.append(violation)
    if examined_jobs == 0:
        print("  dependency-install guard: no script-invoking job found in .github/workflows/")
        registry.examined(0, unit="jobs")
        return
    if not violations:
        print(f"  PASS: every third-party-needing invocation has a preceding same-job install ({examined_jobs} job(s))")
    print(f"  dependency-install guard: enforced over {examined_jobs} job(s)")
    registry.examined(examined_jobs, unit="jobs")
