"""Coverage-instrumentation + deferral-map tests for scripts/checks/_pytest_diff.py
(PLAN-premerge-diff-coverage-gate). Decision 128 sibling of tests/validate/test_pytest_diff.py --
that file's SLOC headroom is thin (35 lines against the 500 budget at this plan's landing), so
this NEW concern (coverage artifact + deferral-map state classification) lives in its own module
rather than pushing test_pytest_diff.py over budget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from coverage.config import read_coverage_config

from scripts.checks._pytest_diff import (
    COVERAGE_ARTIFACT_REL,
    COVERAGE_SCOPE_CONFIG_REL,
    NO_ARTIFACT_STATES,
    STATE_ALL_DEFERRED,
    STATE_EMPTY_AFFECTED_SET,
    STATE_OK,
    STATE_SCOPE_UNRESOLVED,
    STATE_TRACED_NO_ARTIFACT,
    STATE_TWO_INVOCATION_FAILURE,
    _derive_changed_sources,
    _prepare_diff_coverage,
    _write_deferral_map,
    changed_source_files,
    coverage_flags,
    render_coverage_scope_config,
    run_pytest_diff,
)

_PYPROJECT_COVERAGE = """
[tool.coverage.run]
source = ["src"]
omit = ["*/tests/*", "*/__pycache__/*"]

[tool.coverage.report]
fail_under = 37
show_missing = true
exclude_also = ["if __name__ == .__main__.:"]
"""


def _parse_rendered(text: str, tmp_path: Path):
    """Round-trip the generated config through coverage.py's own reader -- the only assertion that
    proves coverage will actually honour what this module writes."""
    path = tmp_path / "generated.coveragerc"
    path.write_text(text, encoding="utf-8")
    warnings: list[str] = []
    return read_coverage_config(config_file=str(path), warn=warnings.append), warnings


def _green(cmd: list[str], **kwargs: object) -> MagicMock:
    """A no-output success result -- the default for every subprocess a test does not care about
    (the git derivation probes, --collect-only, the pytest run itself)."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def _collect_error_block(path: str, missing_module: str) -> str:
    return (
        f"__________________ ERROR collecting {path} ___________________\n"
        f"E   ModuleNotFoundError: No module named '{missing_module}'\n"
    )


