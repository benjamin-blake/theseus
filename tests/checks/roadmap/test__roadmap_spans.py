"""Tests for the pure span-attribution helper. Mirror of
scripts/checks/roadmap/_roadmap_spans.py.

The 40-commit properties are driven from the CHECKED-IN fixture
(tests/fixtures/roadmap_touched_items.json), never from live git history -- main-validate checks
out at fetch-depth 2, where those commits' parents do not exist.
"""

from __future__ import annotations

import ast
import difflib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

from scripts.checks.roadmap import _roadmap_spans
from scripts.checks.roadmap._roadmap_spans import (
    ChangedLines,
    ItemSpan,
    attribute,
    changed_lines,
    item_spans,
    legacy_regex_item_ids,
    touched_item_ids,
)
from tests.fixtures.roadmap_touched_items import known_false_attributions, load_fixture

_SYNTHETIC = "\n".join(
    [
        "document:",
        "  id: synthetic",
        "candidate_decisions:",
        "  - id: CD.1",
        "    state: ratified",
        "tier_items:",
        "  - id: T1.1",
        "    name: first",
        "    exit_criteria:",
        "      - id: c1",
        "        text: nested",
        "  - id: T1.2",
        "    name: second",
        "cross_tier_gates:",
        "  - id: G1",
        "",
    ]
)


_SECTIONED = "\n".join(
    [
        "tier_items:",
        "  - id: T1.1",
        "    name: first",
        "",
        "  # ----- T2: second tier -----",
        "  - id: T2.1",
        "    name: second",
        "",
        "cross_tier_gates:",
        "  - id: G1",
        "",
    ]
)


def _diff(pre: str, post: str) -> str:
    """A unified diff of two in-memory images, in the shape git emits."""
    return "\n".join(difflib.unified_diff(pre.splitlines(), post.splitlines(), lineterm="")) + "\n"


def _edit_line(text: str, index: int, replacement: str) -> str:
    """Return `text` with line `index` replaced."""
    lines = text.splitlines()
    lines[index] = replacement
    return "\n".join(lines) + "\n"


class TestFixtureAttribution:
    """The core property: the span detector reproduces every stored expectation."""

    def test_every_stored_expectation_reproduces_exactly(self) -> None:
        rows = load_fixture()
        bad = [
            (row.commit, sorted(touched_item_ids(row.pre_spans, row.post_spans, row.changed)), row.expected)
            for row in rows
            if sorted(touched_item_ids(row.pre_spans, row.post_spans, row.changed)) != row.expected
        ]

        assert bad == []

    def test_the_fixture_population_is_the_declared_forty_commits(self) -> None:
        assert len(load_fixture()) == 40

    def test_the_span_attribution_contains_every_legacy_true_positive(self) -> None:
        """Decision 181 non-weakening: nothing the legacy detector got right is lost."""
        rows = load_fixture()

        lost = {
            (row.commit, item_id)
            for row in rows
            for item_id in set(row.legacy_true_positives) - touched_item_ids(row.pre_spans, row.post_spans, row.changed)
        }

        assert lost == set()

    def test_the_stored_expectations_are_not_all_empty(self) -> None:
        """Discrimination: an all-empty expectation set would make the equality above vacuous."""
        assert sum(len(row.expected) for row in load_fixture()) > 0


class TestLegacyResidueIsEnumerated:
    """Every legacy-named real tier_item outside the span attribution is curated by name."""

    @staticmethod
    def _consumed(row) -> set[str]:  # type: ignore[no-untyped-def]
        """The legacy raw matches filtered to real tier_item ids on EITHER image -- a deliberate
        superset of the live filter, which tests post-image ids only."""
        return set(row.legacy_raw) & ({s.item_id for s in row.pre_spans} | {s.item_id for s in row.post_spans})

    def test_residue_equals_the_curated_set(self) -> None:
        rows = load_fixture()
        named = {(commit, item_id) for commit, item_id, _mechanism in known_false_attributions()}

        residue = {
            (row.commit, item_id)
            for row in rows
            for item_id in self._consumed(row) - touched_item_ids(row.pre_spans, row.post_spans, row.changed)
        }

        assert residue == named

    def test_the_curated_set_is_non_empty_and_every_entry_names_a_mechanism(self) -> None:
        triples = known_false_attributions()

        assert triples
        assert all(mechanism.strip() for _commit, _item_id, mechanism in triples)

    def test_the_legacy_detector_is_strictly_lossy_over_the_population(self) -> None:
        rows = load_fixture()

        missed = sum(len(set(row.expected) - set(row.legacy_raw)) for row in rows)

        assert missed > 0
        assert sum(len(row.expected) for row in rows) > sum(len(row.legacy_true_positives) for row in rows)


