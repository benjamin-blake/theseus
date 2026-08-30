#!/usr/bin/env python3
"""Public-repo redaction helper for the speculative-plan PR comment (Decision 101 boundary).

Two modes, both fail closed:

redact
    stdin is the raw ``terraform show`` text. Replaces the tfvars-sourced secrets (env
    ``_ACCT``/``_DEV``/``_ADM``/``_OWNER``) with placeholders, then fails if a 12-digit
    account-id-shaped TOKEN survives. The shape check belongs HERE, on untrusted terraform
    output, and nowhere else.

assert-clean
    stdin is the final comment body. Fails if any secret literal appears anywhere in it.
    Deliberately NO shape check: the body embeds hex identifiers -- the saved-plan sha256 digest
    and the 40-hex PR head SHA -- whose digit runs false-positive the account-id shape. That is
    the 2026-08-30 REDACTION_FAIL on PR #975, where digest ...f740037807611c... contained twelve
    digits bounded by hex letters and the job failed with the account id correctly redacted.

``_ACCT`` is required non-empty in both modes: an empty account id means the tfvars parse failed,
and replace-based redaction would silently no-op exactly when redaction matters most.

``owner_email`` is scrubbed alongside the account id and the two ExternalIds because
``terraform/personal/main.tf`` sets ``default_tags { Owner = var.owner_email }``, so a destroy plan
prints it on every tagged resource.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TextIO

# Token-boundary-aware, NOT merely digit-boundary-aware. A real account id appears as its own
# token -- inside an ARN (``...:iam::123456789012:role/x``) or standalone -- never embedded in a
# longer alphanumeric run. Bounding on [0-9A-Za-z] therefore keeps every genuine detection while
# refusing to match a digit run that is part of a hex or base64 token. That distinction is
# load-bearing here: this plan's null_resource triggers carry md5 ``query_hash`` values, and a
# digit-boundary-only pattern has a measured ~1.2% hit rate per md5 (~7% across this plan's six),
# which is the rec-3322 false-positive class re-appearing on the plan text instead of the body.
ACCOUNT_ID_SHAPE = re.compile(r"(?<![0-9A-Za-z])\d{12}(?![0-9A-Za-z])")

_MODES = ("redact", "assert-clean")

_SECRET_ENV_PLACEHOLDERS = (
    ("_ACCT", "[ACCOUNT_ID]"),
    ("_DEV", "[ExternalId]"),
    ("_ADM", "[ExternalId]"),
    ("_OWNER", "[OWNER_EMAIL]"),
)


def secret_pairs(env: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Return (secret_value, placeholder) pairs sourced from the environment."""
    source = os.environ if env is None else env
    return [(source.get(name, ""), placeholder) for name, placeholder in _SECRET_ENV_PLACEHOLDERS]


def redact(text: str, pairs: list[tuple[str, str]]) -> str:
    """Replace every non-empty secret literal with its placeholder."""
    for value, placeholder in pairs:
        if value:
            text = text.replace(value, placeholder)
    return text


def surviving_literals(text: str, pairs: list[tuple[str, str]]) -> list[str]:
    """Return the placeholders whose secret literal still appears in text."""
    return [placeholder for value, placeholder in pairs if value and value in text]


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) == 2 else ""
    if mode not in _MODES:
        print(f"::error::redaction_check: usage: redaction_check.py {{{'|'.join(_MODES)}}}", file=sys.stderr)
        return 1

    # In redact mode stdout is captured into PLAN_REDACTED, so diagnostics must go to stderr or
    # they would be spliced into the comment body itself.
    diag: TextIO = sys.stderr if mode == "redact" else sys.stdout

    pairs = secret_pairs()
    if not pairs[0][0]:
        print(
            "::error::REDACTION_FAIL: account_id parsed empty from tfvars; redaction would no-op.",
            file=diag,
        )
        return 1

    text = sys.stdin.read()

    if mode == "redact":
        text = redact(text, pairs)
        if ACCOUNT_ID_SHAPE.search(text):
            print(
                "::error::REDACTION_FAIL: a 12-digit account-shaped run survives in the redacted plan text.",
                file=diag,
            )
            return 1
        sys.stdout.write(text)
        return 0

    survivors = surviving_literals(text, pairs)
    if survivors:
        print(
            f"::error::REDACTION_FAIL: secret literal(s) survive in the comment body: {' '.join(sorted(set(survivors)))}",
            file=diag,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
