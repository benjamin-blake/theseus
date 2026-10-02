"""Tests for validate_dq_manifest_gate() -- allowlist enforcement."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ops_governance.validate_dq_manifest_gate import validate_dq_manifest_gate


class TestValidateDqManifestGate:
    """Tests for validate_dq_manifest_gate() -- allowlist enforcement."""

    _OPS_YAML = (
        "tables:\n"
        "  ops_recommendations:\n"
        "    columns:\n"
        "      title:\n"
        "        tests:\n"
        "          - not_null:\n"
        "              enforced: true\n"
    )

    def _write_ops_yaml(self, tmp_path: Path, content: str = "") -> None:
        dq_dir = tmp_path / "config" / "agent" / "data_quality"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "ops.yaml").write_text(content or self._OPS_YAML, encoding="utf-8")

    def _write_manifest(self, tmp_path: Path, state: str) -> None:
        dec_dir = tmp_path / "config" / "agent" / "data_quality" / "decisions"
        dec_dir.mkdir(parents=True, exist_ok=True)
        manifest_yaml = f"table: ops_recommendations\nfields:\n  title:\n    enforcement_ready: {state}\n"
        (dec_dir / "ops_recommendations.yaml").write_text(manifest_yaml, encoding="utf-8")

    def _run(self, tmp_path: Path) -> list[str]:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_dq_manifest_gate(failed)
        return failed

    def test_allowed_state_ready_now_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "READY_NOW")
        assert self._run(tmp_path) == []

    def test_allowed_state_write_fix_deployed_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "write_fix_deployed")
        assert self._run(tmp_path) == []

    def test_allowed_state_graduated_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "GRADUATED")
        assert self._run(tmp_path) == []

    def test_allowed_state_needs_temporal_gate_passes(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_TEMPORAL_GATE")
        assert self._run(tmp_path) == []

    def test_blocked_state_needs_write_fix_fails(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_WRITE_FIX")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_blocked_state_needs_data_correction_fails(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "NEEDS_DATA_CORRECTION")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_unknown_state_fails_closed(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        self._write_manifest(tmp_path, "SOME_FUTURE_UNKNOWN_STATE")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_missing_manifest_entry_fails_closed(self, tmp_path: Path) -> None:
        self._write_ops_yaml(tmp_path)
        dec_dir = tmp_path / "config" / "agent" / "data_quality" / "decisions"
        dec_dir.mkdir(parents=True, exist_ok=True)
        (dec_dir / "ops_recommendations.yaml").write_text("table: ops_recommendations\nfields: {}\n", encoding="utf-8")
        assert self._run(tmp_path) == ["DQ manifest gate"]

    def test_non_enforced_column_skipped(self, tmp_path: Path) -> None:
        ops_yaml = (
            "tables:\n"
            "  ops_recommendations:\n"
            "    columns:\n"
            "      title:\n"
            "        tests:\n"
            "          - not_null:\n"
            "              enforced: false\n"
        )
        self._write_ops_yaml(tmp_path, ops_yaml)
        assert self._run(tmp_path) == []

    def test_missing_ops_yaml_skips_gracefully(self, tmp_path: Path) -> None:
        assert self._run(tmp_path) == []


_CHECK = "validate_dq_manifest_gate"
_UNIT = "enforced tests"


def _declared(root: Path | None) -> tuple[list[str], registry._Declaration | None]:
    registry.pop_declaration()
    failed: list[str] = []
    if root is None:
        validate_dq_manifest_gate(failed)
    else:
        with patch("scripts.checks._common.ROOT", root):
            validate_dq_manifest_gate(failed)
    return failed, registry.pop_declaration()


def _write(root: Path, ops_yaml: str, manifest_yaml: str | None = None) -> None:
    dq_dir = root / "config" / "agent" / "data_quality"
    dq_dir.mkdir(parents=True, exist_ok=True)
    (dq_dir / "ops.yaml").write_text(ops_yaml, encoding="utf-8")
    if manifest_yaml is not None:
        (dq_dir / "decisions").mkdir(exist_ok=True)
        (dq_dir / "decisions" / "m.yaml").write_text(manifest_yaml, encoding="utf-8")


_MIXED_OPS_YAML = (
    "tables:\n"
    "  t1:\n"
    "    columns:\n"
    "      a:\n"
    "        tests:\n"
    "          - not_null:\n"
    "              enforced: true\n"
    "          - min_length:\n"
    "              enforced: false\n"
    "          - bare_string_entry\n"
    "      b:\n"
    "        tests:\n"
    "          - not_null:\n"
    "              enforced: true\n"
    "          - accepted_values: [x, y]\n"
    "      c: not_a_mapping\n"
    "  t2:\n"
    "    columns:\n"
    "      d:\n"
    "        tests:\n"
    "          - not_null:\n"
    "              enforced: true\n"
)

_MIXED_MANIFEST = "table: t1\nfields:\n  a:\n    enforcement_ready: READY_NOW\n  b:\n    enforcement_ready: GRADUATED\n"


class TestDqManifestGateAccountingDeclaration:
    """The check declares how many enforced tests it judged, so a run records enforced with a count that
    tracks the judged tests -- not the raw test-entry total, not a constant, and not the failure count."""

    def test_live_tree_declares_enforced(self) -> None:
        failed, declaration = _declared(None)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.unit) == ("examined", _UNIT)
        assert declaration.count is not None and declaration.count > 0
        assert outcome.status == "enforced"

    def test_count_tracks_enforced_tests_only(self, tmp_path: Path) -> None:
        _write(tmp_path, _MIXED_OPS_YAML, _MIXED_MANIFEST)
        (tmp_path / "config" / "agent" / "data_quality" / "decisions" / "m2.yaml").write_text(
            "table: t2\nfields:\n  d:\n    enforcement_ready: READY_NOW\n", encoding="utf-8"
        )

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "enforced"

    def test_blocked_tests_are_counted_and_record_failed(self, tmp_path: Path) -> None:
        _write(tmp_path, _MIXED_OPS_YAML, _MIXED_MANIFEST)  # no t2 manifest, so t2.d fails closed

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == ["DQ manifest gate"]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "failed"

    def test_no_enforced_tests_declares_vacuous_domain(self, tmp_path: Path) -> None:
        _write(tmp_path, _MIXED_OPS_YAML.replace("enforced: true", "enforced: false"))

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, _UNIT)
        assert outcome.status == "vacuous"

    def test_missing_ops_yaml_declares_skipped(self, tmp_path: Path) -> None:
        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert declaration.reason is not None and "not found" in declaration.reason
        assert outcome.status == "skipped"

    def test_unparseable_ops_yaml_declares_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "tables: [unclosed\n")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == []
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert declaration.reason is not None and "unparseable" in declaration.reason
        assert outcome.status == "skipped"

    def test_unparseable_manifest_is_ignored_and_tests_still_judged(self, tmp_path: Path) -> None:
        _write(tmp_path, _MIXED_OPS_YAML, "table: [unclosed\n")

        failed, declaration = _declared(tmp_path)
        outcome = registry.build_outcome(_CHECK, "check", declaration, bool(failed))

        assert failed == ["DQ manifest gate"]
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 3, _UNIT)
        assert outcome.status == "failed"
