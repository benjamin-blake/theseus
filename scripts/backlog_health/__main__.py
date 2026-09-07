"""Backlog-health monitor CLI (PLAN-backlog-health-detection).

    python -m scripts.backlog_health census  [--dry-run] [--artifact-dir PATH]
    python -m scripts.backlog_health probe   [--dry-run] [--artifact-dir PATH]
    python -m scripts.backlog_health escalate [--dry-run] [--artifact-dir PATH]

Three subcommands mirroring the workflow's three jobs (census -> probe -> escalate), handed off
via a JSON artifact under --artifact-dir (default: a temp dir) -- the local stand-in for the
workflow's inter-job actions/upload-artifact + actions/download-artifact handoff (Context: "the
--dry-run contract is that no WAREHOUSE write occurs; local temp files are the stand-in for the
artifact handoff"). Any reader or portal failure exits loudly and non-zero -- there is no silent
degrade-to-empty-result path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from scripts.backlog_health import census as census_mod
from scripts.backlog_health import classify as classify_mod
from scripts.backlog_health import escalate as escalate_mod
from scripts.backlog_health import probe as probe_mod

_CENSUS_ARTIFACT = "census.json"
_PROBE_ARTIFACT = "probe.json"


def _default_artifact_dir() -> Path:
    return Path(tempfile.gettempdir()) / "backlog_health"


def _current_main_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"backlog_health: git rev-parse HEAD failed: {result.stderr}")
    return result.stdout.strip()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"backlog_health: expected artifact not found: {path} (did the prior stage run?)")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_census(args: argparse.Namespace) -> int:
    result = census_mod.run_census(repo_root=census_mod.ROOT)
    print("[backlog_health census] " + ", ".join(f"{bucket}={count}" for bucket, count in result["counts"].items()))
    # --dry-run still writes the local artifact handoff so a three-stage chain (VP step 11) can
    # run census/probe/escalate as separate processes -- the no-warehouse-write contract is about
    # the read side never mutating ops_recommendations, not about this local temp-file handoff.
    _write_json(args.artifact_dir / _CENSUS_ARTIFACT, result)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    census_result = _read_json(args.artifact_dir / _CENSUS_ARTIFACT)
    main_sha = _current_main_sha(Path.cwd())
    result = probe_mod.run_all(census_result["probe_payload"], repo_root=Path.cwd(), main_sha=main_sha)
    verdict_counts: dict[str, int] = {}
    for verdict in result["verdicts"].values():
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    print(
        f"[backlog_health probe] main_sha={result['main_sha']} isolation_available={result['isolation_available']} "
        + str(verdict_counts)
    )
    if not result["isolation_available"] and result["verdicts"]:
        print("[backlog_health probe] FAIL: isolation unavailable on this runner -- no probe was attempted.", file=sys.stderr)
    _write_json(args.artifact_dir / _PROBE_ARTIFACT, result)
    if not result["isolation_available"] and result["verdicts"]:
        return 1
    return 0


def cmd_escalate(args: argparse.Namespace) -> int:
    census_result = _read_json(args.artifact_dir / _CENSUS_ARTIFACT)
    probe_artifact = _read_json(args.artifact_dir / _PROBE_ARTIFACT)
    probe_verdicts = escalate_mod.rejoin_probe_verdicts(census_result, probe_artifact)
    classification = classify_mod.classify_all(census_result, probe_verdicts)

    fresh_open_rows = census_mod.read_open_recs()

    results = escalate_mod.run_all_episodes(census_result, classification, fresh_open_rows, dry_run=args.dry_run)
    for source, outcome in results.items():
        print(f"{source}: {outcome['count']} findings (action={outcome['action']}, rec_id={outcome.get('rec_id')})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.backlog_health")
    parser.add_argument("--artifact-dir", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("census", cmd_census), ("probe", cmd_probe), ("escalate", cmd_escalate)):
        sub = subparsers.add_parser(name)
        sub.add_argument("--dry-run", action="store_true")
        sub.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.artifact_dir is None:
        args.artifact_dir = _default_artifact_dir()
    try:
        return args.handler(args)
    except RuntimeError as exc:
        print(f"[backlog_health] FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
