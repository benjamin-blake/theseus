"""Tests for validate_field_semantics_drift() -- the T2.33 fail-closed drift gate."""

from pathlib import Path
from typing import Any

from scripts.checks import registry
from scripts.checks._common import ROOT
from scripts.checks.ops_governance.validate_field_semantics_drift import validate_field_semantics_drift


class TestFieldSemanticsDriftGate:
    """Tests for validate_field_semantics_drift() -- the T2.33 fail-closed drift gate."""

    def test_passes_when_committed_matches_generator(self, tmp_path: Path) -> None:
        """If the committed file matches what the generator would produce: no failure."""
        import importlib.util as _ilu

        gen_path = ROOT / "scripts" / "schema_to_field_semantics.py"
        spec = _ilu.spec_from_file_location("_gen", gen_path)
        gen = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(gen)  # type: ignore[union-attr]

        # Write the exact generator output to tmp_path
        output = tmp_path / "field_semantics.yaml"
        output.write_text(gen._emit_yaml(gen.generate(include_prose=False)), encoding="utf-8")

        import unittest.mock as _m

        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
            failed: list[str] = []
            validate_field_semantics_drift(failed)
        assert failed == [], f"Expected no failure but got: {failed}"

    def test_fails_when_committed_has_drift(self, tmp_path: Path) -> None:
        """If the committed file has extra content vs the generator output: failure appended."""
        import importlib.util as _ilu
        import unittest.mock as _m

        gen_path = ROOT / "scripts" / "schema_to_field_semantics.py"
        spec = _ilu.spec_from_file_location("_gen2", gen_path)
        gen = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(gen)  # type: ignore[union-attr]

        output = tmp_path / "field_semantics.yaml"
        output.write_text(
            gen._emit_yaml(gen.generate(include_prose=False)) + "\n# injected drift\n",
            encoding="utf-8",
        )

        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
            failed: list[str] = []
            validate_field_semantics_drift(failed)
        assert len(failed) == 1, f"Expected exactly one failure but got: {failed}"
        assert "drift" in failed[0].lower() or "Field semantics" in failed[0]

    def test_does_not_auto_write_on_drift(self, tmp_path: Path) -> None:
        """The drift gate MUST NOT auto-write (Decision 55)."""
        import importlib.util as _ilu
        import unittest.mock as _m

        gen_path = ROOT / "scripts" / "schema_to_field_semantics.py"
        spec = _ilu.spec_from_file_location("_gen3", gen_path)
        gen = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(gen)  # type: ignore[union-attr]

        injected = gen._emit_yaml(gen.generate(include_prose=False)) + "\n# injected drift\n"
        output = tmp_path / "field_semantics.yaml"
        output.write_text(injected, encoding="utf-8")

        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
            failed: list[str] = []
            validate_field_semantics_drift(failed)

        assert output.read_text(encoding="utf-8") == injected, (
            "validate_field_semantics_drift must NOT auto-write the file (Decision 55 fail-closed)"
        )


class TestFieldSemanticsDriftErrorBranches:
    """The two error-path appends the happy/drift tests above never reach."""

    def test_unreadable_output_path_appends_the_read_failure(self, tmp_path: Path) -> None:
        """A committed file that cannot be read is a failure, never a silent no-drift."""
        import unittest.mock as _m

        missing = tmp_path / "never_created" / "field_semantics.yaml"
        with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", missing):
            failed: list[str] = []
            validate_field_semantics_drift(failed)

        assert len(failed) == 1, f"Expected exactly one failure but got: {failed}"
        assert failed[0].startswith("Field semantics drift gate: cannot read ")
        assert "No such file or directory" in failed[0]

    def test_generator_exception_appends_the_generator_failure(self, tmp_path: Path) -> None:
        """A generator that raises is a failure, never treated as no-drift."""
        import unittest.mock as _m

        output = tmp_path / "field_semantics.yaml"
        output.write_text("committed: content\n", encoding="utf-8")

        with (
            _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output),
            _m.patch("scripts.schema_to_field_semantics.generate", side_effect=RuntimeError("synthetic boom")),
        ):
            failed: list[str] = []
            validate_field_semantics_drift(failed)

        assert failed == ["Field semantics drift gate: generator raised: synthetic boom"]


_UNIT = "sections"
_SYNTHETIC_DOC: dict[str, Any] = {"tables": {"history": {}}, "fields": {"ulid": {}}, "ops_tables": {}}


def _declared(output: Path, doc: dict | None = None) -> tuple[list[str], registry._Declaration | None]:
    import unittest.mock as _m

    registry.pop_declaration()
    failed: list[str] = []
    with _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output):
        if doc is None:
            validate_field_semantics_drift(failed)
        else:
            with _m.patch("scripts.schema_to_field_semantics.generate", return_value=doc):
                validate_field_semantics_drift(failed)
    return failed, registry.pop_declaration()


