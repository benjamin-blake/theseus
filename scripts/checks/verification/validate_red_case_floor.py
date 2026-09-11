"""Registry-level red-case floor (audit finding LSA-03, Decision 163 point 1, Decision 170).

Fleet-level detection-quality gap this closes: Decision 170 accounting proves a check examined
inputs, selection proves it was reachable, and the differential admission gate proves
discrimination for the GRADUATED shard population only -- none of the three notices a check whose
mirror test has decayed to a tautology (every assertion expects the check to find nothing) while
still examining inputs and still passing. This module is the fleet-wide floor: every registered
Entry's mirror test must exercise at least one FAILING path of the check under test.

Population (acceptance criterion 1): read from ``registry._ALL_ENTRIES`` INSIDE the function body,
at CALL TIME -- never bound at module scope, never enumerated in a roster. A check registered
tomorrow joins the protected population the moment its Entry lands, with no second edit.

Mirror resolution (acceptance criterion 6): goes through
``scripts.test_coverage_checker.map_source_to_test`` and NOTHING else -- reached through the
``test_coverage_checker`` MODULE OBJECT (``from scripts import test_coverage_checker as tcc`` then
``tcc.map_source_to_test(...)``), never a ``from scripts.test_coverage_checker import
map_source_to_test`` binding, so a test can intercept it with ``patch.object(tcc,
'map_source_to_test', ...)`` -- the documented scripts/checks/misc/coverage_baseline.py pattern.
An Entry whose mirror cannot be resolved, or resolves to a missing file or an empty concern-split
package, FAILS -- never a skip (Decision 55: a missing oracle and a satisfied oracle must not look
the same).

Red-case signal (``red_case_hits``, acceptance criteria 3-4): a purely syntactic, per-mirror-FILE
AST scan (parsed once per file and cached -- several Entries can share a mirror package). An
``assert`` counts as a red case only when BOTH hold:

1. Its subject is DERIVED from an invocation of the check under test: a name bound as an argument
   to, or assigned from the return of, a call that invokes the check -- either directly (a bare
   call to the registered ``attr``, or ``<anything>.<attr>(...)`` regardless of the base
   expression, e.g. ``self.validate_x(...)``) or via a call into ANY OTHER symbol of the check's
   own defining module (module-alias attribute access, e.g. ``guard.hits(...)`` where ``guard`` is
   ``import ...validate_x as guard``, or a sibling name pulled in by the same
   ``from ...validate_x import a, b``) -- or ONE HOP through a same-file non-test helper whose own
   body invokes the check by either of those same rules. A bare Subscript/Attribute on such a
   derived value (e.g. ``derived[0]``) is itself treated as derived, recursively.
2. Its asserted outcome is POSITIVE: a non-empty container/tuple/dict literal, a non-zero int, a
   non-empty string, ``True``, ``X in <derived>``, a subscript/attribute access on a derived value
   used as the whole assertion, or ``any(...)`` over a derived iterable. A ``with pytest.raises(
   ...)`` block whose body invokes the check (directly or one hop) is ALSO a red case, independent
   of any assert.

Negated and empty-side forms NEVER count, by construction rather than by a denylist that could
decay: ``assert not X``, ``== []``/``== {}``/``== ()``/``== ''``, ``is None``, ``is False``,
``len(X) == 0``, ``X not in Y``, and ``all(...)`` (empty-vacuous-true, unlike ``any``) all fail the
positive-outcome test above and so are never hits.

No marker escape and no grandfather hook (acceptance criterion 7, Decision 163 point 1 deliberately
chosen over a discretionary exception path): every reachable exit declares
``examined(len(entries), unit="registered_checks")`` (Decision 170) -- this module is never added
to config/check_accounting_baseline.yaml, which is shrink-only.

Efficacy is explicitly OUT OF SCOPE: this floor proves red-case SHAPE (at least one assertion
expects a failing outcome), never that the fixture is a genuinely effective one that would catch a
broken check (that is P4 leg 3, T3.7's scheduled alarm lane, per CD.12).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from scripts import test_coverage_checker as tcc
from scripts.checks import _common, registry

_ANY_ALL_NAMES = ("any", "all")


@dataclasses.dataclass(frozen=True)
class _Context:
    """Everything the classifiers need to decide "does this call/name invoke the check", derived
    once per mirror file (never per assert) by _resolve_check_namespace/_invoking_helper_names."""

    attr_name: str
    direct_names: frozenset[str]
    module_aliases: frozenset[str]
    helper_names: frozenset[str]
    raises_names: frozenset[str]


def _resolve_check_namespace(tree: ast.Module, attr_name: str) -> tuple[set[str], set[str]]:
    """Names that, called bare, invoke the check (`direct_names`, seeded with `attr_name` itself
    plus every sibling name imported alongside it), and module aliases whose ANY attribute call
    also counts (`module_aliases`, e.g. `guard` in `import ...validate_x as guard`). Purely
    syntactic: reads the mirror's own import statements, never imports anything."""
    direct_names: set[str] = {attr_name}
    module_aliases: set[str] = set()
    check_module: str | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and any(alias.name == attr_name for alias in node.names):
            check_module = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] == attr_name:
                    check_module = alias.name

    if check_module is None:
        return direct_names, module_aliases

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == check_module:
            for alias in node.names:
                local = alias.asname or alias.name
                direct_names.add(local)
                if alias.name == attr_name:
                    # `from <package> import <attr_name> as X` also covers the repo's "from
                    # PACKAGE import SUBMODULE as X" shape (module basename == attr name by
                    # convention): X.<anything>(...) then counts too, matching a call into a
                    # sibling function of the check's own defining module (e.g. `guard.hits(...)`).
                    module_aliases.add(local)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == check_module:
                    module_aliases.add(alias.asname or alias.name.split(".")[0])

    return direct_names, module_aliases


