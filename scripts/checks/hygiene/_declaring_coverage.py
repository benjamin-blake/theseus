"""CFG-lite declaring-coverage walker (Decision 170's deferred path-aware metric;
docs/contracts/check-accounting.yaml's path_aware_declaring_coverage key states the semantics
this module implements, and validate_declaring_coverage is its registered reporter).

Not a registered check and never decorated with registry.register -- a pure, injectable
primitives library in the scripts/checks/<domain>/_helper.py shape
(scripts/checks/iam_tf/_read_coverage.py, scripts/checks/contracts/_population.py).

WHAT IS MEASURED. For one check callable's own body: the number of reachable SUCCESS-EXIT
paths (a `return` or the implicit end-of-function reached on a path that never appended to the
callable's own `failed` list), how many of those reach an examined()/skipped() declaration
first, how many do not, and how many exits are FAILURE-dominated (a `raise`, or a `return`
after an append/extend to the first positional parameter). validate_check_accounting proves a
declaration exists somewhere in a MODULE; this walker asks the path-level question that
module-level scan cannot see.

STATED CFG-LITE LIMITS (each errs toward reporting MORE undeclared, never toward declared, so
`undeclared` is an UPPER bound and `declared` a LOWER bound):
  - No helper inlining: a declaration delegated to a module-level helper is invisible, so the
    calling path is reported UNDECLARED.
  - Nested functions/classes are OUT of the walk at any depth -- a nested `def` contributes no
    effects and its body is never walked.
  - Only the calls a statement evaluates UNCONDITIONALLY are its effects. A `lambda` body is a
    nested function and is never descended into, and a declaration (or failure sink) reachable
    only through an `IfExp` branch, a non-first `BoolOp` operand, a comprehension/generator
    element, an `Assert`'s msg (evaluated only when the assertion FAILS) or a `Compare`
    comparator after the first (short-circuited by an earlier false comparison) is NOT an effect
    of that statement. Skipping such a call keeps the row DECIDABLE and errs in the stated
    direction -- more undeclared success exits for a skipped declaration, and one more success
    exit retained in the population for a skipped sink -- whereas crediting it would report
    DECLARED for a path that may declare nothing at runtime.
  - Compound-statement HEADER expressions are never scanned at all (an `if`/`while` test and any
    walrus inside it, a `for` iterable, a `with` item, a `match` subject), and neither is a
    `return` value -- only the statements of a walked block carry effects. An unconditionally
    evaluated declaration in one of those positions therefore reads as UNDECLARED: incomplete in
    the same safe direction as every limit above, and pinned rather than left implicit.
  - An except handler is entered from the try block's ENTRY state, never from a mid-body state,
    so a declaration made inside the try body is not credited to the handler.
  - `break`/`continue` end the walked path (no exit is recorded for them), while post-loop code
    is still walked from the loop-ENTRY state, so no undeclared path is lost.
  - A `match` statement always contributes its own entry state to the fall-through set, as if no
    case matched -- INCLUDING when a bare `case _:` with no guard is present, whose implicit
    fall-through the walk deliberately does NOT suppress (see the contract's
    stated_cfg_lite_limits and TestStatedCfgLiteLimits).
  - Exits are counted per (exit site x distinct reaching state), so the walk is bounded by
    construction and needs no path budget.

Declaration-name resolution follows the module's OWN import aliases (see
resolve_declaration_names) -- never a bare-identifier match, so a module defining its own local
`examined` without importing scripts.checks.registry is not credited with a declaration.

UNDECIDABLE constructs are reported in their own category (UNDECIDABLE_REASONS) with zero
exits, never counted as declared. Such a row sits OUTSIDE the bound entirely: its `declared`
and `undeclared` are both zero because nothing was walked, so `undeclared == 0` on it is NOT
evidence of full path-declaration. Consumers must filter on `undecidable_reason is None` FIRST
-- is_fully_declared is the predicate that does so.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
from typing import Callable

UNDECIDABLE_REASONS: frozenset[str] = frozenset(
    {"opaque_decorator", "dynamic_declaration", "function_not_found", "source_unavailable"}
)

_REGISTRY_MODULE = "scripts.checks.registry"
_REGISTRY_PACKAGE = "scripts.checks"
_REGISTRY_ATTR = "registry"
_REGISTER_ATTR = "register"
_GETATTR_NAME = "getattr"
_DECLARING_ATTRS: frozenset[str] = frozenset({"examined", "skipped"})
_CONDITIONAL_SUBTREES = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SINK_ATTRS: frozenset[str] = frozenset({"append", "extend"})

# One live path's carried state: (a declaration was reached, a failure sink was reached).
_State = tuple[bool, bool]
_ENTRY_STATE: _State = (False, False)


@dataclasses.dataclass(frozen=True)
class DeclarationNames:
    """The names a single module binds to the accounting API, resolved from its own imports.

    `module_aliases` are dotted heads an `examined`/`skipped` ATTRIBUTE call may hang off
    (`registry`, `reg`, `scripts.checks.registry`); `direct_names` are bare names bound
    straight to examined()/skipped(); `register_names` are bare names bound to register().
    """

    module_aliases: frozenset[str]
    direct_names: frozenset[str]
    register_names: frozenset[str]


@dataclasses.dataclass(frozen=True)
class CheckCoverage:
    """One check's path-aware declaring coverage. An undecidable row carries all-zero counts
    and a reason drawn from UNDECIDABLE_REASONS."""

    check: str
    success_exits: int
    declared: int
    undeclared: int
    failure_exits: int
    undecidable_reason: str | None = None


@dataclasses.dataclass
class _Context:
    names: DeclarationNames
    failed_param: str | None
    success_declared: int = 0
    success_undeclared: int = 0
    failure_exits: int = 0


def _dotted(node: ast.expr) -> str | None:
    """The dotted source of an attribute/name chain (`registry`, `scripts.checks.registry`),
    or None when the chain does not bottom out in a plain name (e.g. `get_registry().examined`)."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _collect_import(node: ast.Import, aliases: set[str]) -> None:
    for alias in node.names:
        if alias.name == _REGISTRY_MODULE:
            aliases.add(alias.asname or alias.name)


