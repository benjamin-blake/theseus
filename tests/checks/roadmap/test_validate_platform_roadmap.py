"""Tests for validate_platform_roadmap(). Mirror of
scripts/checks/roadmap/validate_platform_roadmap.py -- merges
TestPlatformRoadmapCriteriaIntegrity, TestPlatformRoadmapT31Criteria,
TestRoadmapSizeGuard, and the module-level
test_platform_roadmap_t31_criteria_are_structured (rec-2709 Wave 1)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks._common import ROOT
from scripts.checks.roadmap.validate_platform_roadmap import validate_platform_roadmap
from tests.fixtures.subprocess_stubs import _mock_completed


def test_platform_roadmap_t31_criteria_are_structured() -> None:
    """VP step 10: T3.1 exit_criteria are structured ExitCriterion objects, not bare strings."""
    import yaml  # noqa: PLC0415

    data = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
    t31 = next((item for item in data["tier_items"] if item.get("id") == "T3.1"), None)
    assert t31 is not None
    for crit in t31["exit_criteria"]:
        assert isinstance(crit, dict)
        assert {"id", "text", "status"} <= crit.keys()


class TestPlatformRoadmapCriteriaIntegrity:
    """Tests for validate_platform_roadmap() criteria-status integrity assertions (T-1.23).

    Check (i)  -- met criterion met_by resolves to a real plan file or 40-hex sha.
    Check (iii) -- every PLAN-*.yaml closes_criteria ref resolves to a real item:criterion.
    """

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    def _setup_dirs(self, tmp_path: Path, roadmap_extra: str = "") -> None:
        """Write a minimal ROADMAP-PLATFORM.yaml and create docs/plans/ under tmp_path."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "plans").mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._MINIMAL_ROADMAP + roadmap_extra, encoding="utf-8")

    @staticmethod
    def _no_diff_ctx():
        """Patch subprocess.run so the git-diff check (ii) sees an empty diff."""
        return patch(
            "scripts.checks.roadmap.validate_platform_roadmap.subprocess.run",
            return_value=_mock_completed(returncode=0, stdout=""),
        )

    def test_met_criterion_dangling_met_by_fails(self, tmp_path: Path) -> None:
        """Check (i): met criterion whose met_by names no real plan and is not a 40-hex SHA -> failure."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: Some criterion\n"
            "        status: met\n"
            "        met_by: nonexistent-plan\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_met_criterion_valid_plan_file_passes(self, tmp_path: Path) -> None:
        """Check (i): met criterion whose met_by points to an existing PLAN-*.yaml -> pass."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: Some criterion\n"
            "        status: met\n"
            "        met_by: real-plan\n",
        )
        (tmp_path / "docs" / "plans" / "PLAN-real-plan.yaml").write_text("slug: real-plan\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed
        assert "Platform roadmap schema validation" not in failed

    def test_met_criterion_valid_sha_passes(self, tmp_path: Path) -> None:
        """Check (i): met criterion whose met_by is a 40-hex commit SHA -> pass."""
        sha = "a" * 40
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: Some criterion\n"
            "        status: met\n"
            f"        met_by: '{sha}'\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed

    def test_closes_criteria_unknown_item_fails(self, tmp_path: Path) -> None:
        """Check (iii): PLAN closes_criteria refs a tier_item id absent from the roadmap -> failure."""
        self._setup_dirs(tmp_path)  # roadmap has no tier_items
        (tmp_path / "docs" / "plans" / "PLAN-test-plan.yaml").write_text("closes_criteria:\n  - T999.1:c1\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_closes_criteria_unknown_criterion_fails(self, tmp_path: Path) -> None:
        """Check (iii): PLAN closes_criteria refs a criterion id absent from a known item -> failure."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: criterion 1\n"
            "        status: open\n",
        )
        (tmp_path / "docs" / "plans" / "PLAN-test-plan.yaml").write_text("closes_criteria:\n  - T0.1:c999\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_closes_criteria_valid_ref_passes(self, tmp_path: Path) -> None:
        """Check (iii): PLAN closes_criteria ref resolves to a real item:criterion -> pass."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: criterion 1\n"
            "        status: open\n",
        )
        (tmp_path / "docs" / "plans" / "PLAN-test-plan.yaml").write_text("closes_criteria:\n  - T0.1:c1\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff_ctx():
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed
        assert "Platform roadmap schema validation" not in failed

    def test_diff_touched_item_with_bare_string_criterion_fails(self, tmp_path: Path) -> None:
        """Check (ii): a tier_item appearing in the git diff that retains a bare-string criterion -> failure.

        The Pydantic normalizer converts bare strings at load time, but check (ii) reads the raw YAML
        to detect whether the on-disk representation still has unstructured criteria on touched items.
        """
        self._setup_dirs(
            tmp_path,
            # Bare-string criterion: Pydantic normalizes it but the raw YAML still has a string.
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - criterion that was never converted to ExitCriterion format\n",
        )
        # Simulate a git diff that names T0.1 as a modified tier_item.
        mock_diff = "+  - id: T0.1\n+    status: in_progress\n"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.roadmap.validate_platform_roadmap.subprocess.run",
                return_value=_mock_completed(returncode=0, stdout=mock_diff),
            ),
        ):
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" in failed

    def test_diff_touched_item_with_structured_criteria_passes(self, tmp_path: Path) -> None:
        """Check (ii): a tier_item in the diff with fully-structured criteria -> pass (no failure)."""
        self._setup_dirs(
            tmp_path,
            "tier_items:\n"
            "  - id: T0.1\n"
            "    tier: T0\n"
            "    name: Test item\n"
            "    exit_criteria:\n"
            "      - id: c1\n"
            "        text: structured criterion\n"
            "        status: open\n",
        )
        mock_diff = "+  - id: T0.1\n"
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.roadmap.validate_platform_roadmap.subprocess.run",
                return_value=_mock_completed(returncode=0, stdout=mock_diff),
            ),
        ):
            validate_platform_roadmap(failed)
        assert "Platform roadmap criteria integrity" not in failed
        assert "Platform roadmap schema validation" not in failed


