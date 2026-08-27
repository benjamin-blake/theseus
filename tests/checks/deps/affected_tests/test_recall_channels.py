"""Derivation-level tests for the recall channels added to close the measured `no-edge` escape
class: the mirror map promoted to protected, extra-tree .py data-edge candidates, prose-mention
edges, and directory-reference edges for files whose add/delete changes a scanned directory's
membership.

Primitive-level coverage of the same channels lives in tests/checks/deps/test_affected_channels.py.
Real-repo cases replay the exact escapes recorded in the CI-RCA corpus, so they are premise-checked
(an assertion that the fixture they depend on still exists) rather than silently vacuous.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.deps import affected_tests as at
from tests.fixtures.affected_tests_helpers import write_file as _write


class TestMirrorMapIsProtected:
    """The mirror map is a curated, exact source<->test mapping -- Decision 135 permits capping
    only the TRANSITIVE import-closure residue, so a mirror hit must never be deferred."""

    def test_mirror_hit_survives_a_fully_consumed_cap(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_edited.py", "def test_edited():\n    assert True\n")
        _write(tmp_path, "scripts/zzz_mirror_source.py", "def something():\n    pass\n")
        _write(tmp_path, "tests/test_zzz_mirror_source.py", "def test_x():\n    assert True\n")
        diff = [("M", "tests/test_edited.py"), ("M", "scripts/zzz_mirror_source.py")]

        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=1)

        manifest = result["manifest"]
        assert "tests/test_zzz_mirror_source.py" in result["selected"]
        assert manifest["provenance"]["tests/test_zzz_mirror_source.py"] == "mirror_map"
        assert manifest["deferred"] == []

    def test_promotion_does_not_evict_residue_the_cap_would_have_kept(self, tmp_path: Path) -> None:
        """Strict additivity: promoting a channel into the protected set must never cost the
        transitive residue a slot. The residue's budget is now fixed at cap regardless of how
        large protected grows (_residue_keep_set rule 1), so the promoted mirror hit is added
        ON TOP of -- never in place of -- the residue the previous revision kept."""
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        for name in ("aaa", "bbb", "ccc"):
            _write(tmp_path, f"tests/test_{name}_transitive.py", "from scripts.mid import mid\n\ndef test_x():\n    mid()\n")
        _write(tmp_path, "scripts/zzz_mirror_source.py", "def something():\n    pass\n")
        _write(tmp_path, "tests/test_zzz_mirror_source.py", "def test_x():\n    assert True\n")
        diff = [("M", "scripts/base.py"), ("M", "scripts/zzz_mirror_source.py")]

        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=2)

        # The pre-promotion keep-set (mirror hit as residue, one transitive slot left) is a strict
        # SUBSET of what is selected now -- nothing it ran has been deferred.
        assert {"tests/test_zzz_mirror_source.py", "tests/test_aaa_transitive.py"} <= set(result["selected"])
        assert set(result["selected"]) == {
            "tests/test_zzz_mirror_source.py",
            "tests/test_aaa_transitive.py",
            "tests/test_bbb_transitive.py",
            "tests/test_ccc_transitive.py",
        }
        assert result["manifest"]["deferred"] == []

    def test_new_source_module_selects_its_conventional_mirror_test(self, tmp_path: Path) -> None:
        """`A scripts/zzz_new.py` selected ZERO tests before this channel was protected."""
        _write(tmp_path, "scripts/zzz_new.py", "def something():\n    pass\n")
        _write(tmp_path, "tests/test_zzz_new.py", "def test_x():\n    assert True\n")

        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests([("A", "scripts/zzz_new.py")], repo_root=tmp_path)

        assert result["selected"] == ["tests/test_zzz_new.py"]
        assert result["manifest"]["provenance"]["tests/test_zzz_new.py"] == "mirror_map"


class TestExtraTreePythonCandidates:
    """A .py file outside src/|scripts/|tests/ was skipped by the data-edge candidate filter
    outright (the filter admitted only DELETED .py), so it selected zero tests."""

    def test_hook_edit_selects_the_test_quoting_its_basename(self, tmp_path: Path) -> None:
        _write(tmp_path, ".claude/hooks/edit_scope_guard.py", "def main():\n    pass\n")
        _write(
            tmp_path,
            "tests/test_edit_scope_guard.py",
            'HOOK = ROOT / ".claude" / "hooks" / "edit_scope_guard.py"\n\ndef test_x():\n    assert HOOK\n',
        )
        result = at.derive_affected_tests([("M", ".claude/hooks/edit_scope_guard.py")], repo_root=tmp_path)

        assert result["selected"] == ["tests/test_edit_scope_guard.py"]
        assert result["manifest"]["provenance"]["tests/test_edit_scope_guard.py"] == "data_edge"

    def test_first_party_python_is_still_not_a_data_edge_candidate(self, tmp_path: Path) -> None:
        """Guards the additive claim from the other side: admitting extra-tree .py must not turn
        every changed src/scripts module into a basename-text candidate."""
        _write(tmp_path, "scripts/thing.py", "def run():\n    pass\n")
        _write(tmp_path, "tests/test_mentions_thing.py", '"""Covers thing.py end to end."""\n\ndef test_x():\n    pass\n')
        result = at.derive_affected_tests([("M", "scripts/thing.py")], repo_root=tmp_path)

        assert result["selected"] == []

    def test_real_repo_hook_change_selects_its_mirror_test(self) -> None:
        assert Path("tests/test_edit_scope_guard.py").exists(), "premise: the hook's mirror test still exists"
        result = at.derive_affected_tests([("M", ".claude/hooks/edit_scope_guard.py")])
        assert "tests/test_edit_scope_guard.py" in result["selected"]


class TestMentionChannel:
    """A word-boundary basename occurrence anywhere in a test's text counts, not only a whole
    quoted string -- the rec-2548 cluster escaped precisely on that distinction."""

    def test_docstring_only_mention_is_selected_and_tagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "config/thing.yaml", "a: 1\n")
        _write(
            tmp_path,
            "tests/test_prose_reader.py",
            '"""Cross-checks the loader against a raw scan of thing.yaml."""\n\ndef test_x():\n    assert True\n',
        )
        result = at.derive_affected_tests([("M", "config/thing.yaml")], repo_root=tmp_path)

        assert result["selected"] == ["tests/test_prose_reader.py"]
        assert result["manifest"]["provenance"]["tests/test_prose_reader.py"] == "data_edge_mention"

    def test_quoted_hit_keeps_the_precise_channel_provenance(self, tmp_path: Path) -> None:
        _write(tmp_path, "config/thing.yaml", "a: 1\n")
        _write(tmp_path, "tests/test_quoted_reader.py", 'CFG = "thing.yaml"\n\ndef test_x():\n    assert CFG\n')
        result = at.derive_affected_tests([("M", "config/thing.yaml")], repo_root=tmp_path)

        assert result["manifest"]["provenance"]["tests/test_quoted_reader.py"] == "data_edge"

    def test_longer_basename_does_not_false_positive(self, tmp_path: Path) -> None:
        _write(tmp_path, "config/registry.yaml", "a: 1\n")
        _write(tmp_path, "tests/test_other.py", '"""Reads source_registry.yaml only."""\n\ndef test_x():\n    pass\n')
        result = at.derive_affected_tests([("M", "config/registry.yaml")], repo_root=tmp_path)

        assert result["selected"] == []

    def test_real_repo_rec_2548_reproducer(self) -> None:
        """tests/test_rec_write_guidance.py names source_registry.yaml only in a docstring."""
        victim = "tests/test_rec_write_guidance.py"
        assert "source_registry.yaml" in Path(victim).read_text(encoding="utf-8"), "premise: the mention still exists"
        result = at.derive_affected_tests([("M", "config/agent/data_quality/source_registry.yaml")])
        assert victim in result["selected"]


class TestDirectoryReferenceChannel:
    """A file that is being added cannot be quoted anywhere yet, and a file that is being deleted
    stops being there to quote -- either way the surviving edge is to the tests that glob-scan the
    containing directory."""

    def test_added_workflow_selects_the_directory_scanning_test(self, tmp_path: Path) -> None:
        _write(tmp_path, ".github/workflows/zzz.yml", "name: Zzz\n")
        _write(
            tmp_path,
            "tests/test_workflow_inventory.py",
            'def test_x():\n    assert oracle(ROOT / ".github" / "workflows")\n',
        )
        result = at.derive_affected_tests([("A", ".github/workflows/zzz.yml")], repo_root=tmp_path)

        assert result["selected"] == ["tests/test_workflow_inventory.py"]
        assert result["manifest"]["provenance"]["tests/test_workflow_inventory.py"] == "directory_reference"

    def test_deleted_workflow_selects_the_directory_scanning_test(self, tmp_path: Path) -> None:
        """A retirement changes directory membership exactly as an addition does, and the deleted
        path's own precise channels cannot reach a test that names only the DIRECTORY."""
        _write(
            tmp_path,
            "tests/test_workflow_inventory.py",
            'def test_x():\n    assert oracle(ROOT / ".github" / "workflows")\n',
        )
        result = at.derive_affected_tests([("D", ".github/workflows/zzz.yml")], repo_root=tmp_path)

        assert result["selected"] == ["tests/test_workflow_inventory.py"]
        assert result["manifest"]["provenance"]["tests/test_workflow_inventory.py"] == "directory_reference"

    def test_modified_file_does_not_open_the_directory_channel(self, tmp_path: Path) -> None:
        """Scope guard: only MEMBERSHIP CHANGES (additions, deletions) alter what a
        directory-counting test observes -- an in-place edit does not."""
        _write(tmp_path, ".github/workflows/ci.yml", "name: CI\n")
        _write(
            tmp_path,
            "tests/test_workflow_inventory.py",
            'def test_x():\n    assert oracle(ROOT / ".github" / "workflows")\n',
        )
        result = at.derive_affected_tests([("M", ".github/workflows/ci.yml")], repo_root=tmp_path)

        assert result["selected"] == []

    def test_real_repo_added_workflow_and_contract_select_tests(self) -> None:
        workflow = at.derive_affected_tests([("A", ".github/workflows/zzz.yml")])
        contract = at.derive_affected_tests([("A", "docs/contracts/zzz-new.yaml")])
        assert len(workflow["selected"]) > 0
        assert len(contract["selected"]) > 0
        assert "tests/ci_rca/taxonomy/test_load_and_classify.py" in workflow["selected"]

    def test_real_repo_retired_workflow_selects_the_same_directory_scanner(self) -> None:
        """The escape this closed: retiring a workflow yml reached the directory-scanning cluster
        through no channel at all, so it selected only what the deleted path's own text matched."""
        victim = "tests/ci_rca/taxonomy/test_load_and_classify.py"
        assert Path(victim).exists(), "premise: the workflow-directory scanner still exists"
        result = at.derive_affected_tests([("D", ".github/workflows/zzz.yml")])
        assert victim in result["selected"]
        assert result["manifest"]["provenance"][victim] == "directory_reference"

    def test_real_repo_added_config_file_selects_scanners_not_the_word_config(self) -> None:
        """Precision for the one SINGLE-SEGMENT curated root: `config` is also an identifier and
        an English word. Every measured genuine config/ scanner (the structural size-governance
        class engine's three test modules, which spell the root `config/*.yaml`) stays selected;
        the git-subcommand and `tmp_path / "config"` fixture noise does not."""
        scanners = [
            "tests/checks/structural/test_size_limits.py",
            "tests/checks/structural/test__classify.py",
            "tests/checks/structural/test_budget_raises.py",
        ]
        noise = ["tests/checks/_common/test_primitives.py", "tests/checks/typing/test_mypy_baseline.py"]
        for path in scanners + noise:
            assert Path(path).exists(), f"premise: {path} still exists"
        selected = at.derive_affected_tests([("A", "config/zzz_new.yaml")])["selected"]

        assert set(scanners) <= set(selected)
        assert not set(noise) & set(selected)


