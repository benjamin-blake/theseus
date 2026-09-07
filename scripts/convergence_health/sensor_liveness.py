"""Scheduled-loop liveness backstop (audit finding LSA-02, PLAN-sensor-liveness).

The fleet's other sensors all reason about the CONTENT of a run (drift, budget, convergence);
none notice a schedule that stops firing at all -- GitHub's 60-day inactivity auto-disable, a
deleted `schedule:` block, a silent delivery drop. This module is the fifth, alarm-only leg on the
convergence-health cron that closes that gap.

PEER SET IS DERIVED, NEVER DECLARED: `derive_scheduled_peers()` walks every
`.github/workflows/*.yml` at run time and reads its `on:.schedule` block -- no `sensors:` register
anywhere (a second register over the same population is the drift-by-design NS6 forbids).
`peers_from_workflow_docs` normalises PyYAML's bare `on:` key (parsed as Python `True`) and RAISES
on an empty result by DEFAULT -- the production chain `main_sensor_liveness -> detect_stale_loops
-> derive_scheduled_peers` passes no override, so fail-loud is inherited, never opt-in.

THRESHOLD IS DERIVED FROM EACH CRON: `cron_period_seconds` is a bounded 5-field shape matcher (no
croniter) covering the four live shapes; anything else raises. `staleness_threshold_seconds`
clamps 2x the nominal period into [6h, 45d] -- the floor tolerates best-effort scheduled delivery,
the ceiling is the largest threshold whose first bucket [T, 2T) still fits the 90-day Actions
run-retention window, so a `run:{id}` anchor never flips to `intro:{sha}` mid-bucket.

EPISODE GRAIN: the open matcher keys on (loop) ALONE (mirrors
`_budget_recs._is_open_budget_breach_row`), so a recovery-then-redeath while a rec is open UPDATES
it rather than minting a new episode. The resolved matcher sweeps on (loop) alone too -- an
anchor-pinned sweep cannot see across the anchor change a flap causes -- then discriminates
client-side into two dwell legs: SAME anchor mutes on the MAX resolved bucket (`current <= max+1`);
CROSS anchor costs one `rec_by_id` for the newest resolved rec's closure timestamp and mutes while
`now - closed_at < threshold`. Titles are START-ANCHORED (`Loop: {k}. Episode: {a}. Bucket: {n}.
...`) because `recs_by_title_prefix` binds the WHOLE LIKE pattern with no implicit wildcard --
`f"Loop: {k}.%"` needs its trailing `%` or the sweep returns zero rows forever (Decision 142).

NO-OP UPDATES ARE SKIPPED (bucket-quantised title/context, so an unchanged episode writes no
duplicate SCD2 row). FILE/UPDATE ONLY, NEVER CLOSE -- restored cadence does not auto-resolve a
filed rec. FLEET COLLAPSE: `FLEET_COLLAPSE_MIN_STALE` simultaneously-stale peers collapse to one
`__fleet__` episode (per-loop episodes suppressed, never closed) whose bucket derives from its OWN
anchor age -- never `min(bucket over stale peers)`, non-monotonic and able to silently mute an
acknowledged fleet outage. FAIL LOUDLY, NO OUTBOX (Decision 84 I-4): every external dependency is
injected, and a dead query raises rather than reporting an empty, reassuring population.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, cast

import yaml

from scripts.convergence_health.approvals import _make_github_caller
from scripts.convergence_health.code_drift import _assert_full_history
from scripts.convergence_health.record import _parse_utc
from scripts.rec_episode import find_recs

DEFAULT_OWNER = "benjamin-blake"
DEFAULT_REPO = "theseus"

_WORKFLOWS_DIR = ".github/workflows"
_REPO_ROOT = Path(__file__).parent.parent.parent

# Short aliases so injected-dependency signatures stay on one line (repeated 5-40x each below).
_Info = dict[str, Any]
_Rows = list[_Info]
_GhCaller = Callable[[str], Any]
_GitRunner = Callable[[list[str]], str]
_PortalCaller = Callable[[str, _Info], Any]

# SoT: src.common.ducklake_scd2_schema.STATUS_TRANSITIONS["ops_recommendations"]["resolved"] --
# mirrored (not imported) like budget_ingest.RESOLVED_REC_STATUSES; a test pins the two together.
RESOLVED_REC_STATUSES: frozenset[str] = frozenset({"closed", "declined", "superseded"})

_MIN_THRESHOLD_SECONDS = 6 * 3600
_MAX_THRESHOLD_SECONDS = 45 * 86400
_THRESHOLD_MULTIPLIER = 2

FLEET_COLLAPSE_MIN_STALE = 3
_FLEET_LOOP_KEY = "__fleet__"

_DRY_RUN_LABELS = {"file": "would_file", "update": "would_update", "unchanged": "would_skip", "drop": "would_drop"}

_EMPTY_PEER_SET_MESSAGE = (
    "scripts.convergence_health.sensor_liveness: derived ZERO schedule-bearing peers from "
    f"{_WORKFLOWS_DIR}/*.yml -- refusing an all-clear from what may be a broken parse (a missing "
    "directory, a swallowed YAML load failure, or the PyYAML `on:`-as-True key going unnormalised). "
    "Decision 55: a dead sensor and a truly schedule-free fleet must not look the same."
)
_DEAD_QUERY_MESSAGE = (
    "scripts.convergence_health.sensor_liveness: the GitHub workflow-runs query for {loop!r} returned "
    "no payload (absent GH_TOKEN/GITHUB_TOKEN, or a failed query). Refusing to report an empty run "
    "population from a query that never ran -- a dead sensor and a live peer must not look the same."
)
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


# --- Peer derivation: never declared, fail-loud by default on an empty result. ---


def peers_from_workflow_docs(docs: _Info, require_non_empty: bool = True) -> dict[str, list[str]]:
    """Pure seam: {filename: parsed_yaml_dict} -> {filename: [cron_expr, ...]}. Normalises
    PyYAML's `on`-as-True key via `data.get("on", data.get(True, {}))`. Raises when
    `require_non_empty` (the default, and the only value the production chain passes) and the
    result is empty."""
    peers: dict[str, list[str]] = {}
    for filename, data in docs.items():
        if not isinstance(data, dict):
            continue
        on_block = data.get("on", data.get(True, {}))
        schedule = on_block.get("schedule") if isinstance(on_block, dict) else None
        if not isinstance(schedule, list):
            continue
        crons = [entry["cron"] for entry in schedule if isinstance(entry, dict) and entry.get("cron")]
        if crons:
            peers[filename] = crons
    if require_non_empty and not peers:
        raise RuntimeError(_EMPTY_PEER_SET_MESSAGE)
    return peers


def derive_scheduled_peers(require_non_empty: bool = True) -> dict[str, list[str]]:
    """Walk `.github/workflows/*.yml|*.yaml` from the checkout and derive the live peer set."""
    workflows_dir = _REPO_ROOT / _WORKFLOWS_DIR
    docs: _Info = {}
    if workflows_dir.is_dir():
        for path in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
            docs[path.name] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return peers_from_workflow_docs(docs, require_non_empty=require_non_empty)


# --- Threshold oracle: a bounded 5-field cron shape matcher, no croniter dependency. ---


def cron_period_seconds(expr: str) -> int:
    """Nominal period (seconds) of a 5-field cron covering the four live shapes -- hourly,
    every-N-hours, weekly-by-dow, monthly-by-dom. Raises on anything else, including a literal dom
    AND dow together (cron's union semantics -- never guessed at)."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"scripts.convergence_health.sensor_liveness: unclassifiable cron shape {expr!r}")
    minute, hour, dom, month, dow = fields

    def _lit(field: str) -> bool:
        return field.isdigit()

    def _star(field: str) -> bool:
        return field == "*"

    def _step(field: str) -> Optional[int]:
        return int(field[2:]) if field.startswith("*/") and field[2:].isdigit() else None

    hour_step = _step(hour)
    if _lit(minute) and hour_step is not None and _star(dom) and _star(month) and _star(dow):
        return hour_step * 3600
    if _lit(minute) and _star(hour) and _star(dom) and _star(month) and _star(dow):
        return 3600
    minute_step = _step(minute)
    if minute_step is not None and _star(hour) and _star(dom) and _star(month) and _star(dow):
        return minute_step * 60
    if _lit(minute) and _lit(hour) and _star(dom) and _star(month) and _lit(dow):
        return 7 * 86400
    if _lit(minute) and _lit(hour) and _lit(dom) and _star(month) and _star(dow):
        return 31 * 86400
    raise ValueError(f"scripts.convergence_health.sensor_liveness: unclassifiable cron shape {expr!r}")


def staleness_threshold_seconds(expr: str) -> int:
    """clamp(2 x nominal period, 6h, 45d) -- see module docstring for the bounds' rationale."""
    period = cron_period_seconds(expr)
    return min(max(_THRESHOLD_MULTIPLIER * period, _MIN_THRESHOLD_SECONDS), _MAX_THRESHOLD_SECONDS)


def _peer_threshold_seconds(crons: list[str]) -> int:
    """A peer with >1 schedule entry is judged against its tightest (soonest-alarming) threshold."""
    return min(staleness_threshold_seconds(c) for c in crons)


def fleet_threshold_seconds(peers: dict[str, list[str]]) -> int:
    """The minimum per-peer threshold over the DERIVED (not stale) set -- a pure function of the
    workflow tree, constant within a fleet episode by construction."""
    return min(_peer_threshold_seconds(crons) for crons in peers.values())


def _bucket_for(age_seconds: float, threshold_seconds: int) -> int:
    """0 while fresh; else floor(log2(age/threshold)) + 1 -- the log2 re-alarm schedule."""
    if age_seconds < threshold_seconds:
        return 0
    return math.floor(math.log2(age_seconds / threshold_seconds)) + 1


# --- Live GitHub queries: per-peer run + one fleet-wide workflow-state listing. ---


def _default_git_runner(cmd: list[str]) -> str:
    import subprocess  # noqa: PLC0415

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip()


def _query_last_run(loop: str, caller: _GhCaller, api_base: str) -> Optional[_Info]:
    """`?event=schedule&per_page=1` -- filtered so workflow_dispatch cannot masquerade as cron
    liveness. Raises on a dead query (Decision 55)."""
    data = caller(f"{api_base}/actions/workflows/{loop}/runs?event=schedule&per_page=1")
    if not data:
        raise RuntimeError(_DEAD_QUERY_MESSAGE.format(loop=loop))
    runs = data.get("workflow_runs") or []
    return runs[0] if runs else None


def _query_workflow_states(caller: _GhCaller, api_base: str) -> dict[str, str]:
    """ONE bounded workflows listing per tick, indexed by filename (Decision 100). Degrades to {}
    on a dead query -- `state` only ever refines remediation text and must never suppress the
    age-derived alarm."""
    data = caller(f"{api_base}/actions/workflows?per_page=100")
    if not data:
        return {}
    states: dict[str, str] = {}
    for wf in data.get("workflows") or []:
        name = str(wf.get("path") or "").rsplit("/", 1)[-1]
        if name:
            states[name] = str(wf.get("state") or "")
    return states


def _first_commit(loop: str, runner: _GitRunner) -> tuple[str, int]:
    """The workflow file's own first-commit (sha, unix ts) -- the `intro:{sha}` fallback anchor
    when GitHub reports no `event=schedule` run at all. `_assert_full_history` guards a shallow
    clone first (mirrors code_drift.py)."""
    _assert_full_history(runner)
    rel_path = f"{_WORKFLOWS_DIR}/{loop}"
    output = runner(["git", "log", "--format=%H %ct", "--follow", "--", rel_path]).strip()
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(
            f"scripts.convergence_health.sensor_liveness: no commit history for {rel_path} -- cannot "
            "derive an intro-anchor age (Decision 55)."
        )
    sha, ts = lines[-1].split()
    return sha, int(ts)


def _as_utc(value: Any) -> datetime:
    """Normalise a warehouse timestamp (real rows carry `datetime`; fixtures may carry a string)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return _parse_utc(str(value or ""))


def _assess_peer(loop: str, crons: list[str], caller: _GhCaller, runner: _GitRunner, now: datetime, api_base: str) -> _Info:
    """One peer's threshold, anchor, age and bucket -- shared by detect_stale_loops and
    --liveness-probe so the two never compute staleness differently."""
    threshold = _peer_threshold_seconds(crons)
    run = _query_last_run(loop, caller, api_base)
    if run is not None:
        anchor_ts = _parse_utc(str(run.get("created_at") or ""))
        anchor = f"run:{run.get('id')}"
    else:
        sha, first_ts = _first_commit(loop, runner)
        anchor_ts = datetime.fromtimestamp(first_ts, tz=timezone.utc)
        anchor = f"intro:{sha}"
    age = (now - anchor_ts).total_seconds()
    return {
        "loop": loop,
        "anchor": anchor,
        "anchor_ts": anchor_ts,
        "bucket": _bucket_for(age, threshold),
        "age_seconds": age,
        "threshold_seconds": threshold,
    }


# --- Episode title/context: markers START-ANCHORED so recs_by_title_prefix's LIKE match works. ---


def _episode_title(loop: str, anchor: str, bucket: int) -> str:
    return f"Loop: {loop}. Episode: {anchor}. Bucket: {bucket}. Scheduled loop has not run within its derived threshold"


def _parse_episode_title(title: str) -> Optional[tuple[str, str, int]]:
    """(loop, anchor, bucket) parsed back out of a title this module wrote, or None."""
    if not title.startswith("Loop: ") or ". Episode: " not in title or ". Bucket: " not in title:
        return None
    try:
        loop_part, rest = title.split(". Episode: ", 1)
        anchor_part, rest = rest.split(". Bucket: ", 1)
        return loop_part[len("Loop: ") :], anchor_part, int(rest.split(".", 1)[0])
    except (ValueError, IndexError):
        return None


def _episode_context(info: _Info) -> str:
    remediation = _REMEDIATION_BY_STATE.get(str(info.get("state") or ""), _REMEDIATION_GENERIC)
    peers_note = f" Stale peers: {', '.join(info['stale_peers'])}." if info.get("stale_peers") else ""
    return (
        f"Loop: {info['loop']}. Episode: {info['anchor']}. Bucket: {info['bucket']}. No `?event=schedule` "
        f"run within the derived threshold ({info['threshold_seconds'] / 3600:.1f}h); last signal age "
        f"{info['age_seconds'] / 3600:.1f}h.{peers_note} {remediation} Never auto-closed -- restored "
        "cadence does not resolve this rec; a human closes it once satisfied (source loop_liveness_stale, LSA-02)."
    )


def _probe_acceptance(loop: str) -> str:
    """A dedicated function (never an inline f-string in a dict literal, which
    validate_acceptance_literals' static scanner would try -- and fail -- to bash-syntax-check
    with its interpolated segment blanked to a placeholder) so this dynamic command is skipped by
    that scanner exactly as escalate.py's and code_drift.py's own dynamic acceptance strings are."""
    target = "" if loop == _FLEET_LOOP_KEY else f" {loop}"
    return f"bin/venv-python -m scripts.convergence_health --liveness-probe{target}"


def _build_rec_fields(info: _Info) -> _Info:
    return {
        "title": _episode_title(info["loop"], info["anchor"], info["bucket"]),
        "file": ".github/workflows/convergence-health.yml",
        "status": "open",
        "source": "loop_liveness_stale",
        "priority": "High",
        "effort": "S",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _episode_context(info),
        "acceptance": _probe_acceptance(info["loop"]),
    }


# --- Open/resolved matchers: open keys on (loop) alone; resolved sweeps on (loop) alone, then
# discriminates client-side into the same-anchor and cross-anchor post-closure dwell legs. ---


def _is_open_loop_row(rec: _Info, loop: str) -> bool:
    """The live path (scripts.rec_episode.find_recs) already scopes on source="loop_liveness_stale"
    and status="open" via a structural current_state read (rec-3291 / rec-3563 class fix), so both
    keys are guaranteed present and correct on a live row. An injected `open_recs` test fixture may
    still omit either key for brevity -- absent is treated as already-satisfied, an explicit value
    is still honoured."""
    status = rec.get("status")
    if status is not None and status != "open":
        return False
    source = rec.get("source")
    if source is not None and source != "loop_liveness_stale":
        return False
    title = rec.get("title")
    return title is None or str(title).startswith(f"Loop: {loop}. ")


def _find_open_loop_rec(open_recs: _Rows, loop: str) -> Optional[_Info]:
    for rec in open_recs:
        if _is_open_loop_row(rec, loop):
            return rec
    return None


def _filter_resolved_rows(rows: _Rows, loop: str) -> _Rows:
    """Exact client-side re-filter shared by the live sweep and an injected `resolved_recs` list:
    LIKE's `_` wildcard would otherwise let `Loop: __fleet__.%` match a row titled
    `Loop: XXfleetYY. ...`, so membership is re-checked with plain string equality."""
    return [
        row
        for row in rows
        if str(row.get("title") or "").startswith(f"Loop: {loop}. ")
        and row.get("source") == "loop_liveness_stale"
        and row.get("status") in RESOLVED_REC_STATUSES
    ]


def _fetch_resolved_loop_recs(loop: str, profile: Optional[str] = None) -> _Rows:
    """One `recs_by_title_prefix` sweep -- `f"Loop: {loop}.%"`, trailing `%` mandatory, the verb
    binds the WHOLE pattern -- then `_filter_resolved_rows`."""
    from src.common.ducklake_reader_client import DuckLakeReader, make_reader  # noqa: PLC0415

    reader = cast(DuckLakeReader, make_reader(profile=profile))
    rows = reader.named("recs_by_title_prefix", title_prefix=f"Loop: {loop}.%") or []
    return _filter_resolved_rows(rows, loop)


def _resolved_rows_for_loop(loop: str, resolved_recs: Optional[_Rows], profile: Optional[str]) -> _Rows:
    """`resolved_recs` (for testing, mirroring budget_ingest.ingest_budget_breaches) is a single
    shared candidate pool re-filtered per loop; when None, sweeps live per loop."""
    if resolved_recs is not None:
        return _filter_resolved_rows(resolved_recs, loop)
    return _fetch_resolved_loop_recs(loop, profile=profile)


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


def _fetch_rec_by_id(rec_id: Any, profile: Optional[str] = None) -> _Info:
    from src.common.ducklake_reader_client import DuckLakeReader, make_reader  # noqa: PLC0415

    reader = cast(DuckLakeReader, make_reader(profile=profile))
    rows = reader.named("rec_by_id", id=rec_id) or []
    return rows[0] if rows else {}


def _charge(budget: dict[str, int], key: str, loop: str, label: str) -> None:
    """Increment a structural CALL-COUNT cap (`len(peers) + 1`) and raise past it -- unreachable
    under normal operation, so a raise here means a bug, never accumulated rec history."""
    budget[key] += 1
    if budget[key] > budget[f"{key}_max"]:
        raise RuntimeError(
            f"scripts.convergence_health.sensor_liveness: {label} ({budget[f'{key}_max']}) exceeded "
            f"while resolving {loop!r} -- structural invariant violation, never accumulated history."
        )


# --- Portal file/update + the file|update|unchanged|drop decision (mirrors budget_ingest). ---


def _decide_action(existing: Optional[_Info], resolved: Optional[_Info], fields: _Info) -> tuple[str, Optional[Any]]:
    if existing is not None:
        same = existing.get("title") == fields["title"] and existing.get("context") == fields["context"]
        return ("unchanged" if same else "update"), existing["id"]
    if resolved is not None:
        return "drop", resolved["id"]
    return "file", None


def _portal_file(fields: _Info, portal_caller: Optional[_PortalCaller], profile: Optional[str]) -> Any:
    if portal_caller is not None:
        return portal_caller("file", fields)
    from scripts.ops_data_portal import file_rec  # noqa: PLC0415

    return file_rec(fields, profile=profile)


def _portal_update(rec_id: str, updates: _Info, portal_caller: Optional[_PortalCaller], profile: Optional[str]) -> None:
    if portal_caller is not None:
        portal_caller("update", {"id": rec_id, **updates})
        return
    from scripts.ops_data_portal import update_rec  # noqa: PLC0415

    update_rec(rec_id, updates, profile=profile)


def _reconcile_episode(info: _Info, open_recs: _Rows, resolved_recs: Optional[_Rows], ctx: _Info, result: _Info) -> None:
    """`ctx` bundles this tick's call-invariant state (budget/now/portal_caller/profile/dry_run) --
    one dict instead of five trailing params, mutated (via `budget`) across every episode a tick reconciles."""
    budget = ctx["budget"]
    now, portal_caller, profile, dry_run = ctx["now"], ctx["portal_caller"], ctx["profile"], ctx["dry_run"]
    loop = info["loop"]
    fields = _build_rec_fields(info)
    existing = _find_open_loop_rec(open_recs, loop)
    resolved: Optional[_Info] = None
    if existing is None:
        _charge(budget, "sweeps", loop, "MAX_TITLE_SWEEPS")
        resolved_rows = _resolved_rows_for_loop(loop, resolved_recs, profile)
        same_anchor = _same_anchor_best_row(resolved_rows, info["anchor"])
        if same_anchor is not None:
            max_bucket = _parse_episode_title(str(same_anchor["title"]))[2]  # type: ignore[index]
            if info["bucket"] <= max_bucket + 1:
                resolved = same_anchor
        if resolved is None:
            cross = _cross_anchor_newest(resolved_rows, info["anchor"])
            if cross is not None:
                # A live sweep row never carries last_updated_timestamp (recs_by_title_prefix
                # projects id/title/status/source only) so production always pays this fetch; a
                # pre-assembled test row that already carries it skips the extra call.
                if "last_updated_timestamp" in cross:
                    full = cross
                else:
                    _charge(budget, "ids", loop, "MAX_REC_BY_ID")
                    full = _fetch_rec_by_id(cross["id"], profile=profile)
                closed_at = _as_utc(full.get("last_updated_timestamp"))
                if (now - closed_at).total_seconds() < info["threshold_seconds"]:
                    resolved = full

    decision, rec_id = _decide_action(existing, resolved, fields)
    if dry_run:
        action = _DRY_RUN_LABELS[decision]
        print(f"[convergence_health] sensor_liveness DRY-RUN {action}: {json.dumps(fields, sort_keys=True)}")
    elif decision == "file":
        rec_id = _portal_file(fields, portal_caller, profile)
        action = "file"
    elif decision == "update":
        _portal_update(str(rec_id), {"title": fields["title"], "context": fields["context"]}, portal_caller, profile)
        action = "update"
    else:
        action = decision
    result[{"file": "filed", "update": "updated", "unchanged": "unchanged", "drop": "dropped"}[decision]].append(
        {"loop": loop, "rec_id": rec_id, "action": action}
    )


# --- Top-level detection + the --liveness-probe acceptance oracle. ---


def detect_stale_loops(
    gh_caller: Optional[_GhCaller] = None,
    git_runner: Optional[_GitRunner] = None,
    portal_caller: Optional[_PortalCaller] = None,
    open_recs: Optional[_Rows] = None,
    resolved_recs: Optional[_Rows] = None,
    peers: Optional[dict[str, list[str]]] = None,
    now: Optional[datetime] = None,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    profile: Optional[str] = None,
    dry_run: bool = False,
) -> _Info:
    """File/update exactly one deduped rec per stale loop (or one fleet rec on a correlated
    outage). Lazy and bounded (Decision 88): a healthy tick issues zero warehouse reads. `peers`
    is None in production -- `derive_scheduled_peers()` runs with no override, so the fail-loud
    empty-set guard is inherited, never opt-in here. Every other dependency is injected too,
    mirroring `budget_ingest.ingest_budget_breaches`, so the whole module is network-free to test."""
    if now is None:
        now = datetime.now(timezone.utc)
    if peers is None:
        peers = derive_scheduled_peers()

    token = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    caller = gh_caller or _make_github_caller(token)
    runner = git_runner or _default_git_runner
    api_base = f"https://api.github.com/repos/{owner}/{repo}"
    states = _query_workflow_states(caller, api_base)

    infos: dict[str, _Info] = {}
    for loop, crons in sorted(peers.items()):
        info = _assess_peer(loop, crons, caller, runner, now, api_base)
        info["state"] = states.get(loop)
        infos[loop] = info

    stale = {loop: info for loop, info in infos.items() if info["bucket"] > 0}
    result: _Info = {
        "peers": len(peers),
        "stale": sorted(stale),
        "filed": [],
        "updated": [],
        "unchanged": [],
        "dropped": [],
        "fleet_collapse": False,
    }
    if not stale:
        return result

    if open_recs is None:
        open_recs = find_recs("loop_liveness_stale", profile=profile)
    budget = {"sweeps": 0, "sweeps_max": len(peers) + 1, "ids": 0, "ids_max": len(peers) + 1}
    ctx: _Info = {"budget": budget, "now": now, "portal_caller": portal_caller, "profile": profile, "dry_run": dry_run}

    if len(stale) >= FLEET_COLLAPSE_MIN_STALE:
        since_ts = max(info["anchor_ts"] for info in stale.values())
        threshold = fleet_threshold_seconds(peers)
        age = (now - since_ts).total_seconds()
        fleet_info = {
            "loop": _FLEET_LOOP_KEY,
            "anchor": f"since:{since_ts.isoformat().replace('+00:00', 'Z')}",
            "bucket": _bucket_for(age, threshold),
            "age_seconds": age,
            "threshold_seconds": threshold,
            "state": None,
            "stale_peers": sorted(stale),
        }
        _reconcile_episode(fleet_info, open_recs, resolved_recs, ctx, result)
        result["fleet_collapse"] = True
        return result

    for loop in sorted(stale):
        _reconcile_episode(stale[loop], open_recs, resolved_recs, ctx, result)

    return result


def stale_peers_for_probe(
    workflow: Optional[str] = None,
    gh_caller: Optional[_GhCaller] = None,
    git_runner: Optional[_GitRunner] = None,
    peers: Optional[dict[str, list[str]]] = None,
    now: Optional[datetime] = None,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
) -> list[str]:
    """Names of derived peers (or just `workflow`, when named) currently past their derived
    threshold. Backs `--liveness-probe`'s acceptance oracle (`__main__.main_liveness_probe`
    catches errors and maps this to an exit code) -- raises on an unknown `workflow` or a dead
    GitHub query rather than reporting a reassuring empty list."""
    resolved_peers = peers if peers is not None else derive_scheduled_peers()
    if workflow is not None:
        if workflow not in resolved_peers:
            raise ValueError(f"{workflow!r} is not a derived scheduled peer")
        targets = {workflow: resolved_peers[workflow]}
    else:
        targets = resolved_peers

    if now is None:
        now = datetime.now(timezone.utc)
    token = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    caller = gh_caller or _make_github_caller(token)
    runner = git_runner or _default_git_runner
    api_base = f"https://api.github.com/repos/{owner}/{repo}"
    return [
        loop
        for loop, crons in sorted(targets.items())
        if _assess_peer(loop, crons, caller, runner, now, api_base)["bucket"] > 0
    ]
