"""Extract src.* imports from Python files using AST parsing."""

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

_DEFAULT_REPO_ROOT = Path(__file__).parent.parent


def _resolve_relative_import(
    file_path: Path,
    level: int,
    module: str | None,
    roots: tuple[str, ...],
    repo_root: Path | None = None,
) -> str | None:
    """Resolve a relative import to an absolute first-party module name, or None.

    level=1 means current package (one dot); level=2 means parent package (two dots).
    """
    actual_root = repo_root if repo_root is not None else _DEFAULT_REPO_ROOT
    for root in roots:
        base = actual_root / root
        try:
            rel = file_path.resolve().relative_to(base.resolve())
        except ValueError:
            continue
        parts = [root] + list(rel.parent.parts)
        if level > len(parts):
            return None
        base_parts = parts[: len(parts) - (level - 1)]
        if module:
            return ".".join(base_parts + module.split("."))
        return ".".join(base_parts)
    return None


def _resolvable_submodule(package: str, name: str, repo_root: Path | None = None) -> str | None:
    """Return "<package>.<name>" when that names a real first-party MODULE on disk, else None.

    `from <package> import <name>` is ambiguous in the AST: <name> is either a submodule or a
    symbol re-exported by <package>/__init__.py. Only a submodule is an import edge to a
    different file, so the disk decides -- a name resolving to no <name>.py and no
    <name>/__init__.py contributes nothing (a namespace directory is deliberately excluded: it is
    not a scripts.dependency_graph module node either, so an edge to it would be dropped anyway).
    """
    if not name.isidentifier():
        return None
    root = repo_root if repo_root is not None else _DEFAULT_REPO_ROOT
    base = root.joinpath(*package.split("."), name)
    if base.with_suffix(".py").is_file() or (base / "__init__.py").is_file():
        return f"{package}.{name}"
    return None


def _import_from_targets(
    node: ast.ImportFrom,
    file_path: Path,
    roots: tuple[str, ...],
    repo_root: Path | None,
) -> list[str | None]:
    """Candidate first-party module names for one ast.ImportFrom node, in first-appearance order.

    Split out of extract_first_party_imports so that function's own branch count stays under the
    Decision 43 cyclomatic limit -- the same seam _walk_source already carves for the two
    try/except pairs. A None entry is a non-resolving submodule and is a no-op at the _add call
    site, so the caller needs no extra filtering.
    """
    targets: list[str | None] = []
    if node.level and node.level > 0:
        if node.module:
            # from .sub import X -- resolved submodule is the import target
            targets.append(_resolve_relative_import(file_path, node.level, node.module, roots, repo_root))
        else:
            # from . import name1, name2 -- each name may be a first-party submodule
            base = _resolve_relative_import(file_path, node.level, None, roots, repo_root)
            if base:
                for alias in node.names:
                    targets.append(f"{base}.{alias.name}")
    else:
        m = node.module or ""
        if any(m == r or m.startswith(r + ".") for r in roots):
            targets.append(m)
            # from <pkg> import <sub>: the package body runs too, so BOTH edges are real.
            for alias in node.names:
                targets.append(_resolvable_submodule(m, alias.name, repo_root))
    return targets


def _walk_source(file_path: Path) -> Iterable[ast.AST] | None:
    """Read, parse and walk file_path's AST; None when unreadable or unparseable.

    Split out of extract_first_party_imports so that function's own branch count stays under
    the Decision 43 cyclomatic limit -- the two try/except pairs live here instead.
    """
    try:
        return ast.walk(ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path)))
    except (OSError, SyntaxError):
        return None


def extract_first_party_imports(
    file_path: Path,
    roots: tuple[str, ...] = ("src", "scripts"),
    _repo_root: Path | None = None,
    _nodes: Iterable[ast.AST] | None = None,
) -> list[str]:
    """Return unique first-party module names imported in file_path.

    Covers absolute src.*/scripts.* imports AND relative imports (ImportFrom.level > 0).
    An absolute `from <pkg> import <name>` yields <pkg> AND, when <name> resolves to a real
    first-party module on disk (see _resolvable_submodule), <pkg>.<name> -- both are genuine
    runtime dependencies, and recording only the package left every submodule of a package
    invisible to the reverse-dependency lookups built on this (scripts.dependency_graph).
    Returns [] on syntax error or missing file. Order: first appearance.
    `_nodes` supplies an already-materialized `ast.walk()` of file_path's AST so a caller
    running several scans over one file (scripts.dependency_graph.build_graph) reads, parses
    and walks it once; file_path is still the anchor for relative-import resolution.
    """
    nodes = _nodes if _nodes is not None else _walk_source(file_path)
    if nodes is None:
        return []

    seen: set[str] = set()
    results: list[str] = []

    def _add(mod: str | None) -> None:
        if mod and mod not in seen:
            seen.add(mod)
            results.append(mod)

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                m = alias.name
                if any(m == r or m.startswith(r + ".") for r in roots):
                    _add(m)
        elif isinstance(node, ast.ImportFrom):
            for mod in _import_from_targets(node, file_path, roots, _repo_root):
                _add(mod)

    return results


def extract_src_imports(file_path: Path) -> list[str]:
    """Return a list of src.* module names imported in *file_path*.

    Handles both:
      ``import src.X``
      ``from src.X import Y``

    Returns an empty list if the file has a syntax error or does not exist.
    The returned list contains unique module names, preserving order of first
    appearance.

    Branch budget note: this function is the largest branch surface in the module
    (measured 15 of the Decision 43 limit of 20). Adding another arm here wants the same
    helper-seam treatment extract_first_party_imports got, not an inline branch.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, IOError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    seen: set[str] = set()
    results: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if module == "src" or module.startswith("src."):
                    if module not in seen:
                        seen.add(module)
                        results.append(module)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "src" or module.startswith("src."):
                if module not in seen:
                    seen.add(module)
                    results.append(module)

    return results


def main() -> int:
    if len(sys.argv) < 2:
        return 0

    for arg in sys.argv[1:]:
        for module in extract_src_imports(Path(arg)):
            print(module)

    return 0


if __name__ == "__main__":
    sys.exit(main())
