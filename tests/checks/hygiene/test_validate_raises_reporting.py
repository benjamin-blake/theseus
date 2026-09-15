"""Mirror test for scripts/checks/hygiene/validate_raises_discrimination.py -- reporting,
registration, and live-tree slice.

PR1 decomposition sibling of test_validate_raises_discrimination.py (Decision 128
decompose-by-default: that module sat at 499 SLOC against the 500 budget). Holds
TestReportOnly, TestRegistrationSurfaces and TestLiveTreeInvariants. _module_source and _write
are duplicated here rather than imported from the sibling module -- validate_no_cross_test_imports
forbids importing test-module privates across test_* modules (tests/CLAUDE.md).

Deliberately imports NO pytest name and makes no real pytest.raises call: this module is itself
under the census's scanned tree, so a live call here would move the very numbers the census
reports. Every raises shape below is fixture SOURCE TEXT written into a tmp_path tree instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import scripts.checks.hygiene.validate_raises_discrimination as guard
from scripts.checks import registry
from scripts.checks.hygiene._declaring_coverage import measure_check
from scripts.checks.hygiene._manifest import ENTRIES

_ROOT = Path(__file__).resolve().parents[3]
_CHECK = "validate_raises_discrimination"
_SHARD = "raises-discrimination-advisory-declares-examined"
_SHARD_PATH = _ROOT / "config/agent/verification_registry/entries" / f"{_SHARD}.yaml"
_TAXONOMY_PATH = _ROOT / "config/ci_rca_taxonomy.yaml"
_BASELINE_PATH = _ROOT / "config/check_accounting_baseline.yaml"
_MODULE_PATH = _ROOT / "scripts/checks/hygiene/validate_raises_discrimination.py"

_LIVE_SITES: list[guard.RaisesSite] | None = None


def _module_source(body: str) -> str:
    """A fixture test module whose single function body is `body` (already indented)."""
    return "import pytest\n\n\ndef test_case():\n" + body


def _write(tmp_path: Path, source: str, name: str = "test_fixture.py") -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    path = tests_dir / name
    path.write_text(source, encoding="utf-8")
    return path


def _live_sites() -> list[guard.RaisesSite]:
    """The live tests/ scan, computed once for this module's property assertions."""
    global _LIVE_SITES
    if _LIVE_SITES is None:
        _LIVE_SITES = guard.scan_tests(_ROOT)
    return _LIVE_SITES


