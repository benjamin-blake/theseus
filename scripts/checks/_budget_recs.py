"""Fast-tier budget-breach / budget-bypass recommendation-filing helpers.

Decision 128 decomposition: extracted from scripts/checks/_scaffolding.py, which sat at 485/500
SLOC and would have breached the 500-line budget once the VTS-20 dedupe (below) was added --
decompose-don't-raise, not a config/sloc_budgets.yaml raise. _scaffolding.py re-exports both
public names as a facade (Decision 80/104/124 pattern) so `patch("validate._file_budget_breach_rec")`
/ `patch("validate._file_budget_bypass_rec")` and `from scripts.checks._scaffolding import
_file_budget_breach_rec` keep resolving unchanged; scripts/validate.py's own facade re-export of
those two names (sourced from _scaffolding) is likewise untouched.

VTS-20 (audit validate-test-suite-4df4d48): a repeated fast-tier budget breach on the same
(branch, dominant_phase) now UPDATES the existing open budget_breach rec instead of filing a
duplicate. The dedupe lookup reads the DuckLake reader boundary via scripts.rec_episode.find_rec's
source-scoped structural read (src.common.ducklake_reader_client.make_reader -- Decision 84
warehouse-SoT), never logs/.recommendations-log.jsonl (a read cache is never a write source). A
reader failure loud-warns and falls through to filing a new rec -- the breach itself is always
recorded; only the dedupe is best-effort (Decision 55: no silent skip). Decision 142 is the
closest prior art for a non-LLM, reader-verb-based update-instead-of-insert dedupe.

rec-3291 / rec-3563: this module used to carry its own duplicate `_fetch_open_recs` (a bulk fetch
of the `open_recs` named verb, which projects neither `status` nor `source`) and an
absent-key-means-satisfied inversion in `_is_open_budget_breach_row` to work around it. Both are
gone -- the dedupe lookup now goes through scripts.rec_episode.find_rec, whose source-scoped
current_state read returns every column, so a live row always carries both keys.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from scripts.checks import _common
from scripts.rec_episode import find_rec, find_recs

# Shared truncation for the diff manifest, in both the human diagnostics below and the machine
# record build_budget_record emits -- so a reader comparing the two never sees two lengths.
_MANIFEST_TRUNCATION = 20

# The 10 slowest phases only: enough to attribute an overrun, small enough that the block stays a
# footnote on a manifest whose `selected`/`provenance` keys dominate its size.
_PHASE_TIMES_KEPT = 10

# Outcomes whose branch attempts a recommendation write at all. The other three
# ("within_budget", "forced_waived", "forced_ceiling_breach") are notice-only by construction.
_REC_FILING_OUTCOMES = ("breach", "bypass")


def _mirror_to_step_summary(title: str, message: str) -> None:
    """Append a titled section to the CI job's step summary, or do nothing when
    GITHUB_STEP_SUMMARY is unset (the caller's stderr print is then the only diagnostic).

    CI-native diagnosability with no portal and no outbox (Decision 84 I-4). Local to this module
    rather than reusing scripts/checks/_scaffolding.py::_mirror_budget_notice_to_summary:
    _scaffolding imports THIS module for its facade re-exports, so importing back would cycle --
    and that helper also prints the message, which both callers here already do themselves (to
    stderr, deliberately, since these are warnings rather than gate notices).
    """
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"\n## {title}\n\n{message}\n")


def build_budget_record(
    *,
    outcome: str,
    elapsed_s: float,
    limit_s: float,
    dominant_phase: str | None,
    diff_manifest: list[str],
    phase_times: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build the machine-readable budget record for one fast-tier run (D2-2 stage 1).

    Pure apart from reading environment variables: no portal call, no reader call, no filesystem
    access and -- critically -- NO git subprocess. CI identity comes entirely from GITHUB_HEAD_REF
    (the PR branch, matching the `git branch --show-current` value the local dedupe markers key
    on), GITHUB_RUN_ID and GITHUB_REPOSITORY, because the CI path is pinned to make no subprocess
    call at all (tests/checks/test__budget_recs.py's mock_run.assert_not_called()). Absent
    variables degrade to "unknown"; nothing here raises.

    The caller (scripts/validate.py's budget-assertion scaffold) attaches the result to the
    selection manifest under `budget`, which the pr-validate job already uploads as an artifact --
    so the CI breach population becomes enumerable with zero workflow YAML and zero credentials.

    `rec_filed` records whether the rec-filing PATH was taken, not that a portal write succeeded:
    filing itself is best-effort and loud-skips on failure (see _file_budget_breach_rec).
    """
    ci = os.environ.get("CI") == "true"
    if outcome not in _REC_FILING_OUTCOMES:
        rec_filed, rec_skipped_reason = False, "no_rec_for_outcome"
    elif ci:
        rec_filed, rec_skipped_reason = False, "ci_no_portal_access"
    else:
        rec_filed, rec_skipped_reason = True, None
    slowest = sorted((phase_times or {}).items(), key=lambda item: item[1], reverse=True)[:_PHASE_TIMES_KEPT]
    return {
        "outcome": outcome,
        "elapsed_s": round(elapsed_s, 3),
        "elapsed_min": round(elapsed_s / 60, 3),
        "limit_s": float(limit_s),
        "dominant_phase": dominant_phase,
        "phase_times": {name: round(seconds, 3) for name, seconds in slowest},
        "diff_file_count": len(diff_manifest),
        "diff_manifest": list(diff_manifest[:_MANIFEST_TRUNCATION]),
        "branch": os.environ.get("GITHUB_HEAD_REF") or "unknown",
        "run_id": os.environ.get("GITHUB_RUN_ID") or "unknown",
        "repository": os.environ.get("GITHUB_REPOSITORY") or "unknown",
        "ci": ci,
        "rec_filed": rec_filed,
        "rec_skipped_reason": rec_skipped_reason,
    }


def _is_open_budget_breach_row(rec: dict) -> bool:
    """Straight status/source check.

    A live row now always carries both keys: the dedupe lookup reads via
    scripts.rec_episode.find_rec's source-scoped structural read (current_state on
    ops_recommendations, unnarrowed), not the retired `open_recs` named verb, which projected
    neither. Kept as a small readable predicate rather than folded inline.
    """
    return rec.get("status") == "open" and rec.get("source") == "budget_breach"


def _find_open_budget_breach_rec(open_recs: list[dict], branch: str, dedup_phase: str) -> dict | None:
    """Return the open budget_breach rec matching (branch, dedup_phase), or None (VTS-20).

    `open_recs` is scripts.rec_episode.find_rec's `rows` test-injection seam -- treated as if it
    were already the result of the scoped source="budget_breach" read, so this stays a pure
    function over a supplied list for its own mirror tests. Matches on the same context
    substrings both breach writers put in a fresh rec ("Branch: {branch}." / "Dominant phase:
    {dedup_phase}."), so a rec filed before this dedupe landed still matches correctly on its
    next repeat breach.
    """
    branch_marker = f"Branch: {branch}."
    phase_marker = f"Dominant phase: {dedup_phase}."

    def _matches(rec: dict) -> bool:
        if not _is_open_budget_breach_row(rec):
            return False
        context = rec.get("context") or ""
        return branch_marker in context and phase_marker in context

    return find_rec("budget_breach", sub_key=_matches, sub_key_fields=("context",), rows=open_recs)


def _file_budget_breach_rec(elapsed_s: float, diff_manifest: list[str], dominant_phase: str | None) -> None:
    elapsed_min = elapsed_s / 60
    manifest_summary = ", ".join(diff_manifest[:_MANIFEST_TRUNCATION]) + (
        "..." if len(diff_manifest) > _MANIFEST_TRUNCATION else ""
    )

    if os.environ.get("CI") == "true":
        # CI-guard (Decision 84 I-4): the pr-validate CI job installs requirements-fast.txt (no
        # python-ulid) and has no AWS credentials, so file_rec's portal write can never complete
        # there -- it previously raised a swallowed ModuleNotFoundError inside the bare except
        # below. Skip the write (and the VTS-20 dedupe reader lookup, which needs the same
        # credentials) and print the full diagnostic LOUDLY instead: this is a no-op-plus
        # -loud-log, never a silent `if CI: return` (Decision 55) and never a buffered/replayed
        # outbox entry (Decision 84 I-4 -- nothing is staged for later delivery).
        message = (
            f"WARNING: fast-tier budget breach ({elapsed_min:.1f}m, limit 5m): dominant_phase="
            f"{dominant_phase or 'unknown'}, diff ({len(diff_manifest)} files): {manifest_summary}. Rec NOT filed (CI)."
        )
        print(message, file=sys.stderr)
        _mirror_to_step_summary("Fast-tier budget breach", message)
        return

    try:
        from scripts.ops_data_portal import file_rec, update_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        branch = branch_r.stdout.strip() or "unknown"
        dedup_phase = dominant_phase or "unknown"
        context = (
            f"Fast-tier budget breach: {elapsed_min:.1f} min elapsed (limit 5 min). "
            f"Branch: {branch}. Dominant phase: {dedup_phase}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Investigate which check caused the overrun and move it to the full tier or optimise it."
        )
        title = f"Fast-tier budget breach ({elapsed_min:.1f} min) on {branch}"

        # VTS-20 dedupe: look up an existing open budget_breach rec for (branch, dedup_phase) via
        # scripts.rec_episode.find_recs's source-scoped reader boundary -- never
        # logs/.recommendations-log.jsonl. A reader exception here degrades to "no match" (loud
        # warning, fall through to file_rec below) -- it must never crash the breach-recording
        # path itself.
        existing = None
        try:
            from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

            profile = resolve_aws_profile(default="agent_platform")
            existing = _find_open_budget_breach_rec(find_recs("budget_breach", profile=profile), branch, dedup_phase)
        except Exception as reader_exc:  # noqa: BLE001
            print(
                f"WARNING: budget-breach dedupe lookup failed (filing a new rec instead): {reader_exc}",
                file=sys.stderr,
            )
            existing = None

        if existing is not None:
            update_rec(existing["id"], {"title": title, "context": context})
            return

        file_rec(
            {
                "title": title,
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_breach",
                "effort": "S",
                "priority": "Medium",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(
            f"WARNING: budget breach rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )


def _file_budget_bypass_rec(
    elapsed_s: float | None,
    diff_manifest: list[str],
    reason: str | None,
    dominant_phase: str | None = None,
) -> None:
    manifest_summary = ", ".join(diff_manifest[:_MANIFEST_TRUNCATION]) + (
        "..." if len(diff_manifest) > _MANIFEST_TRUNCATION else ""
    )
    elapsed_part = f"{elapsed_s / 60:.1f} min" if elapsed_s is not None else "unknown"

    if os.environ.get("CI") == "true":
        # Defensive-only: validate.py's CI guard already hard-rejects --ignore-budget when
        # CI=="true" before this helper can be reached in the integrated flow. Kept for parity
        # with _file_budget_breach_rec and to cover any direct/test invocation (Decision 55: no
        # silent skip, never a buffered outbox -- Decision 84 I-4). G2: the step-summary mirror
        # is part of that parity -- this branch was stderr-only, an asymmetry with the breach
        # branch that is a live drift risk however unreachable the branch is today.
        message = (
            f"WARNING: fast-tier budget bypass rec NOT filed (CI environment, no portal access): "
            f"Elapsed: {elapsed_part}. Dominant phase: {dominant_phase or 'unknown'}. "
            f"Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}."
        )
        print(message, file=sys.stderr)
        _mirror_to_step_summary("Fast-tier budget bypass", message)
        return

    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        branch = branch_r.stdout.strip() or "unknown"
        context = (
            f"Fast-tier budget assertion bypassed via --ignore-budget on branch {branch}. "
            f"Elapsed: {elapsed_part}. Dominant phase: {dominant_phase or 'unknown'}. "
            f"Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Repeated bypass (>= 3 in 7 days) triggers a soft alert in session_preflight."
        )
        file_rec(
            {
                "title": f"Fast-tier budget bypassed on {branch}",
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_bypass",
                "effort": "S",
                "priority": "Low",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(
            f"WARNING: budget bypass rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )
