"""CD.40 pre-write credential scrubber (stdlib re only).

Replacement is '[REDACTED:<CLASS>]', classes applied in the order of CLASS_ORDER, each once. Deterministic,
idempotent, never raises on a str and never reports matched text -- counts only. A pattern change is a
parser_version bump by construction (config/telemetry/parser_versions.yaml).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CLASS_ORDER = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "BEARER_TOKEN",
)

_KEY_PREFIXES = "AKIA|ASIA|AIDA|AROA|AGPA|ANPA|ANVA|ASCA|APKA"
_AWS_ACCESS = re.compile(rf"(?<![A-Za-z0-9])(?:{_KEY_PREFIXES})[A-Z0-9]{{16}}(?![A-Za-z0-9])")
_CONTEXT_TAIL = r"""\\*"?[ \t]*[:=][ \t]*\\*"?)([A-Za-z0-9/+=_\-]{8,})"""
_AWS_SECRET = re.compile(r"(?i)((?:aws_secret_access_key|secretaccesskey)" + _CONTEXT_TAIL)
_AWS_SESSION = re.compile(r"(?i)((?:aws_session_token|sessiontoken)" + _CONTEXT_TAIL)
_ANTHROPIC = re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}")
_GITHUB = re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{80,})(?![A-Za-z0-9_])")
_BEARER = re.compile(r"(\bBearer[ \t]+)([A-Za-z0-9._~+/=\-]{20,})")


@dataclass(frozen=True)
class ScrubResult:
    text: str
    counts: dict[str, int]


def _marker(cls: str) -> str:
    return f"[REDACTED:{cls}]"


def scrub_text(text: str) -> ScrubResult:
    counts = dict.fromkeys(CLASS_ORDER, 0)

    def whole(cls: str):
        def repl(_match: re.Match[str]) -> str:
            counts[cls] += 1
            return _marker(cls)

        return repl

    def anchored(cls: str):
        def repl(match: re.Match[str]) -> str:
            counts[cls] += 1
            return match.group(1) + _marker(cls)

        return repl

    def bearer(match: re.Match[str]) -> str:
        token = match.group(2)
        if len(token) < 32 and not any(ch.isdigit() for ch in token):
            return match.group(0)
        counts["BEARER_TOKEN"] += 1
        return match.group(1) + _marker("BEARER_TOKEN")

    out = _AWS_ACCESS.sub(whole("AWS_ACCESS_KEY_ID"), text)
    out = _AWS_SECRET.sub(anchored("AWS_SECRET_ACCESS_KEY"), out)
    out = _AWS_SESSION.sub(anchored("AWS_SESSION_TOKEN"), out)
    out = _ANTHROPIC.sub(whole("ANTHROPIC_API_KEY"), out)
    out = _GITHUB.sub(whole("GITHUB_TOKEN"), out)
    out = _BEARER.sub(bearer, out)
    return ScrubResult(out, {k: v for k, v in counts.items() if v})