class TestDeferralMapStateClassification:
    """The three no-usable-artifact states, plus the ordinary OK state, are each classified via
    the deferral-map write -- not silently conflated (this plan's core acceptance surface)."""

    def test_empty_affected_set_writes_that_state(self) -> None:
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")),
        ):
            run_pytest_diff([], [])
        mock_write.assert_called_once_with(STATE_EMPTY_AFFECTED_SET, {})

    def test_all_files_deferred_writes_that_state(self) -> None:
        test_file = "tests/test_heavy.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "duckdb")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([test_file], [])
        mock_write.assert_called_once_with(STATE_ALL_DEFERRED, {test_file: "duckdb"})

    def test_clean_pass_writes_ok_state(self) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            run_pytest_diff(["tests/test_a.py"], [])
        mock_write.assert_called_once_with(STATE_OK, {})

    def test_genuine_single_invocation_failure_still_writes_ok_state(self) -> None:
        """A hard failure with NO heavy-dep signature is still exactly ONE invocation -- its
        coverage.json remains a usable snapshot of that one run. Only the pytest run fails here:
        the git derivation probes stay green, so the untraced run is a genuinely empty scope
        rather than the degraded derivation STATE_SCOPE_UNRESOLVED covers."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            is_pytest_run = "pytest" in cmd and "--collect-only" not in cmd
            result = MagicMock()
            result.returncode = 1 if is_pytest_run else 0
            result.stdout = "FAILED tests/test_a.py::test_x - AssertionError" if is_pytest_run else ""
            result.stderr = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            run_pytest_diff(["tests/test_a.py"], failed)
        mock_write.assert_called_once_with(STATE_OK, {})
        assert failed == ["Tests (pytest)"]

    def test_reactive_fallback_writes_two_invocation_failure_state(self) -> None:
        """Primary run fails on a heavy-dep signature and a second invocation runs on the
        survivor set -- the deferral map must classify this as TWO_INVOCATION_FAILURE, not OK,
        even though the second invocation itself passes."""
        runnable_file = "tests/test_lazy_heavy.py"
        seen_primary = False

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal seen_primary
            result = MagicMock()
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            elif "-v" in cmd and runnable_file in cmd and not seen_primary:
                # primary invocation (the FIRST verbose run naming the file; the reactive survivor
                # re-run is the second): fails with a lazily-imported heavy dep signature
                seen_primary = True
                result.returncode = 1
                result.stdout = (
                    f"FAILED {runnable_file}::test_x - ModuleNotFoundError\n"
                    "E   ModuleNotFoundError: No module named 'duckdb'\n"
                )
                result.stderr = ""
            else:
                # isolated per-file probe, or the reactive survivor re-run
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([runnable_file], failed)

        mock_write.assert_called_once_with(STATE_TWO_INVOCATION_FAILURE, {})
        assert failed == []


class TestTracedRunWithoutAnArtifact:
    """Include-scoping makes a further "no usable coverage artifact" shape reachable that blanket
    --cov=src --cov=scripts could not produce: pytest-cov writes NO json at all when the selected
    tests execute none of the included files ("Failed to generate report: No data to report.",
    exit 0). Recorded as STATE_OK it would reach validate_diff_coverage as an empty file map and
    print a vacuous COVERED=0 UNCOVERED=0 green over lines this run never measured."""

    def _run_traced(self, tmp_path: Path, mock_run) -> MagicMock:
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "scripts/a.py")]),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
        ):
            run_pytest_diff(["tests/test_a.py"], [])
        return mock_write

    def test_traced_run_that_wrote_no_artifact_records_a_declared_skip_state(self, tmp_path) -> None:
        mock_write = self._run_traced(tmp_path, _green)
        mock_write.assert_called_once_with(STATE_TRACED_NO_ARTIFACT, {})
        assert STATE_TRACED_NO_ARTIFACT in NO_ARTIFACT_STATES

    def test_traced_run_that_wrote_an_artifact_records_ok(self, tmp_path) -> None:
        """The discriminator: same traced scope, same green run -- the ONLY difference is that
        this invocation actually produced a coverage artifact."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if "--cov" in cmd:
                artifact = tmp_path / COVERAGE_ARTIFACT_REL
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text('{"files": {}}', encoding="utf-8")
            return _green(cmd)

        self._run_traced(tmp_path, mock_run).assert_called_once_with(STATE_OK, {})

    def test_untraced_run_over_an_empty_domain_stays_ok(self, tmp_path) -> None:
        """An absent artifact after an UNTRACED run whose derivation resolved an empty domain is
        not a missing measurement -- there was nothing to classify either way."""
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=_green),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._pytest_diff._derive_changed_sources", return_value=([], True)),
        ):
            run_pytest_diff(["tests/test_a.py"], [])
        mock_write.assert_called_once_with(STATE_OK, {})


class TestWriteDeferralMapLoudSkip:
    def test_oserror_on_write_prints_loud_skip_never_raises(self, tmp_path, capsys) -> None:
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            _write_deferral_map(STATE_OK, {}, root=tmp_path)
        out = capsys.readouterr().out
        assert "loud skip" in out
        assert "disk full" in out


class TestChangedSourceFileDerivation:
    """The traced set is the diff's own src/scripts .py files -- a superset of the domain
    validate_diff_coverage classifies, never the whole src/ + scripts/ trees."""

    def test_only_added_or_modified_src_and_scripts_python_files_are_traced(self) -> None:
        entries = [
            ("M", "scripts/checks/_pytest_diff.py"),
            ("A", "src/common/config.py"),
            ("??", "scripts/new_tool.py"),
            ("D", "scripts/deleted.py"),
            ("M", "tests/validate/test_pytest_diff.py"),
            ("M", "docs/DECISIONS.md"),
            ("M", "scripts/checks/registry.pyi"),
        ]
        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=entries),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
        ):
            assert changed_source_files() == [
                "scripts/checks/_pytest_diff.py",
                "scripts/new_tool.py",
                "src/common/config.py",
            ]

    def test_a_diff_with_no_source_python_files_derives_an_empty_scope(self) -> None:
        entries = [("M", "docs/ROADMAP-PLATFORM.yaml"), ("M", "tests/validate/test_tiers.py")]
        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=entries),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
        ):
            assert changed_source_files() == []


