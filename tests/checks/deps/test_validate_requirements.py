"""Tests for validate_requirements() -- VTS-14 network-error demotion (audit validate-test-suite-4df4d48)."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks.deps.validate_requirements import validate_requirements


def _write_requirements(tmp_path: Path, packages: list[str]) -> None:
    (tmp_path / "requirements.in").write_text("\n".join(packages) + "\n", encoding="utf-8")


class TestValidateRequirementsNetworkDemotion:
    """VTS-14: a network-classified pip-index error is a loud warning, never a failure; a
    genuinely not-found (typo'd) package still reds."""

    def test_network_error_leaves_failed_empty(self, tmp_path: Path, capsys) -> None:
        _write_requirements(tmp_path, ["requests"])
        mock_result = MagicMock(returncode=1, stderr="ERROR: Could not find a version... Connection timed out")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []
        captured = capsys.readouterr()
        assert "network" in captured.out.lower()
        assert "warning" in captured.out.lower()

    def test_timeout_and_unreachable_are_also_classified_as_network(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["pkg-a", "pkg-b"])

        def fake_run(cmd, **kwargs):
            pkg = cmd[-1]
            if pkg == "pkg-a":
                stderr = "ERROR: Read timeout occurred while contacting PyPI"
            else:
                stderr = "Temporary failure: host unreachable"
            return MagicMock(returncode=1, stderr=stderr)

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=fake_run),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []

    def test_not_found_package_still_fails(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["totally-not-a-real-package-xyz"])
        mock_result = MagicMock(returncode=1, stderr="ERROR: No matching distribution found")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == ["Requirements validation"]

    def test_mixed_run_fails_only_on_not_found(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["requests", "totally-not-a-real-package-xyz"])

        def fake_run(cmd, **kwargs):
            pkg = cmd[-1]
            if pkg == "requests":
                return MagicMock(returncode=1, stderr="ERROR: network unreachable")
            return MagicMock(returncode=1, stderr="ERROR: No matching distribution found")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=fake_run),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == ["Requirements validation"]

    def test_all_packages_found_no_warnings_no_failures(self, tmp_path: Path) -> None:
        _write_requirements(tmp_path, ["requests"])
        mock_result = MagicMock(returncode=0, stderr="")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []

    def test_wired_in_full_tier(self) -> None:
        """validate_requirements is a registered check in the full-tier sequence (post-merge
        only -- it is not part of pre_sequence())."""
        from scripts.checks import registry  # noqa: PLC0415

        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "validate_requirements" in full_names


class TestRequirementsFileMissing:
    """The early-return branch: no requirements.in under ROOT is a hard failure, not a skip."""

    def test_missing_requirements_file_appends_a_failure(self, tmp_path: Path, capsys) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == ["Requirements validation"]
        assert "requirements.in not found" in capsys.readouterr().out


class TestAccountingDeclaration:
    """Decision 170: every exit path declares exactly once, and last-call-wins picks the survivor."""

    @staticmethod
    def _declare(tmp_path: Path, packages: list[str] | None, run_result: MagicMock | None):
        from scripts.checks import registry  # noqa: PLC0415

        if packages is not None:
            _write_requirements(tmp_path, packages)
        registry.examined(-1, unit="sentinel")
        probe = nullcontext() if run_result is None else patch("scripts.checks._common.run", return_value=run_result)
        with patch("scripts.checks._common.ROOT", tmp_path), probe:
            validate_requirements([])
        return registry._CURRENT_DECLARATION

    def test_pass_path_declares_declared_packages(self, tmp_path: Path) -> None:
        declaration = self._declare(tmp_path, ["requests"], MagicMock(returncode=0, stderr=""))
        assert declaration.kind == "examined"
        assert declaration.count == 1 and declaration.unit == "declared_packages"

    def test_network_warning_path_still_declares_examined(self, tmp_path: Path) -> None:
        """A network warning does NOT convert the run to skipped -- those packages were examined."""
        result = MagicMock(returncode=1, stderr="ERROR: Connection timed out")
        declaration = self._declare(tmp_path, ["requests"], result)
        assert declaration.kind == "examined"
        assert declaration.count == 1 and declaration.unit == "declared_packages"

    def test_empty_domain_declares_examined_zero_not_skipped(self, tmp_path: Path) -> None:
        """No packages is an EMPTY DOMAIN (vacuous), never a skip."""
        declaration = self._declare(tmp_path, ["# only a comment"], None)
        assert declaration.kind == "examined"
        assert declaration.count == 0 and declaration.unit == "declared_packages"

    def test_missing_input_declares_skipped(self, tmp_path: Path) -> None:
        """The missing-input path declares skipped; the run still FAILS (Decision 170 clause 1)."""
        declaration = self._declare(tmp_path, None, None)
        assert declaration.kind == "skipped"
        assert "requirements.in not found" in declaration.reason


class TestNonPackageLinesAndProbeFailures:
    """The remaining branches of the declaration scan and the probe loop."""

    @pytest.mark.parametrize(
        "directive",
        ["-r other.in", "-e .", "git+https://example.invalid/pkg.git", "https://example.invalid/pkg.whl"],
    )
    def test_non_pypi_directives_are_skipped(self, tmp_path: Path, directive: str) -> None:
        """A directive line names no PyPI distribution, so it is never probed."""
        _write_requirements(tmp_path, [directive, "requests>=2.0"])
        probed: list[str] = []

        def fake_run(cmd, **kwargs):
            probed.append(cmd[-1])
            return MagicMock(returncode=0, stderr="")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=fake_run),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == []
        assert probed == ["requests"], "only the real declaration is probed"

    def test_missing_pip_is_a_hard_failure(self, tmp_path: Path) -> None:
        """pip absent (a broken venv) is a real failure, never a network-style warning."""
        _write_requirements(tmp_path, ["requests"])
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=FileNotFoundError("pip")),
        ):
            failed: list[str] = []
            validate_requirements(failed)
        assert failed == ["Requirements validation"]

    def test_non_standard_package_name_is_rejected_before_any_subprocess(self, tmp_path: Path) -> None:
        """The charset guard at :48 is defence-in-depth BEHIND the extraction regex at :35, which
        already constrains the name to [A-Za-z0-9_-]. It cannot fire on any file content, so the
        only way to exercise it -- and to prove it still short-circuits before _common.run -- is to
        force the guard itself to reject. A real regression (dropping the guard) would let an
        unsanitised name reach the subprocess, which is exactly what this pins."""
        import scripts.checks.deps.validate_requirements as module  # noqa: PLC0415

        _write_requirements(tmp_path, ["requests"])
        real_match = module.re.match

        def guarded_match(pattern, string, *args, **kwargs):
            if pattern == r"^[A-Za-z0-9_-]+$":
                return None
            return real_match(pattern, string, *args, **kwargs)

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=AssertionError("must not probe")) as probe,
            patch.object(module.re, "match", guarded_match),
        ):
            failed: list[str] = []
            validate_requirements(failed)

        assert failed == ["Requirements validation"]
        assert probe.call_count == 0
