"""Trailer-acceptance verdict LAYER (Decision 201, slice A -- source is "static" throughout).

Stops rec-autoclose closing a rec named in a Resolves: trailer without ever checking that rec's
own acceptance oracle. Three stages, one per ci.yml job (Decision 143 credential split, mirroring
scripts/backlog_health's three-job precedent):

  census   (id-token, reader read only)     -- census(): reads the trailer-named recs via the
            DuckLake reader, classifies each with the EXISTING scripts.backlog_health.census
            bucket vocabulary, and EXECUTES the require_decidable grammar ratchet -- a refusal
            reroutes a would-be-`probeable` entry to `unprobeable_shape`, which verdict_for()
            always resolves to out_of_grammar. Executes nothing.
  evaluate (contents: read ONLY, no id-token, no secret) -- evaluate(): the ONLY stage that runs
            rec-authored acceptance commands, delegated entirely to the EXISTING
            scripts.backlog_health.probe.run_all sandbox (unshare -rmn, read-only bind mount, no
            network). Holds no AWS credential at all.
  close    (id-token, portal writes)        -- rejoin(): treats evaluate's verdict artifact as
            UNTRUSTED INPUT (schema-validated, rejoined against census's own entries on rec_id +
            acceptance_sha256, mirroring scripts.backlog_health.escalate.rejoin_probe_verdicts),
            then threads the result into ci_rca_lifecycle.close_recs_from_trailer.

verdict_for() is a TOTAL map from census.BUCKETS x (probe.VERDICTS | {None}) onto the four-value
ACCEPTANCE_VERDICTS vocabulary (imported from scripts.ops_portal.closure_gate, never restated) --
see TestVerdictMapping for the totality and axis-parity assertions this map is checked against.

MUST NOT import closure_stamps_applicable (constraint 10, Decision 201): the graduated shard
tests/ops_data_portal/test_closure_gate.py::TestContractParity::
test_stamp_precondition_call_sites_match_importers derives importers of that symbol by AST, and a
new importer would require a same-PR ci-rca-lifecycle.yaml edit this plan deliberately avoids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from scripts.backlog_health import census as census_mod
from scripts.backlog_health import probe as probe_mod
from scripts.executor.acceptance_lint import lint_acceptance_command
from scripts.ops_portal.closure_gate import ACCEPTANCE_VERDICTS, FAILS, HOLDS, OUT_OF_GRAMMAR, UNMEASURABLE

ROOT = Path(__file__).resolve().parents[1]

SOURCE_STATIC = "static"

_CENSUS_ARTIFACT = "trailer_census.json"
_VERDICT_ARTIFACT = "acceptance_verdict.json"

# TOTAL over census.BUCKETS x (probe.VERDICTS | {None}) -- built once at import time from the
# upstream vocabularies themselves (never a hand-copied literal set), so a member added to either
# upstream vocabulary raises KeyError here rather than resolving silently (Decision 189 axis
# discipline, applied to totality rather than to the axis itself).
_PROBE_VERDICT_TO_ACCEPTANCE = {
    probe_mod.PASS: HOLDS,
    probe_mod.FAIL: FAILS,
    probe_mod.TIMEOUT: UNMEASURABLE,
    probe_mod.BUDGET_EXHAUSTED: UNMEASURABLE,
    probe_mod.ISOLATION_UNAVAILABLE: UNMEASURABLE,
    None: UNMEASURABLE,
}

_NON_PROBED_BUCKET_VERDICT = {
    census_mod.PROSE_ONLY: OUT_OF_GRAMMAR,
    census_mod.UNPROBEABLE_UNSAFE: OUT_OF_GRAMMAR,
    census_mod.UNPROBEABLE_SHAPE: OUT_OF_GRAMMAR,
    census_mod.EXPECTED_FAIL_MISSING_NODE: FAILS,
}


def verdict_for(bucket: str, probe_verdict: Optional[str]) -> str:
    """TOTAL: raises KeyError for any bucket outside census.BUCKETS or any probe_verdict outside
    probe.VERDICTS | {None} -- never resolves silently to a default. PROBEABLE is the only bucket
    that consults probe_verdict; every other bucket resolves on bucket alone (a non-PROBEABLE
    entry is never sent to probe.run_all, so its probe_verdict is always None in practice, but the
    map stays total over the full cross product regardless)."""
    if bucket == census_mod.PROBEABLE:
        return _PROBE_VERDICT_TO_ACCEPTANCE[probe_verdict]
    return _NON_PROBED_BUCKET_VERDICT[bucket]


def _make_reader(profile: Optional[str] = None) -> Any:
    from src.common.ducklake_reader_client import make_reader  # noqa: PLC0415

    return make_reader(profile=profile)


def census(
    ids: list[str],
    rows: Optional[list[dict[str, Any]]] = None,
    *,
    repo_root: Path = ROOT,
    reader: Any = None,
    profile: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Read every trailer-named rec (via `rows`, the test-injection seam, or a per-id
    `rec_by_id` reader read) and classify each into a census bucket, EXECUTING the
    require_decidable grammar ratchet: a `probeable` entry whose acceptance carries no decidable
    assertion is rerouted to `unprobeable_shape` -- verdict_for always resolves that bucket to
    out_of_grammar. An id absent from the reader is silently omitted (the later closure loop's
    require_acceptance_verdict=True leaves it OPEN with no verdict, the same loud-not-red posture
    as a refusal)."""
    live_rows = rows
    if live_rows is None:
        live_reader = reader if reader is not None else _make_reader(profile)
        live_rows = []
        for rec_id in ids:
            found = live_reader.named("rec_by_id", id=rec_id)
            if found:
                live_rows.append(dict(found[0]))

    entries: list[dict[str, Any]] = []
    for row in live_rows:
        acceptance = row.get("acceptance") or ""
        bucket = census_mod.classify_command(acceptance, repo_root=repo_root)
        if bucket == census_mod.PROBEABLE:
            ok, _reason = lint_acceptance_command(acceptance, require_decidable=True)
            if not ok:
                bucket = census_mod.UNPROBEABLE_SHAPE
        entries.append(
            {
                "rec_id": row["id"],
                "acceptance": acceptance,
                "acceptance_sha256": hashlib.sha256(acceptance.encode("utf-8")).hexdigest(),
                "bucket": bucket,
            }
        )
    return entries


