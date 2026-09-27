"""Pure Bash-command classification and canonical-form parsing for the handoff evidence gate.

Moved OUT of the harness hook (.claude/hooks/handoff_evidence_gate.py) so this logic inherits the
100% per-file coverage floor -- map_source_to_test returns None for .claude/hooks/*.py, so logic
left there would be ungoverned (critique F7). No git, no I/O: this module is pure text
classification and parsing.

Residual surfaces (declared, owned by rec-4085 and the row in docs/contracts/git-ops.yaml citing
it): subprocess pushes that never route through a shell this module recognises (a compiled
helper, a language-level git library), wrapper interpreters beyond the four POSIX shells named
here, heredocs fed to a non-shell interpreter (e.g. a Python script read via ``python - <<EOF``),
nested shells beyond one level of ``-c``/``eval`` recursion, persistent git aliases or
``includeIf`` config that redefines ``push`` outside a single ``-c alias.x=push`` token this
module already recognises, and the accepted ``echo git push`` false positive (named in the hook's
own deny message).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

SHELLS = frozenset({"bash", "sh", "zsh", "dash"})

GIT_ARG_GLOBALS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path", "--super-prefix"}
)
GIT_NOARG_GLOBALS = frozenset(
    {
        "--no-pager",
        "-p",
        "-P",
        "--paginate",
        "--bare",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-replace-objects",
        "--no-optional-locks",
        "--no-lazy-fetch",
        "--no-advice",
    }
)

_PUSH_LIKE_SUBCOMMANDS = frozenset({"push", "send-pack", "http-push"})
_MULTI_WORD_PUSH_NAMESPACES = frozenset({"subtree", "lfs"})

_HEREDOC_OP_RE = re.compile(r"<<([-~]?)\s*(['\"]?)(\w+)\2")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_WORD_RE = re.compile(r"(?:^|[\s/|&;()!])(?:bash|sh|zsh|dash)(?=[\s/]|$)")


@dataclass(frozen=True)
class ParsedPush:
    kind: str  # push, bare_push, delete, dry_run
    worktree_hint: str | None
    remote: str | None
    src: str | None
    dst: str | None


@dataclass(frozen=True)
class NonCanonical:
    reason: str


def _basename(tok: str) -> str:
    return tok.rsplit("/", 1)[-1] if "/" in tok else tok


def _is_assignment(tok: str) -> bool:
    return bool(_ASSIGNMENT_RE.match(tok)) and " " not in tok


def _line_invokes_shell(line_text: str) -> bool:
    return bool(_SHELL_WORD_RE.search(line_text))


def _find_delimiter_line(text: str, start: int, delim: str) -> tuple[int, int]:
    """Return (body_end, delim_line_end) for the first line matching the delimiter, from `start`."""
    pat = re.compile(r"^[ \t]*" + re.escape(delim) + r"[ \t]*$", re.MULTILINE)
    m = pat.search(text, start)
    if m is None:
        return len(text), len(text)
    delim_line_end = m.end()
    if delim_line_end < len(text) and text[delim_line_end] == "\n":
        delim_line_end += 1
    return m.start(), delim_line_end


def strip_heredocs(text: str) -> str:
    """Strip heredoc bodies that are data, per the module docstring's PRE-PASS rule.

    A heredoc body is kept (for downstream classification) only when the line receiving the
    heredoc invokes one of SHELLS directly or feeds a pipeline containing one (``cat <<'EOF' |
    bash``). A heredoc operator is recognised only outside single- and double-quoted text.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_squote = False
    in_dquote = False
    while i < n:
        c = text[i]
        if in_squote:
            out.append(c)
            if c == "'":
                in_squote = False
            i += 1
            continue
        if in_dquote:
            if c == "\\" and i + 1 < n:
                out.append(text[i : i + 2])
                i += 2
                continue
            out.append(c)
            if c == '"':
                in_dquote = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            out.append(c)
            i += 1
            continue
        if c == '"':
            in_dquote = True
            out.append(c)
            i += 1
            continue
        if c == "<" and text[i : i + 2] == "<<":
            m = _HEREDOC_OP_RE.match(text, i)
            if m is not None:
                delim = m.group(3)
                op_end = m.end()
                line_end = text.find("\n", op_end)
                if line_end == -1:
                    line_end = n
                rest_of_line = text[op_end:line_end]
                receiving_line_start = text.rfind("\n", 0, i) + 1
                receiving_line = text[receiving_line_start:i] + rest_of_line
                body_start = line_end + 1 if line_end < n else n
                body_end, resume_at = _find_delimiter_line(text, body_start, delim)
                body = text[body_start:body_end]
                keep_body = _line_invokes_shell(receiving_line)
                out.append(text[i:line_end])
                out.append("\n" if line_end < n else "")
                if keep_body:
                    out.append(body)
                out.append(text[body_end:resume_at])
                i = resume_at
                continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_line_continuations(text: str) -> str:
    """Remove backslash-newline continuations outside single quotes, as bash does.

    Must run AFTER strip_heredocs: a heredoc body line ending in ``\\`` is data, and removing
    continuations first would join it to the delimiter line and hide the delimiter (diff-confirm
    D1).
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_squote = False
    while i < n:
        c = text[i]
        if in_squote:
            out.append(c)
            if c == "'":
                in_squote = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            out.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n and text[i + 1] == "\n":
            out.append(" ")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_balanced_spans(text: str) -> list[tuple[int, int, str]]:
    """Find $(...) and `...` spans at any nesting, incl. inside double quotes.

    Returns (start, end, inner_text) tuples for TOP-LEVEL spans only (nested spans are handled by
    recursion into inner_text). Single-quoted literal text never opens a span.
    """
    spans: list[tuple[int, int, str]] = []
    i = 0
    n = len(text)
    in_squote = False
    while i < n:
        c = text[i]
        if in_squote:
            if c == "'":
                in_squote = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            i += 1
            continue
        if c == "$" and i + 1 < n and text[i + 1] == "(":
            depth = 1
            j = i + 2
            inner_start = j
            while j < n and depth > 0:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            spans.append((i, j, text[inner_start : j - 1]))
            i = j
            continue
        if c == "`":
            j = i + 1
            while j < n and text[j] != "`":
                j += 1
            end = j + 1 if j < n else j
            spans.append((i, end, text[i + 1 : j]))
            i = end
            continue
        i += 1
    return spans


_SHELL_C_RE = re.compile(
    r"(?:^|[\s/])(bash|sh|zsh|dash)\b((?:\s+-{1,2}[A-Za-z-]+)*\s+-[A-Za-z]*c[A-Za-z]*)\s+(['\"])(.*)",
    re.DOTALL,
)
_EVAL_RE = re.compile(r"(?:^|[\s;&|(])eval\s+(.*)", re.DOTALL)


def _extract_quoted_arg(text: str, quote: str) -> str | None:
    if quote == "'":
        end = text.find("'")
        return text[:end] if end != -1 else None
    # double-quoted: find matching unescaped close quote
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == '"':
            return text[:i]
        i += 1
    return None


def _shell_c_and_eval_args(text: str) -> list[str]:
    """Best-effort extraction of shell -c / eval string arguments anywhere in `text`."""
    args: list[str] = []
    for m in _SHELL_C_RE.finditer(text):
        arg = _extract_quoted_arg(m.group(4), m.group(3))
        if arg is not None:
            args.append(arg)
    for m in _EVAL_RE.finditer(text):
        rest = m.group(1).lstrip()
        if rest[:1] in ("'", '"'):
            arg = _extract_quoted_arg(rest[1:], rest[0])
            if arg is not None:
                args.append(arg)
        else:
            # eval's joined bareword arguments, up to end of line/command
            end = len(rest)
            for sep in ("\n", ";"):
                pos = rest.find(sep)
                if pos != -1:
                    end = min(end, pos)
            args.append(rest[:end])
    return args


def _tokenize(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        raise


_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "\n", "(", ")"})


def _split_simple_commands(tokens: list[str]) -> list[list[str]]:
    commands: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in _SEPARATORS:
            if current:
                commands.append(current)
                current = []
            continue
        current.append(tok)
    if current:
        commands.append(current)
    return commands


def _parse_git_subcommand(tokens: list[str]) -> tuple[str | None, bool]:
    """Return (subcommand, unknown_global_seen) when the first non-assignment word is `git`."""
    i = 0
    while i < len(tokens) and _is_assignment(tokens[i]):
        i += 1
    if i >= len(tokens) or _basename(tokens[i]) != "git":
        return None, False
    i += 1
    unknown_global = False
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        tok = tokens[i]
        base = tok.split("=", 1)[0]
        if base in GIT_ARG_GLOBALS:
            if "=" not in tok:
                i += 1
            i += 1
            continue
        if tok in GIT_NOARG_GLOBALS:
            i += 1
            continue
        unknown_global = True
        i += 1
    subcommand = tokens[i] if i < len(tokens) else None
    return subcommand, unknown_global


def _co_occurs_git_then_push(tokens: list[str]) -> bool:
    seen_git = False
    for tok in tokens:
        if _basename(tok) == "git":
            seen_git = True
        elif seen_git and tok == "push":
            return True
    return False


def _simple_command_push_shaped(tokens: list[str]) -> bool:
    if not tokens:
        return False
    subcommand, unknown_global = _parse_git_subcommand(tokens)
    if subcommand is not None and not unknown_global:
        if subcommand in _PUSH_LIKE_SUBCOMMANDS:
            return True
        if subcommand in _MULTI_WORD_PUSH_NAMESPACES:
            return "push" in tokens
        has_config = any(t == "-c" or t == "--config-env" or t.startswith("--config-env=") for t in tokens)
        if has_config and any("push" in t for t in tokens):
            return True
        return False
    return _co_occurs_git_then_push(tokens)


def _recurse_shell_and_eval(text: str) -> bool:
    for arg in _shell_c_and_eval_args(text):
        if ("$(" in arg or "`" in arg) and "git" in arg and "push" in arg:
            return True
        if is_push_shaped(arg):
            return True
    return False


def is_push_shaped(text: str) -> bool:
    """True when `text` contains any simple command that is push-shaped.

    Fails closed on a tokenise failure when the raw text pairs the words "git" and "push".
    """
    stripped = strip_heredocs(text)
    stripped = strip_line_continuations(stripped)

    for _, _, inner in _find_balanced_spans(stripped):
        inner_stripped = strip_heredocs(inner)
        if is_push_shaped(inner_stripped):
            return True

    if _recurse_shell_and_eval(stripped):
        return True

    elided = stripped
    for start, end, _ in reversed(_find_balanced_spans(stripped)):
        elided = elided[:start] + "SUBSTX" + elided[end:]

    try:
        tokens = _tokenize(elided)
    except ValueError:
        return "git" in text and "push" in text

    for command in _split_simple_commands(tokens):
        if _simple_command_push_shaped(command):
            return True
    return False


_CANON_OPTS = frozenset({"-u", "--set-upstream", "--dry-run", "-n"})
_CANON_OPT_PREFIX = "--force-with-lease"


def _strip_cd_prefix(command: str) -> tuple[str | None, str]:
    m = re.match(r"^cd\s+(\S+)\s*&&\s*(.*)$", command)
    if m:
        return m.group(1), m.group(2)
    return None, command


def _reject_shape(tokens: list[str]) -> NonCanonical | None:
    if any(tok in ("|", "&", "&&", "||", ";", "(", ")", "\n") for tok in tokens):
        return NonCanonical(reason="pipe, redirection or second segment")
    if any(tok in ("<", ">") for tok in tokens):
        return NonCanonical(reason="redirection")
    if any(tok.startswith("#") for tok in tokens):
        return NonCanonical(reason="trailing comment")
    if tokens and _is_assignment(tokens[0]):
        return NonCanonical(reason="env assignment prefix")
    return None


def _parse_git_push_prefix(tokens: list[str], worktree_hint: str | None) -> tuple[int, str | None] | NonCanonical:
    """Consume `git [-C <path>] push` and return (next_index, resolved_worktree_hint)."""
    i = 0
    if i >= len(tokens) or _basename(tokens[i]) != "git":
        return NonCanonical(reason="not a git command")
    i += 1

    resolved_worktree = worktree_hint
    if i < len(tokens) and tokens[i] == "-C":
        if i + 1 >= len(tokens):
            return NonCanonical(reason="-C without a path")
        resolved_worktree = tokens[i + 1]
        i += 2

    if i >= len(tokens) or tokens[i] != "push":
        return NonCanonical(reason="not a push subcommand")
    return i + 1, resolved_worktree


def _parse_push_options(tokens: list[str], start: int) -> tuple[int, bool] | NonCanonical:
    """Consume the option cluster after `push`. Returns (next_index, is_dry_run)."""
    i = start
    opts: list[str] = []
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        tok = tokens[i]
        if tok == "-c" or tok in ("--global", "--force", "-f", "--no-verify", "--all", "--mirror", "--tags"):
            return NonCanonical(reason=f"disallowed option {tok}")
        if tok in _CANON_OPTS or tok.startswith(_CANON_OPT_PREFIX):
            opts.append(tok)
            i += 1
            continue
        return NonCanonical(reason=f"unrecognised option {tok}")
    return i, ("--dry-run" in opts or "-n" in opts)


def _parse_refspec(remote: str, refspec: str, *, is_dry_run: bool, worktree_hint: str | None) -> ParsedPush | NonCanonical:
    if refspec.startswith("+"):
        return NonCanonical(reason="force prefix")
    if refspec.startswith(":"):
        branch = refspec[1:]
        if not branch:
            return NonCanonical(reason="malformed refspec")
        return ParsedPush(kind="delete", worktree_hint=worktree_hint, remote=remote, src=None, dst=branch)
    if ":" in refspec:
        src, dst = refspec.split(":", 1)
        if not src or not dst:
            return NonCanonical(reason="malformed refspec")
        kind = "dry_run" if is_dry_run else "push"
        return ParsedPush(kind=kind, worktree_hint=worktree_hint, remote=remote, src=src, dst=dst)
    kind = "dry_run" if is_dry_run else "push"
    return ParsedPush(kind=kind, worktree_hint=worktree_hint, remote=remote, src=refspec, dst=None)


def _parse_remote_and_refspec(
    remaining: list[str], *, is_dry_run: bool, worktree_hint: str | None
) -> ParsedPush | NonCanonical:
    if not remaining:
        return ParsedPush(kind="bare_push", worktree_hint=worktree_hint, remote=None, src=None, dst=None)

    remote, rest_args = remaining[0], remaining[1:]
    if not rest_args:
        return ParsedPush(kind="bare_push", worktree_hint=worktree_hint, remote=remote, src=None, dst=None)

    if rest_args[0] == "--delete":
        if len(rest_args) != 2:
            return NonCanonical(reason="--delete without exactly one branch")
        return ParsedPush(kind="delete", worktree_hint=worktree_hint, remote=remote, src=None, dst=rest_args[1])

    if len(rest_args) > 1:
        return NonCanonical(reason="more than one refspec")

    return _parse_refspec(remote, rest_args[0], is_dry_run=is_dry_run, worktree_hint=worktree_hint)


def parse_canonical(command_text: str) -> ParsedPush | NonCanonical:
    """Parse a single canonical `git push` form. Returns NonCanonical for anything else.

    Whole command must match, optionally prefixed by one ``cd <path> &&``.
    """
    text = strip_line_continuations(command_text).strip()
    if "\n" in text:
        return NonCanonical(reason="multiple lines")
    worktree_hint, rest = _strip_cd_prefix(text)
    rest = rest.strip()
    if not rest:
        return NonCanonical(reason="empty command")

    try:
        tokens = _tokenize(rest)
    except ValueError:
        return NonCanonical(reason="tokenise failure")

    shape_error = _reject_shape(tokens)
    if shape_error is not None:
        return shape_error

    prefix = _parse_git_push_prefix(tokens, worktree_hint)
    if isinstance(prefix, NonCanonical):
        return prefix
    index, resolved_worktree = prefix

    options = _parse_push_options(tokens, index)
    if isinstance(options, NonCanonical):
        return options
    index, is_dry_run = options

    return _parse_remote_and_refspec(tokens[index:], is_dry_run=is_dry_run, worktree_hint=resolved_worktree)