class TestPlatformRoadmapT31Criteria:
    """Tests that T3.1's exit_criteria are now structured ExitCriterion objects."""

    def test_t31_exit_criteria_are_structured(self) -> None:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
        t31 = next((item for item in data["tier_items"] if item.get("id") == "T3.1"), None)
        assert t31 is not None, "T3.1 not found in ROADMAP-PLATFORM.yaml"
        criteria = t31["exit_criteria"]
        assert isinstance(criteria, list)
        assert len(criteria) == 7
        for crit in criteria:
            assert isinstance(crit, dict), f"Criterion is not a dict: {crit!r}"
            assert "id" in crit, f"Criterion missing 'id': {crit}"
            assert "text" in crit, f"Criterion missing 'text': {crit}"
            assert "status" in crit, f"Criterion missing 'status': {crit}"

    def test_t31_criterion_ids_are_c1_through_c7(self) -> None:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load((ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
        t31 = next((item for item in data["tier_items"] if item.get("id") == "T3.1"), None)
        ids = [c["id"] for c in t31["exit_criteria"]]
        assert ids == ["c1", "c2", "c3", "c4", "c5", "c6", "c7"]


class TestRoadmapSizeGuard:
    """Tests for _roadmap_size_issues() / _ROADMAP_MAX_LINES (Decision 114, PLAN-close-audit-ulf-04-ulf-10)."""

    def test_ceiling_constant_is_10000(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _ROADMAP_MAX_LINES

        assert _ROADMAP_MAX_LINES == 10000

    def test_over_ceiling_returns_one_item_fail_list(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _roadmap_size_issues

        text = "\n" * 10001
        issues = _roadmap_size_issues(text, ceiling=10000)
        assert len(issues) == 1
        assert "10001" in issues[0]
        assert "10000" in issues[0]
        assert "Decision 114" in issues[0]

    def test_within_ceiling_returns_empty_list(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _roadmap_size_issues

        text = "\n" * 9999
        issues = _roadmap_size_issues(text, ceiling=10000)
        assert issues == []

    def test_exactly_at_ceiling_returns_empty_list(self) -> None:
        from scripts.checks.roadmap.validate_platform_roadmap import _roadmap_size_issues

        text = "line\n" * 10000
        issues = _roadmap_size_issues(text, ceiling=10000)
        assert issues == []


class TestPlatformRoadmapWrapperFailureEmission:
    """One guard per previously unreached failed.append site in the registered wrapper.

    All five sites append the identical string, so exact list equality on `failed` plus the
    site's own stdout marker is what attributes a failure to a single emission site.
    """

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    @staticmethod
    def _write_roadmap(tmp_path: Path, body: str) -> None:
        """Write body to <tmp_path>/docs/ROADMAP-PLATFORM.yaml, creating docs/ as needed."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(body, encoding="utf-8")

    @staticmethod
    def _run(tmp_path: Path) -> list[str]:
        """Drive the registered wrapper against tmp_path and return its failed list."""
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_platform_roadmap(failed)
        return failed

    def test_missing_roadmap_file_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 46: no docs/ROADMAP-PLATFORM.yaml -> early-return append."""
        failed = self._run(tmp_path)

        out = capsys.readouterr().out
        assert failed == ["Platform roadmap schema validation"]
        assert "FAIL: docs/ROADMAP-PLATFORM.yaml not found" in out

    def test_import_error_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 141: the in-function platform_roadmap import raises -> `except ImportError` append."""
        self._write_roadmap(tmp_path, self._MINIMAL_ROADMAP)

        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch.dict(sys.modules, {"scripts.roadmap.platform_roadmap": None}),
        ):
            validate_platform_roadmap(failed)

        out = capsys.readouterr().out
        assert failed == ["Platform roadmap schema validation"]
        assert "ERROR: Could not import platform_roadmap" in out

    def test_pydantic_validation_error_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 144: an unsupported document.version trips DocumentMeta._check_version."""
        self._write_roadmap(
            tmp_path,
            "document:\n  id: test-roadmap\n  version: 99\n  status: draft\n  filed_via: pending_log_decision_lambda\n",
        )

        failed = self._run(tmp_path)

        out = capsys.readouterr().out
        assert failed == ["Platform roadmap schema validation"]
        assert "FAIL: Pydantic validation error:" in out

    def test_yaml_parse_error_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 147: an unterminated flow sequence makes load()'s yaml.safe_load raise."""
        self._write_roadmap(tmp_path, "document: [unclosed\n")

        failed = self._run(tmp_path)

        out = capsys.readouterr().out
        assert failed == ["Platform roadmap schema validation"]
        assert "FAIL: YAML parse error:" in out

    def test_unexpected_error_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 150: a non-ImportError/ValidationError/YAMLError escape hits the catch-all arm."""
        self._write_roadmap(tmp_path, self._MINIMAL_ROADMAP)

        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.roadmap.platform_roadmap.load", side_effect=RuntimeError("boom")),
        ):
            validate_platform_roadmap(failed)

        out = capsys.readouterr().out
        assert failed == ["Platform roadmap schema validation"]
        assert "FAIL: Unexpected error: boom" in out


class TestAccountingDeclaration:
    """Decision 170 arm (d): the check declares examined() over tier_items on its single
    reachable success exit, and that ONE unconditional call before the terminal if/else dominates
    every branch of the criteria walk -- which is why each branch is driven here rather than only
    the happy path (the walker enters except handlers from the try-ENTRY state, so a declaration
    inside a handler would not cover the fall-through).
    """

    _ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
        "tier_items:\n"
        "  - id: T0.1\n"
        "    tier: T0\n"
        "    name: Test item\n"
        "    exit_criteria:\n"
        "      - id: c1\n"
        "        text: structured criterion\n"
        "        status: open\n"
    )

    def _tree(self, tmp_path: Path) -> None:
        """Write a loadable roadmap plus an empty docs/plans/ under tmp_path."""
        (tmp_path / "docs" / "plans").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "ROADMAP-PLATFORM.yaml").write_text(self._ROADMAP, encoding="utf-8")

    @staticmethod
    def _no_diff():
        """Patch the criterion (ii) git-diff seam so it sees an empty diff."""
        return patch(
            "scripts.checks.roadmap.validate_platform_roadmap.subprocess.run",
            return_value=_mock_completed(returncode=0, stdout=""),
        )

    def _run(self, tmp_path: Path):
        """Drive the check and return (failed, declaration)."""
        from scripts.checks import registry  # noqa: PLC0415

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path), self._no_diff():
            validate_platform_roadmap(failed)
        return failed, registry.pop_declaration()

    def test_the_success_path_declares_examined_over_tier_items(self, tmp_path: Path) -> None:
        self._tree(tmp_path)

        failed, declaration = self._run(tmp_path)

        assert failed == []
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "tier_items"
        assert declaration.count == 1

    def test_the_module_measures_fully_declared_on_every_reachable_success_exit(self) -> None:
        from scripts.checks import registry  # noqa: PLC0415
        from scripts.checks.hygiene._declaring_coverage import is_fully_declared, measure_check  # noqa: PLC0415

        row = measure_check("validate_platform_roadmap", registry.resolve("validate_platform_roadmap"))

        assert row.undeclared == 0
        assert is_fully_declared(row)

    def test_the_roster_no_longer_exempts_this_check(self) -> None:
        import yaml  # noqa: PLC0415

        roster = yaml.safe_load((ROOT / "config" / "check_accounting_baseline.yaml").read_text(encoding="utf-8"))

        assert "validate_platform_roadmap" not in roster["entries"]

    @pytest.mark.parametrize(
        ("plan_body", "expect_failure"),
        [
            ("- not a mapping\n", False),
            ("closes_criteria: 3\n", False),
            ("closes_criteria:\n  - nocolon\n", True),
            ("closes_criteria: [unclosed\n", True),
        ],
    )
    def test_the_declaration_is_reached_from_every_criteria_walk_branch(
        self, tmp_path: Path, plan_body: str, expect_failure: bool
    ) -> None:
        self._tree(tmp_path)
        (tmp_path / "docs" / "plans" / "PLAN-probe.yaml").write_text(plan_body, encoding="utf-8")

        failed, declaration = self._run(tmp_path)

        assert bool(failed) is expect_failure
        assert declaration is not None and declaration.kind == "examined"

    def test_the_declaration_is_reached_when_a_criterion_is_not_an_exit_criterion_object(self, tmp_path: Path) -> None:
        from scripts.roadmap import platform_roadmap  # noqa: PLC0415

        self._tree(tmp_path)
        real_load = platform_roadmap.load

        def _load_with_a_raw_criterion(path):
            doc = real_load(path)
            doc.tier_items[0].exit_criteria.append("a raw criterion the walk must skip")
            return doc

        from scripts.checks import registry  # noqa: PLC0415

        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            self._no_diff(),
            patch("scripts.roadmap.platform_roadmap.load", _load_with_a_raw_criterion),
        ):
            validate_platform_roadmap(failed)
        declaration = registry.pop_declaration()

        assert failed == []
        assert declaration is not None and declaration.kind == "examined"


class TestSpanAttributionAdvisory:
    """The report-only span attribution printed beside criterion (ii)'s frozen legacy detector.

    REPORT-ONLY is absolute: the advisory prints, and criterion (ii)'s failing-arm input stays
    the legacy set behind its named symbol.
    """

    _PRE = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
        "tier_items:\n"
        "  - id: T0.1\n"
        "    tier: T0\n"
        "    name: Test item\n"
        "    exit_criteria:\n"
        "      - id: c1\n"
        "        text: structured criterion\n"
        "        status: open\n"
    )
    _POST = _PRE.replace("    name: Test item\n", "    name: Test item edited\n")

    @staticmethod
    def _unified(pre: str, post: str) -> str:
        import difflib  # noqa: PLC0415

        return "\n".join(difflib.unified_diff(pre.splitlines(), post.splitlines(), lineterm="")) + "\n"

    def _tree(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "plans").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "ROADMAP-PLATFORM.yaml").write_text(self._POST, encoding="utf-8")

    def _run(self, tmp_path: Path, diff_text: str, base_text: str | None | Exception) -> list[str]:
        """Drive the check with a synthetic diff and a synthetic origin/main image.

        `default_base_reader` is patched EXPLICITLY on both arms -- including the None arm.
        Leaving it unpatched would not exercise the missing-base contract at all: the
        `subprocess.run` patch below rebinds the attribute on the shared subprocess module, which
        `scripts.checks._common.run` calls too, so the real reader would read back the synthetic
        diff as though it were the origin/main image.
        """
        reader = {"side_effect": base_text} if isinstance(base_text, Exception) else {"return_value": base_text}
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.roadmap.validate_platform_roadmap.subprocess.run",
                return_value=_mock_completed(returncode=0, stdout=diff_text),
            ),
            patch("scripts.checks.roadmap.validate_platform_roadmap.default_base_reader", **reader),
        ):
            validate_platform_roadmap(failed)
        return failed

    def test_the_advisory_names_the_ids_the_legacy_detector_missed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._tree(tmp_path)
        diff = self._unified(self._PRE, self._POST)

        failed = self._run(tmp_path, diff, self._PRE)

        out = capsys.readouterr().out
        assert "SPAN-ATTRIBUTION span_named=1 legacy_named=0 missed_by_legacy=['T0.1']" in out
        assert "legacy_named_outside_spans=[] (report-only, nothing failed)" in out
        assert failed == []

    def test_the_legacy_detector_names_nothing_on_that_same_body_edit(self, tmp_path: Path) -> None:
        from scripts.checks.roadmap._roadmap_spans import legacy_regex_item_ids  # noqa: PLC0415

        diff = self._unified(self._PRE, self._POST)

        assert legacy_regex_item_ids(diff) == set()

    def test_criterion_ii_consumes_the_frozen_legacy_set(self, tmp_path: Path) -> None:
        """The failing arm's input is the SAME legacy detector, now behind a named symbol: a diff
        naming a touched item with a bare-string criterion still fails."""
        bare = self._POST.replace(
            "    exit_criteria:\n      - id: c1\n        text: structured criterion\n        status: open\n",
            "    exit_criteria:\n      - a bare string criterion\n",
        )
        (tmp_path / "docs" / "plans").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "ROADMAP-PLATFORM.yaml").write_text(bare, encoding="utf-8")

        failed = self._run(tmp_path, "+  - id: T0.1\n+    status: in_progress\n", self._PRE)

        assert "Platform roadmap criteria integrity" in failed

    def test_the_advisory_changes_nothing_criterion_ii_appends(self, tmp_path: Path) -> None:
        self._tree(tmp_path)
        diff = self._unified(self._PRE, self._POST)

        with_advisory = self._run(tmp_path, diff, self._PRE)
        without_base = self._run(tmp_path, diff, None)

        assert with_advisory == without_base == []

    def test_the_origin_main_unreachable_arm_prints_its_own_skip_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """default_base_reader's missing-base contract (None on an unreachable ref) is the
        advisory's own skip arm -- a second git seam of this module's own is what Decision 104
        sole-home discipline forbids."""
        self._tree(tmp_path)

        failed = self._run(tmp_path, self._unified(self._PRE, self._POST), None)

        out = capsys.readouterr().out
        assert "SKIP: origin/main image of docs/ROADMAP-PLATFORM.yaml unreachable" in out
        assert "SPAN-ATTRIBUTION" not in out
        assert failed == []

    @pytest.mark.parametrize("boom", [UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), OSError("git unavailable")])
    def test_a_raising_base_read_is_skipped_and_never_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], boom: Exception
    ) -> None:
        """RED on the pre-fix module: the raise reached the check body's catch-all and appended to failed."""
        self._tree(tmp_path)
        failed = self._run(tmp_path, self._unified(self._PRE, self._POST), boom)
        assert failed == []
        assert "SKIP: origin/main image of docs/ROADMAP-PLATFORM.yaml unreachable" in capsys.readouterr().out
