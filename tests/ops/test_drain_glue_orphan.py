"""Tests for scripts/ops/drain_glue_orphan.py (the executable Decision 178 clause 4 drain runbook).

No cross-test imports: the S3/reader/gh-shaped fakes live in tests/fixtures/drain_glue_orphan.py,
an importable package exempt from the guard by construction -- no network, no warehouse write.
TestPhasePreconditions proves fresh-world-proceeds / moved-world-fails-closed (naming the fluent),
the already-dispatched re-entrancy gate in BOTH directions, and the CROSS-PHASE rec lifecycle:
remove and close must be satisfiable by one rec state, or remove is unreachable in its own sequence.
TestWorkflowInvariants proves each of the FOUR routing invariants passes against real committed
source AND fails against a mutated copy, plus the no-hardcoded-fluent source scan.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

import scripts.ops.drain_glue_orphan as drain_module
from scripts.ci import reconcile_target
from scripts.ops.drain_glue_orphan import (
    _ROOT,
    PhaseOutcome,
    WorldMovedError,
    assert_workflow_invariants,
    correlate_dispatch,
    derive_remove_state,
    gate_converge_preconditions,
    gate_remove_preconditions,
    main,
    phase_close,
    phase_converge,
    phase_remove,
    wait_for_terminal,
)
from tests.fixtures.drain_glue_orphan import (
    RED_RECORD,
    FakeCompletedProcess,
    ProgressiveS3Client,
    make_s3,
    reader_returning,
    unreachable_file_rec,
)

_MODULE_PATH = _ROOT / "scripts" / "ops" / "drain_glue_orphan.py"


def _appears_after_dispatch(dispatched: list[str], run: dict[str, Any]) -> Callable[[], list[dict[str, Any]]]:
    """Reports `run` only after a dispatch fires -- the pre/post asymmetry correlate_dispatch
    needs to tell a run THIS phase started from one already on record."""
    return lambda: [run] if dispatched else []


def _remove(**overrides: Any) -> PhaseOutcome:
    """phase_remove with the fresh-world defaults; each test overrides only its branch's seam."""
    kwargs: dict[str, Any] = {
        "s3_client": make_s3(RED_RECORD, orphan_present=True),
        "rec_reader": reader_returning("closed"),
        "dispatcher": lambda: None,
        "run_lister": lambda: [],
        "run_viewer": lambda run_id: {"status": "completed"},
        "clock": lambda: "2026-09-01T00:00:00Z",
        "sleeper": lambda s: None,
    }
    kwargs.update(overrides)
    return phase_remove(**kwargs)


def _converge(dispatched: list[str], **overrides: Any) -> PhaseOutcome:
    """_remove's twin: the ONE progressive client is shared with the dispatcher, so the post-apply
    read turns green only after a dispatch actually fired."""
    kwargs: dict[str, Any] = {
        "s3_client": ProgressiveS3Client(tfstate_orphan_present=False, dispatched=dispatched),
        "dispatcher": dispatched.append,
        "run_lister": lambda: [],
        "run_viewer": lambda run_id: {"status": "in_progress"},
        "clock": lambda: "2026-09-01T00:00:00Z",
        "sleeper": lambda s: None,
    }
    kwargs.update(overrides)
    return phase_converge(**kwargs)


