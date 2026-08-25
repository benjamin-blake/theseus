"""Mirror test for scripts/checks/decisions/validate_live_entry_immutability.py
(PLAN-adr-restructure-wave, rec-3249) -- the waiver-free append-only live-body lock.

The suite is the VP step-1 discriminator: it drives the REAL check function through an injected
baseline-body reader, asserting each of the five classification branches both ways. A guard that
only ever passes is worthless, so every FAIL case here is paired with the nearest legitimate
shape that must still PASS.

Baselines are injected rather than built from a throwaway git repo (the _baseline reader itself
owns the git mechanics and is covered in test__baseline.py) -- this suite is about
classification, so it varies body TEXT, not git plumbing.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from scripts.checks.decisions import validate_live_entry_immutability as mod
from scripts.checks.decisions.validate_live_entry_immutability import validate_live_entry_immutability

_LIVE = "docs/DECISIONS.md"
_ARCHIVE = "docs/DECISIONS_ARCHIVE.md"

_BASELINE_BODY = """## Decision 1: A ratified entry (Decided)

**Status:** Decided
**Date:** 2026-01-01

**Problem:**
The original problem statement.

**Decision:**
The original ruling, clause one.
The original ruling, clause two.

**Related:** Decision 2.

---
"""

_STANZA_BODY = """## Decision 3: An entry with a monitored stanza (Decided)

**Status:** Decided
**Date:** 2026-01-01

**Decision:**
A ruling.

```yaml reversal-conditions
decision: 3
review_by: 2026-06-01
on_trigger: "re-decide via /plan; update or re-arm this stanza"
conditions:
  - id: some-condition
    kind: manual
    description: "A condition."
```

**Related:** Decision 1.

