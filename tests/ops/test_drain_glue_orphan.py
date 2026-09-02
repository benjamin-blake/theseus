"""Tests for scripts/ops/drain_glue_orphan (the executable Decision 178 clause 4 drain runbook).

Precondition-gate cases (TestPhasePreconditions) moved to
tests/ops/test_drain_glue_orphan_cli.py::TestPreconditionGates (VP10) -- the verification-registry
shard's node_id points there so its differential admission finds this class in the package's own
test surface, not a suite unrelated to what it guards. mcp__github__ payload/oracle cases
(TestLiveWiring's gh-CLI subject is gone) moved to test_drain_glue_orphan_github.py; CLI/step-
record-chain cases moved to test_drain_glue_orphan_cli.py. This file keeps the phase-level
(PhaseOutcome-consuming) and workflow-invariant cases.

TestWorkflowInvariants proves each of the FOUR routing invariants passes against real committed
source AND fails against a mutated copy, plus the no-hardcoded-fluent scan -- repointed from the
single pre-split file to every module in the package directory.
"""

from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.ops.drain_glue_orphan._github import (
    _APPLY_SANDBOX_DISPATCH_FILE,
    _RECONCILE_DISPATCH_FILE,
    _REPO_NAME,
    _REPO_OWNER,
)
from scripts.ops.drain_glue_orphan._phases import (
    PhaseOutcome,
    converge_correlate,
    converge_gate,
    converge_verify,
    phase_close,
    remove_correlate,
    remove_gate,
    remove_verify,
)
from scripts.ops.drain_glue_orphan._world import _ROOT, WorldMovedError, assert_workflow_invariants
from tests.fixtures.drain_glue_orphan import (
    APPLY_SANDBOX_JOB_ID,
    RED_RECORD,
    ProgressiveS3Client,
    apply_sandbox_jobs,
    job_log,
    make_s3,
    reader_returning,
    unreachable_file_rec,
)

_PACKAGE_DIR = _ROOT / "scripts" / "ops" / "drain_glue_orphan"


class TestPhaseClose:
    def test_recs_still_open_refuses_to_file(self) -> None:
        outcome = phase_close(
            profile_s3_client=make_s3(None, orphan_present=False),
            state_s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader_returning("open"),
            file_rec=unreachable_file_rec,
            get_rec_write_guidance=lambda **kw: {},
        )
        assert outcome.status == "recs_still_open"

    def test_orphan_still_in_state_refuses_to_file(self) -> None:
        outcome = phase_close(
            profile_s3_client=make_s3(None, orphan_present=True),
            state_s3_client=make_s3(None, orphan_present=True),
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
            profile_s3_client=make_s3(None, orphan_present=False),
            state_s3_client=make_s3(None, orphan_present=False),
            rec_reader=reader_returning("closed"),
            file_rec=_tracked_file_rec,
            get_rec_write_guidance=lambda **kw: calls.append("guidance"),
        )
        assert outcome.status == "filed"
        assert outcome.fluents["removal_rec_id"] == "rec-9999"
        assert filed["priority"] == "High" and filed["effort"] == "XS" and filed["source"] == "manual"
        # Decision 66 Precision Context Injection: guidance reaches context BEFORE composition.
        assert calls == ["guidance", "file_rec"], calls


class TestRemoveGate:
    def test_dispatches_when_world_fresh_and_no_in_flight_run(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=True)
        outcome = remove_gate(
            profile_s3_client=s3,
            state_s3_client=s3,
            rec_reader=reader_returning("closed"),
            runs_payload=[],
            clock=lambda: "2026-09-01T00:00:00Z",
        )
        assert outcome.status == "dispatch"
        assert outcome.fluents["dispatch_timestamp"] == "2026-09-01T00:00:00Z"
        assert outcome.next_action == {
            "tool": "mcp__github__actions_run_trigger",
            "method": "run_workflow",
            "owner": _REPO_OWNER,
            "repo": _REPO_NAME,
            "workflow_id": _RECONCILE_DISPATCH_FILE,
            "ref": "main",
        }

    def test_resumes_instead_of_dispatching_when_a_run_is_already_in_flight(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=True)
        in_flight = {"id": 999, "status": "in_progress", "conclusion": None, "created_at": "2026-09-01T00:00:00Z"}
        outcome = remove_gate(
            profile_s3_client=s3,
            state_s3_client=s3,
            rec_reader=reader_returning("closed"),
            runs_payload={"workflow_runs": [in_flight]},
            clock=lambda: "2026-09-01T00:00:00Z",
        )
        assert outcome.status == "resume"
        assert outcome.fluents["run_id"] == 999
        assert outcome.next_action is None

    def test_raises_on_stale_world(self) -> None:
        s3 = make_s3({"status": "green"}, orphan_present=True)
        with pytest.raises(WorldMovedError):
            remove_gate(
                profile_s3_client=s3,
                state_s3_client=s3,
                rec_reader=reader_returning("closed"),
                runs_payload=[],
                clock=lambda: "x",
            )


