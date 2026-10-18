"""Predicate + parsers for Decision 225 (rec-4049): no CI identity holds an iam: Allow, write or
read, whose Resource matches PlatformDev or PlatformAdmin.

Parses BOTH HCL dialects used by the scanned files: jsonencode Statement lists
(terraform/bootstrap's two apply-role policy files) and `statement {}` blocks
(terraform/personal's aws_iam_policy_document data sources). Reuses the comment/string masking
primitives from _platform_security_hcl.py rather than a third masker (Decision 128 precedent).
"""

from __future__ import annotations

import fnmatch
import re

from tests.checks.iam_tf._platform_security_hcl import _block_body, _mask, _strip_comments

_PLATFORM_ROLE_NAMES = ("PlatformDev", "PlatformAdmin")


def _substitute(raw: str) -> str:
    return raw.replace("${var.account_id}", "123456789012").replace("${var.aws_region}", "eu-west-2")


def _is_resolved_literal(raw: str) -> bool:
    """True once var.account_id / var.aws_region substitution leaves no interpolation behind."""
    return "${" not in _substitute(raw)


def _list_or_scalar(raw: str) -> list[str]:
    """A quoted scalar or a `[...]` list of quoted strings -> its literal string elements."""
    raw = raw.strip()
    m = re.fullmatch(r"\[(.*)\]", raw, re.S)
    body = m.group(1) if m is not None else raw
    return re.findall(r'"((?:[^"\\]|\\.)*)"', body)


def _case_fold_covers_iam(patterns: list[str]) -> bool:
    """True if any action pattern's case-folded fnmatch covers at least one iam: verb shape.

    Namespace-based: a pattern with a colon covers iam: actions iff its namespace fragment
    (case-folded fnmatch) matches "iam"; a bare pattern with no colon (e.g. "*", "i*") is tested
    against a representative iam: action string directly.
    """
    for p in patterns:
        pl = p.lower()
        if ":" in pl:
            ns = pl.split(":", 1)[0]
            if fnmatch.fnmatch("iam", ns):
                return True
        elif fnmatch.fnmatch("iam:getrole", pl):
            return True
    return False


class _Statement:
    __slots__ = ("sid", "effect", "actions", "not_actions", "resources", "not_resources", "resources_unresolved")

    def __init__(self) -> None:
        self.sid: str | None = None
        self.effect: str = "Allow"
        self.actions: list[str] = []
        self.not_actions: list[str] = []
        self.resources: list[str] = []
        self.not_resources: list[str] = []
        self.resources_unresolved: bool = False


def _jsonencode_statement_blocks(text: str) -> list[str]:
    """Raw text spans of every top-level object inside every `Statement = [...]` list."""
    out: list[str] = []
    masked = _mask(text)
    for m in re.finditer(r"\bStatement\s*=\s*\[", masked):
        depth = 1
        i = m.end()
        list_start = i
        while depth > 0 and i < len(masked):
            if masked[i] == "[":
                depth += 1
            elif masked[i] == "]":
                depth -= 1
            i += 1
        list_body = text[list_start : i - 1]
        masked_body = masked[list_start : i - 1]
        bd = 0
        obj_start = None
        for j, ch in enumerate(masked_body):
            if ch == "{":
                if bd == 0:
                    obj_start = j
                bd += 1
            elif ch == "}":
                bd -= 1
                if bd == 0 and obj_start is not None:
                    out.append(list_body[obj_start : j + 1])
                    obj_start = None
    return out


def _parse_jsonencode_statement(block: str) -> _Statement:
    s = _Statement()
    stripped = _strip_comments(block)
    sm = re.search(r'Sid\s*=\s*"([^"]*)"', stripped)
    s.sid = sm.group(1) if sm is not None else None
    em = re.search(r'Effect\s*=\s*"([^"]*)"', stripped)
    s.effect = em.group(1) if em is not None else "Allow"
    for attr, target in (
        ("Action", "actions"),
        ("NotAction", "not_actions"),
        ("Resource", "resources"),
        ("NotResource", "not_resources"),
    ):
        am = re.search(rf"{attr}\s*=\s*(\[(?:[^][]|\[[^]]*\])*\]|\"(?:[^\"\\\\]|\\\\.)*\")", stripped, re.S)
        if am is not None:
            setattr(s, target, _list_or_scalar(am.group(1)))
    if any(not _is_resolved_literal(r) for r in (s.resources + s.not_resources)):
        s.resources_unresolved = True
    return s


def _hcl_statement_blocks(text: str) -> list[str]:
    masked = _mask(text)
    out: list[str] = []
    for m in re.finditer(r"\bstatement\s*\{", masked):
        out.append(_block_body(text, m.end() - 1))
    return out


