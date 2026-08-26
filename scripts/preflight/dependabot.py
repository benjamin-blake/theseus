"""Stranded-dependabot-PR concern for session_preflight.

Dependabot PRs are invisible to every existing wake signal: ci.yml's signal-green job is scoped to
`claude/*` head refs and pr-conflict-signal.yml polls `claude/*` only, so a bump that goes behind
main, conflicts, or waits on a CODEOWNERS review simply sits there. Once an ecosystem reaches
`open-pull-requests-limit` (5, per .github/dependabot.yml) Dependabot stops opening PRs for it
entirely, which turns a stalled backlog into a silent dependency freeze.

This module is the deterministic detector for that state (Decision 59): one `gh pr list` shell-out
per preflight run, no warehouse read, no AWS credentials. It computes; `/orient` only renders what
it wrote to the preflight cache.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

# A PR this old has outlived any plausible "CI is still running" explanation -- two dependabot
# weekly cadences plus slack.
STRANDED_AGE_DAYS = 14

# gh's mergeStateStatus for "needs a rebase" (DIRTY) and "a required review/check is holding it"
# (BLOCKED). Both are terminal without intervention, so age is irrelevant for them.
STRANDED_MERGE_STATES = frozenset({"DIRTY", "BLOCKED"})

# .github/dependabot.yml sets open-pull-requests-limit: 5 for both ecosystems. At the limit
# Dependabot opens nothing new, so saturation is a harder signal than any single stranded PR.
ECOSYSTEM_PR_LIMIT = 5

_UNKNOWN_ECOSYSTEM = "unknown"


def _ecosystem(head_ref: str) -> str:
    """Ecosystem slug from a dependabot head ref (`dependabot/pip/...` -> `pip`)."""
    parts = (head_ref or "").split("/")
    if len(parts) >= 3 and parts[0] == "dependabot" and parts[1]:
        return parts[1]
    return _UNKNOWN_ECOSYSTEM


def _age_days(created_at: str, now: datetime) -> float | None:
    """Whole-day age of an ISO-8601 `createdAt` in UTC, rounded to 0.1d; None when unparseable.

    Rounding happens once, here, so the age reported in the payload and the age the stranded
    threshold is applied to can never disagree.
    """
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return round((now - created).total_seconds() / 86400.0, 1)


def _is_stranded(age_days: float | None, merge_state: str) -> bool:
    """DIRTY/BLOCKED is always stranded (terminal without intervention); otherwise age decides."""
    if merge_state in STRANDED_MERGE_STATES:
        return True
    return age_days is not None and age_days >= STRANDED_AGE_DAYS


def check_stranded_prs() -> dict | None:
    """Return the open-dependabot-PR backlog signal, or None when `gh` cannot answer.

    Shape:
        {"open_total": int,
         "by_ecosystem": {"pip": int, ...},
         "stranded": [{"number", "title", "ecosystem", "age_days", "merge_state"}],
         "quota_saturated": ["pip", ...]}

    None (never an empty dict) means the signal is UNAVAILABLE -- gh missing, unauthenticated,
    timed out, or answering garbage -- so a consumer can render UNKNOWN rather than a false clean
    bill of health. A healthy repo with no open bumps returns a populated dict with `open_total: 0`.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--author",
                "app/dependabot",
                "--state",
                "open",
                "--json",
                "number,title,headRefName,mergeStateStatus,createdAt",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        prs = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, IndexError, KeyError):
        return None

    if not isinstance(prs, list):
        return None

    now = datetime.now(timezone.utc)
    by_ecosystem: dict[str, int] = {}
    stranded: list[dict] = []

    for pr in prs:
        if not isinstance(pr, dict):
            continue
        ecosystem = _ecosystem(pr.get("headRefName", ""))
        by_ecosystem[ecosystem] = by_ecosystem.get(ecosystem, 0) + 1
        age_days = _age_days(pr.get("createdAt", ""), now)
        merge_state = pr.get("mergeStateStatus", "") or ""
        if _is_stranded(age_days, merge_state):
            stranded.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "ecosystem": ecosystem,
                    "age_days": age_days,
                    "merge_state": merge_state,
                }
            )

    return {
        "open_total": sum(by_ecosystem.values()),
        "by_ecosystem": by_ecosystem,
        "stranded": stranded,
        "quota_saturated": sorted(eco for eco, count in by_ecosystem.items() if count >= ECOSYSTEM_PR_LIMIT),
    }
