"""String- and comment-aware HCL helpers shared by the platform-security-* detector tests.

Moved verbatim out of test_platform_role_iam_change_alarms.py (Decision 128 decompose-by-default;
the alarm test was 483 of 500 SLOC). Patterns are string literals full of braces, so a naive brace
count would split mid-string; comments are blanked so a commented header never matches.
"""

from __future__ import annotations

import re
from functools import lru_cache


def _scan(text: str, blank_strings: bool) -> str:
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#" or (c == "/" and text[i + 1 : i + 2] == "/"):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                step = 2 if text[i] == "\\" else 1
                if blank_strings:
                    for j in range(i, min(i + step, n)):
                        if text[j] != "\n":
                            out[j] = " "
                i += step
            i += 1
        else:
            i += 1
    return "".join(out)


@lru_cache(maxsize=256)
def _mask(text: str) -> str:
    """Equal-length copy with string contents and #/// comments blanked (quotes and newlines kept)."""
    return _scan(text, blank_strings=True)


@lru_cache(maxsize=256)
def _strip_comments(text: str) -> str:
    """Equal-length copy with only comments blanked; string contents intact."""
    return _scan(text, blank_strings=False)


def _block_body(text: str, open_brace_idx: int) -> str:
    """Body between the '{' at open_brace_idx and its match, computed on masked text."""
    masked = _mask(text)
    depth = 0
    for i in range(open_brace_idx, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : i]
    raise ValueError(f"unbalanced braces at {open_brace_idx}")


def _resource_body(text: str, rtype: str, rname: str) -> str | None:
    m = re.search(rf'resource\s+"{re.escape(rtype)}"\s+"{re.escape(rname)}"\s*\{{', _strip_comments(text))
    return None if m is None else _block_body(text, m.end() - 1)


def _resources(text: str) -> list[tuple[str, str, str]]:
    """Every (kind, type, name) of a resource/data block, comments ignored."""
    return [
        (m.group(1), m.group(2), m.group(3))
        for m in re.finditer(r'\b(resource|data)\s+"([\w-]+)"\s+"([\w-]+)"\s*\{', _strip_comments(text))
    ]


def _local_map(text: str, name: str) -> dict[str, str]:
    """A `name = { "k" = "v" ... }` string map from a locals block, values unescaped."""
    m = re.search(rf"\b{re.escape(name)}\s*=\s*\{{", _strip_comments(text))
    if m is None:
        return {}
    body = _block_body(text, m.end() - 1)
    out: dict[str, str] = {}
    for em in re.finditer(r'"([^"]+)"\s*=\s*"((?:[^"\\]|\\.)*)"', _strip_comments(body)):
        out[em.group(1)] = em.group(2).replace('\\"', '"').replace("\\\\", "\\")
    return out


def _local_string(text: str, name: str) -> str | None:
    m = re.search(rf'\b{re.escape(name)}\s*=\s*"((?:[^"\\]|\\.)*)"', _strip_comments(text))
    return None if m is None else m.group(1)


def _attr(body: str, name: str) -> str | None:
    """Raw right-hand side of a top-level `name = ...` line inside a block body (first match)."""
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*(.+?)\s*$", _strip_comments(body), re.M)
    return None if m is None else m.group(1)


# Canary state-machine definition heredocs, the mutation anchors for the heartbeat canary red cases.
_HEREDOC_JSON = (
    '        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",\n'
    '        "Parameters": {\n'
    '          "RoleName": "platform-security-heartbeat-canary"\n'
    "        },\n"
    '        "ResultPath": null,\n'
    '        "End": true\n'
    "      }\n"
    "    }\n"
)
_HEREDOC_TWO_STATES = (
    '        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",\n'
    '        "Parameters": {\n'
    '          "RoleName": "platform-security-heartbeat-canary"\n'
    "        },\n"
    '        "ResultPath": null,\n'
    '        "End": true\n'
    "      },\n"
    '      "Second": {\n'
    '        "Type": "Pass",\n'
    '        "End": true\n'
    "      }\n"
    "    }\n"
)
_HEREDOC_RETRY = (
    '        "Resource": "arn:aws:states:::aws-sdk:iam:getRole",\n'
    '        "Parameters": {\n'
    '          "RoleName": "platform-security-heartbeat-canary"\n'
    "        },\n"
    '        "ResultPath": null,\n'
    '        "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 1}],\n'
    '        "End": true\n'
    "      }\n"
    "    }\n"
)
