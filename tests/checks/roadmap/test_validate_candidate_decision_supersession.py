"""Tests for validate_candidate_decision_supersession() (audit PCD-03)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.registry import full_sequence, pre_sequence
from scripts.checks.roadmap.validate_candidate_decision_supersession import (
    validate_candidate_decision_supersession,
)


class TestCandidateDecisionSupersession:
    """4-case fixture matrix: ratified-superseder=red; pending-superseder/narrow/self-demotion=green."""

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    def _setup(self, tmp_path: Path, cd_yaml: str) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._MINIMAL_ROADMAP + cd_yaml, encoding="utf-8")

    def test_pending_fully_superseded_by_ratified_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.7\n    title: t\n    state: pending\n"
            "    detail: '[Amendment -- fully superseded by CD.28]'\n"
            "  - id: CD.28\n    title: t2\n    state: ratified\n    ratified_as: dec-122\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_supersession(failed)
        assert "Candidate decision supersession guard" in failed

    def test_pending_fully_superseded_by_pending_passes(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.7\n    title: t\n    state: pending\n"
            "    detail: '[Amendment -- fully superseded by CD.28]'\n"
            "  - id: CD.28\n    title: t2\n    state: pending\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_supersession(failed)
        assert failed == []

    def test_narrow_supersession_does_not_trigger(self, tmp_path: Path) -> None:
        """CD.11's shape: 'narrowly superseded by CD.NN' must NOT match the 'fully superseded' trigger."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.11\n    title: t\n    state: pending\n"
            "    detail: '[Amendment -- narrowly superseded by CD.27]'\n"
            "  - id: CD.27\n    title: t2\n    state: ratified\n    ratified_as: dec-1\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_supersession(failed)
        assert failed == []

    def test_self_demotion_does_not_trigger(self, tmp_path: Path) -> None:
        """CD.10's shape: self-demoting amendment prose naming no successor CD must NOT trigger."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.10\n    title: t\n    state: pending\n"
            "    detail: '[Amendment -- audit integration (F-008)]: the six-Lambda enumeration is illustrative.'\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_supersession(failed)
        assert failed == []

    def test_unknown_superseder_does_not_trigger(self, tmp_path: Path) -> None:
        """A dangling 'fully superseded by CD.NN' whose CD.NN does not exist is deliberately not flagged."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.7\n    title: t\n    state: pending\n"
            "    detail: '[Amendment -- fully superseded by CD.999]'\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_supersession(failed)
        assert failed == []

    def test_registered_in_both_tiers(self) -> None:
        pre_names = {step.name for step in pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in full_sequence() if step.kind == "check"}
        assert "validate_candidate_decision_supersession" in pre_names
        assert "validate_candidate_decision_supersession" in full_names


class TestCandidateDecisionSupersessionWrapperEmission:
    """The guard's two early-return failed.append sites, which every well-formed fixture skips."""

    @staticmethod
    def _run(tmp_path: Path) -> list[str]:
        """Drive the registered guard against tmp_path and return its failed list."""
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_supersession(failed)
        return failed

    def test_missing_roadmap_file_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 39: no docs/ROADMAP-PLATFORM.yaml at all -> early-return append."""
        failed = self._run(tmp_path)

        out = capsys.readouterr().out
        assert failed == ["Candidate decision supersession guard"]
        assert "FAIL: docs/ROADMAP-PLATFORM.yaml not found" in out

    def test_unloadable_roadmap_appends_a_failure(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Line 52: an unparseable roadmap drives the `except Exception` early return."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text("document: [unclosed\n", encoding="utf-8")

        failed = self._run(tmp_path)

        out = capsys.readouterr().out
        assert failed == ["Candidate decision supersession guard"]
        assert "FAIL: could not load roadmap:" in out
