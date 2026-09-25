"""Success-age leg for the scheduled-loop liveness backstop (PLAN-monitor-liveness-sweep).

The cadence leg (`sensor_liveness.detect_stale_loops`) asks `?event=schedule&per_page=1` -- the
newest scheduled RUN, unfiltered by conclusion -- so it catches "stopped firing" but misses "fires
on cadence and every run fails" (the 2026-09-21 ghas-probe observation: last RUN 6954s old and
FRESH by cadence, last SUCCESS 1217716s old and STALE). This module is the sibling leg that asks
`?event=schedule&status=success&per_page=1` instead, judged against the SAME cron-derived
threshold, so the two never compute staleness differently.

A SIBLING module, not an inline addition to sensor_liveness.py (Decision 128 decompose-by-default):
that module sits at 496/500 SLOC before this leg, with no headroom to absorb a second query path.

PARAMETERISES sensor_liveness._assess_peer's query rather than reimplementing its arithmetic, so
two behaviours are inherited for free, both wanted: a dead query RAISES (Decision 55 fail-loud --
do not catch a transport failure into a fresh verdict) and a peer with zero successful runs ever
falls back to the `intro:{sha}` first-commit anchor -- the same fallback a peer with zero runs at
all uses on the cadence leg, and exactly the right answer here too: a schedule that has NEVER
succeeded is judged from its introduction, not treated as fresh for lack of a signal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from scripts.convergence_health.sensor_liveness import _assess_peer

_Info = dict[str, Any]
_GhCaller = Callable[[str], Any]
_GitRunner = Callable[[list[str]], str]

_SUCCESS_QUERY_SUFFIX = "&status=success"


def assess_success_leg(
    loop: str, crons: list[str], caller: _GhCaller, runner: _GitRunner, now: datetime, api_base: str
) -> _Info:
    """One peer's success-age threshold, anchor, age and bucket -- the same info shape
    `sensor_liveness._assess_peer` returns for the cadence leg, filtered to `status=success` runs."""
    return _assess_peer(loop, crons, caller, runner, now, api_base, query_suffix=_SUCCESS_QUERY_SUFFIX)
