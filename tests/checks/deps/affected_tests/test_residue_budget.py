"""Cap-mechanics tests for the transitive-residue budget (_residue_keep_set).

These distil the failure the real-repo pin at
tests/checks/registry/test_manifest_contracts.py::TestAffectedSetSurvival exists to catch, without
paying its build_graph() cost: growing the PROTECTED set (a channel promotion, or a faithful
graph edge that widens the import closure) used to consume the residue's budget and evict
transitive tests the previous revision had kept, and alphabetical truncation decided which ones
survived by filename rather than by relevance.

Every fixture drives the REAL selector against a self-contained tmp_path repo. The chain
scripts/base.py <- scripts/l1.py <- ... puts each test module at a KNOWN import distance from the
changed file, which is the ranking these tests assert on.
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks.deps import affected_tests as at
from tests.fixtures.affected_tests_helpers import write_file as _write


def _chain(tmp_path: Path, depth: int) -> None:
    """scripts/base.py <- scripts/l1.py <- ... <- scripts/l{depth}.py, one import hop each."""
    _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
    previous = "base"
    for level in range(1, depth + 1):
        _write(tmp_path, f"scripts/l{level}.py", f"from scripts.{previous} import do\n\ndef do():\n    pass\n")
        previous = f"l{level}"


def _test_on(tmp_path: Path, name: str, level: int) -> None:
    """A test module importing scripts/l{level}.py -- import distance level+1 from base.py."""
    _write(tmp_path, f"tests/{name}", f"from scripts.l{level} import do\n\ndef test_x():\n    do()\n")


class TestResidueBudgetIsFixed:
    """The residue's budget is CAP itself, never `CAP - len(protected)` -- protected growth can
    no longer evict residue that fits."""

    def test_residue_survives_a_protected_set_that_fills_the_whole_cap(self, tmp_path: Path) -> None:
        """The blocker, distilled: protected alone reaches the cap, so the old shared budget was
        max(cap - len(protected), 0) == 0 and the ENTIRE residue was deferred."""
        _chain(tmp_path, depth=1)
        _test_on(tmp_path, "test_transitive.py", level=1)
        _write(tmp_path, "tests/test_edited_a.py", "def test_a():\n    assert True\n")
        _write(tmp_path, "tests/test_edited_b.py", "def test_b():\n    assert True\n")
        diff = [("M", "scripts/base.py"), ("M", "tests/test_edited_a.py"), ("M", "tests/test_edited_b.py")]

        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=2)

        manifest = result["manifest"]
        assert "tests/test_transitive.py" in result["selected"]
        assert manifest["provenance"]["tests/test_transitive.py"] == "import_closure_transitive"
        assert manifest["deferred"] == []
        assert manifest["residue_budget"] == 2

    def test_residue_budget_does_not_shrink_as_protected_grows(self, tmp_path: Path) -> None:
        """Same residue, same cap, more protected hits -> identical residue keep-set. Under the
        shared budget the second call kept strictly fewer transitive tests than the first."""
        _chain(tmp_path, depth=1)
        for name in ("aaa", "bbb", "ccc"):
            _test_on(tmp_path, f"test_{name}_transitive.py", level=1)

        lean = at.derive_affected_tests([("M", "scripts/base.py")], repo_root=tmp_path, cap=3)
        _write(tmp_path, "tests/test_edited.py", "def test_e():\n    assert True\n")
        fat = at.derive_affected_tests([("M", "scripts/base.py"), ("M", "tests/test_edited.py")], repo_root=tmp_path, cap=3)

        assert set(lean["selected"]) <= set(fat["selected"])
        assert set(fat["selected"]) - set(lean["selected"]) == {"tests/test_edited.py"}


class TestNearestFirstRanking:
    """Residue is kept nearest-first by import distance, in whole BFS layers -- not alphabetically,
    which is what evicted the alphabetically-late registry driver tests."""

    def test_nearer_residue_outranks_an_alphabetically_earlier_distant_one(self, tmp_path: Path) -> None:
        """cap == len(protected) zeroes the no-regression floor, isolating the ranking. Purely
        alphabetical truncation would have kept test_aaa_d4 and deferred both nearer modules."""
        _chain(tmp_path, depth=3)
        _test_on(tmp_path, "test_zzz_d2.py", level=1)
        _test_on(tmp_path, "test_yyy_d3.py", level=2)
        _test_on(tmp_path, "test_aaa_d4.py", level=3)
        _write(tmp_path, "tests/test_edited_a.py", "def test_a():\n    assert True\n")
        _write(tmp_path, "tests/test_edited_b.py", "def test_b():\n    assert True\n")
        diff = [("M", "scripts/base.py"), ("M", "tests/test_edited_a.py"), ("M", "tests/test_edited_b.py")]

        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=2)

        manifest = result["manifest"]
        assert set(result["selected"]) == {
            "tests/test_edited_a.py",
            "tests/test_edited_b.py",
            "tests/test_zzz_d2.py",
            "tests/test_yyy_d3.py",
        }
        assert manifest["deferred"] == ["tests/test_aaa_d4.py"]
        assert manifest["capped"] is True
        assert manifest["residue_kept_depth"] == 3
        assert manifest["residue_ranking"] == "bfs_distance_layers_then_path"

    def test_a_distance_layer_is_never_split_by_filename(self, tmp_path: Path) -> None:
        """The layer that reaches the budget is kept WHOLE: three siblings at one distance carry
        identical relevance evidence, so a cap of 1 must not keep only the alphabetically first."""
        _chain(tmp_path, depth=2)
        for name in ("aaa", "bbb", "ccc"):
            _test_on(tmp_path, f"test_{name}_d2.py", level=1)
        _test_on(tmp_path, "test_ddd_d3.py", level=2)
        _write(tmp_path, "tests/test_edited.py", "def test_e():\n    assert True\n")
        diff = [("M", "scripts/base.py"), ("M", "tests/test_edited.py")]

        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=1)

        assert set(result["selected"]) == {
            "tests/test_edited.py",
            "tests/test_aaa_d2.py",
            "tests/test_bbb_d2.py",
            "tests/test_ccc_d2.py",
        }
        assert result["manifest"]["deferred"] == ["tests/test_ddd_d3.py"]


class TestNoRegressionFloor:
    """Whatever the superseded `cap - len(protected)` alphabetical accounting kept is still kept,
    so the switch to distance ranking cannot defer a module the previous revision ran."""

    def test_alphabetical_prefix_the_old_accounting_kept_is_never_evicted(self, tmp_path: Path) -> None:
        """test_aaa_d4 is the alphabetically-first residue member and the most DISTANT one: the
        floor keeps it alongside the nearest layer, so neither revision's keep-set is lost."""
        _chain(tmp_path, depth=3)
        _test_on(tmp_path, "test_zzz_d2.py", level=1)
        _test_on(tmp_path, "test_aaa_d4.py", level=3)

        result = at.derive_affected_tests([("M", "scripts/base.py")], repo_root=tmp_path, cap=1)

        assert set(result["selected"]) == {"tests/test_zzz_d2.py", "tests/test_aaa_d4.py"}
        assert result["manifest"]["deferred"] == []