class TestPhasePreconditions:
    def test_fresh_world_derives_and_gates_cleanly(self) -> None:
        state = derive_remove_state(make_s3(RED_RECORD, orphan_present=True), reader_returning("closed"))
        gate_remove_preconditions(state)  # must not raise

    def test_moved_world_fails_closed(self) -> None:
        """Record turned green mid-run -- named explicitly, never a bare exit-status failure."""
        state = derive_remove_state(make_s3({"status": "green"}, orphan_present=True), reader_returning("closed"))
        with pytest.raises(WorldMovedError, match="not reconcilable"):
            gate_remove_preconditions(state)

    def test_moved_world_orphan_already_drained_fails_closed(self) -> None:
        state = derive_remove_state(make_s3(RED_RECORD, orphan_present=False), reader_returning("closed"))
        with pytest.raises(WorldMovedError, match="no longer in tfstate"):
            gate_remove_preconditions(state)

    def test_moved_world_bundled_rec_still_open_fails_closed(self) -> None:
        """An OPEN bundled rec means the enabling PR has not merged, so the restored grant is not in
        HCL yet and the destroy would AccessDeny exactly as run 33323201848 did."""
        state = derive_remove_state(make_s3(RED_RECORD, orphan_present=True), reader_returning("open"))
        with pytest.raises(WorldMovedError, match="still open"):
            gate_remove_preconditions(state)

    def test_one_rec_state_satisfies_both_remove_and_close(self) -> None:
        """Cross-phase lifecycle pin. remove once required the bundled recs OPEN while close required
        them CLOSED, and rec-autoclose.yml flips them at the merge the drain itself depends on -- so
        NO single world satisfied both and phase_remove was unreachable in its own sequence. Each
        phase's own tests feed it a hand-picked rec state, so only walking ONE state through both
        gates can see the contradiction."""
        reader = reader_returning("closed")
        gate_remove_preconditions(derive_remove_state(make_s3(RED_RECORD, orphan_present=True), reader))
        outcome = phase_close(
            s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader,
            file_rec=lambda fields, profile=None: "rec-9999",
            get_rec_write_guidance=lambda **kw: None,
        )
        assert outcome.status != "recs_still_open", outcome

    def test_pre_merge_open_rec_state_satisfies_neither_phase(self) -> None:
        reader = reader_returning("open")
        with pytest.raises(WorldMovedError, match="still open"):
            gate_remove_preconditions(derive_remove_state(make_s3(RED_RECORD, orphan_present=True), reader))
        outcome = phase_close(
            s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader,
            file_rec=unreachable_file_rec,
            get_rec_write_guidance=lambda **kw: None,
        )
        assert outcome.status == "recs_still_open"

    def test_converge_moved_world_record_not_red_fails_closed(self) -> None:
        with pytest.raises(WorldMovedError, match="not CONVERGENCE_RED"):
            gate_converge_preconditions({"status": "green"}, orphan_in_state=False)

    def test_converge_moved_world_orphan_still_present_fails_closed(self) -> None:
        with pytest.raises(WorldMovedError, match="still in tfstate"):
            gate_converge_preconditions(RED_RECORD, orphan_in_state=True)

    def test_remove_refuses_second_dispatch_while_run_in_flight(self) -> None:
        """ALREADY-DISPATCHED: a non-terminal run exists -- must NOT dispatch again, and must
        report that run's id, even though every other precondition still passes (record red,
        orphan in state) -- exactly why a blind re-run would double-spend the one human approval."""
        dispatched: list[str] = []
        in_flight_run = {"databaseId": 999, "status": "in_progress", "createdAt": "2026-09-01T00:00:00Z"}
        outcome = _remove(dispatcher=lambda: dispatched.append("fired"), run_lister=lambda: [in_flight_run])
        assert dispatched == [], "must not dispatch a second Reconcile run while one is in flight"
        assert outcome.status == "already_dispatched"
        assert outcome.fluents["run_id"] == 999

    def test_remove_dispatches_when_only_terminal_runs_exist(self) -> None:
        """Twin of the above: with only TERMINAL runs on record, the phase MUST dispatch -- a
        one-direction case on the re-entrancy gate is as vacuous as one on the invariants."""
        dispatched: list[str] = []
        stale_terminal_run = {"databaseId": 1, "status": "completed", "createdAt": "2020-01-01T00:00:00Z"}
        fresh_correlated_run = {
            "databaseId": 2,
            "status": "completed",
            "createdAt": "2026-09-01T00:00:01Z",
            "log": "aws_glue_catalog_database.ops: Destruction complete",
        }

        outcome = _remove(
            dispatcher=lambda: dispatched.append("fired"),
            run_lister=lambda: [stale_terminal_run, fresh_correlated_run] if dispatched else [stale_terminal_run],
            run_viewer=lambda run_id: fresh_correlated_run,
        )
        assert dispatched == ["fired"]
        assert outcome.status == "drained"


