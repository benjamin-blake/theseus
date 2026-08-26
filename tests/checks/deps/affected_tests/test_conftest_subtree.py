"""W2-D: a changed sub-conftest.py protects its ENTIRE subtree, not just when it happens to
declare an autouse fixture.

Pytest imports a conftest for every test collected beneath it -- a real, structural dependency,
not a heuristic (see affected_tests.py's module docstring, item 4). Before this change, only a
FORCING conftest (root or autouse-declaring) landed in the protected/uncapped set; an ORDINARY
conftest (e.g. tests/checks/conftest.py, which declares zero fixtures) fed the cappable residue
pool, so a change there could select as few as CAP=35 of its subtree and silently defer the rest
past the fast tier -- the exact rec-class this closes (affected-tests.md sec 2.1: a change to
tests/checks/conftest.py selected 35 of 176 governed files, deferring 141 with no budget waiver).

Split from tests/checks/deps/affected_tests/test_derivation.py's TestRootConftestForcesFullScope
(root/autouse coverage) and test_channels.py's TestConftestSubtreeChannel (basic subtree-selects
coverage) -- this module owns the protected-vs-cappable distinction specifically.
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks.deps import affected_tests as at
from tests.fixtures.affected_tests_helpers import write_file as _write


class TestOrdinarySubConftestIsProtected:
    """A non-root, non-autouse conftest change now protects its whole subtree -- the additive
    invariant applies to it exactly as it already does to the edited-set and direct import-deps."""

    def _plain_subtree_fixture(self, tmp_path: Path, n_tests: int) -> None:
        _write(tmp_path, "tests/pkg/conftest.py", "")
        for i in range(n_tests):
            _write(tmp_path, f"tests/pkg/test_{i:02d}.py", f"def test_{i}():\n    assert True\n")

    def test_ordinary_subtree_survives_a_cap_smaller_than_the_subtree(self, tmp_path: Path) -> None:
        """cap=1 is far below the 8-file subtree -- proves protection is unconditional, not
        merely 'usually big enough to fit under the default cap'."""
        self._plain_subtree_fixture(tmp_path, n_tests=8)
        result = at.derive_affected_tests([("M", "tests/pkg/conftest.py")], repo_root=tmp_path, cap=1)
        manifest = result["manifest"]
        for i in range(8):
            assert f"tests/pkg/test_{i:02d}.py" in result["selected"]
        assert manifest["capped"] is False
        assert manifest["deferred"] == []

    def test_ordinary_subtree_hit_provenance_is_conftest_subtree_structural(self, tmp_path: Path) -> None:
        self._plain_subtree_fixture(tmp_path, n_tests=2)
        result = at.derive_affected_tests([("M", "tests/pkg/conftest.py")], repo_root=tmp_path, cap=1)
        manifest = result["manifest"]
        assert manifest["provenance"]["tests/pkg/test_00.py"] == "conftest_subtree_structural"
        assert manifest["channels"]["conftest_subtree_structural"] == 2

    def test_autouse_and_ordinary_sub_conftests_both_protected_distinct_provenance(self, tmp_path: Path) -> None:
        """The forcing/ordinary split survives as a PROVENANCE distinction even though both are
        now equally uncapped -- an autouse conftest still reports conftest_subtree_forced
        (every test's behavior can change, not just its import graph)."""
        _write(
            tmp_path,
            "tests/autouse_pkg/conftest.py",
            "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _setup():\n    yield\n",
        )
        _write(tmp_path, "tests/autouse_pkg/test_a.py", "def test_a():\n    assert True\n")
        self._plain_subtree_fixture(tmp_path, n_tests=3)
        diff = [("M", "tests/autouse_pkg/conftest.py"), ("M", "tests/pkg/conftest.py")]
        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=1)
        manifest = result["manifest"]
        assert manifest["provenance"]["tests/autouse_pkg/test_a.py"] == "conftest_subtree_forced"
        assert manifest["provenance"]["tests/pkg/test_00.py"] == "conftest_subtree_structural"
        assert manifest["capped"] is False
        assert manifest["deferred"] == []
        # Root's full_suite_forced semantics are untouched by W2-D -- neither sub-conftest here
        # is the root, so the whole-suite waiver flag must not fire.
        assert manifest["full_suite_forced"] is False

    def test_unrelated_transitive_residue_still_capped_alongside_a_protected_subtree(self, tmp_path: Path) -> None:
        """The conftest subtree is unconditionally protected, but that must not leak protection
        onto an UNRELATED high-fanout transitive edit in the same diff -- only import-closure
        transitive residue remains cappable."""
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        _write(tmp_path, "scripts/deeper.py", "from scripts.mid import mid\n\ndef deeper():\n    mid()\n")
        for name in ("aaa", "bbb"):
            _write(
                tmp_path,
                f"tests/test_{name}_dep.py",
                f"from scripts.mid import mid\n\ndef test_{name}():\n    mid()\n",
            )
        _write(tmp_path, "tests/test_ccc_deeper.py", "from scripts.deeper import deeper\n\ndef test_c():\n    deeper()\n")
        self._plain_subtree_fixture(tmp_path, n_tests=2)
        diff = [("M", "scripts/base.py"), ("M", "tests/pkg/conftest.py")]
        # cap=2: the 2 protected conftest-subtree hits no longer consume the residue's budget
        # (it is fixed at cap), and the residue's own budget stops at the nearer distance layer --
        # proves the two mechanisms compose correctly, not just that the conftest channel is
        # protected.
        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=2)
        manifest = result["manifest"]
        assert "tests/pkg/test_00.py" in result["selected"]
        assert "tests/pkg/test_01.py" in result["selected"]
        assert "tests/test_aaa_dep.py" in result["selected"]
        assert "tests/test_bbb_dep.py" in result["selected"]
        assert manifest["capped"] is True
        assert manifest["deferred"] == ["tests/test_ccc_deeper.py"]


