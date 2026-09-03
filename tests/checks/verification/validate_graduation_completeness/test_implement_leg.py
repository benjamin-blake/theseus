"""TestImplementPrLeg, TestObligationAwareDiagnostics, TestLoadErrorHandling, TestRegistryReaders
and TestContentKeyedResolution (Decision 176 concern-split decomposition of the former
tests/checks/verification/test_validate_graduation_completeness.py monolith), plus the new
TestShardedRegistryReaders.

TestRegistryReaders' incumbent test_current_entries_missing_file_is_empty is re-authored against
the loader's four-branch rule (Decision 176): a missing entries/ directory on the LIVE tree is
simply an empty/not-yet-graduated registry, distinct from entries_at_ref's branch (iii) (a
resolving ref missing BOTH layouts), which fails loud instead."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import _common, registry
from scripts.verification_graduation import GraduationError

from .conftest import (
    _commit_all,
    _current_registry_entries,
    _default_baseline_registry_entries,
    _git,
    _ImplementFixture,
    _init_repo,
    _step,
    _write_plan,
    _write_registry,
    validate_graduation_completeness,
)


class TestImplementPrLeg:
    fixture = _ImplementFixture()

    def test_graduate_step_missing_row_fails(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-impl-missing",
            [_step(1, graduation="graduate", graduation_check_id="gc-impl-missing-check")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)

    def test_graduate_step_with_matching_row_passes(self, tmp_path: Path) -> None:
        cid = "gc-impl-present-check"
        slug = "gc-impl-present"
        repo, rel = self.fixture.build(
            tmp_path,
            slug,
            [_step(1, graduation="graduate", graduation_check_id=cid)],
            registry_entries=[
                {
                    "check_id": cid,
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "scripts/example.py",
                    "plan_slug": slug,
                    "graduated_at": "2026-07-16",
                }
            ],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_flip_to_waive_passes_with_no_row(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-impl-waived",
            [_step(1, graduation="waive", graduation_waiver_reason="proved un-graduatable at implement time")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_undeclared_plan_is_noop_pass(self, tmp_path: Path) -> None:
        """implementation_declared=false resolves nothing -- plan-only PR, not yet implemented."""
        rel = _write_plan(
            tmp_path, "gc-undeclared", [_step(1, graduation="graduate", graduation_check_id="gc-undeclared-check")]
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_origin_main_unreachable_advisory_skips(self, tmp_path: Path, capsys) -> None:
        """No git repo at all (origin/main unreachable) never fails the implement leg."""
        rel = _write_plan(tmp_path, "gc-unreachable", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []
        assert "SKIP (implement-PR leg)" in capsys.readouterr().out

    def test_no_plan_in_diff_is_noop_pass(self) -> None:
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=["scripts/unrelated.py"], root=Path("/nonexistent"))
        assert failed == []


class TestObligationAwareDiagnostics:
    """Schema-v4 obligations name which declared behaviors lose their guard when a row is missing."""

    fixture = _ImplementFixture()
    _SELECTOR = "tests/test_example.py::test_behavior"

    def _overrides(self, sources: list[str]) -> dict:
        return {
            "schema_version": 4,
            "handoff_policy": {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
            "test_obligations": [
                {
                    "source": source,
                    "behavior": "stays guarded by the graduated check",
                    "test_selector": self._SELECTOR,
                    "verification_step": 1,
                    "red_green_expectation": "fails before the change and passes after it",
                }
                for source in sources
            ],
        }

    def _steps(self) -> list[dict]:
        return [
            _step(
                1,
                command=f"bin/venv-python -m pytest {self._SELECTOR}",
                graduation="graduate",
                graduation_check_id="gc-obligation-check",
            )
        ]

    def test_missing_row_names_the_obligation_sources_losing_their_guard(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-obligation-named",
            self._steps(),
            registry_entries=[],
            plan_overrides=self._overrides(["scripts/example.py", "scripts/other.py"]),
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("test obligation(s) losing their guard: scripts/example.py, scripts/other.py" in f for f in failed)

    def test_missing_row_without_obligations_keeps_the_original_diagnostic(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path, "gc-obligation-absent", self._steps(), registry_entries=[], plan_overrides=self._overrides([])
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)
        assert not any("losing their guard" in f for f in failed)


class TestLoadErrorHandling:
    """A schema error is validate_plan_documents' verdict; an import failure stays fail-loud (Decision 55)."""

    fixture = _ImplementFixture()

    @staticmethod
    def _raiser(exc: Exception):
        def _loader(plan_rel: str, root: Path) -> object:
            raise exc

        return _loader

    def test_plan_leg_import_error_is_fail_loud(self, tmp_path: Path) -> None:
        rel = _write_plan(tmp_path, "gc-plan-import", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(
            failed, changed_files=[rel], root=tmp_path, load_plan=self._raiser(ImportError("no module"))
        )
        assert any("could not import scripts.roadmap.plan_document" in f for f in failed)

    def test_plan_leg_schema_error_skips_without_double_reporting(self, tmp_path: Path, capsys) -> None:
        rel = _write_plan(tmp_path, "gc-plan-schema", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(
            failed, changed_files=[rel], root=tmp_path, load_plan=self._raiser(ValueError("bad schema"))
        )
        assert failed == []
        assert "SKIP (plan-PR leg)" in capsys.readouterr().out

    def test_implement_leg_import_error_is_fail_loud(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(tmp_path, "gc-impl-import", [_step(1)], registry_entries=[])
        failed: list[str] = []
        validate_graduation_completeness(
            failed,
            changed_files=[rel],
            root=repo,
            load_plan=self._raiser(ImportError("no module")),
            baseline_registry_reader=lambda r: [],
        )
        assert any("could not import scripts.roadmap.plan_document" in f for f in failed)

    def test_implement_leg_import_error_is_reported_by_the_implement_leg_itself(self, tmp_path: Path) -> None:
        """The implement leg's own append, told apart from the plan leg's identical wording."""
        repo, rel = self.fixture.build(tmp_path, "gc-impl-import-distinct", [_step(1)], registry_entries=[])
        failed: list[str] = []
        validate_graduation_completeness(
            failed,
            changed_files=[rel],
            root=repo,
            load_plan=self._raiser(ImportError("no module")),
            baseline_registry_reader=lambda r: [],
        )
        implement_leg = [f for f in failed if "(implement-PR leg)" in f]
        assert implement_leg, failed
        assert "could not import scripts.roadmap.plan_document" in implement_leg[0]

    def test_implement_leg_schema_error_skips_without_double_reporting(self, tmp_path: Path, capsys) -> None:
        repo, rel = self.fixture.build(tmp_path, "gc-impl-schema", [_step(1)], registry_entries=[])
        failed: list[str] = []
        validate_graduation_completeness(
            failed,
            changed_files=[rel],
            root=repo,
            load_plan=self._raiser(ValueError("bad schema")),
            baseline_registry_reader=lambda r: [],
        )
        assert failed == []
        assert "SKIP (implement-PR leg)" in capsys.readouterr().out


class TestRegistryReaders:
    """Both readers degrade to an empty list on a missing/unreachable input -- never raise."""

    def test_current_entries_missing_entries_dir_is_empty(self, tmp_path: Path) -> None:
        """Re-authored against the loader's four-branch rule (Decision 176) -- see module
        docstring."""
        assert _current_registry_entries(tmp_path) == []

    def test_baseline_without_origin_main_is_empty(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")
        assert _default_baseline_registry_entries(repo) == []

    def test_baseline_reads_entries_from_origin_main(self, tmp_path: Path) -> None:
        repo = self._repo_with_baseline(tmp_path, [{"check_id": "baseline-row"}])
        assert _default_baseline_registry_entries(repo) == [{"check_id": "baseline-row"}]

    def test_baseline_reads_entries_from_injected_base(self, tmp_path: Path) -> None:
        """The base is an injected parameter, not hardcoded -- a non-'origin/main' ref works too."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_registry(repo, [{"check_id": "tagged-row"}])
        sha = _commit_all(repo, "base")
        _git(repo, ["tag", "custom-base", sha])
        assert _default_baseline_registry_entries(repo, base="custom-base") == [{"check_id": "tagged-row"}]

    @staticmethod
    def _repo_with_baseline(tmp_path: Path, entries: list[dict]) -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _write_registry(repo, entries)
        sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", sha])
        return repo


class TestShardedRegistryReaders:
    """VP step 4: both the current-state reader (_current_registry_entries) and the baseline
    reader (_default_baseline_registry_entries) resolve the sharded layout, preserving the
    (plan_slug, check_id) join the implement-PR leg relies on."""

    fixture = _ImplementFixture()

    def test_current_reader_resolves_sharded_layout(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            [
                {
                    "check_id": "shard-check",
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "x",
                    "plan_slug": "p",
                    "graduated_at": "2026-08-24",
                }
            ],
        )
        rows = _current_registry_entries(tmp_path)
        assert [r["check_id"] for r in rows] == ["shard-check"]
        assert (tmp_path / "config" / "agent" / "verification_registry" / "entries" / "shard-check.yaml").exists()

    def test_current_reader_raises_loud_on_malformed_shard(self, tmp_path: Path) -> None:
        entries_dir = tmp_path / "config" / "agent" / "verification_registry" / "entries"
        entries_dir.mkdir(parents=True)
        (entries_dir / "bad-check.yaml").write_text("{broken yaml: [", encoding="utf-8")
        with pytest.raises(GraduationError):
            _current_registry_entries(tmp_path)

    def test_baseline_reader_resolves_sharded_layout_at_ref(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _write_registry(
            repo,
            [
                {
                    "check_id": "baseline-shard-check",
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "x",
                    "plan_slug": "p",
                    "graduated_at": "2026-08-24",
                }
            ],
        )
        sha = _commit_all(repo, "base with sharded registry")
        _git(repo, ["update-ref", "refs/remotes/origin/main", sha])
        rows = _default_baseline_registry_entries(repo)
        assert [r["check_id"] for r in rows] == ["baseline-shard-check"]

    def test_implement_pr_leg_join_survives_sharding(self, tmp_path: Path) -> None:
        cid = "sharded-join-check"
        slug = "gc-sharded-join"
        repo, rel = self.fixture.build(
            tmp_path,
            slug,
            [_step(1, graduation="graduate", graduation_check_id=cid)],
            registry_entries=[
                {
                    "check_id": cid,
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "scripts/example.py",
                    "plan_slug": slug,
                    "graduated_at": "2026-08-24",
                }
            ],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []
        assert (repo / "config" / "agent" / "verification_registry" / "entries" / f"{cid}.yaml").exists()


class TestContentKeyedResolution:
    """Resolution is content-keyed, not commit-message-keyed; also single-declaration + push-aware base."""

    fixture = _ImplementFixture()

    def test_checkpoint_only_commit_message_still_resolves_for_implement_leg(self, tmp_path: Path) -> None:
        """A checkpoint-only commit subject (no feat({slug}) match) must not block resolution."""
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-checkpoint-only",
            [_step(1, graduation="graduate", graduation_check_id="gc-checkpoint-only-check")],
            registry_entries=[],
            commit_message="chore: automated checkpoint",
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)

    def test_declaration_enforced_when_a_plan_resolves(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path, "gc-declared-enforced", [_step(1, graduation="not-applicable")], registry_entries=[]
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "declared_plans"

    def test_declaration_vacuous_when_plan_present_but_undeclared(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(repo, "gc-declared-vacuous", [_step(1)])
        _commit_all(repo, "add undeclared plan")

        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_vacuous_when_no_plan_in_diff(self) -> None:
        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=["scripts/foo.py"], root=Path("/nonexistent"))
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_skipped_when_base_unreachable(self, tmp_path: Path) -> None:
        rel = _write_plan(tmp_path, "gc-declared-skipped", [_step(1)])
        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []

    def test_registry_baseline_and_resolution_stay_correct_on_simulated_post_merge_main(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Both diff baselines must be push-aware (Decision 159): origin/main==HEAD here,
        GITHUB_EVENT_BEFORE names the true pre-merge commit."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        # The entries/ directory must already exist at the pre-merge commit (steady state once
        # this migration lands -- every reachable commit carries it) so the push-context base
        # resolves via branch (i), not entries_at_ref's branch (iii) fail-loud (a ref resolving
        # with NEITHER layout present, reserved for a genuinely pre-registry ref or a real bug).
        _write_registry(
            repo,
            [
                {
                    "check_id": "pre-existing-check",
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "scripts/pre_existing.py",
                    "plan_slug": "some-earlier-plan",
                    "graduated_at": "2026-08-01",
                }
            ],
        )
        before_sha = _commit_all(repo, "before merge")

        slug = "gc-post-merge-main"
        cid = "gc-post-merge-main-check"
        rel = _write_plan(
            repo, slug, [_step(1, graduation="graduate", graduation_check_id=cid)], {"implementation_declared": True}
        )
        _write_registry(
            repo,
            [
                {
                    "check_id": cid,
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "scripts/example.py",
                    "plan_slug": slug,
                    "graduated_at": "2026-08-17",
                }
            ],
        )
        after_sha = _commit_all(repo, "feature merged to main")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])  # origin/main == HEAD

        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.setenv("GITHUB_EVENT_BEFORE", before_sha)

        # De-vacuum (rec-3166 second defect): assert on the DERIVED base itself, not only on
        # failed == [] -- a wrong (real-repo) base would make every git show/diff fail inside
        # the fixture repo, which also happens to yield failed == [] for the wrong reason.
        assert _common.push_context_base(root=repo) == before_sha

        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        assert failed == []
