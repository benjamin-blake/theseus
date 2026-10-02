"""Check-accounting declaration tests for validate_check_manifests() (Decision 170)."""

import importlib
from pathlib import Path
from unittest.mock import patch

import networkx as nx

from scripts.checks import registry, validation_result
from scripts.checks.deps.validate_check_manifests import validate_check_manifests

_REPO_ROOT = Path(__file__).parents[3]

_CONTRACT = """\
entry_grammar:
  declared_segment_tokens:
    - full_after_lint
    - full_after_unit_tests
    - full_after_terraform_checks
    - full_after_dependency_health
    - full_after_ensure_fresh_dq
"""

_ENTRY = 'Entry(name="{name}", module="{module}", attr="{name}")'


class TestCheckManifestsAccountingDeclaration:
    """The evaluator declares how many manifest Entry(...) calls it checked for the module=/attr=
    grammar across every scripts/checks/*/_manifest.py, so a run is recorded enforced with a count
    that tracks the registered-check roster instead of undeclared."""

    _UNIT = "manifest_entries"

    @staticmethod
    def _declare(root: Path, graph_nodes: tuple[str, ...] = ()) -> tuple[list[str], registry._Declaration | None]:
        graph = nx.DiGraph()
        graph.add_nodes_from(graph_nodes)
        registry.pop_declaration()
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", root),
            patch("scripts.dependency_graph.build_graph", return_value=graph),
        ):
            validate_check_manifests(failed)
        return failed, registry.pop_declaration()

    @staticmethod
    def _write(root: Path, domains: dict[str, list[str]]) -> None:
        for domain, modules in domains.items():
            manifest_dir = root / "scripts" / "checks" / domain
            manifest_dir.mkdir(parents=True, exist_ok=True)
            calls = "".join(_ENTRY.format(name=m.rsplit(".", 1)[-1], module=m) + ",\n    " for m in modules)
            body = f"from scripts.checks._schema import Entry\n\nENTRIES = (\n    {calls})\n"
            (manifest_dir / "_manifest.py").write_text(body, encoding="utf-8")
        contracts_dir = root / "docs" / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / "check-manifest.yaml").write_text(_CONTRACT, encoding="utf-8")

    def test_real_tree_declares_every_manifest_entry(self) -> None:
        expected = sum(
            len(importlib.import_module(f"scripts.checks.{path.parent.name}._manifest").ENTRIES)
            for path in (_REPO_ROOT / "scripts" / "checks").glob("*/_manifest.py")
        )
        registry.pop_declaration()
        failed: list[str] = []
        validate_check_manifests(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, self._UNIT)

    def test_declared_count_sums_entries_across_manifests(self, tmp_path: Path) -> None:
        mods = [f"scripts.checks.{d}.validate_{d}_{i}" for d in ("alpha", "beta") for i in range(3)]
        self._write(tmp_path, {"alpha": mods[:1], "beta": mods[3:5]})
        failed, base = self._declare(tmp_path, tuple(mods))
        self._write(tmp_path, {"alpha": mods[:3], "beta": mods[3:]})
        grown_failed, grown = self._declare(tmp_path, tuple(mods))
        assert failed == [] and grown_failed == []
        assert base is not None and grown is not None
        assert (base.count, grown.count) == (3, 6)

    def test_failing_entries_still_counted(self, tmp_path: Path) -> None:
        good = "scripts.checks.alpha.validate_good"
        self._write(tmp_path, {"alpha": [good, "scripts.checks.alpha:validate_colon", "scripts.checks.alpha.validate_gone"]})
        failed, declaration = self._declare(tmp_path, (good,))
        assert len(failed) == 2
        assert declaration is not None and declaration.count == 3

    def test_manifests_without_entries_declare_empty_domain(self, tmp_path: Path) -> None:
        self._write(tmp_path, {"alpha": [], "beta": []})
        failed, declaration = self._declare(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, self._UNIT)

    def test_real_tree_is_recorded_enforced(self) -> None:
        validation_result._OUTCOMES.clear()
        try:
            validation_result.dispatch_recording("validate_check_manifests", [], validate_check_manifests)
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert (outcome.status, outcome.examined_unit) == ("enforced", self._UNIT)
        assert outcome.examined_count is not None and outcome.examined_count > 0
