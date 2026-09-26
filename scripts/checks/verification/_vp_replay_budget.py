"""Bounded subprocess runner and budget telemetry for validate_vp_replay's shared-aggregate
deadline model (docs/contracts/vp-red-before.yaml's ``replay_bound``). Private sibling of
validate_vp_replay.py (Decision 104 precedent: _vp_replay_classify.py) -- 18+ graduated registry
rows name validate_vp_replay.py as ``guard_target``, so a facade-package conversion (Decision 128's
default) would retire a live path out from under them.

``run_bounded`` executes a replayed VP step's command against a wall-clock deadline, in its own
process group (``start_new_session=True``): on ``TimeoutExpired`` -- or any ``BaseException``
raised while waiting, since ``start_new_session`` detaches the child from the caller's foreground
group and would otherwise orphan it -- the whole process group is SIGKILLed and reaped with a
BOUNDED wait, so a descendant that escaped via setsid while holding the pipe can never hang this
check with no deadline. POSIX-only by design (``os.killpg``, ``start_new_session``): every surface
that runs this check is Linux (CC-web, CI). Accepted residual: a SIGTERM/SIGKILL delivered to the
validate process itself (no Python exception raised) orphans a still-running step's process group
-- bounded at job end on CI runners, unbounded locally only for a genuinely hung step.

The remaining helpers are pure telemetry, never a source of truth: a replayed PASS line's duration
suffix, the one terminal per-dispatch summary line, the two deadline-kill failure-text builders
(green leg and red-before leg), and the advisory warn band (never appends to a check's ``failed``
list -- WARN only, docs/contracts/vp-red-before.yaml's ``replay_bound``). The aggregate is always
passed in by the caller, never read from this module, so the existing
``validate_vp_replay.MAX_AGGREGATE_SECONDS`` patch seam keeps binding.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# docs/contracts/vp-red-before.yaml's replay_bound -- TestContractPins derive-asserts these three
# fractions equal to the contract's own values.
PER_STEP_WARN_FRACTION = 0.5
CUMULATIVE_WARN_FRACTION = 0.8
AUTHORING_MAX_FRACTION = 0.25

# Bounded reap window after a SIGKILL -- never an unbounded communicate(), per the module
# docstring's accepted residual (a descendant that escaped the killed group via setsid, still
# holding the pipe open, must not be able to hang this check indefinitely).
_REAP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class BoundedResult:
    returncode: int | None
    output: str
    elapsed: float
    timed_out: bool


def _killpg_quiet(pgid: int) -> None:
    """SIGKILL a process group; a group that has already exited is not an error."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _kill_and_reap(popen: subprocess.Popen) -> tuple[str, str]:
    """SIGKILL ``popen``'s whole process group and reap it with a BOUNDED wait.

    A descendant that escaped the group via setsid before the kill (e.g. a double-forked
    daemonizer still holding the inherited stdout/stderr pipe open) would otherwise make an
    unbounded ``communicate()`` hang forever waiting for EOF -- the bounded reap trades a
    guaranteed return for a possibly-incomplete capture of that descendant's own output, which
    is a fine trade since the step is already being reported as a deadline kill.
    """
    _killpg_quiet(popen.pid)
    try:
        return popen.communicate(timeout=_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return "", ""


def run_bounded(command: str, cwd: Path, timeout: float) -> BoundedResult:
    """Run ``command`` (``shell=True``) under a wall-clock ``timeout``, in its own process group.

    On timeout, kills and bounded-reaps the whole group (see ``_kill_and_reap``). The same
    kill-and-reap runs on any ``BaseException`` raised while waiting (``KeyboardInterrupt``, a
    harness timeout) -- ``start_new_session`` removes the child from the caller's foreground
    process group, which would otherwise orphan it the moment this function's own frame unwinds.
    """
    start = time.monotonic()
    popen = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = popen.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        stdout, stderr = _kill_and_reap(popen)
        return BoundedResult(returncode=None, output=(stdout or "") + (stderr or ""), elapsed=elapsed, timed_out=True)
    except BaseException:
        _kill_and_reap(popen)
        raise
    elapsed = time.monotonic() - start
    return BoundedResult(returncode=popen.returncode, output=stdout + stderr, elapsed=elapsed, timed_out=False)


def duration_suffix(elapsed: float, aggregate: float) -> str:
    """The 'in X.Xs (N% of <aggregate>s)' suffix appended to every replayed PASS line."""
    pct = (elapsed / aggregate * 100) if aggregate else 0.0
    return f"in {elapsed:.1f}s ({pct:.0f}% of {aggregate:.0f}s)"


def summary_line(total_elapsed: float, aggregate: float, count: int, peak: tuple[str, int, float] | None) -> str:
    """The one terminal per-dispatch line: "vp-replay budget: X.Xs of <aggregate>s across N
    step(s); peak <plan>:<step> Y.Ys" -- appends the authoring-target note when the peak step
    alone exceeds AUTHORING_MAX_FRACTION of the aggregate, so that constant has a code consumer
    and the target surfaces where authors actually see replay cost."""
    line = f"vp-replay budget: {total_elapsed:.1f}s of {aggregate:.0f}s across {count} step(s)"
    if peak is not None:
        peak_plan, peak_step, peak_elapsed = peak
        line += f"; peak {peak_plan}:{peak_step} {peak_elapsed:.1f}s"
        if aggregate and peak_elapsed > AUTHORING_MAX_FRACTION * aggregate:
            line += f" (over the {AUTHORING_MAX_FRACTION * 100:.0f}% authoring target)"
    return line


def warn_band(peak_elapsed: float, total_elapsed: float, aggregate: float) -> str | None:
    """ADVISORY only -- never appended to a check's ``failed`` list. Fires when the single
    largest replayed step exceeds PER_STEP_WARN_FRACTION of the aggregate, or cumulative replay
    spend exceeds CUMULATIVE_WARN_FRACTION of it (the 0.8 band mirrors Decision 182 reversal
    condition (a)). Strictly-greater on both arms -- exactly at a threshold does not warn."""
    if not aggregate:
        return None
    if peak_elapsed > PER_STEP_WARN_FRACTION * aggregate:
        return (
            f"WARN: vp-replay drift -- a single step spent {peak_elapsed:.1f}s, over "
            f"{PER_STEP_WARN_FRACTION * 100:.0f}% of the {aggregate:.0f}s aggregate budget"
        )
    if total_elapsed > CUMULATIVE_WARN_FRACTION * aggregate:
        return (
            f"WARN: vp-replay drift -- {total_elapsed:.1f}s spent of the {aggregate:.0f}s aggregate budget, over "
            f"{CUMULATIVE_WARN_FRACTION * 100:.0f}% cumulative"
        )
    return None


def _prior_clause(prior_elapsed: float, prior_count: int, aggregate: float) -> str:
    if prior_count == 0:
        return f"step alone exceeds the {aggregate:.0f}s aggregate budget"
    return f"{prior_elapsed:.1f}s already spent across {prior_count} prior step(s)"


def format_deadline_kill_green(
    plan_rel: str, step_number: int, elapsed: float, prior_elapsed: float, prior_count: int, aggregate: float
) -> str:
    """Green-leg deadline-kill failure text: TIMEOUT, the aggregate deadline, the step's own run
    time, and the prior spend/step count (or "step alone exceeds..." when nothing ran before it)."""
    return (
        f"vp-replay {plan_rel}:{step_number}: actual=TIMEOUT (killed at the aggregate deadline) after {elapsed:.1f}s "
        f"-- {_prior_clause(prior_elapsed, prior_count, aggregate)}, {aggregate:.0f}s aggregate deadline"
    )


def format_deadline_kill_red_before(
    plan_rel: str, step_number: int, elapsed: float, prior_elapsed: float, prior_count: int, aggregate: float
) -> str:
    """Red-before-leg deadline-kill failure text: classifies unmeasurable (the contract's
    subprocess_timeout arm; the four frozen outcome classes are unchanged), names the aggregate
    deadline, and states plainly that unmeasurable is a hard failure, never counted as red."""
    return (
        f"vp-red-before {plan_rel}:{step_number}: actual=unmeasurable (killed at the aggregate deadline) after "
        f"{elapsed:.1f}s -- {_prior_clause(prior_elapsed, prior_count, aggregate)}, {aggregate:.0f}s aggregate "
        "deadline -- unmeasurable is a hard failure, never counted as red"
    )
