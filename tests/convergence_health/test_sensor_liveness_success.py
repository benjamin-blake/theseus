"""Unit tests for scripts.convergence_health.sensor_liveness_success (PLAN-monitor-liveness-sweep).

Drives the REAL classifier (assess_success_leg) against a stubbed HTTP caller -- the same
injection seam detect_stale_loops uses -- never a stubbed classifier itself."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest

from scripts.convergence_health import sensor_liveness as sl
from scripts.convergence_health import sensor_liveness_success as sls

NOW = datetime(2026, 9, 21, 15, 24, 46, tzinfo=timezone.utc)
LOOP = "ghas-probe.yml"
CRON = "0 7 * * 1"  # weekly -> threshold 1209600s (14d), the live ghas-probe.yml cadence
THRESHOLD = sl.staleness_threshold_seconds(CRON)
CRONS = [CRON]
_DEAD = object()


def _run(run_id: Any, created_at: datetime, conclusion: str = "success") -> dict[str, Any]:
    return {"id": run_id, "created_at": created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "conclusion": conclusion}


def _caller(plain_run: Any = _DEAD, success_run: Any = _DEAD) -> Callable[[str], Any]:
    """A query-aware stub: routes on whether `status=success` is in the URL, mirroring the real
    GitHub query shapes `_query_last_run` builds for each leg. `_DEAD` (the sentinel default,
    distinct from both `None` and `[]`) means "not configured for this test" -- callers must pick
    a run dict (one run), `[]` (zero runs, not dead), or `None` (a dead/no-payload query) for
    whichever query the test exercises."""

    def caller(url: str) -> Any:
        is_success_query = "status=success" in url
        value = success_run if is_success_query else plain_run
        if value is _DEAD:
            raise AssertionError(f"unconfigured query reached the stub: {url}")
        if value is None:
            return None
        return {"workflow_runs": [value] if value else []}

    return caller


def _git_runner(sha: str = "cafef00d", ts: int = 0, shallow: bool = False) -> Callable[[list[str]], str]:
    def runner(cmd: list[str]) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            return "true" if shallow else "false"
        if cmd[:2] == ["git", "log"]:
            return f"{sha} {ts}\n"
        return ""

    return runner


class TestSuccessLegClassification:
    def test_runs_fire_but_every_one_is_red_classifies_success_leg_stale(self) -> None:
        # The case this plan exists for: cadence sees a recent (failing) run, but the success
        # query -- filtered server-side to status=success -- returns zero rows, so the success leg
        # falls back to the intro anchor exactly as a peer with zero runs at all would.
        old_ts = int((NOW - timedelta(seconds=THRESHOLD * 3)).timestamp())
        caller = _caller(plain_run=_run(1, NOW - timedelta(hours=1), conclusion="failure"), success_run=[])
        git = _git_runner(sha="cafebabe", ts=old_ts)
        info = sls.assess_success_leg(LOOP, CRONS, caller, git, NOW, "https://api.github.com/repos/x/y")
        assert info["bucket"] > 0
        assert info["anchor"] == "intro:cafebabe"

    def test_a_peer_succeeding_inside_its_threshold_is_not_stale(self) -> None:
        recent_success = _run(42, NOW - timedelta(hours=1))
        caller = _caller(plain_run=recent_success, success_run=recent_success)
        info = sls.assess_success_leg(LOOP, CRONS, caller, _git_runner(), NOW, "https://api.github.com/repos/x/y")
        assert info["bucket"] == 0
        assert info["anchor"] == "run:42"

    def test_dead_success_query_raises(self) -> None:
        # The success leg's own query returns no payload (Decision 55): raises rather than
        # reporting a reassuring empty/fresh population.
        def dead_caller(url: str) -> Any:
            return None if "status=success" in url else {"workflow_runs": [_run(1, NOW)]}

        with pytest.raises(RuntimeError, match="no payload"):
            sls.assess_success_leg(LOOP, CRONS, dead_caller, _git_runner(), NOW, "https://api.github.com/repos/x/y")

    def test_query_is_filtered_to_scheduled_successful_runs(self) -> None:
        captured: list[str] = []

        def caller(url: str) -> Any:
            captured.append(url)
            return {"workflow_runs": []}

        git = _git_runner(ts=int((NOW - timedelta(seconds=THRESHOLD * 5)).timestamp()))
        sls.assess_success_leg(LOOP, CRONS, caller, git, NOW, "https://api.github.com/repos/x/y")
        assert len(captured) == 1
        assert "event=schedule" in captured[0]
        assert "status=success" in captured[0]

    def test_pinned_ghas_probe_observation(self) -> None:
        # PINNED red-before observation captured live 2026-09-21T15:24:46Z (this plan's context):
        # ghas-probe.yml, cron 0 7 * * 1, threshold 1209600s. Last SUCCESS run 34125799719 at
        # 2026-09-07T13:09:30Z (age 1217716s -> STALE). Last RUN 35605883403 at
        # 2026-09-21T13:28:52Z, conclusion failure (age 6954s -> cadence FRESH). Pins the raw
        # payload subset (id, created_at, conclusion), not the derived ages, so a wrong query or a
        # wrong anchor field can't hide behind pre-computed numbers.
        last_success = {"id": 34125799719, "created_at": "2026-09-07T13:09:30Z", "conclusion": "success"}
        last_run = {"id": 35605883403, "created_at": "2026-09-21T13:28:52Z", "conclusion": "failure"}
        assert THRESHOLD == 1209600

        caller = _caller(plain_run=last_run, success_run=last_success)
        cadence_info = sl._assess_peer(LOOP, CRONS, caller, _git_runner(), NOW, "https://api.github.com/repos/x/y")
        success_info = sls.assess_success_leg(LOOP, CRONS, caller, _git_runner(), NOW, "https://api.github.com/repos/x/y")

        assert cadence_info["bucket"] == 0, "cadence leg must stay fresh on this pinned observation"
        assert success_info["bucket"] > 0, "success leg must classify stale on this pinned observation"


class TestSharedArithmeticParameterisation:
    def test_success_leg_reuses_assess_peer_rather_than_reimplementing_it(self) -> None:
        assert sls.assess_success_leg is not sl._assess_peer
        import inspect

        source = inspect.getsource(sls.assess_success_leg)
        assert "_assess_peer(" in source
        assert "query_suffix" in source


class TestStalePeersForProbeSuccessLeg:
    def test_success_leg_reported_independently_of_cadence(self) -> None:
        # Cadence run is fresh; the success-filtered query sees none at all -- falls back to the
        # (old) intro anchor, so success alone reports this peer stale.
        old_ts = int((NOW - timedelta(seconds=THRESHOLD * 3)).timestamp())
        caller = _caller(plain_run=_run(1, NOW), success_run=[])
        git = _git_runner(sha="cafebabe", ts=old_ts)
        peers = {LOOP: CRONS}
        assert sl.stale_peers_for_probe(LOOP, "success", peers=peers, now=NOW, gh_caller=caller, git_runner=git) == [LOOP]
        assert sl.stale_peers_for_probe(LOOP, "cadence", peers=peers, now=NOW, gh_caller=caller) == []
