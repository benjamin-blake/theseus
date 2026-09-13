"""Tests for validate_ducklake_version_lockstep() -- the OQ.12 SSOT drift gate."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.misc.validate_ducklake_version_lockstep import validate_ducklake_version_lockstep


class TestDucklakeVersionLockstepGate:
    """Tests for validate_ducklake_version_lockstep() -- the OQ.12 SSOT drift gate."""

    def test_passes_on_coherent_tree(self, tmp_path: Path) -> None:
        """Gate passes when requirements.in is in sync and no literal in derive surfaces."""
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        # coherent requirements.in
        req = tmp_path / "requirements.in"
        req.write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("duckdb==1.5.4\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        runtime = src / "ducklake_runtime.py"
        no_literal = (
            "# no literal\n"
            "from src.common.ducklake_version import pinned_duckdb_version as _p\n"
            "_PINNED_DUCKDB_VERSION = None\n"
        )
        runtime.write_text(no_literal, encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        build = scripts / "build_lambda.py"
        build.write_text(
            "from src.common.ducklake_version import pinned_duckdb_version as _p\nPINNED_DUCKDB_VERSION = _p()\n",
            encoding="utf-8",
        )

        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert failed == [], failed

    def test_fails_when_requirements_drifts(self, tmp_path: Path) -> None:
        """Gate fails when requirements.in has an old floor."""
        req = tmp_path / "requirements.in"
        req.write_text("duckdb>=1.5.3  # old\n", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("duckdb==1.5.3\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        (src / "ducklake_runtime.py").write_text("# no literal\n", encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert any("duckdb floor" in f or "requirements" in f for f in failed), failed

    def test_fails_when_literal_in_derive_surface(self, tmp_path: Path) -> None:
        """Gate fails when a raw PINNED_DUCKDB_VERSION = '...' literal is in a derive surface."""
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        req = tmp_path / "requirements.in"
        req.write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("duckdb==1.5.4\n", encoding="utf-8")

        src = tmp_path / "src" / "common"
        src.mkdir(parents=True)
        # reintroduce a hardcoded literal
        (src / "ducklake_runtime.py").write_text('PINNED_DUCKDB_VERSION = "1.5.3"\n', encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert any("hardcoded" in f or "literal" in f or "ducklake_runtime" in f for f in failed), failed


class TestUnexpectedFailuresAreReported:
    """The two defensive except-arms of validate_ducklake_version_lockstep -- an unexpected
    exception out of the requirements-floor check, and an unreadable derive surface -- must each
    add their own failed[] entry rather than being swallowed into a clean green."""

    @staticmethod
    def _write_clean_tree(tmp_path: Path) -> None:
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        (tmp_path / "requirements.in").write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("duckdb==1.5.4\n", encoding="utf-8")
        (tmp_path / "src" / "common").mkdir(parents=True)
        (tmp_path / "src" / "common" / "ducklake_runtime.py").write_text("# no literal\n", encoding="utf-8")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")

    def test_requirements_check_exception_is_reported(self, tmp_path: Path) -> None:
        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        self._write_clean_tree(tmp_path)
        failed: list[str] = []
        with patch.object(sdv, "sync", side_effect=RuntimeError("synthetic sync failure")):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        assert failed == ["ducklake-version-lockstep: requirements check raised: synthetic sync failure"]

    def test_unreadable_derive_surface_is_reported(self, tmp_path: Path) -> None:
        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        self._write_clean_tree(tmp_path)
        surface = tmp_path / "src" / "common" / "ducklake_runtime.py"
        surface.unlink()
        surface.mkdir()
        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        prefix = f"ducklake-version-lockstep: cannot read {surface}: "
        read_errors = [f for f in failed if f.startswith(prefix)]
        assert read_errors, failed
        assert read_errors == failed


class TestCompiledPinSatisfiesFloor:
    """The second half of check (a): the compiled requirements.txt pin must satisfy the
    requirements.in floor, so moving the floor without recompiling is caught."""

    @staticmethod
    def _run(tmp_path: Path, floor: str, pin: str | None) -> list[str]:
        import scripts.sync.ducklake_version as sdv  # noqa: PLC0415

        (tmp_path / "requirements.in").write_text(floor, encoding="utf-8")
        if pin is not None:
            (tmp_path / "requirements.txt").write_text(pin, encoding="utf-8")
        (tmp_path / "src" / "common").mkdir(parents=True)
        (tmp_path / "src" / "common" / "ducklake_runtime.py").write_text("# no literal\n", encoding="utf-8")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "build_lambda.py").write_text("# no literal\n", encoding="utf-8")
        failed: list[str] = []
        with patch.object(sdv, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                validate_ducklake_version_lockstep(failed)
        return failed

    def test_fails_when_compiled_pin_is_below_the_floor(self, tmp_path: Path) -> None:
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        failed = self._run(tmp_path, _sdv_inner._expected_floor_line("1.5.4") + "\n", "duckdb==1.5.3\n")
        assert any("pins duckdb==1.5.3" in f and "rejects" in f for f in failed), failed

    def test_fails_when_the_compiled_output_has_no_duckdb_pin(self, tmp_path: Path) -> None:
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        failed = self._run(tmp_path, _sdv_inner._expected_floor_line("1.5.4") + "\n", "requests==2.34.2\n")
        assert any("no duckdb line" in f for f in failed), failed

    def test_duckdb_prefixed_distribution_is_not_mistaken_for_duckdb(self, tmp_path: Path) -> None:
        """`duckdb-engine` is a different distribution -- the pin scan must not match it."""
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415

        failed = self._run(tmp_path, _sdv_inner._expected_floor_line("1.5.4") + "\n", "duckdb-engine==0.1.0\nduckdb==1.5.4\n")
        assert failed == [], failed


class TestAccountingDeclaration:
    """Decision 170 touch-it-fix-it: exactly one terminal declaration survives."""

    def test_declares_the_floor_plus_every_derive_surface_read(self) -> None:
        from scripts.checks import registry  # noqa: PLC0415

        registry.examined(-1, unit="sentinel")
        validate_ducklake_version_lockstep([])
        declaration = registry._CURRENT_DECLARATION
        assert declaration.kind == "examined"
        assert declaration.unit == "ducklake_derive_surfaces"
        assert declaration.count == 3, "1 requirements.in floor + 2 derive surfaces"


class TestEveryExitPathDeclares:
    """REGRESSION (code-review round 1, Medium): the terminal declaration used to sit after block
    (b) inside the try, so an unexpected exception in the derive-surface loop escaped with no
    accounting declaration at all -- breaking the plan's own every-exit-path criterion."""

    def test_an_undecodable_derive_surface_still_leaves_a_declaration(self, tmp_path: Path) -> None:
        """Invalid UTF-8 raises UnicodeDecodeError (a ValueError), which escapes the OSError arm."""
        import scripts.sync.ducklake_version as _sdv_inner  # noqa: PLC0415
        from scripts.checks import registry  # noqa: PLC0415

        (tmp_path / "requirements.in").write_text(_sdv_inner._expected_floor_line("1.5.4") + "\n", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("duckdb==1.5.4\n", encoding="utf-8")
        (tmp_path / "src" / "common").mkdir(parents=True)
        (tmp_path / "src" / "common" / "ducklake_runtime.py").write_text("# no literal\n", encoding="utf-8")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "build_lambda.py").write_bytes(b"\xff\xfe not utf-8\n")

        registry.examined(-1, unit="sentinel")
        failed: list[str] = []
        with patch.object(_sdv_inner, "_get_pinned_version", return_value="1.5.4"):
            with patch("scripts.checks._common.ROOT", tmp_path):
                with pytest.raises(UnicodeDecodeError):
                    validate_ducklake_version_lockstep(failed)

        declaration = registry._CURRENT_DECLARATION
        assert declaration.kind == "examined"
        assert declaration.unit == "ducklake_derive_surfaces"
        assert declaration.count == 2, "1 requirements.in floor + the 1 surface read before the raise"
