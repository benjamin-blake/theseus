"""main() --pre tier dispatch/diff-aware-selection tests -- orchestrator residue (rec-2709 Wave 1)."""

import itertools
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import registry
from scripts.checks.contracts._shared import _load_prompt_compliance
from scripts.checks.deps import affected_tests as at
from scripts.checks.misc.validate_test_coverage import _load_coverage_checker
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

# get_changed_files/ROOT/_pre_glob_match/_should_run_in_pre are still reachable on the "validate"
# module object -- the two former are retained _common re-exports (scripts/validate.py:42), the
# two latter are module-local functions never extracted (Decision 169 only deleted the check
# facade, lines 63-261).
get_changed_files = _validate.get_changed_files
ROOT = _validate.ROOT
_pre_glob_match = _validate._pre_glob_match
_should_run_in_pre = _validate._should_run_in_pre


def test_full_success_evidence_write_error_preserves_exit_zero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["validate"])
    monkeypatch.setenv("_VALIDATE_DEPTH", "0")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with (
        patch("scripts.checks._common.run", return_value=MagicMock(stdout="work\n", returncode=0)),
        patch("validate.run_python_checks"),
        patch("validate.validation_result.clear"),
        patch("validate.validation_result.write_completed", side_effect=OSError("disk full")),
        pytest.raises(SystemExit) as exc,
    ):
        _validate.main()
    assert exc.value.code == 0
    assert "WARNING: validation evidence could not be written: OSError" in capsys.readouterr().out


class TestLoadHelpers:
    """Tests for _load_coverage_checker and _load_prompt_compliance."""

    def test_load_coverage_checker_returns_module_when_exists(self) -> None:
        """Returns a module object when test_coverage_checker.py exists."""
        checker = _load_coverage_checker()
        assert checker is not None
        assert hasattr(checker, "extract_definitions")
        assert hasattr(checker, "get_changed_source_files")

    def test_load_coverage_checker_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Returns None when the script does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            result = _load_coverage_checker()
        assert result is None

    def test_load_prompt_compliance_returns_module_when_exists(self) -> None:
        """Returns a module object when prompt_compliance.py exists."""
        compliance = _load_prompt_compliance()
        assert compliance is not None
        assert hasattr(compliance, "parse_invariants")
        assert hasattr(compliance, "check_retro_lite_compliance")

    def test_load_prompt_compliance_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Returns None when the script does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            result = _load_prompt_compliance()
        assert result is None