class TestBlockScoping:
    """item_spans is scoped to ONE top-level block, at both boundaries."""

    def test_nested_exit_criterion_ids_are_never_tier_item_ids(self) -> None:
        assert "c1" not in {span.item_id for span in item_spans(_SYNTHETIC)}

    def test_candidate_decision_ids_are_never_tier_item_ids(self) -> None:
        assert "CD.1" not in {span.item_id for span in item_spans(_SYNTHETIC)}
        assert [span.item_id for span in item_spans(_SYNTHETIC, "candidate_decisions")] == ["CD.1"]

    def test_an_edit_below_the_last_tier_item_attributes_to_nothing(self) -> None:
        """TRAILING boundary: a cross_tier_gates edit must not leak into the last tier_item."""
        post = _edit_line(_SYNTHETIC, 14, "  - id: G2")

        assert attribute(_SYNTHETIC, post, _diff(_SYNTHETIC, post)) == set()

    def test_an_edit_above_the_block_attributes_to_nothing(self) -> None:
        """LEADING boundary: a candidate_decisions edit is outside every tier_item span."""
        post = _edit_line(_SYNTHETIC, 4, "    state: superseded")

        assert attribute(_SYNTHETIC, post, _diff(_SYNTHETIC, post)) == set()

    def test_an_absent_block_yields_no_spans(self) -> None:
        assert item_spans("document:\n  id: x\n") == []

    def test_a_block_running_to_end_of_file_ends_at_the_last_line(self) -> None:
        text = "tier_items:\n  - id: T0.1\n    name: only\n"

        assert item_spans(text) == [ItemSpan(item_id="T0.1", start=1, end=2)]