class TestTracedScopeUnionsBothDiffDerivations:
    """The traced scope was derived from the MERGE-BASE diff while validate_diff_coverage
    classifies against the TIP diff -- on a branch behind main the two disagree, and a file the
    classifier sees but the tracer misses gets no coverage entry, silently dropping its added
    lines from the report. The scope is the strictly-additive UNION of both derivations."""

    def test_a_file_only_the_tip_derivation_sees_is_still_traced(self) -> None:
        tip_diff = "M\tsrc/only_in_tip.py\nD\tsrc/deleted.py\nM\tsrc/schema.yaml\n"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = _green(cmd)
            result.stdout = tip_diff if "diff" in cmd else ""
            return result

        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "scripts/in_merge_base.py")]),
            patch("scripts.checks._common.push_context_base", return_value=None),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            assert changed_source_files() == ["scripts/in_merge_base.py", "src/only_in_tip.py"]

    def test_tip_probe_uses_the_same_base_validate_diff_coverage_classifies_against(self) -> None:
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(cmd))
            return _green(cmd)

        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=[]),
            patch("scripts.checks._common.push_context_base", return_value="abc1234"),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            changed_source_files()
        assert ["git", "diff", "--name-status", "--no-renames", "abc1234", "--", "src", "scripts"] in captured

    def test_a_failed_tip_probe_reports_the_derivation_as_degraded(self) -> None:
        """A failed git probe returns no path -- indistinguishable from an empty diff unless the
        derivation reports its own health, which is what the second element carries."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 128
            result.stdout = ""
            result.stderr = "fatal: bad revision 'origin/main'"
            return result

        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=[]),
            patch("scripts.checks._common.push_context_base", return_value=None),
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            assert _derive_changed_sources(None) == ([], False)


class TestCoverageScopeConfigContent:
    """The generated config is the whole mechanism: coverage.py only narrows tracing when it is
    told which files to include, and only collapses the residual per-event cost when it is told to
    use the sys.monitoring core."""

    def test_include_names_exactly_the_changed_sources_as_absolute_paths(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text(_PYPROJECT_COVERAGE, encoding="utf-8")
        rendered = render_coverage_scope_config(["scripts/a.py", "src/pkg/b.py"], root=tmp_path)
        config, warnings = _parse_rendered(rendered, tmp_path)
        assert config.run_include == [str(tmp_path / "scripts/a.py"), str(tmp_path / "src/pkg/b.py")]
        assert warnings == []

    def test_source_key_is_dropped_so_include_is_not_ignored(self, tmp_path) -> None:
        """coverage.py ignores `include` whenever `source` is set -- carrying pyproject's
        source=["src"] through would silently restore whole-tree tracing."""
        (tmp_path / "pyproject.toml").write_text(_PYPROJECT_COVERAGE, encoding="utf-8")
        rendered = render_coverage_scope_config(["scripts/a.py"], root=tmp_path)
        config, _ = _parse_rendered(rendered, tmp_path)
        assert config.source is None
        assert "source =" not in rendered

    def test_sysmon_core_is_selected(self, tmp_path) -> None:
        (tmp_path / "pyproject.toml").write_text(_PYPROJECT_COVERAGE, encoding="utf-8")
        config, _ = _parse_rendered(render_coverage_scope_config(["scripts/a.py"], root=tmp_path), tmp_path)
        assert config.core == "sysmon"

    def test_pyproject_run_and_report_options_are_carried_over(self, tmp_path) -> None:
        """A generated config REPLACES pyproject's [tool.coverage.*] for the traced invocation, so
        anything that shapes executed/missing/excluded line sets must be copied forward or the
        report contract silently changes."""
        (tmp_path / "pyproject.toml").write_text(_PYPROJECT_COVERAGE, encoding="utf-8")
        config, _ = _parse_rendered(render_coverage_scope_config(["scripts/a.py"], root=tmp_path), tmp_path)
        assert config.run_omit == ["*/tests/*", "*/__pycache__/*"]
        assert config.exclude_also == ["if __name__ == .__main__.:"]
        assert config.fail_under == 37
        assert config.show_missing is True

    def test_absent_pyproject_still_renders_a_usable_scope_config(self, tmp_path) -> None:
        config, warnings = _parse_rendered(render_coverage_scope_config(["scripts/a.py"], root=tmp_path), tmp_path)
        assert config.run_include == [str(tmp_path / "scripts/a.py")]
        assert config.core == "sysmon"
        assert warnings == []


class TestCoverageFlagConstruction:
    def test_flags_point_at_the_generated_config_never_at_whole_source_trees(self, tmp_path) -> None:
        flags = coverage_flags(tmp_path / COVERAGE_SCOPE_CONFIG_REL)
        assert flags == [
            "--cov",
            f"--cov-config={tmp_path / COVERAGE_SCOPE_CONFIG_REL}",
            "--cov-fail-under=0",
            f"--cov-report=json:{COVERAGE_ARTIFACT_REL}",
        ]
        assert "--cov=src" not in flags
        assert "--cov=scripts" not in flags

    def test_changed_sources_write_the_config_and_return_scoped_flags(self, tmp_path) -> None:
        entries = [("M", "scripts/a.py"), ("M", "docs/DECISIONS.md")]
        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=entries),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
        ):
            flags, state = _prepare_diff_coverage(root=tmp_path)
        config_path = tmp_path / COVERAGE_SCOPE_CONFIG_REL
        assert config_path.exists()
        assert flags == coverage_flags(config_path)
        assert state is None

    def test_zero_changed_source_files_produces_no_coverage_flags(self, tmp_path) -> None:
        """A docs/roadmap-only diff has no added source line to classify, so the primary run pays
        no instrumentation at all -- and, the derivation itself being healthy, no forced skip
        state: an absent artifact here really does mean an empty classified domain."""
        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "docs/DECISIONS.md")]),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
        ):
            flags, state = _prepare_diff_coverage(root=tmp_path)
        assert flags == []
        assert state is None
        assert not (tmp_path / COVERAGE_SCOPE_CONFIG_REL).exists()

    def test_stale_coverage_artifact_is_discarded_before_every_primary_run(self, tmp_path) -> None:
        """An untraced (or zero-data) run must never leave a PREVIOUS run's coverage.json on disk
        for validate_diff_coverage to read as this run's measurement."""
        artifact = tmp_path / COVERAGE_ARTIFACT_REL
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('{"files": {"scripts/a.py": {}}}', encoding="utf-8")
        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "docs/DECISIONS.md")]),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
        ):
            _prepare_diff_coverage(root=tmp_path)
        assert not artifact.exists()

    def test_stale_artifact_unlink_failure_is_a_loud_skip_not_a_raise(self, tmp_path, capsys) -> None:
        """The discard is best-effort: an OSError (read-only logs/, a held file handle) LOUDLY
        skips and the run continues -- it must never raise out of the --pre step (Decision 55)."""
        with (
            patch("pathlib.Path.unlink", side_effect=OSError("permission denied")),
            patch("scripts.checks._pytest_diff._derive_changed_sources", return_value=(["scripts/a.py"], True)),
        ):
            flags, state = _prepare_diff_coverage(root=tmp_path)
        out = capsys.readouterr().out
        assert "loud skip" in out
        assert "permission denied" in out
        assert state is None
        assert flags == coverage_flags(tmp_path / COVERAGE_SCOPE_CONFIG_REL)

    def test_scope_config_write_failure_is_a_loud_skip_not_a_raise(self, tmp_path, capsys) -> None:
        """Tracing was wanted and the domain is non-empty, so the untraced run that follows is NOT
        evidence of nothing to classify -- it forces the declared-skip state."""
        with (
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "scripts/a.py")]),
            patch("scripts.checks._pytest_diff._tip_diff_source_files", return_value=(set(), True)),
            patch("pathlib.Path.write_text", side_effect=OSError("disk full")),
        ):
            flags, state = _prepare_diff_coverage(root=tmp_path)
        assert flags == []
        assert state == STATE_SCOPE_UNRESOLVED
        out = capsys.readouterr().out
        assert "loud skip" in out
        assert "disk full" in out

    def test_degraded_derivation_forces_the_declared_skip_state(self, tmp_path, capsys) -> None:
        """A degraded derivation yields no path, exactly like an empty diff -- but the run is then
        untraced over an UNKNOWN domain, so it must not print the empty-diff reason nor let the
        absent artifact read as a measurement (tracing still does not fail closed into blanket
        --cov: the invocation runs, just untraced)."""
        with patch("scripts.checks._pytest_diff._derive_changed_sources", return_value=([], False)):
            flags, state = _prepare_diff_coverage(root=tmp_path)
        assert flags == []
        assert state == STATE_SCOPE_UNRESOLVED
        assert state in NO_ARTIFACT_STATES
        out = capsys.readouterr().out
        assert "degraded" in out
        assert "no changed src/scripts .py file" not in out


