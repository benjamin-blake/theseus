"""Episode identity for sensor_liveness's loop_liveness_stale recs (Decision 80/104/124 facade).

Lifted out of sensor_liveness.py (PLAN-monitor-liveness-sweep) to fund that module's SLOC budget
and to re-key episode identity on (loop, leg) rather than (loop) alone -- the cadence leg
(schedule stopped firing) and the success leg (schedule fires, every run fails) are different
operator actions and must resolve into independently-closable recs, never one flip-flopping title.

TITLES ARE START-ANCHORED (`Loop: {k}. Episode: {a}. Bucket: {n}. ...`) because
`recs_by_title_prefix` binds the WHOLE LIKE pattern with no implicit wildcard (Decision 142). The
leg marker is appended AFTER that anchored prefix, never before it, or the sweep breaks. CADENCE is
the bare, marker-less legacy grammar -- every rec filed before this leg existed (e.g. the live
rec-3860 "Loop: main-canary.yml. Episode: run:31336661344. Bucket: 8. ...") carries no marker, and
a title with no marker is always the cadence leg; only a non-cadence leg ever gets an explicit
`Leg: {leg}.` segment.
"""

from __future__ import annotations

from typing import Any, Optional

_Info = dict[str, Any]
_Rows = list[_Info]

# SoT: src.common.ducklake_scd2_schema.STATUS_TRANSITIONS["ops_recommendations"]["resolved"] --
# mirrored (not imported) like budget_ingest.RESOLVED_REC_STATUSES; a test pins the two together.
RESOLVED_REC_STATUSES: frozenset[str] = frozenset({"closed", "declined", "superseded"})

_REMEDIATION_GENERIC = (
    "State unknown; investigate a removed `schedule:` block, a delivery drop, or GitHub's own inactivity auto-disable."
)
_REMEDIATION_BY_STATE: dict[str, str] = {
    "disabled_inactivity": (
        "GitHub auto-disabled this workflow after 60 idle days (state: disabled_inactivity) -- "
        "re-enable it from the Actions tab."
    ),
    "disabled_manually": "Manually disabled (state: disabled_manually) -- re-enable it from the Actions tab if unintended.",
    "active": (
        "state: active -- investigate a delivery drop or a removed `schedule:` block; auto-disable does not explain this."
    ),
}


def _episode_title(loop: str, anchor: str, bucket: int, leg: str = "cadence") -> str:
    if leg == "cadence":
        return f"Loop: {loop}. Episode: {anchor}. Bucket: {bucket}. Scheduled loop has not run within its derived threshold"
    return (
        f"Loop: {loop}. Episode: {anchor}. Bucket: {bucket}. Leg: {leg}. "
        "Scheduled loop has not succeeded within its derived threshold"
    )


def _title_leg(title: str) -> str:
    """cadence unless the title carries an explicit non-cadence `Leg: {leg}.` marker."""
    return "success" if ". Leg: success." in title else "cadence"


def _parse_episode_title(title: str) -> Optional[tuple[str, str, int]]:
    """(loop, anchor, bucket) parsed back out of a title this module wrote, or None. The leg lives
    after the parsed bucket segment and is read separately via `_title_leg`."""
    if not title.startswith("Loop: ") or ". Episode: " not in title or ". Bucket: " not in title:
        return None
    try:
        loop_part, rest = title.split(". Episode: ", 1)
        anchor_part, rest = rest.split(". Bucket: ", 1)
        return loop_part[len("Loop: ") :], anchor_part, int(rest.split(".", 1)[0])
    except (ValueError, IndexError):
        return None


def _is_open_loop_row(rec: _Info, loop: str, leg: str = "cadence") -> bool:
    """The live path (scripts.rec_episode.find_recs) already scopes on source="loop_liveness_stale"
    and status="open" via a structural current_state read (rec-3291 / rec-3563 class fix), so both
    keys are guaranteed present and correct on a live row. An injected `open_recs` test fixture may
    still omit either key for brevity -- absent is treated as already-satisfied, an explicit value
    is still honoured. A legacy title with no leg marker (rec-3860's shape) is CADENCE."""
    status = rec.get("status")
    if status is not None and status != "open":
        return False
    source = rec.get("source")
    if source is not None and source != "loop_liveness_stale":
        return False
    title = rec.get("title")
    if title is None:
        return True
    title_str = str(title)
    return title_str.startswith(f"Loop: {loop}. ") and _title_leg(title_str) == leg


def _filter_resolved_rows(rows: _Rows, loop: str, leg: Optional[str] = None) -> _Rows:
    """Exact client-side re-filter shared by the live sweep and an injected `resolved_recs` list:
    LIKE's `_` wildcard would otherwise let `Loop: __fleet__.%` match a row titled
    `Loop: XXfleetYY. ...`, so membership is re-checked with plain string equality. `leg=None`
    (the raw per-loop sweep pool, memoised once per tick) returns both legs; a leg reconciliation
    always re-filters that shared pool down to its own leg -- no second warehouse read."""
    return [
        row
        for row in rows
        if str(row.get("title") or "").startswith(f"Loop: {loop}. ")
        and (leg is None or _title_leg(str(row.get("title") or "")) == leg)
        and row.get("source") == "loop_liveness_stale"
        and row.get("status") in RESOLVED_REC_STATUSES
    ]


def _same_anchor_best_row(resolved_rows: _Rows, anchor: str) -> Optional[_Info]:
    """The resolved row at the CURRENT anchor with the MAXIMUM bucket (never the first hit)."""
    best: Optional[_Info] = None
    best_bucket = -1
    for row in resolved_rows:
        parsed = _parse_episode_title(str(row.get("title") or ""))
        if parsed is not None and parsed[1] == anchor and parsed[2] > best_bucket:
            best, best_bucket = row, parsed[2]
    return best


def _cross_anchor_newest(resolved_rows: _Rows, anchor: str) -> Optional[_Info]:
    """Highest-id resolved row at a DIFFERENT anchor (`recs_by_title_prefix` orders by id
    ascending, so the last match in iteration order is newest)."""
    newest: Optional[_Info] = None
    for row in resolved_rows:
        parsed = _parse_episode_title(str(row.get("title") or ""))
        if parsed is not None and parsed[1] != anchor:
            newest = row
    return newest


def _episode_context(info: _Info) -> str:
    leg = info.get("leg", "cadence")
    remediation = _REMEDIATION_BY_STATE.get(str(info.get("state") or ""), _REMEDIATION_GENERIC)
    peers_note = f" Stale peers: {', '.join(info['stale_peers'])}." if info.get("stale_peers") else ""
    lede = "No `?event=schedule` run" if leg == "cadence" else "No `?event=schedule&status=success` run"
    return (
        f"Loop: {info['loop']}. Episode: {info['anchor']}. Bucket: {info['bucket']}. {lede} "
        f"within the derived threshold ({info['threshold_seconds'] / 3600:.1f}h); last signal age "
        f"{info['age_seconds'] / 3600:.1f}h.{peers_note} {remediation} Never auto-closed -- restored "
        "cadence does not resolve this rec; a human closes it once satisfied (source loop_liveness_stale, LSA-02)."
    )
