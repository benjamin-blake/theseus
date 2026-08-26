"""Tests for validate_verification_registry() (VF-06). Mirror of
scripts/checks/verification/validate_verification_registry.py -- STRUCTURAL REWRITE for the
Decision 176 re-grain (config/agent/verification_registry/entries/<check_id>.yaml shards, never
a flat registry.yaml). Merges TestVerificationRegistry, TestVerificationRegistryDifferential,
TestShardPlacement, TestFlatFileRejected, TestModifiedRecordReadmitted, and the module-level
test_registry_differential_skip_is_non_fatal / test_verification_registry_accepts_empty_file
(rec-2709 Wave 1)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts import verification_graduation
from scripts.checks.verification.validate_verification_registry import validate_verification_registry


def _write_shard(root: Path, entry: dict) -> Path:
    entries_dir = root / "config" / "agent" / "verification_registry" / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    path = entries_dir / f"{entry['check_id']}.yaml"
    path.write_text(yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")
    return path


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", message])
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


_BASE_FIELDS = {
    "primitive_slot": "grep_count",
    "guard_target": "scripts/foo.py",
    "plan_slug": "my-plan",
    "graduated_at": "2026-06-29",
}


class TestVerificationRegistry:
    """Tests for validate_verification_registry() in validate.py --pre tier."""

    def test_pass_with_no_shards(self, tmp_path: Path) -> None:
        (tmp_path / "config" / "agent" / "verification_registry" / "entries").mkdir(parents=True)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert not failed

    def test_fail_missing_entries_dir(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("entries/ not found" in f for f in failed)

    def test_fail_entry_not_a_mapping(self, tmp_path: Path) -> None:
        entries_dir = tmp_path / "config" / "agent" / "verification_registry" / "entries"
        entries_dir.mkdir(parents=True)
        (entries_dir / "just-a-string.yaml").write_text("just-a-string\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_invalid_yaml(self, tmp_path: Path) -> None:
        entries_dir = tmp_path / "config" / "agent" / "verification_registry" / "entries"
        entries_dir.mkdir(parents=True)
        (entries_dir / "broken.yaml").write_text("entries: [\n  - invalid: yaml: :", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("YAML parse error" in f for f in failed)

    def test_fail_missing_required_field(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "x", "primitive_slot": "grep_count"})
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_unknown_slot(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "x", **{**_BASE_FIELDS, "primitive_slot": "unknown_slot"}})
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_duplicate_check_id_declared_inside_a_second_file(self, tmp_path: Path) -> None:
        """Structurally rare (filename IS the primary key) but the schema check independently
        catches a duplicate check_id declared inside a differently-named file's content too."""
        entry = {"check_id": "dup", **_BASE_FIELDS}
        _write_shard(tmp_path, entry)
        entries_dir = tmp_path / "config" / "agent" / "verification_registry" / "entries"
        (entries_dir / "dup-again.yaml").write_text(yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_pass_valid_entry(self, tmp_path: Path) -> None:
        """Schema-valid entry with no check_spec: treated as pre-existing (not added/modified),
        so the VF-06 c2 differential does not fire (no check_spec means it can't be materialized)."""
        _write_shard(tmp_path, {"check_id": "my-check", **_BASE_FIELDS})
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.verification.validate_verification_registry._added_entries", return_value=[]),
            patch("scripts.checks.verification.validate_verification_registry._modified_entries", return_value=[]),
        ):
            validate_verification_registry(failed)
        assert not failed


class TestShardPlacement:
    """VP step 2: a shard whose filename does not equal its own check_id fails the gate."""

    def test_misplaced_record_fails_naming_the_mismatch(self, tmp_path: Path) -> None:
        entries_dir = tmp_path / "config" / "agent" / "verification_registry" / "entries"
        entries_dir.mkdir(parents=True)
        entry = {"check_id": "real-check-id", **_BASE_FIELDS}
        (entries_dir / "wrong-filename.yaml").write_text(yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any(
            "wrong-filename.yaml" in f and "real-check-id" in f and "filename does not equal check_id" in f for f in failed
        )

    def test_correctly_placed_record_passes_placement_leg(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "correct-check", **_BASE_FIELDS})
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert not any("filename does not equal" in f for f in failed)