def _collect_import_from(node: ast.ImportFrom, aliases: set[str], direct: set[str], registers: set[str]) -> None:
    if node.module == _REGISTRY_PACKAGE:
        for alias in node.names:
            if alias.name == _REGISTRY_ATTR:
                aliases.add(alias.asname or alias.name)
    elif node.module == _REGISTRY_MODULE:
        for alias in node.names:
            if alias.name in _DECLARING_ATTRS:
                direct.add(alias.asname or alias.name)
            elif alias.name == _REGISTER_ATTR:
                registers.add(alias.asname or alias.name)


def resolve_declaration_names(tree: ast.Module) -> DeclarationNames:
    """Resolve what THIS module calls the accounting API, from its own import statements.

    Recognised forms: `from scripts.checks import registry` (with or without an alias),
    `from scripts.checks.registry import examined, skipped, register` (with or without
    aliases), and `import scripts.checks.registry` (with or without an alias). A module that
    imports none of these binds no declaration name at all, so a bare local `examined(...)`
    call in it is NOT a declaration.
    """
    aliases: set[str] = set()
    direct: set[str] = set()
    registers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _collect_import(node, aliases)
        elif isinstance(node, ast.ImportFrom):
            _collect_import_from(node, aliases, direct, registers)
    return DeclarationNames(frozenset(aliases), frozenset(direct), frozenset(registers))


def _is_declaration_call(node: ast.Call, names: DeclarationNames) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _DECLARING_ATTRS and _dotted(func.value) in names.module_aliases
    return isinstance(func, ast.Name) and func.id in names.direct_names


def _is_failure_sink_call(node: ast.Call, failed_param: str | None) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _SINK_ATTRS
        and isinstance(func.value, ast.Name)
        and func.value.id == failed_param
    )


def _unconditional_children(node: ast.AST) -> list[ast.AST]:
    """The children evaluated EVERY time `node` is evaluated: an IfExp and an Assert evaluate
    only their test (an Assert's msg is evaluated only when the assertion FAILS), a BoolOp only
    its first operand, and a Compare only its left operand and FIRST comparator (a later
    comparator is short-circuited by an earlier false comparison), while a lambda body and a
    comprehension/generator element may be evaluated zero times, so those subtrees are dropped
    rather than descended."""
    if isinstance(node, (ast.IfExp, ast.Assert)):
        return [node.test]
    if isinstance(node, ast.BoolOp):
        return [node.values[0]]
    if isinstance(node, ast.Compare):
        return [node.left, node.comparators[0]]
    return [child for child in ast.iter_child_nodes(node) if not isinstance(child, _CONDITIONAL_SUBTREES)]


