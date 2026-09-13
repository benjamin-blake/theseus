"""Tests for scripts/roadmap/scope_projection.py (PLAN-decision-scout-roadmap-projection).

Two classes: module behaviour (TierItem/ExitCriterion fixtures built inline, no file I/O) and
cross-surface anti-drift (the projected-field roster and the decision-scout report shape stay in
lockstep across the module, docs/contracts/exit-criteria-ledger.yaml, and
.claude/skills/decision-scout/SKILL.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from scripts.roadmap.platform_roadmap import ExitCriterion, TierItem
from scripts.roadmap.scope_projection import (
    INTENT_CHARS,
    PROJECTED_FIELDS,
    main,
    matched_paths,
    project_items,
)

ROOT = Path(__file__).resolve().parents[1]


def _item(**overrides) -> TierItem:
    base = {"id": "T9.1", "tier": "T9", "name": "fixture item"}
    base.update(overrides)
    return TierItem(**base)


class TestMatchedPaths:
    def test_exact_match(self) -> None:
        assert matched_paths(["AGENTS.md"], ["AGENTS.md"]) == ["AGENTS.md"]

    def test_directory_prefix_match(self) -> None:
        assert matched_paths(["docs/contracts/"], ["docs/contracts/instruction-architecture.yaml"]) == ["docs/contracts/"]

    def test_directory_prefix_match_no_trailing_slash_on_entry(self) -> None:
        # entry without a trailing slash is still treated as a directory prefix.
        assert matched_paths(["docs/contracts"], ["docs/contracts/instruction-architecture.yaml"]) == ["docs/contracts"]

    def test_near_miss_bare_string_prefix_rejected(self) -> None:
        # "docs/contract" must NOT match "docs/contracts/x.yaml" -- that is a bare string
        # prefix, not a directory prefix ("docs/contract/" is not a prefix of the scope path).
        assert matched_paths(["docs/contract"], ["docs/contracts/x.yaml"]) == []

    def test_no_match_returns_empty(self) -> None:
        assert matched_paths(["scripts/unrelated.py"], ["docs/contracts/x.yaml"]) == []

    def test_result_is_sorted_deduplicated(self) -> None:
        result = matched_paths(["b.py", "a.py", "b.py"], ["a.py", "b.py"])
        assert result == ["a.py", "b.py"]

    def test_directory_shaped_scope_path_matches_file_shaped_entry(self) -> None:
        # A plan's Scope list may itself be directory-shaped (e.g. "scripts/", as used by
        # docs/plans/archive/* and scripts/checks/deps/*) -- it must match a file-shaped
        # files_in_scope entry beneath it, not just the reverse direction.
        assert matched_paths(["scripts/roadmap/scope_projection.py"], ["scripts/"]) == ["scripts/roadmap/scope_projection.py"]

    def test_directory_shaped_scope_path_no_trailing_slash_still_matches(self) -> None:
        assert matched_paths(["scripts/roadmap/scope_projection.py"], ["scripts"]) == ["scripts/roadmap/scope_projection.py"]

    def test_directory_shaped_scope_path_near_miss_bare_string_prefix_rejected(self) -> None:
        # "scripts" as a Scope path must not match "scripts-extra/x.py" -- that is a bare
        # string prefix, not a directory prefix, in either direction.
        assert matched_paths(["scripts-extra/x.py"], ["scripts"]) == []


class TestProjectItems:
    def test_matching_item_carries_exactly_projected_fields(self) -> None:
        item = _item(
            files_in_scope=["docs/contracts/x.yaml"],
            status="in_progress",
            depends_on=["T1.1"],
            related_candidate_decisions=["CD.9"],
        )
        [row] = project_items([item], ["docs/contracts/x.yaml"])
        assert set(row.keys()) == set(PROJECTED_FIELDS)
        assert row["id"] == "T9.1"
        assert row["name"] == "fixture item"
        assert row["status"] == "in_progress"
        assert row["matched"] == ["docs/contracts/x.yaml"]
        assert row["depends_on"] == ["T1.1"]
        assert row["related_candidate_decisions"] == ["CD.9"]

    def test_non_matching_item_excluded(self) -> None:
        item = _item(files_in_scope=["scripts/unrelated.py"])
        assert project_items([item], ["docs/contracts/x.yaml"]) == []

    def test_directory_shaped_scope_path_yields_a_match(self) -> None:
        # Regression for the false CONFLICT: 0 (code-review round 1, H3): a directory-shaped
        # Scope entry must still find file-shaped files_in_scope entries beneath it.
        item = _item(files_in_scope=["scripts/roadmap/scope_projection.py"])
        [row] = project_items([item], ["scripts/"])
        assert row["id"] == "T9.1"

    def test_open_criteria_filtered_to_open_status_and_carries_criterion_id(self) -> None:
        item = _item(
            files_in_scope=["a.py"],
            exit_criteria=[
                ExitCriterion(id="c1", text="open one", status="open"),
                ExitCriterion(id="c2", text="met one", status="met", met_by="some-plan"),
                ExitCriterion(id="c3", text="rehomed one", status="rehomed", met_by="T9.2"),
            ],
        )
        [row] = project_items([item], ["a.py"])
        # Each open criterion carries its stable id alongside its text so a CITE/CONFLICT row
        # can name it as "<item id>:<criterion id>" (e.g. "T9.1:c1") -- H2 regression.
        assert row["open_criteria"] == [{"id": "c1", "text": "open one"}]

    def test_intent_truncated_at_intent_chars(self) -> None:
        long_intent = "x" * (INTENT_CHARS + 50)
        item = _item(files_in_scope=["a.py"], intent=long_intent)
        [row] = project_items([item], ["a.py"])
        assert row["intent"] == long_intent[:INTENT_CHARS]
        assert len(row["intent"]) == INTENT_CHARS


class TestMain:
    def test_empty_argv_returns_2_and_prints_usage(self, capsys) -> None:
        assert main([]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Usage" in captured.err

    def test_nonempty_argv_returns_0_and_prints_json(self, capsys) -> None:
        assert main(["a-scope-path-unlikely-to-match-anything.xyz"]) == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert isinstance(payload, list)


# ---------------------------------------------------------------------------
# Cross-surface anti-drift: the module, the ledger contract, and the decision-scout skill must
# agree on the field roster and the report shape (PDB-04 / remedy B2-R5).
# ---------------------------------------------------------------------------

_LEDGER_PATH = ROOT / "docs" / "contracts" / "exit-criteria-ledger.yaml"
_INSTRUCTION_ARCH_PATH = ROOT / "docs" / "contracts" / "instruction-architecture.yaml"
_SKILL_PATH = ROOT / ".claude" / "skills" / "decision-scout" / "SKILL.md"

_FIELDS_MARKER_RE = re.compile(r"fields=\[([^\]]*)\]")
_NO_WHOLE_DECISIONS_READ_RE = re.compile(r"[Rr]ead the (\*\*)?(entire|full)(\*\*)?[^\n]{0,12}DECISIONS\.md")
_SPIRIT_GATE_MARKER_RE = re.compile(r"^   - \((i|ii|iii|iv)\) \*\*", re.MULTILINE)


def _ledger_audit_invariants_string() -> str:
    data = yaml.safe_load(_LEDGER_PATH.read_text(encoding="utf-8"))
    [entry] = data["audit_invariants"]
    assert entry.startswith("roadmap_alignment_projection: ")
    return entry


class TestLedgerRosterAgreement:
    def test_ledger_fields_marker_matches_projected_fields(self) -> None:
        entry = _ledger_audit_invariants_string()
        match = _FIELDS_MARKER_RE.search(entry)
        assert match is not None, entry
        roster = tuple(name.strip() for name in match.group(1).split(","))
        assert roster == PROJECTED_FIELDS

    def test_emitted_row_keys_match_projected_fields(self) -> None:
        item = _item(files_in_scope=["a.py"])
        [row] = project_items([item], ["a.py"])
        assert tuple(sorted(row.keys())) == tuple(sorted(PROJECTED_FIELDS))

    def test_ledger_string_carries_required_semantics(self) -> None:
        entry = _ledger_audit_invariants_string()
        for literal in (
            "T2.20",
            "WARN",
            "never BLOCK",
            "Widen the field roster HERE first",
            "at most 5 rows",
            ".claude/skills/",
            "K=0",
        ):
            assert literal in entry, literal

    def test_ledger_string_declares_bidirectional_match_semantics(self) -> None:
        # H3 regression: the ledger must state the resulting match semantics, not just the
        # roster, so a reader knows a directory-shaped Scope path matches a file-shaped entry.
        entry = _ledger_audit_invariants_string()
        assert "bidirectionally" in entry
        assert "directory-shaped Scope path" in entry

    def test_ledger_string_declares_per_criterion_id(self) -> None:
        # H2 regression: open_criteria carries a per-criterion id, not text-only.
        entry = _ledger_audit_invariants_string()
        assert "{id, text} pair" in entry


class TestSkillReportShape:
    def _text(self) -> str:
        return _SKILL_PATH.read_text(encoding="utf-8")

    def test_roadmap_heading_present(self) -> None:
        assert "### Roadmap Alignment (ROADMAP)" in self._text()

    def test_integrity_line_and_copy_instruction_inside_fenced_template(self) -> None:
        text = self._text()
        fence_start = text.index("```\n## Decision Scout Report")
        fence_end = text.index("```", fence_start + 3)
        template = text[fence_start:fence_end]
        assert "Decisions triaged: N of M" in template
        assert "Roadmap items intersected: K; CONFLICT: c; RELATED: r" in template
        triaged_pos = template.index("Decisions triaged: N of M")
        roadmap_count_pos = template.index("Roadmap items intersected: K; CONFLICT: c; RELATED: r")
        copy_pos = template.index("copy both count lines verbatim into the plan's scout context line.")
        assert triaged_pos < roadmap_count_pos < copy_pos

    def test_conflict_always_warn_never_block(self) -> None:
        text = self._text()
        assert "CONFLICT is ALWAYS WARN, never BLOCK" in text
        assert "ROADMAP rows never raise the verdict to BLOCK" in text

    def test_unavailability_disposition_and_tally_exclusion(self) -> None:
        text = self._text()
        assert "Roadmap items intersected: unavailable (projection failed)" in text
        assert "excluded from the 40-plan tally" in text
        assert "Non-zero exit" in text

    def test_unavailability_disposition_does_not_suppress_decisions_triaged(self) -> None:
        # H1 regression: the round-1 wording ("replaces both count lines") read literally as
        # suppressing "Decisions triaged: N of M" too, which planning/SKILL.md's gate-
        # completeness check treats as a re-dispatch trigger. The disposition must name the
        # ROADMAP line specifically and never claim to replace both lines.
        text = self._text()
        assert "replaces the ROADMAP line" in text
        assert "replaces both count lines" not in text
        # The template's "Decisions triaged: N of M" line is unconditional fixed text -- it is
        # never inside the disposition sentence that names what the failure literal replaces.
        disposition_sentence = text[text.index("Non-zero exit:") : text.index("Non-zero exit:") + 200]
        assert "Decisions triaged" not in disposition_sentence

    def test_display_cap_and_ordering(self) -> None:
        text = self._text()
        assert "at most 5 rows" in text
        assert "showing 5 of K" in text
        assert "CONFLICT > CITE > RELATED" in text

    def test_word_and_revisit_budget_literals(self) -> None:
        text = self._text()
        assert "150" in text
        assert "40 consecutive" in text

    def test_module_invocation_and_ledger_path_named(self) -> None:
        text = self._text()
        assert "scripts.roadmap.scope_projection" in text
        assert "docs/contracts/exit-criteria-ledger.yaml" in text

    def test_merged_cite_lane_bullet_keeps_both_rules(self) -> None:
        text = self._text()
        assert "CITE only when the decision's *clause* governs the approach's *action*" in text
        assert "CITE only when omission would meaningfully harm the plan" in text

    def test_standing_registry_guards_survive(self) -> None:
        text = self._text()
        assert "SPIRIT over-citation" in text
        assert text.count("### Spirit-Alignment Flags (SPIRIT)") == 1
        assert len(_SPIRIT_GATE_MARKER_RE.findall(text)) == 4
        assert "decisions-index.json" in text
        assert not _NO_WHOLE_DECISIONS_READ_RE.search(text)


class TestInstructionArchitectureRelocation:
    def _data(self) -> dict:
        return yaml.safe_load(_INSTRUCTION_ARCH_PATH.read_text(encoding="utf-8"))

    def test_gate_subagent_retrieval_block_present(self) -> None:
        data = self._data()
        assert "gate_subagent_retrieval" in data
        block = data["gate_subagent_retrieval"]
        assert "A naive inline grep" in block["isolation_rationale"]
        assert "index-plus-targeted-reads" in block["substrate_swap_contract"]
        assert "T1.5" in block["substrate_swap_contract"]

    def test_over_citation_long_forms_relocated(self) -> None:
        block = self._data()["gate_subagent_retrieval"]
        anti_patterns = " ".join(block["anti_patterns"])
        assert "Keyword-only CITE" in anti_patterns
        assert "Defensive over-citation" in anti_patterns

    def test_relocated_sentences_no_longer_in_skill(self) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        assert "A naive inline grep" not in text
        assert "index-plus-targeted-reads" not in text
