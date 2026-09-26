"""Tests for extract_definitions(), check_test_file_exists(), and get_changed_source_files().

Split from the former tests/test_coverage_checker.py monolith (rec-2709 Wave 6b -- SLOC governance
per Decision 128, not a mirror-roster retirement). See tests/fixtures/coverage_checker_module.py
for the shared module-under-test singleton.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.coverage_checker_module import ROOT, checker

extract_definitions = checker.extract_definitions
check_test_file_exists = checker.check_test_file_exists
get_changed_source_files = checker.get_changed_source_files


class TestExtractDefinitions:
    """Tests for extract_definitions()."""

    def test_extracts_top_level_function(self, tmp_path: Path) -> None:
        """Module-level function names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("def my_func():\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "my_func" in result

    def test_extracts_top_level_async_function(self, tmp_path: Path) -> None:
        """Module-level async function names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("async def fetch_data():\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "fetch_data" in result

    def test_extracts_top_level_class(self, tmp_path: Path) -> None:
        """Module-level class names are extracted."""
        f = tmp_path / "sample.py"
        f.write_text("class MyClass:\n    pass\n", encoding="utf-8")
        result = extract_definitions(f)
        assert "MyClass" in result

    def test_skips_private_functions(self, tmp_path: Path) -> None:
        """Private functions (starting with _) are skipped."""
        f = tmp_path / "sample.py"
        f.write_text(
            "def public_func():\n    pass\n\ndef _private_func():\n    pass\n",
            encoding="utf-8",
        )
        result = extract_definitions(f)
        assert "public_func" in result
        assert "_private_func" not in result

    def test_skips_nested_functions(self, tmp_path: Path) -> None:
        """Nested functions inside other functions are not extracted."""
        f = tmp_path / "sample.py"
        f.write_text(
            "def outer():\n    def inner():\n        pass\n",
            encoding="utf-8",
        )
        result = extract_definitions(f)
        assert "outer" in result
        assert "inner" not in result

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        result = extract_definitions(f)
        assert result == []

    def test_returns_empty_for_syntax_error(self, tmp_path: Path) -> None:
        """File with syntax error returns empty list (no exception raised)."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n", encoding="utf-8")
        result = extract_definitions(f)
        assert result == []


class TestCheckTestFileExists:
    """Tests for check_test_file_exists()."""

    def test_returns_true_when_test_file_exists(self, tmp_path: Path) -> None:
        """Returns (True, ...) when the expected test file is present."""
        with (
            patch("test_coverage_checker.map_source_to_test") as mock_map,
            patch("test_coverage_checker.ROOT", tmp_path),
        ):
            test_file = tmp_path / "tests" / "test_config.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("# tests", encoding="utf-8")
            mock_map.return_value = test_file

            source = tmp_path / "src" / "config.py"
            ok, msg = check_test_file_exists(source)

        assert ok is True
        assert "found" in msg

    def test_returns_false_when_test_file_missing(self, tmp_path: Path) -> None:
        """Returns (False, ...) when the expected test file is absent."""
        with patch("test_coverage_checker.map_source_to_test") as mock_map:
            test_file = tmp_path / "tests" / "test_missing.py"
            mock_map.return_value = test_file

            source = tmp_path / "src" / "missing.py"
            ok, msg = check_test_file_exists(source)

        assert ok is False
        assert "missing" in msg

    def test_returns_true_for_unmapped_path(self, tmp_path: Path) -> None:
        """Returns (True, skipped) for files that don't map to tests."""
        with patch("test_coverage_checker.map_source_to_test", return_value=None):
            source = tmp_path / "docs" / "something.py"
            ok, msg = check_test_file_exists(source)

        assert ok is True
        assert "skipped" in msg


