"""Tests for validate_complexity()."""

import json
from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.sloc.complexity import validate_complexity


class TestValidateComplexity:
    """Tests for validate_complexity()."""

    def test_returns_empty_list_when_no_outliers(self, tmp_path: Path) -> None:
        """Returns empty list and writes empty JSON when no complexity outliers."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        # Create simple Python files with moderate complexity
        for i in range(3):
            py_file = src_dir / f"module{i}.py"
            py_file.write_text(
                "def func1(): pass\ndef func2(): pass\nimport os\nimport sys\n",
                encoding="utf-8",
            )

        prompts_dir = tmp_path / ".github" / "prompts"
        prompts_dir.mkdir(parents=True)
        for i in range(3):
            md_file = prompts_dir / f"test{i}.md"
            md_file.write_text("Some text here.\nRegular lines only.\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        assert warnings == []
        assert failed == []
        warnings_file = tmp_path / "logs" / ".complexity-warnings.json"
        assert warnings_file.exists()

        data = json.loads(warnings_file.read_text(encoding="utf-8"))
        assert data == []

    def test_flags_outlier_python_files(self, tmp_path: Path) -> None:
        """Flags Python files with complexity >2 std-devs above package mean."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        # Create 5 simple files with low complexity + 1 extreme outlier
        # This gives us more points for the std-dev calculation
        for i in range(5):
            py_file = src_dir / f"simple{i}.py"
            py_file.write_text(
                "def func1(): pass\nimport os\n",
                encoding="utf-8",
            )

        # Extreme outlier: 100 functions + 100 imports = 200
        complex_file = src_dir / "complex.py"
        complex_lines = []
        for i in range(1, 101):
            complex_lines.append(f"def f{i}(): pass")
        # Add many imports to reach 100+ unique ones
        for i in range(100):
            complex_lines.append(f"import m{i}")
        complex_file.write_text("\n".join(complex_lines) + "\n", encoding="utf-8")

        prompts_dir = tmp_path / ".github" / "prompts"
        prompts_dir.mkdir(parents=True)
        for i in range(3):
            md_file = prompts_dir / f"test{i}.md"
            md_file.write_text("Regular text here.\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        assert len(warnings) > 0
        assert any(w["file"].endswith("complex.py") for w in warnings)
        assert failed == []

    def test_skips_excluded_files(self, tmp_path: Path) -> None:
        """Skips __init__.py, conftest.py, and files under excluded dirs."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        # Create excluded files
        init_file = src_dir / "__init__.py"
        init_file.write_text(
            "def func1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        conftest_file = src_dir / "conftest.py"
        conftest_file.write_text(
            "def func1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        # Create file in excluded dir
        pip_dir = tmp_path / "pip"
        pip_dir.mkdir()
        pip_file = pip_dir / "module.py"
        pip_file.write_text(
            "def func1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        # Excluded files should not appear in warnings
        file_paths = [w["file"] for w in warnings]
        assert not any("__init__.py" in p for p in file_paths)
        assert not any("conftest.py" in p for p in file_paths)
        assert not any("pip" in p for p in file_paths)
        assert failed == []

    def test_skips_packages_with_fewer_than_3_files(self, tmp_path: Path) -> None:
        """Skips complexity analysis for packages with <3 files."""
        src_dir = tmp_path / "src" / "small_pkg"
        src_dir.mkdir(parents=True)

        # Create only 2 files (below threshold)
        for i in range(2):
            py_file = src_dir / f"module{i}.py"
            py_file.write_text(
                "def func1(): pass\n" * 10 + "import a\n" * 10,
                encoding="utf-8",
            )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            warnings = validate_complexity(failed)

        # Should not flag any warnings (package too small)
        assert all("small_pkg" not in w.get("package", "") for w in warnings)
        assert failed == []

    def test_never_appends_to_failed_list(self, tmp_path: Path) -> None:
        """Complexity analysis never appends to the failed list."""
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)

        complex_file = src_dir / "complex.py"
        complex_file.write_text(
            "def f1(): pass\n" * 20 + "import a\n" * 20,
            encoding="utf-8",
        )

        for i in range(2):
            py_file = src_dir / f"simple{i}.py"
            py_file.write_text("def func(): pass\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_complexity(failed)

        assert failed == []


class TestPromptDensityOutliers:
    """complexity.py:154/158/161 -- the prompt-density arm is advisory-only, so its warnings are
    observed through the list validate_complexity RETURNS, never through `failed`."""

    @staticmethod
    def _write_prompts(tmp_path: Path, plain_count: int, with_outlier: bool) -> None:
        """Write plain_count zero-density prompts, optionally plus one density-1.0 outlier.

        Nine plain plus one outlier gives mean 0.1, stdev 0.3162 and threshold 0.7325, so the
        outlier's 1.0 clears it and the plain files' 0.0 do not.
        """
        prompts_dir = tmp_path / ".github" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        for i in range(plain_count):
            (prompts_dir / f"plain{i}.md").write_text("Regular narrative line.\n", encoding="utf-8")
        if with_outlier:
            (prompts_dir / "outlier.md").write_text("You must do the thing.\n", encoding="utf-8")

    @staticmethod
    def _prompt_warning_files(tmp_path: Path) -> list[str]:
        """Return the prompt-typed warning paths from the value validate_complexity returns."""
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            warnings = validate_complexity(failed)
        assert failed == []
        return [w["file"] for w in warnings if w["type"] == "prompt"]

    def test_prompt_density_outlier_is_flagged(self, tmp_path: Path) -> None:
        """A prompt more than two stdevs above the mean imperative density is warned about."""
        self._write_prompts(tmp_path, plain_count=9, with_outlier=True)

        assert ".github/prompts/outlier.md" in self._prompt_warning_files(tmp_path)

    def test_non_outlier_prompt_files_are_not_flagged(self, tmp_path: Path) -> None:
        """Exact list equality: only the outlier is selected, never the nine in-band files."""
        self._write_prompts(tmp_path, plain_count=9, with_outlier=True)

        assert self._prompt_warning_files(tmp_path) == [".github/prompts/outlier.md"]

    def test_uniform_prompt_densities_produce_no_prompt_warning(self, tmp_path: Path) -> None:
        """Anti-vacuity green: a zero-spread prompt surface short-circuits before any warning."""
        self._write_prompts(tmp_path, plain_count=10, with_outlier=False)

        assert self._prompt_warning_files(tmp_path) == []


_REPO_ROOT = Path(__file__).parents[3]
_UNIT = "files"
_EXCLUDED_NAMES = {"__init__.py", "conftest.py"}
_EXCLUDED_DIRS = {"pip", "lambda-packages", "docker", "terraform"}


def _declared(root: Path) -> tuple[list[str], registry._Declaration | None]:
    registry.pop_declaration()
    with patch("scripts.checks._common.ROOT", root):
        failed: list[str] = []
        validate_complexity(failed)
    return failed, registry.pop_declaration()


def _measured_py(root: Path) -> int:
    return sum(
        1
        for top in ("src", "scripts")
        for p in (root / top).glob("**/*.py")
        if p.name not in _EXCLUDED_NAMES and not _EXCLUDED_DIRS.intersection(p.parts)
    )


class TestComplexityAccountingDeclaration:
    """The check declares how many Python and prompt files it measured, so a run records enforced
    with a count that tracks both surfaces -- not a constant and not the warning count."""

    def test_real_tree_declares_every_measured_file(self) -> None:
        expected = _measured_py(_REPO_ROOT) + sum(1 for _ in (_REPO_ROOT / ".github" / "prompts").glob("**/*.md"))

        _, declaration = _declared(_REPO_ROOT)

        assert expected > 0
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)

    def test_count_sums_python_and_prompt_files_and_omits_excluded(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "data").mkdir(parents=True)
        (tmp_path / "src" / "data" / "a.py").write_text("def f(): pass\n", encoding="utf-8")
        (tmp_path / "src" / "data" / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "scripts" / "tools").mkdir(parents=True)
        (tmp_path / "scripts" / "tools" / "b.py").write_text("import os\n", encoding="utf-8")
        (tmp_path / "scripts" / "tools" / "conftest.py").write_text("", encoding="utf-8")
        (tmp_path / "scripts" / "docker").mkdir()
        (tmp_path / "scripts" / "docker" / "c.py").write_text("import os\n", encoding="utf-8")
        prompts_dir = tmp_path / ".github" / "prompts" / "scheduled"
        prompts_dir.mkdir(parents=True)
        for name in ("one.md", "two.md", "three.md"):
            (prompts_dir / name).write_text("You must do the thing.\n", encoding="utf-8")
        (prompts_dir / "notes.txt").write_text("You must.\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 5, _UNIT)

    def test_empty_tree_declares_vacuous_domain(self, tmp_path: Path) -> None:
        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome("validate_complexity", "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "vacuous"

    def test_outlier_tree_records_enforced_not_failed(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)
        for i in range(5):
            (src_dir / f"simple{i}.py").write_text("def f(): pass\n", encoding="utf-8")
        (src_dir / "complex.py").write_text("".join(f"def f{i}(): pass\nimport m{i}\n" for i in range(50)), encoding="utf-8")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome("validate_complexity", "check", declaration, bool(failed))

        assert declaration is not None and declaration.count == 6
        assert failed == []
        assert outcome.status == "enforced"


class TestUnreadableInputsStayMeasured:
    """An unparseable Python file or an undecodable / blank prompt degrades to a zero metric but is
    still measured and counted, never crashing the advisory run or dropping out of the declaration."""

    def test_unparseable_python_files_score_zero_and_are_still_counted(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "data"
        src_dir.mkdir(parents=True)
        for i in range(4):
            (src_dir / f"ok{i}.py").write_text("def f(): pass\nimport os\n", encoding="utf-8")
        (src_dir / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        (src_dir / "nul.py").write_text("x = 1\x00\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)

        assert failed == []
        assert declaration is not None and declaration.count == 6
        assert json.loads((tmp_path / "logs" / ".complexity-warnings.json").read_text(encoding="utf-8")) == []

    def test_undecodable_empty_and_blank_prompts_score_zero_density(self, tmp_path: Path) -> None:
        prompts_dir = tmp_path / ".github" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "binary.md").write_bytes(b"You must \xff\xfe do it.\n")
        (prompts_dir / "empty.md").write_text("", encoding="utf-8")
        (prompts_dir / "blank.md").write_text("   \n\n\t\n", encoding="utf-8")
        for i in range(6):
            (prompts_dir / f"plain{i}.md").write_text("Regular narrative line.\n", encoding="utf-8")
        (prompts_dir / "outlier.md").write_text("You must do the thing.\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)
        warnings = json.loads((tmp_path / "logs" / ".complexity-warnings.json").read_text(encoding="utf-8"))

        assert failed == []
        assert declaration is not None and declaration.count == 10
        assert [w["file"] for w in warnings] == [".github/prompts/outlier.md"]