class TestRemoveCorrelate:
    def test_no_candidates_is_not_a_failure(self) -> None:
        outcome = remove_correlate(
            gate_record={"verdict": "dispatch", "fluents": {"dispatch_timestamp": "2026-09-01T00:00:00Z"}}, runs_payload=[]
        )
        assert outcome.status == "no_candidates"

    def test_correlated_selects_the_single_candidate(self) -> None:
        runs = [{"id": 7, "created_at": "2026-09-01T00:00:01Z"}]
        outcome = remove_correlate(
            gate_record={"verdict": "dispatch", "fluents": {"dispatch_timestamp": "2026-09-01T00:00:00Z"}}, runs_payload=runs
        )
        assert outcome.status == "correlated"
        assert outcome.fluents["run_id"] == 7


class TestRemoveVerify:
    def test_not_yet_terminal(self) -> None:
        outcome = remove_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 5}},
            run_payload={"id": 5, "status": "in_progress"},
            job_logs_payload={"logs_content": "", "original_length": 0},
        )
        assert outcome.status == "not_yet_terminal"

    def test_drained_on_destruction_line(self) -> None:
        outcome = remove_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 5}},
            run_payload={"id": 5, "status": "completed"},
            job_logs_payload=job_log("aws_glue_catalog_database.ops: Destruction complete"),
        )
        assert outcome.status == "drained"
        assert outcome.fluents["job_id"] == APPLY_SANDBOX_JOB_ID

    def test_envelope_without_a_job_id_is_refused(self) -> None:
        """The remove step has no jobs payload to correlate against (VP16 supplies only the run
        and the log), so the envelope's own job_id is the sole tie between the destruction verdict
        and the job that produced it -- a log that cannot say where it came from licenses nothing."""
        with pytest.raises(WorldMovedError, match="carries no job_id"):
            remove_verify(
                correlation_record={"verdict": "correlated", "fluents": {"run_id": 5}},
                run_payload={"id": 5, "status": "completed"},
                job_logs_payload={"logs_content": "aws_glue_catalog_database.ops: Destruction complete"},
            )

    def test_terminal_without_destruction_escalates_to_operator(self) -> None:
        outcome = remove_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 5}},
            run_payload={"id": 5, "status": "completed"},
            job_logs_payload=job_log("some other output"),
        )
        assert outcome.status == "terminal_without_destruction"
        assert outcome.next_action == {"tool": "escalate_to_operator"}


class TestConvergeGate:
    def test_dispatches_with_acknowledge_red_commit_input(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=False)
        outcome = converge_gate(
            profile_s3_client=s3, state_s3_client=s3, runs_payload=[], clock=lambda: "2026-09-01T00:00:00Z"
        )
        assert outcome.status == "dispatch"
        assert outcome.next_action == {
            "tool": "mcp__github__actions_run_trigger",
            "method": "run_workflow",
            "owner": _REPO_OWNER,
            "repo": _REPO_NAME,
            "workflow_id": _APPLY_SANDBOX_DISPATCH_FILE,
            "ref": "main",
            "inputs": {"acknowledge_red_commit": RED_RECORD["commit_sha"]},
        }
        assert outcome.fluents["acknowledge_red_commit"] == RED_RECORD["commit_sha"]

    def test_resumes_on_in_flight_run(self) -> None:
        s3 = make_s3(RED_RECORD, orphan_present=False)
        in_flight = {"id": 42, "status": "queued", "conclusion": None, "created_at": "2026-09-01T00:00:00Z"}
        outcome = converge_gate(profile_s3_client=s3, state_s3_client=s3, runs_payload=[in_flight], clock=lambda: "x")
        assert outcome.status == "resume"
        assert outcome.fluents["run_id"] == 42


