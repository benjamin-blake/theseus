"""Tests for validate_lambda_manifests()."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import lambda_manifest
from scripts.checks import _common, registry
from scripts.checks.lambda_pkg.validate_lambda_manifests import validate_lambda_manifests


class TestValidateLambdaManifests:
    """Tests for validate_lambda_manifests() -- schema validation wrapper."""

    def test_passes_when_cmd_validate_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert failed == []

    def test_fails_when_cmd_validate_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.side_effect = RuntimeError("unexpected boom")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed


_CHECK = "validate_lambda_manifests"
_UNIT = "manifests"
_REPO_ROOT = Path(__file__).parents[3]
_FAILED_LABEL = "Lambda manifest schema validation"


def _write_manifest(lambdas_dir: Path, name: str, body: str = "artifact: x.zip\n") -> None:
    (lambdas_dir / name).mkdir(parents=True)
    (lambdas_dir / name / "manifest.yaml").write_text(body, encoding="utf-8")


def _declared(lambdas_dir: Path) -> tuple[list[str], registry._Declaration | None]:
    """Run the check against the real, unmocked helper with its src/lambdas/ pointed at `lambdas_dir`."""
    registry.pop_declaration()
    failed: list[str] = []
    with patch.object(lambda_manifest, "_LAMBDAS_DIR", lambdas_dir):
        validate_lambda_manifests(failed)
    return failed, registry.pop_declaration()


class TestLambdaManifestsAccountingDeclaration:
    """The check declares how many manifest.yaml files it schema-validated, so a run records enforced with a
    count that tracks src/lambdas/ -- not a constant, not the directory count and not the failure count."""

    def test_real_tree_declares_every_manifest(self) -> None:
        expected = len(list((_REPO_ROOT / "src" / "lambdas").glob("*/manifest.yaml")))

        registry.pop_declaration()
        failed: list[str] = []
        validate_lambda_manifests(failed)
        declaration = registry.pop_declaration()
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert expected > 0
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, _UNIT)
        assert outcome.status == "enforced"

    def test_count_excludes_dirs_without_manifest_pycache_and_files(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta", "gamma"):
            _write_manifest(tmp_path, name)
        (tmp_path / "no_manifest_yet").mkdir()
        _write_manifest(tmp_path, "__pycache__")
        (tmp_path / "CLAUDE.md").write_text("x\n", encoding="utf-8")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "enforced"

    def test_invalid_manifest_is_counted_and_records_failed(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "good")
        _write_manifest(tmp_path, "bad", "artifact: not-a-zip\n")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == [_FAILED_LABEL]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 2, _UNIT)
        assert outcome.status == "failed"

    def test_declared_count_equals_manifests_the_helper_actually_loaded(self, tmp_path: Path) -> None:
        """Pins the wrapper's count to the helper's own validation loop: a helper that stopped at the first
        invalid manifest, or skipped some directories, would load fewer manifests than the check declares."""
        _write_manifest(tmp_path, "a_bad", "artifact: not-a-zip\n")
        _write_manifest(tmp_path, "b_good")
        _write_manifest(tmp_path, "c_not_a_mapping", "- just\n- a list\n")
        _write_manifest(tmp_path, "d_good")
        (tmp_path / "e_no_manifest").mkdir()
        _write_manifest(tmp_path, "__pycache__")
        real_load = lambda_manifest.load
        loaded: list[Path] = []

        def _counting_load(manifest_path: Path) -> lambda_manifest.LambdaManifest:
            loaded.append(manifest_path)
            return real_load(manifest_path)

        with patch.object(lambda_manifest, "load", _counting_load):
            failed, declaration = _declared(tmp_path)

        assert failed == [_FAILED_LABEL]
        assert declaration is not None
        assert declaration.count == len(loaded) == 4

    def test_empty_lambdas_dir_declares_vacuous_domain(self, tmp_path: Path) -> None:
        (tmp_path / "no_manifest_yet").mkdir()

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
        mock_lm.cmd_validate.side_effect = _record_shim

        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)

        assert failed == []
        assert seen_during_call == [True]
        assert root_str not in sys.path

    def test_leaves_root_in_place_when_already_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        root_str = str(_common.ROOT)
        monkeypatch.setattr(sys, "path", [root_str, *(p for p in sys.path if p != root_str)])
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 0

        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)

        assert failed == []
        assert sys.path.count(root_str) == 1
