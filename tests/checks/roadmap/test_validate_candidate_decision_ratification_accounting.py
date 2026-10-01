"""Check-accounting declaration tests for validate_candidate_decision_ratification() (Decision 170)."""

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks import registry, validation_result
from scripts.checks.roadmap.validate_candidate_decision_ratification import validate_candidate_decision_ratification

_REPO_ROOT = Path(__file__).parents[3]


class TestCandidateDecisionRatificationAccountingDeclaration:
    """The guard declares how many non-superseded candidate decisions it validated (R1/R2/R4 run on
    pending and ratified CDs; R3 exempts superseded ones), so a run is recorded enforced with a count
    that tracks the roadmap instead of undeclared."""

    _UNIT = "non_superseded_candidate_decisions"
    _HEADER = "document:\n  id: t\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"

    @staticmethod
    def _declare(root: Path) -> tuple[list[str], registry._Declaration | None]:
        registry.pop_declaration()
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", root):
            validate_candidate_decision_ratification(failed)
        return failed, registry.pop_declaration()

    def _write(self, root: Path, cd_yaml: str) -> None:
        docs_dir = root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._HEADER + cd_yaml, encoding="utf-8")
        (docs_dir / "DECISIONS.md").write_text("## Decision 7: X (Decided)\n", encoding="utf-8")

    def test_real_tree_declares_every_non_superseded_cd(self) -> None:
        raw = yaml.safe_load((_REPO_ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8"))
        expected = sum(1 for cd in raw["candidate_decisions"] if cd.get("state", "pending") != "superseded")
        failed, declaration = self._declare(_REPO_ROOT)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", expected, self._UNIT)

    def test_declared_count_tracks_pending_and_ratified_not_superseded(self, tmp_path: Path) -> None:
        ratified = "  - id: CD.{n}\n    title: t\n    state: ratified\n    ratified_as: dec-7\n"
        pending = "  - id: CD.{n}\n    title: t\n    state: pending\n"
        superseded = "  - id: CD.{n}\n    title: t\n    state: superseded\n"
        body = ratified.format(n=1) + pending.format(n=2) + superseded.format(n=3)
        self._write(tmp_path, "candidate_decisions:\n" + body)
        _, base = self._declare(tmp_path)
        self._write(tmp_path, "candidate_decisions:\n" + body + pending.format(n=4) + superseded.format(n=5))
        failed, grown = self._declare(tmp_path)
        assert failed == []
        assert base is not None and grown is not None
        assert (base.count, grown.count) == (2, 3)

    def test_failing_cd_still_counted(self, tmp_path: Path) -> None:
        cd = "  - id: CD.1\n    title: t\n    state: ratified\n    ratified_as: dec-9\n"
        self._write(tmp_path, "candidate_decisions:\n" + cd)
        failed, declaration = self._declare(tmp_path)
        assert failed == ["Candidate decision ratification guard"]
        assert declaration is not None and declaration.count == 1

    def test_all_superseded_declares_empty_domain(self, tmp_path: Path) -> None:
        self._write(tmp_path, "candidate_decisions:\n  - id: CD.1\n    title: t\n    state: superseded\n")
        failed, declaration = self._declare(tmp_path)
        assert failed == []
        assert declaration is not None
        assert (declaration.kind, declaration.count, declaration.unit) == ("examined", 0, self._UNIT)

    def test_real_tree_is_recorded_enforced(self) -> None:
        validation_result._OUTCOMES.clear()
        try:
            validation_result.dispatch_recording(
                "validate_candidate_decision_ratification", [], validate_candidate_decision_ratification
            )
            (outcome,) = validation_result._OUTCOMES
        finally:
            validation_result._OUTCOMES.clear()
        assert (outcome.status, outcome.examined_unit) == ("enforced", self._UNIT)
        assert outcome.examined_count is not None and outcome.examined_count > 0