class TestConvergeCorrelate:
    def test_correlated(self) -> None:
        runs = [{"id": 9, "created_at": "2026-09-01T00:00:01Z"}]
        outcome = converge_correlate(
            gate_record={"verdict": "dispatch", "fluents": {"dispatch_timestamp": "2026-09-01T00:00:00Z"}}, runs_payload=runs
        )
        assert outcome.status == "correlated" and outcome.fluents["run_id"] == 9


class TestConvergeVerify:
    _JOBS_ALL_PASS = apply_sandbox_jobs("success")
    _JOBS_GUARD_ROUTED = apply_sandbox_jobs("skipped")

    def test_converged_when_all_four_facts_hold(self) -> None:
        dispatched: list[str] = ["fired"]
        s3 = ProgressiveS3Client(tfstate_orphan_present=False, dispatched=dispatched)
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "completed"},
            jobs_payload=self._JOBS_ALL_PASS,
            job_logs_payload=job_log(),
            profile_s3_client=s3,
        )
        assert outcome.status == "converged"
        assert outcome.fluents == {
            "run_id": 10,
            "apply_sandbox_job_id": APPLY_SANDBOX_JOB_ID,
            "orphan_delete_absent": True,
            "plan_zero_destroys": True,
            "guard_passed": True,
            "review_approving": True,
            "record_green": True,
        }

    def test_not_converged_when_guard_routed(self) -> None:
        """guard_routed=True (the guard BLOCKED) must invert to guard_passed=False before it
        reaches the all() check -- fed in raw, a blocked guard's truthy `guard_routed` would
        satisfy all() and report a false "converged"."""
        dispatched: list[str] = ["fired"]
        s3 = ProgressiveS3Client(tfstate_orphan_present=False, dispatched=dispatched)
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "completed"},
            jobs_payload=self._JOBS_GUARD_ROUTED,
            job_logs_payload=job_log(),
            profile_s3_client=s3,
        )
        assert outcome.status == "not_converged"
        assert outcome.fluents["guard_passed"] is False

    def test_not_yet_terminal(self) -> None:
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "in_progress"},
            jobs_payload=self._JOBS_ALL_PASS,
            job_logs_payload=job_log(),
            profile_s3_client=make_s3(None, orphan_present=False),
        )
        assert outcome.status == "not_yet_terminal"

    def test_not_converged_when_review_step_did_not_approve(self) -> None:
        jobs = apply_sandbox_jobs("failure")
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "completed"},
            jobs_payload=jobs,
            job_logs_payload=job_log(),
            profile_s3_client=ProgressiveS3Client(tfstate_orphan_present=False, dispatched=["fired"]),
        )
        assert outcome.status == "not_converged"
        assert outcome.fluents["review_approving"] is False

    def test_not_converged_when_record_not_green(self) -> None:
        """dispatched=[] means ProgressiveS3Client's convergence-record read stays RED even
        though the run is terminal -- the acknowledge-and-retry apply never actually wrote green."""
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "completed"},
            jobs_payload=self._JOBS_ALL_PASS,
            job_logs_payload=job_log(),
            profile_s3_client=ProgressiveS3Client(tfstate_orphan_present=False, dispatched=[]),
        )
        assert outcome.status == "not_converged"
        assert outcome.fluents["record_green"] is False

    def test_not_converged_when_glue_delete_still_in_plan(self) -> None:
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "completed"},
            jobs_payload=self._JOBS_ALL_PASS,
            job_logs_payload=job_log(
                "  # aws_glue_catalog_database.ops will be destroyed", "Plan: 0 to add, 0 to change, 1 to destroy."
            ),
            profile_s3_client=ProgressiveS3Client(tfstate_orphan_present=False, dispatched=["fired"]),
        )
        assert outcome.status == "not_converged"
        assert outcome.fluents["plan_zero_destroys"] is False
        assert outcome.fluents["orphan_delete_absent"] is False

    def test_not_converged_when_a_NON_glue_address_is_still_being_destroyed(self) -> None:
        """VP19's widening: the orphan-address scan passes this plan (the orphan is gone) while a
        DIFFERENT retired address is still being destroyed -- which would route the guard and make
        this phase unreachable. Fact 1 must fail; the orphan diagnostic must stay True."""
        outcome = converge_verify(
            correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
            run_payload={"id": 10, "status": "completed"},
            jobs_payload=self._JOBS_ALL_PASS,
            job_logs_payload=job_log(
                "  # aws_athena_workgroup.production will be destroyed", "Plan: 0 to add, 0 to change, 1 to destroy."
            ),
            profile_s3_client=ProgressiveS3Client(tfstate_orphan_present=False, dispatched=["fired"]),
        )
        assert outcome.status == "not_converged"
        assert outcome.fluents["plan_zero_destroys"] is False
        assert outcome.fluents["orphan_delete_absent"] is True

    def test_log_from_another_job_is_refused_outright(self) -> None:
        """Not a not_converged -- a verdict read from a different job's log is evidence this
        module must refuse, so it raises rather than scoring facts."""
        with pytest.raises(WorldMovedError, match="another job's log"):
            converge_verify(
                correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
                run_payload={"id": 10, "status": "completed"},
                jobs_payload=self._JOBS_ALL_PASS,
                job_logs_payload=job_log(job_id=999999),
                profile_s3_client=ProgressiveS3Client(tfstate_orphan_present=False, dispatched=["fired"]),
            )

    def test_missing_plan_step_is_refused_outright(self) -> None:
        with pytest.raises(WorldMovedError, match="carries no step named"):
            converge_verify(
                correlation_record={"verdict": "correlated", "fluents": {"run_id": 10}},
                run_payload={"id": 10, "status": "completed"},
                jobs_payload=apply_sandbox_jobs("success", with_plan_step=False),
                job_logs_payload=job_log(),
                profile_s3_client=ProgressiveS3Client(tfstate_orphan_present=False, dispatched=["fired"]),
            )


