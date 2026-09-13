"""Mirror test for scripts/checks/deps/validate_pre_glob_closure.py's BLOCKING contract (LSA-06)
and its Decision 170 accounting. Replaces the pre-decomposition suite's
TestAdvisoryContractAndAccounting: the check now APPENDS to `failed` on a genuine finding instead
of only printing one -- this is the acceptance proper for the wave-4c flip."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.checks import _common, registry
from scripts.checks._schema import Entry
from scripts.checks.deps import validate_pre_glob_closure as vpgc
from scripts.checks.registry import _Declaration


def _entry(name: str, module: str, **kwargs: Any) -> Entry:
    defaults: dict[str, Any] = {"pre": True, "pre_globs": ("scripts/checks/**",), "full_segment": "full_after_lint"}
    defaults.update(kwargs)
    return Entry(name=name, module=module, attr=name, **defaults)


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts" / "checks" / "fake").mkdir(parents=True)
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "checks" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "checks" / "fake" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "hublib.py").write_text("def hub():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "checks" / "fake" / "validate_thing.py").write_text(
        "from scripts.hublib import hub\n\n\ndef validate_thing(failed):\n    hub()\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "checks" / "fake" / "_manifest.py").write_text(
        'ENTRIES = ("scripts.checks.fake.validate_thing",)\n', encoding="utf-8"
    )
    return tmp_path


def _run_against(root: Path, entries: dict[str, Entry]) -> tuple[list[str], _Declaration]:
    """Dispatch the auditor with ROOT and the manifest roster swapped for a fixture pair."""
    failed: list[str] = []
    with patch.object(_common, "ROOT", root), patch.object(registry, "_ALL_ENTRIES", entries):
        with registry.outcome_scope("validate_pre_glob_closure"):
            vpgc.validate_pre_glob_closure(failed)
        declaration = registry.pop_declaration()
    assert declaration is not None, "validate_pre_glob_closure must always declare Decision 170 accounting"
    return failed, declaration


class TestBlockingContractAndAccounting:
    """The check APPENDS to `failed` on a genuine finding (BLOCKING, LSA-06) and declares
    Decision 170 accounting on all three of its reachable exit paths."""

    def test_a_synthetic_uncovered_import_appends_to_failed(self, tmp_path: Path) -> None:
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        failed, declaration = _run_against(_make_repo(tmp_path), entries)
        assert failed != []
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "gated_pre_checks"

    def test_failure_detail_names_the_offending_entry(self, tmp_path: Path) -> None:
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        failed: list[str] = []
        with patch.object(_common, "ROOT", _make_repo(tmp_path)), patch.object(registry, "_ALL_ENTRIES", entries):
            with registry.outcome_scope("validate_pre_glob_closure"):
                vpgc.validate_pre_glob_closure(failed)
                detail = registry.pop_failure_detail()
        assert failed != []
        assert detail is not None and any("validate_thing" in d for d in detail)

    def test_examined_count_is_the_roster_size(self, tmp_path: Path) -> None:
        """A multi-entry roster: a constant would satisfy every single-entry fixture."""
        roster = {n: _entry(n, "scripts.checks.fake.validate_thing") for n in ("a_check", "b_check", "c_check")}
        failed, declaration = _run_against(_make_repo(tmp_path), roster)
        assert failed != []
        assert len(roster) == 3
        assert declaration.count == len(roster)

    def test_blocking_banner_and_summary_are_printed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        _run_against(_make_repo(tmp_path), entries)
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "validate_thing" in out
        assert "scripts/hublib.py" in out
        assert "ADVISORY" not in out

    def test_clean_roster_prints_a_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing", pre_globs=("scripts/**",))
        failed, declaration = _run_against(_make_repo(tmp_path), {entry.name: entry})
        assert failed == []
        assert declaration.count == 1
        assert "PASS" in capsys.readouterr().out

    def test_empty_roster_is_vacuous_not_skipped(self, tmp_path: Path) -> None:
        """check-accounting.yaml's discrimination rule: an empty DOMAIN declares examined(0)."""
        failed, declaration = _run_against(_make_repo(tmp_path), {})
        assert failed == []
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert declaration.unit == "gated_pre_checks"

    def test_an_internal_error_is_a_loud_skip_not_an_aborted_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Decision 55 loud-skip precedent (derive_affected_tests): a probe failure must not be
        able to abort --pre, and must not silently pass either. Nothing wraps a check body --
        validation_result.dispatch_recording calls fn(failed) bare -- so the guard has to live
        here."""
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        with patch.object(vpgc, "_closure_view", side_effect=RuntimeError("graph oracle exploded")):
            failed, declaration = _run_against(_make_repo(tmp_path), entries)
        out = capsys.readouterr().out
        assert failed == []
        assert declaration.kind == "skipped"
        assert declaration.reason is not None and "graph oracle exploded" in declaration.reason
        assert "SKIP" in out
        assert "graph oracle exploded" in out

    def test_pruned_edges_row_violation_flows_into_findings(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """The _PRUNED_EDGES row-addition marker gate (rec-3558) is wired into the SAME `failed`
        pool as an uncovered closure path -- both are BLOCKING findings of one check."""
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing", pre_globs=("scripts/**",))
        with patch.object(vpgc, "_pruned_edges_row_addition_violations", return_value=["fake violation"]):
            failed, _declaration = _run_against(_make_repo(tmp_path), {entry.name: entry})
        out = capsys.readouterr().out
        assert failed != []
        assert "_PRUNED_EDGES row-addition violations" in out
        assert "fake violation" in out

    def test_suppressed_count_is_printed_but_never_asserted_against_failed(self, tmp_path: Path) -> None:
        """The inert-module floor's suppressed count is informational: a trivial module in the
        closure is suppressed from `failed`'s reasoning without being asserted anywhere itself."""
        root = _make_repo(tmp_path)
        (root / "scripts" / "checks" / "fake" / "validate_thing.py").write_text(
            "import scripts.trivial_hub\n\n\ndef validate_thing(failed):\n    pass\n", encoding="utf-8"
        )
        (root / "scripts" / "trivial_hub.py").write_text('"""Just a docstring."""\n', encoding="utf-8")
        entry = _entry("validate_thing", "scripts.checks.fake.validate_thing", pre_globs=("scripts/checks/**",))
        failed, _declaration = _run_against(root, {entry.name: entry})
        assert failed == []


