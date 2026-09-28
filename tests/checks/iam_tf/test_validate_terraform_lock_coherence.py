"""Tests for validate_terraform_lock_coherence (rec-4110/3400/3318/3369/3919)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.iam_tf import _manifest
from scripts.checks.iam_tf.validate_terraform_lock_coherence import (
    _block_end,
    _normalize_source,
    _parse_required_providers_entries,
    lock_coherence_findings,
    validate_terraform_lock_coherence,
)

_LOCK_AWS_NEON = """
provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.100.0"
  constraints = "~> 5.0"
  hashes = []
}

provider "registry.terraform.io/kislerdm/neon" {
  version     = "0.13.0"
  constraints = "0.13.0"
  hashes = []
}
"""

_TF_AWS_NEON = """
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    neon = {
      source  = "kislerdm/neon"
      version = "0.13.0"
    }
  }
}
"""

_NULL_LOCK_BLOCK = """
provider "registry.terraform.io/hashicorp/null" {
  version = "3.3.0"
  hashes = []
}
"""


class TestLockCoherenceFindings:
    def test_coherent_aws_and_neon_passes(self) -> None:
        assert lock_coherence_findings(_LOCK_AWS_NEON, [_TF_AWS_NEON]) == []

    def test_orphaned_lock_entry_is_a_finding(self) -> None:
        """The exact pre-fix shape: an orphaned hashicorp/null block with no declaration."""
        findings = lock_coherence_findings(_LOCK_AWS_NEON + _NULL_LOCK_BLOCK, [_TF_AWS_NEON])
        assert len(findings) == 1
        assert "orphan" in findings[0]
        assert "hashicorp/null" in findings[0]

    def test_declared_provider_missing_from_lock_is_a_finding(self) -> None:
        tf = _TF_AWS_NEON.replace(
            "neon = {",
            'github = {\n      source  = "integrations/github"\n      version = "~> 6.0"\n    }\n    neon = {',
        )
        findings = lock_coherence_findings(_LOCK_AWS_NEON, [tf])
        assert len(findings) == 1
        assert "missing" in findings[0]
        assert "integrations/github" in findings[0]

    def test_version_constraint_drift_alone_is_not_a_finding(self) -> None:
        """Residual (measured, Terraform 1.10.5): a config version constraint change that the
        locked version still satisfies is invisible to plain and readonly init alike -- this
        parser must not gate on it either."""
        tf = _TF_AWS_NEON.replace('version = "~> 5.0"', 'version = ">= 5.0"')
        assert lock_coherence_findings(_LOCK_AWS_NEON, [tf]) == []

    def test_legacy_string_shorthand_entry(self) -> None:
        tf = """
terraform {
  required_providers {
    aws = "~> 5.0"
  }
}
"""
        lock = """
provider "registry.terraform.io/hashicorp/aws" {
  version = "5.100.0"
  hashes = []
}
"""
        assert lock_coherence_findings(lock, [tf]) == []

    def test_object_entry_without_source_implies_hashicorp(self) -> None:
        tf = """
terraform {
  required_providers {
    aws = {
      version = "~> 5.0"
    }
  }
}
"""
        lock = """
provider "registry.terraform.io/hashicorp/aws" {
  version = "5.100.0"
  hashes = []
}
"""
        assert lock_coherence_findings(lock, [tf]) == []

    def test_three_part_host_source_kept_as_is(self) -> None:
        tf = """
terraform {
  required_providers {
    corp = {
      source  = "registry.mycorp.example/team/corp"
      version = "1.0.0"
    }
  }
}
"""
        lock = """
provider "registry.mycorp.example/team/corp" {
  version = "1.0.0"
  hashes = []
}
"""
        assert lock_coherence_findings(lock, [tf]) == []

    def test_mixed_case_source_is_lower_cased(self) -> None:
        tf = """
terraform {
  required_providers {
    random = {
      source  = "HashiCorp/Random"
      version = "3.0.0"
    }
  }
}
"""
        lock = """
