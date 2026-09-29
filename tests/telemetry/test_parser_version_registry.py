"""rec-4122: parser_version registry and golden-corpus CI check per producer (Decision 207 R1).

Stdlib + yaml, fast tier. The CASES tuple names every golden case file basename literally: those literals are what
make --pre's data-edge channel select this module when only a golden case file changes.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from src.turn_capture.record_turn import PARSER_VERSION, PRODUCER, record_turn
from tests.fixtures.turn_capture_corpus import (
    GOLDEN_DIR,
    PROJECT_REF,
    case_names,
    golden_digest,
    load_case,
    mem_tree,
    normalise,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_REL = "config/telemetry/parser_versions.yaml"
CASES = (
    "pin_first_record_without_uuid.json",
    "multiblock_response_interleaved_tool_results.json",
    "meta_and_companion_records.json",
    "tool_result_error.json",
    "tool_result_interrupted.json",
    "hook_blocked_tool_call.json",
    "sidecar_present.json",
    "sidecar_absent.json",
    "subagent_sync.json",
    "subagent_background_with_completion.json",
    "subagent_background_without_completion.json",
    "nested_subagent_depth2.json",
    "hooks_resume_and_compact.json",
    "empty_thinking_and_image_blocks.json",
    "orphan_tool_result.json",
    "unknown_record_and_attachment_types.json",
    "trailing_partial_line.json",
    "malformed_line.json",
    "large_tool_result_over_64k.json",
    "observed_real_shapes.json",
    "secrets.json",
)


def registry_problems(registry: dict, producer: str, code_version: int, recomputed: str, expected: str) -> list[str]:
    """Every way the registry, the producer constant and the golden corpus can disagree."""
    entry = registry["producers"][producer]
    history = entry["history"]
    problems: list[str] = []
    versions = [h["version"] for h in history]
    if versions != sorted(set(versions)):
        problems.append("history versions are not strictly increasing")
    if entry["current"] != code_version or versions[-1] != code_version:
        problems.append("current, the last history version and the producer constant disagree")
    if history[-1]["golden_digest"] != recomputed:
        problems.append("output drift without a bump: the recomputed golden digest differs from the registry")
    if history[-1]["golden_digest"] != expected:
        problems.append("expected files edited without a bump: the committed expected_rows digest differs from the registry")
    for before, after in zip(history, history[1:]):
        if before["golden_digest"] == after["golden_digest"]:
            problems.append(f"bump without drift: v{after['version']} repeats v{before['version']}'s digest")
    return problems


def append_only_problems(base: dict | None, current: dict) -> list[str]:
    """History is append-only versus the merge-base copy (a path absent at the base passes)."""
    if base is None:
        return []
    problems: list[str] = []
    for producer, entry in base["producers"].items():
        now = current["producers"].get(producer)
        if now is None:
            problems.append(f"producer {producer} was removed")
            continue
        if now["history"][: len(entry["history"])] != entry["history"]:
            problems.append(f"{producer}: a past history entry was rewritten or removed")
        if now["current"] < entry["current"]:
            problems.append(f"{producer}: current went backwards")
    return problems


def _live_registry() -> dict:
    return yaml.safe_load((ROOT / REGISTRY_REL).read_text(encoding="utf-8"))


def _synthetic() -> dict:
    return {"producers": {"p": {"current": 2, "history": [
        {"version": 1, "date": "2026-01-01", "golden_digest": "d1", "reason": "first"},
        {"version": 2, "date": "2026-01-02", "golden_digest": "d2", "reason": "second"},
    ]}}}  # fmt: skip


def test_output_drift_without_bump_fails() -> None:
    registry = _synthetic()
    assert registry_problems(registry, "p", 2, "d2", "d2") == []
    problems = registry_problems(registry, "p", 2, "d3", "d2")
    assert len(problems) == 1 and problems[0].startswith("output drift without a bump")


def test_bump_without_drift_fails() -> None:
    registry = copy.deepcopy(_synthetic())
    registry["producers"]["p"]["history"][1]["golden_digest"] = "d1"
    problems = registry_problems(registry, "p", 2, "d1", "d1")
    assert len(problems) == 1 and problems[0].startswith("bump without drift")
    stale = registry_problems(_synthetic(), "p", 3, "d2", "d2")
    assert stale == ["current, the last history version and the producer constant disagree"]
    unordered = copy.deepcopy(_synthetic())
    unordered["producers"]["p"]["history"][1]["version"] = 1
    assert "history versions are not strictly increasing" in registry_problems(unordered, "p", 1, "d2", "d2")


def test_expected_edit_without_bump_fails() -> None:
    problems = registry_problems(_synthetic(), "p", 2, "d2", "d9")
    assert len(problems) == 1 and problems[0].startswith("expected files edited without a bump")


def _base_registry() -> tuple[str, dict | None]:
    """('absent' | 'unreadable' | 'present', parsed base copy) read from the merge base with origin/main."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)

    base = git("merge-base", "HEAD", "origin/main")
    if base.returncode != 0 or not base.stdout.strip():
        return "unreadable", None
    sha = base.stdout.strip()
    if not git("ls-tree", "-r", "--name-only", sha, "--", REGISTRY_REL).stdout.strip():
        return ("absent", None) if git("cat-file", "-e", sha).returncode == 0 else ("unreadable", None)
    shown = git("show", f"{sha}:{REGISTRY_REL}")
    return ("present", yaml.safe_load(shown.stdout)) if shown.returncode == 0 else ("unreadable", None)