def evaluate(entries: list[dict[str, Any]], repo_root: Path, sha: str) -> dict[str, Any]:
    """Execute only `probeable` entries through scripts.backlog_health.probe.run_all; every other
    entry's verdict is resolved from its bucket alone, with no execution. Returns the verdict
    document {sha, isolation_available, source, records: [{rec_id, sha, acceptance_sha256,
    verdict, source, arm}]}. `source` is "static" throughout -- the extension point slice B
    (junit ::node_id) adds records at."""
    probe_payload = [
        {"id": e["rec_id"], "acceptance": e["acceptance"]} for e in entries if e["bucket"] == census_mod.PROBEABLE
    ]
    probe_result = probe_mod.run_all(probe_payload, repo_root=repo_root, main_sha=sha)

    records: list[dict[str, Any]] = []
    for entry in entries:
        probed = entry["bucket"] == census_mod.PROBEABLE
        probe_verdict = probe_result["verdicts"].get(entry["rec_id"]) if probed else None
        records.append(
            {
                "rec_id": entry["rec_id"],
                "sha": sha,
                "acceptance_sha256": entry["acceptance_sha256"],
                "verdict": verdict_for(entry["bucket"], probe_verdict),
                "source": SOURCE_STATIC,
                "arm": probe_verdict if probed else entry["bucket"],
            }
        )
    return {
        "sha": sha,
        "isolation_available": probe_result["isolation_available"],
        "source": SOURCE_STATIC,
        "records": records,
    }