class TestSpanContiguity:
    """Spans are ordered and non-overlapping, each ending at its own LAST CONTENT LINE.

    They are NOT contiguous: the blank and comment-only lines separating two entries -- where the
    roadmap's `# ----- T3: ... -----` tier section headers live -- are trimmed off the preceding
    entry and belong to no entry at all. Adjacent spans therefore meet only when nothing separates
    them, which is what the first case pins.
    """

    def test_adjacent_spans_meet_when_no_separator_lines_intervene(self) -> None:
        spans = item_spans(_SYNTHETIC)

        assert [(s.item_id, s.start, s.end) for s in spans] == [("T1.1", 6, 10), ("T1.2", 11, 12)]
        assert spans[0].end == spans[1].start - 1

    def test_a_span_ends_at_its_last_content_line_not_at_the_next_entry(self) -> None:
        spans = item_spans(_SECTIONED)

        assert [(s.item_id, s.start, s.end) for s in spans] == [("T1.1", 1, 2), ("T2.1", 5, 6)]

    def test_editing_an_inter_entry_section_header_attributes_to_nothing(self) -> None:
        """The observed defect this rule closes: without the trim the `# ----- T2 -----` header
        sits inside T1.1's span and its edit is falsely attributed to T1.1."""
        post = _edit_line(_SECTIONED, 4, "  # ----- T2: second tier (renamed) -----")

        assert attribute(_SECTIONED, post, _diff(_SECTIONED, post)) == set()

    def test_editing_an_inter_entry_blank_line_attributes_to_nothing(self) -> None:
        post = _edit_line(_SECTIONED, 3, "   ")

        assert attribute(_SECTIONED, post, _diff(_SECTIONED, post)) == set()

    def test_a_body_edit_beside_those_separators_is_still_attributed(self) -> None:
        """Discrimination: the trim removes the separator lines, not the entry."""
        post = _edit_line(_SECTIONED, 2, "    name: first edited")

        assert attribute(_SECTIONED, post, _diff(_SECTIONED, post)) == {"T1.1"}

    def test_the_last_span_ends_at_the_blocks_last_content_line(self) -> None:
        spans = item_spans(_SYNTHETIC)

        assert spans[-1].end == _SYNTHETIC.splitlines().index("cross_tier_gates:") - 1
        assert item_spans(_SECTIONED)[-1].end == _SECTIONED.splitlines().index("cross_tier_gates:") - 2

    def test_an_entry_declaring_no_id_contributes_no_span(self) -> None:
        text = "tier_items:\n  - name: unnamed\n    tier: T0\n  - id: T9.9\n    name: named\n"

        assert [span.item_id for span in item_spans(text)] == ["T9.9"]

    def test_an_id_on_a_following_key_line_is_found(self) -> None:
        text = "tier_items:\n  - tier: T0\n    id: T7.7\n    name: keyed\n"

        assert item_spans(text) == [ItemSpan(item_id="T7.7", start=1, end=3)]

    def test_a_deeper_indented_list_item_never_starts_a_span(self) -> None:
        assert len(item_spans(_SYNTHETIC)) == 2

    def test_the_ordered_span_ids_equal_the_live_documents_tier_items(self) -> None:
        """Binds this second, line-shape parser to the Pydantic document model.

        A future roadmap indentation or flow-style change reddens THIS test rather than letting
        the detector silently mis-attribute -- the one path by which this advisory-only work can
        turn a roadmap edit red, since neither surfacing can ever append to `failed`.
        """
        from scripts.checks import _common  # noqa: PLC0415
        from scripts.roadmap.platform_roadmap import load  # noqa: PLC0415

        path = _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"

        assert [span.item_id for span in item_spans(path.read_text(encoding="utf-8"))] == [
            item.id for item in load(path).tier_items
        ]


class TestContextLinesAreNotChanges:
    """changed_lines counts added and removed lines only."""

    def test_context_lines_advance_both_cursors_and_change_nothing(self) -> None:
        diff = "@@ -1,3 +1,3 @@\n alpha\n-beta\n+gamma\n delta\n"

        changed = changed_lines(diff)

        assert changed.pre == frozenset({1})
        assert changed.post == frozenset({1})

    def test_lines_before_the_first_hunk_are_ignored(self) -> None:
        diff = "diff --git a/f b/f\nindex 111..222 100644\n--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+b\n"

        changed = changed_lines(diff)

        assert changed.pre == frozenset({0})
        assert changed.post == frozenset({0})

    def test_a_second_diff_git_header_closes_the_previous_hunk(self) -> None:
        diff = "@@ -1,1 +1,1 @@\n-a\n+b\ndiff --git a/g b/g\n--- a/g\n+++ b/g\n"

        changed = changed_lines(diff)

        assert changed.pre == frozenset({0})
        assert changed.post == frozenset({0})

    def test_the_no_newline_marker_is_not_a_change(self) -> None:
        diff = "@@ -1,1 +1,1 @@\n-a\n\\ No newline at end of file\n+b\n"

        changed = changed_lines(diff)

        assert changed.pre == frozenset({0})
        assert changed.post == frozenset({0})

    def test_an_empty_changed_set_touches_nothing(self) -> None:
        assert touched_item_ids(item_spans(_SYNTHETIC), [], ChangedLines(pre=frozenset(), post=frozenset())) == set()