def test_registry_history_is_append_only_against_main() -> None:
    older = _synthetic()
    grown = copy.deepcopy(older)
    grown["producers"]["p"]["history"].append({"version": 3, "date": "2026-01-03", "golden_digest": "d3", "reason": "third"})
    grown["producers"]["p"]["current"] = 3
    assert append_only_problems(older, grown) == [] and append_only_problems(None, grown) == []
    rewritten = copy.deepcopy(grown)
    rewritten["producers"]["p"]["history"][0]["golden_digest"] = "other"
    assert append_only_problems(older, rewritten)
    assert append_only_problems(grown, older) and append_only_problems(older, {"producers": {}})
    state, base = _base_registry()
    if state == "unreadable":
        if os.environ.get("CI"):
            pytest.fail("origin/main is unreadable in CI: the append-only check cannot run (Decision 208 cl.1)")
        pytest.skip("origin/main unreadable locally: advisory skip (Decision 208 cl.1)")
    assert (state == "absent") == (base is None)
    assert append_only_problems(base, _live_registry()) == []


def _live_digests() -> tuple[str, str]:
    names = case_names()
    recomputed: dict[str, list] = {}
    committed: dict[str, list] = {}
    for name in names:
        files, expected = load_case(name)
        recomputed[name] = normalise(record_turn(mem_tree(files), None, project_ref=PROJECT_REF, session_final=True).batches)
        committed[name] = expected
    return golden_digest(recomputed, names), golden_digest(committed, names)


def test_registry_matches_producer() -> None:
    registry = _live_registry()
    entry = registry["producers"][PRODUCER]
    assert PARSER_VERSION == entry["current"] == entry["history"][-1]["version"]
    recomputed, committed = _live_digests()
    assert recomputed == committed == entry["history"][-1]["golden_digest"]
    digests = [h["golden_digest"] for h in entry["history"]]
    assert all(a != b for a, b in zip(digests, digests[1:])), "a history entry repeats its predecessor's digest"
    assert registry_problems(registry, PRODUCER, PARSER_VERSION, recomputed, committed) == []


def test_cases_match_index() -> None:
    index = json.loads((GOLDEN_DIR / "index.json").read_text(encoding="utf-8"))
    assert list(CASES) == index["cases"]
    on_disk = sorted(p.name for p in GOLDEN_DIR.glob("*.json") if p.name != "index.json")
    assert on_disk == sorted(CASES)
    assert len(set(CASES)) == len(CASES)