class TestPrimaryInvocationCarriesCoverageFlags:
    def test_primary_invocation_has_explicit_cov_fail_under_zero(self, tmp_path) -> None:
        """Live-measured (VP step 2): a scoped run measures well under pyproject.toml's
        fail_under=37 -- --cov-fail-under=0 at the invocation site must override it, never a
        [tool.coverage.report] re-baseline."""
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "scripts/a.py")]),
            patch("scripts.checks._pytest_diff._write_deferral_map"),
        ):
            run_pytest_diff(["tests/test_a.py"], [])

        real_run = next(c for c in captured if "pytest" in c and "--collect-only" not in c)
        assert "--cov" in real_run
        assert f"--cov-config={tmp_path / COVERAGE_SCOPE_CONFIG_REL}" in real_run
        assert "--cov-fail-under=0" in real_run
        assert f"--cov-report=json:{COVERAGE_ARTIFACT_REL}" in real_run
        assert "--cov=src" not in real_run and "--cov=scripts" not in real_run

    def test_untraceable_diff_leaves_the_primary_invocation_untraced(self, tmp_path) -> None:
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "docs/DECISIONS.md")]),
            patch("scripts.checks._pytest_diff._write_deferral_map"),
        ):
            run_pytest_diff(["tests/test_a.py"], [])

        real_run = next(c for c in captured if "pytest" in c and "--collect-only" not in c)
        assert not any(flag.startswith("--cov") for flag in real_run)

    def test_reactive_survivor_rerun_carries_no_cov_flags(self, tmp_path) -> None:
        """The declared green-path lever: only the primary invocation is traced, never the
        reactive survivor re-run."""
        runnable_file = "tests/test_lazy_heavy.py"
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(cmd))
            result = MagicMock()
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            elif "--cov" in cmd:
                result.returncode = 1
                result.stdout = f"FAILED {runnable_file}::test_x\nE   ModuleNotFoundError: No module named 'duckdb'\n"
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_status_aware_diff", return_value=[("M", "scripts/a.py")]),
            patch("scripts.checks._pytest_diff._write_deferral_map"),
            patch("scripts.checks._pytest_diff._excluded_heavy_import_names", return_value={"pyarrow"}),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([runnable_file], [])

        traced = [c for c in captured if "pytest" in c and "--collect-only" not in c and "--cov" in c]
        # "-v" distinguishes the real reactive re-run from the isolated per-file probe (a separate
        # "-q" single-file subprocess that also names runnable_file but is not the re-run itself).
        untraced_reruns = [
            c
            for c in captured
            if "pytest" in c and "--collect-only" not in c and "--cov" not in c and "-v" in c and runnable_file in c
        ]
        assert len(traced) == 1
        assert len(untraced_reruns) == 1
        assert not any(flag.startswith("--cov") for flag in untraced_reruns[0])