def _statement_effects(stmt: ast.stmt, ctx: _Context) -> tuple[bool, bool]:
    """(reaches a declaration, reaches a failure sink) for one SIMPLE statement, counting ONLY
    the calls that statement evaluates unconditionally -- see _unconditional_children and the
    module docstring's stated limit on conditionally reachable calls."""
    declares = False
    sinks = False
    stack: list[ast.AST] = [stmt]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            if _is_declaration_call(node, ctx.names):
                declares = True
            elif _is_failure_sink_call(node, ctx.failed_param):
                sinks = True
        stack.extend(_unconditional_children(node))
    return declares, sinks


def _record_exit(states: set[_State], ctx: _Context, *, success: bool) -> None:
    """Classify one exit site under every DISTINCT reaching state. `states` is a set and each
    block is walked exactly once, so an exit is counted per (exit site x distinct reaching
    state) by construction -- the walk is bounded and needs no path budget."""
    for declared, failure_sink in states:
        if not success or failure_sink:
            ctx.failure_exits += 1
        elif declared:
            ctx.success_declared += 1
        else:
            ctx.success_undeclared += 1


def _apply_effects(stmt: ast.stmt, states: set[_State], ctx: _Context) -> set[_State]:
    declares, sinks = _statement_effects(stmt, ctx)
    return {(declared or declares, sink or sinks) for declared, sink in states}


def _walk_if(stmt: ast.If, states: set[_State], ctx: _Context) -> set[_State]:
    out = _walk_block(stmt.body, states, ctx)
    if stmt.orelse:
        return out | _walk_block(stmt.orelse, states, ctx)
    return out | set(states)


def _walk_loop(stmt: ast.For | ast.AsyncFor | ast.While, states: set[_State], ctx: _Context) -> set[_State]:
    """The loop-ENTRY state always survives (zero iterations, or a `break`), so post-loop code is
    walked from it as well as from whatever fell out of the body."""
    out = set(states) | _walk_block(stmt.body, states, ctx)
    if stmt.orelse:
        out = out | _walk_block(stmt.orelse, out, ctx)
    return out


def _walk_try(stmt: ast.Try | ast.TryStar, states: set[_State], ctx: _Context) -> set[_State]:
    """Handlers are entered from the try block's ENTRY state -- a declaration made partway
    through the try body is never credited to a handler that may have pre-empted it."""
    entry = set(states)
    out = _walk_block(stmt.body, entry, ctx)
    if stmt.orelse:
        out = _walk_block(stmt.orelse, out, ctx)
    for handler in stmt.handlers:
        out = out | _walk_block(handler.body, entry, ctx)
    if stmt.finalbody:
        out = _walk_block(stmt.finalbody, out, ctx)
    return out


def _walk_match(stmt: ast.Match, states: set[_State], ctx: _Context) -> set[_State]:
    """Fall-through is always modelled: the entry state survives as if no case matched."""
    out = set(states)
    for case in stmt.cases:
        out = out | _walk_block(case.body, states, ctx)
    return out


def _walk_stmt(stmt: ast.stmt, states: set[_State], ctx: _Context) -> set[_State]:
    """Explicit isinstance chain, deliberately not a node-type lookup table (a table keyed on
    AST node types does not type-check: ast.stmt is not ast.If)."""
    if isinstance(stmt, ast.Return):
        _record_exit(states, ctx, success=True)
        return set()
    if isinstance(stmt, ast.Raise):
        _record_exit(states, ctx, success=False)
        return set()
    if isinstance(stmt, (ast.Break, ast.Continue)):
        return set()
    if isinstance(stmt, ast.If):
        return _walk_if(stmt, states, ctx)
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        return _walk_loop(stmt, states, ctx)
    if isinstance(stmt, (ast.Try, ast.TryStar)):
        return _walk_try(stmt, states, ctx)
    if isinstance(stmt, ast.Match):
        return _walk_match(stmt, states, ctx)
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return _walk_block(stmt.body, states, ctx)
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return set(states)
    return _apply_effects(stmt, states, ctx)


def _walk_block(body: list[ast.stmt], states: set[_State], ctx: _Context) -> set[_State]:
    live = set(states)
    for stmt in body:
        live = _walk_stmt(stmt, live, ctx)
    return live


