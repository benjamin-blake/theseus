"""CLI entry point for the drain runbook: `-m scripts.ops.drain_glue_orphan`.

--phase {remove,converge} --step {gate,correlate,verify} drives one granular step per invocation
-- the agent makes any needed mcp__github__ call BETWEEN invocations (a Python process cannot call
an MCP tool itself) and hands this CLI the raw payload plus the previous step's on-disk record.
--phase close takes no --step. Two AWS profile flags carry the per-leg identity split (Decision
143 / VP5): --profile (default agent_platform) builds the client used for the convergence record,
the DuckLake reader and the portal write; --state-profile (default agent_platform_admin) builds
the client used ONLY for the raw tfstate read.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.ci import reconcile_target
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
from scripts.ops.drain_glue_orphan._world import WorldMovedError


def _live_clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Optional[str], *, label: str) -> dict[str, Any]:
    if not path:
        raise WorldMovedError(f"{label} is required for this step but was not supplied")
    resolved = Path(path)
    if not resolved.is_file():
        raise WorldMovedError(
            f"{label} file not found: {path} -- this step cannot self-clear without its predecessor's record"
        )
    return json.loads(resolved.read_text(encoding="utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.ops.drain_glue_orphan")
    parser.add_argument("--phase", choices=("remove", "converge", "close"), required=True)
    parser.add_argument("--step", choices=("gate", "correlate", "verify"), default=None)
    parser.add_argument("--profile", default="agent_platform")
    parser.add_argument("--state-profile", default="agent_platform_admin")
    parser.add_argument("--runs-json", default=None, help="gate: agent-fetched actions_list(list_workflow_runs) payload")
    parser.add_argument("--gate-record", default=None, help="correlate: this phase's own --out record from --step gate")
    parser.add_argument(
        "--dispatch-timestamp-from-record",
        action="store_true",
        help="correlate: required -- sources the dispatch timestamp from --gate-record, never a shell variable",
    )
    parser.add_argument(
        "--correlation-record", default=None, help="verify: this phase's own --out record from --step correlate"
    )
    parser.add_argument("--run-json", default=None, help="verify: agent-fetched actions_get(get_workflow_run) payload")
    parser.add_argument("--jobs-json", default=None, help="converge verify: agent-fetched list_workflow_jobs payload")
    parser.add_argument("--job-logs-json", default=None, help="verify: agent-fetched get_job_logs payload")
    parser.add_argument("--out", required=True)
    return parser


def _s3_client(profile: Optional[str]) -> Any:
    import boto3  # noqa: PLC0415

    return boto3.Session(profile_name=profile or None).client("s3")


def _dispatch(args: argparse.Namespace) -> PhaseOutcome:
    """Builds AWS clients and the DuckLake reader LAZILY, only in the branches that actually
    touch them -- gate and close. correlate/verify process only already-fetched JSON payloads and
    on-disk records, so a missing gate/correlation record must fail closed on ITS OWN terms
    (WorldMovedError) rather than crashing first on an unrelated AWS profile lookup."""
    if args.phase == "remove":
        if args.step == "gate":
            runs_payload = _load_json(args.runs_json, label="--runs-json")
            return remove_gate(
                profile_s3_client=_s3_client(args.profile),
                state_s3_client=_s3_client(args.state_profile),
                rec_reader=reconcile_target._default_reader(args.profile),
                runs_payload=runs_payload,
                clock=_live_clock,
            )
        if args.step == "correlate":
            if not args.dispatch_timestamp_from_record:
                raise WorldMovedError("--dispatch-timestamp-from-record is required for --step correlate")
            gate_record = _load_json(args.gate_record, label="--gate-record")
            runs_payload = _load_json(args.runs_json, label="--runs-json")
            return remove_correlate(gate_record=gate_record, runs_payload=runs_payload)
        correlation_record = _load_json(args.correlation_record, label="--correlation-record")
        run_payload = _load_json(args.run_json, label="--run-json")
        job_logs_payload = _load_json(args.job_logs_json, label="--job-logs-json")
        return remove_verify(correlation_record=correlation_record, run_payload=run_payload, job_logs_payload=job_logs_payload)

    if args.phase == "converge":
        if args.step == "gate":
            runs_payload = _load_json(args.runs_json, label="--runs-json")
            return converge_gate(
                profile_s3_client=_s3_client(args.profile),
                state_s3_client=_s3_client(args.state_profile),
                runs_payload=runs_payload,
                clock=_live_clock,
            )
        if args.step == "correlate":
            if not args.dispatch_timestamp_from_record:
                raise WorldMovedError("--dispatch-timestamp-from-record is required for --step correlate")
            gate_record = _load_json(args.gate_record, label="--gate-record")
            runs_payload = _load_json(args.runs_json, label="--runs-json")
            return converge_correlate(gate_record=gate_record, runs_payload=runs_payload)
        correlation_record = _load_json(args.correlation_record, label="--correlation-record")
        run_payload = _load_json(args.run_json, label="--run-json")
        jobs_payload = _load_json(args.jobs_json, label="--jobs-json")
        job_logs_payload = _load_json(args.job_logs_json, label="--job-logs-json")
        return converge_verify(
            correlation_record=correlation_record,
            run_payload=run_payload,
            jobs_payload=jobs_payload,
            job_logs_payload=job_logs_payload,
            profile_s3_client=_s3_client(args.profile),
        )

    from scripts.executor.rec_write_guidance import get_rec_write_guidance  # noqa: PLC0415
    from scripts.ops_data_portal import file_rec  # noqa: PLC0415

    return phase_close(
        profile_s3_client=_s3_client(args.profile),
        state_s3_client=_s3_client(args.state_profile),
        rec_reader=reconcile_target._default_reader(args.profile),
        file_rec=file_rec,
        get_rec_write_guidance=get_rec_write_guidance,
        profile=args.profile,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.phase in ("remove", "converge") and args.step is None:
        parser.error(f"--phase {args.phase} requires --step")
    if args.phase == "close" and args.step is not None:
        parser.error("--phase close does not take --step")

    try:
        outcome = _dispatch(args)
    except WorldMovedError as exc:
        print(f"drain_glue_orphan[world_moved]: {exc}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(outcome.to_record(), indent=2, default=str))
    return outcome.report()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