class TestFlatFileRejected:
    """VP step 3: reappearance of the pre-migration flat registry.yaml fails the gate, even
    alongside a healthy entries/ directory."""

    def test_resurrected_flat_file_fails(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "fine-check", **_BASE_FIELDS})
        flat = tmp_path / verification_graduation.REGISTRY_DIR_REL / verification_graduation.LEGACY_FLAT_BASENAME
        flat.write_text("entries: []\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("has resurrected" in f for f in failed)

    def test_no_flat_file_passes_that_leg(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "fine-check", **_BASE_FIELDS})
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert not any("has resurrected" in f for f in failed)


class TestModifiedRecordReadmitted:
    """VP step 6: closes the silent-modification hole -- a record whose check_spec changes
    while its check_id stays the same IS selected for differential re-admission, not only novel
    check_ids."""

    def test_unit_selection_by_parsed_mapping(self, tmp_path: Path) -> None:
        """_modified_entries compares PARSED MAPPINGS, never bytes/text."""
        from scripts.checks.verification.validate_verification_registry import _modified_entries

        baseline = [{"check_id": "mod-check", "primitive_slot": "command_exit_zero", "check_spec": {"command": ["true"]}}]
        current = [
            {
                "check_id": "mod-check",
                "primitive_slot": "command_exit_zero",
                "check_spec": {"command": ["bash", "-c", "exit 0"]},
            }
        ]
        with (
            patch("scripts.verification_graduation.entries_at_ref", return_value=baseline),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            modified = _modified_entries(current)
        assert [e["check_id"] for e in modified] == ["mod-check"]

    def test_unmodified_record_is_not_selected(self, tmp_path: Path) -> None:
        from scripts.checks.verification.validate_verification_registry import _modified_entries

        record = {"check_id": "same-check", "primitive_slot": "command_exit_zero", "check_spec": {"command": ["true"]}}
        with (
            patch("scripts.verification_graduation.entries_at_ref", return_value=[record]),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            modified = _modified_entries([dict(record)])
        assert modified == []

    def test_modified_entries_skips_non_dict_current_entry(self, tmp_path: Path) -> None:
        from scripts.checks.verification.validate_verification_registry import _modified_entries

        with (
            patch("scripts.verification_graduation.entries_at_ref", return_value=[]),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            assert _modified_entries(["not-a-mapping"]) == []

    def test_added_and_modified_entries_empty_when_ref_unreachable(self, tmp_path: Path) -> None:
        """Mirrors each other: neither helper claims added/modified when origin/main does not
        resolve -- the caller's own reachability check decides whether to skip the leg."""
        from scripts.checks.verification.validate_verification_registry import _added_entries, _modified_entries

        with (
            patch("scripts.verification_graduation.entries_at_ref", return_value=None),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            assert _added_entries([{"check_id": "x"}]) == []
            assert _modified_entries([{"check_id": "x"}]) == []

    def test_tautological_edit_selected_and_rejected_end_to_end(self, tmp_path: Path) -> None:
        """A fixture replacing a record's check_spec with a tautology (bash -c 'exit 0') is
        selected for differential re-admission and rejected as non-discriminating."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        original = {
            "check_id": "mod-e2e-check",
            "primitive_slot": "command_exit_zero",
            "guard_target": "scripts/foo.py",
            "plan_slug": "my-plan",
            "graduated_at": "2026-08-24",
            "check_spec": {"command": ["bash", "-c", "test -f scripts/foo.py"]},
        }
        path = repo / "config" / "agent" / "verification_registry" / "entries" / "mod-e2e-check.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")
        base_sha = _commit_all(repo, "base: genuine check_spec")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        tautological = dict(original, check_spec={"command": ["bash", "-c", "exit 0"]})
        path.write_text(yaml.safe_dump(tautological, sort_keys=False), encoding="utf-8")
        _commit_all(repo, "neuter check_spec to a tautology")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", repo):
            validate_verification_registry(failed)
        assert any("not admitted" in f and "mod-e2e-check" in f for f in failed), failed


class TestVerificationRegistryDifferential:
    """VP step 6 (added leg, VF-06 c2): validate_verification_registry's added-entry
    differential branch.

    The differential mechanism itself (real worktree revert) is covered by
    tests/verification_graduation/test_differential.py; here we drive the validate.py wiring
    with a stubbed scripts.verification_graduation to verify the diff-gating, message shape, and
    fail-loud error surfacing.
    """

    def test_added_entry_admitted(self, tmp_path: Path) -> None:
        _write_shard(
            tmp_path,
            {
                "check_id": "new-check",
                **_BASE_FIELDS,
                "check_spec": {"path": "scripts/foo.py", "pattern": "x", "operator": "eq", "count": 1},
            },
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.origin_main_reachable", return_value=True),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "new-check"}],
            ),
            patch("scripts.checks.verification.validate_verification_registry._modified_entries", return_value=[]),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=verification_graduation.DifferentialOutcome(
                    admitted=True, reason="admitted -- fails on origin/main, passes on HEAD"
                ),
            ),
        ):
            validate_verification_registry(failed)
        assert not failed

    def test_added_entry_not_admitted_tautological(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "taut", **{**_BASE_FIELDS, "guard_target": "x", "plan_slug": "p"}})
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.origin_main_reachable", return_value=True),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "taut"}],
            ),
            patch("scripts.checks.verification.validate_verification_registry._modified_entries", return_value=[]),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=verification_graduation.DifferentialOutcome(
                    admitted=False, reason="not admitted -- revert did not produce FAIL (tautological)"
                ),
            ),
        ):
            validate_verification_registry(failed)
        assert any("not admitted" in f for f in failed), failed

    def test_no_added_entry_is_noop(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "x", **{**_BASE_FIELDS, "guard_target": "y", "plan_slug": "p"}})
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.origin_main_reachable", return_value=True),
            patch("scripts.checks.verification.validate_verification_registry._added_entries", return_value=[]),
            patch("scripts.checks.verification.validate_verification_registry._modified_entries", return_value=[]),
            patch("scripts.verification_graduation.run_differential") as mock_diff,
        ):
            validate_verification_registry(failed)
        assert not failed
        mock_diff.assert_not_called()

    def test_graduation_error_surfaces_as_failure(self, tmp_path: Path) -> None:
        _write_shard(tmp_path, {"check_id": "bad", **{**_BASE_FIELDS, "guard_target": "y", "plan_slug": "p"}})
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.origin_main_reachable", return_value=True),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "bad"}],
            ),
            patch("scripts.checks.verification.validate_verification_registry._modified_entries", return_value=[]),
            patch(
                "scripts.verification_graduation.run_differential",
                side_effect=verification_graduation.GraduationError("worktree add failed"),
            ),
        ):
            validate_verification_registry(failed)
        assert any("error --" in f for f in failed), failed


def test_registry_differential_skip_is_non_fatal(tmp_path: Path) -> None:
    """rec-2655: a skipped DifferentialOutcome (importorskip-guarded, fast-tier-excluded node)
    does not append to failed -- distinct from a genuine not-admitted rejection."""
    _write_shard(
        tmp_path,
        {
            "check_id": "guarded",
            "primitive_slot": "test_selector",
            "guard_target": "scripts/foo.py",
            "plan_slug": "my-plan",
            "graduated_at": "2026-07-04",
            "check_spec": {"node_id": "tests/test_foo.py::test_x"},
        },
    )
    failed: list[str] = []
    with (
        patch("scripts.checks._common.ROOT", tmp_path),
        patch("scripts.checks._common.origin_main_reachable", return_value=True),
        patch(
            "scripts.checks.verification.validate_verification_registry._added_entries",
            return_value=[{"check_id": "guarded"}],
        ),
        patch("scripts.checks.verification.validate_verification_registry._modified_entries", return_value=[]),
        patch(
            "scripts.verification_graduation.run_differential",
            return_value=verification_graduation.DifferentialOutcome(
                admitted=False,
                skipped=True,
                reason="skipped -- node in importorskip-guarded fast-tier-excluded file (duckdb)",
            ),
        ),
    ):
        validate_verification_registry(failed)
    assert failed == []


def test_verification_registry_accepts_empty_file(tmp_path: Path) -> None:
    """VP step 5: registry guard accepts an empty well-formed entries/ directory."""
    (tmp_path / "config" / "agent" / "verification_registry" / "entries").mkdir(parents=True)
    failed: list = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_verification_registry(failed)
    assert not failed
