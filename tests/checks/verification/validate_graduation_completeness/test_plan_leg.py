"""TestPlanPrLeg and TestWaiver (Decision 176 concern-split decomposition of the former
tests/checks/verification/test_validate_graduation_completeness.py monolith), moved verbatim.

TestPlanPrLeg exercises the plan-PR leg via changed_files/root injection (a throwaway git repo
for net-new cases). TestWaiver exercises the implement leg's no-row-required waive/not-applicable
dispositions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from .conftest import _commit_all, _git, _ImplementFixture, _init_repo, _step, _write_plan, validate_graduation_completeness


class TestPlanPrLeg:
    def test_missing_disposition_fails(self, tmp_path: Path) -> None:
        rel = _write_plan(
            tmp_path,
            "gc-missing",
            [
                _step(1, graduation="waive", graduation_waiver_reason="needs live infra"),
                _step(2),  # no disposition -- has_any_disposition=True bypasses the pre-field skip
            ],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert any("lack a graduation disposition" in f and "[2]" in f for f in failed)

    def test_all_dispositions_present_passes(self, tmp_path: Path) -> None:
        rel = _write_plan(
            tmp_path,
            "gc-complete",
            [_step(1, graduation="graduate", graduation_check_id="gc-complete-check"), _step(2, graduation="not-applicable")],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_historical_plan_not_in_diff_is_untouched(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "gc-historical", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=["scripts/unrelated.py"], root=tmp_path)
        assert failed == []

    def test_merely_modified_pre_field_plan_is_skipped(self, tmp_path: Path) -> None:
        """Zero dispositions anywhere + not net-new (no git repo -> never 'added') is skipped, not failed."""
        rel = _write_plan(tmp_path, "gc-pre-field", [_step(1), _step(2)])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_net_new_plan_with_zero_dispositions_fails(self, tmp_path: Path) -> None:
        """A genuinely net-new plan (git diff --diff-filter=A) is enforced even with zero dispositions."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(repo, "gc-net-new", [_step(1), _step(2)])
        _commit_all(repo, "add plan")

        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        assert any("lack a graduation disposition" in f for f in failed)

    def test_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=["docs/plans/PLAN-gc-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_no_pre_deploy_steps_passes(self, tmp_path: Path) -> None:
        rel = _write_plan(tmp_path, "gc-post-only", [_step(1, phase="post-deploy")])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_push_event_trigger_root_scoped_base_still_detects_net_new(self, tmp_path: Path, monkeypatch) -> None:
        """rec-3166 (push event): pre-fix, push_context_base() read the DECOY `_common.ROOT` instead of `root`."""
        decoy = tmp_path / "decoy"
        _init_repo(decoy)
        (decoy / "d.txt").write_text("decoy\n", encoding="utf-8")
        _commit_all(decoy, "decoy first")
        (decoy / "d2.txt").write_text("decoy2\n", encoding="utf-8")
        _commit_all(decoy, "decoy second")

        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(repo, "gc-net-new-push", [_step(1), _step(2)])
        _commit_all(repo, "add plan")

        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", decoy):
            validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        assert any("lack a graduation disposition" in f for f in failed)

    def test_on_main_trigger_root_scoped_base_still_detects_net_new(self, tmp_path: Path) -> None:
        """rec-3166 (on-main trigger): `root` itself is on main with that state; ROOT is a DECOY."""
        decoy = tmp_path / "decoy"
        _init_repo(decoy)
        (decoy / "d.txt").write_text("decoy\n", encoding="utf-8")
        _commit_all(decoy, "decoy commit")

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, ["init", "-q", "-b", "main"])
        _git(repo, ["config", "user.email", "test@example.com"])
        _git(repo, ["config", "user.name", "Test"])
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(repo, "gc-net-new-onmain", [_step(1), _step(2)])
        after_sha = _commit_all(repo, "add plan")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])  # merge-base(origin/main, HEAD) == HEAD

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", decoy):
            validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        assert any("lack a graduation disposition" in f for f in failed)


class TestWaiver:
    fixture = _ImplementFixture()

    def test_waive_with_reason_requires_no_registry_row(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-waiver-only",
            [_step(1, graduation="waive", graduation_waiver_reason="requires live infra, not kernel-expressible")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_not_applicable_requires_no_registry_row(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path, "gc-not-applicable-only", [_step(1, graduation="not-applicable")], registry_entries=[]
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []
