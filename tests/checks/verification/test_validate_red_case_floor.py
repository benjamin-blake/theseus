"""Tests for validate_red_case_floor() and red_case_hits() (audit finding LSA-03).

This is itself a mirror test in the floor's own derived population -- TestSelfApplication proves
the floor judges its own mirror (this file) and clears it, so a floor that flagged every check
including itself would be the exact tautology-detector-that-is-itself-a-tautology this slice
exists to rule out.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts import test_coverage_checker as tcc
from scripts.checks import registry
from scripts.checks._schema import Entry
from scripts.checks.verification import validate_red_case_floor as floor
from scripts.checks.verification.validate_red_case_floor import (
    _mirror_test_files,
    red_case_hits,
    validate_red_case_floor,
)


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


class TestFloorOnSyntheticMirror:
    """The audit's acceptance criterion verbatim (Q5 seed 6): a passing-path-only mirror is
    flagged; the same file plus one red-case test clears it. Both halves against the same
    fixture pair, so a floor that flags everything and a floor that flags nothing each red
    exactly one half."""

    _PASSING = (
        "from pathlib import Path\n\n\n"
        "def _run(tmp_path: Path) -> list[str]:\n"
        "    failed: list[str] = []\n"
        "    validate_synth(failed, root=tmp_path)\n"
        "    return failed\n\n\n"
        "class TestSynth:\n"
        "    def test_clean_tree_passes(self, tmp_path: Path) -> None:\n"
        "        assert _run(tmp_path) == []\n\n"
        "    def test_empty_tree_passes(self, tmp_path: Path) -> None:\n"
        "        failed: list[str] = []\n"
        "        validate_synth(failed, root=tmp_path)\n"
        "        assert not failed\n"
        "        assert len(failed) == 0\n\n"
        "    def test_marker_constant(self) -> None:\n"
        "        assert MARKER == '# synth:'\n"
    )

    def test_passing_path_only_mirror_is_not_cleared(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "test_passing_only.py", self._PASSING)
        assert red_case_hits(p, "validate_synth") == []

    def test_one_red_case_added_clears_it(self, tmp_path: Path) -> None:
        source = self._PASSING + (
            "\n    def test_bad_tree_is_flagged(self, tmp_path: Path) -> None:\n"
            "        assert _run(tmp_path) == ['synth check']\n"
        )
        p = _write(tmp_path, "test_with_red.py", source)
        hits = red_case_hits(p, "validate_synth")
        assert len(hits) == 1


class TestNegatedFormsNeverCount:
    """Every negated/empty-side form is asserted individually to yield no red case, over a corpus
    carrying each one -- the guard against the floor decaying into a test-name grep."""

    _FORMS = (
        "assert not failed",
        "assert failed == []",
        "assert failed == {}",
        "assert failed == ''",
        "assert failed is None",
        "assert failed is False",
        "assert len(failed) == 0",
        "assert 'x' not in failed",
        "assert all(x for x in failed)",
    )

    def test_no_negated_form_counts(self, tmp_path: Path) -> None:
        for i, form in enumerate(self._FORMS):
            source = (
                "def test_detects_the_bad_thing(tmp_path):\n"
                "    failed = []\n"
                "    validate_synth(failed, root=tmp_path)\n"
                f"    {form}\n"
            )
            p = _write(tmp_path, f"test_negated_{i}.py", source)
            assert red_case_hits(p, "validate_synth") == [], form

    def test_name_suggestive_test_with_only_a_negated_body_does_not_clear(self, tmp_path: Path) -> None:
        source = (
            "def test_detects_the_bad_thing(tmp_path):\n"
            "    failed = []\n"
            "    validate_synth(failed, root=tmp_path)\n"
            "    assert not failed\n"
        )
        p = _write(tmp_path, "test_name_trap.py", source)
        assert red_case_hits(p, "validate_synth") == []


class TestOneHopHelperDerivation:
    """Live-corpus shape: `assert self._run(tmp_path) == [...]` and a plain module-level helper --
    derivation reaches one hop through a same-file non-test helper."""

    def test_module_level_helper_bare_call_in_assert(self, tmp_path: Path) -> None:
        source = (
            "def _run(tmp_path):\n"
            "    failed = []\n"
            "    validate_x(failed)\n"
            "    return failed\n\n\n"
            "def test_bad(tmp_path):\n"
            "    assert _run(tmp_path) == ['bad']\n"
        )
        p = _write(tmp_path, "test_helper.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_self_method_helper(self, tmp_path: Path) -> None:
        source = (
            "class TestThing:\n"
            "    def _run(self, tmp_path):\n"
            "        failed = []\n"
            "        validate_x(failed)\n"
            "        return failed\n\n"
            "    def test_bad(self, tmp_path):\n"
            "        assert self._run(tmp_path) == ['bad']\n"
        )
        p = _write(tmp_path, "test_self_helper.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_accumulator_passed_through_helper_by_name(self, tmp_path: Path) -> None:
        """The one-hop rule also covers an accumulator NAME passed to a helper (not just the
        helper's return value): `helper(failed)` then `assert failed == [...]`."""
        source = (
            "def _run(failed):\n"
            "    validate_x(failed)\n\n\n"
            "def test_bad():\n"
            "    failed = []\n"
            "    _run(failed)\n"
            "    assert failed == ['bad']\n"
        )
        p = _write(tmp_path, "test_helper_arg.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_helper_that_never_invokes_the_check_does_not_count(self, tmp_path: Path) -> None:
        source = (
            "def _unrelated(tmp_path):\n"
            "    return ['bad']\n\n\n"
            "def test_bad(tmp_path):\n"
            "    assert _unrelated(tmp_path) == ['bad']\n"
        )
        p = _write(tmp_path, "test_unrelated_helper.py", source)
        assert red_case_hits(p, "validate_x") == []


class TestModuleAliasDerivation:
    """Live-corpus shape (tests/checks/hygiene/test_validate_raises_discrimination.py): a helper
    invoking a SIBLING function of the check's own defining module via the module alias --
    `guard.hits(...)` where `import ...validate_x as guard` -- counts as invoking the check."""

    def test_module_alias_attribute_call_via_helper(self, tmp_path: Path) -> None:
        source = (
            "import scripts.checks.fake.validate_x as guard\n\n\n"
            "def _hit_count(tmp_path, body):\n"
            "    return len(guard.hits(body))\n\n\n"
            "def test_bad(tmp_path):\n"
            "    assert _hit_count(tmp_path, 'body') == 1\n"
        )
        p = _write(tmp_path, "test_module_alias.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_direct_import_sibling_name(self, tmp_path: Path) -> None:
        """`from ...validate_x import validate_x, hits` -- a sibling name imported alongside the
        check's own attr counts too, called bare (no helper hop needed)."""
        source = (
            "from scripts.checks.fake.validate_x import hits, validate_x\n\n\n"
            "def test_bad():\n"
            "    assert hits(['a']) == ['a']\n"
        )
        p = _write(tmp_path, "test_sibling_import.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_bare_import_without_alias_does_not_register_a_module_alias(self, tmp_path: Path) -> None:
        """`import scripts.checks.fake.validate_x` (no `as`) binds the dotted path's own name
        chain, not a single-token alias this floor's simplified alias rule tracks -- confirms the
        module-alias branch requires an explicit `as` binding rather than crashing on its absence."""
        source = "import scripts.checks.fake.validate_x\n\n\ndef test_ok():\n    assert True\n"
        p = _write(tmp_path, "test_bare_import.py", source)
        assert red_case_hits(p, "validate_x") == []


class TestAttributeAnyBaseDirect:
    """`<anything>.attr_name(...)` is a direct (zero-hop) invocation regardless of the base
    expression -- covers `self.validate_x(...)` (including a staticmethod-aliased class
    attribute) and `cls.validate_x(...)` alike."""

    def test_self_dot_attr_name_direct_call(self, tmp_path: Path) -> None:
        source = (
            "class TestThing:\n"
            "    validate_x = staticmethod(guard.validate_x)\n\n"
            "    def test_bad(self):\n"
            "        failed = []\n"
            "        self.validate_x(failed)\n"
            "        assert failed == ['bad']\n"
        )
        p = _write(tmp_path, "test_staticmethod_alias.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1


class TestPositiveOutcomeForms:
    """Every enumerated positive shape: non-empty container/string, non-zero int, True, `X in
    derived`, subscript/attribute access on a derived value, `any(...)`, plus the reversed-operand
    (`literal == derived`) direction for each comparison family."""

    @staticmethod
    def _hits(tmp_path: Path, assertion: str) -> list[str]:
        source = f"def test_bad():\n    failed = []\n    validate_x(failed)\n    {assertion}\n"
        p = _write(tmp_path, "test_positive.py", source)
        return red_case_hits(p, "validate_x")

    def test_non_empty_string_literal(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed == 'bad'")) == 1

    def test_non_zero_int_literal(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed == 3")) == 1

    def test_zero_int_literal_does_not_count(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert failed == 0") == []

    def test_is_true(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed is True")) == 1

    def test_is_not_none(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed is not None")) == 1

    def test_x_in_derived(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert 'bad' in failed")) == 1

    def test_not_equal_to_empty(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed != []")) == 1

    def test_len_greater_than_zero(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert len(failed) > 0")) == 1

    def test_len_greater_equal_one(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert len(failed) >= 1")) == 1

    def test_len_less_than_never_counts(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert len(failed) < 5") == []

    def test_len_non_int_other_side_is_not_classified(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert len(failed) == some_other_name") == []

    def test_reversed_equality_literal_first(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert ['bad'] == failed")) == 1

    def test_reversed_len_compare(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert 0 < len(failed)")) == 1

    def test_len_not_equal_zero(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert len(failed) != 0")) == 1

    def test_non_len_wrapped_derived_int_greater_than_zero(self, tmp_path: Path) -> None:
        """Live-corpus shape (`_hit_count` returns `len(...)` directly, then the assert compares
        the HELPER's own return value with `>`/`==`, never re-wrapping it in `len()` at the assert
        site) -- covers the plain Gt/GtE-on-a-directly-derived-value branch, distinct from the
        `len(<derived>) > 0` special case above."""
        source = (
            "def _count():\n"
            "    failed = []\n"
            "    validate_x(failed)\n"
            "    return len(failed)\n\n\n"
            "def test_bad():\n"
            "    assert _count() > 0\n"
        )
        p = _write(tmp_path, "test_direct_gt.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_non_len_wrapped_derived_int_less_than_never_counts(self, tmp_path: Path) -> None:
        source = (
            "def _count():\n"
            "    failed = []\n"
            "    validate_x(failed)\n"
            "    return len(failed)\n\n\n"
            "def test_bad():\n"
            "    assert _count() < 5\n"
        )
        p = _write(tmp_path, "test_direct_lt.py", source)
        assert red_case_hits(p, "validate_x") == []

    def test_bytes_literal_is_not_a_recognised_polarity_shape(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert failed == b'x'") == []

    def test_any_with_no_arguments_is_not_classified(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert any()") == []

    def test_any_over_a_non_iterable_shaped_argument_is_not_classified(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert any([1, 2, 3])") == []

    def test_subscript_on_derived_used_bare(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed[0]")) == 1

    def test_attribute_on_derived_used_bare(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed.anything")) == 1

    def test_subscript_on_derived_compared_to_string(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert failed[0] == 'bad'")) == 1

    def test_any_over_derived_generator(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert any(x == 'bad' for x in failed)")) == 1

    def test_any_over_derived_bare_name(self, tmp_path: Path) -> None:
        assert len(self._hits(tmp_path, "assert any(failed)")) == 1

    def test_all_over_derived_never_counts(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert all(x for x in failed)") == []

    def test_any_over_non_derived_iterable_does_not_count(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert any(x for x in [1, 2])") == []

    def test_unrelated_name_equality_is_irrelevant(self, tmp_path: Path) -> None:
        assert self._hits(tmp_path, "assert MARKER == 'x'") == []

    def test_direct_call_result_used_inline_without_binding(self, tmp_path: Path) -> None:
        source = "def test_bad():\n    assert validate_x([]) == ['bad']\n"
        p = _write(tmp_path, "test_inline_call.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_derived_via_assignment_from_call_return(self, tmp_path: Path) -> None:
        source = "def _run():\n    return validate_x([])\n\n\ndef test_bad():\n    x = _run()\n    assert x == ['bad']\n"
        p = _write(tmp_path, "test_assign_from_call.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_assignment_from_unrelated_call_is_not_derived(self, tmp_path: Path) -> None:
        source = "def test_bad():\n    x = list()\n    assert x == ['bad']\n"
        p = _write(tmp_path, "test_assign_unrelated.py", source)
        assert red_case_hits(p, "validate_x") == []


class TestPytestRaisesRedCase:
    """`with pytest.raises(...)` whose body invokes the check under test is ALSO a red case,
    independent of any assert."""

    def test_pytest_dot_raises_with_direct_invocation(self, tmp_path: Path) -> None:
        source = "import pytest\n\n\ndef test_bad():\n    with pytest.raises(ValueError):\n        validate_x([])\n"
        p = _write(tmp_path, "test_raises.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_aliased_raises_import(self, tmp_path: Path) -> None:
        source = (
            "from pytest import raises as expect_raises\n\n\n"
            "def test_bad():\n"
            "    with expect_raises(ValueError):\n"
            "        validate_x([])\n"
        )
        p = _write(tmp_path, "test_raises_alias.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1

    def test_raises_block_that_never_invokes_the_check_does_not_count(self, tmp_path: Path) -> None:
        source = "import pytest\n\n\ndef test_bad():\n    with pytest.raises(ValueError):\n        int('x')\n"
        p = _write(tmp_path, "test_raises_unrelated.py", source)
        assert red_case_hits(p, "validate_x") == []

    def test_with_block_whose_context_expr_is_not_a_call_does_not_count(self, tmp_path: Path) -> None:
        """`with foo:` (a bare name, no call at all) is a legal with-statement shape distinct from
        `with foo(...):` -- exercises the non-Call guard in the raises-detector."""
        source = "def test_bad():\n    with foo:\n        validate_x([])\n"
        p = _write(tmp_path, "test_bare_with.py", source)
        assert red_case_hits(p, "validate_x") == []

    def test_unrelated_with_block_does_not_count(self, tmp_path: Path) -> None:
        source = (
            "from unittest.mock import patch\n\n\n"
            "def test_bad(tmp_path):\n"
            "    with patch('os.getcwd'):\n"
            "        validate_x([])\n"
        )
        p = _write(tmp_path, "test_unrelated_with.py", source)
        assert red_case_hits(p, "validate_x") == []


class TestUnparseableOrMissingMirror:
    """A missing, unreadable or unparseable mirror never raises -- it yields [] at this layer, so
    the CALLER's own existence check (never this function) is what turns it into a failure."""

    def test_nonexistent_path_yields_no_hits(self, tmp_path: Path) -> None:
        assert red_case_hits(tmp_path / "does_not_exist.py", "validate_x") == []

    def test_syntax_error_yields_no_hits(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "test_broken.py", "def test_x(:\n    pass\n")
        assert red_case_hits(p, "validate_x") == []

    def test_bad_encoding_yields_no_hits(self, tmp_path: Path) -> None:
        p = tmp_path / "test_bad_encoding.py"
        p.write_bytes(b"\xff\xfe\x00\x01 not valid utf-8 sequence \x80\x81")
        assert red_case_hits(p, "validate_x") == []


class TestCacheSharing:
    """A caller-supplied `_cache` lets one parse serve several lookups against the same mirror
    FILE -- several Entries can share a mirror package."""

    def test_repeated_lookup_with_shared_cache_yields_consistent_results(self, tmp_path: Path) -> None:
        source = "def test_bad():\n    failed = []\n    validate_x(failed)\n    assert failed == ['bad']\n"
        p = _write(tmp_path, "test_cached.py", source)
        cache: dict = {}
        first = red_case_hits(p, "validate_x", _cache=cache)
        assert str(p) in cache
        second = red_case_hits(p, "validate_x", _cache=cache)
        assert first == second and len(first) == 1

    def test_default_cache_is_fresh_each_call(self, tmp_path: Path) -> None:
        source = "def test_bad():\n    failed = []\n    validate_x(failed)\n    assert failed == ['bad']\n"
        p = _write(tmp_path, "test_no_cache.py", source)
        assert len(red_case_hits(p, "validate_x")) == 1


class TestLenCompareFallbackShape:
    """`len(<derived>) <op> <int>` for an op this shape does not specifically recognise (neither
    an equality nor an ordering the floor treats as a count) falls through to "not a hit" rather
    than raising or mis-classifying -- probed here because it is a real, reachable branch that a
    normal positive-form test never exercises."""

    def test_len_compare_with_an_unrecognised_operator_is_not_a_hit(self, tmp_path: Path) -> None:
        source = "def test_bad():\n    failed = []\n    validate_x(failed)\n    assert len(failed) in 5\n"
        p = _write(tmp_path, "test_len_in.py", source)
        assert red_case_hits(p, "validate_x") == []


def _entry(name: str, module: str, attr: str | None = None) -> Entry:
    return Entry(name=name, module=module, attr=attr or name)


class TestPopulationIsDerived:
    """The protected population is read from registry._ALL_ENTRIES at CALL TIME, patchable --
    never enumerated, never snapshotted at import time (acceptance criterion 1)."""

    def test_examines_exactly_the_patched_population_size(self) -> None:
        entries = {"validate_thing": _entry("validate_thing", "scripts.checks.fake.validate_thing")}
        with patch.object(registry, "_ALL_ENTRIES", entries):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "registered_checks"
        assert declaration.count == 1

    def test_a_second_disjoint_population_examines_its_own_size(self) -> None:
        entries = {
            "validate_a": _entry("validate_a", "scripts.checks.fake.validate_a"),
            "validate_b": _entry("validate_b", "scripts.checks.fake.validate_b"),
        }
        with patch.object(registry, "_ALL_ENTRIES", entries):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                declaration = registry.pop_declaration()
        assert declaration is not None and declaration.count == 2


class TestUnresolvableMirrorFails:
    """An Entry whose mirror cannot be resolved, or resolves to a missing file/empty package, is
    a FAILURE and never a skip (Decision 55: a missing oracle and a satisfied oracle must not look
    the same)."""

    def test_entry_with_no_resolvable_mirror_fails(self) -> None:
        entries = {"validate_ghost": _entry("validate_ghost", "scripts.checks.fake.validate_ghost")}
        with patch.object(registry, "_ALL_ENTRIES", entries):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                detail = registry.pop_failure_detail()
        assert failed != []
        assert detail is not None and len(detail) == 1
        assert "validate_ghost" in detail[0]

    def test_mirror_files_none_when_map_resolves_to_none(self) -> None:
        with patch.object(tcc, "map_source_to_test", lambda p: None):
            assert _mirror_test_files("scripts.checks.fake.validate_x") == []

    def test_mirror_files_empty_when_py_target_missing(self, tmp_path: Path) -> None:
        with patch.object(tcc, "map_source_to_test", lambda p: tmp_path / "test_missing.py"):
            assert _mirror_test_files("scripts.checks.fake.validate_x") == []

    def test_mirror_files_empty_when_package_directory_has_no_test_modules(self, tmp_path: Path) -> None:
        pkg = tmp_path / "empty_pkg"
        pkg.mkdir()
        with patch.object(tcc, "map_source_to_test", lambda p: pkg):
            assert _mirror_test_files("scripts.checks.fake.validate_x") == []

    def test_mirror_files_lists_every_test_module_in_a_populated_package(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
        (pkg / "test_b.py").write_text("def test_b():\n    pass\n", encoding="utf-8")
        with patch.object(tcc, "map_source_to_test", lambda p: pkg):
            files = _mirror_test_files("scripts.checks.fake.validate_x")
        assert [f.name for f in files] == ["test_a.py", "test_b.py"]

    def test_a_populated_package_where_only_the_second_file_carries_the_red_case_still_clears(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg2"
        pkg.mkdir()
        (pkg / "test_a.py").write_text("def test_passes():\n    assert True\n", encoding="utf-8")
        (pkg / "test_b.py").write_text(
            "def test_bad():\n    failed = []\n    validate_x(failed)\n    assert failed == ['bad']\n", encoding="utf-8"
        )
        entries = {"validate_x": _entry("validate_x", "scripts.checks.fake.validate_x")}
        with patch.object(tcc, "map_source_to_test", lambda p: pkg), patch.object(registry, "_ALL_ENTRIES", entries):
            failed: list[str] = []
            validate_red_case_floor(failed)
        assert failed == []


class TestFleetWiring:
    """The registered check must CONSULT red_case_hits' verdict rather than merely shipping it,
    and mirror resolution must go through the canonical map and NOTHING else (acceptance
    criterion 6's negative claim, made executable)."""

    def test_starving_red_case_hits_fails_an_entry_with_a_real_conforming_mirror(self) -> None:
        real_entry = registry._ALL_ENTRIES["validate_red_case_floor"]
        one = {"validate_red_case_floor": real_entry}
        with patch.object(registry, "_ALL_ENTRIES", one), patch.object(floor, "red_case_hits", lambda *a, **k: []):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                detail = registry.pop_failure_detail()
        assert failed != []
        assert detail is not None and len(detail) == 1

    def test_neutering_the_canonical_map_fails_every_entry(self) -> None:
        with patch.object(tcc, "map_source_to_test", lambda p: Path("tests/checks/no_such_dir/test_no_such_mirror.py")):
            failed: list[str] = []
            with registry.outcome_scope("validate_red_case_floor"):
                validate_red_case_floor(failed)
                declaration = registry.pop_declaration()
                detail = registry.pop_failure_detail()
        assert declaration is not None
        assert detail is not None
        assert len(detail) == declaration.count


class TestSelfApplication:
    """Self-hosting (acceptance criterion 9): validate_red_case_floor is itself a registered
    Entry, in its own derived population, judging its own mirror -- this very file."""

    def test_the_floor_is_registered(self) -> None:
        assert "validate_red_case_floor" in registry._ALL_ENTRIES

    def test_the_floor_judges_its_own_mirror_and_clears_it(self) -> None:
        entry = registry._ALL_ENTRIES["validate_red_case_floor"]
        with patch.object(registry, "_ALL_ENTRIES", {"validate_red_case_floor": entry}):
            failed: list[str] = []
            validate_red_case_floor(failed)
        assert failed == []

    def test_calling_the_real_check_against_a_ghost_entry_flags_it(self) -> None:
        """The assertion that makes THIS file itself satisfy the floor for its own Entry: a bare,
        direct call to `validate_red_case_floor` whose asserted outcome is non-empty."""
        entries = {"validate_ghost_self": _entry("validate_ghost_self", "scripts.checks.fake.validate_ghost_self")}
        with patch.object(registry, "_ALL_ENTRIES", entries):
            failed: list[str] = []
            validate_red_case_floor(failed)
        assert failed != []


class TestLiveFleet:
    """Anti-vacuous: exercised against the REAL live registry at least once, not only synthetic
    populations (mirrors VP step 2)."""

    def test_real_fleet_is_clean_with_no_grandfather_hook(self) -> None:
        failed: list[str] = []
        with registry.outcome_scope("validate_red_case_floor"):
            validate_red_case_floor(failed)
            declaration = registry.pop_declaration()
        assert failed == [], failed
        assert declaration is not None
        assert declaration.count == len(registry._ALL_ENTRIES)
        assert declaration.count >= 123
