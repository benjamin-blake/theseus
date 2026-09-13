"""Mirror test for scripts/checks/deps/validate_pre_glob_closure.py (D2-3, rec-3289): glob-matcher
equivalence, closure traversal, gated-entry selection, synthetic end-to-end closure behaviour, and
the derived inert-module floor (wave 4b pay-down).

Split out of the former single-file mirror (Decision 128 decompose-by-default) alongside
test_pruned_edges_roster.py and test_blocking_contract.py. This file's classes are relocated
unchanged from the pre-decomposition suite except for TestInertFloorDiscrimination, which is new.
"""

from __future__ import annotations

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
    defaults: dict[str, Any] = {"pre": True, "pre_globs": ("scripts/checks/**",), "full_segment": "full_after_lint"}
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
        failed: list[str] = []
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", entries):
            with registry.outcome_scope("validate_pre_glob_closure"):
                vpgc.validate_pre_glob_closure(failed)
        out = capsys.readouterr().out
        printed_paths = [line for line in out.splitlines() if line.startswith("      - ")]
        assert failed != []
        assert len(printed_paths) == vpgc._MAX_PRINTED_PATHS
        assert f"{hubs} closure path" in out
        assert f"... and {overflow} more" in out


class TestInertFloorDiscrimination:
    """VP step 6: the derived inert-module floor. MEASURED PROBLEM this exists to close: on the
    live tree the correct rule and a naive `len(tree.body) <= 1` heuristic select the IDENTICAL 5
    modules (all __init__.py), so a two-fixture test would prove nothing about the rule itself.
    Four fixtures separate the rule from the heuristic and from a filename-keyed rule."""

    def test_docstring_only_module_is_trivial(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text('"""Just a docstring."""\n', encoding="utf-8")
        assert vpgc._module_body_is_trivial("m.py", tmp_path) is True

    def test_docstring_plus_one_statement_is_reported(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text('"""Docstring."""\nX = 1\n', encoding="utf-8")
        assert vpgc._module_body_is_trivial("m.py", tmp_path) is False

    def test_no_docstring_exactly_one_statement_is_reported(self, tmp_path: Path) -> None:
        """The fixture that separates the rule from the length heuristic: len(body) == 1 here
        too, but the one statement is not a docstring, so `len(tree.body) <= 1` would wrongly
        exclude it while the real rule reports it."""
        (tmp_path / "m.py").write_text("X = 1\n", encoding="utf-8")
        assert vpgc._module_body_is_trivial("m.py", tmp_path) is False

    def test_non_init_docstring_only_module_is_also_trivial(self, tmp_path: Path) -> None:
        """Proves the rule is keyed on the AST body, never on the filename being __init__.py."""
        (tmp_path / "not_init.py").write_text('"""Just a docstring, not an __init__.py."""\n', encoding="utf-8")
        assert vpgc._module_body_is_trivial("not_init.py", tmp_path) is True

    def test_docstring_plus_future_import_is_reported(self, tmp_path: Path) -> None:
        """Ruling: `docstring + from __future__ import annotations` is REPORTED -- the import is
        an executable statement."""
        (tmp_path / "m.py").write_text('"""Docstring."""\nfrom __future__ import annotations\n', encoding="utf-8")
        assert vpgc._module_body_is_trivial("m.py", tmp_path) is False

    def test_empty_module_is_trivial(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("", encoding="utf-8")
        assert vpgc._module_body_is_trivial("m.py", tmp_path) is True

    def test_unreadable_module_is_not_trivial(self, tmp_path: Path) -> None:
        assert vpgc._module_body_is_trivial("does_not_exist.py", tmp_path) is False

    def test_unparseable_module_is_not_trivial(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("def broken(:\n", encoding="utf-8")
        assert vpgc._module_body_is_trivial("m.py", tmp_path) is False

    def test_floor_suppresses_a_trivial_uncovered_module_without_dropping_it_from_the_closure(self, tmp_path: Path) -> None:
        """End-to-end through _uncovered_and_suppressed: a trivial module in the closure moves
        from reported to suppressed -- it is never simply dropped from the closure itself."""
        root = _make_repo(tmp_path)
        (root / "scripts" / "checks" / "fake" / "validate_thing.py").write_text(
            "from scripts.hublib import hub\nimport scripts.trivial_hub\n\n\ndef validate_thing(failed):\n    hub()\n",
            encoding="utf-8",
        )
        (root / "scripts" / "trivial_hub.py").write_text('"""Just a docstring."""\n', encoding="utf-8")
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing")
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", {entry.name: entry}):
            view = vpgc._closure_view(root)
            reported, suppressed = vpgc._uncovered_and_suppressed(entry, view, root)
            closure = vpgc._closure_modules(view, entry.module)
        assert "scripts/hublib.py" in reported
        assert "scripts/trivial_hub.py" in suppressed
        assert "scripts/trivial_hub.py" not in reported
        assert "scripts.trivial_hub" in closure

    def test_unresolvable_module_never_reaches_the_floor(self, tmp_path: Path) -> None:
        """An unresolvable Entry.module is reported as the unresolvable-module finding with an
        empty suppressed list -- it is never eligible for the inert-module floor."""
        root = _make_repo(tmp_path)
        entry = _entry("ghost", "scripts.checks.fake.ghost")
        with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", {entry.name: entry}):
            view = vpgc._closure_view(root)
            reported, suppressed = vpgc._uncovered_and_suppressed(entry, view, root)
        assert reported == ["<module not in the import graph: scripts.checks.fake.ghost>"]
        assert suppressed == []