class TestNeverFailsTheBuildStringIsGone:
    def test_the_advisory_never_fails_string_is_absent_from_the_module_source(self) -> None:
        source = Path(vpgc.__file__).read_text(encoding="utf-8")
        assert "Never fails the build at this stage" not in source


class TestLiveTreeSmoke:
    """Post-flip: the real tree must be BLOCKING-CLEAN, not merely advisory-non-crashing -- this
    is the LSA-06 acceptance proper, tested directly rather than only via the VP shell command."""

    def test_runs_clean_on_the_real_tree(self) -> None:
        failed: list[str] = []
        with registry.outcome_scope("validate_pre_glob_closure"):
            vpgc.validate_pre_glob_closure(failed)
            declaration = registry.pop_declaration()
        assert failed == [], failed
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "gated_pre_checks"
        assert declaration.count is not None and declaration.count > 0

    def test_its_own_entry_is_one_of_the_audited_ones(self) -> None:
        assert "validate_pre_glob_closure" in {e.name for e in vpgc._gated_entries()}

    def test_its_own_pre_globs_cover_its_own_closure(self) -> None:
        """Dogfood: the auditor's own Entry must have nothing to report about itself."""
        root = _common.ROOT
        entry = next(e for e in vpgc._gated_entries() if e.name == "validate_pre_glob_closure")
        assert vpgc._unmatched_paths(entry, vpgc._closure_view(root), root) == []