---
"""


def _run(tmp_path: Path, baseline: dict[str, dict[int, str]], current: dict[str, str]) -> list[str]:
    """Write `current` corpus files under tmp_path, run the check against `baseline`, return failures."""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "DECISIONS.md").write_text(current.get(_LIVE, ""), encoding="utf-8")
    (docs / "DECISIONS_ARCHIVE.md").write_text(current.get(_ARCHIVE, ""), encoding="utf-8")
    failed: list[str] = []
    validate_live_entry_immutability(failed, root=tmp_path, baseline_body_reader=lambda _root: baseline)
    return failed


def _baseline(live: dict[int, str] | None = None, archive: dict[int, str] | None = None) -> dict:
    return {_LIVE: live or {}, _ARCHIVE: archive or {}}


class TestBranchOneAppendOnlyFailures:
    """(i) Live, not newly superseded: exact-line append-only. These must all FAIL."""

    def test_destructive_line_edit_fails(self, tmp_path: Path) -> None:
        mutated = _BASELINE_BODY.replace("The original ruling, clause one.", "The REWRITTEN ruling, clause one.")
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: mutated})
        assert failed
        assert "Live decision-body immutability" in failed

    def test_line_deletion_fails(self, tmp_path: Path) -> None:
        mutated = _BASELINE_BODY.replace("The original ruling, clause two.\n", "")
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: mutated})
        assert failed

    def test_deleting_one_of_two_duplicate_lines_fails(self, tmp_path: Path) -> None:
        """Injective matching: N identical baseline lines demand N identical current lines."""
        dup_baseline = _BASELINE_BODY.replace(
            "**Problem:**\nThe original problem statement.\n",
            "**Problem:**\nRepeated line.\nRepeated line.\n",
        )
        dup_current = dup_baseline.replace("Repeated line.\nRepeated line.\n", "Repeated line.\n")
        failed = _run(tmp_path, _baseline(live={1: dup_baseline}), {_LIVE: dup_current})
        assert failed

    def test_line_join_fails(self, tmp_path: Path) -> None:
        mutated = _BASELINE_BODY.replace(
            "The original ruling, clause one.\nThe original ruling, clause two.",
            "The original ruling, clause one. The original ruling, clause two.",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: mutated})
        assert failed

    def test_mid_line_splice_fails(self, tmp_path: Path) -> None:
        """A retired micro-shape: corrections land as their own dated line, never spliced in."""
        mutated = _BASELINE_BODY.replace(
            "The original ruling, clause one.",
            "The original ruling, clause one (as corrected 2026-08-25).",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: mutated})
        assert failed

    def test_line_reorder_fails(self, tmp_path: Path) -> None:
        mutated = _BASELINE_BODY.replace(
            "The original ruling, clause one.\nThe original ruling, clause two.",
            "The original ruling, clause two.\nThe original ruling, clause one.",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: mutated})
        assert failed


class TestBranchOneAppendOnlyPasses:
    """(i) The legitimate shapes: these must all PASS."""

    def test_suffix_appended_annotation_passes(self, tmp_path: Path) -> None:
        appended = _BASELINE_BODY + "\n[Amendment 2026-08-25, operator: a dated clarification.]\n"
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: appended})
        assert failed == []

    def test_mid_body_inserted_annotation_passes(self, tmp_path: Path) -> None:
        inserted = _BASELINE_BODY.replace(
            "**Related:** Decision 2.",
            "> **Update (2026-08-25):** a mid-body dated note.\n\n**Related:** Decision 2.",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: inserted})
        assert failed == []

    def test_in_intent_accretion_passes(self, tmp_path: Path) -> None:
        """Decision 151 clause 3(ii): an Intent-section accretion is an insertion, not an edit."""
        with_intent = _BASELINE_BODY.replace(
            "**Problem:**",
            "**Intent:**\nThe durable why.\n\n**Problem:**",
        )
        accreted = with_intent.replace(
            "The durable why.\n",
            "The durable why.\n[Amendment 2026-08-25, operator: a narrowing clarification.]\n",
        )
        failed = _run(tmp_path, _baseline(live={1: with_intent}), {_LIVE: accreted})
        assert failed == []

    def test_trailing_whitespace_only_difference_passes(self, tmp_path: Path) -> None:
        mutated = _BASELINE_BODY.replace(
            "The original ruling, clause one.",
            "The original ruling, clause one.   ",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: mutated})
        assert failed == []

    def test_baseline_absent_new_entry_passes(self, tmp_path: Path) -> None:
        """A brand-new entry has no baseline body to preserve -- conformance owns its shape."""
        new_entry = _BASELINE_BODY.replace("Decision 1:", "Decision 9:")
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: _BASELINE_BODY + new_entry})
        assert failed == []


class TestStanzaCarveOut:
    """The one monitored-surface carve-out: interiors free, existence locked."""

    def test_stanza_interior_edit_passes(self, tmp_path: Path) -> None:
        rearmed = _STANZA_BODY.replace("review_by: 2026-06-01", "review_by: 2026-12-01").replace(
            'description: "A condition."', 'description: "A re-armed condition."'
        )
        failed = _run(tmp_path, _baseline(live={3: _STANZA_BODY}), {_LIVE: rearmed})
        assert failed == []

    def test_stanza_deletion_fails(self, tmp_path: Path) -> None:
        start = _STANZA_BODY.index("```yaml reversal-conditions")
        end = _STANZA_BODY.index("```\n", _STANZA_BODY.index("conditions:")) + len("```\n")
        stripped = _STANZA_BODY[:start] + _STANZA_BODY[end:]
        failed = _run(tmp_path, _baseline(live={3: _STANZA_BODY}), {_LIVE: stripped})
        assert failed

    def test_prose_edit_outside_stanza_still_fails(self, tmp_path: Path) -> None:
        """The carve-out is scoped to the stanza -- it never licenses edits elsewhere."""
        mutated = _STANZA_BODY.replace("A ruling.", "A REWRITTEN ruling.")
        failed = _run(tmp_path, _baseline(live={3: _STANZA_BODY}), {_LIVE: mutated})
        assert failed

    def test_metadata_envelope_fence_is_not_carved_out(self, tmp_path: Path) -> None:
        """A bare ```yaml block is the Decision 167 envelope, NOT the monitored stanza -- editing
        it is a body edit and must fail."""
        enveloped = """## Decision 5: Enveloped entry (Decided)

```yaml
number: 5
status: Decided
```

**Status:** Decided

---
"""
        mutated = enveloped.replace("status: Decided\n```", "status: Superseded\n```")
        failed = _run(tmp_path, _baseline(live={5: enveloped}), {_LIVE: mutated})
        assert failed


class TestBranchTwoNewlySuperseded:
    """(ii) A Status flip to Superseded demands the strict stub shape."""

    _STUB = """## Decision 1: A ratified entry (Decided)

**Status:** Superseded
**Date:** 2026-08-25

**Decision:** Superseded by Decision 7; see that entry.

**Superseded by: Decision 7**

---
"""

    def test_strict_stub_passes(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: self._STUB})
        assert failed == []

    def test_pointer_bearing_full_body_status_flip_fails(self, tmp_path: Path) -> None:
        """The round-3 governance finding: a full body carrying BOTH supersession markers passes
        is_compacted_stub, so the shape bound -- not marker presence -- is what closes the bypass."""
        bypass = _BASELINE_BODY.replace("**Status:** Decided", "**Status:** Superseded").replace(
            "**Related:** Decision 2.",
            "**Superseded by: Decision 7**\n\n**Related:** Decision 2.",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: bypass})
        assert failed

    def test_stub_retaining_one_stray_prose_line_fails(self, tmp_path: Path) -> None:
        leaky = self._STUB.replace(
            "**Superseded by: Decision 7**",
            "A lingering rationale sentence.\n\n**Superseded by: Decision 7**",
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: leaky})
        assert failed


class TestBranchThreeArchiveMove:
    """(iii) Archive moves embed the baseline body; relocation is not a content escape."""

    def test_conforming_move_passes(self, tmp_path: Path) -> None:
        moved = _BASELINE_BODY.replace(
            "## Decision 1: A ratified entry (Decided)",
            "## Decision 1: A ratified entry (Superseded, archived 2026-08-25)",
        ).replace("**Status:** Decided", "**Status:** Superseded -- archived")
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: "", _ARCHIVE: moved})
        assert failed == []

    def test_move_with_body_rewrite_fails(self, tmp_path: Path) -> None:
        moved = (
            _BASELINE_BODY.replace(
                "## Decision 1: A ratified entry (Decided)",
                "## Decision 1: A ratified entry (Superseded, archived 2026-08-25)",
            )
            .replace("**Status:** Decided", "**Status:** Superseded -- archived")
            .replace("The original ruling, clause two.", "A rewritten clause two.")
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: "", _ARCHIVE: moved})
        assert failed

    def test_move_dropping_a_body_line_fails(self, tmp_path: Path) -> None:
        moved = _BASELINE_BODY.replace("**Status:** Decided", "**Status:** Superseded -- archived").replace(
            "**Problem:**\nThe original problem statement.\n", ""
        )
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: "", _ARCHIVE: moved})
        assert failed


class TestBranchFourVanishedNumber:
    """(iv) never_remove_headers: absent from both files is unconditionally a failure."""

    def test_number_absent_from_both_files_fails(self, tmp_path: Path) -> None:
        failed = _run(tmp_path, _baseline(live={1: _BASELINE_BODY}), {_LIVE: "", _ARCHIVE: ""})
        assert failed


class TestBranchFiveBaselineSuperseded:
    """(v) A body already Superseded at baseline defers to conformance's stub/archive rules."""

    def test_baseline_superseded_body_left_untouched_passes(self, tmp_path: Path) -> None:
        superseded = _BASELINE_BODY.replace("**Status:** Decided", "**Status:** Superseded")
        failed = _run(tmp_path, _baseline(live={1: superseded}), {_LIVE: superseded})
        assert failed == []

    def test_baseline_superseded_body_edited_is_deferred_not_failed(self, tmp_path: Path) -> None:
        """Deliberate deferral, asserted so a future widening of this branch is a conscious edit
        rather than a silent behaviour change."""
        superseded = _BASELINE_BODY.replace("**Status:** Decided", "**Status:** Superseded")
        edited = superseded.replace("The original ruling, clause one.", "Compacted away.")
        failed = _run(tmp_path, _baseline(live={1: superseded}), {_LIVE: edited})
        assert failed == []


class TestAdvisorySkip:
    def test_unreachable_baseline_skips_without_failing(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "DECISIONS.md").write_text(_BASELINE_BODY, encoding="utf-8")
        failed: list[str] = []
        validate_live_entry_immutability(failed, root=tmp_path, baseline_body_reader=lambda _root: None)
        assert failed == []


class TestNoWaiverRoute:
    """The lock reads no config and exposes no escape hatch (Decision 163 anti-pattern)."""

    def test_module_source_contains_no_waiver_or_allowlist_vocabulary(self) -> None:
        source = inspect.getsource(mod)
        body = source.split('"""', 2)[2] if source.count('"""') >= 2 else source
        lowered = body.lower()
        for token in ("waiver", "allowlist", "raise-approved", "grandfather", "exempt_file", "skip_list"):
            assert token not in lowered, f"waiver-shaped vocabulary {token!r} present in the lock's code"

    def test_module_imports_no_config_or_yaml_loader(self) -> None:
        source = inspect.getsource(mod)
        assert "import yaml" not in source
        assert "yaml.safe_load" not in source
        assert "config/" not in source

    def test_check_signature_exposes_no_waiver_parameter(self) -> None:
        params = set(inspect.signature(validate_live_entry_immutability).parameters)
        assert params == {"failed", "root", "baseline_body_reader"}