def _invokes_check(call: ast.Call, ctx: _Context) -> bool:
    """True iff `call` invokes the check under test directly (zero hops): bare `attr_name(...)`,
    `<anything>.attr_name(...)` regardless of base, or `<module_alias>.<anything>(...)`."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == ctx.attr_name:
        return True
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in ctx.module_aliases:
        return True
    return isinstance(func, ast.Name) and func.id in ctx.direct_names


def _invoking_helper_names(tree: ast.Module, ctx: _Context) -> set[str]:
    """Same-file non-test functions/methods whose OWN body directly invokes the check (zero hops)
    -- the one-hop rule's helper roster. `ctx.helper_names` is ignored by `_invokes_check`, so a
    partial context (empty helper_names) is safe to pass in here; no chaining beyond one hop."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("test_"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and _invokes_check(sub, ctx):
                    names.add(node.name)
                    break
    return names


def _resolve_raises_names(tree: ast.Module) -> set[str]:
    """Local names bound to `pytest.raises` via a direct `from pytest import raises [as x]` --
    `<anything>.raises(...)` is always recognised regardless of this set (see
    _is_pytest_raises_call)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pytest":
            names.update(alias.asname or alias.name for alias in node.names if alias.name == "raises")
    return names


def _call_hop(call: ast.Call, ctx: _Context) -> int | None:
    """0 if `call` invokes the check directly, 1 if it calls a one-hop helper, else None."""
    if _invokes_check(call, ctx):
        return 0
    func = call.func
    if isinstance(func, ast.Name) and func.id in ctx.helper_names:
        return 1
    if isinstance(func, ast.Attribute) and func.attr in ctx.helper_names:
        return 1
    return None


def _is_derived(expr: ast.expr, derived: dict[str, int], ctx: _Context) -> bool:
    """True iff `expr` is itself, or is built directly on, something derived from an invocation of
    the check under test (see module docstring rule 1)."""
    if isinstance(expr, ast.Name):
        return expr.id in derived
    if isinstance(expr, ast.Call):
        return _call_hop(expr, ctx) is not None
    if isinstance(expr, (ast.Subscript, ast.Attribute)):
        return _is_derived(expr.value, derived, ctx)
    return False


def _derived_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef, ctx: _Context) -> dict[str, int]:
    """Local names in `func_node` derived from an invoking call: every argument passed to such a
    call (the accumulator-mutated-in-place shape), and every simple assignment target whose value
    is such a call (the return-value shape). Value is the hop count (0 or 1)."""
    derived: dict[str, int] = {}
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        hop = _call_hop(node, ctx)
        if hop is None:
            continue
        for arg in (*node.args, *(kw.value for kw in node.keywords)):
            if isinstance(arg, ast.Name):
                derived[arg.id] = min(hop, derived.get(arg.id, hop))
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            hop = _call_hop(node.value, ctx)
            if hop is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    derived[target.id] = min(hop, derived.get(target.id, hop))
    return derived


def _literal_polarity(node: ast.expr) -> bool | None:
    """True for a positive literal shape, False for a negative(empty)-shaped one, None if `node`
    is not a literal this floor classifies (in which case the comparison is not a hit either
    way)."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, str):
            return len(value) > 0
        if isinstance(value, (int, float)):
            return value != 0
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        return len(node.elts) > 0
    if isinstance(node, ast.Dict):
        return len(node.keys) > 0
    return None