class TestPhaseOutcomeReport:
    def test_report_success_status_returns_zero(self, capsys: pytest.CaptureFixture) -> None:
        rc = PhaseOutcome("drained", "ok", {"run_id": "1"}).report()
        assert rc == 0
        assert "drained" in capsys.readouterr().out

    def test_report_world_moved_status_returns_one(self) -> None:
        assert PhaseOutcome("world_moved", "bad").report() == 1


class TestCorrelateDispatch:
    def test_multiple_candidates_fails_closed(self) -> None:
        runs = [{"createdAt": "2026-09-01T00:00:01Z"}, {"createdAt": "2026-09-01T00:00:02Z"}]
        with pytest.raises(WorldMovedError, match="more than one"):
            correlate_dispatch(lambda: runs, "2026-09-01T00:00:00Z", sleeper=lambda s: None)

    def test_zero_candidates_times_out_to_dispatched_but_not_correlated(self) -> None:
        slept: list[float] = []
        result = correlate_dispatch(lambda: [], "2026-09-01T00:00:00Z", sleeper=slept.append, attempts=3, interval_s=1.0)
        assert result.outcome == "dispatched_but_not_correlated"
        assert slept == [1.0, 1.0]  # never sleeps after the LAST attempt


class TestWaitForTerminal:
    def test_times_out_returns_none(self) -> None:
        slept: list[float] = []
        result = wait_for_terminal(
            lambda run_id: {"status": "in_progress"}, "1", sleeper=slept.append, attempts=2, interval_s=5.0
        )
        assert result is None
        assert slept == [5.0]


class TestPhaseRemoveBranches:
    def test_dispatched_but_not_correlated(self) -> None:
        assert _remove().status == "dispatched_but_not_correlated"

    def test_awaiting_approval(self) -> None:
        dispatched: list[str] = []
        run = {"databaseId": 5, "status": "in_progress", "createdAt": "2026-09-01T00:00:01Z"}
        outcome = _remove(
            dispatcher=lambda: dispatched.append("x"),
            run_lister=_appears_after_dispatch(dispatched, run),
            run_viewer=lambda run_id: {"status": "in_progress"},
        )
        assert outcome.status == "awaiting_approval"

    def test_terminal_without_destruction_line(self) -> None:
        dispatched: list[str] = []
        run = {"databaseId": 7, "status": "completed", "createdAt": "2026-09-01T00:00:01Z", "log": "some other output"}
        outcome = _remove(
            dispatcher=lambda: dispatched.append("x"),
            run_lister=_appears_after_dispatch(dispatched, run),
            run_viewer=lambda run_id: run,
        )
        assert outcome.status == "terminal_without_destruction"
        assert outcome.fluents["drained"] is False


class TestPhaseConverge:
    def _run(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "databaseId": 10,
            "status": "completed",
            "createdAt": "2026-09-01T00:00:01Z",
            "plan_log": "",
            "guard_routed": False,
            "review_approving": True,
        }
        base.update(overrides)
        return base

    def test_converged_when_all_four_facts_hold(self) -> None:
        dispatched: list[str] = []
        run = self._run()
        outcome = _converge(dispatched, run_lister=_appears_after_dispatch(dispatched, run), run_viewer=lambda run_id: run)
        assert outcome.status == "converged"
        assert dispatched == [RED_RECORD["commit_sha"]]

    def test_not_converged_when_review_is_not_approving(self) -> None:
        dispatched: list[str] = []
        run = self._run(review_approving=False)
        outcome = _converge(dispatched, run_lister=_appears_after_dispatch(dispatched, run), run_viewer=lambda run_id: run)
        assert outcome.status == "not_converged"
        assert outcome.fluents["review_approving"] is False

    def test_dispatched_but_not_correlated(self) -> None:
        assert _converge([], dispatcher=lambda sha: None).status == "dispatched_but_not_correlated"

    def test_awaiting_terminal(self) -> None:
        dispatched: list[str] = []
        run = {"databaseId": 11, "status": "in_progress", "createdAt": "2026-09-01T00:00:01Z"}
        outcome = _converge(dispatched, run_lister=_appears_after_dispatch(dispatched, run))
        assert outcome.status == "awaiting_terminal"