def rejoin(census_doc: dict[str, Any], verdict_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Rejoin the (untrusted) verdict document against census_doc's own entries on rec_id +
    acceptance_sha256 -- mirrors scripts.backlog_health.escalate.rejoin_probe_verdicts. A record
    for a rec_id census never sent to evaluate, whose verdict is outside ACCEPTANCE_VERDICTS, or
    whose acceptance_sha256 no longer matches (a stale/tampered artifact) is dropped rather than
    trusted. Returns {rec_id: record} -- the exact shape update_rec's acceptance_verdict kwarg
    expects for that rec."""
    census_entries = {e["rec_id"]: e for e in census_doc.get("entries") or [] if isinstance(e, dict) and e.get("rec_id")}
    clean: dict[str, dict[str, Any]] = {}
    for record in verdict_doc.get("records") or []:
        if not isinstance(record, dict):
            continue
        rec_id = record.get("rec_id")
        if not isinstance(rec_id, str) or record.get("verdict") not in ACCEPTANCE_VERDICTS:
            continue
        census_entry = census_entries.get(rec_id)
        if census_entry is None or record.get("acceptance_sha256") != census_entry.get("acceptance_sha256"):
            continue
        clean[rec_id] = record
    return clean


def _current_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"rec_trailer_acceptance: git rev-parse HEAD failed: {result.stderr}")
    return result.stdout.strip()


def _current_commit_message(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%B", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"rec_trailer_acceptance: git log -1 failed: {result.stderr}")
    return result.stdout


def _default_artifact_dir() -> Path:
    return Path(tempfile.gettempdir()) / "trailer_acceptance"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"rec_trailer_acceptance: expected artifact not found: {path} (did the prior stage run?)")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_census(args: argparse.Namespace) -> int:
    from scripts.rec_trailer import parse_resolves_trailer  # noqa: PLC0415

    message = _current_commit_message(ROOT)
    ids = parse_resolves_trailer(message)
    if not ids:
        print("[rec_trailer_acceptance census] no Resolves trailer found -- no-op")
        _write_json(args.artifact_dir / _CENSUS_ARTIFACT, {"ids": [], "entries": []})
        return 0

    entries = census(ids, repo_root=ROOT)
    print(f"[rec_trailer_acceptance census] ids={ids} entries={[e['bucket'] for e in entries]}")
    _write_json(args.artifact_dir / _CENSUS_ARTIFACT, {"ids": ids, "entries": entries})
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    census_doc = _read_json(args.payload) if args.payload else _read_json(args.artifact_dir / _CENSUS_ARTIFACT)
    sha = _current_sha(ROOT)
    result = evaluate(census_doc.get("entries") or [], ROOT, sha)
    print(
        f"[rec_trailer_acceptance evaluate] sha={result['sha']} isolation_available={result['isolation_available']} "
        f"verdicts={[(r['rec_id'], r['verdict']) for r in result['records']]}"
    )
    _write_json(args.artifact_dir / _VERDICT_ARTIFACT, result)
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    import os  # noqa: PLC0415

    from scripts.ops_data_portal import sync  # noqa: PLC0415
    from scripts.ops_portal.ci_rca_lifecycle import close_recs_from_trailer  # noqa: PLC0415

    census_doc = _read_json(args.artifact_dir / _CENSUS_ARTIFACT)
    ids = census_doc.get("ids") or []
    if not ids:
        print("[rec_trailer_acceptance close] no Resolves trailer found -- no-op")
        return 0

    verdict_doc = _read_json(args.artifact_dir / _VERDICT_ARTIFACT)
    acceptance_verdicts = rejoin(census_doc, verdict_doc)

    commit_sha = os.environ.get("GITHUB_SHA", "unknown")
    repo = os.environ.get("GITHUB_REPOSITORY", "unknown")
    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    try:
        sync()
    except Exception as exc:  # noqa: BLE001 -- mirrors rec-autoclose.yml's prior best-effort sync
        print(f"[rec_trailer_acceptance close] sync warning ({exc}); continuing with possibly stale cache")

    recs_cache: dict[str, dict[str, Any]] = {}
    cache_path = ROOT / "logs" / ".recommendations-log.jsonl"
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    recs_cache[row["id"]] = row
                except (json.JSONDecodeError, KeyError):
                    pass

    return close_recs_from_trailer(
        ids,
        commit_sha,
        run_url,
        recs_cache,
        acceptance_verdicts=acceptance_verdicts,
        require_acceptance_verdict=True,
    )


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--artifact-dir", type=Path, default=None)

    parser = argparse.ArgumentParser(prog="python -m scripts.rec_trailer_acceptance", parents=[common])
    subparsers = parser.add_subparsers(dest="command", required=True)

    census_parser = subparsers.add_parser("census", parents=[common])
    census_parser.set_defaults(handler=cmd_census)

    evaluate_parser = subparsers.add_parser("evaluate", parents=[common])
    evaluate_parser.add_argument("--payload", type=Path, default=None)
    evaluate_parser.set_defaults(handler=cmd_evaluate)

    close_parser = subparsers.add_parser("close", parents=[common])
    close_parser.set_defaults(handler=cmd_close)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.artifact_dir is None:
        args.artifact_dir = _default_artifact_dir()
    try:
        return args.handler(args)
    except RuntimeError as exc:
        print(f"[rec_trailer_acceptance] FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
