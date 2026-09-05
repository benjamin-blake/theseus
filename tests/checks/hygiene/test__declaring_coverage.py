"""Mirror of scripts/checks/hygiene/_declaring_coverage.py -- the CFG-lite declaring-coverage
walker behind the Decision 170 path-aware metric.

Every pin below is a PROPERTY over a synthetic in-memory source, never over the live fleet's
integers: the fleet's counts move with every check that adopts a declaration, so an assertion
on them would pin today's repository rather than the walker's behaviour.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from scripts.checks.hygiene._declaring_coverage import (
    UNDECIDABLE_REASONS,
    CheckCoverage,
    is_fully_declared,
    measure_check,
    measure_source,
    resolve_declaration_names,
)

_IMPORT_REGISTRY = "from scripts.checks import registry"


def _module(*body: str, header: str = _IMPORT_REGISTRY, signature: str = "def validate_probe(failed):") -> str:
    """A synthetic one-check module: `header`, then `signature` with `body` indented under it."""
    lines = [header, "", "", signature]
    lines.extend(f"    {line}" for line in body)
    return "\n".join(lines) + "\n"


def _measure(*body: str, **kwargs: str) -> CheckCoverage:
    return measure_source(_module(*body, **kwargs), "validate_probe")


def _conditional_shapes(call: str) -> tuple[tuple[str, str], ...]:
    """One statement per construct through which `call` is reachable only CONDITIONALLY: a
    lambda body, an IfExp branch, a non-first BoolOp operand, each comprehension or generator
    element, an assert's msg (evaluated only when the assertion FAILS) and a non-first Compare
    comparator (short-circuited by an earlier false comparison). Every one of them may evaluate
    `call` zero times at runtime."""
    return (
        ("lambda", f"declare = lambda n: {call}"),
        ("ifexp", f"{call} if flag else None"),
        ("boolop_and", f"flag and {call}"),
        ("boolop_or", f"flag or {call}"),
        ("listcomp", f"[{call} for _ in rows]"),
        ("setcomp", f"{{{call} for _ in rows}}"),
        ("dictcomp", f"{{{call}: 1 for _ in rows}}"),
        ("genexp", f"tuple({call} for _ in rows)"),
        ("assert_msg", f"assert flag, {call}"),
        ("compare_chain", f"x = 1 < 2 < {call}"),
    )


_DECLARATION_SHAPES = _conditional_shapes("registry.examined(1)")
_SINK_SHAPES = _conditional_shapes('failed.append("x")')
_SHAPE_IDS = [label for label, _line in _DECLARATION_SHAPES]


class TestDeclarationNameResolution:
    """Declarations are resolved through the module's OWN import aliases -- never by matching
    the bare identifier `examined`, which is the mutant this class exists to kill."""

    def test_bare_identifier_without_import_is_not_a_declaration(self) -> None:
        source = _module("examined(1)", "return", header="def examined(n):\n    return n")
        row = measure_source(source, "validate_probe")
        assert row.declared == 0
        assert row.undeclared == 1

    def test_package_import_binds_the_module_alias(self) -> None:
        names = resolve_declaration_names(ast.parse(_IMPORT_REGISTRY))
        assert names.module_aliases == frozenset({"registry"})
        assert names.direct_names == frozenset()

    def test_dotted_module_import_binds_the_full_dotted_head(self) -> None:
        names = resolve_declaration_names(ast.parse("import scripts.checks.registry"))
        assert names.module_aliases == frozenset({"scripts.checks.registry"})

    def test_direct_function_import_binds_bare_names(self) -> None:
        source = "from scripts.checks.registry import examined, skipped"
        names = resolve_declaration_names(ast.parse(source))
        assert names.direct_names == frozenset({"examined", "skipped"})

    def test_register_import_binds_a_register_name_but_no_declaration_name(self) -> None:
        names = resolve_declaration_names(ast.parse("from scripts.checks.registry import register"))
        assert names.register_names == frozenset({"register"})
        assert names.direct_names == frozenset()

    def test_unrelated_symbol_from_the_registry_module_binds_nothing(self) -> None:
        names = resolve_declaration_names(ast.parse("from scripts.checks.registry import STATUS_VOCABULARY"))
        assert names.direct_names == frozenset()
        assert names.register_names == frozenset()

    def test_unrelated_module_import_binds_nothing(self) -> None:
        names = resolve_declaration_names(ast.parse("import os\nfrom pathlib import Path"))
        assert names.module_aliases == frozenset()

    def test_declaration_on_a_non_name_chain_is_not_credited(self) -> None:
        row = _measure("get_registry().examined(1)", "return")
        assert row.declared == 0
        assert row.undeclared == 1

    def test_direct_imported_name_is_credited(self) -> None:
        header = "from scripts.checks.registry import examined"
        row = _measure("examined(1)", "return", header=header)
        assert row.declared == 1
        assert row.undeclared == 0


class TestUndeclaredBranchReported:
    """Pin (a): a success-exit path reached without a declaration is reported undeclared, and
    the same path reports declared once a declaration is inserted before it."""

    def test_undeclared_branch_is_reported(self) -> None:
        row = _measure("if flag:", "    return", "registry.examined(1)")
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_declaration_before_the_branch_makes_both_paths_declared(self) -> None:
        row = _measure("registry.examined(1)", "if flag:", "    return")
        assert row.success_exits == 2
        assert row.declared == 2
        assert row.undeclared == 0

    def test_else_branch_without_a_declaration_is_reported(self) -> None:
        row = _measure("if flag:", "    registry.examined(1)", "else:", "    pass", "return")
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_skipped_counts_as_a_declaration_too(self) -> None:
        row = _measure("registry.skipped('no input')", "return")
        assert row.declared == 1
        assert row.undeclared == 0


class TestMonotoneShrink:
    """Pin (b): inserting a declaration at the top of a body converts undeclared success exits
    into declared ones and changes neither the success-exit total nor the failure-exit total."""

    _BODY = ("rows = collect()", "if a:", "    return", "if b:", "    return", "return")

    def test_undeclared_shrinks_to_zero_and_declared_grows(self) -> None:
        before = _measure(*self._BODY)
        after = _measure("registry.examined(1)", *self._BODY)
        assert before.undeclared > 0
        assert after.undeclared == 0
        assert after.declared == before.declared + before.undeclared
        assert after.success_exits == before.success_exits

    def test_failure_exits_are_untouched_by_the_declaration(self) -> None:
        body = ("rows = collect()", "if a:", "    failed.append('x')", "    return", "return")
        before = _measure(*body)
        after = _measure("registry.examined(1)", *body)
        assert before.failure_exits == after.failure_exits == 1
        assert after.undeclared == 0


class TestFailureDominatedExit:
    """Pin (c): an exit reached after an append/extend to the callable's own first positional
    parameter, and any raise, is a FAILURE exit and never enters the success population."""

    def test_append_to_the_failed_parameter_dominates_the_exit(self) -> None:
        row = _measure("failed.append('boom')", "return")
        assert row.success_exits == 0
        assert row.declared == 0
        assert row.undeclared == 0
        assert row.failure_exits == 1

    def test_extend_of_the_failed_parameter_dominates_the_exit(self) -> None:
        row = _measure("failed.extend(['boom'])", "return")
        assert row.failure_exits == 1
        assert row.success_exits == 0

    def test_raise_is_a_failure_exit(self) -> None:
        row = _measure("raise ValueError('boom')")
        assert row.failure_exits == 1
        assert row.success_exits == 0

    def test_append_to_another_list_is_not_a_failure_sink(self) -> None:
        row = _measure("violations.append('boom')", "return")
        assert row.failure_exits == 0
        assert row.undeclared == 1

    def test_a_declared_failure_exit_is_still_a_failure_exit(self) -> None:
        row = _measure("registry.examined(1)", "failed.append('boom')", "return")
        assert row.failure_exits == 1
        assert row.declared == 0
        assert row.success_exits == 0


class TestAliasedImportRecognised:
    """Pin (f): every aliased and bare import form of the accounting API is recognised."""

    def test_aliased_package_import(self) -> None:
        row = _measure("reg.examined(1)", "return", header="from scripts.checks import registry as reg")
        assert row.declared == 1

    def test_aliased_direct_import(self) -> None:
        header = "from scripts.checks.registry import examined as ex"
        row = _measure("ex(1)", "return", header=header)
        assert row.declared == 1

    def test_aliased_dotted_module_import(self) -> None:
        row = _measure("r.skipped('x')", "return", header="import scripts.checks.registry as r")
        assert row.declared == 1

    def test_bare_dotted_module_import(self) -> None:
        row = _measure("scripts.checks.registry.examined(1)", "return", header="import scripts.checks.registry")
        assert row.declared == 1

    def test_an_alias_that_was_never_imported_is_not_credited(self) -> None:
        row = _measure("reg.examined(1)", "return")
        assert row.declared == 0
        assert row.undeclared == 1


class TestStatedCfgLiteLimits:
    """Every limit the contract's stated_cfg_lite_limits declares, pinned. Each errs toward
    reporting MORE undeclared and never toward declared, so undeclared is an UPPER bound."""

    def test_no_helper_inlining_reports_the_calling_path_undeclared(self) -> None:
        header = _IMPORT_REGISTRY + "\n\n\ndef _declare():\n    registry.examined(1)"
        row = measure_source(_module("_declare()", "return", header=header), "validate_probe")
        assert row.declared == 0
        assert row.undeclared == 1

    def test_a_nested_definition_is_out_of_the_walk(self) -> None:
        row = _measure("def _inner():", "    registry.examined(1)", "return")
        assert row.declared == 0
        assert row.undeclared == 1

    def test_a_nested_class_is_out_of_the_walk(self) -> None:
        row = _measure("class _Inner:", "    registry.examined(1)", "return")
        assert row.declared == 0
        assert row.undeclared == 1

    def test_a_handler_is_entered_from_the_try_entry_state(self) -> None:
        row = _measure("try:", "    registry.examined(1)", "except OSError:", "    pass", "return")
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_try_else_continues_from_the_body_state(self) -> None:
        body = (
            "try:",
            "    registry.examined(1)",
            "except OSError:",
            "    registry.skipped('x')",
            "    return",
            "else:",
            "    pass",
            "return",
        )
        row = _measure(*body)
        assert row.declared == 2
        assert row.undeclared == 0

    def test_finally_is_walked_from_the_joined_state(self) -> None:
        body = ("try:", "    pass", "except OSError:", "    pass", "finally:", "    registry.examined(1)", "return")
        row = _measure(*body)
        assert row.declared == 1
        assert row.undeclared == 0

    def test_break_ends_the_path_and_post_loop_code_is_walked_from_loop_entry(self) -> None:
        row = _measure("for item in items:", "    registry.examined(1)", "    break", "return")
        assert row.success_exits == 1
        assert row.undeclared == 1
        assert row.declared == 0

    def test_continue_ends_the_path(self) -> None:
        row = _measure("while flag:", "    registry.examined(1)", "    continue", "return")
        assert row.success_exits == 1
        assert row.undeclared == 1

    def test_a_loop_body_declaration_does_not_hide_the_zero_iteration_path(self) -> None:
        row = _measure("for item in items:", "    registry.examined(1)", "return")
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_loop_else_is_walked(self) -> None:
        row = _measure("for item in items:", "    pass", "else:", "    registry.examined(1)", "return")
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_match_fall_through_reaches_the_trailing_exit(self) -> None:
        body = ("match value:", "    case 1:", "        registry.examined(1)", "    case _:", "        pass", "return")
        row = _measure(*body)
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_a_bare_wildcard_case_does_not_suppress_the_implicit_fall_through(self) -> None:
        """The stated rule, pinned in the direction that costs the metric: a bare wildcard case
        with no guard is NOT treated as exhaustive, so the trailing exit is still walked from
        the match ENTRY state -- three success exits with one undeclared, never two."""
        body = (
            "match value:",
            "    case 1:",
            "        registry.examined(1)",
            "        return",
            "    case _:",
            "        registry.examined(2)",
            "        return",
            "return",
        )
        row = _measure(*body)
        assert row.success_exits == 3
        assert row.declared == 2
        assert row.undeclared == 1

    def test_a_match_without_a_wildcard_case_reports_the_same_fall_through(self) -> None:
        body = ("match value:", "    case 1:", "        registry.examined(1)", "        return", "return")
        row = _measure(*body)
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_a_guarded_wildcard_case_is_no_different(self) -> None:
        body = (
            "match value:",
            "    case _ if flag:",
            "        registry.examined(1)",
            "        return",
            "return",
        )
        row = _measure(*body)
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1

    def test_a_with_block_does_not_branch(self) -> None:
        row = _measure("with lock:", "    registry.examined(1)", "return")
        assert row.success_exits == 1
        assert row.declared == 1
        assert row.undeclared == 0

    def test_the_implicit_end_of_body_is_an_exit(self) -> None:
        row = _measure("pass")
        assert row.success_exits == 1
        assert row.undeclared == 1

    def test_a_compound_header_and_a_return_value_are_not_scanned(self) -> None:
        """The walk never scans compound-statement HEADER expressions (an if/while test and any
        walrus inside one, a for iterable, a with item, a match subject) nor a return VALUE, so
        an unconditionally-evaluated declaration in either position reads as UNDECLARED. Safe
        direction, and pinned here so the documented limit is measured rather than asserted."""
        header = _measure("if (v := registry.examined(1)):", "    pass")
        assert (header.success_exits, header.declared, header.undeclared) == (1, 0, 1)
        returned = _measure("return registry.examined(1)")
        assert (returned.success_exits, returned.declared, returned.undeclared) == (1, 0, 1)

    @pytest.mark.parametrize("line", [line for _label, line in _DECLARATION_SHAPES], ids=_SHAPE_IDS)
    def test_a_conditionally_reachable_declaration_is_not_an_effect(self, line: str) -> None:
        """A declaration reachable only through a lambda body, an IfExp branch, a non-first
        BoolOp operand or a comprehension element is NOT an effect of the statement: crediting
        it would report DECLARED for a path that may declare nothing at runtime, which inverts
        the bound. Skipping it keeps the row decidable and errs toward more undeclared."""
        row = _measure(line, "return")
        assert row.undecidable_reason is None, line
        assert (row.success_exits, row.declared, row.undeclared) == (1, 0, 1), line

    @pytest.mark.parametrize("line", [line for _label, line in _SINK_SHAPES], ids=_SHAPE_IDS)
    def test_a_conditionally_reachable_sink_does_not_dominate_the_exit(self, line: str) -> None:
        """The sink mirror image: a conditionally reachable append to the callable's own failed
        list does not make the exit failure-dominated, because doing so would REMOVE a real
        success exit from the population and hide the undeclared path it carries."""
        row = _measure(line, "return")
        assert row.failure_exits == 0, line
        assert (row.success_exits, row.declared, row.undeclared) == (1, 0, 1), line

    def test_bound_direction_holds_for_every_pinned_limit(self) -> None:
        """The whole point: no stated limit ever reports declared where the truth is
        undeclared, so declared is a LOWER bound on real declaring coverage."""
        shapes = (
            ("_declare()", "return"),
            ("def _inner():", "    registry.examined(1)", "return"),
            ("for item in items:", "    registry.examined(1)", "    break", "return"),
        )
        for body in shapes:
            row = _measure(*body)
            assert row.declared == 0, body
            assert row.undeclared >= 1, body


class TestUndecidable:
    """An undecidable construct gets its own category and ZERO exits -- never declared."""

    def test_vocabulary_is_frozen_and_exact(self) -> None:
        expected = {"opaque_decorator", "dynamic_declaration", "function_not_found", "source_unavailable"}
        assert UNDECIDABLE_REASONS == frozenset(expected)

    def test_an_extra_decorator_is_opaque(self) -> None:
        signature = "@memoize(maxsize=4)\ndef validate_probe(failed):"
        source = _module("registry.examined(1)", "return", signature=signature)
        row = measure_source(source, "validate_probe")
        assert row.undecidable_reason == "opaque_decorator"
        assert (row.success_exits, row.declared, row.undeclared, row.failure_exits) == (0, 0, 0, 0)

    def test_the_register_decorator_is_not_opaque(self) -> None:
        signature = "@registry.register('validate_probe')\ndef validate_probe(failed):"
        source = _module("registry.examined(1)", "return", signature=signature)
        row = measure_source(source, "validate_probe")
        assert row.undecidable_reason is None
        assert row.declared == 1

    def test_a_bare_register_name_decorator_is_not_opaque(self) -> None:
        header = "from scripts.checks.registry import examined, register"
        signature = "@register('validate_probe')\ndef validate_probe(failed):"
        source = _module("examined(1)", "return", header=header, signature=signature)
        row = measure_source(source, "validate_probe")
        assert row.undecidable_reason is None
        assert row.declared == 1

    def test_a_bare_unknown_decorator_is_opaque(self) -> None:
        source = _module("return", signature="@memoize\ndef validate_probe(failed):")
        assert measure_source(source, "validate_probe").undecidable_reason == "opaque_decorator"

    def test_a_getattr_declaration_is_dynamic(self) -> None:
        row = _measure("getattr(registry, 'examined')(1)", "return")
        assert row.undecidable_reason == "dynamic_declaration"
        assert row.declared == 0

    def test_an_unrelated_getattr_is_decidable(self) -> None:
        row = _measure("getattr(config, 'value')", "registry.examined(1)", "return")
        assert row.undecidable_reason is None

    def test_a_getattr_with_no_arguments_is_decidable(self) -> None:
        row = _measure("getattr()", "registry.examined(1)", "return")
        assert row.undecidable_reason is None

    def test_a_non_name_call_is_not_a_dynamic_declaration(self) -> None:
        row = _measure("helpers.getattr(registry, 'examined')", "registry.examined(1)", "return")
        assert row.undecidable_reason is None

    def test_a_missing_function_is_function_not_found(self) -> None:
        row = measure_source(_module("return"), "validate_absent")
        assert row.undecidable_reason == "function_not_found"
        assert row.check == "validate_absent"

    def test_a_nested_definition_is_never_found(self) -> None:
        row = measure_source(_module("def _inner():", "    return"), "_inner")
        assert row.undecidable_reason == "function_not_found"

    def test_unparseable_source_is_source_unavailable(self) -> None:
        row = measure_source("def (:", "validate_probe")
        assert row.undecidable_reason == "source_unavailable"

    @pytest.mark.parametrize(
        "source",
        ["x = 1\0", "x = " + "+".join(["1"] * 20000), "x = " + "-" * 20000 + "1"],
        ids=["nul_byte", "recursion_error", "parser_stack_overflow"],
    )
    def test_a_parse_failure_never_escapes_as_a_raise(self, source: str) -> None:
        """ast.parse fails in more ways than SyntaxError: a 20000-term chain exhausts the
        recursion limit (RecursionError) and a 20000-deep unary chain overflows the parser stack
        (MemoryError). A NUL byte raises SyntaxError on CPython 3.12 and ValueError on
        interpreters that predate that change, so both are caught by name. The tier dispatch
        wraps a check in no try/except, so any of these escaping would abort the whole run."""
        assert measure_source(source, "validate_probe").undecidable_reason == "source_unavailable"

    def test_a_callable_with_no_readable_source_is_source_unavailable(self) -> None:
        row = measure_check("validate_probe", len)
        assert row.undecidable_reason == "source_unavailable"
        assert row.check == "validate_probe"

    def test_every_reported_reason_is_a_vocabulary_member(self) -> None:
        rows = (
            measure_source(_module("return"), "validate_absent"),
            measure_source("def (:", "validate_probe"),
            _measure("getattr(registry, 'examined')(1)", "return"),
        )
        assert all(row.undecidable_reason in UNDECIDABLE_REASONS for row in rows)

    def test_an_undecidable_row_is_never_reported_fully_declared(self) -> None:
        """The bound-filter pin. An opaque_decorator row reports undeclared=0 only because
        nothing was walked, so the predicate a consumer uses must reject it -- reading
        undeclared == 0 off such a row would be reading an absent measurement as a bound."""
        signature = "@memoize(maxsize=4)\ndef validate_probe(failed):"
        row = measure_source(_module("registry.examined(1)", "return", signature=signature), "validate_probe")
        assert row.undecidable_reason == "opaque_decorator"
        assert row.undeclared == 0
        assert is_fully_declared(row) is False

    def test_every_undecidable_reason_is_rejected_by_the_predicate(self) -> None:
        for reason in sorted(UNDECIDABLE_REASONS):
            row = CheckCoverage(
                check="synthetic", success_exits=0, declared=0, undeclared=0, failure_exits=0, undecidable_reason=reason
            )
            assert is_fully_declared(row) is False, reason

    def test_a_populated_undecidable_row_is_rejected_on_the_reason_alone(self) -> None:
        """The undecidable conjunct, discriminated on its own: each row here carries a POSITIVE
        success-exit count with zero undeclared, so only `undecidable_reason is None` can reject
        it -- a predicate that dropped that conjunct would call these rows fully declared."""
        for reason in sorted(UNDECIDABLE_REASONS):
            row = CheckCoverage(
                check="synthetic", success_exits=2, declared=2, undeclared=0, failure_exits=0, undecidable_reason=reason
            )
            assert is_fully_declared(row) is False, reason

    def test_a_decidable_row_with_no_undeclared_exit_is_fully_declared(self) -> None:
        row = _measure("registry.examined(1)", "return")
        assert row.undecidable_reason is None
        assert is_fully_declared(row) is True

    def test_a_decidable_row_with_an_undeclared_exit_is_not_fully_declared(self) -> None:
        assert is_fully_declared(_measure("return")) is False

    def test_a_row_with_no_success_exit_at_all_is_not_fully_declared(self) -> None:
        """Zero success exits is zero evidence, so the predicate rejects it too rather than
        reading a vacuous undeclared == 0 as full declaration."""
        row = _measure("failed.append('boom')", "return")
        assert (row.success_exits, row.undeclared) == (0, 0)
        assert is_fully_declared(row) is False


class TestSignatureShapes:
    """The failure sink is the callable's FIRST POSITIONAL parameter, whatever it is named."""

    def test_a_positional_only_first_parameter_is_the_sink(self) -> None:
        signature = "def validate_probe(bucket, /, other=None):"
        row = _measure("bucket.append('x')", "return", signature=signature)
        assert row.failure_exits == 1

    def test_a_renamed_first_parameter_is_the_sink(self) -> None:
        row = _measure("problems.append('x')", "return", signature="def validate_probe(problems):")
        assert row.failure_exits == 1

    def test_a_second_parameter_is_not_the_sink(self) -> None:
        signature = "def validate_probe(failed, extra):"
        row = _measure("extra.append('x')", "return", signature=signature)
        assert row.failure_exits == 0
        assert row.undeclared == 1

    def test_a_parameterless_callable_has_no_sink(self) -> None:
        row = _measure("failed.append('x')", "return", signature="def validate_probe():")
        assert row.failure_exits == 0
        assert row.undeclared == 1

    def test_an_async_check_body_is_walked(self) -> None:
        row = _measure("registry.examined(1)", "return", signature="async def validate_probe(failed):")
        assert row.declared == 1

    def test_an_async_loop_and_async_with_are_walked(self) -> None:
        body = ("async with lock:", "    pass", "async for item in items:", "    pass", "registry.examined(1)")
        row = _measure(*body, signature="async def validate_probe(failed):")
        assert row.declared == 1
        assert row.undeclared == 0

    def test_coverage_rows_carry_the_declared_field_set(self) -> None:
        row = _measure("registry.examined(1)")
        assert isinstance(row, CheckCoverage)
        assert (row.check, row.success_exits, row.declared, row.undeclared) == ("validate_probe", 1, 1, 0)

    def test_measure_check_reads_a_real_module_from_disk(self, tmp_path: Path) -> None:
        """RE-SHAPE, not a loosening (recorded deliberately, round-2 review). This node used to
        import the LIVE validate_vacuity_justified module and assert its row was decidable,
        coupling a pin to a file this plan does not own -- a decorator or a getattr added there
        would redden it on an unrelated PR. What is pinned is unchanged in strength (measure_check
        reads a real module off DISK through importlib, resolves the callable by name, returns a
        decidable row carrying the figures that module's shape entails); only the module measured
        is now one this file writes. The LIVE fleet is still walked end to end by the sibling
        mirror's TestMeasureFleet.test_the_default_population_is_the_whole_roster."""
        path = tmp_path / "validate_on_disk.py"
        path.write_text(_module("registry.examined(1)", "if flag:", "    return", "return"), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("validate_on_disk", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        row = measure_check("validate_on_disk", module.validate_probe)
        assert row.undecidable_reason is None
        assert (row.check, row.success_exits, row.declared, row.undeclared) == ("validate_on_disk", 2, 2, 0)


class TestExhaustedLiveStateSet:
    """All four (declaration seen, failure sink seen) live STATES of the walker reach one exit
    site, so every arm of the exit classifier is exercised by a single SYNTHETIC walked body.
    Nothing here reads the live fleet -- the exhausted set is the walker's state lattice."""

    def test_all_four_states_reach_one_exit(self) -> None:
        body = ("if a:", "    registry.examined(1)", "if b:", "    failed.append('x')", "return")
        row = _measure(*body)
        assert row.success_exits == 2
        assert row.declared == 1
        assert row.undeclared == 1
        assert row.failure_exits == 2

    def test_states_are_deduped_so_the_walk_stays_bounded(self) -> None:
        body = ("if a:", "    pass", "else:", "    pass", "if b:", "    pass", "else:", "    pass", "return")
        row = _measure(*body)
        assert row.success_exits == 1
        assert row.undeclared == 1

    def test_dead_code_after_a_terminator_contributes_no_exit(self) -> None:
        row = _measure("return", "registry.examined(1)", "return")
        assert row.success_exits == 1
        assert row.undeclared == 1
        assert row.declared == 0
