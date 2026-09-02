"""Tests for scripts/import_governance.py -- 100% coverage including anti-vacuous-pass cases."""

from __future__ import annotations

import re
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.import_governance import (
    _fast_tier_budget_breach_open,
    _kg13_tier_item_filed,
    _normalize_pkg,
    _read_executor_concurrency,
    check_lockfile_sync,
    evaluate_bazel_revisit_trigger,
    main,
    run_import_contracts,
)

ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# run_import_contracts
# ---------------------------------------------------------------------------


class TestRunImportContracts:
    def test_passes_on_clean_tree(self) -> None:
        """Contracts pass green on the unmodified repository tree."""
        passed, output = run_import_contracts()
        assert passed, f"Expected contracts to pass, got:\n{output}"
        assert "kept" in output.lower() or "KEPT" in output

    def test_negative_illegal_import_detected(self, tmp_path: Path) -> None:
        """Anti-vacuous-pass: an injected illegal import is detected by lint-imports."""
        # Create a minimal importlinter config with a forbidden contract
        importlinter_cfg = tmp_path / ".importlinter"
        importlinter_cfg.write_text(
            "[importlinter]\n"
            "root_packages =\n"
            "    mypkg\n\n"
            "[importlinter:contract:test-forbidden]\n"
            "name = src.a must not import src.b\n"
            "type = forbidden\n"
            "source_modules =\n"
            "    mypkg.a\n"
            "forbidden_modules =\n"
            "    mypkg.b\n",
            encoding="utf-8",
        )
        # Create a minimal two-module package that violates the contract
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "b.py").write_text("X = 1\n", encoding="utf-8")
        (pkg / "a.py").write_text("from mypkg import b  # forbidden import\n", encoding="utf-8")

        lint_imports_bin = Path(sys.executable).parent / "lint-imports"
        cmd: list[str] = [str(lint_imports_bin)] if lint_imports_bin.exists() else ["lint-imports"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=tmp_path,
        )
        assert result.returncode != 0, "Expected lint-imports to report a violation for the injected forbidden import"
        combined = result.stdout + result.stderr
        assert "broken" in combined.lower() or "BROKEN" in combined

    def test_contracts_invoke_lint_imports(self) -> None:
        """run_import_contracts shells out to lint-imports; verify the returned output is non-empty."""
        passed, output = run_import_contracts()
        assert len(output) > 0, "Expected non-empty output from lint-imports"

    def test_lint_imports_not_found_returns_false(self) -> None:
        """run_import_contracts returns (False, message) when lint-imports binary is missing."""
        with patch("scripts.import_governance.subprocess.run", side_effect=FileNotFoundError("lint-imports: not found")):
            passed, output = run_import_contracts()
        assert not passed
        assert "lint-imports not found" in output


# ---------------------------------------------------------------------------
# check_lockfile_sync
# ---------------------------------------------------------------------------


