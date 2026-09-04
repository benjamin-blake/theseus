"""Mirror test for scripts/checks/deps/validate_pre_glob_closure.py (D2-3 wave 4a, rec-3289).

Behaviour is pinned on SYNTHETIC fixture repositories, never on the live backlog count -- that
number moves with every glob edit. TWO classes depend on the real tree and neither pins that
count: TestLiveTreeSmoke asserts only that the auditor runs green (it is advisory), and
TestPrunedEdgesRoster builds the real import graph via _closure_view to pin the wave-4b prune
roster's CONTENT and the liveness of every edge it declares.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import patch

import networkx as nx
import pytest

from scripts.checks import _common, registry
from scripts.checks._schema import Entry
from scripts.checks.deps import validate_pre_glob_closure as vpgc
from tests.fixtures.validate_module import _validate


def _entry(name: str, module: str, **kwargs: Any) -> Entry:
    defaults = {"pre": True, "pre_globs": ("scripts/checks/**",), "full_segment": "full_after_lint"}
    defaults.update(kwargs)
    return Entry(name=name, module=module, attr=name, **defaults)


def _make_repo(tmp_path: Path) -> Path:
    """A synthetic repo whose one gated check imports a hub module OUTSIDE its declared globs.

    scripts/checks/fake/validate_thing.py  -- imports scripts.hublib (an uncovered closure path)
    scripts/checks/fake/_manifest.py       -- names the check by BARE STRING LITERAL only
    scripts/hublib.py                      -- the uncovered hub
    """
    (tmp_path / "scripts" / "checks" / "fake").mkdir(parents=True)
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "checks" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "checks" / "fake" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "hublib.py").write_text("def hub():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "checks" / "fake" / "validate_thing.py").write_text(
        "from scripts.hublib import hub\n\n\ndef validate_thing(failed):\n    hub()\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "checks" / "fake" / "_manifest.py").write_text(
        'ENTRIES = ("scripts.checks.fake.validate_thing",)\n', encoding="utf-8"
    )
    return tmp_path


def _run_against(root: Path, entries: dict[str, Entry]) -> tuple[list[str], object]:
    """Dispatch the auditor with ROOT and the manifest roster swapped for a fixture pair."""
    failed: list[str] = []
    with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", entries):
        with registry.outcome_scope("validate_pre_glob_closure"):
            vpgc.validate_pre_glob_closure(failed)
        declaration = registry.pop_declaration()
    return failed, declaration


class TestGlobMatcherEquivalence:
    """_glob_match must be behaviourally identical to scripts/validate.py::_pre_glob_match --
    a replica, not an import (see the module docstring's cycle/closure rationale). If the two
    ever diverge the auditor would report a path the real gate does select, or miss one it does
    not."""

    _CASES = [
        ("setup.py", "**/*.py"),
        ("conftest.py", "**/*.py"),
        ("scripts/validate.py", "**/*.py"),
        ("AGENTS.md", "**/*.py"),
        ("AGENTS.md", "**/*.md"),
        ("docs/plans/PLAN-x.yaml", "docs/plans/**"),
        ("plans/PLAN-x.yaml", "docs/plans/**"),
        ("scripts/checks/deps/affected_tests.py", "scripts/checks/**"),
        ("scripts/dependency_graph.py", "scripts/checks/**"),
        ("scripts/dependency_graph.py", "scripts/dependency_graph.py"),
        ("scripts/checks/deps/_manifest.py", "scripts/checks/*/_manifest.py"),
        ("scripts/checks/deps/x/_manifest.py", "scripts/checks/*/_manifest.py"),
    ]

    @pytest.mark.parametrize("path,glob", _CASES, ids=[f"{p}|{g}" for p, g in _CASES])
    def test_matches_the_real_gate(self, path: str, glob: str) -> None:
        assert vpgc._glob_match(path, glob) is _validate._pre_glob_match(path, glob)


class TestModuleToRepoPath:
    """Inverse of scripts.dependency_graph._file_to_module, for the two node shapes build_graph
    produces: a plain module and a package __init__ node."""

    def test_plain_module(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert vpgc._module_to_repo_path("scripts.hublib", root) == "scripts/hublib.py"

    def test_package_init_node(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert vpgc._module_to_repo_path("scripts.checks.fake", root) == "scripts/checks/fake/__init__.py"

    def test_unknown_module_is_none(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        assert vpgc._module_to_repo_path("scripts.does_not_exist", root) is None


class TestClosureModules:
    """_closure_modules is REFLEXIVE (the defining module is part of its own audited surface --
    editing a check's own file must select it) and honours _PRUNED_EDGES per edge."""

    @staticmethod
    def _chain() -> nx.DiGraph:
        graph = nx.DiGraph()
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        graph.add_edge("c", "d")
        return graph

    def test_includes_the_module_itself(self) -> None:
        assert vpgc._closure_modules(self._chain(), "a") == {"a", "b", "c", "d"}

    def test_leaf_closure_is_just_itself(self) -> None:
        assert vpgc._closure_modules(self._chain(), "d") == {"d"}

    def test_module_absent_from_the_view_yields_empty(self) -> None:
        assert vpgc._closure_modules(self._chain(), "zz") == set()

    def test_a_cycle_terminates(self) -> None:
        graph = self._chain()
        graph.add_edge("d", "a")
        assert vpgc._closure_modules(graph, "a") == {"a", "b", "c", "d"}

    def test_pruned_edge_removes_everything_only_reachable_through_it(self) -> None:
        with patch.object(vpgc, "_PRUNED_EDGES", {"b": ("c",)}):
            assert vpgc._closure_modules(self._chain(), "a") == {"a", "b"}

    def test_pruned_edge_does_not_remove_an_independently_reachable_module(self) -> None:
        graph = self._chain()
        graph.add_edge("a", "c")
        with patch.object(vpgc, "_PRUNED_EDGES", {"b": ("c",)}):
            assert vpgc._closure_modules(graph, "a") == {"a", "b", "c", "d"}


class TestPrunedEdgesRoster:
    """The reviewed wave-4b hub roster, pinned against SILENT staleness.

    A row whose key or target no longer exists, or whose target is no longer a SUCCESSOR of its key
    in the live import subgraph, prunes nothing and reads exactly like a correct row. So these
    assertions check resolution AND liveness against the real graph the auditor traverses, carry an
    explicit non-vacuity guard so an emptied roster cannot satisfy them, and are paired with a
    negative control that feeds the detector a deliberately bogus roster. CONTENT and edge liveness
    are pinned here; the live backlog count never is.
    """

    _CAP = 4
    _REGISTRY = "scripts.checks.registry"
    _COMMON = "scripts.checks._common"

    @staticmethod
    def _dead_rows(roster: dict[str, tuple[str, ...]]) -> list[str]:
        """One report per dead row, in the three shapes a stale roster can take: an unresolvable
        key, an unresolvable target, and a declared pair that is not an edge of the live subgraph."""
        root = _common.ROOT
        view = vpgc._closure_view(root)
        reports: list[str] = []
        for key, targets in sorted(roster.items()):
            key_live = vpgc._module_to_repo_path(key, root) is not None and key in view
            if not key_live:
                reports.append(f"key {key} unresolvable")
            for target in targets:
                if vpgc._module_to_repo_path(target, root) is None or target not in view:
                    reports.append(f"target {target} unresolvable")
                elif not key_live or not view.has_edge(key, target):
                    reports.append(f"edge {key} -> {target} not live")
        return reports

    @staticmethod
    def _literal_block() -> list[str]:
        """Source lines of the _PRUNED_EDGES literal, ast-located rather than offset-guessed."""
        source = Path(vpgc.__file__).read_text(encoding="utf-8").splitlines()
        node = next(
            n
            for n in ast.walk(ast.parse("\n".join(source)))
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "_PRUNED_EDGES"
        )
        return source[node.lineno - 1 : node.end_lineno]

    def test_the_roster_is_the_two_reviewed_hub_rows(self) -> None:
        """Supersedes test_starts_empty, whose whole contract was the staging precondition (the
        roster is INTENTIONALLY EMPTY until an entry is added with an inline reason) that this
        authorised wave-4b pay-down discharges. Also the NON-VACUITY guard the two staleness
        assertions below lean on -- they iterate the roster and would pass trivially against an
        emptied one."""
        roster = vpgc._PRUNED_EDGES
        assert sorted(roster) == [self._COMMON, self._REGISTRY]
        assert roster[self._COMMON] == ("scripts.roadmap.plan_document",)
        targets = roster[self._REGISTRY]
        assert "scripts.checks._schema" in targets
        assert len([t for t in targets if t.endswith("._manifest")]) == 17
        assert len(targets) == 18

    def test_row_count_is_exactly_the_reviewed_two_and_within_the_cap(self) -> None:
        """An EXACT pin replacing an exact pin (`== {}` -> `== 2`), never a 0 -> 4 allowance: the
        cap records the reviewed wave ceiling and is not permission to fill it."""
        assert len(vpgc._PRUNED_EDGES) == 2
        assert len(vpgc._PRUNED_EDGES) <= self._CAP

    def test_every_declared_edge_is_live_in_the_import_subgraph(self) -> None:
        """Every key and target resolves to a real repo module AND every declared pair is genuinely
        an edge of the subgraph the auditor traverses -- a row that resolves but no longer prunes
        anything is indistinguishable from a correct one."""
        assert vpgc._PRUNED_EDGES, "an emptied roster must not satisfy this assertion vacuously"
        assert self._dead_rows(vpgc._PRUNED_EDGES) == []

    def test_the_detector_rejects_all_three_dead_row_shapes(self) -> None:
        """Negative control, green in BOTH states by construction: it feeds the detector its own
        bogus roster and never reads the real one. Without it the assertions above could all be
        satisfied by a detector that returns an empty list unconditionally. FOUR findings, not
        three -- a bogus KEY also invalidates every edge declared under it."""
        bogus = {
            "scripts.checks.no_such_hub": ("scripts.checks._schema",),
            self._REGISTRY: ("scripts.checks.no_such_target", "scripts.dependency_graph"),
        }
        reports = self._dead_rows(bogus)
        assert reports == [
            "key scripts.checks.no_such_hub unresolvable",
            "edge scripts.checks.no_such_hub -> scripts.checks._schema not live",
            "target scripts.checks.no_such_target unresolvable",
            f"edge {self._REGISTRY} -> scripts.dependency_graph not live",
        ]
        assert len(reports) == 4

    def test_every_row_is_preceded_by_an_inline_rationale_comment(self) -> None:
        """The module's own rule for adding an entry, enforced rather than trusted. Together with
        the cap test this is the anti-gaming pin: a row cannot be added silently or unexplained."""
        assert vpgc._PRUNED_EDGES, "an emptied roster must not satisfy this assertion vacuously"
        block = self._literal_block()
        for key in vpgc._PRUNED_EDGES:
            index = next(i for i, line in enumerate(block) if line.strip().startswith(f'"{key}":'))
            preceding = next(block[i] for i in range(index - 1, -1, -1) if block[i].strip())
            assert preceding.strip().startswith("#"), f"row {key} carries no inline rationale comment"


class TestGatedEntries:
    """Only pre=True entries that DECLARE pre_globs are auditable: an ungated (pre_globs=None)
    entry always runs, so it has nothing to under-cover."""

    def test_selects_only_gated_pre_entries(self) -> None:
        entries = {
            "gated": _entry("gated", "scripts.checks.fake.gated"),
            "ungated": _entry("ungated", "scripts.checks.fake.ungated", pre_globs=None),
            "full_only": _entry("full_only", "scripts.checks.fake.full_only", pre=False, pre_globs=None),
        }
        with patch.object(registry, "_ALL_ENTRIES", entries):
            assert [e.name for e in vpgc._gated_entries()] == ["gated"]

    def test_is_sorted_by_name(self) -> None:
        """Module order DISAGREES with name order here on purpose -- a fixture whose modules are
        the names with a constant prefix cannot tell the two sort keys apart."""
        modules = {"zeta": "scripts.checks.fake.aaa", "alpha": "scripts.checks.fake.zzz", "mid": "scripts.checks.fake.mmm"}
        entries = {n: _entry(n, m) for n, m in modules.items()}
        with patch.object(registry, "_ALL_ENTRIES", entries):
            selected = vpgc._gated_entries()
        assert [e.name for e in selected] == ["alpha", "mid", "zeta"]
        assert [e.module for e in selected] != sorted(e.module for e in selected)


class TestAuditorOnSyntheticRepo:
    """End-to-end over a real build_graph of a synthetic tree."""

    def test_reports_the_uncovered_hub_import(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", entries):
            view = vpgc._closure_view(root)
            entry = vpgc._gated_entries()[0]
            assert vpgc._unmatched_paths(entry, view, root) == ["scripts/hublib.py"]

    def test_declaring_the_hub_glob_clears_the_finding(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing", pre_globs=("scripts/**",))
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", {entry.name: entry}):
            view = vpgc._closure_view(root)
            assert vpgc._unmatched_paths(entry, view, root) == []

    def test_a_patch_string_edge_is_not_part_of_the_closure(self, tmp_path: Path) -> None:
        """Decision 169's manifest driver edge is kind="patch_string" and must be invisible here
        -- it is what collapses every check into one SCC and makes the naive derivation inert."""
        root = _make_repo(tmp_path)
        (root / "scripts" / "checks" / "fake" / "validate_thing.py").write_text(
            'TARGET = "scripts.hublib.hub"\n\n\ndef validate_thing(failed):\n    pass\n', encoding="utf-8"
        )
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing")
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", {entry.name: entry}):
            view = vpgc._closure_view(root)
            assert vpgc._unmatched_paths(entry, view, root) == []

    def test_a_module_missing_from_the_graph_is_reported_not_crashed(self, tmp_path: Path) -> None:
        """A typo'd or relocated Entry.module has no computable closure, so NO glob can be shown
        to cover it -- auditing it clean is the same fail-open shape this check exists to catch.
        The module itself is the finding."""
        root = _make_repo(tmp_path)
        entry = _entry("ghost", "scripts.checks.fake.ghost")
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", {entry.name: entry}):
            view = vpgc._closure_view(root)
            assert vpgc._unmatched_paths(entry, view, root) == ["<module not in the import graph: scripts.checks.fake.ghost>"]

    def test_an_unresolvable_module_is_reported_even_when_its_globs_are_broad(self, tmp_path: Path) -> None:
        """A catch-all glob must not mask it: the finding is the missing NODE, not a path."""
        root = _make_repo(tmp_path)
        entry = _entry("ghost", "scripts.checks.fake.ghost", pre_globs=("**/*.py",))
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", {entry.name: entry}):
            assert vpgc._unmatched_paths(entry, vpgc._closure_view(root), root) != []

    def test_long_finding_list_is_truncated_in_the_printout(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """The COUNT of printed path lines is the assertion -- the trailing "... and N more" line
        survives deleting the slice, so asserting on it alone pins nothing."""
        overflow = 3
        hubs = vpgc._MAX_PRINTED_PATHS + overflow
        root = _make_repo(tmp_path)
        extra = "\n".join(f"from scripts.hub{i} import x" for i in range(hubs))
        for i in range(hubs):
            (root / "scripts" / f"hub{i}.py").write_text("def x():\n    pass\n", encoding="utf-8")
        (root / "scripts" / "checks" / "fake" / "validate_thing.py").write_text(
            f"{extra}\n\n\ndef validate_thing(failed):\n    pass\n", encoding="utf-8"
        )
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        failed, _declaration = _run_against(root, entries)
        out = capsys.readouterr().out
        printed_paths = [line for line in out.splitlines() if line.startswith("      - ")]
        assert not failed
        assert len(printed_paths) == vpgc._MAX_PRINTED_PATHS
        assert f"{hubs} closure path" in out
        assert f"... and {overflow} more" in out


class TestAdvisoryContractAndAccounting:
    """This stage NEVER appends to `failed` and NEVER raises -- and declares Decision 170
    accounting on all three of its reachable exit paths."""

    def test_never_fails_even_with_findings(self, tmp_path: Path) -> None:
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        failed, declaration = _run_against(_make_repo(tmp_path), entries)
        assert failed == []
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "gated_pre_checks"

    def test_examined_count_is_the_roster_size(self, tmp_path: Path) -> None:
        """A multi-entry roster: a constant would satisfy every single-entry fixture."""
        roster = {n: _entry(n, "scripts.checks.fake.validate_thing") for n in ("a_check", "b_check", "c_check")}
        failed, declaration = _run_against(_make_repo(tmp_path), roster)
        assert failed == []
        assert len(roster) == 3
        assert declaration.count == len(roster)

    def test_advisory_banner_and_summary_are_printed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        _run_against(_make_repo(tmp_path), entries)
        out = capsys.readouterr().out
        assert "ADVISORY" in out
        assert "validate_thing" in out
        assert "scripts/hublib.py" in out

    def test_clean_roster_prints_a_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing", pre_globs=("scripts/**",))
        failed, declaration = _run_against(_make_repo(tmp_path), {entry.name: entry})
        assert failed == []
        assert declaration.count == 1
        assert "PASS" in capsys.readouterr().out

    def test_empty_roster_is_vacuous_not_skipped(self, tmp_path: Path) -> None:
        """check-accounting.yaml's discrimination rule: an empty DOMAIN declares examined(0)."""
        failed, declaration = _run_against(_make_repo(tmp_path), {})
        assert failed == []
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert declaration.unit == "gated_pre_checks"

    def test_an_internal_error_is_a_loud_skip_not_an_aborted_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Decision 55 loud-skip precedent (derive_affected_tests): an ADVISORY check must not be
        able to abort --pre. Nothing wraps a check body -- validation_result.dispatch_recording
        calls fn(failed) bare -- so the guard has to live here."""
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        with patch.object(vpgc, "_closure_view", side_effect=RuntimeError("graph oracle exploded")):
            failed, declaration = _run_against(_make_repo(tmp_path), entries)
        out = capsys.readouterr().out
        assert failed == []
        assert declaration.kind == "skipped"
        assert "graph oracle exploded" in declaration.reason
        assert "SKIP" in out
        assert "graph oracle exploded" in out


class TestLiveTreeSmoke:
    """Advisory on the real repository: it must run green and declare a non-zero examination.
    Deliberately asserts NO backlog number -- that count is a moving target."""

    def test_runs_green_on_the_real_tree(self) -> None:
        failed: list[str] = []
        with registry.outcome_scope("validate_pre_glob_closure"):
            vpgc.validate_pre_glob_closure(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration.kind == "examined"
        assert declaration.unit == "gated_pre_checks"
        assert declaration.count > 0

    def test_its_own_entry_is_one_of_the_audited_ones(self) -> None:
        assert "validate_pre_glob_closure" in {e.name for e in vpgc._gated_entries()}

    def test_its_own_pre_globs_cover_its_own_closure(self) -> None:
        """Dogfood: the auditor's own Entry must have nothing to report about itself."""
        root = _common.ROOT
        entry = next(e for e in vpgc._gated_entries() if e.name == "validate_pre_glob_closure")
        assert vpgc._unmatched_paths(entry, vpgc._closure_view(root), root) == []
