"""Historical executed-node differ for the fast-tier optimisation audit."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from scripts.checks.deps import fast_tier_harness_capture, fast_tier_harness_support

_FILE_LAUNCH = __package__ in {None, ""}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_QUALIFYING_PATH_RE = re.compile(r"^(?:scripts|src|tests)/.+\.py$")
_DIFF_STATUSES = frozenset({"A", "M", "D"})
HarnessError = fast_tier_harness_support.HarnessError


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    pr: int
    merge_parent_sha: str
    merge_commit_sha: str
    diff_sha256: str
    qualifying_python_paths: tuple[str, ...]


@dataclass(frozen=True)
class Corpus:
    base_sha: str
    cases: tuple[CorpusCase, ...]
    predictor_pairs: tuple[dict[str, Any], ...]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HarnessError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise HarnessError(f"{label} must be a list")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise HarnessError(f"{label} must be a full lowercase Git SHA")
    return value


def _load_predictor_pairs(root: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    predictor = _mapping(root.get("predictor_calibration"), "predictor_calibration")
    pairs = _sequence(predictor.get("pairs"), "predictor_calibration.pairs")
    if predictor.get("required_count") != 8 or len(pairs) != 8:
        raise HarnessError("predictor calibration corpus must contain the required 8 pairs")
    pair_prs: set[int] = set()
    for index, item in enumerate(pairs):
        row = _mapping(item, f"predictor_calibration.pairs[{index}]")
        implementation_row = _mapping(row.get("implementation"), f"predictor_calibration.pairs[{index}].implementation")
        observed = _mapping(row.get("observed"), f"predictor_calibration.pairs[{index}].observed")
        pr = implementation_row.get("pr")
        if not isinstance(pr, int) or pr <= 0 or pr in pair_prs:
            raise HarnessError(f"predictor pair {index} has an invalid or duplicate implementation PR")
        if not isinstance(observed.get("n_selected"), int) or not isinstance(observed.get("test_s"), (int, float)):
            raise HarnessError(f"predictor pair for PR {pr} lacks observed n_selected/test_s")
        pair_prs.add(pr)
    loaded = tuple(pairs)
    try:
        fast_tier_harness_support.predictor_report(loaded)
    except (KeyError, TypeError, ValueError) as exc:
        raise HarnessError(f"predictor calibration corpus is incomplete: {exc}") from exc
    return loaded


def load_corpus(path: Path) -> Corpus:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise HarnessError(f"cannot load corpus {path}: {exc}") from exc
    root = _mapping(raw, "corpus")
    if root.get("schema_version") != 1:
        raise HarnessError("corpus schema_version must be 1")
    base_sha = _sha(root.get("base_sha"), "base_sha")
    implementation = _mapping(root.get("implementation"), "implementation")
    rows = _sequence(implementation.get("cases"), "implementation.cases")
    required_count = implementation.get("required_count")
    if required_count != 16 or len(rows) != required_count:
        raise HarnessError("implementation corpus must contain the required 16 cases")
    cases: list[CorpusCase] = []
    seen_ids: set[str] = set()
    seen_prs: set[int] = set()
    for index, item in enumerate(rows):
        row = _mapping(item, f"implementation.cases[{index}]")
        case_id = row.get("id")
        pr = row.get("pr")
        digest = row.get("diff_sha256")
        paths = _sequence(row.get("qualifying_python_paths"), f"implementation.cases[{index}].qualifying_python_paths")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise HarnessError(f"implementation case {index} has an invalid or duplicate id")
        if not isinstance(pr, int) or pr <= 0 or pr in seen_prs:
            raise HarnessError(f"implementation case {case_id} has an invalid or duplicate PR")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise HarnessError(f"implementation case {case_id} has an invalid diff_sha256")
        if not paths or any(not isinstance(value, str) or _QUALIFYING_PATH_RE.fullmatch(value) is None for value in paths):
            raise HarnessError(f"implementation case {case_id} has an invalid qualifying Python path")
        if len(paths) != len(set(paths)):
            raise HarnessError(f"implementation case {case_id} repeats a qualifying Python path")
        seen_ids.add(case_id)
        seen_prs.add(pr)
        cases.append(
            CorpusCase(
                case_id=case_id,
                pr=pr,
                merge_parent_sha=_sha(row.get("merge_parent_sha"), f"{case_id}.merge_parent_sha"),
                merge_commit_sha=_sha(row.get("merge_commit_sha"), f"{case_id}.merge_commit_sha"),
                diff_sha256=digest,
                qualifying_python_paths=tuple(paths),
            )
        )
    return Corpus(base_sha=base_sha, cases=tuple(cases), predictor_pairs=_load_predictor_pairs(root))


def _git_text(repo_root: Path, args: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise HarnessError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _git_bytes(repo_root: Path, args: list[str], *, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo_root, input=input_bytes, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HarnessError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def historical_diff(repo_root: Path, case: CorpusCase) -> list[tuple[str, str]]:
    fast_tier_harness_support.assert_pinned_objects_available(
        repo_root, (case.merge_parent_sha, case.merge_commit_sha), case_id=case.case_id
    )
    text = _git_text(repo_root, ["diff", "--name-status", "--no-renames", case.merge_parent_sha, case.merge_commit_sha])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != case.diff_sha256:
        raise HarnessError(f"{case.case_id}: historical diff digest drifted")
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] not in _DIFF_STATUSES:
            raise HarnessError(f"{case.case_id}: unsupported historical diff row {line!r}")
        entries.append((parts[0], parts[1]))
    qualifying = tuple(path for _, path in entries if _QUALIFYING_PATH_RE.fullmatch(path))
    if qualifying != case.qualifying_python_paths:
        raise HarnessError(f"{case.case_id}: qualifying Python paths drifted")
    return entries


def _safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise HarnessError(f"unsafe repository path {relative!r}")
    return root / path


def _apply_historical_diff(repo_root: Path, worktree: Path, case: CorpusCase) -> None:
    patch = _git_bytes(repo_root, ["diff", "--binary", "--full-index", case.merge_parent_sha, case.merge_commit_sha])
    _git_bytes(worktree, ["apply", "--binary", "--whitespace=nowarn", "-"], input_bytes=patch)


def _overlay_delta(repo_root: Path, worktree: Path, baseline_ref: str, engine_ref: str) -> None:
    _git_text(repo_root, ["rev-parse", "--verify", f"{baseline_ref}^{{commit}}"])
    _git_text(repo_root, ["rev-parse", "--verify", f"{engine_ref}^{{commit}}"])
    rows = _git_text(repo_root, ["diff", "--name-status", "--no-renames", baseline_ref, engine_ref])
    for line in rows.splitlines():
        status, relative = line.split("\t")
        target = _safe_path(worktree, relative)
        if status == "D":
            target.unlink(missing_ok=True)
            continue
        if status not in {"A", "M"}:
            raise HarnessError(f"unsupported engine delta row {line!r}")
        mode_row = _git_text(repo_root, ["ls-tree", engine_ref, "--", relative]).strip()
        mode = mode_row.split(maxsplit=1)[0] if mode_row else ""
        if mode not in {"100644", "100755"}:
            raise HarnessError(f"unsupported engine delta mode {mode!r} for {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_bytes(repo_root, ["show", f"{engine_ref}:{relative}"]))
        target.chmod(0o755 if mode == "100755" else 0o644)


def _worker(repo_root: Path, diff_path: Path, output_path: Path) -> None:
    if _FILE_LAUNCH:
        for module_name in tuple(sys.modules):
            if module_name == "scripts" or module_name.startswith("scripts."):
                del sys.modules[module_name]
    sys.path.insert(0, str(repo_root))
    from scripts.checks import (
        _common,  # noqa: PLC0415
        _pytest_diff,  # noqa: PLC0415
    )
    from scripts.checks.deps.affected_tests import derive_affected_tests  # noqa: PLC0415

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{fast_tier_harness_capture.PLUGIN_NAME}.py").write_text(
        fast_tier_harness_capture.PLUGIN_SOURCE, encoding="utf-8"
    )
    entries = json.loads(diff_path.read_text(encoding="utf-8"))
    selection = derive_affected_tests([(row["status"], row["path"]) for row in entries], repo_root=repo_root)
    original_run = _common.run
    command_rows: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    capture_lock = threading.Lock()

    def instrumented_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if not fast_tier_harness_capture.is_pytest_execution(command):
            return original_run(command, **kwargs)
        with capture_lock:
            index = len(command_rows)
            command_rows.append({"index": index, "state": "running"})
        augmented, env, junit_path, event_path = fast_tier_harness_capture.instrumented_pytest_command(
            command, output_dir, index, kwargs.get("env")
        )
        kwargs["env"] = env
        result = original_run(augmented, **kwargs)
        fast_tier_harness_capture.validate_junit(junit_path)
        events = fast_tier_harness_capture.read_events(event_path)
        with capture_lock:
            all_events.extend(events)
            command_rows[index] = {
                "index": index,
                "command": augmented,
                "returncode": result.returncode,
                "junit": junit_path.name,
                "node_events": event_path.name,
            }
        return result

    failed: list[str] = []
    setattr(_common, "run", instrumented_run)
    try:
        _pytest_diff.run_pytest_diff(selection["selected"], failed)
    finally:
        setattr(_common, "run", original_run)
    deferral_rel = getattr(_pytest_diff, "DEFERRAL_MAP_REL", "logs/debug/diff-coverage-deferrals.json")
    deferral_path = repo_root / deferral_rel
    if not deferral_path.is_file():
        raise HarnessError(f"real run_pytest_diff path did not emit its deferral map: {deferral_path}")
    deferral_payload = _mapping(json.loads(deferral_path.read_text(encoding="utf-8")), "deferral map")
    deferred = _mapping(deferral_payload.get("deferred"), "deferral map deferred")
    payload = {
        "selection": selection["manifest"],
        "gate_failures": failed,
        "commands": command_rows,
        "nodes": fast_tier_harness_capture.consolidate_nodes(all_events, deferred),
        "deferred_modules": deferred,
        "environment": {
            "python": sys.executable,
            "python_version": sys.version,
            "requirements_sha256": fast_tier_harness_capture.file_sha256(repo_root / "requirements.txt"),
            "requirements_fast_sha256": fast_tier_harness_capture.file_sha256(repo_root / "requirements-fast.txt"),
        },
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@contextlib.contextmanager
def _prepared_worktree(repo_root: Path, case: CorpusCase, baseline_ref: str, engine_ref: str) -> Iterator[Path]:
    from scripts.verification_graduation import git_worktree  # noqa: PLC0415

    with git_worktree(case.merge_parent_sha, repo_root=repo_root) as worktree:
        _apply_historical_diff(repo_root, worktree, case)
        _overlay_delta(repo_root, worktree, baseline_ref, engine_ref)
        yield worktree


def capture_case(
    repo_root: Path,
    case: CorpusCase,
    entries: list[tuple[str, str]],
    baseline_ref: str,
    engine_ref: str,
    output_path: Path,
    environment_root: Path,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path = output_path.parent / "historical-diff.json"
    diff_path.write_text(
        json.dumps([{"status": status, "path": path} for status, path in entries], indent=2) + "\n",
        encoding="utf-8",
    )
    with _prepared_worktree(repo_root, case, baseline_ref, engine_ref) as worktree:
        environment_python, environment_key = fast_tier_harness_support.ensure_fast_environment(worktree, environment_root)
        result = subprocess.run(
            [
                str(environment_python),
                str(Path(__file__).resolve()),
                "_worker",
                str(worktree),
                str(diff_path),
                str(output_path),
            ],
            cwd=worktree,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(repo_root), os.environ.get("PYTHONPATH", "")))},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    if result.returncode != 0:
        raise HarnessError(f"{case.case_id} worker failed for {engine_ref}: {(result.stdout + result.stderr).strip()}")
    try:
        capture = _mapping(json.loads(output_path.read_text(encoding="utf-8")), f"{case.case_id} capture")
        environment = _mapping(capture.get("environment"), f"{case.case_id} capture.environment")
        environment["fingerprint"] = environment_key
        output_path.write_text(json.dumps(capture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return capture
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"cannot read {case.case_id} capture: {exc}") from exc


def run_comparison(
    repo_root: Path,
    corpus: Corpus,
    baseline_ref: str,
    candidate_ref: str,
    output_path: Path,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    output_path = output_path.resolve()
    selected_cases = [case for case in corpus.cases if case_ids is None or case.case_id in case_ids]
    if case_ids is not None and {case.case_id for case in selected_cases} != case_ids:
        missing = sorted(case_ids - {case.case_id for case in selected_cases})
        raise HarnessError(f"unknown corpus case(s): {', '.join(missing)}")
    artifact_root = output_path.parent / f"{output_path.stem}-artifacts"
    environment_root = artifact_root / "environments"
    results: list[dict[str, Any]] = []
    for case in selected_cases:
        entries = historical_diff(repo_root, case)
        baseline = capture_case(
            repo_root,
            case,
            entries,
            baseline_ref,
            baseline_ref,
            artifact_root / case.case_id / "baseline" / "capture.json",
            environment_root,
        )
        candidate = capture_case(
            repo_root,
            case,
            entries,
            baseline_ref,
            candidate_ref,
            artifact_root / case.case_id / "candidate" / "capture.json",
            environment_root,
        )
        results.append(
            {
                "id": case.case_id,
                "pr": case.pr,
                "comparison": fast_tier_harness_capture.compare_captures(baseline, candidate),
            }
        )
    payload = {
        "schema_version": 1,
        "corpus_base_sha": corpus.base_sha,
        "baseline_ref": baseline_ref,
        "candidate_ref": candidate_ref,
        "stratum_i": {"case_count": len(results), "cases": results},
        "stratum_p": fast_tier_harness_support.predictor_report(corpus.predictor_pairs),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-corpus", help="validate the tracked corpus manifest")
    validate.add_argument("--corpus", type=Path, required=True)
    compare = subparsers.add_parser("compare", help="run the historical executed-node A/B differ")
    compare.add_argument("--corpus", type=Path, required=True)
    compare.add_argument("--baseline-ref", required=True)
    compare.add_argument("--candidate-ref", required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--case", action="append", dest="cases")
    worker = subparsers.add_parser("_worker")
    worker.add_argument("repo_root", type=Path)
    worker.add_argument("diff_path", type=Path)
    worker.add_argument("output_path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "_worker":
        _worker(args.repo_root, args.diff_path, args.output_path)
        return 0
    corpus = load_corpus(args.corpus)
    if args.command == "validate-corpus":
        print(
            f"Corpus valid: base={corpus.base_sha} implementation={len(corpus.cases)} predictor={len(corpus.predictor_pairs)}"
        )
        return 0
    repo_root = Path(__file__).resolve().parents[3]
    result = run_comparison(
        repo_root, corpus, args.baseline_ref, args.candidate_ref, args.output, set(args.cases or []) or None
    )
    print(f"Executed-node comparison written: {args.output} ({result['stratum_i']['case_count']} case(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
