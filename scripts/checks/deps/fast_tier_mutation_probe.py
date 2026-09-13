"""Run named test mutations against two revisions of the fast-tier audit work."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from scripts.verification_graduation import git_worktree


class MutationProbeError(RuntimeError):
    """A malformed probe or a test that does not catch its named mutation."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MutationProbeError(f"{label} must be a mapping")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MutationProbeError(f"{label} must be a non-empty string")
    return value


def _safe_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise MutationProbeError(f"unsafe mutation path {relative!r}")
    return root / path


def load_manifest(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        root = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "mutation manifest")
    except (OSError, yaml.YAMLError) as exc:
        raise MutationProbeError(f"cannot load mutation manifest {path}: {exc}") from exc
    if root.get("schema_version") != 1:
        raise MutationProbeError("mutation manifest schema_version must be 1")
    probes = root.get("probes")
    if not isinstance(probes, list) or not probes:
        raise MutationProbeError("mutation manifest probes must be a non-empty list")
    seen: set[str] = set()
    for index, value in enumerate(probes):
        probe = _mapping(value, f"probes[{index}]")
        probe_id = _string(probe.get("id"), f"probes[{index}].id")
        if probe_id in seen:
            raise MutationProbeError(f"duplicate mutation probe id {probe_id!r}")
        seen.add(probe_id)
        for side_name in ("baseline", "candidate"):
            side = _mapping(probe.get(side_name), f"{probe_id}.{side_name}")
            for field in ("subject_path", "test_node", "find", "replace"):
                _string(side.get(field), f"{probe_id}.{side_name}.{field}")
    return tuple(probes)


def _run_test(root: Path, test_node: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(root / "bin" / "venv-python"), "-m", "pytest", test_node, "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def _exercise_side(root: Path, side: dict[str, Any]) -> dict[str, Any]:
    subject_path = _string(side["subject_path"], "subject_path")
    test_node = _string(side["test_node"], "test_node")
    find = _string(side["find"], "find")
    replacement = _string(side["replace"], "replace")
    subject = _safe_path(root, subject_path)
    try:
        original = subject.read_text(encoding="utf-8")
    except OSError as exc:
        raise MutationProbeError(f"cannot read mutation subject {subject_path}: {exc}") from exc
    if original.count(find) != 1:
        raise MutationProbeError(f"{subject_path}: mutation anchor must occur exactly once")
    control = _run_test(root, test_node)
    if control.returncode != 0:
        raise MutationProbeError(f"{test_node}: unmutated control failed with exit {control.returncode}")
    subject.write_text(original.replace(find, replacement), encoding="utf-8")
    try:
        mutated = _run_test(root, test_node)
    finally:
        subject.write_text(original, encoding="utf-8")
    if mutated.returncode != 1:
        raise MutationProbeError(f"{test_node}: mutation was not caught as a test failure (exit {mutated.returncode})")
    return {
        "subject_path": subject_path,
        "test_node": test_node,
        "control_returncode": control.returncode,
        "mutation_returncode": mutated.returncode,
        "caught": True,
    }


def run_probe(
    repo_root: Path,
    probes: tuple[dict[str, Any], ...],
    baseline_ref: str,
    candidate_ref: str,
    output_path: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with git_worktree(baseline_ref, repo_root=repo_root) as baseline_root:
        with git_worktree(candidate_ref, repo_root=repo_root) as candidate_root:
            for probe in probes:
                rows.append(
                    {
                        "id": probe["id"],
                        "baseline": _exercise_side(baseline_root, _mapping(probe["baseline"], "baseline")),
                        "candidate": _exercise_side(candidate_root, _mapping(probe["candidate"], "candidate")),
                    }
                )
    payload = {
        "schema_version": 1,
        "baseline_ref": baseline_ref,
        "candidate_ref": candidate_ref,
        "probe_count": len(rows),
        "all_caught": all(row["baseline"]["caught"] and row["candidate"]["caught"] for row in rows),
        "probes": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    probes = load_manifest(args.manifest)
    repo_root = Path(__file__).resolve().parents[3]
    result = run_probe(repo_root, probes, args.baseline_ref, args.candidate_ref, args.output)
    print(f"Mutation probe written: {args.output} ({result['probe_count']} mutation(s), all caught)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
