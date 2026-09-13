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
