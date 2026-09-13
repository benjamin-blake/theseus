"""Advisory census of non-discriminating pytest.raises sites under tests/ (Decision 170's
accounting channel; the report-only registration shape of validate_declaring_coverage).

A scanned pytest.raises site is a HIT when all FOUR arms hold together:
  1. its declared expected_exception resolves to a name in BROAD_EXCEPTION_TYPES. For a TUPLE of
     types the membership rule is ANY member, never all: a tuple is an OR of catchable types, so
     (CustomError, ValueError) still admits a bare ValueError and is broad. Requiring ALL members
     would drop every mixed tuple off the census the narrowing sweep works from.
  2. the call carries no match= keyword (a **kwargs splat counts as one -- see keyword_facts);
  3. it binds no excinfo whose bound name is LOADED again inside the SAME enclosing scope and
     strictly AFTER the with-statement's own end_lineno. The arm is "the bound name is READ
     back", never "the bound name appears in an assert": a helper whose last statement is
     `return exc_info.value.code`, for its caller to assert, discriminates exactly as well as an
     inline assert does. Conversely a read that PRECEDES the with-statement, one that sits inside
     the with-body (where pytest has not filled the excinfo yet), and one in a different function
     that merely REUSES the binding name are each not a read of THIS site's excinfo, and none of
     them suppresses it.
  4. no WAIVER_MARKER comment sits on the call's OWN line span -- lineno..end_lineno inclusive,
     the _assert_has_waiver placement rule of validate_test_count_coupling.py. A marker on a
     continuation line of a multi-line call waives that call; a marker on the line ABOVE the
     `with` does not waive anything.
Each arm ALONE suppresses the hit, so a narrower type, a match=, a follow-up excinfo read or a
waiver each takes a site off the list.

REPORT-ONLY. `failed` is never appended to on any path, no threshold is stated, and no
status_vocabulary member is added -- the ratified shape of validate_declaring_coverage and of
docs/contracts/check-accounting.yaml's path_aware_declaring_coverage key. This is the deliberate
resting state of the census half of the narrowing work, not a gate left discretionary; flipping
the census to blocking is a later, separately reviewed change, never an escape path inside this
module.

BROAD_EXCEPTION_TYPES is the FROZEN roster, collocated with the enforcement it feeds (AGENTS.md;
the _CURATED_TOKENS precedent in validate_test_count_coupling.py) and pinned by equality in the
mirror test. Its members are the built-in exception types that unrelated code raises for many
distinct causes, so binding one proves little about WHICH failure occurred. Narrow library types
are deliberately OUT of the roster -- pydantic ValidationError, FileNotFoundError,
subprocess.CalledProcessError, subprocess.TimeoutExpired and botocore ClientError each name a
single failure mode already.

The scan is TOTAL over pytest.raises call shapes: a positional type, a tuple of types, an
attribute-qualified type, no argument at all, a keyword-only expected_exception, a starred
argument, a kwargs splat and a subscript expression all classify without raising, because an
expression this scan cannot resolve yields NO type names and a site with no names is never broad.

NEITHER I/O SEAM CAN RAISE OUT OF THIS MODULE. read_text is guarded against OSError, TypeError
and UnicodeDecodeError; ast.parse fails in more ways than SyntaxError, so it is guarded against
SyntaxError, ValueError, RecursionError and MemoryError -- the same by-name set
_declaring_coverage.measure_source catches, for the same stated reason: scripts/validation_result
dispatches a check with NO try/except, so a failure escaping here would abort the whole tier
rather than red one check. A file lost at either seam is counted into the `skipped` accumulator
and PRINTED alongside the census; it is never silently dropped.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

from scripts.checks import _common, registry

BROAD_EXCEPTION_TYPES: frozenset[str] = frozenset(
    {
        "AssertionError",
        "AttributeError",
        "BaseException",
        "EnvironmentError",
        "Exception",
        "IOError",
        "IndexError",
        "KeyError",
        "LookupError",
        "NameError",
        "OSError",
        "RuntimeError",
        "SystemExit",
        "TypeError",
        "ValueError",
    }
)

# A per-site suppression marker in the `# count-coupling-ok:` / `# root-scoped-ok:` shape: a
# free-text WAIVER local to this module, never an authorization token, so it stays out of
# scripts/checks/_marker_guard.py and cites no Decision (Decision 165 consolidated the
# raise-marker authorization guards only). It waives only when it sits on the guarded call's own
# lineno..end_lineno span -- a marker on the line above the `with` waives nothing.
WAIVER_MARKER = "# raises-discrimination-ok:"

SUMMARY_GRAMMAR = "raises-discrimination scanned={scanned} hits={hits} directories={directories} (advisory)"

_PYTEST_MODULE = "pytest"
_RAISES_ATTR = "raises"
_MATCH_KEYWORD = "match"
_EXPECTED_KEYWORD = "expected_exception"
_UNRESOLVED_TYPE = "<unresolved>"
_TESTS_DIRNAME = "tests"
_HEADER = "\n=== pytest.raises discrimination census (advisory) ==="
_SKIPPED_GRAMMAR = "unreadable or unparseable files skipped: {skipped}"
_ADVISORY_NOTICE = (
    "  ADVISORY: nothing is failed here -- this census is the measured input to the narrowing "
    "sweep, and a site leaves the list by gaining a narrower type, a match=, an excinfo read "
    "after the with-statement, or a waiver."
)

_READ_FAILURES = (OSError, TypeError, UnicodeDecodeError)
_PARSE_FAILURES = (SyntaxError, ValueError, RecursionError, MemoryError)

_Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclasses.dataclass(frozen=True)
class RaisesNames:
    """The names ONE module binds to pytest.raises, resolved from its own imports.

    `module_aliases` are heads a `raises` ATTRIBUTE call may hang off (`pytest`, `pt`);
    `direct_names` are bare names bound straight to raises (`from pytest import raises as
    assert_raises`). A module importing neither binds no raises name at all, so a local
    `raises(...)` call in it is not a pytest.raises site.
    """

    module_aliases: frozenset[str]
    direct_names: frozenset[str]


@dataclasses.dataclass(frozen=True)
class RaisesSite:
    """One scanned pytest.raises site with all four rule arms already decided.

    `loads_excinfo` is named for what arm 3 actually measures -- the bound name is READ back
    after the with-statement -- not for the narrower "asserted" shape it is often written as.
    """

    path: str
    lineno: int
    type_text: str
    broad: bool
    has_match: bool
    loads_excinfo: bool
    waived: bool

    @property
    def directory(self) -> str:
        """The site's parent directory -- the census's grouping key."""
        return PurePosixPath(self.path).parent.as_posix()


def resolve_raises_names(tree: ast.Module) -> RaisesNames:
    """Resolve what THIS module calls pytest.raises, from its own import statements.

    Recognised forms: `import pytest` (with or without an alias) and `from pytest import raises`
    (with or without an alias).
    """
    aliases: set[str] = set()
    direct: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _PYTEST_MODULE:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == _PYTEST_MODULE:
            for alias in node.names:
                if alias.name == _RAISES_ATTR:
                    direct.add(alias.asname or alias.name)
    return RaisesNames(frozenset(aliases), frozenset(direct))


def is_raises_call(node: ast.Call, names: RaisesNames) -> bool:
    """Whether `node` is a pytest.raises call under this module's own import aliases."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == _RAISES_ATTR and isinstance(func.value, ast.Name) and func.value.id in names.module_aliases
    return isinstance(func, ast.Name) and func.id in names.direct_names


