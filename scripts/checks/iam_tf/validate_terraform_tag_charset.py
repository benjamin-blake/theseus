"""S3 TagValue charset lint for literal terraform tag values (rec-3326 preventive_action).

S3 is stricter than the other AWS services tagged in this repo's terraform tree: its TagValue
charset is letters, digits, whitespace, and + - = . _ : / @ only -- no parentheses, no commas.
A value legal for e.g. SNS or Lambda tags can still be S3-illegal, which is exactly how rec-3326
happened (aws_s3_bucket.data_lake's Purpose tag carried both).

Only literal double-quoted tag values inside `tags = { ... }` blocks are checked. A
variable-sourced value (e.g. `Owner = var.owner_email`) never matches the literal-assignment
pattern and is silently out of reach for this static text scan -- that is a scope limitation,
not a false pass being claimed as coverage.
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry

_S3_TAGVALUE_RE = re.compile(r"^[A-Za-z0-9 +\-=._:/@]*$")
_TAGS_OPEN_RE = re.compile(r"\btags\s*=\s*\{")
_LITERAL_ASSIGNMENT_RE = re.compile(r'^[ \t]*[A-Za-z0-9_]+[ \t]*=[ \t]*"([^"]*)"[ \t]*$', re.MULTILINE)


def _blank_comment_lines(content: str) -> str:
    """Blank out whole-line HCL comments, preserving every character offset (mirrors
    validate_terraform_try._blank_comment_lines so comment prose can never false-positive)."""
    return "\n".join(" " * len(ln) if ln.lstrip().startswith(("#", "//")) else ln for ln in content.split("\n"))


def _tags_block_end(content: str, open_brace_pos: int) -> int:
    """Return the index just past the '}' that closes the '{' at open_brace_pos."""
    depth = 0
    i = open_brace_pos
    while i < len(content):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(content)


def _find_literal_tag_values(content: str) -> list[tuple[int, str]]:
    """Return (line_number, value) for every literal-string tag value inside a tags = { ... }
    block anywhere in content."""
    found: list[tuple[int, str]] = []
    for m in _TAGS_OPEN_RE.finditer(content):
        brace_pos = content.index("{", m.start())
        end = _tags_block_end(content, brace_pos)
        block = content[brace_pos + 1 : end - 1]
        for lm in _LITERAL_ASSIGNMENT_RE.finditer(block):
            abs_pos = brace_pos + 1 + lm.start()
            line_num = content[:abs_pos].count("\n") + 1
            found.append((line_num, lm.group(1)))
    return found


@registry.register("validate_terraform_tag_charset", owner="platform")
def validate_terraform_tag_charset(failed: list[str]) -> None:
    """Every literal terraform tag value stays inside the AWS S3 TagValue charset.

    Two reachable exit paths, each with exactly one Decision 170 declaration: the terraform
    directory missing `skipped()`s -- could not examine; the fall-through `examined(N, ...)`s the
    N literal tag values actually checked, whether N is zero (vacuous) or positive (enforced).
    """
    print("\n=== Terraform tag value S3-charset lint ===")
    tf_dir = _common.ROOT / "terraform"

    if not tf_dir.is_dir():
        reason = f"{tf_dir} not found"
        print(f"  SKIP: {reason}")
        registry.skipped(reason)
        return

    errors: list[str] = []
    total_values = 0
    for tf_file in sorted(tf_dir.rglob("*.tf")):
        content = _blank_comment_lines(tf_file.read_text(encoding="utf-8"))
        rel = tf_file.relative_to(_common.ROOT)
        for line_num, value in _find_literal_tag_values(content):
            total_values += 1
            if not _S3_TAGVALUE_RE.match(value):
                errors.append(
                    f"{rel}:{line_num}: tag value {value!r} is outside the S3 TagValue charset "
                    "(letters, digits, whitespace, and + - = . _ : / @ only)"
                )

    if errors:
        print("Terraform tag value S3-charset lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Terraform tag value S3-charset lint")
    else:
        print(f"All {total_values} literal terraform tag value(s) are inside the S3 TagValue charset.")

    registry.examined(total_values, unit="tag_values")


if __name__ == "__main__":  # pragma: no cover
    _failed: list[str] = []
    validate_terraform_tag_charset(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