provider "registry.terraform.io/hashicorp/random" {
  version = "3.0.0"
  hashes = []
}
"""
        assert lock_coherence_findings(lock, [tf]) == []

    def test_required_providers_block_inside_a_comment_is_ignored(self) -> None:
        tf = """
# terraform {
#   required_providers {
#     aws = {
#       source = "hashicorp/aws"
#     }
#   }
# }
"""
        lock = ""
        assert lock_coherence_findings(lock, [tf]) == []

    def test_two_required_providers_blocks_across_files_are_unioned(self) -> None:
        tf_a = """
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
"""
        tf_b = """
terraform {
  required_providers {
    neon = {
      source  = "kislerdm/neon"
      version = "0.13.0"
    }
  }
}
"""
        assert lock_coherence_findings(_LOCK_AWS_NEON, [tf_a, tf_b]) == []


class TestParserEdgeCases:
    def test_unterminated_block_falls_back_to_end_of_content(self) -> None:
        """Malformed HCL (no closing brace) must not crash the scan -- the block span falls back
        to end-of-content rather than looping or raising."""
        content = 'required_providers {\n  aws = {\n    source = "hashicorp/aws"\n'
        brace_pos = content.index("{")
        assert _block_end(content, brace_pos) == len(content)

    def test_builtin_terraform_source_is_ignored(self) -> None:
        assert _normalize_source("terraform.io/builtin/terraform") is None

    def test_malformed_source_shape_returns_none(self) -> None:
        assert _normalize_source("onlyonepart") is None
        assert _normalize_source("a/b/c/d") is None

    def test_entry_with_non_object_non_string_value_is_skipped(self) -> None:
        """A value that is neither `{` nor a string literal (e.g. a bare reference) contributes
        no address and does not crash the scan."""
        assert _parse_required_providers_entries("foo = var.x\n") == set()


class TestCheckAccounting:
    """Decision 170 surface: examined()/skipped() on every reachable exit path."""

    def test_git_unavailable_declares_skipped(self) -> None:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks.iam_tf.validate_terraform_lock_coherence.tracked_lock_files", return_value=None):
            validate_terraform_lock_coherence(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "skipped"

    def test_no_tracked_locks_declares_examined_zero(self) -> None:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks.iam_tf.validate_terraform_lock_coherence.tracked_lock_files", return_value=[]):
            validate_terraform_lock_coherence(failed)
        declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_orphaned_tracked_lock_fails_with_one_label_and_examined_one(self, tmp_path: Path) -> None:
        tf_dir = tmp_path / "terraform" / "personal"
        tf_dir.mkdir(parents=True)
        (tf_dir / "main.tf").write_text(_TF_AWS_NEON, encoding="utf-8")
        (tf_dir / ".terraform.lock.hcl").write_text(_LOCK_AWS_NEON + _NULL_LOCK_BLOCK, encoding="utf-8")

        registry.pop_declaration()
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.iam_tf.validate_terraform_lock_coherence.tracked_lock_files",
                return_value=["terraform/personal/.terraform.lock.hcl"],
            ),
        ):
            validate_terraform_lock_coherence(failed)
        declaration = registry.pop_declaration()

        assert failed == ["Terraform lock coherence"]
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1


class TestRepoLocksCoherent:
    def test_every_tracked_lock_matches_its_root(self) -> None:
        failed: list[str] = []
        validate_terraform_lock_coherence(failed)
        assert failed == []


class TestRegistration:
    def test_entry_present_in_manifest(self) -> None:
        names = {e.name for e in _manifest.ENTRIES}
        assert "validate_terraform_lock_coherence" in names

    def test_registered_in_pre_and_full_tiers(self) -> None:
        pre = {s.name for s in registry.pre_sequence() if getattr(s, "kind", "check") == "check"}
        full = {s.name for s in registry.full_sequence() if getattr(s, "kind", "check") == "check"}
        assert "validate_terraform_lock_coherence" in pre
        assert "validate_terraform_lock_coherence" in full

    def test_resolves_through_the_registry(self) -> None:
        assert registry.resolve("validate_terraform_lock_coherence") is validate_terraform_lock_coherence
