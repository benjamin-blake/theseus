#!/usr/bin/env python3
"""DEP-10 stale-plan stderr signature classifier (Decision 158).

reconcile.yml's apply-reconcile job already matches terraform's stale-plan stderr signature
inline (`saved plan is stale|plan file can no longer be applied|state was changed`) to decide
whether to fall through to a same-run fresh re-plan (STALE_PLAN_FRESH_REPLAN). That inline match
is proven correct by the incident that motivated this module -- Terraform's own native apply
already detects the staleness class correctly.

This module extracts the SAME signature into a single named, tested function so the three
human-gated verbatim-apply sites that currently have no stale-plan detection at all
(terraform-apply-sandbox.yml's apply-sandbox and gated-apply jobs, reconcile.yml's
gated-apply-reconcile job) can emit a distinguishable PLAN_STALE_CONCURRENT_WRITER marker on a
match, giving ci-rca a stable, declared signature instead of a generic failure_category=unknown.
reconcile.yml's own apply-reconcile step is NOT refactored to call this module -- it already works
and is untouched; this module's job is to give the three currently-bare sites the SAME proven
signature, not to consolidate the fourth, already-working one.

No same-run fresh-replan is added at any of the three newly-covered sites: they stay fail-closed
exactly as before this module's addition (Decision 92 Environment-gates-execution / Decision 77
no-TOCTOU) -- this module is a diagnostic classifier only.

The `--wrap -- <command...>` CLI mode (below) runs the wrapped command AS A SUBPROCESS, capturing
and re-emitting its stderr, classifying it on a non-zero exit, and always returning the wrapped
command's own exit code. Chosen over a separate delegate script (Decision 59 scope-boundary
discipline: this module was already the plan's sole new file) or an inline multi-line `run:`
block (Decision 162 R3 / Decision 166 structural-size: each of the three call sites' `run:` body
must stay small): the wrapped command stays LITERAL, real argv in the workflow step's own `run:`
text, so a structural guard that substring-matches a step body for `terraform apply ... plan.bin`
(e.g. validate_dispatch_gated_apply_topology.py's invariant (ii)) is satisfied honestly by the
actual executed command, not a decoy string, and needs no changes of its own.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Optional

_STALE_PLAN_RE = re.compile(
    r"saved plan is stale|plan file can no longer be applied|state was changed",
    re.IGNORECASE,
)


def is_stale_plan_stderr(stderr: Optional[str]) -> bool:
    """True iff stderr matches one of DEP-10's three stale-plan stderr phrasings.

    A None or empty stderr never matches -- there is nothing to classify.
    """
    if not stderr:
        return False
    return bool(_STALE_PLAN_RE.search(stderr))


PLAN_STALE_CONCURRENT_WRITER_MARKER = (
    "::error::PLAN_STALE_CONCURRENT_WRITER -- the verbatim-apply of plan.bin failed because "
    "terraform detected the tfstate serial advanced out-of-band since this plan was captured (a "
    "concurrent apply landed after this plan was captured but before it was applied). Fails "
    "closed as designed; the convergence record is written RED and ci-rca will file a rec. No "
    "same-run fresh-replan is attempted at this site (Decision 77 no-TOCTOU for the push-path "
    "site; Decision 92 Environment-gates-execution for a human-gated site)."
)


def _wrap(command: list[str]) -> int:
    """Run `command` as a subprocess, re-emit its stderr, classify it on a non-zero exit, and
    return the command's own exit code verbatim (Decision 55/154 anti-masking: classification is
    a diagnostic guard only and must never itself change the caller's observed exit status)."""
    result = subprocess.run(command, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    stderr_content = result.stderr or ""
    sys.stderr.write(stderr_content)
    if result.returncode != 0 and is_stale_plan_stderr(stderr_content):
        print(PLAN_STALE_CONCURRENT_WRITER_MARKER, file=sys.stderr)
    return result.returncode


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint: `--wrap -- <command> [args...]` runs the command after `--` as a
    subprocess via _wrap(). Exits 2 with a usage message if `--wrap` or `--` (or a command after
    it) is missing."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--wrap" not in argv or "--" not in argv:
        print("usage: stale_plan_signature.py --wrap -- <command> [args...]", file=sys.stderr)
        return 2
    command = argv[argv.index("--") + 1 :]
    if not command:
        print("stale_plan_signature.py: --wrap requires a command after '--'", file=sys.stderr)
        return 2
    return _wrap(command)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
