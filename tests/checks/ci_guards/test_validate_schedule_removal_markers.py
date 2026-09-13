"""Mirror test for scripts/checks/ci_guards/validate_schedule_removal_markers.py (LSA-01 leg c).

Every fixture is a synthetic git repository built fresh in tmp_path, mirroring
tests/checks/verification/test_validate_tier_demotion_markers.py's own
_git/_write_files/refs-remotes-origin-main idiom -- the gate reads only git and disk, so a
committed snapshot fixture would not exercise its real oracles.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks import _common, registry
from scripts.checks.ci_guards import validate_schedule_removal_markers as gate

_FAKE_DECISIONS_MD = (
    "## Decision 501: Authorizes fixture.yml's schedule removal for testing (Decided)\n\n"
    "**Status:** Decided\n**Date:** 2026-01-01\n"
    "**Decision:** Authorizes fixture.yml's schedule removal.\n\n---\n\n"
    "## Decision 502: Skeleton-key decoy, mentions only .github/workflows generically (Decided)\n\n"
    "**Status:** Decided\n**Date:** 2026-01-01\n"
    "**Decision:** Governs .github/workflows broadly, names no specific workflow file.\n\n---\n"
)


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _workflow(*, schedule: bool, commented: bool = False, marker: str | None = None, cron: str = "0 * * * *") -> str:
    marker_line = f"# {marker}\n" if marker else ""
    if schedule:
        on_block = f'on:\n  schedule:\n    - cron: "{cron}"\n  workflow_dispatch: {{}}\n'
    elif commented:
        on_block = f'on:\n  # schedule:\n  #   - cron: "{cron}"\n  workflow_dispatch: {{}}\n'
    else:
        on_block = "on:\n  workflow_dispatch: {}\n"
    jobs_block = "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    return f"{marker_line}name: Fixture\n{on_block}{jobs_block}"


def _repo(
    tmp_path: Path,
    workflow_rel: str,
    base_text: str | None,
    head_text: str | None,
    *,
    extra_base: dict[str, str] | None = None,
    extra_head: dict[str, str] | None = None,
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])

    base_files = dict(extra_base or {})
    base_files["docs/DECISIONS.md"] = _FAKE_DECISIONS_MD
    if base_text is not None:
        base_files[workflow_rel] = base_text
    _write_files(repo, base_files)
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", "base"])
    base_sha = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

    if base_text is not None and head_text is None:
        (repo / workflow_rel).unlink()
    for rel in extra_base or {}:
        if rel not in (extra_head or {}):
            (repo / rel).unlink(missing_ok=True)

    head_files = dict(extra_head or {})
    if head_text is not None:
        head_files[workflow_rel] = head_text
    _write_files(repo, head_files)
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", "head", "--allow-empty"])
    return repo


def _run(repo: Path) -> list[str]:
    failed: list[str] = []
    with patch.object(_common, "ROOT", repo):
        gate.validate_schedule_removal_markers(failed, root=repo)
    return failed


_REL = ".github/workflows/fixture.yml"


class TestKnownBad:
    """VP step 2: a removed schedule block, a commented-out one, and a deleted whole workflow
    file each gate without a marker; each passes with a valid authorized marker except the
    whole-file deletion, which has no head line to carry one."""

    def test_removed_schedule_block_unmarked_fails(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), _workflow(schedule=False))
        failed = _run(repo)
        assert failed != []

    def test_removed_schedule_block_with_authorized_marker_passes(self, tmp_path: Path) -> None:
        head = _workflow(schedule=False, marker="schedule-removal-approved: dec-501 removed per Decision 501")
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), head)
        assert _run(repo) == []

    def test_commented_out_schedule_block_unmarked_fails(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), _workflow(schedule=False, commented=True))
        assert _run(repo) != []

    def test_commented_out_schedule_block_with_authorized_marker_passes(self, tmp_path: Path) -> None:
        head = _workflow(schedule=False, commented=True, marker="schedule-removal-approved: dec-501 removed per Decision 501")
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), head)
        assert _run(repo) == []

    def test_deleted_whole_workflow_file_fails_with_no_marker_escape(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), None)
        failed = _run(repo)
        assert failed != []

    def test_marker_citing_a_skeleton_key_decision_still_fails(self, tmp_path: Path) -> None:
        """dec-502 mentions `.github/workflows` generically, never this file's own bare name --
        the plan's own worked example of the skeleton-key refusal at filename level."""
        head = _workflow(schedule=False, marker="schedule-removal-approved: dec-502 generic mention only")
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), head)
        assert _run(repo) != []

    def test_marker_with_empty_reason_never_counts(self, tmp_path: Path) -> None:
        head = _workflow(schedule=False, marker="schedule-removal-approved: dec-501")
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), head)
        assert _run(repo) != []

    def test_deleted_non_scheduled_workflow_is_free(self, tmp_path: Path) -> None:
        """A workflow with no schedule at base has nothing to gate on deletion."""
        repo = _repo(tmp_path, _REL, _workflow(schedule=False), None)
        assert _run(repo) == []


