"""Unit tests for scripts/ci/stale_plan_signature.py (Decision 158 DEP-10 classifier extraction).

Proves the extracted classifier matches all three DEP-10 stderr phrasings reconcile.yml's
apply-reconcile step already matches inline, rejects an unrelated terraform error, and rejects
empty/None input -- the exact behaviour the three newly-covered verbatim-apply sites depend on --
plus the `--wrap -- <command>` CLI mode each of those three sites actually invokes.
"""

from __future__ import annotations

import sys

import pytest

from scripts.ci.stale_plan_signature import PLAN_STALE_CONCURRENT_WRITER_MARKER, is_stale_plan_stderr, main


@pytest.mark.parametrize(
    "stderr",
    [
        (
            "Error: Saved plan is stale\n\nThe given plan file can no longer be applied because "
            "the state was changed by another process since the plan was created."
        ),
        (
            "Error: Terraform can't apply this plan\n\nThe plan file can no longer be applied "
            "because the source configuration or state has changed since the plan was generated."
        ),
        "Error: Saved plan is stale\n\nThe state was changed by another process after this plan was created.",
    ],
)
def test_classifies_known_stale_plan_signatures(stderr: str) -> None:
    assert is_stale_plan_stderr(stderr) is True


def test_match_is_case_insensitive() -> None:
    assert is_stale_plan_stderr("SAVED PLAN IS STALE") is True


def test_unrelated_terraform_error_does_not_match() -> None:
    stderr = (
        "Error: Invalid count argument\n\n  on main.tf line 12, in resource "
        '"aws_s3_bucket" "x":\n  12:   count = var.enabled ? 1 : "bad"\n\n'
        'The "count" value depends on resource attributes that cannot be determined '
        "until apply."
    )
    assert is_stale_plan_stderr(stderr) is False


def test_empty_string_does_not_match() -> None:
    assert is_stale_plan_stderr("") is False


def test_none_does_not_match() -> None:
    assert is_stale_plan_stderr(None) is False


def _fake_terraform(stderr_text: str, exit_code: int) -> list[str]:
    """A Python-as-terraform-stand-in argv: writes stderr_text to stderr, exits with exit_code."""
    script = f"import sys; sys.stderr.write({stderr_text!r}); sys.exit({exit_code})"
    return [sys.executable, "-c", script]


class TestWrapMode:
    """--wrap -- <command>: the real invocation shape all three call sites use."""

    def test_success_exits_0_and_emits_no_marker(self, capsys) -> None:
        rc = main(["--wrap", "--", *_fake_terraform("", 0)])
        assert rc == 0
        assert "PLAN_STALE_CONCURRENT_WRITER" not in capsys.readouterr().err

    def test_stale_plan_failure_preserves_exit_code_and_emits_marker(self, capsys) -> None:
        rc = main(["--wrap", "--", *_fake_terraform("Error: saved plan is stale", 1)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "saved plan is stale" in err
        assert PLAN_STALE_CONCURRENT_WRITER_MARKER in err

    def test_unrelated_failure_preserves_exit_code_and_emits_no_marker(self, capsys) -> None:
        rc = main(["--wrap", "--", *_fake_terraform("Error: Invalid count argument", 1)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "Invalid count argument" in err
        assert "PLAN_STALE_CONCURRENT_WRITER" not in err

    def test_a_different_nonzero_exit_code_is_preserved(self, capsys) -> None:
        """rc is the wrapped command's return code verbatim, not collapsed to 0/1 --
        steps.apply.outcome downstream readers must see the SAME failure they would without
        this wrapper."""
        rc = main(["--wrap", "--", *_fake_terraform("Error: Invalid count argument", 42)])
        assert rc == 42

    def test_missing_wrap_flag_is_a_usage_error(self) -> None:
        assert main(["--", "true"]) == 2

    def test_missing_separator_is_a_usage_error(self) -> None:
        assert main(["--wrap", "true"]) == 2

    def test_missing_command_after_separator_is_a_usage_error(self) -> None:
        assert main(["--wrap", "--"]) == 2
