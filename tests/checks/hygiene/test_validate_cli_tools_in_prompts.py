"""Tests for validate_cli_tools_in_prompts()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.hygiene.validate_cli_tools_in_prompts import validate_cli_tools_in_prompts

_REPO_ROOT = Path(__file__).parents[3]
_UNIT = "prompt_files"


class TestValidateCliToolsInPrompts:
    """Tests for validate_cli_tools_in_prompts()."""

    def test_passes_when_all_tools_in_path(self, tmp_path: Path) -> None:
        """No failures when all referenced tools are found in PATH."""
        prompt_dir = tmp_path / ".github" / "prompts" / "scheduled"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\naws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"aws"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value="/usr/bin/aws"),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []

    def test_fails_when_tool_not_in_path(self, tmp_path: Path) -> None:
        """Appends to failed list when a referenced tool is not in PATH."""
        prompt_dir = tmp_path / ".github" / "prompts" / "scheduled"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\nterraform validate\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"terraform"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert len(failed) == 1
        assert "CLI tool verification" in failed[0]

    def test_optional_tool_gh_missing_is_skipped(self, tmp_path: Path) -> None:
        """gh is optional (Decision 76); a referenced-but-missing gh does not fail the gate."""
        prompt_dir = tmp_path / ".github" / "prompts" / "scheduled"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "ci.prompt.md"
        md.write_text("```bash\ngh pr view\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"gh"}),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._OPTIONAL_CLI_TOOLS", {"gh"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []

    def test_skips_comment_lines_in_code_blocks(self, tmp_path: Path) -> None:
        """Lines starting with # inside code blocks are not treated as commands."""
        prompt_dir = tmp_path / ".github" / "prompts" / "scheduled"
        prompt_dir.mkdir(parents=True)
        md = prompt_dir / "test.prompt.md"
        md.write_text("```bash\n# aws sts get-caller-identity\n```\n", encoding="utf-8")

        with (
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts._KNOWN_CLI_TOOLS", {"aws"}),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=None),
        ):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        # aws appears only in a comment — not in referenced, so not checked
        assert failed == []

    def test_no_failures_when_no_md_files(self, tmp_path: Path) -> None:
        """No failures when no markdown files exist in the search dirs."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cli_tools_in_prompts(failed)

        assert failed == []


def _declared(root: Path, which: str | None = "/usr/bin/tool") -> tuple[list[str], registry._Declaration | None]:
    registry.pop_declaration()
    with (
        patch("scripts.checks._common.ROOT", root),
        patch("scripts.checks.hygiene.validate_cli_tools_in_prompts.shutil.which", return_value=which),
    ):
        failed: list[str] = []
        validate_cli_tools_in_prompts(failed)
    return failed, registry.pop_declaration()


def _prompt_dir(root: Path) -> Path:
    prompt_dir = root / ".github" / "prompts" / "scheduled"
    prompt_dir.mkdir(parents=True)
    return prompt_dir


class TestCliToolsInPromptsAccountingDeclaration:
    """The check declares how many scheduled-prompt *.md files it read, so a run records enforced
    with a count that tracks the prompt surface -- not a constant and not the referenced-tool count."""

    def test_real_tree_declares_every_scheduled_prompt_file(self) -> None:
        expected = sum(1 for p in (_REPO_ROOT / ".github" / "prompts" / "scheduled").glob("*.md") if p.is_file())

        _, declaration = _declared(_REPO_ROOT)

        assert expected > 0
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)

    def test_count_tracks_md_files_not_referenced_tools(self, tmp_path: Path) -> None:
        prompt_dir = _prompt_dir(tmp_path)
        (prompt_dir / "a.prompt.md").write_text("```bash\naws s3 ls\n```\n", encoding="utf-8")
        (prompt_dir / "b.prompt.md").write_text("no code blocks here\n", encoding="utf-8")
        (prompt_dir / "c.prompt.md").write_text("```bash\naws sts get-caller-identity\n```\n", encoding="utf-8")
        (prompt_dir / "notes.txt").write_text("```bash\nterraform plan\n```\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)

    def test_absent_prompt_dir_declares_vacuous_domain(self, tmp_path: Path) -> None:
        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome("validate_cli_tools_in_prompts", "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "vacuous"

    def test_missing_tool_still_records_failed_over_examined(self, tmp_path: Path) -> None:
        (_prompt_dir(tmp_path) / "infra.prompt.md").write_text("```bash\nterraform validate\n```\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path, which=None)
        outcome = registry.build_outcome("validate_cli_tools_in_prompts", "check", declaration, bool(failed))

        assert declaration is not None and declaration.count == 1
        assert failed == ["CLI tool verification"]
        assert outcome.status == "failed"