class TestChannelRoster:
    """The manifest's channel roster reflects the new channel and drops the retired one."""

    def test_conftest_subtree_structural_is_protected_and_named(self) -> None:
        assert "conftest_subtree_structural" in at._PROTECTED_CHANNELS
        assert "conftest_subtree_structural" in at.CHANNEL_NAMES

    def test_old_cappable_conftest_subtree_name_is_retired(self) -> None:
        assert "conftest_subtree" not in at.CHANNEL_NAMES

    def test_empty_diff_manifest_lists_the_new_channel_at_zero(self, tmp_path: Path) -> None:
        result = at.derive_affected_tests([], repo_root=tmp_path)
        assert result["manifest"]["channels"]["conftest_subtree_structural"] == 0


class TestRealRepoReplay:
    """Real-repo replay of the exact recall gap named in the recon (affected-tests.md sec 2.1):
    a change to tests/checks/conftest.py (176+ governed test files, zero fixtures declared, so
    it was classified ORDINARY/cappable pre-fix) selected only CAP=35 and deferred the rest with
    no budget waiver. Bounds are used instead of exact counts (Decision/tests/CLAUDE.md
    'Test-count coupling') since the governed subtree grows over time."""

    def test_tests_checks_conftest_change_selects_its_whole_subtree_uncapped(self) -> None:
        governed = sorted(p.as_posix() for p in Path("tests/checks").rglob("test_*.py"))
        assert len(governed) >= 100, "premise: tests/checks/ must still be a large subtree for this replay to mean anything"

        result = at.derive_affected_tests([("M", "tests/checks/conftest.py")])
        manifest = result["manifest"]

        assert manifest["capped"] is False
        assert manifest["deferred"] == []
        assert set(governed) <= set(result["selected"])
        assert manifest["channels"]["conftest_subtree_structural"] == len(governed)
        for path in governed[:5]:
            assert manifest["provenance"][path] == "conftest_subtree_structural"

    def test_small_ordinary_sub_conftest_change_selects_its_whole_subtree_uncapped(self) -> None:
        subtree_dir = Path("tests/checks/contracts/validate_contract_drift")
        governed = sorted(p.as_posix() for p in subtree_dir.rglob("test_*.py"))
        assert 5 <= len(governed) <= 34, "premise: stays well under CAP so a pre-fix run would NOT have needed to defer"

        result = at.derive_affected_tests([("M", f"{subtree_dir.as_posix()}/conftest.py")])
        manifest = result["manifest"]

        assert manifest["capped"] is False
        assert set(governed) <= set(result["selected"])
        for path in governed:
            assert manifest["provenance"][path] == "conftest_subtree_structural"