class TestCheckLockfileSync:
    @pytest.fixture(autouse=True)
    def _isolate_dev_requirements(self, tmp_path: Path) -> Iterator[None]:
        with patch("scripts.import_governance._REQUIREMENTS_DEV", tmp_path / "requirements-dev.txt"):
            yield

    def test_passes_on_committed_lockfile(self) -> None:
        """check_lockfile_sync passes when requirements.lock is in sync with requirements.txt."""
        in_sync, message = check_lockfile_sync()
        assert in_sync, f"Expected lockfile to be in sync, got: {message}"
        assert "pins all" in message

    def test_committed_lockfile_covers_runtime_and_dev_requirements(self) -> None:
        with patch("scripts.import_governance._REQUIREMENTS_DEV", ROOT / "requirements-dev.txt"):
            in_sync, message = check_lockfile_sync()
        assert in_sync, message
        assert "across 2 files" in message

    def test_missing_dev_pin_fails(self, tmp_path: Path) -> None:
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\n", encoding="utf-8")
        req_dev = tmp_path / "requirements-dev.txt"
        req_dev.write_text("pytest>=9.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("requests==2.31.0\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_DEV", req_dev),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, message = check_lockfile_sync()

        assert not in_sync
        assert "pytest" in message

    def test_extras_pin_fails(self, tmp_path: Path) -> None:
        """A lock pin carrying extras fails: pip rejects extras in constraints files."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("requests==2.31.0\npyjwt[crypto]==2.13.0\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, message = check_lockfile_sync()

        assert not in_sync
        assert "extras" in message
        assert "pyjwt[crypto]==2.13.0" in message

    def test_missing_lock_fails(self, tmp_path: Path) -> None:
        """check_lockfile_sync fails when requirements.lock is absent."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", tmp_path / "requirements.lock"),
        ):
            in_sync, msg = check_lockfile_sync()

        assert not in_sync
        assert "not found" in msg or "requirements.lock" in msg

    def test_missing_top_level_package_fails(self, tmp_path: Path) -> None:
        """check_lockfile_sync fails when a top-level package from requirements.txt is absent from the lock."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\nmypackage>=1.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        # Lock only pins requests, missing mypackage
        req_lock.write_text("requests==2.31.0\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, msg = check_lockfile_sync()

        assert not in_sync
        assert "mypackage" in msg or "missing" in msg.lower()

    def test_missing_requirements_txt_fails(self, tmp_path: Path) -> None:
        """check_lockfile_sync fails gracefully when requirements.txt is absent."""
        with patch("scripts.import_governance._REQUIREMENTS_TXT", tmp_path / "requirements.txt"):
            in_sync, msg = check_lockfile_sync()
        assert not in_sync
        assert "not found" in msg or "requirements.txt" in msg

    def test_extras_are_normalized(self, tmp_path: Path) -> None:
        """A requirements.txt entry with extras matches its stripped lock pin.

        The lock side must be extras-free (pip rejects extras in constraints files; see
        test_extras_pin_fails) -- pip-compile --strip-extras pins the bare name, and the
        sync check matches it against the extras-carrying requirement.
        """
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("uvicorn[standard,http2]>=0.11.1\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("uvicorn==0.11.1\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, msg = check_lockfile_sync()

        assert in_sync, f"Expected extras-normalized package to be found; got: {msg}"

    def test_incompatible_major_pin_fails(self, tmp_path: Path) -> None:
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("mcp>=1.28.0,<2\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("mcp==2.0.0\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, msg = check_lockfile_sync()

        assert not in_sync
        assert "mcp<2,>=1.28.0 rejects 2.0.0" in msg

    @pytest.mark.parametrize("requirements_file", ["requirements.txt", "requirements-fast.txt"])
    def test_mcp_declaration_rejects_major_two(self, requirements_file: str) -> None:
        from packaging.requirements import Requirement
        from packaging.version import Version

        declaration = next(
            line for line in Path(requirements_file).read_text(encoding="utf-8").splitlines() if line.startswith("mcp")
        )
        assert Version("1.28.1") in Requirement(declaration).specifier
        assert Version("2.0.0") not in Requirement(declaration).specifier

    def test_pytz_is_a_direct_requirement_not_a_transitive_survivor(self) -> None:
        """pytz must be declared in requirements.txt and pinned in the lock as a DIRECT dependency.

        duckdb soft-imports pytz when it converts tz-aware timestamps (the DuckLake read path
        scripts/session/preflight.py serves from cache), but declares no hard dependency on it --
        the same soft-import scripts/build_lambda_config.py's DUCKLAKE_DEPS already pins for the
        Lambda layer. While pytz survived in the lock only as another package's transitive pin, the
        repo cleanse that removed that parent silently deleted pytz too, and every `pip install -c
        requirements.lock` CI install lost the module (red main-validate on c19328d). Asserting the
        `-r requirements.txt` provenance -- not merely the pin's presence -- is what stops pytz from
        regressing back to a transitive survivor.
        """
        from packaging.requirements import Requirement
        from packaging.version import Version

        declaration = next(
            line for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.startswith("pytz")
        )
        specifier = Requirement(declaration.split("#")[0].strip()).specifier

        lock_lines = (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        pin_index = next(i for i, line in enumerate(lock_lines) if line.startswith("pytz=="))
        pinned = Version(lock_lines[pin_index].split("==")[1].strip())
        assert pinned in specifier, f"lock pin {pinned} does not satisfy requirements.txt {specifier}"
        assert lock_lines[pin_index + 1].strip() == "# via -r requirements.txt", (
            f"pytz must be pinned as a direct requirement, not a transitive survivor: got {lock_lines[pin_index + 1]!r}"
        )

    def test_comments_and_blanks_skipped(self, tmp_path: Path) -> None:
        """Comments and blank lines in requirements.txt are ignored."""
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("# core\nrequests>=2.0\n\n# dev\npytest>=7.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text("requests==2.31.0\npytest==7.4.0\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, msg = check_lockfile_sync()

        assert in_sync

    @pytest.mark.parametrize("invalid_lock_line", ["not a requirement", "requests==not-a-version", "requests==1.*"])
    def test_invalid_lock_entries_do_not_count_as_pins(self, tmp_path: Path, invalid_lock_line: str) -> None:
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("requests>=2.0\n", encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text(f"{invalid_lock_line}\n", encoding="utf-8")

        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            in_sync, msg = check_lockfile_sync()

        assert not in_sync
        assert "missing pins for: requests" in msg

    def _gate(self, tmp_path: Path, req_text: str, lock_text: str) -> tuple[bool, str]:
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text(req_text, encoding="utf-8")
        req_lock = tmp_path / "requirements.lock"
        req_lock.write_text(lock_text, encoding="utf-8")
        with (
            patch("scripts.import_governance._REQUIREMENTS_TXT", req_txt),
            patch("scripts.import_governance._REQUIREMENTS_LOCK", req_lock),
        ):
            return check_lockfile_sync()

    def test_absurd_bump_with_trailing_comment_fails(self, tmp_path: Path) -> None:
        """An inline comment must not hide an absurd floor from the gate (the pre-fix silent skip)."""
        in_sync, msg = self._gate(tmp_path, "duckdb>=99.0  # inline comment\n", "duckdb==1.5.4\n")
        assert not in_sync, msg
        assert "incompatible pins" in msg and "duckdb>=99.0 rejects 1.5.4" in msg, msg

    def test_absurd_bump_without_comment_fails_identically(self, tmp_path: Path) -> None:
        """Control: the uncommented form already fails through the specifier-compatibility branch."""
        in_sync, msg = self._gate(tmp_path, "duckdb>=99.0\n", "duckdb==1.5.4\n")
        assert not in_sync, msg
        assert "incompatible pins" in msg and "duckdb>=99.0 rejects 1.5.4" in msg, msg

    def test_unparseable_declaration_fails_not_skipped(self, tmp_path: Path) -> None:
        """A line packaging cannot parse is a FAIL naming the line, never a silent skip."""
        in_sync, msg = self._gate(tmp_path, "not a requirement\nrequests>=2.0\n", "requests==2.31.0\n")
        assert not in_sync, msg
        assert "not a requirement" in msg, msg

    def test_hash_without_preceding_whitespace_is_not_a_comment(self, tmp_path: Path) -> None:
        """pip's comment rule needs whitespace before '#': `foo>=1.0#x` is unparseable, so the gate FAILS."""
        in_sync, msg = self._gate(tmp_path, "foo>=1.0#x\n", "foo==1.0.0\n")
        assert not in_sync, msg
        assert "foo>=1.0#x" in msg, msg

    def test_commented_declarations_are_counted(self, tmp_path: Path) -> None:
        """The four real inline-comment shapes are parsed and counted, not skipped."""
        req = (
            "psycopg2-binary>=2.9.12  # Neon catalog connections\n"
            "duckdb>=1.5.4  # generated by scripts/sync/ducklake_version.py\n"
            "python-ulid>=3.1.0  # monotonic ULID generation\n"
            "pytz>=2026.2  # duckdb soft-imports pytz\n"
        )
        lock = "psycopg2-binary==2.9.12\nduckdb==1.5.4\npython-ulid==3.1.0\npytz==2026.2\n"
        in_sync, msg = self._gate(tmp_path, req, lock)
        assert in_sync, msg
        assert "4 top-level packages" in msg, msg

    def test_live_declarations_all_parsed(self) -> None:
        """Every declaration in the live requirements files is parsed: declared count == gate-reported count."""
        comment = re.compile(r"(^|\s+)#.*$")
        declared = 0
        for name in ("requirements.txt", "requirements-dev.txt"):
            for raw in (ROOT / name).read_text(encoding="utf-8").splitlines():
                line = comment.sub("", raw).strip()
                if line and not line.startswith("-"):
                    declared += 1
        with patch("scripts.import_governance._REQUIREMENTS_DEV", ROOT / "requirements-dev.txt"):
            in_sync, msg = check_lockfile_sync()
        assert in_sync, msg
        assert f"{declared} top-level packages" in msg, f"declared {declared}: {msg}"