class TestLegacyDetectorDefects:
    """The two MEASURED defects of the frozen legacy detector, reproduced as named cases."""

    def test_an_added_blank_line_spans_into_the_context_id_line_below_it(self) -> None:
        """The 6f15d11 / T2.42 mechanism: '+' alone, then \\s+ crossing the newline into the
        context '  - id: X' line, under re.MULTILINE."""
        pre = "tier_items:\n  - id: T9.9\n    name: x\n"
        post = "tier_items:\n\n  - id: T9.9\n    name: x\n"
        diff = "@@ -1,3 +1,4 @@\n tier_items:\n+\n   - id: T9.9\n     name: x\n"

        assert legacy_regex_item_ids(diff) == {"T9.9"}
        assert attribute(pre, post, diff) == set()

    def test_an_interior_body_edit_is_named_by_spans_and_missed_by_the_legacy_detector(self) -> None:
        post = _edit_line(_SYNTHETIC, 7, "    name: first edited")
        diff = _diff(_SYNTHETIC, post)

        assert attribute(_SYNTHETIC, post, diff) == {"T1.1"}
        assert legacy_regex_item_ids(diff) & {span.item_id for span in item_spans(_SYNTHETIC)} == set()

    def test_the_frozen_pattern_still_matches_a_plain_added_id_line(self) -> None:
        """Discrimination: the legacy symbol is the same detector, not a neutered stand-in."""
        assert legacy_regex_item_ids("@@ -1,0 +1,1 @@\n+  - id: T4.4\n") == {"T4.4"}


class TestDeletedItemAttributedFromPreImage:
    """A wholesale deletion has no post-image span, so the pre-image half is load-bearing."""

    def test_a_deleted_item_is_attributed_from_its_pre_image_span(self) -> None:
        post = "\n".join(_SYNTHETIC.splitlines()[:11] + _SYNTHETIC.splitlines()[13:]) + "\n"
        diff = _diff(_SYNTHETIC, post)

        assert "T1.2" in attribute(_SYNTHETIC, post, diff)

    def test_a_post_image_only_rule_would_lose_it(self) -> None:
        post = "\n".join(_SYNTHETIC.splitlines()[:11] + _SYNTHETIC.splitlines()[13:]) + "\n"
        changed = changed_lines(_diff(_SYNTHETIC, post))

        assert "T1.2" not in touched_item_ids([], item_spans(post), changed)


class TestAdvisoryFramingCounterfactual:
    """The measured reason both surfacings land ADVISORY, computed rather than quoted.

    Criterion (ii)'s failing arm rejects a TOUCHED tier_item that still carries a bare-string exit
    criterion. Feeding it the span attribution instead of the legacy detector would therefore have
    blocked every fixture commit whose attribution meets the post-image bare-string set. That
    count is the design fork, so it is measured here and by the verification plan, never asserted
    from plan prose.
    """

    @staticmethod
    def _blocked(selector) -> int:  # type: ignore[no-untyped-def]
        return sum(1 for row in load_fixture() if set(selector(row)) & set(row.bare_string_criteria))

    def test_a_span_driven_failing_arm_would_have_blocked_commits_the_legacy_one_did_not(self) -> None:
        span_blocked = self._blocked(lambda row: row.expected)
        legacy_blocked = self._blocked(lambda row: row.legacy_raw)

        assert legacy_blocked == 0
        assert span_blocked > 0

    def test_the_counterfactual_is_measured_over_the_whole_population(self) -> None:
        rows = load_fixture()

        assert len(rows) == 40
        assert all(row.bare_string_criteria for row in rows)


class TestFixtureLoadIsHermetic:
    """No test reads live git history: the helper cannot shell, and the loader does not."""

    def test_the_pure_helper_imports_no_subprocess_or_shell_surface(self) -> None:
        tree = ast.parse(Path(_roadmap_spans.__file__).read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add((node.module or "").split(".")[0])

        assert roots & {"subprocess", "os", "shutil", "pathlib"} == set()

    def test_load_fixture_shells_nothing(self) -> None:
        with patch("subprocess.run", side_effect=AssertionError("load_fixture shelled out")):
            rows = load_fixture()

        assert len(rows) == 40

    def test_importing_the_generator_module_executes_nothing(self) -> None:
        name = "_roadmap_touched_items_import_probe"
        path = Path(__file__).resolve().parents[2] / "fixtures" / "roadmap_touched_items.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        try:
            sys.modules[name] = module  # dataclasses resolves annotations through sys.modules
            with patch("subprocess.run", side_effect=AssertionError("import-time shell")):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)

        assert module.GENERATION_COMMAND == "bin/venv-python -m tests.fixtures.roadmap_touched_items --generate"