def type_names(expression: ast.expr | None) -> tuple[str, ...]:
    """The exception-type names a declared expected_exception expression resolves to.

    Total by construction: a Name yields its id, an Attribute its final attr, a Tuple the
    concatenation of its elements, and EVERY other expression -- a subscript, a call, a starred
    element, an absent argument -- yields the empty tuple, which is never broad.
    """
    if isinstance(expression, ast.Name):
        return (expression.id,)
    if isinstance(expression, ast.Attribute):
        return (expression.attr,)
    if isinstance(expression, ast.Tuple):
        return tuple(name for element in expression.elts for name in type_names(element))
    return ()


def type_text(names: tuple[str, ...]) -> str:
    """The reported rendering of a site's declared type names."""
    if not names:
        return _UNRESOLVED_TYPE
    if len(names) == 1:
        return names[0]
    return "(" + ", ".join(names) + ")"


def is_broad(names: tuple[str, ...]) -> bool:
    """Whether a declared type expression is BROAD -- ANY member of a tuple being in the roster
    is enough, because a tuple of types is an OR of what the site will catch."""
    return any(name in BROAD_EXCEPTION_TYPES for name in names)


def keyword_facts(call: ast.Call) -> tuple[bool, ast.expr | None]:
    """(a match= is or may be supplied, the expected_exception keyword's value or None).

    A `**kwargs` splat carries an unresolvable keyword population, so it counts as MAY supply a
    match= -- the SUPPRESSING direction, which keeps an unresolvable site out of the census
    rather than reporting a site the scan cannot actually read.
    """
    match_present = False
    expected: ast.expr | None = None
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg == _MATCH_KEYWORD:
            match_present = True
        elif keyword.arg == _EXPECTED_KEYWORD:
            expected = keyword.value
    return match_present, expected