class TestPhaseClose:
    def test_recs_still_open_refuses_to_file(self) -> None:
        outcome = phase_close(
            s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader_returning("open"),
            file_rec=unreachable_file_rec,
            get_rec_write_guidance=lambda **kw: {},
        )
        assert outcome.status == "recs_still_open"

    def test_orphan_still_in_state_refuses_to_file(self) -> None:
        outcome = phase_close(
            s3_client=make_s3(None, orphan_present=True),
            rec_reader=reader_returning("closed"),
            file_rec=unreachable_file_rec,
            get_rec_write_guidance=lambda **kw: {},
        )
        assert outcome.status == "orphan_still_in_state"

    def test_files_removal_rec_once_both_preconditions_confirmed(self) -> None:
        filed: dict[str, Any] = {}
        calls: list[str] = []

        def _tracked_file_rec(fields: dict[str, Any], profile: str | None = None) -> str:
            calls.append("file_rec")
            filed.update(fields)
            return "rec-9999"

        outcome = phase_close(
            s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader_returning("closed"),
            file_rec=_tracked_file_rec,
            get_rec_write_guidance=lambda **kw: calls.append("guidance"),
        )
        assert outcome.status == "filed"
        assert outcome.fluents["removal_rec_id"] == "rec-9999"
        assert filed["priority"] == "High" and filed["effort"] == "XS" and filed["source"] == "manual"
        # Decision 66 Precision Context Injection: guidance reaches context BEFORE composition.
        assert calls == ["guidance", "file_rec"], calls


