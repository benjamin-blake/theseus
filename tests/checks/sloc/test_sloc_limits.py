"""Tests for validate_sloc_limits() -- Decision 43 SLOC gate."""

import importlib.util
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks import registry
from scripts.checks.hygiene.validate_check_accounting import validate_check_accounting
from scripts.checks.sloc.sloc_limits import _load_sloc_budgets, _update_sloc_budgets, validate_sloc_limits


class TestValidateSlocLimits:
    """Tests for validate_sloc_limits() -- Decision 43 SLOC gate."""

    def test_catches_over_limit_file(self, tmp_path: Path) -> None:
        """Files exceeding 500 SLOC without waiver are flagged."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "big_module.py"
        big_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_waivered_file(self, tmp_path: Path) -> None:
        """Bare waiver alone is insufficient for >500 SLOC files; budget registration required (Decision 102)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        big_file = scripts_dir / "waivered.py"
        big_file.write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 501,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_allows_under_limit_file(self, tmp_path: Path) -> None:
        """Files under 500 SLOC pass without waiver."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        small_file = scripts_dir / "small.py"
        small_file.write_text("x = 1\n" * 100, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        """__init__.py files are excluded from SLOC checks."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        init_file = scripts_dir / "__init__.py"
        init_file.write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def _write_budget(self, tmp_path: Path, entries: dict[str, int]) -> None:
        """Write a sloc_budgets.yaml into tmp_path/config/."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["budgets:"]
        for k, v in entries.items():
            lines.append(f"  {k}: {v}")
        (config_dir / "sloc_budgets.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_registered_file_exceeds_budget_fails(self, tmp_path: Path) -> None:
        """A registered file whose current SLOC exceeds its budget fails the gate."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 601, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_registered_file_at_budget_passes(self, tmp_path: Path) -> None:
        """A registered file at exactly its budget does not fail."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 600, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_registered_file_below_budget_passes_advisory(self, tmp_path: Path) -> None:
        """A registered file below its budget passes (advisory only, no failure)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "heavy.py").write_text("x = 1\n" * 550, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/heavy.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_oversized_unregistered_with_waiver_fails(self, tmp_path: Path) -> None:
        """A file >500 SLOC with a waiver but no budget registration fails (Decision 102)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "old_waiver.py").write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 510,
            encoding="utf-8",
        )
        self._write_budget(tmp_path, {})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_stale_waiver_under_limit_is_advisory_not_failure(self, tmp_path: Path) -> None:
        """A file <=500 SLOC with a waiver is a stale-waiver advisory, not a failure."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "small_waiver.py").write_text(
            "# complexity-waiver: decision-43\n" + "x = 1\n" * 100,
            encoding="utf-8",
        )

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_update_sloc_budgets_downward_only(self, tmp_path: Path) -> None:
        """_update_sloc_budgets never raises an existing budget below current SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "growing.py").write_text("x = 1\n" * 600, encoding="utf-8")
        # Seed a budget BELOW current SLOC -- regen must not raise it
        self._write_budget(tmp_path, {"scripts/growing.py": 580})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert result["scripts/growing.py"] == 580

    def test_update_sloc_budgets_does_not_seed_new_oversized(self, tmp_path: Path) -> None:
        """_update_sloc_budgets does NOT auto-seed a newly-oversized, unregistered file (B2 /
        Decision 128) -- forces a deliberate raise-approved registration or a decompose instead
        of a frictionless one-command auto-seed. validate_sloc_limits then fails the file until
        it is registered."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "new_big.py").write_text("x = 1\n" * 620, encoding="utf-8")
        self._write_budget(tmp_path, {})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert "scripts/new_big.py" not in result
        assert len(failed) == 1

    def test_update_sloc_budgets_drops_shrunken_file(self, tmp_path: Path) -> None:
        """_update_sloc_budgets drops a file that shrank to <=500 SLOC."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "shrunken.py").write_text("x = 1\n" * 100, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/shrunken.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert "scripts/shrunken.py" not in result

    def test_update_sloc_budgets_idempotent(self, tmp_path: Path) -> None:
        """rec-2419: running --update-sloc-budgets twice leaves config/sloc_budgets.yaml
        byte-identical the second time (steady-state idempotency)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "steady.py").write_text("x = 1\n" * 550, encoding="utf-8")
        self._write_budget(tmp_path, {"scripts/steady.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            first_pass = (tmp_path / "config" / "sloc_budgets.yaml").read_text(encoding="utf-8")
            _update_sloc_budgets()
            second_pass = (tmp_path / "config" / "sloc_budgets.yaml").read_text(encoding="utf-8")

        assert first_pass == second_pass


class TestUpdateSlocBudgetsLoweringGap:
    """rec-2420: a file shrinks from an existing budget of 700 to 550 SLOC (still over 500) --
    the budget should lower from 700 to 550, not stay frozen at the old value. Relocated from
    the retired tests/test_checks_registry.py monolith (Decision 169), repointed onto
    scripts.checks.sloc.sloc_limits directly."""

    def test_update_sloc_budgets_lowers_shrunken_oversized(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (scripts_dir / "shrunk_but_still_big.py").write_text("x = 1\n" * 550, encoding="utf-8")
        (config_dir / "sloc_budgets.yaml").write_text("budgets:\n  scripts/shrunk_but_still_big.py: 700\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            _update_sloc_budgets()
            result = _load_sloc_budgets()

        assert result["scripts/shrunk_but_still_big.py"] == 550


class TestSlocRatchetAdvisoryEmission:
    """sloc_limits.py:111 -- the ratchet-down advisory never touches `failed`, so stdout is the
    only channel that can observe it. Owns its helpers rather than reusing another class's."""

    @staticmethod
    def _write_budget(tmp_path: Path, rel: str, budget: int) -> None:
        """Write a one-entry config/sloc_budgets.yaml under tmp_path."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "sloc_budgets.yaml").write_text(f"budgets:\n  {rel}: {budget}\n", encoding="utf-8")

    @staticmethod
    def _run(tmp_path: Path, sloc: int, budget: int) -> list[str]:
        """Register scripts/heavy.py at `budget` with exactly `sloc` SLOC and run the gate."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        (scripts_dir / "heavy.py").write_text("x = 1\n" * sloc, encoding="utf-8")
        TestSlocRatchetAdvisoryEmission._write_budget(tmp_path, "scripts/heavy.py", budget)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_sloc_limits(failed)
        return failed

    def test_registered_file_below_budget_emits_ratchet_advisory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Strictly below budget -> the non-blocking ratchet-down advisory is printed."""
        failed = self._run(tmp_path, sloc=550, budget=600)

        out = capsys.readouterr().out
        assert failed == []
        assert "SLOC advisories (non-blocking):" in out
        assert "scripts/heavy.py: 550 SLOC below budget 600" in out
        assert "validate --update-sloc-budgets" in out

    def test_registered_file_exactly_at_budget_emits_no_advisory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exactly at budget -> nothing is printed (the other side of the same comparison)."""
        failed = self._run(tmp_path, sloc=550, budget=550)

        out = capsys.readouterr().out
        assert failed == []
        assert "below budget" not in out
        assert "SLOC advisories (non-blocking):" not in out


class TestSlocLimitsAccountingDeclaration:
    """Decision 170 accounting declaration (docs/contracts/check-accounting.yaml): the gate ends
    with registry.examined(<gated files scanned>, unit="gated_python_files") on its single
    reachable exit, so a vacuous pass, an enforced pass and a failure are distinguishable in the
    run's check_outcomes rows. Owns its fixtures -- no import from any other test module
    (Decision 131)."""

    def test_pass_path_declares_examined_count_of_gated_files(self, tmp_path: Path) -> None:
        """Two gated modules plus an excluded __init__.py -> examined(2), unit
        "gated_python_files", with nothing appended to `failed`."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "one.py").write_text("x = 1\n" * 10, encoding="utf-8")
        (scripts_dir / "two.py").write_text("y = 2\n" * 20, encoding="utf-8")
        (scripts_dir / "__init__.py").write_text("z = 3\n", encoding="utf-8")

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_sloc_limits(failed)
        declaration = registry.pop_declaration()

        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "gated_python_files"
        assert declaration.count == 2
        assert registry.derive_status(declaration, bool(failed)) == "enforced"

    def test_failure_path_appends_and_still_declares_examined(self, tmp_path: Path) -> None:
        """A >500-SLOC unregistered module both appends to `failed` AND declares examined(1) --
        the declaration is not skipped when the check fails, so derive_status() sees "failed"
        over a PRESENT declaration rather than over a missing one."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "oversized.py").write_text("x = 1\n" * 501, encoding="utf-8")

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_sloc_limits(failed)
        declaration = registry.pop_declaration()

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "gated_python_files"
        assert declaration.count == 1
        assert registry.derive_status(declaration, bool(failed)) == "failed"

    def test_empty_tree_declares_examined_zero_as_vacuous(self, tmp_path: Path) -> None:
        """A tree with no gated Python file is an EMPTY DOMAIN, never a skip: examined(0), which
        derive_status() maps to "vacuous" (the contract's discrimination rule)."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "notes.md").write_text("no python here\n", encoding="utf-8")

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_sloc_limits(failed)
        declaration = registry.pop_declaration()

        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
        assert registry.derive_status(declaration, bool(failed)) == "vacuous"


class TestSlocLimitsOffAccountingRoster:
    """The touch-it-fix-it consequence, pinned hermetically: with validate_sloc_limits absent from
    config/check_accounting_baseline.yaml and its module in the changed-file set,
    validate_check_accounting reports NO violation naming it. Re-implements the hygiene mirror's
    fixture style by hand rather than importing it (Decision 131)."""

    _MODULE_REL_PATH = "scripts/checks/sloc/sloc_limits.py"

    _CONTRACT = """
contract:
  id: check-accounting
  class: D
  contract_version: 1
  status: ratified
  ratified_via: "Decision 170 / PLAN-validate-vacuous-pass-accounting"
  description: test fixture
  subject: check-accounting
  evaluator:
    check: validate_check_accounting
amendment_log: []
status_vocabulary:
  - failed
  - skipped
  - vacuous
  - enforced
  - undeclared
"""

    @classmethod
    def _build_tree(cls, tmp_path: Path):
        """Write the contract, a roster WITHOUT validate_sloc_limits, and a real copy of the
        module source at its true repo-relative path; return the loaded copy."""
        contract_path = tmp_path / "docs" / "contracts" / "check-accounting.yaml"
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(cls._CONTRACT, encoding="utf-8")

        roster_path = tmp_path / "config" / "check_accounting_baseline.yaml"
        roster_path.parent.mkdir(parents=True, exist_ok=True)
        roster_path.write_text("entries: []\n", encoding="utf-8")

        source_file = inspect.getsourcefile(validate_sloc_limits)
        assert source_file is not None
        copied = tmp_path / cls._MODULE_REL_PATH
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_text(Path(source_file).read_text(encoding="utf-8"), encoding="utf-8")

        spec = importlib.util.spec_from_file_location("sloc_limits_roster_fixture", copied)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_edited_module_declaring_reports_no_violation(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        module = self._build_tree(tmp_path)
        checks = {"validate_sloc_limits": registry.Check(name="validate_sloc_limits")}

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.object(registry, "all_checks", return_value=checks),
            patch.object(registry, "resolve", return_value=module.validate_sloc_limits),
            patch(
                "scripts.checks._marker_guard.default_base_reader",
                return_value="entries:\n  - validate_sloc_limits\n",
            ),
            patch("scripts.checks._common.get_changed_files", return_value=[self._MODULE_REL_PATH]),
        ):
            failed: list[str] = []
            validate_check_accounting(failed)

        out = capsys.readouterr().out
        assert failed == []
        assert [line.strip() for line in out.splitlines() if "validate_sloc_limits" in line] == []