class TestTighteningFree:
    """VP step 3: adding a schedule passes unmarked; the replicated on:.schedule parse agrees
    with sensor_liveness.derive_scheduled_peers on the live tree; the guard's own module imports
    nothing from scripts.convergence_health."""

    def test_adding_a_schedule_is_free(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _REL, _workflow(schedule=False), _workflow(schedule=True))
        assert _run(repo) == []

    def test_brand_new_scheduled_workflow_is_free(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _REL, None, _workflow(schedule=True))
        assert _run(repo) == []

    def test_replicated_parse_agrees_with_sensor_liveness_on_the_live_tree(self) -> None:
        from scripts.convergence_health import sensor_liveness

        live_peers = sensor_liveness.derive_scheduled_peers(require_non_empty=False)
        workflows_dir = _common.ROOT / ".github" / "workflows"
        for path in sorted(workflows_dir.glob("*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            replicated = gate._schedule_present(data)
            assert replicated == (path.name in live_peers), path.name

    def test_guard_module_imports_nothing_from_convergence_health(self) -> None:
        tree = ast.parse(Path(inspect.getfile(gate)).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any("convergence_health" in alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module and "convergence_health" in node.module)


class TestInternalHelperEdgeCases:
    """Defensive-branch coverage the git-repo fixtures above never reach."""

    def test_schedule_present_non_dict_input_is_false(self) -> None:
        assert gate._schedule_present(None) is False
        assert gate._schedule_present("not a dict") is False

    def test_schedule_present_bare_on_key_normalisation(self) -> None:
        """PyYAML parses a bare `on:` mapping key as Python `True` -- data.get(True, {}) covers it."""
        data = {True: {"schedule": [{"cron": "0 * * * *"}]}}
        assert gate._schedule_present(data) is True

    def test_schedule_present_non_list_schedule_is_false(self) -> None:
        assert gate._schedule_present({"on": {"schedule": "not-a-list"}}) is False

    def test_schedule_present_entries_without_cron_are_false(self) -> None:
        assert gate._schedule_present({"on": {"schedule": [{"no_cron": True}, "not-a-dict"]}}) is False

    def test_extract_marker_no_marker_line_returns_none(self) -> None:
        assert gate._extract_marker("name: x\non:\n  workflow_dispatch: {}\n") == (None, None)

    def test_state_extractor_unparseable_yaml_reads_as_no_schedule(self) -> None:
        extractor = gate._state_extractor_for("fixture.yml")
        entry = extractor("not: valid: yaml: [")["fixture.yml"]
        assert entry.state is False

    def test_state_extractor_empty_text_reads_as_no_schedule(self) -> None:
        entry = gate._state_extractor_for("fixture.yml")("")["fixture.yml"]
        assert entry.state is False

    def test_weakened_rejects_non_bool_input(self) -> None:
        with pytest.raises(TypeError):
            gate.weakened(1, 2)

    def test_gates_deletion_rejects_non_bool_input(self) -> None:
        with pytest.raises(TypeError):
            gate.gates_deletion("not-a-bool")

    def test_gates_deletion_true_only_when_base_scheduled(self) -> None:
        assert gate.gates_deletion(True) is True
        assert gate.gates_deletion(False) is False

    def test_weakened_transitions(self) -> None:
        assert gate.weakened(True, False) is True
        assert gate.weakened(True, True) is False
        assert gate.weakened(False, True) is False
        assert gate.weakened(False, False) is False

    def test_head_workflow_paths_missing_dir_is_empty(self, tmp_path: Path) -> None:
        assert gate._head_workflow_paths(tmp_path) == []

    def test_base_workflow_paths_non_git_directory_is_empty(self, tmp_path: Path) -> None:
        assert gate._base_workflow_paths(tmp_path) == []

    def test_batched_base_reader_empty_paths_returns_blank_reader(self) -> None:
        reader = gate._batched_base_reader(Path("."), [])
        assert reader is not None
        assert reader("anything") == ""

    def test_batched_base_reader_failed_subprocess_returns_no_reader(self) -> None:
        fake_result = subprocess.CompletedProcess(["git", "cat-file", "--batch"], 128, b"", b"fatal")
        with patch.object(_common, "run", return_value=fake_result):
            assert gate._batched_base_reader(Path("."), ["a"]) is None

    def test_batched_base_reader_truncated_output_on_a_successful_call_reads_blank(self) -> None:
        """Record robustness, NOT a fail-open: rc is zero, so a newline-less record is an empty blob."""
        with patch.object(_common, "run", return_value=subprocess.CompletedProcess(["git"], 0, b"no newline here", b"")):
            reader = gate._batched_base_reader(Path("."), ["a"])
        assert reader is not None
        assert reader("a") == ""


class TestGitProbesFailLoudNeverOpen:
    """Decision 55: an unavailable oracle must SKIP, never read as an affirmative pass."""

    def test_no_origin_main_ref_skips_rather_than_passing_silently(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), _workflow(schedule=False))
        _git(repo, ["update-ref", "-d", "refs/remotes/origin/main"])
        failed: list[str] = []
        with registry.outcome_scope("validate_schedule_removal_markers"):
            with patch.object(_common, "ROOT", repo):
                gate.validate_schedule_removal_markers(failed, root=repo)
            declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None and declaration.kind == "skipped"
        assert "SKIP" in capsys.readouterr().out

    def test_cat_file_failure_skips_instead_of_reading_an_empty_base(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _REL, _workflow(schedule=True), _workflow(schedule=False))
        original_run = _common.run

        def _selective(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if cmd[:3] == ["git", "cat-file", "--batch"]:
                return subprocess.CompletedProcess(cmd, 128, b"", b"fatal")
            return original_run(cmd, **kwargs)

        failed: list[str] = []
        with patch.object(_common, "ROOT", repo), patch.object(_common, "run", _selective):
            with registry.outcome_scope("validate_schedule_removal_markers"):
                gate.validate_schedule_removal_markers(failed, root=repo)
                declaration = registry.pop_declaration()
        assert failed == []
        assert declaration is not None and declaration.kind == "skipped"


class TestCleanOnLiveFleet:
    """Clean on day one, no grandfather hook."""

    def test_zero_violations_against_the_real_tree_and_base_ref(self) -> None:
        failed: list[str] = []
        gate.validate_schedule_removal_markers(failed)
        assert failed == []

    def test_examined_count_covers_every_live_workflow(self) -> None:
        failed: list[str] = []
        with registry.outcome_scope("validate_schedule_removal_markers"):
            gate.validate_schedule_removal_markers(failed)
            declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        workflows_dir = _common.ROOT / ".github" / "workflows"
        assert declaration.count == len(list(workflows_dir.glob("*.yml")))
