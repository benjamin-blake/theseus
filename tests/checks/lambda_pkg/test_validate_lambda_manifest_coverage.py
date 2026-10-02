"""Tests for validate_lambda_manifest_coverage()."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import lambda_manifest
from scripts.checks import _common, registry
from scripts.checks.lambda_pkg.validate_lambda_manifest_coverage import validate_lambda_manifest_coverage


class TestValidateLambdaManifestCoverage:
    """Tests for validate_lambda_manifest_coverage() -- coverage gate wrapper."""

    def test_passes_when_cmd_check_coverage_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert failed == []

    def test_fails_when_cmd_check_coverage_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed


_CHECK = "validate_lambda_manifest_coverage"
_UNIT = "lambda dirs"
_REPO_ROOT = Path(__file__).parents[3]
_FAILED_LABEL = "Lambda manifest coverage"


def _write_manifest(lambdas_dir: Path, name: str) -> None:
    (lambdas_dir / name).mkdir(parents=True)
    (lambdas_dir / name / "manifest.yaml").write_text("artifact: x.zip\n", encoding="utf-8")


@contextmanager
def _counting_manifest_probes(lambdas_dir: Path) -> Iterator[list[Path]]:
    """Record every <dir>/manifest.yaml existence probe under `lambdas_dir`, i.e. each directory the helper's
    coverage loop actually inspected (the wrapper's own count never probes manifest.yaml)."""
    real_exists = Path.exists
    probed: list[Path] = []

    def _exists(self: Path, *, follow_symlinks: bool = True) -> bool:
        if self.name == "manifest.yaml" and self.parent.parent == lambdas_dir:
            probed.append(self)
        return real_exists(self, follow_symlinks=follow_symlinks)

    with patch.object(Path, "exists", autospec=True, side_effect=_exists):
        yield probed


def _declared(lambdas_dir: Path) -> tuple[list[str], registry._Declaration | None]:
    """Run the check against the real, unmocked helper with its src/lambdas/ pointed at `lambdas_dir`."""
    registry.pop_declaration()
    failed: list[str] = []
    with patch.object(lambda_manifest, "_LAMBDAS_DIR", lambdas_dir):
        validate_lambda_manifest_coverage(failed)
    return failed, registry.pop_declaration()


class TestLambdaManifestCoverageAccountingDeclaration:
    """The check declares how many src/lambdas/<name>/ directories it probed for a manifest, so a run records
    enforced with a count that tracks src/lambdas/ -- not a constant, not the manifest count and not the
    failure count."""

    def test_real_tree_declares_every_lambda_dir(self) -> None:
        lambdas_dir = _REPO_ROOT / "src" / "lambdas"
        expected = sum(1 for c in lambdas_dir.iterdir() if c.is_dir() and c.name != "__pycache__")

        registry.pop_declaration()
        failed: list[str] = []
        with _counting_manifest_probes(lambdas_dir) as probed:
            validate_lambda_manifest_coverage(failed)
        declaration = registry.pop_declaration()
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert expected > 0
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)
        assert len(probed) == expected
        assert outcome.status == "enforced"

    def test_count_excludes_pycache_and_plain_files(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta", "gamma"):
            _write_manifest(tmp_path, name)
        _write_manifest(tmp_path, "__pycache__")
        (tmp_path / "CLAUDE.md").write_text("x\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "enforced"

    def test_uncovered_dir_is_counted_and_records_failed(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "covered")
        (tmp_path / "uncovered_one").mkdir()
        (tmp_path / "uncovered_two").mkdir()

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == [_FAILED_LABEL]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "failed"

    def test_declared_count_equals_dirs_the_helper_actually_probed(self, tmp_path: Path) -> None:
        """Pins the wrapper's count to the helper's own coverage loop: a helper that stopped at the first
        uncovered directory, or skipped some directories, would probe fewer manifests than the check declares."""
        (tmp_path / "a_uncovered").mkdir()
        _write_manifest(tmp_path, "b_covered")
        (tmp_path / "c_uncovered").mkdir()
        _write_manifest(tmp_path, "d_covered")
        _write_manifest(tmp_path, "__pycache__")
        (tmp_path / "notes.txt").write_text("x\n", encoding="utf-8")
        with _counting_manifest_probes(tmp_path) as probed:
            failed, declaration = _declared(tmp_path)

        assert failed == [_FAILED_LABEL]
        assert declaration is not None
        assert declaration.count == len(probed) == 4

    def test_empty_lambdas_dir_declares_vacuous_domain(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("x\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "vacuous"

    def test_absent_lambdas_dir_declares_zero_and_records_failed(self, tmp_path: Path) -> None:
        failed, declaration = _declared(tmp_path / "missing")
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == [_FAILED_LABEL]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "failed"


class TestSysPathShim:
    """Both branches of the repo-root sys.path shim around the helper import."""

    def test_injects_root_for_the_call_and_removes_it_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        root_str = str(_common.ROOT)
        monkeypatch.setattr(sys, "path", [p for p in sys.path if p != root_str])
        seen_during_call: list[bool] = []

        def _record_shim(_args: object) -> int:
            seen_during_call.append(root_str in sys.path)
            return 0

        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.side_effect = _record_shim

        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)

        assert failed == []
        assert seen_during_call == [True]
        assert root_str not in sys.path

    def test_leaves_root_in_place_when_already_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        root_str = str(_common.ROOT)
        monkeypatch.setattr(sys, "path", [root_str, *(p for p in sys.path if p != root_str)])
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 0

        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)

        assert failed == []
        assert sys.path.count(root_str) == 1
