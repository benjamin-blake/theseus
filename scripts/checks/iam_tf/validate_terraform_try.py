from __future__ import annotations

import re

from scripts.checks import _common, registry


def _is_inside_try(content: str, pos: int) -> bool:
    """Return True if position pos is nested inside any try() call (at any depth).

    Algorithm: walk backwards from pos tracking parenthesis depth. Every time a
    '(' is found while depth is 0, it is an enclosing call boundary. Check
    whether its identifier is exactly 'try' (word boundary enforced). If yes,
    return True. If not, keep depth at 0 and continue walking to find higher
    ancestors.

    Examples::

        try(filemd5("x"))              -> True  (direct parent)
        try(md5(file("x")))            -> True  (ancestor, not direct parent)
        filemd5("x")                   -> False (no enclosing try)
        retry(filemd5("x"))            -> False ('retry' is not 'try')
    """
    depth = 0
    i = pos - 1
    while i >= 0:
        ch = content[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth > 0:
                depth -= 1
            else:
                # depth == 0: this ( is an enclosing call boundary
                preceding = content[max(0, i - 10) : i]
                if re.search(r"(?<![\w])try$", preceding):
                    return True
                # depth stays 0: continue looking for outer ancestors
        i -= 1
    return False


def _blank_comment_lines(content: str) -> str:
    """Blank out whole-line HCL comments, preserving every character offset.

    Comment prose routinely contains the very tokens this lint scans for (e.g. "the native lock
    file (use_lockfile ...)"), which reads as an unwrapped file() call. Only WHOLE-LINE comments
    are blanked, so a `#` or `//` inside a quoted ARN or URL on a code line can never mask a real
    call later on that same line. Blanking (rather than deleting) keeps offsets -- and therefore
    the reported line numbers -- exact.
    """
    return "\n".join(" " * len(ln) if ln.lstrip().startswith(("#", "//")) else ln for ln in content.split("\n"))


@registry.register("validate_terraform_try", owner="platform")
def validate_terraform_try(failed: list[str]) -> None:
    """Check that filemd5() and file() in .tf files are wrapped with try().

    Recursive over the whole terraform tree: every root lives in a subdirectory
    (terraform/personal, terraform/github, terraform/bootstrap), so a depth-1 glob would examine
    nothing and pass vacuously. Findings are keyed by path relative to the repo root, since the
    same basename (main.tf, variables.tf) recurs in several roots.
    """
    print("\n=== Terraform try() lint ===")
    tf_dir = _common.ROOT / "terraform"
    errors: list[str] = []

    for tf_file in sorted(tf_dir.rglob("*.tf")):
        content = _blank_comment_lines(tf_file.read_text(encoding="utf-8"))
        for m in re.finditer(r"\bfilemd5\s*\(|(?<![\w])file\s*\(", content):
            if not _is_inside_try(content, m.start()):
                fn_name = "filemd5()" if "filemd5" in m.group() else "file()"
                line_num = content[: m.start()].count("\n") + 1
                rel = tf_file.relative_to(_common.ROOT)
                errors.append(f"{rel}:{line_num}: {fn_name} must be wrapped in try() for CI compatibility")

    if errors:
        print("Terraform try() lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Terraform try() lint")
    else:
        print("All filemd5() and file() calls in terraform files are wrapped with try().")