def _attr_raw(body: str, name: str) -> str | None:
    """Raw RHS of `name = ...`: a bracket-matched `[...]` list (may span lines, comments
    included), a quoted scalar, or a bare token to end of line."""
    stripped = _strip_comments(body)
    m = re.search(rf"^\s*{name}\s*=\s*", stripped, re.M)
    if m is None:
        return None
    i = m.end()
    if i < len(stripped) and stripped[i] == "[":
        depth = 0
        j = i
        while j < len(stripped):
            if stripped[j] == "[":
                depth += 1
            elif stripped[j] == "]":
                depth -= 1
                if depth == 0:
                    return stripped[i : j + 1]
            j += 1
        return None
    lm = re.match(r'"(?:[^"\\]|\\.)*"', stripped[i:])
    if lm is not None:
        return lm.group(0)
    em = re.match(r"[^\n]*", stripped[i:])
    return em.group(0).strip() if em is not None else None


def _parse_hcl_statement(block: str) -> _Statement:
    s = _Statement()
    sm = re.search(r'^\s*sid\s*=\s*"([^"]*)"\s*$', _strip_comments(block), re.M)
    s.sid = sm.group(1) if sm is not None else None
    em = re.search(r'^\s*effect\s*=\s*"([^"]*)"\s*$', _strip_comments(block), re.M)
    s.effect = em.group(1) if em is not None else "Allow"
    for attr, target in (
        ("actions", "actions"),
        ("not_actions", "not_actions"),
        ("resources", "resources"),
        ("not_resources", "not_resources"),
    ):
        raw = _attr_raw(block, attr)
        if raw is not None:
            setattr(s, target, _list_or_scalar(raw))
    if any(not _is_resolved_literal(r) for r in (s.resources + s.not_resources)):
        s.resources_unresolved = True
    return s


_TEST_ACCOUNT_ID = "123456789012"


def _role_matches(pattern: str, role_name: str) -> bool:
    concrete = f"arn:aws:iam::{_TEST_ACCOUNT_ID}:role/{role_name}"
    translated = _substitute(pattern)
    return fnmatch.fnmatch(concrete.lower(), translated.lower())


def statement_leaks(stmt: _Statement) -> list[str]:
    """Role names (PlatformDev / PlatformAdmin) this single Allow statement leaks an iam: grant on."""
    if stmt.effect != "Allow":
        return []
    is_iam = bool(stmt.not_actions) or _case_fold_covers_iam(stmt.actions)
    if not is_iam:
        return []
    if stmt.not_resources:
        # Any NotResource on an iam-granting Allow is itself the leak shape -- it cannot be
        # proven to exclude either platform role.
        return list(_PLATFORM_ROLE_NAMES)
    if stmt.resources_unresolved:
        return list(_PLATFORM_ROLE_NAMES)
    hits: list[str] = []
    for role_name in _PLATFORM_ROLE_NAMES:
        for pattern in stmt.resources:
            if _role_matches(pattern, role_name):
                hits.append(role_name)
                break
    return hits


def ci_platform_role_iam_leaks(texts: dict[str, str]) -> list[tuple[str, str | None, str]]:
    """(file, sid, role_name) for every Allow statement across both dialects that carries an
    iam: action (or NotAction) and whose Resource matches a concrete PlatformDev or PlatformAdmin
    ARN, over every scanned file. Fails closed: an unresolvable Resource or a NotResource on an
    iam-granting Allow counts as a leak on BOTH role names, never a pass."""
    out: list[tuple[str, str | None, str]] = []
    for fname, text in texts.items():
        if not text.strip():
            raise ValueError(f"{fname}: scanned file is empty -- fail closed")
        for block in _jsonencode_statement_blocks(text):
            stmt = _parse_jsonencode_statement(block)
            for role in statement_leaks(stmt):
                out.append((fname, stmt.sid, role))
        for block in _hcl_statement_blocks(text):
            stmt = _parse_hcl_statement(block)
            for role in statement_leaks(stmt):
                out.append((fname, stmt.sid, role))
    return out


def independent_statement_counts(text: str) -> tuple[int, int]:
    """(parsed statement{} blocks, raw `statement {` openings) and
    (parsed jsonencode statements, raw `Effect =` keys) must each agree -- see
    independent_jsonencode_counts for the second pair."""
    masked = _mask(text)
    raw_hcl = len(re.findall(r"\bstatement\s*\{", masked))
    parsed_hcl = len(_hcl_statement_blocks(text))
    return parsed_hcl, raw_hcl


def independent_jsonencode_counts(text: str) -> tuple[int, int]:
    masked = _mask(text)
    raw_json = len(re.findall(r"\bEffect\s*=", masked))
    parsed_json = len(_jsonencode_statement_blocks(text))
    return parsed_json, raw_json