# ---------------------------------------------------------------------------
# evaluate_bazel_revisit_trigger
# ---------------------------------------------------------------------------


class TestEvaluateBazelRevisitTrigger:
    def test_dormant_at_concurrency_one(self) -> None:
        """Trigger is dormant when executor concurrency == 1 (current state)."""
        with patch("scripts.import_governance._read_executor_concurrency", return_value=1):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert not fired
        assert "DORMANT" in msg
        assert "concurrency=1" in msg

    def test_does_not_fire_when_concurrency_gt1_but_no_second_condition(self) -> None:
        """Trigger stays dormant when concurrency > 1 but neither KG.13 nor breach is present."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=2),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=False),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=False),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert not fired
        assert "DORMANT" in msg

    def test_fires_when_concurrency_gt1_and_kg13_filed(self) -> None:
        """Trigger fires when concurrency > 1 AND KG.13 is filed."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=2),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=True),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=False),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert fired
        assert "ADVISORY" in msg
        assert "KG.13" in msg

    def test_fires_when_concurrency_gt1_and_budget_breach(self) -> None:
        """Trigger fires when concurrency > 1 AND a budget breach is open."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=3),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=False),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=True),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert fired
        assert "ADVISORY" in msg
        assert "breach" in msg.lower() or "budget" in msg.lower()

    def test_advisory_message_does_not_auto_act(self) -> None:
        """Fired trigger message is advisory only -- no auto-action language."""
        with (
            patch("scripts.import_governance._read_executor_concurrency", return_value=2),
            patch("scripts.import_governance._kg13_tier_item_filed", return_value=True),
            patch("scripts.import_governance._fast_tier_budget_breach_open", return_value=False),
        ):
            fired, msg = evaluate_bazel_revisit_trigger()
        assert fired
        assert "No automatic action" in msg or "Decision 55" in msg


# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------


class TestNormalizePkg:
    def test_lowercases(self) -> None:
        assert _normalize_pkg("Requests") == "requests"

    def test_replaces_hyphens(self) -> None:
        assert _normalize_pkg("import-linter") == "import_linter"

    def test_replaces_dots(self) -> None:
        assert _normalize_pkg("zope.interface") == "zope_interface"


class TestReadExecutorConcurrency:
    def test_returns_one_when_no_capabilities(self, tmp_path: Path) -> None:
        with patch("scripts.import_governance.ROOT", tmp_path):
            val = _read_executor_concurrency()
        assert val == 1

    def test_reads_concurrency_from_yaml(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "config" / "agent" / "executor"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "capabilities.yaml").write_text("concurrency: 4\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            val = _read_executor_concurrency()
        assert val == 4

    def test_defaults_to_one_on_parse_error(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "config" / "agent" / "executor"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "capabilities.yaml").write_text("not: valid: yaml: :\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            val = _read_executor_concurrency()
        assert val == 1


class TestKg13TierItemFiled:
    def test_false_when_no_roadmap(self, tmp_path: Path) -> None:
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _kg13_tier_item_filed()

    def test_true_when_id_present(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "docs" / "ROADMAP-PLATFORM.yaml"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text("tier_items:\n  - id: KG.13\n    name: foo\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert _kg13_tier_item_filed()

    def test_false_when_id_absent(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "docs" / "ROADMAP-PLATFORM.yaml"
        roadmap.parent.mkdir(parents=True)
        roadmap.write_text("tier_items:\n  - id: T3.11\n    name: foo\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _kg13_tier_item_filed()

    def test_false_when_roadmap_read_fails(self, tmp_path: Path) -> None:
        roadmap = tmp_path / "docs" / "ROADMAP-PLATFORM.yaml"
        roadmap.parent.mkdir(parents=True)
        roadmap.touch()
        with (
            patch("scripts.import_governance.ROOT", tmp_path),
            patch.object(Path, "read_text", side_effect=OSError("unreadable")),
        ):
            assert not _kg13_tier_item_filed()


class TestFastTierBudgetBreachOpen:
    def test_false_when_no_log(self, tmp_path: Path) -> None:
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _fast_tier_budget_breach_open()

    def test_true_when_open_budget_breach_rec(self, tmp_path: Path) -> None:
        import json

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / ".recommendations-log.jsonl"
        log.write_text(
            json.dumps({"status": "open", "title": "fast tier budget breach exceeded"}) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert _fast_tier_budget_breach_open()

    def test_false_when_rec_is_closed(self, tmp_path: Path) -> None:
        import json

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / ".recommendations-log.jsonl"
        log.write_text(
            json.dumps({"status": "closed", "title": "fast tier budget breach exceeded"}) + "\n",
            encoding="utf-8",
        )
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _fast_tier_budget_breach_open()

    def test_invalid_json_line_is_ignored(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / ".recommendations-log.jsonl").write_text("not-json\n", encoding="utf-8")
        with patch("scripts.import_governance.ROOT", tmp_path):
            assert not _fast_tier_budget_breach_open()

    def test_false_when_log_read_fails(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / ".recommendations-log.jsonl"
        log.touch()
        with (
            patch("scripts.import_governance.ROOT", tmp_path),
            patch.object(Path, "open", side_effect=OSError("unreadable")),
        ):
            assert not _fast_tier_budget_breach_open()


class TestMain:
    def test_check_contracts_dispatch(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["import_governance", "--check-contracts"])
        with patch("scripts.import_governance.run_import_contracts", return_value=(True, "contracts ok\n")):
            with pytest.raises(SystemExit, match="0"):
                main()
        assert capsys.readouterr().out == "contracts ok\n"

    def test_check_lockfile_dispatch_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["import_governance", "--check-lockfile"])
        with patch("scripts.import_governance.check_lockfile_sync", return_value=(False, "lock drift")):
            with pytest.raises(SystemExit, match="1"):
                main()
        assert capsys.readouterr().out == "lock drift\n"

    def test_revisit_trigger_dispatch(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["import_governance", "--revisit-trigger"])
        with patch("scripts.import_governance.evaluate_bazel_revisit_trigger", return_value=(False, "dormant")):
            with pytest.raises(SystemExit, match="0"):
                main()
        assert capsys.readouterr().out == "dormant\n"

    @pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
    def test_module_entrypoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["import_governance", "--revisit-trigger"])
        with pytest.raises(SystemExit, match="0"):
            runpy.run_module("scripts.import_governance", run_name="__main__")