_FLIPPED_CMPOP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.Eq,
    ast.NotEq: ast.NotEq,
    ast.Gt: ast.Lt,
    ast.Lt: ast.Gt,
    ast.GtE: ast.LtE,
    ast.LtE: ast.GtE,
}


def _flip_op(op: ast.cmpop) -> ast.cmpop:
    flipped = _FLIPPED_CMPOP.get(type(op))
    return flipped() if flipped is not None else op


def _plain_int_value(node: ast.expr) -> int | None:
    """The int value of a plain (non-bool) int constant, or None if `node` is not one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None


def _classify_len_compare(
    len_side: ast.expr, op: ast.cmpop, other_side: ast.expr, derived: dict[str, int], ctx: _Context
) -> bool | None:
    """`len(<derived>) <op> <int literal>` is a special-cased shape (acceptance criterion 3's
    `len(X) == 0` example) because `len(...)` is a builtin call, never itself "derived" under the
    generic rule. Returns None (not applicable) unless `len_side` is exactly this shape."""
    if not (isinstance(len_side, ast.Call) and isinstance(len_side.func, ast.Name) and len_side.func.id == "len"):
        return None
    if len(len_side.args) != 1 or not _is_derived(len_side.args[0], derived, ctx):
        return None
    n = _plain_int_value(other_side)
    if n is None:
        return None
    if isinstance(op, ast.Eq):
        return n != 0
    if isinstance(op, ast.NotEq):
        return n == 0
    if isinstance(op, ast.Gt):
        return n <= 0
    if isinstance(op, ast.GtE):
        return n <= 1
    if isinstance(op, (ast.Lt, ast.LtE)):
        return False
    return None


def _any_all_iterable(call: ast.Call) -> ast.expr | None:
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return arg.generators[0].iter if arg.generators else None
    if isinstance(arg, ast.Name):
        return arg
    return None


def _is_pytest_raises_call(expr: ast.expr, raises_names: frozenset[str]) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Attribute) and func.attr == "raises":
        return True
    return isinstance(func, ast.Name) and func.id in raises_names


def _classify_compare(node: ast.Compare, derived: dict[str, int], ctx: _Context) -> bool:
    op = node.ops[0]
    left, right = node.left, node.comparators[0]

    len_result = _classify_len_compare(left, op, right, derived, ctx)
    if len_result is not None:
        return len_result
    len_result = _classify_len_compare(right, _flip_op(op), left, derived, ctx)
    if len_result is not None:
        return len_result

    if isinstance(op, (ast.In, ast.NotIn)):
        return isinstance(op, ast.In) and _is_derived(right, derived, ctx)

    if _is_derived(left, derived, ctx):
        other, eff_op = right, op
    elif _is_derived(right, derived, ctx):
        other, eff_op = left, _flip_op(op)
    else:
        return False

    if isinstance(eff_op, ast.Is):
        return _literal_polarity(other) is True
    if isinstance(eff_op, ast.IsNot):
        return _literal_polarity(other) is False
    if isinstance(eff_op, (ast.Eq, ast.NotEq)):
        polarity = _literal_polarity(other)
        if polarity is None:
            return False
        return polarity if isinstance(eff_op, ast.Eq) else not polarity
    if isinstance(eff_op, (ast.Gt, ast.GtE)):
        n = _plain_int_value(other)
        if n is not None:
            threshold = n if isinstance(eff_op, ast.Gt) else n - 1
            return threshold <= 0
    return False


def _classify_assert(test_expr: ast.expr, derived: dict[str, int], ctx: _Context) -> bool:
    """True iff `test_expr` (an `assert`'s test expression) is a red-case per the module
    docstring's rule 2 -- POSITIVE outcome on a value derived per rule 1. `A and B`/`A or B`
    counts iff ANY conjunct/disjunct independently classifies positive (live-corpus shape:
    `assert failed and any(... for x in failed)`, where the `any(...)` half alone already
    qualifies) -- never because the boolean operator itself is meaningful here."""
    if isinstance(test_expr, ast.BoolOp):
        return any(_classify_assert(value, derived, ctx) for value in test_expr.values)

    if isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not):
        return False

    if isinstance(test_expr, ast.Call) and isinstance(test_expr.func, ast.Name) and test_expr.func.id in _ANY_ALL_NAMES:
        iterable = _any_all_iterable(test_expr)
        if iterable is not None and _is_derived(iterable, derived, ctx):
            return test_expr.func.id == "any"
        return False

    if isinstance(test_expr, ast.Compare) and len(test_expr.ops) == 1:
        return _classify_compare(test_expr, derived, ctx)

    if isinstance(test_expr, (ast.Subscript, ast.Attribute)) and _is_derived(test_expr.value, derived, ctx):
        return True

    return False


def _with_block_is_hit(node: ast.With, ctx: _Context) -> bool:
    if not any(_is_pytest_raises_call(item.context_expr, ctx.raises_names) for item in node.items):
        return False
    return any(isinstance(sub, ast.Call) and _call_hop(sub, ctx) is not None for sub in ast.walk(node))


def red_case_hits(mirror_path: Path, attr_name: str, *, _cache: dict[str, ast.Module | None] | None = None) -> list[str]:
    """Every red-case assertion or `with pytest.raises(...)` block in `mirror_path` that is
    derived from an invocation of the check registered under `attr_name` (see module docstring).

    Never raises: an unreadable or unparseable mirror yields `[]` -- the caller (`
    validate_red_case_floor`, via its own existence/resolution check) is what turns an unusable
    mirror into a FAILURE, so a malformed file is never silently indistinguishable from "no red
    case found" at THIS layer's log, but is still surfaced (Decision 55 never collapses the two at
    the check level).

    `_cache` (keyed by file path, holding the parsed AST or None) lets a caller share one parse per
    mirror FILE across several Entries -- private/keyword-only so the two-positional-arg calling
    convention this module's own tests and VP steps use is unaffected.
    """
    cache = _cache if _cache is not None else {}
    key = str(mirror_path)
    if key not in cache:
        try:
            cache[key] = ast.parse(mirror_path.read_text(encoding="utf-8"), filename=key)
        except (SyntaxError, UnicodeDecodeError, OSError):
            cache[key] = None
    tree = cache[key]
    if tree is None:
        return []

    direct_names, module_aliases = _resolve_check_namespace(tree, attr_name)
    partial = _Context(attr_name, frozenset(direct_names), frozenset(module_aliases), frozenset(), frozenset())
    helper_names = _invoking_helper_names(tree, partial)
    raises_names = _resolve_raises_names(tree)
    ctx = _Context(attr_name, partial.direct_names, partial.module_aliases, frozenset(helper_names), frozenset(raises_names))

    hits: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")):
            continue
        derived = _derived_names(node, ctx)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert) and _classify_assert(sub.test, derived, ctx):
                hits.append(f"{mirror_path}:{sub.lineno}")
            elif isinstance(sub, ast.With) and _with_block_is_hit(sub, ctx):
                hits.append(f"{mirror_path}:{sub.lineno}:raises")
    return hits


def _mirror_test_files(entry_module: str) -> list[Path]:
    """Resolve `entry_module`'s mirror via the CANONICAL map, reached through the module OBJECT
    (never a `from ... import map_source_to_test` binding -- see module docstring) so a test can
    intercept it with `patch.object(tcc, 'map_source_to_test', ...)`. Returns [] when the mirror
    cannot be resolved, does not exist, or (for a concern-split package) holds no test_*.py."""
    source_path = _common.ROOT / Path(*entry_module.split(".")).with_suffix(".py")
    mirror = tcc.map_source_to_test(source_path)
    if mirror is None:
        return []
    if mirror.suffix == ".py":
        return [mirror] if mirror.exists() else []
    return sorted(mirror.glob("test_*.py")) if mirror.is_dir() else []


@registry.register("validate_red_case_floor", owner="platform")
def validate_red_case_floor(failed: list[str]) -> None:
    """Every registered check's mirror test must exercise at least one FAILING path (LSA-03).

    See the module docstring for the population/mirror-resolution/red-case-signal rules. This
    function's only job is to WIRE them together and CONSULT `red_case_hits`' verdict -- it never
    re-derives the signal inline, so a test that starves `red_case_hits` (patches it to return
    `[]`) must starve this function's outcome too.
    """
    entries = dict(registry._ALL_ENTRIES)
    cache: dict[str, ast.Module | None] = {}
    non_conforming: list[str] = []

    for name in sorted(entries):
        entry = entries[name]
        test_files = _mirror_test_files(entry.module)
        if not test_files:
            non_conforming.append(f"{name}: mirror not found for {entry.module}")
            continue
        if not any(red_case_hits(test_file, entry.attr, _cache=cache) for test_file in test_files):
            non_conforming.append(f"{name}: mirror carries no red-case assertion for {entry.attr}")

    if non_conforming:
        failed.append(f"red-case floor: {len(non_conforming)} registered check(s) with no failing-path mirror assertion")
        registry.failure_detail(non_conforming)

    registry.examined(len(entries), unit="registered_checks")