class TestReportOnly:
    """The advisory guarantee and the declaration payload."""

    validate_raises_discrimination = staticmethod(guard.validate_raises_discrimination)

    def test_failed_is_never_appended_to_on_a_tree_with_hits(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"))
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            self.validate_raises_discrimination(failed)
        out = capsys.readouterr().out
        assert failed == []
        assert "tests/test_fixture.py:5 Exception" in out
        assert "raises-discrimination scanned=1 hits=1 directories=1 (advisory)" in out
        assert "ADVISORY" in out

    def test_declaration_payload_names_the_scanned_population(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"))
        failed: list[str] = []
        with registry.outcome_scope(_CHECK):
            with patch("scripts.checks._common.ROOT", tmp_path):
                self.validate_raises_discrimination(failed)
            declaration = registry.pop_declaration()
        capsys.readouterr()
        assert declaration is not None
        assert (declaration.kind, declaration.unit, declaration.count) == ("examined", "pytest_raises_sites", 1)

    def test_hit_list_is_grouped_by_directory_largest_first(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write(
            tmp_path,
            "import pytest\n\n\ndef test_x():\n"
            "    with pytest.raises(Exception):\n        pass\n"
            "    with pytest.raises(KeyError):\n        pass\n",
        )
        nested = tmp_path / "tests" / "nested"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "test_b.py").write_text(_module_source("    with pytest.raises(OSError):\n        pass\n"), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            self.validate_raises_discrimination(failed)
        lines = [line for line in capsys.readouterr().out.splitlines() if "non-discriminating site(s)" in line]
        assert lines == ["  tests: 2 non-discriminating site(s)", "  tests/nested: 1 non-discriminating site(s)"]

    def test_injected_population_bypasses_the_live_walk(self, capsys: pytest.CaptureFixture[str]) -> None:
        failed: list[str] = []
        self.validate_raises_discrimination(failed, sites=[])
        out = capsys.readouterr().out
        assert failed == []
        assert "raises-discrimination scanned=0 hits=0 directories=0 (advisory)" in out
        assert "unreadable or unparseable files skipped: 0" in out


class TestRegistrationSurfaces:
    """All seven registration surfaces, asserted together (Decision 169)."""

    def test_module_exists_and_resolves_through_the_registry(self) -> None:
        assert _MODULE_PATH.exists()
        assert registry.resolve(_CHECK) is guard.validate_raises_discrimination
        assert registry.all_checks()[_CHECK].owner == "platform"

    def test_manifest_entry_declares_both_tiers(self) -> None:
        entry = next(candidate for candidate in ENTRIES if candidate.name == _CHECK)
        assert entry.module == "scripts.checks.hygiene.validate_raises_discrimination"
        assert entry.attr == _CHECK
        assert entry.pre is True
        assert entry.pre_globs == (
            "tests/**",
            "scripts/checks/hygiene/**",
            "scripts/checks/_common.py",
            "scripts/checks/registry.py",
        )
        assert entry.full_segment == "full_after_lint"
        dispatched = [step.name for step in registry.pre_sequence() + registry.full_sequence()]
        assert dispatched.count(_CHECK) >= 2

    def test_taxonomy_row_exists(self) -> None:
        taxonomy = yaml.safe_load(_TAXONOMY_PATH.read_text(encoding="utf-8"))
        assert taxonomy["function_to_category"][_CHECK] == "code_regression"

    def test_absent_from_the_shrink_only_accounting_baseline(self) -> None:
        """A NEW check declares from day one and never joins the grandfather roster."""
        baseline = yaml.safe_load(_BASELINE_PATH.read_text(encoding="utf-8"))
        assert _CHECK not in baseline["entries"]

    def test_declares_examined_on_every_reachable_success_exit(self) -> None:
        row = measure_check(_CHECK, registry.resolve(_CHECK))
        assert row.undecidable_reason is None
        assert row.success_exits >= 1
        assert row.undeclared == 0

    def test_graduation_shard_expected_is_digit_classed_never_a_pinned_count(self) -> None:
        """The shard is a STANDING row and slice 2 shrinks the hit list by design, so its regex
        pins the summary GRAMMAR with digit classes -- a literal count would red the shard on the
        very change it exists to accompany (the declaring-coverage-fleet-report-line precedent)."""
        shard = yaml.safe_load(_SHARD_PATH.read_text(encoding="utf-8"))
        expected = shard["check_spec"]["expected"]
        assert expected == r"raises-discrimination scanned=\d+ hits=\d+ directories=\d+ \(advisory\)"
        assert not any(char.isdigit() for char in expected)

    def test_graduation_shard_pins_a_regex_the_check_actually_emits(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The shard's expected pattern is matched against EMITTED output, never re-derived on
        both sides of the assertion."""
        shard = yaml.safe_load(_SHARD_PATH.read_text(encoding="utf-8"))
        assert shard["check_id"] == _SHARD
        assert shard["guard_target"] == "scripts/checks/hygiene/validate_raises_discrimination.py"
        assert shard["guard_symbol"] == _CHECK
        assert shard["plan_slug"] == "raises-discrimination-guard-advisory"
        assert shard["primitive_slot"] == "command_output_matches"
        assert shard["check_spec"]["use_regex"] is True
        _write(tmp_path, _module_source("    with pytest.raises(Exception):\n        pass\n"))
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            guard.validate_raises_discrimination(failed)
        assert re.search(shard["check_spec"]["expected"], capsys.readouterr().out) is not None


class TestLiveTreeInvariants:
    """Growth-safe properties over the LIVE tests/ tree -- never an exact count, which would be
    the test-count-coupling anti-pattern and would red every later narrowing slice.

    validate_test_count_coupling does NOT bind this collection (none of this check's symbols is in
    its _CURATED_TOKENS roster), so keeping an exact count out of here is review discipline, not a
    mechanical guarantee -- stated so a later author does not assume the machine will catch it."""

    def test_scan_is_non_empty_and_hits_are_a_subset(self) -> None:
        scanned = _live_sites()
        reported = guard.hits(scanned)
        assert scanned
        assert {id(site) for site in reported} <= {id(site) for site in scanned}

    def test_every_reported_hit_satisfies_all_four_arms(self) -> None:
        offenders = [
            site
            for site in guard.hits(_live_sites())
            if not (site.broad and not site.has_match and not site.loads_excinfo and not site.waived)
        ]
        assert offenders == []

    def test_every_broad_non_hit_fails_at_least_one_other_arm(self) -> None:
        reported = {id(site) for site in guard.hits(_live_sites())}
        offenders = [
            site
            for site in _live_sites()
            if site.broad and id(site) not in reported and not (site.has_match or site.loads_excinfo or site.waived)
        ]
        assert offenders == []

    def test_every_scanned_path_is_a_python_file_under_tests(self) -> None:
        offenders = [site for site in _live_sites() if not site.path.startswith("tests/") or not site.path.endswith(".py")]
        assert offenders == []

    def test_live_tree_parses_with_no_skipped_files(self) -> None:
        """Every file under tests/ reads and parses today, so the census covers the whole tree --
        a growth-safe property, not a count."""
        skipped: list[str] = []
        guard.scan_tests(_ROOT, skipped)
        assert skipped == []

    def test_summary_line_agrees_with_the_measured_population(self) -> None:
        scanned = _live_sites()
        reported = guard.hits(scanned)
        expected = guard.SUMMARY_GRAMMAR.format(
            scanned=len(scanned), hits=len(reported), directories=len(guard.hits_by_directory(reported))
        )
        assert guard.summary_line(scanned) == expected
