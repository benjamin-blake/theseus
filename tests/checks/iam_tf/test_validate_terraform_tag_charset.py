"""Tests for validate_terraform_tag_charset() (rec-3326)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.iam_tf import _manifest
from scripts.checks.iam_tf.validate_terraform_tag_charset import validate_terraform_tag_charset


def _run(tmp_path: Path, tf: str, filename: str = "main.tf") -> list[str]:
    tf_dir = tmp_path / "terraform" / "personal"
    tf_dir.mkdir(parents=True, exist_ok=True)
    (tf_dir / filename).write_text(tf, encoding="utf-8")
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_terraform_tag_charset(failed)
    return failed


class TestValidateTerraformTagCharset:
    def test_fails_on_the_pre_fix_parenthesised_value(self, tmp_path: Path) -> None:
        """Red path: a Purpose tag carrying parentheses and a comma, the exact rec-3326 shape."""
        tf = """
resource "aws_s3_bucket" "data_lake" {
  tags = {
    Purpose = "Platform object storage (tfstate, plans, convergence records, logs)"
  }
}
"""
        failed = _run(tmp_path, tf)
        assert "Terraform tag value S3-charset lint" in failed

    def test_passes_on_the_fixed_value(self, tmp_path: Path) -> None:
        """Green path: the reworded, comma/paren-free value."""
        tf = """
resource "aws_s3_bucket" "data_lake" {
  tags = {
    Purpose = "Platform object storage - tfstate / plans / convergence records / logs"
  }
}
"""
        assert _run(tmp_path, tf) == []

    def test_comment_prose_is_not_scanned(self, tmp_path: Path) -> None:
        """A commented-out tags block (or comment prose mentioning tag syntax) must never
        false-positive -- comment lines are blanked before scanning, exactly like
        validate_terraform_try."""
        tf = """
# tags = {
#   Purpose = "This (has) illegal, characters but is only a comment"
# }
resource "aws_s3_bucket" "clean" {
  tags = {
    Purpose = "Legal value"
  }
}
"""
        assert _run(tmp_path, tf) == []

    def test_variable_sourced_value_is_out_of_reach(self, tmp_path: Path) -> None:
        """Owner = var.owner_email never matches the literal-string pattern -- silently skipped,
        not falsely counted as examined or as a violation."""
        tf = """
resource "aws_s3_bucket" "b" {
  tags = {
    Owner = var.owner_email
  }
}
"""
        assert _run(tmp_path, tf) == []

    def test_unterminated_tags_block_does_not_crash(self, tmp_path: Path) -> None:
        """A tags block with no closing brace (malformed HCL) must not crash the scan -- the block
        span falls back to end-of-content rather than raising."""
        tf = """
resource "aws_s3_bucket" "b" {
  tags = {
    Name = "ok"
"""
        assert _run(tmp_path, tf) == []

    def test_multiple_tags_blocks_across_files_all_scanned(self, tmp_path: Path) -> None:
        tf_dir = tmp_path / "terraform" / "personal"
        tf_dir.mkdir(parents=True, exist_ok=True)
        (tf_dir / "a.tf").write_text('resource "x" "a" {\n  tags = {\n    Name = "ok"\n  }\n}\n', encoding="utf-8")
        (tf_dir / "b.tf").write_text('resource "x" "b" {\n  tags = {\n    Name = "not (ok)"\n  }\n}\n', encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_terraform_tag_charset(failed)
        assert "Terraform tag value S3-charset lint" in failed


class TestAccountingDeclaration:
    """Decision 170 surface 7: examined()/skipped() on every reachable exit path."""

    def test_examined_declared_on_the_fall_through_path(self, tmp_path: Path) -> None:
        tf = """
resource "aws_s3_bucket" "b" {
  tags = {
    Name = "ok"
  }
}
"""
        registry.pop_declaration()
        _run(tmp_path, tf)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "tag_values"

    def test_examined_zero_on_empty_domain(self, tmp_path: Path) -> None:
        """No tags blocks anywhere -- an empty domain declares examined(0), never skipped()
        (docs/contracts/check-accounting.yaml's discrimination rule)."""
        registry.pop_declaration()
        _run(tmp_path, 'resource "x" "y" {\n  name = "z"\n}\n')
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_skipped_declared_when_terraform_directory_is_missing(self, tmp_path: Path) -> None:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_terraform_tag_charset(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []


class TestRegistration:
    """The manifest Entry must be reachable through the registry in the --pre tier -- registry.
    all_checks() membership alone does not prove tier membership (validate_terraform_try is a
    counter-example: registered but not in pre_sequence())."""

    def test_entry_present_in_manifest(self) -> None:
        names = {e.name for e in _manifest.ENTRIES}
        assert "validate_terraform_tag_charset" in names

    def test_registered_in_pre_and_full_tiers(self) -> None:
        pre = {s.name for s in registry.pre_sequence() if getattr(s, "kind", "check") == "check"}
        full = {s.name for s in registry.full_sequence() if getattr(s, "kind", "check") == "check"}
        assert "validate_terraform_tag_charset" in pre
        assert "validate_terraform_tag_charset" in full

    def test_resolves_through_the_registry(self) -> None:
        assert registry.resolve("validate_terraform_tag_charset") is validate_terraform_tag_charset


class TestRealTree:
    def test_live_terraform_tree_passes(self) -> None:
        failed: list[str] = []
        validate_terraform_tag_charset(failed)
        assert failed == []
