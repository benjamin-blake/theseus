"""Tests for scripts/checks/ci_guards/_agent_loop_caps.py -- the shared, check-side agent-loop
cap extraction grammar and two-way comparator (audit finding LSA-05).

This file is _agent_loop_caps.py's OWN mirror and drives every branch directly against synthetic
trees; the two production callers (validate_ci_rca_adjudication's group (d),
validate_composite_action_shape_rosters' group 5) exercise this module through their own separate
mirror tests and are not duplicated here.
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks.ci_guards._agent_loop_caps import (
    check_cap_entry_shape,
    compare_caps,
    scan_cap_literals,
)

_LONG_ON_EXHAUSTION = "the mask lifts, the deterministic gate then fires and reddens the build"
_LONG_RATIONALE = "thirty turns because this agent is multi-bundle read-write, unlike a reviewer"


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _valid_entry(**overrides: object) -> dict:
    entry = {
        "kind": "max_turns",
        "value": 30,
        "on_exhaustion": _LONG_ON_EXHAUSTION,
        "rationale": _LONG_RATIONALE,
    }
    entry.update(overrides)
    return entry


class TestScanCapLiteralsGreen:
    def test_inline_integer_resolves(self, tmp_path):
        _write(tmp_path, ".github/workflows/w.yml", "name: w\nrun: --max-turns 30\n")
        discovered, errors = scan_cap_literals(tmp_path)
        assert errors == []
        assert discovered == {".github/workflows/w.yml": {"max_turns": 30}}

    def test_var_indirect_same_file_resolves(self, tmp_path):
        _write(tmp_path, ".github/actions/a/run.sh", 'MAX_TURNS=5\nfoo --max-turns "$MAX_TURNS"\n')
        discovered, errors = scan_cap_literals(tmp_path)
        assert errors == []
        assert discovered == {".github/actions/a/run.sh": {"max_turns": 5}}

    def test_braced_var_form_resolves(self, tmp_path):
        _write(tmp_path, ".github/actions/a/run.sh", 'MAX_TURNS=5\nfoo --max-turns "${MAX_TURNS}"\n')
        discovered, errors = scan_cap_literals(tmp_path)
        assert errors == []
        assert discovered == {".github/actions/a/run.sh": {"max_turns": 5}}

    def test_review_sh_shape_shared_assignment_two_invocations_yields_one_value(self, tmp_path):
        """The real review.sh:68 shape -- ONE MAX_TURNS=5 assignment feeds TWO invocations,
        yielding ONE value, not a conflict."""
        _write(
            tmp_path,
            ".github/actions/subagent-plan-review/review.sh",
            'MAX_TURNS=5\nfoo --max-turns "$MAX_TURNS"\nbar --max-turns "$MAX_TURNS"\n',
        )
        discovered, errors = scan_cap_literals(tmp_path)
        assert errors == []
        assert discovered == {".github/actions/subagent-plan-review/review.sh": {"max_turns": 5}}

    def test_no_flag_present_yields_empty_census(self, tmp_path):
        _write(tmp_path, ".github/workflows/w.yml", "name: w\n")
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors == []

    def test_missing_github_dir_yields_empty_census(self, tmp_path):
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors == []

    def test_undecodable_file_is_skipped_without_raising(self, tmp_path):
        path = tmp_path / ".github" / "workflows" / "binary.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00--max-turns 30")
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors == []


class TestScanCapLiteralsFailClosed:
    def test_unresolvable_bare_variable_with_no_assignment(self, tmp_path):
        _write(tmp_path, ".github/workflows/w.yml", 'foo --max-turns "$UNDEFINED_VAR"\n')
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors and "unresolvable" in errors[0]

    def test_unresolvable_computed_interpolated_token(self, tmp_path):
        _write(tmp_path, ".github/workflows/w.yml", "foo --max-turns $(( 1 + 2 ))\n")
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors and "unresolvable" in errors[0]

    def test_one_file_two_different_values_is_ambiguous(self, tmp_path):
        _write(tmp_path, ".github/workflows/w.yml", "foo --max-turns 5\nbar --max-turns 10\n")
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors and "different" in errors[0]

    def test_literal_outside_both_governed_regions_fails_closed(self, tmp_path):
        """Relocating a cap out of the two governed regions is not an escape from declaration --
        it fails closed instead of silently escaping the census."""
        _write(tmp_path, ".github/agents/schedule.yaml", "agent:\n  args: --max-turns 30\n")
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors and "outside both governed regions" in errors[0]

    def test_ungoverned_extension_under_actions_dir_is_still_outside_region(self, tmp_path):
        """A file under .github/actions/ with an extension outside {.yml,.yaml,.sh} does not
        silently join the action-region glob -- it is scanned as outside-both-regions instead."""
        _write(tmp_path, ".github/actions/a/notes.txt", "--max-turns 30\n")
        discovered, errors = scan_cap_literals(tmp_path)
        assert discovered == {}
        assert errors and "outside both governed regions" in errors[0]


class TestCompareCaps:
    def test_match_passes(self):
        assert compare_caps({"f.yml": {"max_turns": 30}}, {"f.yml": {"max_turns": 30}}, "workflow") == []

    def test_value_mismatch_declared_lower_fails(self):
        failures = compare_caps({"f.yml": {"max_turns": 30}}, {"f.yml": {"max_turns": 31}}, "workflow")
        assert failures and "drift" in failures[0]

    def test_value_mismatch_declared_higher_fails(self):
        failures = compare_caps({"f.yml": {"max_turns": 31}}, {"f.yml": {"max_turns": 30}}, "workflow")
        assert failures and "drift" in failures[0]

    def test_discovered_but_undeclared_fails(self):
        failures = compare_caps({}, {"f.yml": {"max_turns": 30}}, "workflow")
        assert failures and "undeclared" in failures[0]

    def test_declared_but_not_discovered_is_stale(self):
        failures = compare_caps({"f.yml": {"max_turns": 30}}, {}, "workflow")
        assert failures and "stale" in failures[0]

    def test_region_label_appears_in_failure_text(self):
        failures = compare_caps({}, {"f.yml": {"max_turns": 30}}, "action")
        assert failures and "(action)" in failures[0]

    def test_both_empty_passes_vacuously(self):
        assert compare_caps({}, {}, "workflow") == []


class TestCheckCapEntryShape:
    def test_valid_entry_passes(self):
        failures, kind, value = check_cap_entry_shape(_valid_entry(), context="t")
        assert failures == []
        assert kind == "max_turns"
        assert value == 30

    def test_non_mapping_entry_fails(self):
        failures, kind, value = check_cap_entry_shape("not a dict", context="t")
        assert failures
        assert kind is None
        assert value is None

    def test_unknown_kind_fails(self):
        failures, kind, value = check_cap_entry_shape(_valid_entry(kind="bogus_kind"), context="t")
        assert failures and any("kind" in f for f in failures)
        assert kind is None
        assert value is None

    def test_non_int_value_fails(self):
        failures, _, _ = check_cap_entry_shape(_valid_entry(value="30"), context="t")
        assert failures and any("non-int" in f for f in failures)

    def test_bool_value_fails(self):
        """bool is an int subclass in Python -- must not silently pass as a value."""
        failures, _, _ = check_cap_entry_shape(_valid_entry(value=True), context="t")
        assert failures and any("non-int" in f for f in failures)

    def test_blank_on_exhaustion_fails(self):
        failures, _, _ = check_cap_entry_shape(_valid_entry(on_exhaustion=""), context="t")
        assert failures and any("on_exhaustion" in f for f in failures)

    def test_missing_on_exhaustion_key_fails(self):
        """A non-string (here: absent, so None) on_exhaustion must fail the same as a blank one."""
        entry = _valid_entry()
        del entry["on_exhaustion"]
        failures, _, _ = check_cap_entry_shape(entry, context="t")
        assert failures and any("on_exhaustion" in f for f in failures)

    def test_blank_rationale_fails(self):
        failures, _, _ = check_cap_entry_shape(_valid_entry(rationale=""), context="t")
        assert failures and any("rationale" in f for f in failures)

    def test_floor_clause_on_exhaustion_under_min_length_fails(self):
        failures, _, _ = check_cap_entry_shape(_valid_entry(on_exhaustion="short"), context="t")
        assert failures and any("on_exhaustion" in f and "non-triviality floor" in f for f in failures)

    def test_floor_clause_rationale_equal_to_kind_name_fails(self):
        failures, _, _ = check_cap_entry_shape(_valid_entry(rationale="max_turns"), context="t")
        assert failures and any("rationale" in f and "non-triviality floor" in f for f in failures)

    def test_floor_clause_on_exhaustion_equal_to_rationale_fails(self):
        failures, _, _ = check_cap_entry_shape(_valid_entry(rationale=_LONG_ON_EXHAUSTION), context="t")
        assert failures and any("must not be equal" in f for f in failures)