def declared_type(call: ast.Call) -> ast.expr | None:
    """The expected_exception expression this call declares, or None when it declares none this
    scan can resolve: no argument at all, or a starred first positional."""
    if call.args:
        first = call.args[0]
        return None if isinstance(first, ast.Starred) else first
    return keyword_facts(call)[1]


def with_bindings(tree: ast.Module) -> dict[int, tuple[str, int]]:
    """Map id(context-expression Call) -> (the name a `with pytest.raises(...) as name:` binds,
    the enclosing with-statement's end_lineno).

    The end_lineno travels with the binding because arm 3 only credits a READ that happens after
    the with-statement finishes; a read before it, or inside its body, is a different value.
    Only a plain Name target is recorded; any other target binds no excinfo this scan follows.
    """
    bindings: dict[int, tuple[str, int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            target = item.optional_vars
            if isinstance(item.context_expr, ast.Call) and isinstance(target, ast.Name):
                bindings[id(item.context_expr)] = (target.id, node.end_lineno or node.lineno)
    return bindings


def binding_is_loaded(scope: _Scope, name: str, after_lineno: int) -> bool:
    """Whether `name` is READ inside `scope`'s own statements strictly after `after_lineno`.

    Scoped and positioned rather than module-wide, because binding names repeat: `exc_info` is
    bound many times over in a single test module, and a module-wide search would let one
    function's follow-up read suppress an unrelated function's undiscriminating site. A site that
    binds `as excinfo` and never reads it back discriminates no better than one that binds
    nothing, so the READ is what clears the site, not the binding.
    """
    return any(
        isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load) and node.lineno > after_lineno
        for node in _scope_nodes(scope)
    )


def has_waiver(lines: list[str], call: ast.Call) -> bool:
    """Whether a WAIVER_MARKER comment sits on the call's own lineno..end_lineno span."""
    start = call.lineno
    end = call.end_lineno or start
    return any(WAIVER_MARKER in lines[number - 1] for number in range(start, end + 1) if 1 <= number <= len(lines))


def _scopes(tree: ast.Module) -> list[_Scope]:
    """The module plus every def/class node in it -- one entry per lexical scope."""
    scopes: list[_Scope] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, _SCOPE_NODES):
            scopes.append(node)
    return scopes