def _find_function(tree: ast.Module, function_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    return None


def _decorator_is_register(node: ast.expr, names: DeclarationNames) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr == _REGISTER_ATTR and _dotted(target.value) in names.module_aliases
    return isinstance(target, ast.Name) and target.id in names.register_names


def _has_opaque_decorator(fn_node: ast.FunctionDef | ast.AsyncFunctionDef, names: DeclarationNames) -> bool:
    return any(not _decorator_is_register(decorator, names) for decorator in fn_node.decorator_list)


def _has_dynamic_declaration(fn_node: ast.FunctionDef | ast.AsyncFunctionDef, names: DeclarationNames) -> bool:
    """A getattr() on the registry module hides which declaration (if any) is being made.

    Deliberately ast.walk over the WHOLE function subtree -- nested definitions and
    conditionally reached subtrees included -- so a getattr on the registry anywhere inside the
    check marks the whole check dynamic_declaration. That over-reaches in the stated direction
    only: an undecidable row is never counted as declared, so it can cost declared coverage and
    never manufacture it."""
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != _GETATTR_NAME:
            continue
        if node.args and _dotted(node.args[0]) in names.module_aliases:
            return True
    return False


def _first_param(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    positional = [*fn_node.args.posonlyargs, *fn_node.args.args]
    if not positional:
        return None
    return positional[0].arg


def undecidable(check: str, reason: str) -> CheckCoverage:
    """An all-zero row carrying one UNDECIDABLE_REASONS member -- never counted as declared."""
    return CheckCoverage(check=check, success_exits=0, declared=0, undeclared=0, failure_exits=0, undecidable_reason=reason)


def is_fully_declared(row: CheckCoverage) -> bool:
    """Whether one row is EVIDENCE that every success-exit path reaches a declaration.

    The bound-direction filter every consumer owes (a later roster-shrink slice included):
    `declared`/`undeclared` are evidence only when `undecidable_reason` is None, because an
    undecidable row reports success_exits=0, declared=0, undeclared=0 with the reason set --
    its `undeclared == 0` is the absence of a measurement, not a full-declaration verdict. True
    iff the row is decidable, reaches at least one success exit, and none of them is undeclared.
    """
    return row.undecidable_reason is None and row.success_exits >= 1 and row.undeclared == 0


def _walk_function(fn_node: ast.FunctionDef | ast.AsyncFunctionDef, names: DeclarationNames, check: str) -> CheckCoverage:
    ctx = _Context(names=names, failed_param=_first_param(fn_node))
    live = _walk_block(fn_node.body, {_ENTRY_STATE}, ctx)
    _record_exit(live, ctx, success=True)
    return CheckCoverage(
        check=check,
        success_exits=ctx.success_declared + ctx.success_undeclared,
        declared=ctx.success_declared,
        undeclared=ctx.success_undeclared,
        failure_exits=ctx.failure_exits,
        undecidable_reason=None,
    )


def measure_source(source: str, function_name: str, *, check: str | None = None) -> CheckCoverage:
    """Path-aware declaring coverage for `function_name` as defined at `source`'s TOP LEVEL.

    A nested definition is never found here (nested functions are out of the walk at any
    depth), so it reports function_not_found rather than a misleading zero.

    ast.parse fails in more ways than SyntaxError, and a report-only check is dispatched with no
    try/except (scripts/validation_result.py), so a parse failure that escaped would abort the
    whole tier. Every one of them is caught BY NAME and routed to the existing
    source_unavailable reason -- the frozen four-member vocabulary already covers unparseable
    source, so none is added: SyntaxError (malformed source, and a NUL byte on CPython 3.12),
    ValueError (the same NUL byte on interpreters predating that change), RecursionError (a long
    enough operand chain) and MemoryError (the parser's own stack overflowing on a deeply nested
    expression, reported as "Parser stack overflowed").
    """
    name = check if check is not None else function_name
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return undecidable(name, "source_unavailable")
    names = resolve_declaration_names(tree)
    fn_node = _find_function(tree, function_name)
    if fn_node is None:
        return undecidable(name, "function_not_found")
    if _has_opaque_decorator(fn_node, names):
        return undecidable(name, "opaque_decorator")
    if _has_dynamic_declaration(fn_node, names):
        return undecidable(name, "dynamic_declaration")
    return _walk_function(fn_node, names, name)


def measure_check(check: str, fn: Callable[..., object]) -> CheckCoverage:
    """Path-aware declaring coverage for one resolved check callable, read from its own source
    file. An unreadable or non-Python callable (a C builtin, a deleted file) reports
    source_unavailable rather than a silently-zero row."""
    try:
        source = Path(inspect.getsourcefile(fn) or "").read_text(encoding="utf-8")
    except (OSError, TypeError):
        return undecidable(check, "source_unavailable")
    return measure_source(source, fn.__name__, check=check)
