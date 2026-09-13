"""TestRoadmapLivenessBaselineRow (PLAN-roadmap-liveness-baseline-companion): the
roadmap_liveness_baseline_shrink sanction row's scope_contains_file trigger kind.

Three arms: a plan declaring docs/ROADMAP-PLATFORM.yaml in scope sanctions
config/roadmap_liveness_baseline.yaml (no findings); a plan that omits it still STOPs on that
same touched path; and the row derives exactly that one path, nothing else -- a sibling
unrelated companion path stays unsanctioned even with the roadmap in scope.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import _ResolvedFixture, validate_scope_boundary

_BASELINE_PATH = "config/roadmap_liveness_baseline.yaml"


class TestRoadmapLivenessBaselineRow:
    def test_roadmap_in_scope_sanctions_the_baseline_path(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-roadmap-liveness", [{"file": "docs/ROADMAP-PLATFORM.yaml", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "docs/ROADMAP-PLATFORM.yaml", _BASELINE_PATH], root=repo)
        assert failed == []

    def test_roadmap_absent_from_scope_still_stops_on_baseline_path(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path, "sb-no-roadmap-liveness", [{"file": "scripts/foo.py", "action": "Modify", "purpose": "x"}]
        )
        failed: list[str] = []
        validate_scope_boundary(failed, changed_files=[rel, "scripts/foo.py", _BASELINE_PATH], root=repo)
        assert any(_BASELINE_PATH in f and "outside declared scope" in f for f in failed)

    def test_row_derives_exactly_one_path_and_nothing_else(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "sb-roadmap-liveness-narrow",
            [{"file": "docs/ROADMAP-PLATFORM.yaml", "action": "Modify", "purpose": "x"}],
        )
        failed: list[str] = []
        validate_scope_boundary(
            failed,
            changed_files=[rel, "docs/ROADMAP-PLATFORM.yaml", _BASELINE_PATH, "docs/contracts/roadmap-liveness.yaml"],
            root=repo,
        )
        assert any("docs/contracts/roadmap-liveness.yaml" in f and "outside declared scope" in f for f in failed)
        assert not any(_BASELINE_PATH in f for f in failed)