def _scope_nodes(scope: _Scope) -> Iterator[ast.AST]:
    """Every node reachable from `scope`'s own statements WITHOUT descending into a nested
    def/class body -- those are separate scopes, walked independently (the _iter_scope_nodes
    precedent in validate_test_count_coupling.py). Pairs each call with the smallest scope that
    encloses it, exactly once."""
    stack: list[ast.AST] = list(scope.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _SCOPE_NODES):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _relative(path: Path, base: Path) -> str:
    """`path` rendered repo-relative, falling back to its own posix text when it does not sit
    under `base` -- a report line is never worth a raise out of a report-only check. Pure path
    arithmetic, deliberately without resolve(): resolve() touches the filesystem and raises
    RuntimeError on a symlink loop, which is neither a read nor a parse failure and would escape
    both guarded seams; the read seam below meets a loop symlink as OSError and skips it."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _site(rel: str, call: ast.Call, scope: _Scope, lines: list[str], bindings: dict[int, tuple[str, int]]) -> RaisesSite:
    names = type_names(declared_type(call))
    binding = bindings.get(id(call))
    match_present, _expected = keyword_facts(call)
    return RaisesSite(
        path=rel,
        lineno=call.lineno,
        type_text=type_text(names),
        broad=is_broad(names),
        has_match=match_present,
        loads_excinfo=binding is not None and binding_is_loaded(scope, binding[0], binding[1]),
        waived=has_waiver(lines, call),
    )


def scan_file(path: Path, root: Path | None = None, skipped: list[str] | None = None) -> list[RaisesSite]:
    """Every pytest.raises site in ONE file, in line order, each carrying its four rule arms.

    An unreadable, undecodable or unparseable module yields no sites rather than raising, and its
    path is appended to `skipped` when one is supplied: the tier dispatcher wraps a check in no
    try/except, so an escaping read or parse failure would abort the whole run. Every failure
    shape is caught BY NAME -- _READ_FAILURES at the read seam, _PARSE_FAILURES at ast.parse.
    """
    base = _common.ROOT if root is None else root
    rel = _relative(path, base)
    try:
        text = path.read_text(encoding="utf-8")
    except _READ_FAILURES:
        if skipped is not None:
            skipped.append(rel)
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except _PARSE_FAILURES:
        if skipped is not None:
            skipped.append(rel)
        return []
    names = resolve_raises_names(tree)
    if not names.module_aliases and not names.direct_names:
        return []
    lines = text.splitlines()
    bindings = with_bindings(tree)
    sites: list[RaisesSite] = []
    for scope in _scopes(tree):
        for node in _scope_nodes(scope):
            if isinstance(node, ast.Call) and is_raises_call(node, names):
                sites.append(_site(rel, node, scope, lines, bindings))
    return sorted(sites, key=lambda site: site.lineno)


def scan_tests(root: Path | None = None, skipped: list[str] | None = None) -> list[RaisesSite]:
    """Every pytest.raises site under `root`/tests, in path then line order. Each file is read
    and parsed exactly ONCE (scan_file), so the walk costs one pass over the tree."""
    base = _common.ROOT if root is None else root
    sites: list[RaisesSite] = []
    for path in sorted((base / _TESTS_DIRNAME).glob("**/*.py")):
        sites.extend(scan_file(path, base, skipped))
    return sites


def hits(sites: Iterable[RaisesSite]) -> list[RaisesSite]:
    """The REPORTED subset -- the four arms conjoined, in scan order."""
    return [site for site in sites if site.broad and not site.has_match and not site.loads_excinfo and not site.waived]


def hits_by_directory(reported: Iterable[RaisesSite]) -> dict[str, int]:
    """Reported-site counts keyed by parent directory."""
    counts: dict[str, int] = {}
    for site in reported:
        counts[site.directory] = counts.get(site.directory, 0) + 1
    return counts


def summary_line(scanned: list[RaisesSite]) -> str:
    """The one census line, rendered from SUMMARY_GRAMMAR over a scanned population."""
    reported = hits(scanned)
    return SUMMARY_GRAMMAR.format(scanned=len(scanned), hits=len(reported), directories=len(hits_by_directory(reported)))


def skipped_line(skipped: list[str]) -> str:
    """The one skipped-file census line -- always emitted, so a lost file is never silent."""
    return _SKIPPED_GRAMMAR.format(skipped=len(skipped))


@registry.register("validate_raises_discrimination", owner="platform")
def validate_raises_discrimination(failed: list[str], sites: list[RaisesSite] | None = None) -> None:
    """Report the non-discriminating pytest.raises census over tests/, grouped by directory.

    NEVER appends to `failed` on any path -- see the module docstring's report-only paragraph.
    `sites` is an injection seam substituting a scanned population for the live walk; the single
    reachable exit declares examined() over that population.
    """
    print(_HEADER)
    skipped: list[str] = []
    scanned = scan_tests(skipped=skipped) if sites is None else list(sites)
    reported = hits(scanned)
    grouped = hits_by_directory(reported)
    for directory in sorted(grouped, key=lambda name: (-grouped[name], name)):
        print(f"  {directory}: {grouped[directory]} non-discriminating site(s)")
        for site in reported:
            if site.directory == directory:
                print(f"    - {site.path}:{site.lineno} {site.type_text}")
    print(f"  {summary_line(scanned)}")
    print(f"  {skipped_line(skipped)}")
    for rel in skipped:
        print(f"    ? {rel}")
    print(_ADVISORY_NOTICE)
    registry.examined(len(scanned), unit="pytest_raises_sites")
