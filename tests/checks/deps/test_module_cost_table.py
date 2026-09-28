"""Decision 131 mirror for scripts/checks/deps/module_cost_table.py -- full per-file coverage from
this module alone (Decision 208 VP step 6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks.deps import module_cost_table as mct

_GIT_ENV = ["-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _write_junit(path: Path, cases: list[tuple[str, str, float]]) -> None:
    """cases: (file, name, time)."""
    testcases = "".join(f'<testcase classname="c" name="{name}" file="{f}" time="{t}"/>' for f, name, t in cases)
    path.write_text(f'<testsuite name="s">{testcases}</testsuite>', encoding="utf-8")


class TestGenerate:
    def test_sums_per_file_across_junit_files(self, tmp_path: Path) -> None:
        j1 = tmp_path / "a.xml"
        j2 = tmp_path / "b.xml"
        _write_junit(j1, [("tests/test_a.py", "t1", 1.5), ("tests/test_a.py", "t2", 0.5), ("tests/test_b.py", "t3", 2.0)])
        _write_junit(j2, [("tests/test_a.py", "t4", 1.0)])
        totals = mct.generate([j1, j2])
        assert totals == {"tests/test_a.py": 3.0, "tests/test_b.py": 2.0}

    def test_fails_loudly_without_file_attribute(self, tmp_path: Path) -> None:
        j = tmp_path / "bad.xml"
        j.write_text('<testsuite><testcase classname="c" name="t" time="1.0"/></testsuite>', encoding="utf-8")
        with pytest.raises(ValueError, match="junit_family=xunit1"):
            mct.generate([j])


class TestCli:
    def test_output_banner_is_first_key_and_round_trips(self, tmp_path: Path) -> None:
        j = tmp_path / "j.xml"
        _write_junit(j, [("tests/test_a.py", "t1", 1.5)])
        out = tmp_path / "table.json"
        rc = mct.main(["--junit", str(j), "--write", str(out)])
        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert next(iter(data)) == "_banner"
        assert "DO NOT EDIT" in data["_banner"]
        assert data["modules"] == {"tests/test_a.py": 1.5}


class TestReadAtBaseRef:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        origin = tmp_path / "origin.git"
        origin.mkdir()
        _git(["init", "--bare", "-b", "main"], cwd=origin)
        work = tmp_path / "work"
        work.mkdir()
        _git(["init", "-b", "main"], cwd=work)
        _git(["remote", "add", "origin", str(origin)], cwd=work)
        (work / "README.md").write_text("hello\n", encoding="utf-8")
        _git(["add", "-A"], cwd=work)
        _git([*_GIT_ENV, "commit", "-m", "initial"], cwd=work)
        _git(["push", "-u", "origin", "main"], cwd=work)
        return work

    def test_absent_when_merge_base_resolves_and_path_missing(self, repo: Path) -> None:
        read = mct.read_at_base_ref(repo)
        assert read.status == "absent"
        assert read.costs == {}

    def test_ok_when_table_committed_at_the_merge_base(self, repo: Path) -> None:
        table_dir = repo / "config" / "agent" / "fast_tier"
        table_dir.mkdir(parents=True)
        table = {
            "_banner": "GENERATED",
            "modules": {"tests/test_a.py": 1.0, "tests/test_b.py": 2.0, "tests/test_c.py": 100.0},
        }
        (table_dir / "module_costs.json").write_text(json.dumps(table), encoding="utf-8")
        _git(["add", "-A"], cwd=repo)
        _git([*_GIT_ENV, "commit", "-m", "add table"], cwd=repo)
        _git(["push", "origin", "main"], cwd=repo)

        read = mct.read_at_base_ref(repo)
        assert read.status == "ok"
        assert read.costs == {"tests/test_a.py": 1.0, "tests/test_b.py": 2.0, "tests/test_c.py": 100.0}
        assert read.default_cost > 0

    def test_working_tree_edit_does_not_win_over_the_base_copy(self, repo: Path) -> None:
        """A PR cannot inflate its own allowance: only the merge-base's committed table is read."""
        table_dir = repo / "config" / "agent" / "fast_tier"
        table_dir.mkdir(parents=True)
        table_path = table_dir / "module_costs.json"
        table_path.write_text(json.dumps({"_banner": "GENERATED", "modules": {"tests/test_a.py": 1.0}}), encoding="utf-8")
        _git(["add", "-A"], cwd=repo)
        _git([*_GIT_ENV, "commit", "-m", "add table"], cwd=repo)
        _git(["push", "origin", "main"], cwd=repo)

        # A PR-branch edit inflating the WORKING TREE table must be ignored.
        table_path.write_text(json.dumps({"_banner": "GENERATED", "modules": {"tests/test_a.py": 999999.0}}), encoding="utf-8")

        read = mct.read_at_base_ref(repo)
        assert read.costs == {"tests/test_a.py": 1.0}

    def test_unreadable_when_no_origin_main_ref(self, tmp_path: Path) -> None:
        work = tmp_path / "solo"
        work.mkdir()
        _git(["init", "-b", "main"], cwd=work)
        (work / "README.md").write_text("hi\n", encoding="utf-8")
        _git(["add", "-A"], cwd=work)
        _git([*_GIT_ENV, "commit", "-m", "initial"], cwd=work)

        read = mct.read_at_base_ref(work)
        assert read.status == "unreadable"

    def test_unreadable_when_ls_tree_fails(self, repo: Path) -> None:
        def _fake_git(root, *args):
            if args[0] == "merge-base":
                return MagicMock(returncode=0, stdout="deadbeef\n")
            if args[0] == "ls-tree":
                return MagicMock(returncode=128, stdout="")
            raise AssertionError(f"unexpected git call: {args}")

        with patch("scripts.checks.deps.module_cost_table._git", side_effect=_fake_git):
            assert mct.read_at_base_ref(repo).status == "unreadable"

    def test_unreadable_when_git_show_fails(self, repo: Path) -> None:
        def _fake_git(root, *args):
            if args[0] == "merge-base":
                return MagicMock(returncode=0, stdout="deadbeef\n")
            if args[0] == "ls-tree":
                return MagicMock(returncode=0, stdout="100644 blob abc\tconfig/agent/fast_tier/module_costs.json\n")
            if args[0] == "show":
                return MagicMock(returncode=128, stdout="")
            raise AssertionError(f"unexpected git call: {args}")

        with patch("scripts.checks.deps.module_cost_table._git", side_effect=_fake_git):
            assert mct.read_at_base_ref(repo).status == "unreadable"

    def test_unreadable_when_table_has_no_modules(self, repo: Path) -> None:
        table_dir = repo / "config" / "agent" / "fast_tier"
        table_dir.mkdir(parents=True)
        (table_dir / "module_costs.json").write_text(json.dumps({"_banner": "GENERATED", "modules": {}}), encoding="utf-8")
        _git(["add", "-A"], cwd=repo)
        _git([*_GIT_ENV, "commit", "-m", "empty table"], cwd=repo)
        _git(["push", "origin", "main"], cwd=repo)

        read = mct.read_at_base_ref(repo)
        assert read.status == "unreadable"

    def test_unreadable_on_invalid_json_at_base(self, repo: Path) -> None:
        table_dir = repo / "config" / "agent" / "fast_tier"
        table_dir.mkdir(parents=True)
        (table_dir / "module_costs.json").write_text("not json", encoding="utf-8")
        _git(["add", "-A"], cwd=repo)
        _git([*_GIT_ENV, "commit", "-m", "bad table"], cwd=repo)
        _git(["push", "origin", "main"], cwd=repo)

        read = mct.read_at_base_ref(repo)
        assert read.status == "unreadable"


class TestDefaultCost:
    def test_default_cost_is_the_p90(self) -> None:
        import statistics

        costs = {f"tests/test_{i}.py": float(i) for i in range(1, 101)}
        read = mct.CostTableRead("ok", costs, statistics.quantiles(list(costs.values()), n=10, method="inclusive")[8])
        assert read.default_cost == pytest.approx(90.0, abs=1.0)


class TestSelectionCost:
    def test_dedupes_and_prices_known_paths(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("", encoding="utf-8")
        read = mct.CostTableRead("ok", {"tests/test_a.py": 5.0}, 2.0)
        cost = mct.selection_cost(["tests/test_a.py", "tests/test_a.py"], read, tmp_path)
        assert cost == 5.0

    def test_unknown_test_module_prices_at_default(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_new.py").write_text("", encoding="utf-8")
        read = mct.CostTableRead("ok", {}, 3.5)
        cost = mct.selection_cost(["tests/test_new.py"], read, tmp_path)
        assert cost == 3.5

    def test_unknown_non_test_path_costs_zero(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "conftest.py").write_text("", encoding="utf-8")
        read = mct.CostTableRead("ok", {}, 3.5)
        cost = mct.selection_cost(["tests/conftest.py"], read, tmp_path)
        assert cost == 0.0

    def test_require_on_disk_ignores_a_phantom_path(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        read = mct.CostTableRead("ok", {"tests/test_ghost.py": 50.0}, 2.0)
        cost = mct.selection_cost(["tests/test_ghost.py"], read, tmp_path, require_on_disk=True)
        assert cost == 0.0

    def test_require_on_disk_false_prices_a_phantom_path(self, tmp_path: Path) -> None:
        read = mct.CostTableRead("ok", {"tests/test_ghost.py": 50.0}, 2.0)
        cost = mct.selection_cost(["tests/test_ghost.py"], read, tmp_path, require_on_disk=False)
        assert cost == 50.0
