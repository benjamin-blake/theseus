"""Tests for validate_verifier_same_pr_guard() (VF-06). Mirror of
scripts/checks/verification/validate_verifier_same_pr_guard.py -- merges
TestSamePrGuard, TestSamePrGuardHelpers, TestSamePrGuardDifferential, and the
module-level test_same_pr_guard_passes_on_no_verifier_in_diff (rec-2709 Wave 1)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import verification_graduation
from scripts.checks import registry
from scripts.checks.verification.validate_verifier_same_pr_guard import validate_verifier_same_pr_guard


class TestSamePrGuard:
    """Tests for validate_verifier_same_pr_guard() in validate.py --pre tier."""

    def test_no_violations_when_no_verifier_in_diff(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_no_violation_when_verifier_newly_added(self, tmp_path: Path) -> None:
        """Exception (b): a brand-new verifier file is exempt from the guard.

        Its covers ('**') intersects the diff, so this also exercises the VF-06 c3
        differential dispatch path -- stubbed here to an admitted outcome since the
        differential mechanism itself (real worktree) is covered by
        TestSamePrGuardDifferential below.
        """
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "new_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['**']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/new_verifier.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/validate.py"]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=rel + "\n"),
            ),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=True, skipped=False, reason="stubbed for AST-level guard test"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed, f"Expected no violation for newly-added verifier: {failed}"

    def test_no_violation_exception_c_no_covered_in_diff(self, tmp_path: Path) -> None:
        """Exception (c): verifier modified but no covered file in diff."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "my_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['scripts/some_module.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/my_verifier.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/other.py"]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=""),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed, f"Expected no violation when no covered file in diff: {failed}"

    def test_violation_detected_when_verifier_and_covered_both_modified(self, tmp_path: Path) -> None:
        """Same-PR guard fires when an existing verifier AND a file it covers are both in diff."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        verifier_file = verifier_src / "my_verifier.py"
        verifier_file.write_text(
            "class MyVerifier:\n    covers = ['scripts/target.py']\n",
            encoding="utf-8",
        )
        rel = "scripts/verifiers/my_verifier.py"
        target = "scripts/target.py"
        (tmp_path / "scripts" / "target.py").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "scripts" / "target.py").write_text("# target\n", encoding="utf-8")
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, target]),
            patch(
                "scripts.checks._common.run",
                return_value=MagicMock(returncode=0, stdout=""),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert "Verifier same-PR guard" in failed

    def _write_default_covers_verifier(self, tmp_path: Path) -> str:
        """Fixture verifier whose single class declares the default covers of ['**']."""
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "wide_verifier.py").write_text("class WideVerifier:\n    covers = ['**']\n", encoding="utf-8")
        return "scripts/verifiers/wide_verifier.py"

    def _run_with_changed(self, tmp_path: Path, changed: list[str]) -> list[str]:
        """Drive the guard under the three seams the sibling cases already patch, inside
        registry.outcome_scope so the module-level declaration slot is reset rather than left
        populated for whatever dispatch reads it next."""
        failed: list[str] = []
        with registry.outcome_scope("validate_verifier_same_pr_guard"):
            with (
                patch("scripts.checks._common.ROOT", tmp_path),
                patch("scripts.checks._common.get_changed_files", return_value=changed),
                patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
            ):
                validate_verifier_same_pr_guard(failed)
        return failed

    def test_resolved_plan_companion_is_not_a_covered_file(self, tmp_path: Path) -> None:
        """A CANDIDATE plan path is its own diff's bookkeeping companion, never a covered file."""
        rel = self._write_default_covers_verifier(tmp_path)
        failed = self._run_with_changed(tmp_path, [rel, "docs/plans/PLAN-some-slug.yaml"])
        assert not failed, f"Expected no violation for a plan companion: {failed}"

    def test_violation_still_detected_when_plan_and_covered_file_both_present(self, tmp_path: Path) -> None:
        """Decision 181 pin: a real covered source file still violates with a plan path present."""
        rel = self._write_default_covers_verifier(tmp_path)
        failed = self._run_with_changed(tmp_path, [rel, "docs/plans/PLAN-some-slug.yaml", "scripts/target.py"])
        assert "Verifier same-PR guard" in failed

    def test_non_plan_path_under_docs_plans_is_still_covered(self, tmp_path: Path) -> None:
        """Decision 181 pin: the exemption is PLAN_PATH_RE's set, not the docs/plans directory."""
        rel = self._write_default_covers_verifier(tmp_path)
        failed = self._run_with_changed(tmp_path, [rel, "docs/plans/nested/PLAN-c.yaml"])
        assert "Verifier same-PR guard" in failed

    def test_declares_examined_outcome_for_scanned_verifier_modules(self, tmp_path: Path) -> None:
        """Decision 170: the terminal exit declares examined(n, unit="verifier_modules"), where n
        is the count of verifier files present in the changed set (the guard's ``scanned += 1``
        per verifier file it processes). Two blocks pin both ends of that arithmetic so a mutant
        that guts the counter -- 'scanned += 1' replaced with 'pass', or the call hardcoded to
        examined(0, unit="verifier_modules") -- cannot satisfy both:

        Block 1 -- EMPTY DOMAIN: the diff holds no verifier file, so count == 0 and status is
        vacuous (an always-zero counter passes this block alone, which is why block 2 exists).

        Block 2 -- non-empty domain: the diff holds exactly two verifier files, each with a
        narrow ``covers`` that matches no other file present in the diff (so exception (c)
        suppresses any violation and this block stays a pure accounting probe). The count is
        pinned at 2, not 0 or 1, and status must be enforced -- this is the assertion an
        always-zero or off-by-one mutant fails, since it can no longer fake the count by
        returning a constant."""
        failed: list[str] = []
        with registry.outcome_scope("validate_verifier_same_pr_guard"):
            with (
                patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
                patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
            ):
                validate_verifier_same_pr_guard(failed)
        declaration = registry.pop_declaration()
        assert not failed
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert declaration.unit == "verifier_modules"
        assert registry.derive_status(declaration, bool(failed)) == "vacuous"

        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "verifier_a.py").write_text(
            "class VerifierA:\n    covers = ['scripts/only_a_target.py']\n", encoding="utf-8"
        )
        (verifier_src / "verifier_b.py").write_text(
            "class VerifierB:\n    covers = ['scripts/only_b_target.py']\n", encoding="utf-8"
        )
        rel_a = "scripts/verifiers/verifier_a.py"
        rel_b = "scripts/verifiers/verifier_b.py"
        failed_two: list[str] = []
        with registry.outcome_scope("validate_verifier_same_pr_guard"):
            with (
                patch("scripts.checks._common.ROOT", tmp_path),
                patch("scripts.checks._common.get_changed_files", return_value=[rel_a, rel_b]),
                patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
            ):
                validate_verifier_same_pr_guard(failed_two)
        declaration_two = registry.pop_declaration()
        assert not failed_two, f"Expected no violation for narrowly-covered verifiers: {failed_two}"
        assert declaration_two is not None
        assert declaration_two.kind == "examined"
        assert declaration_two.count == 2
        assert declaration_two.unit == "verifier_modules"
        assert registry.derive_status(declaration_two, bool(failed_two)) == "enforced"

    def test_declares_skipped_outcome_when_verifiers_dir_absent(self, tmp_path: Path) -> None:
        """Decision 170: the scripts/verifiers-absent exit declares skipped -- an unavailable
        input, never an empty domain."""
        failed: list[str] = []
        with registry.outcome_scope("validate_verifier_same_pr_guard"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_verifier_same_pr_guard(failed)
        declaration = registry.pop_declaration()
        assert not failed
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert registry.derive_status(declaration, bool(failed)) == "skipped"


class TestSamePrGuardHelpers:
    """Edge-case coverage for _extract_verifier_covers and the guard's structural branches."""

    def test_extract_verifier_covers_annotated_assignment(self) -> None:
        import ast

        from scripts.checks.verification.validate_verifier_same_pr_guard import _extract_verifier_covers

        tree = ast.parse("class MyVerifier:\n    covers: list[str] = ['a.py', 'b.py']\n")
        cls = tree.body[0]
        assert _extract_verifier_covers(cls) == ["a.py", "b.py"]

    def test_extract_verifier_covers_returns_none_when_absent(self) -> None:
        import ast

        from scripts.checks.verification.validate_verifier_same_pr_guard import _extract_verifier_covers

        tree = ast.parse("class MyVerifier:\n    pass\n")
        cls = tree.body[0]
        assert _extract_verifier_covers(cls) is None

    def test_verifiers_dir_missing_returns_early(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_verifier_file_with_syntax_error_is_skipped(self, tmp_path: Path) -> None:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        rel = "scripts/verifiers/broken.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_verifier_file_with_no_classes_is_skipped(self, tmp_path: Path) -> None:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "no_classes.py").write_text("x = 1\n", encoding="utf-8")
        rel = "scripts/verifiers/no_classes.py"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed


class TestSamePrGuardDifferential:
    """VP step 7: validate_verifier_same_pr_guard's exception-(b) differential branch (VF-06 c3).

    The differential mechanism itself is covered by tests/test_verification_graduation.py; here
    we drive the validate.py wiring with a stubbed scripts.verification_graduation.
    """

    def _setup_new_verifier(self, tmp_path: Path) -> str:
        verifier_src = tmp_path / "scripts" / "verifiers"
        verifier_src.mkdir(parents=True)
        (verifier_src / "new_verifier.py").write_text(
            "class MyVerifier:\n    covers = ['scripts/target.py']\n", encoding="utf-8"
        )
        target = tmp_path / "scripts" / "target.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# target\n", encoding="utf-8")
        return "scripts/verifiers/new_verifier.py"

    def test_exception_b_differential_admits(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=True, skipped=False, reason="admitted"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_exception_b_tautological_fails(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=False,
                    skipped=False,
                    reason="not admitted -- verifier passes even with its covered change reverted",
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert any("not admitted" in f for f in failed), failed

    def test_exception_b_non_hermetic_advisory_skip_does_not_block(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                return_value=verification_graduation.VerifierDifferentialOutcome(
                    admitted=False, skipped=True, reason="advisory SKIP -- NON_HERMETIC_BY_CONSTRUCTION new verifier"
                ),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert not failed

    def test_exception_b_error_surfaces(self, tmp_path: Path) -> None:
        rel = self._setup_new_verifier(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=[rel, "scripts/target.py"]),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=rel + "\n")),
            patch(
                "scripts.verification_graduation.run_verifier_differential",
                side_effect=verification_graduation.GraduationError("worktree add failed"),
            ),
        ):
            validate_verifier_same_pr_guard(failed)
        assert any("error --" in f for f in failed), failed


def test_same_pr_guard_passes_on_no_verifier_in_diff() -> None:
    """VP step 6: same-PR guard passes when no verifier file is in the diff."""
    failed: list = []
    with patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]):
        validate_verifier_same_pr_guard(failed)
    assert not failed
