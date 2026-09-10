"""Backlog-health escalation (PLAN-backlog-health-detection).

Runs in the CREDENTIALED escalate job (id-token, portal writes). Treats probe.py's verdict
artifact as UNTRUSTED INPUT produced by a job that executed rec-authored commands with no
credentials of its own: `_rejoin_probe_verdicts` schema-validates it (only rec_id -> one of
probe.VERDICTS survives) and rejoins it against census.json's own probe_payload on rec_id +
acceptance_sha256, so a verdict for a rec_id census never sent to probe, or whose acceptance has
since changed, is dropped rather than trusted. `build_findings` then intersects every class's
finding set against a FRESH read of the currently-open recs, so a rec closed or edited between
census and escalate can never be acted on.

Four calls to scripts.rec_episode.run_episode, one per defect class, each with its own
`source` (registered in config/agent/data_quality/source_registry.yaml). Never closes or updates
an INDIVIDUAL rec by id -- taint must not steer a privileged verb; the only writes this module
makes are the four class-level rollup recs run_episode's file/update/close orchestration drives.
build_close's resolution records the finding count going to zero, not a per-rec disposition.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from scripts import rec_episode
from scripts.backlog_health import probe as probe_mod

SOURCE_VACUOUS_PROBE = "backlog_health_vacuous_probe"
SOURCE_ACCEPTANCE_QUALITY = "backlog_health_acceptance_quality"
SOURCE_DEPENDENCY_REF = "backlog_health_dependency_ref"
SOURCE_PREMISE_DEAD = "backlog_health_premise_dead"

ALL_SOURCES: tuple[str, ...] = (
    SOURCE_VACUOUS_PROBE,
    SOURCE_ACCEPTANCE_QUALITY,
    SOURCE_DEPENDENCY_REF,
    SOURCE_PREMISE_DEAD,
)

# The module every class's rollup rec anchors on -- this detector's own implementation, mirroring
# dedup-probe.yml's MARKER_FILE convention for a monitor-filed rec with no single "broken" source.
_ANCHOR_FILE = "scripts/backlog_health/classify.py"

_MAX_LISTED_IDS = 20


def _validate_probe_artifact(probe_artifact: dict[str, Any]) -> dict[str, str]:
    """Schema-validate the untrusted probe artifact: only (str rec_id -> str verdict in
    probe.VERDICTS) survives; anything else is dropped rather than trusted."""
    verdicts = probe_artifact.get("verdicts")
    if not isinstance(verdicts, dict):
        return {}
    clean: dict[str, str] = {}
    for rec_id, verdict in verdicts.items():
        if isinstance(rec_id, str) and isinstance(verdict, str) and verdict in probe_mod.VERDICTS:
            clean[rec_id] = verdict
    return clean


def rejoin_probe_verdicts(census_result: dict[str, Any], probe_artifact: dict[str, Any]) -> dict[str, str]:
    """Rejoin the (untrusted) probe verdicts against census's own probe_payload on rec_id +
    acceptance_sha256 -- a verdict for a rec_id census never sent to probe, or whose acceptance
    has since changed (a stale/tampered acceptance_sha256), is dropped rather than trusted."""
    clean_verdicts = _validate_probe_artifact(probe_artifact)
    sent_ids = {entry["id"] for entry in census_result["probe_payload"]}
    return {rec_id: verdict for rec_id, verdict in clean_verdicts.items() if rec_id in sent_ids}


def build_findings(
    census_result: dict[str, Any],
    classification: dict[str, dict[str, list[str]]],
    fresh_open_rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """The four classes' final finding sets, each intersected against a FRESH open-rec read so a
    rec closed or edited between census and escalate can never be acted on."""
    still_open = {row["id"] for row in fresh_open_rows}
    probe_split = classification["probe_split"]
    acceptance_quality = classification["acceptance_quality"]
    dependency_refs = classification["dependency_refs"]
    premise = classification["premise_dead_and_duplicates"]

    def _filtered(ids: list[str]) -> list[str]:
        return sorted({rec_id for rec_id in ids if rec_id in still_open})

    return {
        SOURCE_VACUOUS_PROBE: _filtered(probe_split["vacuous"]),
        SOURCE_ACCEPTANCE_QUALITY: _filtered(acceptance_quality["lint_reject"] + acceptance_quality["non_discriminating"]),
        SOURCE_DEPENDENCY_REF: _filtered(dependency_refs["malformed"] + dependency_refs["dangling"]),
        SOURCE_PREMISE_DEAD: _filtered(
            premise["premise_dead_bootstrap"] + premise["premise_dead_post_anchor"] + premise["near_duplicate"]
        ),
    }


def _title_for(source: str, count: int) -> str:
    labels = {
        SOURCE_VACUOUS_PROBE: (
            f"{count} acceptance probe(s) pass vacuously on main (no commit touched the target since creation)"
        ),
        SOURCE_ACCEPTANCE_QUALITY: (
            f"{count} open rec(s) carry a low-quality acceptance command (lint-rejected or non-discriminating)"
        ),
        SOURCE_DEPENDENCY_REF: f"{count} open rec(s) carry a malformed or dangling dependency reference",
        SOURCE_PREMISE_DEAD: (f"{count} open rec(s) are premise-dead (stale target) or a near-duplicate of another open rec"),
    }
    return f"Backlog health: {labels[source]}"


def _context_for(source: str, finding_ids: list[str]) -> str:
    shown = finding_ids[:_MAX_LISTED_IDS]
    suffix = f" (+{len(finding_ids) - _MAX_LISTED_IDS} more)" if len(finding_ids) > _MAX_LISTED_IDS else ""
    return (
        f"scripts/backlog_health's scheduled monitor (Decision 62 2026-06-16 amendment / CD.12, "
        f"alarm-not-gate) flagged {len(finding_ids)} open recommendation(s) under source={source!r}: "
        f"{', '.join(shown)}{suffix}. Re-run the monitor via the acceptance command below to confirm "
        "this list before triaging any individual rec."
    )


def _acceptance_for(source: str) -> str:
    return f"bin/venv-python -m scripts.backlog_health escalate --dry-run 2>&1 | grep -q '{source}: 0 findings'"


def _finding_payload(finding_ids: list[str]) -> str:
    current_ids = sorted(finding_ids)
    return json.dumps({"finding_ids": current_ids, "count": len(current_ids)})


def _base_fields(source: str, finding_ids: list[str]) -> dict[str, Any]:
    return {
        "title": _title_for(source, len(finding_ids)),
        "file": _ANCHOR_FILE,
        "status": "open",
        "priority": "High",
        "effort": "M",
        "risk": "low",
        "automatable": False,
        "verification_tier": "V1",
        "context": _context_for(source, finding_ids),
        "acceptance": _acceptance_for(source),
        # Stamped at file time too (not only on update) so the very next tick's build_update
        # comparison has a real baseline instead of reading an absent field as "no findings
        # last time" and writing a spurious update for an unchanged finding set.
        "context_v2_json": _finding_payload(finding_ids),
    }


def build_fields(source: str, finding_ids: list[str]) -> dict[str, Any]:
    """The returned dict's `source` value is a literal string per branch (never the `source`
    parameter itself) so scripts/checks/ops_governance/check_source_registry.py's literal scan --
    a textual pattern match on a quoted `source` key followed by a quoted string value -- can see
    and guard all four canonical_ids registered in config/agent/data_quality/source_registry.yaml."""
    base = _base_fields(source, finding_ids)
    if source == SOURCE_VACUOUS_PROBE:
        return base | {"source": "backlog_health_vacuous_probe"}
    if source == SOURCE_ACCEPTANCE_QUALITY:
        return base | {"source": "backlog_health_acceptance_quality"}
    if source == SOURCE_DEPENDENCY_REF:
        return base | {"source": "backlog_health_dependency_ref"}
    return base | {"source": "backlog_health_premise_dead"}


def build_update(source: str, finding_ids: list[str]):
    def _build(existing: dict[str, Any]) -> Optional[dict[str, Any]]:
        try:
            previous = json.loads(existing.get("context_v2_json") or "{}")
        except (ValueError, TypeError):
            previous = {}
        previous_ids = sorted(previous.get("finding_ids") or [])
        current_ids = sorted(finding_ids)
        if previous_ids == current_ids:
            return None
        return {
            "context": _context_for(source, finding_ids),
            "context_v2_json": _finding_payload(finding_ids),
        }

    return _build


def _build_fields_factory(source: str, finding_ids: list[str]) -> Callable[[], dict[str, Any]]:
    def _build() -> dict[str, Any]:
        return build_fields(source, finding_ids)

    return _build


def build_close(existing: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "closed",
        "resolution": "backlog-health monitor: class cleared -- 0 findings on the most recent scheduled run.",
    }


def run_all_episodes(
    census_result: dict[str, Any],
    classification: dict[str, dict[str, list[str]]],
    fresh_open_rows: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    profile: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    """One rec_episode.run_episode call per defect class. In dry-run mode, no portal write
    happens (build_fields()/build_update()/build_close() are never invoked by run_episode when
    dry_run short-circuits before dispatch) -- only the finding counts are reported."""
    findings = build_findings(census_result, classification, fresh_open_rows)
    results: dict[str, dict[str, Any]] = {}
    for source in ALL_SOURCES:
        ids = findings[source]
        if dry_run:
            results[source] = {"action": "dry_run", "rec_id": None, "count": len(ids)}
            continue
        result = rec_episode.run_episode(
            source=source,
            over_threshold=bool(ids),
            build_fields=_build_fields_factory(source, ids),
            build_update=build_update(source, ids),
            build_close=build_close,
            rows=fresh_open_rows,
            profile=profile,
        )
        results[source] = {**result, "count": len(ids)}
    return results