class TestGetChangedSourceFiles:
    """Tests for get_changed_source_files(). The git-diff branch delegates entirely to
    scripts.checks._common.get_status_aware_diff(root=base_root) (Decision 159 pairing
    invariant); its own push-context-base -> merge-base -> HEAD fallback is owned by
    tests/checks/_common/test_push_context_base.py and
    tests/validate/test_changed_files.py::TestGetStatusAwareDiff (Decision 181) -- the mocked
    cases here re-seat onto that one delegation point instead of pinning the deleted git
    branches."""

    def test_filters_to_src_and_scripts(self) -> None:
        """Only .py files under src/ or scripts/ are returned."""
        entries = [
            ("M", "src/common/ducklake_runtime.py"),
            ("A", "scripts/validate.py"),
            ("M", "docs/README.md"),
            ("M", "terraform/main.tf"),
        ]
        with patch("scripts.checks._common.get_status_aware_diff", return_value=entries):
            result = get_changed_source_files()

        rel_parts = [str(p.relative_to(ROOT)).replace("\\", "/") for p in result]
        assert any("src/common/ducklake_runtime.py" in r for r in rel_parts)
        assert any("scripts/validate.py" in r for r in rel_parts)
        assert not any("docs" in r for r in rel_parts)
        assert not any(".tf" in r for r in rel_parts)

    def test_excludes_init_and_conftest(self) -> None:
        """__init__.py and conftest.py are excluded from results."""
        entries = [("A", "src/common/__init__.py"), ("M", "src/common/ducklake_runtime.py")]
        with patch("scripts.checks._common.get_status_aware_diff", return_value=entries):
            result = get_changed_source_files()

        names = [p.name for p in result]
        assert "__init__.py" not in names

    def test_excludes_test_files(self) -> None:
        """Paths outside src/ or scripts/ (e.g. tests/) are excluded."""
        entries = [("A", "tests/test_ducklake_runtime.py"), ("M", "src/common/ducklake_runtime.py")]
        with patch("scripts.checks._common.get_status_aware_diff", return_value=entries):
            result = get_changed_source_files()

        names = [p.name for p in result]
        assert "test_ducklake_runtime.py" not in names

    def test_deleted_status_entry_is_dropped(self) -> None:
        """A "D" entry is dropped by the status filter -- not the exists() filter, so the path
        used here (scripts/validate.py) deliberately EXISTS on disk."""
        entries = [("D", "scripts/validate.py"), ("M", "src/common/ducklake_runtime.py")]
        with patch("scripts.checks._common.get_status_aware_diff", return_value=entries):
            result = get_changed_source_files()

        rel_parts = [str(p.relative_to(ROOT)).replace("\\", "/") for p in result]
        assert "scripts/validate.py" not in rel_parts
        assert any("ducklake_runtime.py" in r for r in rel_parts)

    def test_uses_explicit_files_list(self) -> None:
        """When --files is provided, git diff is not called."""
        explicit = [str(ROOT / "scripts" / "validate.py")]
        with patch("scripts.checks._common.get_status_aware_diff") as mock_diff:
            result = get_changed_source_files(files=explicit)
            mock_diff.assert_not_called()

        assert any("validate.py" in str(p) for p in result)

    @pytest.mark.real_subprocess
    def test_untracked_new_source_file_is_returned(self, tmp_path: Path) -> None:
        """rec-4057/rec-4066 escape-chain regression: a brand-new UNTRACKED src/ or scripts/
        module is returned (the local pre-handoff full tier ran `git add` after measuring, so
        `git diff` alone never saw it -- see get_status_aware_diff's "??" leg, rec-2638), while
        tracked added/modified files are still returned and deleted, __init__.py, conftest.py,
        gitignored, and non-src/scripts paths are still excluded."""

        def git(*args: str) -> None:
            result = subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
            assert result.returncode == 0, result.stderr

        git("init", "-q")
        git("symbolic-ref", "HEAD", "refs/heads/not-main")

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        tracked_modified = scripts_dir / "tracked_modified.py"
        tracked_modified.write_text("x = 1\n", encoding="utf-8")
        tracked_deleted = scripts_dir / "tracked_deleted.py"
        tracked_deleted.write_text("x = 1\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text("scripts/ignored_file.py\n", encoding="utf-8")

        git("add", "-A")
        git(
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-q",
            "-m",
            "initial",
        )

        # Uncommitted tracked changes: "M" and "D".
        tracked_modified.write_text("x = 2\n", encoding="utf-8")
        tracked_deleted.unlink()

        # Brand-new untracked source files under src/ and scripts/: "??".
        new_scripts_module = scripts_dir / "new_scripts_module.py"
        new_scripts_module.write_text("y = 1\n", encoding="utf-8")
        new_src_module = src_dir / "new_src_module.py"
        new_src_module.write_text("y = 1\n", encoding="utf-8")

        # Untracked but out of scope: outside src/scripts, gitignored, __init__.py, conftest.py.
        (docs_dir / "outside.py").write_text("z = 1\n", encoding="utf-8")
        (scripts_dir / "ignored_file.py").write_text("z = 1\n", encoding="utf-8")
        (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
        (scripts_dir / "conftest.py").write_text("", encoding="utf-8")

        result = get_changed_source_files(root=tmp_path)
        rel_names = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in result}

        assert "scripts/tracked_modified.py" in rel_names
        assert "scripts/new_scripts_module.py" in rel_names
        assert "src/new_src_module.py" in rel_names

        assert "scripts/tracked_deleted.py" not in rel_names
        assert "docs/outside.py" not in rel_names
        assert "scripts/ignored_file.py" not in rel_names
        assert "scripts/__init__.py" not in rel_names
        assert "scripts/conftest.py" not in rel_names


def test_unmapped_sources_do_not_grow() -> None:
    """rec-3809 / rec-3783 non-regression: census every real repo source under src/ or scripts/
    (filtered exactly like get_changed_source_files: .py files, excluding __init__.py and
    conftest.py) and assert the unmapped set (map_source_to_test resolves, but the resolved test
    file/package does not exist) never grows past the two grandfathered stragglers.
    src/common/ducklake_maintenance_ops.py must be ABSENT -- its mirror-resolved test file
    (tests/common/test_ducklake_maintenance_ops.py) already exists on disk. The remaining set must
    be a SUBSET of {scripts/checks/ci_guards/_shared.py, scripts/checks/sloc/_shared.py} --
    subset, not equality, so a future improvement that maps one of them does not regress this
    test."""
    excluded_names = {"__init__.py", "conftest.py"}
    unmapped: set[str] = set()
    for base in ("src", "scripts"):
        for source in (ROOT / base).rglob("*.py"):
            if source.name in excluded_names:
                continue
            ok, _msg = check_test_file_exists(source)
            if not ok:
                unmapped.add(str(source.relative_to(ROOT)).replace("\\", "/"))

    assert "src/common/ducklake_maintenance_ops.py" not in unmapped
    allowed = {"scripts/checks/ci_guards/_shared.py", "scripts/checks/sloc/_shared.py"}
    assert unmapped <= allowed, f"unmapped set grew beyond the known stragglers: {unmapped - allowed}"


def test_coverage_reports_owning_target_and_module(tmp_path: Path, capsys) -> None:
    source = ROOT / "scripts" / "checks" / "validation_result.py"
    test_target = ROOT / "tests" / "checks" / "test_validation_result.py"
    proc = MagicMock()
    proc.__enter__.return_value = proc
    proc.__exit__.return_value = False
    proc.communicate.return_value = ("", "")
    coverage = ROOT / ".coverage.json"
    coverage.write_text(
        '{"files":{"scripts/checks/validation_result.py":{"summary":{"percent_covered":100}}}}', encoding="utf-8"
    )
    with (
        patch("test_coverage_checker.map_source_to_test", return_value=test_target),
        patch("test_coverage_checker.subprocess.Popen", return_value=proc),
    ):
        assert checker.check_per_file_coverage([source]) == []
    output = capsys.readouterr().out
    assert "scripts/checks/validation_result.py -> tests/checks/test_validation_result.py" in output
    # rec-943: --cov targets the file's PARENT DIRECTORY, not a dotted module path.
    assert "--cov=scripts/checks" in output