class TestExaminedDeclaration:
    """Decision 170: the check declares examined over the regenerated document's top-level sections."""

    def test_matching_file_declares_examined_over_the_regenerated_sections(self, tmp_path: Path) -> None:
        from scripts.schema_to_field_semantics import _emit_yaml

        output = tmp_path / "field_semantics.yaml"
        output.write_text(_emit_yaml(_SYNTHETIC_DOC), encoding="utf-8")
        failed, decl = _declared(output, _SYNTHETIC_DOC)
        assert failed == []
        assert decl is not None
        assert (decl.kind, decl.count, decl.unit) == ("examined", 3, _UNIT)
        outcome = registry.build_outcome("validate_field_semantics_drift", "check", decl, appended_to_failed=False)
        assert outcome.status == "enforced"

    def test_drifted_file_counts_the_regenerated_side_not_the_committed_side(self, tmp_path: Path) -> None:
        output = tmp_path / "field_semantics.yaml"
        output.write_text("tables: {}\n", encoding="utf-8")
        failed, decl = _declared(output, _SYNTHETIC_DOC)
        assert len(failed) == 1
        assert decl is not None
        assert (decl.kind, decl.count, decl.unit) == ("examined", 3, _UNIT)
        outcome = registry.build_outcome("validate_field_semantics_drift", "check", decl, appended_to_failed=True)
        assert outcome.status == "failed"

    def test_empty_regenerated_document_declares_a_vacuous_domain(self, tmp_path: Path) -> None:
        from scripts.schema_to_field_semantics import _emit_yaml

        output = tmp_path / "field_semantics.yaml"
        output.write_text(_emit_yaml({}), encoding="utf-8")
        failed, decl = _declared(output, {})
        assert failed == []
        assert decl is not None
        assert (decl.kind, decl.count) == ("examined", 0)
        outcome = registry.build_outcome("validate_field_semantics_drift", "check", decl, appended_to_failed=False)
        assert outcome.status == "vacuous"

    def test_live_tree_declares_every_generated_section(self, tmp_path: Path) -> None:
        from scripts.schema_to_field_semantics import _emit_yaml, generate

        live = generate(include_prose=False)
        output = tmp_path / "field_semantics.yaml"
        output.write_text(_emit_yaml(live), encoding="utf-8")
        failed, decl = _declared(output)
        assert failed == []
        assert decl is not None
        assert decl.kind == "examined"
        assert decl.count == len(live) > 0

    def test_unreadable_file_fails_without_a_declaration(self, tmp_path: Path) -> None:
        failed, decl = _declared(tmp_path / "never_created" / "field_semantics.yaml", _SYNTHETIC_DOC)
        assert len(failed) == 1
        assert decl is None

    def test_raising_generator_fails_without_a_declaration(self, tmp_path: Path) -> None:
        import unittest.mock as _m

        output = tmp_path / "field_semantics.yaml"
        output.write_text("committed: content\n", encoding="utf-8")
        registry.pop_declaration()
        failed: list[str] = []
        with (
            _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output),
            _m.patch("scripts.schema_to_field_semantics.generate", side_effect=RuntimeError("synthetic boom")),
        ):
            validate_field_semantics_drift(failed)
        assert len(failed) == 1
        assert registry.pop_declaration() is None


class TestSysPathInjection:
    """The repo root is injected onto sys.path only when absent, and removed again on exit."""

    def test_absent_root_is_injected_for_the_run_and_removed_afterwards(self, tmp_path: Path) -> None:
        import sys
        import unittest.mock as _m

        from scripts.schema_to_field_semantics import _emit_yaml

        output = tmp_path / "field_semantics.yaml"
        output.write_text(_emit_yaml(_SYNTHETIC_DOC), encoding="utf-8")
        root_str = str(ROOT)
        seen: list[bool] = []

        def _generate(*, include_prose: bool = False) -> dict:
            seen.append(sys.path[0] == root_str)
            return _SYNTHETIC_DOC

        stripped = [p for p in sys.path if p != root_str]
        with (
            _m.patch.object(sys, "path", stripped),
            _m.patch("scripts.schema_to_field_semantics._OUTPUT_PATH", output),
            _m.patch("scripts.schema_to_field_semantics.generate", side_effect=_generate),
        ):
            failed: list[str] = []
            validate_field_semantics_drift(failed)
            after = list(sys.path)

        assert failed == []
        assert seen == [True]
        assert root_str not in after
