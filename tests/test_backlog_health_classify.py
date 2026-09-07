"""Mirror test for scripts/backlog_health/classify.py (PLAN-backlog-health-detection).

Includes the VP step 14 AST sole-executor invariant: an AST walk over scripts/backlog_health/**
(excluding probe.py, the one sanctioned executor) proving no other module imports or calls
`_run_acceptance_probe`, passes `run_acceptance_probe` as anything but the literal `False`, or
reaches a subprocess sink with a non-constant-foldable argv -- verified against both the real
package files AND synthetic fixture trees (the earlier two-token grep passed several shapes that
must fail; this walk resolves imports/calls/keyword literals structurally instead).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from scripts.backlog_health import classify, probe

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "scripts" / "backlog_health"

_SUBPROCESS_DOTTED_SINKS = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "os.system",
        "os.popen",
    }
)
# The DI seam name this package's own modules use to inject a subprocess replacement
# (`runner: Callable[..., Any] = subprocess.run`) -- treated as a subprocess sink too, so an
# indirected call through it is held to the same constant-foldable-argv bar as a direct
# `subprocess.run(...)` call.
_SINK_BARE_NAMES = frozenset({"runner"})

# The argv/command parameter's KEYWORD name for each sink, per its real stdlib signature --
# consulted only when a sink call passes its argv as a keyword rather than positionally
# (code review: `node.args[0]`-only missed a kwargs-only call like
# `subprocess.run(args=rec['acceptance'], shell=True)`, a real soundness gap in the "sound
# over-approximation" this invariant claims). `runner` mirrors subprocess.run's `args` name
# since every call site in this package uses that same positional/keyword convention.
_SINK_ARGV_KWARG = {
    "subprocess.run": "args",
    "subprocess.call": "args",
    "subprocess.check_call": "args",
    "subprocess.check_output": "args",
    "subprocess.Popen": "args",
    "os.system": "command",
    "os.popen": "cmd",
    "runner": "args",
}


def _full_dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        prefix = _full_dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_constant_foldable(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_is_constant_foldable(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_constant_foldable(node.left) and _is_constant_foldable(node.right)
    return False


def _find_violations_in_tree(tree: ast.AST, label: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "_run_acceptance_probe":
                    violations.append(f"{label}: imports _run_acceptance_probe")
        if isinstance(node, ast.Call):
            dotted = _full_dotted(node.func)
            bare_name = node.func.id if isinstance(node.func, ast.Name) else ""
            if dotted.endswith("_run_acceptance_probe") or bare_name == "_run_acceptance_probe":
                violations.append(f"{label}: calls _run_acceptance_probe")
            for kw in node.keywords:
                if kw.arg == "run_acceptance_probe":
                    literal_false = isinstance(kw.value, ast.Constant) and kw.value.value is False
                    if not literal_false:
                        violations.append(f"{label}: passes run_acceptance_probe as a non-literal-False value")
            sink_key = dotted if dotted in _SUBPROCESS_DOTTED_SINKS else (bare_name if bare_name in _SINK_BARE_NAMES else "")
            if sink_key:
                argv_node = node.args[0] if node.args else None
                if argv_node is None:
                    kwarg_name = _SINK_ARGV_KWARG.get(sink_key)
                    argv_node = next((kw.value for kw in node.keywords if kw.arg == kwarg_name), None)
                if argv_node is not None and not _is_constant_foldable(argv_node):
                    violations.append(f"{label}: {dotted or bare_name} argv is not constant-foldable")
    return violations


def _violations_for_source(source: str, label: str = "fixture") -> list[str]:
    return _find_violations_in_tree(ast.parse(source), label)


def _violations_for_file(path: Path) -> list[str]:
    return _find_violations_in_tree(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), path.name)


def test_probe_is_sole_rec_authored_executor() -> None:
    """VP step 14: the AST walk finds no rec-authored execution path outside probe.py, and does
    not flag census.py's literal git argv (a positive control -- proves the walk recognises the
    call as a subprocess sink and verifies it, not merely that it never looked).

    Walks scripts/backlog_health/** recursively (rglob, not glob) so the invariant keeps
    enforcing itself if the package ever grows a subpackage -- the docstrings describing this
    walk already claim "**" coverage; the walk itself must match that claim."""
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == "probe.py":
            continue
        assert _violations_for_file(path) == [], f"unexpected violation(s) in {path.name}"

    assert _violations_for_file(PACKAGE_ROOT / "census.py") == []


class TestSoleRecAuthoredExecutorFixtures:
    def test_flags_direct_run_acceptance_probe_import(self) -> None:
        src = "from scripts.rec_relevance import _run_acceptance_probe\n"
        assert _violations_for_source(src)

    def test_flags_aliased_module_call(self) -> None:
        src = "from scripts import rec_relevance\nrec_relevance._run_acceptance_probe('echo hi')\n"
        assert _violations_for_source(src)

    def test_flags_run_acceptance_probe_as_variable_flag(self) -> None:
        src = "flag = True\nevaluate_rec_relevance(rec, run_acceptance_probe=flag)\n"
        assert _violations_for_source(src)

    def test_flags_run_acceptance_probe_as_bool_call(self) -> None:
        src = "evaluate_rec_relevance(rec, run_acceptance_probe=bool(x))\n"
        assert _violations_for_source(src)

    def test_permits_run_acceptance_probe_literal_false(self) -> None:
        src = "evaluate_rec_relevance(rec, run_acceptance_probe=False)\n"
        assert _violations_for_source(src) == []

    def test_permits_run_acceptance_probe_absent(self) -> None:
        src = "evaluate_rec_relevance(rec, open_recs=others)\n"
        assert _violations_for_source(src) == []

    def test_flags_os_system_with_rec_derived_argv(self) -> None:
        src = "import os\nos.system(rec['acceptance'])\n"
        assert _violations_for_source(src)

    def test_flags_os_popen_with_rec_derived_argv(self) -> None:
        src = "import os\nos.popen(rec.get('acceptance'))\n"
        assert _violations_for_source(src)

    def test_flags_subprocess_run_with_rec_derived_argv(self) -> None:
        src = "import subprocess\nsubprocess.run(rec['acceptance'], shell=True)\n"
        assert _violations_for_source(src)

    def test_flags_indirected_runner_call_with_rec_derived_argv(self) -> None:
        src = "runner([rec['acceptance']], cwd=root)\n"
        assert _violations_for_source(src)

    def test_permits_subprocess_run_with_fixed_literal_argv(self) -> None:
        src = "import subprocess\nsubprocess.run(['git', 'log', '--name-only'], capture_output=True)\n"
        assert _violations_for_source(src) == []

    def test_permits_indirected_runner_call_with_fixed_literal_argv(self) -> None:
        src = "runner(['git', 'log'], cwd=root, capture_output=True)\n"
        assert _violations_for_source(src) == []

    def test_flags_subprocess_run_with_rec_derived_argv_passed_as_kwarg(self) -> None:
        # Regression (code review): a kwargs-only call (subprocess.run's `args=` form) has an
        # empty node.args -- args[0]-only detection missed this shape entirely.
        src = "import subprocess\nsubprocess.run(args=rec['acceptance'], shell=True)\n"
        assert _violations_for_source(src)

    def test_flags_os_system_with_rec_derived_argv_passed_as_kwarg(self) -> None:
        src = "import os\nos.system(command=rec['acceptance'])\n"
        assert _violations_for_source(src)

    def test_flags_indirected_runner_call_with_rec_derived_argv_passed_as_kwarg(self) -> None:
        src = "runner(args=[rec['acceptance']], cwd=root)\n"
        assert _violations_for_source(src)

    def test_permits_subprocess_run_with_fixed_literal_argv_passed_as_kwarg(self) -> None:
        src = "import subprocess\nsubprocess.run(args=['git', 'log', '--name-only'], capture_output=True)\n"
        assert _violations_for_source(src) == []


class TestClassifyAcceptanceQuality:
    def test_lint_reject_python_dash_c(self) -> None:
        rows = [{"id": "rec-1", "acceptance": 'bin/venv-python -c "print(1)"'}]
        result = classify.classify_acceptance_quality(rows)
        assert result["lint_reject"] == ["rec-1"]
        assert result["non_discriminating"] == []

    def test_lint_reject_dash_dash_pre_flag(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "bin/venv-python -m scripts.validate --pre"}]
        result = classify.classify_acceptance_quality(rows)
        assert result["lint_reject"] == ["rec-1"]

    def test_python_dash_c_as_quoted_search_string_not_lint_rejected(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "grep -q 'python -c' scripts/foo.py"}]
        result = classify.classify_acceptance_quality(rows)
        assert result["lint_reject"] == []

    def test_non_discriminating_bare_echo(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "echo done"}]
        result = classify.classify_acceptance_quality(rows)
        assert result["non_discriminating"] == ["rec-1"]

    def test_discriminating_grep_is_not_flagged(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "grep -q foo bar.txt"}]
        result = classify.classify_acceptance_quality(rows)
        assert result["lint_reject"] == []
        assert result["non_discriminating"] == []

    def test_discriminating_pytest_is_not_flagged(self) -> None:
        rows = [{"id": "rec-1", "acceptance": "bin/venv-python -m pytest tests/test_x.py::test_y -q"}]
        result = classify.classify_acceptance_quality(rows)
        assert result["non_discriminating"] == []

    def test_empty_acceptance_is_skipped(self) -> None:
        rows: list[dict[str, Any]] = [{"id": "rec-1", "acceptance": ""}, {"id": "rec-2", "acceptance": None}]
        result = classify.classify_acceptance_quality(rows)
        assert result["lint_reject"] == []
        assert result["non_discriminating"] == []

    def test_prose_acceptance_is_skipped_not_flagged_non_discriminating(self) -> None:
        # Regression (code review): a prose command like "N/A" is census.py's PROSE_ONLY
        # concern -- it must never also land in this class's non_discriminating bucket, which
        # would double-count the same rec under two defect classes.
        rows: list[dict[str, Any]] = [
            {"id": "rec-1", "acceptance": "N/A -- manual review"},
            {"id": "rec-2", "acceptance": "Manual review by a human"},
        ]
        result = classify.classify_acceptance_quality(rows)
        assert result["lint_reject"] == []
        assert result["non_discriminating"] == []


class TestClassifyDependencyRefs:
    def test_malformed_bracketed_entry(self) -> None:
        rows = [{"id": "rec-1", "dependencies": ["[rec-028]"]}]
        result = classify.classify_dependency_refs(rows, known_ids={"rec-1", "rec-028"})
        assert result["malformed"] == ["rec-1"]
        assert result["dangling"] == []

    def test_dangling_well_shaped_but_unknown(self) -> None:
        rows = [{"id": "rec-1", "dependencies": ["rec-9999"]}]
        result = classify.classify_dependency_refs(rows, known_ids={"rec-1"})
        assert result["dangling"] == ["rec-1"]
        assert result["malformed"] == []

    def test_well_formed_known_dependency_is_clean(self) -> None:
        rows = [{"id": "rec-1", "dependencies": ["rec-2"]}]
        result = classify.classify_dependency_refs(rows, known_ids={"rec-1", "rec-2"})
        assert result["malformed"] == []
        assert result["dangling"] == []

    def test_empty_dependencies_is_clean(self) -> None:
        rows: list[dict[str, Any]] = [{"id": "rec-1", "dependencies": []}, {"id": "rec-2"}]
        result = classify.classify_dependency_refs(rows, known_ids={"rec-1", "rec-2"})
        assert result["malformed"] == []
        assert result["dangling"] == []

    def test_malformed_takes_precedence_over_dangling_for_same_rec(self) -> None:
        rows = [{"id": "rec-1", "dependencies": ["[rec-028]", "rec-9999"]}]
        result = classify.classify_dependency_refs(rows, known_ids={"rec-1"})
        assert result["malformed"] == ["rec-1"]
        assert result["dangling"] == []


class TestClassifyPremiseDeadAndDuplicates:
    def test_stale_target_pre_anchor_is_bootstrap(self, tmp_path: Path) -> None:
        rows = [{"id": "rec-1", "file": "does/not/exist.py", "created_timestamp": "2026-04-01T00:00:00Z", "title": "x"}]
        result = classify.classify_premise_dead_and_duplicates(rows)
        assert result["premise_dead_bootstrap"] == ["rec-1"]
        assert result["premise_dead_post_anchor"] == []

    def test_stale_target_post_anchor_is_post_anchor(self) -> None:
        rows = [{"id": "rec-1", "file": "does/not/exist.py", "created_timestamp": "2026-06-01T00:00:00Z", "title": "x"}]
        result = classify.classify_premise_dead_and_duplicates(rows)
        assert result["premise_dead_post_anchor"] == ["rec-1"]
        assert result["premise_dead_bootstrap"] == []

    def test_near_duplicate_detected(self) -> None:
        rows = [
            {"id": "rec-1", "file": __file__, "title": "fix the widget alignment bug in the header component"},
            {"id": "rec-2", "file": __file__, "title": "fix the widget alignment bug in the header component now"},
        ]
        result = classify.classify_premise_dead_and_duplicates(rows)
        assert "rec-2" in result["near_duplicate"] or "rec-1" in result["near_duplicate"]

    def test_existing_target_and_unique_title_is_clean(self) -> None:
        rows = [
            {"id": "rec-1", "file": __file__, "title": "a wholly unrelated one-off title", "created_timestamp": "2026-06-01"}
        ]
        result = classify.classify_premise_dead_and_duplicates(rows)
        assert result["premise_dead_bootstrap"] == []
        assert result["premise_dead_post_anchor"] == []
        assert result["near_duplicate"] == []


class TestFileTouchedSince:
    def test_empty_rec_file_is_never_touched(self) -> None:
        assert classify._file_touched_since("", "2026-06-01", [{"sha": "x", "date": "2026-06-02", "files": ["a.py"]}]) is False


class TestClassifyProbeSplit:
    def _census_result(self, rows: list[dict], commits: list[dict]) -> dict:
        return {"open_rows": rows, "recent_commits": commits}

    def test_verdict_for_id_absent_from_open_rows_is_skipped(self) -> None:
        census_result = self._census_result([], [])
        result = classify.classify_probe_split(census_result, {"rec-ghost": probe.PASS})
        assert result["satisfied_candidate"] == []
        assert result["vacuous"] == []

    def test_pass_with_commit_after_creation_is_satisfied(self) -> None:
        rows = [{"id": "rec-1", "file": "a.py", "created_timestamp": "2026-06-01T00:00:00Z"}]
        commits = [{"sha": "x", "date": "2026-06-02T00:00:00Z", "files": ["a.py"]}]
        census_result = self._census_result(rows, commits)
        result = classify.classify_probe_split(census_result, {"rec-1": probe.PASS})
        assert result["satisfied_candidate"] == ["rec-1"]
        assert result["vacuous"] == []

    def test_pass_with_no_touching_commit_is_vacuous(self) -> None:
        rows = [{"id": "rec-1", "file": "a.py", "created_timestamp": "2026-06-01T00:00:00Z"}]
        commits = [{"sha": "x", "date": "2026-06-02T00:00:00Z", "files": ["b.py"]}]
        census_result = self._census_result(rows, commits)
        result = classify.classify_probe_split(census_result, {"rec-1": probe.PASS})
        assert result["vacuous"] == ["rec-1"]
        assert result["satisfied_candidate"] == []

    def test_commit_before_creation_does_not_count(self) -> None:
        rows = [{"id": "rec-1", "file": "a.py", "created_timestamp": "2026-06-01T00:00:00Z"}]
        commits = [{"sha": "x", "date": "2026-05-01T00:00:00Z", "files": ["a.py"]}]
        census_result = self._census_result(rows, commits)
        result = classify.classify_probe_split(census_result, {"rec-1": probe.PASS})
        assert result["vacuous"] == ["rec-1"]

    def test_non_pass_verdicts_are_excluded_from_split(self) -> None:
        rows = [{"id": "rec-1", "file": "a.py", "created_timestamp": "2026-06-01T00:00:00Z"}]
        census_result = self._census_result(rows, [])
        for verdict in (probe.FAIL, probe.TIMEOUT, probe.BUDGET_EXHAUSTED, probe.ISOLATION_UNAVAILABLE):
            result = classify.classify_probe_split(census_result, {"rec-1": verdict})
            assert result["satisfied_candidate"] == []
            assert result["vacuous"] == []


class TestClassifyAll:
    def test_wires_all_four_classes(self) -> None:
        census_result = {
            "open_rows": [
                {
                    "id": "rec-1",
                    "file": "a.py",
                    "acceptance": "echo hi",
                    "dependencies": [],
                    "created_timestamp": "2026-06-01",
                },
            ],
            "recent_commits": [],
        }
        result = classify.classify_all(census_result, {})
        assert set(result.keys()) == {
            "probe_split",
            "acceptance_quality",
            "dependency_refs",
            "premise_dead_and_duplicates",
        }
