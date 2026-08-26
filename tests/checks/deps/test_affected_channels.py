"""Unit tests for scripts/checks/deps/affected_channels.py -- the three recall channels added
to the --pre affected-set derivation (extra-tree .py candidates, prose-mention data edges, and
directory-reference edges for newly added files).

Derivation-level (end-to-end through derive_affected_tests) coverage of the same channels lives
in tests/checks/deps/affected_tests/test_recall_channels.py; this module tests the primitives.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks.deps import affected_channels as ac


class TestIsExtraTreePy:
    """A .py file outside src/|scripts/|tests/ is a data-edge candidate (it has mirror tests
    that quote its basename, but no import-graph node and no dedicated channel)."""

    def test_repo_edge_python_files_are_extra_tree(self) -> None:
        assert ac.is_extra_tree_py("setup.py")
        assert ac.is_extra_tree_py(".claude/hooks/edit_scope_guard.py")
        assert ac.is_extra_tree_py(".claude/statusline.py")

    def test_first_party_trees_are_not_extra_tree(self) -> None:
        assert not ac.is_extra_tree_py("scripts/validate.py")
        assert not ac.is_extra_tree_py("src/common/config.py")
        assert not ac.is_extra_tree_py("tests/test_validate.py")

    def test_non_python_is_not_extra_tree(self) -> None:
        assert not ac.is_extra_tree_py("docs/DECISIONS.md")
        assert not ac.is_extra_tree_py(".github/workflows/ci.yml")


class TestMentionPattern:
    """Word-boundary basename occurrence ANYWHERE in the text -- docstring, comment, prose --
    not only as a whole quoted string (the rec-2548 cluster's escape shape)."""

    def test_matches_bare_docstring_mention(self) -> None:
        pattern = ac.mention_pattern("source_registry.yaml")
        assert pattern.search('"""An independent raw-text scan of source_registry.yaml -- not yaml.safe_load."""')

    def test_matches_path_prefixed_mention(self) -> None:
        pattern = ac.mention_pattern("source_registry.yaml")
        assert pattern.search("# reads config/agent/data_quality/source_registry.yaml at import time")

    def test_matches_quoted_token_too(self) -> None:
        assert ac.mention_pattern("ci.yml").search('WORKFLOW = "ci.yml"')

    def test_does_not_match_inside_a_longer_basename(self) -> None:
        pattern = ac.mention_pattern("registry.yaml")
        assert not pattern.search("source_registry.yaml")
        assert not pattern.search("my.registry.yaml")

    def test_does_not_match_a_longer_trailing_identifier(self) -> None:
        assert not ac.mention_pattern("ci.yml").search("ci.yml-backup")


class TestDirectoryReferencePattern:
    """A file being added cannot be quoted anywhere yet and a file being deleted stops being
    there to quote, so the edge that matters is the one to tests that scan its CONTAINING
    DIRECTORY -- in both the plain-literal and the pathlib segment-join spelling."""

    def test_matches_plain_posix_directory_literal(self) -> None:
        assert ac.directory_reference_pattern(".github/workflows").search('WORKFLOWS = ROOT / ".github/workflows"')

    def test_matches_pathlib_segment_join_idiom(self) -> None:
        """The real escaping test (tests/ci_rca/taxonomy/test_load_and_classify.py) writes
        ROOT / ".github" / "workflows" -- a plain path literal never appears in its text."""
        assert ac.directory_reference_pattern(".github/workflows").search('oracle(ROOT / ".github" / "workflows")')

    def test_matches_glob_expression(self) -> None:
        assert ac.directory_reference_pattern("docs/contracts").search('sorted(glob("docs/contracts/*.yaml"))')

    def test_matches_trailing_slash_directory_literal(self) -> None:
        assert ac.directory_reference_pattern("docs/contracts").search('assert "docs/contracts/" not in text')

    def test_does_not_match_a_specific_file_reference(self) -> None:
        pattern = ac.directory_reference_pattern("docs/contracts")
        assert not pattern.search('CONTRACT = "docs/contracts/check-manifest.yaml"')

    def test_does_not_match_a_specific_file_in_segment_join_form(self) -> None:
        """The same specific-file read, spelled the pathlib way. Both guarantees are documented
        for BOTH forms, and a closing quote is not a terminator when a `/ "..."` segment follows."""
        pattern = ac.directory_reference_pattern("docs/contracts")
        assert not pattern.search('CONTRACT = ROOT / "docs" / "contracts" / "check-manifest.yaml"')
        assert not pattern.search('CONTRACT = ROOT / "docs/contracts" / "check-manifest.yaml"')

    def test_does_not_match_a_longer_sibling_directory(self) -> None:
        assert not ac.directory_reference_pattern("config/agent").search('"config/agentic/x.yaml"')

    def test_does_not_match_a_nested_sibling_in_segment_join_form(self) -> None:
        """`ROOT / "x" / "docs" / "contracts"` is x/docs/contracts -- a nested sibling, exactly
        what the plain-literal form already rejects via its leading path-boundary lookbehind."""
        assert not ac.directory_reference_pattern("docs/contracts").search('P = ROOT / "x" / "docs" / "contracts"')
        assert not ac.directory_reference_pattern("config").search('P = ROOT / "docs" / "config/*.yaml"')


class TestSingleSegmentRootRequiresPathContext:
    """A single-segment root (`config`) is also an ordinary Python identifier and an ordinary
    English word, so a bare occurrence carries no directory signal at all: measured, the bare
    form put 67 test modules -- git subcommand strings, `tmp_path / "config"` fixtures, prose --
    into the never-capped PROTECTED set for one added config/ file."""

    def test_glob_and_trailing_slash_forms_still_match(self) -> None:
        """The two forms every measured genuine config/ scanner is written in -- the structural
        size-governance class engine's `include:` globs, and a `config/` path-prefix test."""
        pattern = ac.directory_reference_pattern("config")
        assert pattern.search('    include: ["config/*.yaml", "config/*.yml"]')
        assert pattern.search('assert "config/" not in source')

    def test_bare_identifier_and_prose_forms_do_not_match(self) -> None:
        pattern = ac.directory_reference_pattern("config")
        assert not pattern.search("config = load_config()")
        assert not pattern.search('_git(["config", "user.email", "test@example.com"])')
        assert not pattern.search('"""The lock reads no config and exposes no escape hatch."""')

    def test_pathlib_fixture_directory_does_not_match(self) -> None:
        """`tmp_path / "config"` builds a synthetic fixture tree and observes nothing about the
        repo's config/ directory; it is indistinguishable from a genuine `ROOT / "config"` scan,
        and zero genuine repo-root scanners of config/ are written that way."""
        pattern = ac.directory_reference_pattern("config")
        assert not pattern.search('(tmp_path / "config").mkdir(parents=True)')
        assert not pattern.search('config_dir = tmp_path / "config"')

    def test_multi_segment_roots_keep_the_bare_directory_form(self) -> None:
        """Anti-vacuity: the path-context requirement is scoped to SINGLE-segment roots -- a
        multi-segment root is already unambiguous, so both of its spellings must still match."""
        assert ac.directory_reference_pattern(".github/workflows").search('oracle(ROOT / ".github" / "workflows")')
        assert ac.directory_reference_pattern("docs/contracts").search('D = ROOT / "docs/contracts"')


class TestNewFileReferenceDirs:
    """Only MEMBERSHIP-CHANGING (A / untracked / D) non-.py files under a curated root."""

    def test_added_file_under_curated_root_yields_its_parent_dir(self) -> None:
        assert ac.new_file_reference_dirs([("A", ".github/workflows/zzz.yml")]) == [".github/workflows"]

    def test_untracked_file_counts_as_added(self) -> None:
        assert ac.new_file_reference_dirs([("??", "docs/contracts/zzz-new.yaml")]) == ["docs/contracts"]

    def test_nested_dir_under_curated_root_yields_the_nested_dir(self) -> None:
        assert ac.new_file_reference_dirs([("A", "config/agent/data_quality/zzz.yaml")]) == ["config/agent/data_quality"]

    def test_deleted_file_under_curated_root_yields_its_parent_dir(self) -> None:
        """A retired file changes what a glob-scanning validator observes exactly as much as a
        new one does -- measured, `D .github/workflows/<x>.yml` selected 2 test modules against
        the 16 the same path's addition selected."""
        assert ac.new_file_reference_dirs([("D", ".github/workflows/retired.yml")]) == [".github/workflows"]
        assert ac.new_file_reference_dirs([("D", "docs/contracts/x.yaml")]) == ["docs/contracts"]

    def test_modified_files_are_excluded(self) -> None:
        """A modification leaves directory membership untouched, so a directory-counting test
        observes nothing new -- the precise path/basename channels own that edge."""
        assert ac.new_file_reference_dirs([("M", ".github/workflows/ci.yml")]) == []

    def test_added_or_deleted_python_file_is_excluded(self) -> None:
        """A .py path already has its own channels (mirror map, import closure, and -- for a
        deletion -- the structural dotted-module-token edge)."""
        assert ac.new_file_reference_dirs([("A", "config/agent/zzz.py")]) == []
        assert ac.new_file_reference_dirs([("D", "config/agent/zzz.py")]) == []

    def test_added_file_outside_curated_roots_is_excluded(self) -> None:
        assert ac.new_file_reference_dirs([("A", "docs/plans/PLAN-zzz.yaml"), ("A", "zzz.md")]) == []

    def test_curated_roots_are_the_evidence_backed_tuple(self) -> None:
        assert ac.GLOB_SCANNED_DIRS == (".github/workflows", "docs/contracts", "config")


class TestScanTestTexts:
    """One shared read of tests/**/*.py -- every text channel rides this single pass."""

    def test_yields_relpath_and_text_skipping_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "tests" / "pkg").mkdir(parents=True)
        (tmp_path / "tests" / "pkg" / "test_a.py").write_text("body\n", encoding="utf-8")
        (tmp_path / "tests" / "__pycache__").mkdir()
        (tmp_path / "tests" / "__pycache__" / "test_b.py").write_text("cached\n", encoding="utf-8")
        assert list(ac.scan_test_texts(tmp_path)) == [("tests/pkg/test_a.py", "body\n")]

    def test_missing_tests_dir_yields_nothing(self, tmp_path: Path) -> None:
        assert list(ac.scan_test_texts(tmp_path)) == []

    def test_unreadable_entry_is_skipped_without_losing_its_siblings(self, tmp_path: Path) -> None:
        """A .py-suffixed directory is what rglob hands back for a stray build artifact; reading
        it raises OSError, and one such entry must not take the whole channel down."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "artifact.py").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("body\n", encoding="utf-8")
        assert list(ac.scan_test_texts(tmp_path)) == [("tests/test_a.py", "body\n")]


class TestScanReferenceChannels:
    """The three text channels are disjoint by construction: a precise hit is never re-reported
    as a mention hit (precision wins), and the directory channel is independent of both."""

    def _repo(self, tmp_path: Path, **files: str) -> Path:
        (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (tmp_path / "tests" / f"{name}.py").write_text(text, encoding="utf-8")
        return tmp_path

    def test_precise_hit_wins_over_mention_hit(self, tmp_path: Path) -> None:
        self._repo(tmp_path, test_quoted='CFG = "thing.yaml"\n', test_prose='"""reads thing.yaml here."""\n')
        precise, mention, dirref = ac.scan_reference_channels(
            tmp_path,
            path_literals=["config/thing.yaml"],
            quoted_patterns=[re.compile(r"['\"]([^'\"]*/)?thing\.yaml['\"]")],
            mention_basenames=["thing.yaml"],
            directory_paths=[],
        )
        assert precise == {"tests/test_quoted.py"}
        assert mention == {"tests/test_prose.py"}
        assert dirref == set()

    def test_directory_channel_is_independent(self, tmp_path: Path) -> None:
        self._repo(tmp_path, test_dir_scanner='D = ROOT / ".github/workflows"\n')
        precise, mention, dirref = ac.scan_reference_channels(
            tmp_path,
            path_literals=[],
            quoted_patterns=[],
            mention_basenames=[],
            directory_paths=[".github/workflows"],
        )
        assert (precise, mention) == (set(), set())
        assert dirref == {"tests/test_dir_scanner.py"}