class TestLiveWiring:
    """Thin gh-CLI/boto3 wiring -- monkeypatches subprocess.run and sys.modules['boto3'] the same
    way tests/test_reconcile_target.py's main() tests do, so no live process or network fires."""

    def test_gh_json_parses_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drain_module.subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout='{"a": 1}'))
        assert drain_module._gh_json(["run", "list"]) == {"a": 1}

    def test_gh_json_empty_stdout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drain_module.subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout=""))
        assert drain_module._gh_json(["run", "list"]) is None

    def test_live_run_lister_wraps_gh_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_gh_json(args: list[str]) -> Any:
            captured["args"] = args
            return [{"databaseId": 1}]

        monkeypatch.setattr(drain_module, "_gh_json", _fake_gh_json)
        assert drain_module._live_run_lister_for("reconcile.yml")() == [{"databaseId": 1}]
        assert "reconcile.yml" in captured["args"]

    def test_live_run_lister_none_becomes_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drain_module, "_gh_json", lambda args: None)
        assert drain_module._live_run_lister_for("reconcile.yml")() == []

    def test_live_run_lister_scopes_to_the_workflow_it_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each phase correlates against the workflow it DISPATCHED. A shared reconcile-only
        lister made the converge phase poll Reconcile for an apply-sandbox run, so it could never
        correlate and its four-fact oracle was unreachable."""
        captured: dict[str, Any] = {}
        monkeypatch.setattr(drain_module, "_gh_json", lambda args: captured.setdefault("args", args) and [])
        drain_module._live_run_lister_for("terraform-apply-sandbox.yml")()
        assert "terraform-apply-sandbox.yml" in captured["args"]
        assert "reconcile.yml" not in captured["args"]

    def test_live_run_viewer_fetches_log_when_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drain_module, "_gh_json", lambda args: {"status": "completed"})
        monkeypatch.setattr(drain_module.subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout="LOG TEXT"))
        assert drain_module._live_run_viewer("123")["log"] == "LOG TEXT"

    def test_live_run_viewer_skips_log_when_not_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drain_module, "_gh_json", lambda args: {"status": "in_progress"})
        assert "log" not in drain_module._live_run_viewer("123")

    def test_live_dispatch_reconcile_invokes_gh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(drain_module.subprocess, "run", lambda args, **k: calls.append(args) or FakeCompletedProcess())
        drain_module._live_dispatch_reconcile()
        assert calls[0] == ["gh", "workflow", "run", "reconcile.yml"]

    def test_live_dispatch_apply_sandbox_passes_ack_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(drain_module.subprocess, "run", lambda args, **k: calls.append(args) or FakeCompletedProcess())
        drain_module._live_dispatch_apply_sandbox("some-ack-value")
        assert "acknowledge_red_commit=some-ack-value" in calls[0]

    def test_live_converge_run_viewer_fails_closed_when_the_review_step_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """H3 fail-closed: guard_routed is derived from the review step being SKIPPED, so a
        renamed or removed step would read as 'not skipped' -> guard passed. That is fail-open on
        an authoritative safety oracle, so a step this module cannot find is a moved world."""

        def _fake_gh_json(args: list[str]) -> Any:
            if "jobs" in args:
                return self._jobs_payload([{"name": "Some Renamed Step", "conclusion": "success"}])
            return {"status": "completed"}

        monkeypatch.setattr(drain_module, "_gh_json", _fake_gh_json)
        monkeypatch.setattr(drain_module.subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout="log"))
        with pytest.raises(WorldMovedError, match="carries no step named"):
            drain_module._live_converge_run_viewer("1")

    def test_live_clock_returns_a_z_suffixed_timestamp(self) -> None:
        assert drain_module._live_clock().endswith("Z")

    def test_live_converge_run_viewer_skips_job_lookup_when_not_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(drain_module, "_gh_json", lambda args: {"status": "in_progress"})
        row = drain_module._live_converge_run_viewer("1")
        assert row == {"status": "in_progress"}

    @staticmethod
    def _jobs_payload(steps: list[dict[str, Any]]) -> dict[str, Any]:
        return {"jobs": [{"name": "apply-sandbox", "databaseId": 55, "steps": steps}]}

    def test_live_converge_run_viewer_resolves_guard_and_review_facts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        steps = [
            {"name": "Terraform plan (workflow_dispatch -- fresh plan)", "conclusion": "success"},
            {"name": "Subagent plan review (digest-fed, JSON-classified)", "conclusion": "success"},
        ]
        monkeypatch.setattr(
            drain_module, "_gh_json", lambda args: self._jobs_payload(steps) if "jobs" in args else {"status": "completed"}
        )
        monkeypatch.setattr(drain_module.subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout="plan text"))
        row = drain_module._live_converge_run_viewer("1")
        assert row["guard_routed"] is False
        assert row["review_approving"] is True
        assert row["plan_log"] == "plan text"

    def test_live_converge_run_viewer_marks_guard_routed_when_review_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        steps = [{"name": "Subagent plan review (digest-fed, JSON-classified)", "conclusion": "skipped"}]
        monkeypatch.setattr(
            drain_module, "_gh_json", lambda args: self._jobs_payload(steps) if "jobs" in args else {"status": "completed"}
        )
        monkeypatch.setattr(drain_module.subprocess, "run", lambda *a, **k: FakeCompletedProcess(stdout="full run log"))
        row = drain_module._live_converge_run_viewer("1")
        assert row["guard_routed"] is True
        assert row["review_approving"] is False
        assert row["plan_log"] == ""


class TestMain:
    def _fake_boto3(self, s3_client: Any) -> Any:
        class _FakeSession:
            def __init__(self, profile_name: str | None = None) -> None:
                pass

            def client(self, name: str) -> Any:
                return s3_client

        class _FakeBoto3Module:
            Session = _FakeSession

        return _FakeBoto3Module()

    def test_main_close_phase_end_to_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "boto3", self._fake_boto3(make_s3(None, orphan_present=False)))
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("closed"))
        import scripts.ops_data_portal as portal_module

        monkeypatch.setattr(portal_module, "file_rec", lambda fields, profile=None: "rec-1234")
        assert main(["--phase", "close"]) == 0

    def test_main_reports_world_moved_as_exit_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setitem(sys.modules, "boto3", self._fake_boto3(make_s3({"status": "green"}, orphan_present=True)))
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("open"))
        assert main(["--phase", "remove"]) == 1
        assert "world_moved" in capsys.readouterr().err

    def test_main_pairs_each_phase_with_the_workflow_it_dispatches(self) -> None:
        """C2 regression pin: the converge phase dispatches terraform-apply-sandbox.yml, so it must
        correlate against that workflow -- not reconcile.yml, which only the remove phase
        dispatches. A shared lister made the converge oracle structurally unreachable."""
        import inspect

        source = inspect.getsource(drain_module.main)
        remove_block = source.split('args.phase == "remove"')[1].split("elif")[0]
        converge_block = source.split('args.phase == "converge"')[1].split("else:")[0]
        assert "_RECONCILE_DISPATCH_FILE" in remove_block and "_APPLY_SANDBOX_DISPATCH_FILE" not in remove_block
        assert "_APPLY_SANDBOX_DISPATCH_FILE" in converge_block and "_RECONCILE_DISPATCH_FILE" not in converge_block

    def test_main_converge_phase_dispatches_and_gates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "boto3", self._fake_boto3(make_s3({"status": "green"}, orphan_present=True)))
        monkeypatch.setattr(reconcile_target, "_default_reader", lambda profile: reader_returning("open"))
        assert main(["--phase", "converge"]) == 1  # record not red -- fails closed, still exercises the converge branch


def _load_yaml(rel: str) -> dict[str, Any]:
    return yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8"))


def _write_mutated_tree(tmp_path: Path, *, apply_sandbox: dict, reconcile_wf: dict, budget: dict) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / "terraform" / "bootstrap").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".github" / "workflows" / "terraform-apply-sandbox.yml").write_text(yaml.safe_dump(apply_sandbox))
    (tmp_path / ".github" / "workflows" / "reconcile.yml").write_text(yaml.safe_dump(reconcile_wf))
    (tmp_path / "terraform" / "bootstrap" / "authority_budget.json").write_text(json.dumps(budget))


def _real_docs() -> tuple[dict, dict, dict]:
    return (
        copy.deepcopy(_load_yaml(".github/workflows/terraform-apply-sandbox.yml")),
        copy.deepcopy(_load_yaml(".github/workflows/reconcile.yml")),
        json.loads((_ROOT / "terraform" / "bootstrap" / "authority_budget.json").read_text(encoding="utf-8")),
    )


def _source_minus_removal_rec_constants() -> str:
    """Structured exclusion (AST line ranges, never a text-substring cut) of the ONE sanctioned
    exemption: the filed rec's own content constants, which are data this module writes, not an
    operational fluent it reads or branches on."""
    source = _MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exempt_ranges = [
        (node.lineno, node.end_lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("_REMOVAL_REC_")
    ]
    lines = source.splitlines()
    kept = [line for i, line in enumerate(lines, start=1) if not any(start <= i <= end for start, end in exempt_ranges)]
    return "\n".join(kept)


class TestWorkflowInvariants:
    def test_passes_against_real_committed_source(self) -> None:
        assert_workflow_invariants(_ROOT)  # must not raise

    def test_invariant_a_fails_when_gated_apply_loses_push_condition(self, tmp_path: Path) -> None:
        apply_sandbox, reconcile_wf, budget = _real_docs()
        apply_sandbox["jobs"]["gated-apply"]["if"] = "always() && needs.apply-sandbox.outputs.routed == 'true'"
        _write_mutated_tree(tmp_path, apply_sandbox=apply_sandbox, reconcile_wf=reconcile_wf, budget=budget)
        with pytest.raises(WorldMovedError, match=r"\(a\)"):
            assert_workflow_invariants(tmp_path)

    def test_invariant_b_fails_when_gated_apply_reconcile_gains_push_condition(self, tmp_path: Path) -> None:
        apply_sandbox, reconcile_wf, budget = _real_docs()
        reconcile_wf["jobs"]["gated-apply-reconcile"]["if"] += " && github.event_name == 'push'"
        _write_mutated_tree(tmp_path, apply_sandbox=apply_sandbox, reconcile_wf=reconcile_wf, budget=budget)
        with pytest.raises(WorldMovedError, match=r"\(b\)"):
            assert_workflow_invariants(tmp_path)

    def test_invariant_c_fails_when_budget_exact_lists_aws_iam_role(self, tmp_path: Path) -> None:
        apply_sandbox, reconcile_wf, budget = _real_docs()
        budget["in_budget_resource_types"].append("aws_iam_role")
        _write_mutated_tree(tmp_path, apply_sandbox=apply_sandbox, reconcile_wf=reconcile_wf, budget=budget)
        with pytest.raises(WorldMovedError, match=r"\(c\)"):
            assert_workflow_invariants(tmp_path)

    def test_invariant_c_naive_substring_check_would_invert(self) -> None:
        """Documents the exact failure mode the plan calls out: a substring test for aws_iam_role
        against in_budget_resource_types matches the aws_iam_role_policy prefix and returns True --
        the OPPOSITE of the truth. Exact list membership (what assert_workflow_invariants uses)
        correctly returns False."""
        types = ["aws_iam_role_policy", "aws_iam_role_policy_attachment"]
        assert any("aws_iam_role" in t for t in types), "the naive (WRONG) substring check"
        assert "aws_iam_role" not in types, "exact membership -- the correct check"

    def test_invariant_d_fails_when_checkout_pins_a_ref(self, tmp_path: Path) -> None:
        apply_sandbox, reconcile_wf, budget = _real_docs()
        apply_sandbox["jobs"]["apply-sandbox"]["steps"][0]["with"] = {"ref": "some-other-ref"}
        _write_mutated_tree(tmp_path, apply_sandbox=apply_sandbox, reconcile_wf=reconcile_wf, budget=budget)
        with pytest.raises(WorldMovedError, match=r"\(d\).*ref"):
            assert_workflow_invariants(tmp_path)

    def test_invariant_d_fails_when_fresh_plan_step_loses_dispatch_gate(self, tmp_path: Path) -> None:
        apply_sandbox, reconcile_wf, budget = _real_docs()
        steps = apply_sandbox["jobs"]["apply-sandbox"]["steps"]
        plan_step = next(s for s in steps if s.get("id") == "plan")
        plan_step["if"] = "success()"
        _write_mutated_tree(tmp_path, apply_sandbox=apply_sandbox, reconcile_wf=reconcile_wf, budget=budget)
        with pytest.raises(WorldMovedError, match=r"\(d\).*dispatch"):
            assert_workflow_invariants(tmp_path)

    def test_invariant_d_regate_false_positive_would_have_matched_a_comment(self) -> None:
        """Documents the second failure mode the plan calls out: reconcile.yml's own line-31
        COMMENT about apply-sandbox contains the literal text 'github.event_name == 'push'' --
        a file-level grep for it false-positives on the job that genuinely lacks the condition.
        assert_workflow_invariants never file-greps; it reads jobs['gated-apply-reconcile']['if']
        specifically, via yaml.safe_load."""
        _, reconcile_wf, _ = _real_docs()
        raw_text = (_ROOT / ".github" / "workflows" / "reconcile.yml").read_text(encoding="utf-8")
        assert "github.event_name == 'push'" in raw_text, "the comment mentioning it must still exist"
        assert "github.event_name == 'push'" not in str(reconcile_wf["jobs"]["gated-apply-reconcile"]["if"])

    def test_module_source_carries_no_hardcoded_fluent(self) -> None:
        scannable = _source_minus_removal_rec_constants()
        hex_shas = re.findall(r"\b[0-9a-f]{7,40}\b", scannable)
        assert not hex_shas, f"module source contains hex-SHA-shaped literal(s) outside the removal-rec text: {hex_shas}"
        rec_ids = set(re.findall(r"rec-\d+", scannable))
        assert rec_ids <= {"rec-3348", "rec-3328"}, (
            f"unexpected rec id literal(s) in source: {rec_ids - {'rec-3348', 'rec-3328'}}"
        )