class TestPreModeDiffAware:
    """Tests that --pre passes changed files to ruff/mypy/pytest."""

    def test_lints_whole_tree_regardless_of_changed_py_files(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """Retargeted (rec-3861/rec-3863): a changed-py-files diff used to narrow the ruff argv
        to those exact files; run_lint_checks now ignores `files` for target selection, so the
        argv is always whole-tree regardless of what changed."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        changed = ["scripts/validate.py", "tests/test_validate.py"]

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=changed),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_check = [c for c in captured_cmds if "ruff" in c and "check" in c and "format" not in c]
        assert ruff_check, "No ruff check command issued"
        assert "src/" in ruff_check[0]
        assert "tests/" in ruff_check[0]
        assert "scripts/" in ruff_check[0]

    def test_lints_whole_tree_even_when_no_files_changed(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """Retargeted (rec-3861/rec-3863): a no-diff --pre run used to skip lint entirely (the
        exact escape that let commit 1c50e26b's zero-.py ruff-version bump reach main unlinted).
        It now still lints the whole tree, at ~0.1s (Decision affected-set-selection precedent:
        dec-166 already sanctions whole-tree lint at this cost in both tiers)."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_check = [c for c in captured_cmds if "ruff" in c and "check" in c and "format" not in c]
        assert ruff_check, "Expected a whole-tree ruff invocation even with no changed files"
        assert "src/" in ruff_check[0]
        assert "tests/" in ruff_check[0]
        assert "scripts/" in ruff_check[0]

    def test_pin_only_diff_drives_whole_tree_lint(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """DRIVER ALTITUDE (VP step 3): replay commit 1c50e26b's actual five-file pin-only diff
        (dependabot's ruff 0.15.20 -> 0.16.7 bump; zero .py files) through the real --pre
        _validate.main() driver -- not just run_lint_checks() at the unit level -- and assert the
        emitted ruff argv is whole-tree. The --pre lint call site is a closure INSIDE main()
        (scripts/validate.py's `_scaffold_lint`), so a unit-level-only assertion on
        run_lint_checks would not catch a call-site re-scoping there; this is the regression
        shape rec-3863's gap_explanation names."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        pin_only_changed = [
            "requirements.in",
            "requirements.txt",
            "requirements-dev.in",
            "requirements-dev.txt",
            "requirements-fast.txt",
        ]

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=pin_only_changed),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        ruff_check = [c for c in captured_cmds if "ruff" in c and "check" in c and "format" not in c]
        assert ruff_check, "No ruff check command issued for a pin-only diff"
        assert "src/" in ruff_check[0]
        assert "tests/" in ruff_check[0]
        assert "scripts/" in ruff_check[0]

    def test_source_only_change_now_selects_reverse_dep_tests_via_affected_set(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        """Superseded by Decision affected-set-selection: a source-only diff (no test file
        literally changed) used to skip pytest entirely under the old edited-set selection.
        The live affected-set derivation now walks scripts/validate.py's REAL reverse-dependency
        test modules (e.g. tests/checks/roadmap/test_validate_tier_floor.py statically imports
        it) via the import-closure channel, so pytest DOES run -- this is the plan's headline
        acceptance criterion (a source-only PR is caught pre-merge), not a regression."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "--collect-only" not in c and "pytest" in c]
        assert pytest_cmds, "expected the import-closure channel to select scripts.validate's real reverse-dep tests"
        assert "scripts/validate.py" not in pytest_cmds[0], "a changed SOURCE file must never itself be a pytest target"

    def test_invokes_pytest_with_explicit_files_when_test_files_changed(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py", "tests/test_validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert pytest_cmds, "pytest not invoked"
        assert "tests/test_validate.py" in pytest_cmds[0], "explicit test file path not in pytest argv"
        assert "--picked" not in pytest_cmds[0], "--picked must not appear in pytest argv"
        assert "not integration" in pytest_cmds[0]

    def test_treats_pytest_exit_5_as_failure(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = "agent/test-branch\n"
            result.stderr = ""
            result.returncode = 5 if "pytest" in cmd else 0
            return result

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_validate.py"]),
            patch("scripts.checks._common.run", side_effect=exit5_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code != 0


class TestPreModePytestSelection:
    """Regression tests locking the explicit-file pytest selection contract.

    Acceptance criteria from PLAN-ci-pre-gate-pytest-picked-noop:
    (a) changed test file -> pytest invoked with that explicit path, no --picked
    (b) exit 5 / 0-collected with changed test files -> failure (gate reddens)
    (c) no test files changed -> pytest not invoked at all
    """

    def test_explicit_path_in_argv_no_picked(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_x.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "pytest" in c]
        assert pytest_cmds, "pytest was not invoked despite changed test file"
        assert "tests/test_x.py" in pytest_cmds[0], "explicit file path missing from pytest argv"
        assert "--picked" not in pytest_cmds[0], "--picked must not appear (explicit-file transport)"

    def test_exit_5_with_changed_tests_reddens_gate(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        def exit5_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 5 if "pytest" in cmd else 0
            return result

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=["tests/test_x.py"]),
            patch("scripts.checks._common.run", side_effect=exit5_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code != 0, "exit 5 / 0-collected with changed test files must redden the gate"

    def test_source_only_changes_now_select_reverse_dep_tests_via_affected_set(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        """Superseded by Decision affected-set-selection (see the sibling test in
        TestPreModeDiffAware): two source-only changes with real reverse-dep test modules
        (scripts.validate, scripts.sync.ops both have several) now select those tests via the
        import-closure channel instead of running no tests at all."""
        monkeypatch.setattr(sys, "argv", ["validate.py", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        captured_cmds: list[list[str]] = []

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py", "scripts/sync/ops.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        pytest_cmds = [c for c in captured_cmds if "--collect-only" not in c and "pytest" in c]
        assert pytest_cmds, "expected the import-closure channel to select real reverse-dep tests"


class TestSlocLimitsInPreMode:
    """Assert validate_sloc_limits runs in the --pre tier (rec-2106 RCA fix)."""

    def test_sloc_limits_called_in_pre_mode(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """validate_sloc_limits must be invoked during --pre alongside validate_cc_limits."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        sloc_called = []

        def capture_sloc(failed: list[str]) -> None:
            sloc_called.append(True)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=("validate_sloc_limits",))),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("scripts.checks.sloc.sloc_limits.validate_sloc_limits", side_effect=capture_sloc),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        assert sloc_called, "validate_sloc_limits was NOT called in --pre mode"

    def test_sloc_limits_called_after_cc_limits_in_pre(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """validate_sloc_limits is called in the same --pre block as validate_cc_limits."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        call_order: list[str] = []

        def capture_cc(failed: list[str]) -> None:
            call_order.append("cc")

        def capture_sloc(failed: list[str]) -> None:
            call_order.append("sloc")

        with (
            patch.object(
                registry,
                "pre_sequence",
                return_value=pre_sequence_stub(checks=("validate_cc_limits", "validate_sloc_limits")),
            ),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("scripts.checks.sloc.cc_limits.validate_cc_limits", side_effect=capture_cc),
            patch("scripts.checks.sloc.sloc_limits.validate_sloc_limits", side_effect=capture_sloc),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        assert "cc" in call_order, "validate_cc_limits not called in --pre mode"
        assert "sloc" in call_order, "validate_sloc_limits not called in --pre mode"
        cc_idx = call_order.index("cc")
        sloc_idx = call_order.index("sloc")
        assert cc_idx < sloc_idx, "validate_sloc_limits must be called after validate_cc_limits"


class TestPreModeChecks:
    """Assert validate_subprocess_encoding runs in the --pre tier (rec-2382 RCA fix)."""

    def test_pre_mode_calls_subprocess_encoding(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """validate_subprocess_encoding must be invoked during --pre (tier-membership regression guard)."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        encoding_called = []

        def capture_encoding(failed: list[str]) -> None:
            encoding_called.append(True)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=("validate_subprocess_encoding",))),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch(
                "scripts.checks.hygiene.validate_subprocess_encoding.validate_subprocess_encoding",
                side_effect=capture_encoding,
            ),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        assert encoding_called, "validate_subprocess_encoding was NOT called in --pre mode"


class TestPreModeRegistryIsolation:
    """Isolation-guard test (defect 2 lock-in): proves the real check registry is not
    executed inside a neutralized --pre main() call, so a future edit that silently
    reintroduces full-registry execution (and its wall-clock cost) is caught here instead
    of resurfacing as a slow/flaky fast-tier gate."""

    def test_real_registry_check_not_invoked_under_neutralization(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        """validate_import_contracts prints a distinctive banner when it actually runs
        (see scripts/checks/deps/validate_import_contracts.py). SELECTING it (rather than
        relying on scaffold-only exclusion) and then patching it here is what makes this a real
        interception guard: excluding it from the selection would make the banner assertion
        true regardless of whether interception works, silently orphaning the graduated row
        pre-tier-registry-isolation-guard.
        """
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=("validate_import_contracts",))),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch("scripts.checks.deps.validate_import_contracts.validate_import_contracts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Import contracts (Decision 80" not in captured.out, (
            "validate_import_contracts printed its real banner -- the real check ran "
            "instead of being intercepted by the test's own explicit patch"
        )


class TestRoadmapGuardSubsumption:
    """Subsumption proof (Decision affected-set-selection, VP step 9): the retired
    select_roadmap_guard_tests special case (ci-rca-cd25-ratification-tier-gap) is subsumed by
    the general data-edge channel in scripts/checks/deps/affected_tests.py -- a roadmap-YAML
    change still selects the tests that reference its basename, via the GENERAL channel, not a
    roadmap-specific special case."""

    def _make_tests_dir(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_roadmap_guard.py").write_text(
            'ROADMAP = "ROADMAP-PLATFORM.yaml"\n\ndef test_x():\n    assert ROADMAP\n', encoding="utf-8"
        )
        (tests_dir / "test_unrelated.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

    def test_roadmap_yaml_change_selects_guard_test_via_general_channel(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = at.derive_affected_tests([("M", "docs/ROADMAP-PLATFORM.yaml")], repo_root=tmp_path)
        assert "tests/test_roadmap_guard.py" in result["selected"]
        assert result["manifest"]["provenance"]["tests/test_roadmap_guard.py"] == "data_edge"

    def test_unrelated_diff_does_not_force_select_guard_test(self, tmp_path: Path) -> None:
        self._make_tests_dir(tmp_path)
        result = at.derive_affected_tests([("M", "scripts/unrelated_thing.py")], repo_root=tmp_path)
        assert "tests/test_roadmap_guard.py" not in result["selected"]

    def test_semanto_roadmap_yaml_also_selects_via_general_channel(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_semanto_guard.py").write_text(
            'ROADMAP = "ROADMAP-SEMANTO.yaml"\n\ndef test_x():\n    assert ROADMAP\n', encoding="utf-8"
        )
        result = at.derive_affected_tests([("M", "docs/ROADMAP-SEMANTO.yaml")], repo_root=tmp_path)
        assert "tests/test_semanto_guard.py" in result["selected"]

    def test_special_case_function_no_longer_exists(self) -> None:
        assert not hasattr(_validate, "select_roadmap_guard_tests")
