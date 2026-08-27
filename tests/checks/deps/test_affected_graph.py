"""Direct unit tests for scripts/checks/deps/affected_graph.py -- the graph/structural half of
the --pre affected-set channel roster (Decision 135).

Every test here calls the channel function UNDER TEST directly rather than driving
derive_affected_tests(), because this module's mirror-test coverage is measured on its own
(scripts/checks/misc/coverage_baseline.py runs exactly this file with --cov=scripts/checks/deps):
coverage that only arrives through the orchestrator in
tests/checks/deps/affected_tests/ counts for affected_tests.py, never for this module. The
derivation-level tests that exercise these same channels end-to-end stay where they are.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

from scripts.checks.deps import affected_graph as ag
from tests.fixtures.affected_tests_helpers import write_file as _write


class TestChangedPathPredicates:
    """The admission rule deciding which changed paths the graph channels may follow."""

    def test_source_py_predicate_admits_only_non_test_src_and_scripts(self) -> None:
        assert ag._is_changed_source_py("scripts/foo.py")
        assert ag._is_changed_source_py("src/pkg/bar.py")
        assert not ag._is_changed_source_py("scripts/foo.yaml"), "not a .py file"
        assert not ag._is_changed_source_py("docs/foo.py"), "outside src/ and scripts/"
        assert not ag._is_changed_source_py("tests/test_foo.py"), "a test file is the edited set"

    def test_tests_helper_predicate_admits_only_non_test_non_conftest_tests_py(self) -> None:
        assert ag._is_changed_tests_helper_py("tests/fixtures/helper.py")
        assert not ag._is_changed_tests_helper_py("tests/fixtures/helper.yaml"), "not a .py file"
        assert not ag._is_changed_tests_helper_py("scripts/helper.py"), "outside tests/"
        assert not ag._is_changed_tests_helper_py("tests/test_helper.py"), "a test file is the edited set"
        assert not ag._is_changed_tests_helper_py("tests/pkg/conftest.py"), "conftest has its own channel"


class TestModuleToTestPath:
    """Mapping a graph module dotted-name back to a live tests/**/test_*.py path."""

    def test_non_test_shaped_module_returns_none(self, tmp_path: Path) -> None:
        """A package or non-test module never reconstructs to a test path."""
        assert ag._module_to_test_path("tests.pkg", tmp_path) is None
        assert ag._module_to_test_path("scripts.checks.registry", tmp_path) is None

    def test_test_shaped_module_absent_from_disk_returns_none(self, tmp_path: Path) -> None:
        """The regex matches but nothing is there -- a stale graph node, not a selectable test."""
        assert ag._module_to_test_path("tests.foo.test_ghost", tmp_path) is None

    def test_test_shaped_module_present_on_disk_returns_its_relative_path(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/foo/test_real.py", "def test_x():\n    assert True\n")
        assert ag._module_to_test_path("tests.foo.test_real", tmp_path) == "tests/foo/test_real.py"


class TestImportClosureChannel:
    """The reverse-BFS channel: direct importers, transitive residue, and the distance rank."""

    def test_no_candidates_skips_the_graph_build_entirely(self, tmp_path: Path) -> None:
        assert ag._import_closure_channel([], tmp_path) == (set(), set(), {})

    def test_changed_file_with_no_graph_node_contributes_nothing(self, tmp_path: Path) -> None:
        """A path that maps to a dotted name absent from the graph is skipped, not an error."""
        _write(tmp_path, "scripts/placeholder.py", "x = 1\n")
        assert ag._import_closure_channel(["scripts/does_not_exist.py"], tmp_path) == (set(), set(), {})

    def test_direct_transitive_and_distance_are_split_by_import_hops(self, tmp_path: Path) -> None:
        """A direct importer is 1 hop; its own importer is 2 and lands in the residue."""
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        _write(tmp_path, "tests/test_direct.py", "from scripts.base import do\n\ndef test_d():\n    do()\n")
        _write(tmp_path, "tests/test_indirect.py", "from scripts.mid import mid\n\ndef test_i():\n    mid()\n")

        direct, transitive, distance = ag._import_closure_channel(["scripts/base.py"], tmp_path)

        assert direct == {"tests/test_direct.py"}
        assert transitive == {"tests/test_indirect.py"}
        assert distance == {"tests/test_direct.py": 1, "tests/test_indirect.py": 2}
        assert "scripts/mid.py" not in distance, "a non-test reachable module is not a selectable test"

    def test_nearest_hop_count_wins_across_several_changed_modules(self, tmp_path: Path) -> None:
        """Two changed modules reach the same test at different depths -- the closer one ranks it."""
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        _write(tmp_path, "tests/test_far.py", "from scripts.mid import mid\n\ndef test_f():\n    mid()\n")

        _, _, far_only = ag._import_closure_channel(["scripts/base.py"], tmp_path)
        assert far_only == {"tests/test_far.py": 2}

        direct, _, both = ag._import_closure_channel(["scripts/base.py", "scripts/mid.py"], tmp_path)
        assert both == {"tests/test_far.py": 1}, "the nearer changed module sets the distance"
        assert direct == {"tests/test_far.py"}


class TestModuleImportsAny:
    """The ast predicate behind the tests-tree direct-importer scan."""

    @staticmethod
    def _tree(source: str) -> ast.Module:
        return ast.parse(source)

    def test_plain_import_of_an_exact_name_matches(self) -> None:
        assert ag._module_imports_any(self._tree("import tests.fixtures.helper\n"), {"tests.fixtures.helper"})

    def test_plain_import_of_a_submodule_of_a_changed_package_matches(self) -> None:
        assert ag._module_imports_any(self._tree("import tests.fixtures.helper.deep\n"), {"tests.fixtures.helper"})

    def test_from_import_of_an_exact_name_matches(self) -> None:
        assert ag._module_imports_any(self._tree("from tests.fixtures.helper import VALUE\n"), {"tests.fixtures.helper"})

    def test_from_import_of_a_submodule_of_a_changed_package_matches(self) -> None:
        assert ag._module_imports_any(self._tree("from tests.fixtures.helper.deep import V\n"), {"tests.fixtures.helper"})

    def test_unrelated_imports_do_not_match(self) -> None:
        source = "import os\nfrom pathlib import Path\nimport tests.fixtures.other\nfrom . import sibling\n"
        assert ag._module_imports_any(self._tree(source), {"tests.fixtures.helper"}) is False

    def test_prefix_collision_is_not_a_match(self) -> None:
        """'tests.fixtures.helper_extra' is a different module, not a submodule."""
        assert ag._module_imports_any(self._tree("import tests.fixtures.helper_extra\n"), {"tests.fixtures.helper"}) is False


class TestTestsTreeImportClosureChannel:
    """The self-contained scan supplying the direct-importer signal build_graph() cannot."""

    def test_no_candidates_skips_the_scan(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        assert ag._tests_tree_import_closure_channel([], tmp_path) == set()

    def test_absent_tests_tree_skips_the_scan(self, tmp_path: Path) -> None:
        assert ag._tests_tree_import_closure_channel(["tests/fixtures/helper.py"], tmp_path) == set()

    def test_candidate_resolving_to_no_dotted_name_skips_the_scan(self, tmp_path: Path) -> None:
        """Nothing to match against, so the scan is skipped rather than matched against {}."""
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        assert ag._tests_tree_import_closure_channel(["notes.txt"], tmp_path) == set()

    def test_direct_importers_are_selected_and_others_are_not(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/fixtures/helper.py", "VALUE = 1\n")
        _write(
            tmp_path,
            "tests/test_from_importer.py",
            "from tests.fixtures.helper import VALUE\n\ndef test_x():\n    assert VALUE\n",
        )
        _write(
            tmp_path,
            "tests/test_plain_importer.py",
            "import tests.fixtures.helper\n\ndef test_x():\n    assert tests.fixtures.helper.VALUE\n",
        )
        _write(tmp_path, "tests/test_unrelated.py", "def test_y():\n    assert True\n")

        assert ag._tests_tree_import_closure_channel(["tests/fixtures/helper.py"], tmp_path) == {
            "tests/test_from_importer.py",
            "tests/test_plain_importer.py",
        }

    def test_pycache_artifacts_are_never_selected(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/fixtures/helper.py", "VALUE = 1\n")
        importer = "from tests.fixtures.helper import VALUE\n\ndef test_x():\n    assert VALUE\n"
        _write(tmp_path, "tests/test_real_importer.py", importer)
        _write(tmp_path, "tests/__pycache__/test_stale_importer.py", importer)

        assert ag._tests_tree_import_closure_channel(["tests/fixtures/helper.py"], tmp_path) == {"tests/test_real_importer.py"}

    def test_unparseable_test_file_is_skipped_without_losing_its_siblings(self, tmp_path: Path) -> None:
        """Decision 55: one malformed file degrades narrowly, it never takes the scan down."""
        _write(tmp_path, "tests/fixtures/helper.py", "VALUE = 1\n")
        _write(tmp_path, "tests/test_broken.py", "def test_x(:\n")
        _write(
            tmp_path,
            "tests/test_good.py",
            "from tests.fixtures.helper import VALUE\n\ndef test_x():\n    assert VALUE\n",
        )

        assert ag._tests_tree_import_closure_channel(["tests/fixtures/helper.py"], tmp_path) == {"tests/test_good.py"}


class TestMirrorMapChannel:
    """Read-only use of map_source_to_test(), expanded to the one-module-per-entry grain."""

    def test_source_with_no_mirror_target_contributes_nothing(self, tmp_path: Path) -> None:
        """scripts/executor/** deliberately maps to None (Decision 124) -- skipped, not an error."""
        _write(tmp_path, "scripts/executor/step_runner.py", "def run():\n    pass\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            assert ag._mirror_map_channel(["scripts/executor/step_runner.py"], tmp_path) == set()

    def test_file_mirror_target_present_on_disk_is_selected(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/checks/hygiene/validate_something.py", "def validate_something(failed):\n    pass\n")
        _write(tmp_path, "tests/checks/hygiene/test_validate_something.py", "def test_x():\n    assert True\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            hits = ag._mirror_map_channel(["scripts/checks/hygiene/validate_something.py"], tmp_path)
        assert hits == {"tests/checks/hygiene/test_validate_something.py"}

    def test_file_mirror_target_absent_from_disk_is_not_selected(self, tmp_path: Path) -> None:
        """A mapping is not a promise the file exists -- an unwritten mirror selects nothing."""
        _write(tmp_path, "scripts/checks/hygiene/validate_something.py", "def validate_something(failed):\n    pass\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            assert ag._mirror_map_channel(["scripts/checks/hygiene/validate_something.py"], tmp_path) == set()

    def test_package_mirror_target_expands_to_its_test_modules(self, tmp_path: Path) -> None:
        """A concern-split mapping resolves to a directory; the channel emits its test modules."""
        _write(tmp_path, "scripts/ops_writer.py", "def write():\n    pass\n")
        _write(tmp_path, "tests/ops_writer/test_write.py", "def test_write():\n    assert True\n")
        _write(tmp_path, "tests/ops_writer/nested/test_retry.py", "def test_retry():\n    assert True\n")
        _write(tmp_path, "tests/ops_writer/helper.py", "VALUE = 1\n")
        _write(tmp_path, "tests/ops_writer/__pycache__/test_cached.py", "garbage\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            hits = ag._mirror_map_channel(["scripts/ops_writer.py"], tmp_path)
        assert hits == {"tests/ops_writer/test_write.py", "tests/ops_writer/nested/test_retry.py"}
