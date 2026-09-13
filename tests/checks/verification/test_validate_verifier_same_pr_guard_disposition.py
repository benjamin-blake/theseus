"""Disposition tests for the rec-3721 narrowing of validate_verifier_same_pr_guard to concrete
Verifier subclasses (LSA-01 leg c). Carries TestFrameworkOnlyPopulation::
test_editing_harness_alongside_another_file_does_not_gate VERBATIM -- this exact path/class/method
is rec-3721's own acceptance command, so the rec cannot close without it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.checks import registry
from scripts.checks.verification.validate_verifier_same_pr_guard import validate_verifier_same_pr_guard


class TestFrameworkOnlyPopulation:
    """Drives the REAL scripts/verifiers/harness.py (unpatched ROOT -- the live repository file,
    not a synthetic copy) alongside an unrelated changed file. Before rec-3721 this produced six
    violations (one per framework class defaulting to covers=["**"]); after, the narrowed scan
    finds zero concrete Verifier subclasses in harness.py and declares examined(0)."""

    def test_editing_harness_alongside_another_file_does_not_gate(self) -> None:
        failed: list[str] = []
        with registry.outcome_scope("validate_verifier_same_pr_guard"):
            with (
                patch(
                    "scripts.checks._common.get_changed_files",
                    return_value=["scripts/verifiers/harness.py", "scripts/checks/_common.py"],
                ),
                patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
            ):
                validate_verifier_same_pr_guard(failed)
            declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert declaration.unit == "verifier_modules"

    def test_a_concrete_verifier_subclass_alongside_harness_still_gates(self, tmp_path) -> None:  # noqa: ANN001
        """The complementary positive: mixing a concrete subclass INTO the same diff as harness.py
        still gates on its own covered file -- the narrowing removes the framework noise, not the
        guard's actual teeth."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "concrete.py").write_text(
            "from scripts.verifiers.harness import Verifier\n\n\n"
            "class ConcreteVerifier(Verifier):\n    covers = ['scripts/target.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/concrete.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert "Verifier same-PR guard" in failed