class TestChannelObservability:
    """Every channel reports its own size in the manifest, not only a per-file provenance tag
    (a file hit by two channels is attributed once, so provenance alone under-counts)."""

    def test_manifest_channels_counts_every_channel(self, tmp_path: Path) -> None:
        _write(tmp_path, "config/thing.yaml", "a: 1\n")
        _write(tmp_path, "tests/test_edited.py", "def test_edited():\n    assert True\n")
        _write(
            tmp_path,
            "tests/test_prose_reader.py",
            '"""Cross-checks a raw scan of thing.yaml."""\n\ndef test_x():\n    assert True\n',
        )
        diff = [("M", "config/thing.yaml"), ("M", "tests/test_edited.py")]
        channels = at.derive_affected_tests(diff, repo_root=tmp_path)["manifest"]["channels"]

        assert channels["edited_set"] == 1
        assert channels["data_edge_mention"] == 1
        assert channels["data_edge"] == 0
        assert channels["directory_reference"] == 0
        assert set(channels) == set(at.CHANNEL_NAMES)

    def test_empty_diff_manifest_still_carries_channels(self, tmp_path: Path) -> None:
        channels = at.derive_affected_tests([], repo_root=tmp_path)["manifest"]["channels"]
        assert set(channels) == set(at.CHANNEL_NAMES)
        assert sum(channels.values()) == 0