class TestPhaseOutcomeReport:
    def test_report_success_status_returns_zero(self, capsys: pytest.CaptureFixture) -> None:
        rc = PhaseOutcome("drained", "ok", {"run_id": "1"}).report()
        assert rc == 0
        assert "drained" in capsys.readouterr().out

    def test_report_world_moved_status_returns_one(self) -> None:
        assert PhaseOutcome("world_moved", "bad").report() == 1

    def test_report_prints_next_action_when_present(self, capsys: pytest.CaptureFixture) -> None:
        PhaseOutcome("dispatch", "ok", {}, next_action={"tool": "x"}).report()
        assert "next_action" in capsys.readouterr().out

    def test_to_record_omits_next_action_when_none(self) -> None:
        assert "next_action" not in PhaseOutcome("drained", "ok", {}).to_record()


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


def _package_source_minus_removal_rec_constants() -> str:
    """Structured exclusion (AST line ranges per file, never a text-substring cut) of the ONE
    sanctioned exemption -- the filed rec's own content constants in _phases.py, which are data
    this package writes, not an operational fluent it reads or branches on. Repointed from a
    single pre-split file to every *.py module in the package directory (VP10)."""
    chunks: list[str] = []
    for path in sorted(_PACKAGE_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
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
        chunks.append("\n".join(kept))
    return "\n".join(chunks)


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

    def test_package_source_carries_no_hardcoded_fluent(self) -> None:
        scannable = _package_source_minus_removal_rec_constants()
        hex_shas = re.findall(r"\b[0-9a-f]{7,40}\b", scannable)
        assert not hex_shas, f"package source contains hex-SHA-shaped literal(s) outside the removal-rec text: {hex_shas}"
        # rec-3348/rec-3328 are OPERATIONAL: _BUNDLED_REC_IDS, read and branched on by
        # derive_remove_state/gate_remove_preconditions/phase_close. rec-3381 is PROVENANCE-ONLY:
        # _github.py's docstrings cite it as the rec this normalizer module resolves -- never read
        # or branched on by any function. All three are a closed, reviewed allowlist; a fourth
        # rec id appearing anywhere is still unexpected and still reds this check.
        rec_ids = set(re.findall(r"rec-\d+", scannable))
        allowed = {"rec-3348", "rec-3328", "rec-3381"}
        assert rec_ids <= allowed, f"unexpected rec id literal(s) in source: {rec_ids - allowed}"
