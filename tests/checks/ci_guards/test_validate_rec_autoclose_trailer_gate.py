"""Tests for validate_rec_autoclose_trailer_gate() -- the Resolves: trailer merge-leg gate's
delegation-shape pin (rec-3775 / rec-2922 / rec-3901).

Pass-path fixture is the real committed repository state. Each negative patches this module's
own `_read` binding to simulate ONE removal (workflow stops delegating; ci_rca_lifecycle no
longer references the gate; either git-ops.yaml clause absent) so it fails on exactly that
removal and nothing else.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from scripts.checks import registry
from scripts.checks.ci_guards.validate_rec_autoclose_trailer_gate import (
    _GIT_OPS_CONTRACT,
    _LIFECYCLE_MODULE_PATH,
    _WORKFLOW_PATH,
    validate_rec_autoclose_trailer_gate,
)

_MODULE = "scripts.checks.ci_guards.validate_rec_autoclose_trailer_gate"


def _real_sources() -> dict[str, str]:
    from scripts.checks import _common

    return {
        rel: (_common.ROOT / rel).read_text(encoding="utf-8")
        for rel in (_WORKFLOW_PATH, _LIFECYCLE_MODULE_PATH, _GIT_OPS_CONTRACT)
    }


def _run(sources: dict[str, str]) -> list[str]:
    def fake_read(root, rel):  # noqa: ANN001, ARG001
        return sources.get(rel)

    with patch(f"{_MODULE}._read", side_effect=fake_read):
        failed: list[str] = []
        validate_rec_autoclose_trailer_gate(failed)
    return failed


class TestPassPath:
    def test_passes_against_the_real_committed_repository(self) -> None:
        failed: list[str] = []
        validate_rec_autoclose_trailer_gate(failed)
        assert failed == []

    def test_registered_in_pre_sequence(self) -> None:
        names = {step.name for step in registry.pre_sequence()}
        assert "validate_rec_autoclose_trailer_gate" in names

    def test_examined_count_is_four_delegation_assertions(self) -> None:
        with registry.outcome_scope("validate_rec_autoclose_trailer_gate"):
            failed: list[str] = []
            validate_rec_autoclose_trailer_gate(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 4
        assert declaration.unit == "delegation_assertions"


class TestRemovalNegatives:
    def test_fails_when_workflow_stops_delegating(self) -> None:
        sources = _real_sources()
        sources[_WORKFLOW_PATH] = sources[_WORKFLOW_PATH].replace("close_recs_from_trailer", "inline_loop")
        failed = _run(sources)
        assert any("no longer delegates" in item for item in failed), failed

    def test_fails_when_gate_unreferenced(self) -> None:
        sources = _real_sources()
        sources[_LIFECYCLE_MODULE_PATH] = sources[_LIFECYCLE_MODULE_PATH].replace("merge_leg_refuses", "unrelated_symbol")
        failed = _run(sources)
        assert any("no longer references the merge-leg gate" in item for item in failed), failed

    def test_fails_when_carrier_clause_absent(self) -> None:
        sources = _real_sources()
        sources[_GIT_OPS_CONTRACT] = sources[_GIT_OPS_CONTRACT].replace("IMPLEMENTATION merge", "the right merge")
        failed = _run(sources)
        assert any("carrier rule" in item for item in failed), failed

    def test_fails_when_placement_clause_absent(self) -> None:
        sources = _real_sources()
        sources[_GIT_OPS_CONTRACT] = sources[_GIT_OPS_CONTRACT].replace("Key: value", "properly shaped")
        failed = _run(sources)
        assert any("placement rule" in item for item in failed), failed

    def test_skips_when_a_source_is_unreadable(self) -> None:
        with (
            registry.outcome_scope("validate_rec_autoclose_trailer_gate"),
            patch(f"{_MODULE}._read", return_value=None),
        ):
            failed: list[str] = []
            validate_rec_autoclose_trailer_gate(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed  # unreadable sources are also a hard failure, never a silent pass

    def test_read_returns_none_on_oserror(self) -> None:
        with (
            registry.outcome_scope("validate_rec_autoclose_trailer_gate"),
            patch.object(pathlib.Path, "read_text", side_effect=OSError("unreadable")),
        ):
            failed: list[str] = []
            validate_rec_autoclose_trailer_gate(failed)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert any("could not read" in item for item in failed)
        assert failed
