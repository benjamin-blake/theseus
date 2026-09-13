"""Tests for validate_composite_action_shape_rosters() -- PLAN-class-d-enforcers-wave-2 (rec-3059).

Covers: green path derived from the LIVE guard/config constants (mirrors
test_validate_read_engine_verbs.py's _live_verbs() pattern), roster-drift red paths (keys,
pinned_lines, baseline_file.path, section_allowlist.sections), delegate/script resolution red
paths, ABSENT/EMPTY-target red paths for all four blocks, missing-file, and malformed-YAML red
paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.checks import registry
from scripts.checks.ci_guards._workflow_shell_bodies import _KNOWN_BASELINE_SECTIONS
from scripts.checks.ci_guards.validate_composite_action_shell_bodies import _BASELINE_REL_PATH, _R1_KNOWN_VIOLATORS
from scripts.checks.contracts.validate_composite_action_shape_rosters import validate_composite_action_shape_rosters

_CONTRACT_NAME = "composite-action-shape.yaml"

# Real, on-disk conformant entry + closing instance (delegate/script resolution is always against
# the real repo root, never an injectable dir -- see the module docstring).
_REAL_CONFORMANT = {"key": ".github/actions/subagent-plan-review::review", "delegate": "review.sh"}
_REAL_CLOSING_SCRIPT = ".github/actions/write-convergence-record/assert_review_outcome.sh"

# Assertion group 5 (LSA-05): the agent-loop cap census also always scans the real repo root by
# default (see validate_composite_action_shape_rosters' `repo_root` override docstring), so the
# default fixture below matches the ONE real live site rather than leaving it undeclared.
_REAL_CAP_SITE = ".github/actions/subagent-plan-review/review.sh"
_REAL_CAP_ENTRY = {
    "site": _REAL_CAP_SITE,
    "kind": "max_turns",
    "value": 5,
    "on_exhaustion": "a starved verdict retries once at the same budget, then blocks the apply",
    "rationale": "five turns is enough for a read-only, single-verdict, Read-tool-only reviewer",
}


def _live_pinned() -> dict[str, int]:
    return dict.fromkeys(sorted(_R1_KNOWN_VIOLATORS), 5)


def _write_baseline(tmp_path: Path, r1: dict[str, int] | None) -> Path:
    baseline_path = tmp_path / "baseline.yaml"
    doc: dict = {}
    if r1 is not None:
        doc["r1"] = r1
    baseline_path.write_text(yaml.dump(doc), encoding="utf-8")
    return baseline_path


def _write_contract(
    contracts_dir: Path,
    *,
    violators: object = "__default__",
    baseline_file: object = "__default__",
    conformant: object = "__default__",
    closing_instance: object = "__default__",
    agent_loop_caps: object = "__default__",
) -> None:
    doc: dict = {}
    if violators == "__default__":
        doc["known_r1_violators"] = [{"key": k, "pinned_lines": v} for k, v in sorted(_live_pinned().items())]
    elif violators is not None:
        doc["known_r1_violators"] = violators

    if baseline_file == "__default__":
        doc["baseline_file"] = {
            "path": _BASELINE_REL_PATH,
            "section_allowlist": {"sections": sorted(_KNOWN_BASELINE_SECTIONS)},
        }
    elif baseline_file is not None:
        doc["baseline_file"] = baseline_file

    if conformant == "__default__":
        doc["known_r1_conformant"] = [_REAL_CONFORMANT]
    elif conformant is not None:
        doc["known_r1_conformant"] = conformant

    if closing_instance == "__default__":
        doc["closing_instance"] = {"script": _REAL_CLOSING_SCRIPT}
    elif closing_instance is not None:
        doc["closing_instance"] = closing_instance

    if agent_loop_caps == "__default__":
        doc["agent_loop_caps"] = [dict(_REAL_CAP_ENTRY)]
    elif agent_loop_caps is not None:
        doc["agent_loop_caps"] = agent_loop_caps

    (contracts_dir / _CONTRACT_NAME).write_text(yaml.dump(doc), encoding="utf-8")


_SYNTH_ON_EXHAUSTION = "synthetic starved path retries once then blocks the apply outright"
_SYNTH_RATIONALE = "synthetic reviewer needs only a few turns to read and reply with a verdict"


def _write_action_script(repo_root: Path, action_rel_dir: str, script_name: str, max_turns_value: int | None) -> str:
    """Write a synthetic .github/actions/<action_rel_dir>/<script_name> carrying a
    `--max-turns <value>` literal, or none at all when max_turns_value is None. Returns the
    repo-relative POSIX site path scan_cap_literals would key it under."""
    path = repo_root / ".github" / "actions" / action_rel_dir / script_name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "#!/usr/bin/env bash\n"
    if max_turns_value is not None:
        text += f"foo --max-turns {max_turns_value}\n"
    path.write_text(text, encoding="utf-8")
    return f".github/actions/{action_rel_dir}/{script_name}"


def _cap_entry(site: str, **overrides: object) -> dict:
    entry = {
        "site": site,
        "kind": "max_turns",
        "value": 5,
        "on_exhaustion": _SYNTH_ON_EXHAUSTION,
        "rationale": _SYNTH_RATIONALE,
    }
    entry.update(overrides)
    return entry


class TestGreenPath:
    def test_live_rosters_pass(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert failed == []


class TestRosterDriftRedPath:
    def test_extra_key_not_in_r1_known_violators_fails(self, tmp_path: Path) -> None:
        pinned = {**_live_pinned(), "extra::key": 3}
        _write_contract(tmp_path, violators=[{"key": k, "pinned_lines": v} for k, v in sorted(pinned.items())])
        baseline = _write_baseline(tmp_path, pinned)

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("_R1_KNOWN_VIOLATORS" in f for f in failed)

    def test_pinned_lines_drift_vs_baseline_fails(self, tmp_path: Path) -> None:
        live = _live_pinned()
        _write_contract(tmp_path, violators=[{"key": k, "pinned_lines": v} for k, v in sorted(live.items())])
        drifted = {**live, next(iter(live)): live[next(iter(live))] + 1}
        baseline = _write_baseline(tmp_path, drifted)

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("r1 section" in f for f in failed)

    def test_baseline_file_path_drift_fails(self, tmp_path: Path) -> None:
        _write_contract(
            tmp_path,
            baseline_file={
                "path": "config/wrong-path.yaml",
                "section_allowlist": {"sections": sorted(_KNOWN_BASELINE_SECTIONS)},
            },
        )
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("_BASELINE_REL_PATH" in f for f in failed)

    def test_section_allowlist_drift_fails(self, tmp_path: Path) -> None:
        _write_contract(
            tmp_path,
            baseline_file={"path": _BASELINE_REL_PATH, "section_allowlist": {"sections": ["r1"]}},
        )
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("_KNOWN_BASELINE_SECTIONS" in f for f in failed)

    def test_malformed_violator_entry_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, violators=[{"key": "no-pinned-lines"}])
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("malformed" in f for f in failed)

    def test_malformed_conformant_entry_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, conformant=[{"key": "no-delegate"}])
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("malformed" in f for f in failed)


class TestResolutionRedPath:
    def test_conformant_delegate_missing_on_disk_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, conformant=[{"key": ".github/actions/subagent-plan-review::review", "delegate": "nope.sh"}])
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("does not resolve" in f and "nope.sh" in f for f in failed)

    def test_closing_instance_script_missing_on_disk_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, closing_instance={"script": ".github/actions/does-not-exist/nope.sh"})
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("does not resolve" in f for f in failed)


class TestAbsentEmptyTarget:
    def test_missing_known_r1_violators_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, violators=None)
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("known_r1_violators" in f and "missing or empty" in f for f in failed)

    def test_empty_known_r1_violators_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, violators=[])
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("known_r1_violators" in f and "missing or empty" in f for f in failed)

    def test_missing_baseline_file_block_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, baseline_file=None)
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("baseline_file" in f and "missing or empty" in f for f in failed)

    def test_missing_section_allowlist_sections_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, baseline_file={"path": _BASELINE_REL_PATH, "section_allowlist": {}})
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("section_allowlist.sections" in f for f in failed)

    def test_section_allowlist_not_a_mapping_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, baseline_file={"path": _BASELINE_REL_PATH, "section_allowlist": "not-a-mapping"})
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("section_allowlist.sections" in f for f in failed)

    def test_missing_known_r1_conformant_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, conformant=None)
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("known_r1_conformant" in f and "missing or empty" in f for f in failed)

    def test_missing_closing_instance_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, closing_instance=None)
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("closing_instance.script" in f and "missing or empty" in f for f in failed)

    def test_missing_baseline_r1_section_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline = _write_baseline(tmp_path, None)

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert any("r1" in f and "missing or empty" in f for f in failed)

    def test_malformed_baseline_section_value_type_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline_path = tmp_path / "baseline.yaml"
        baseline_path.write_text(yaml.dump({"r1": {"a::b": "not-an-int"}}), encoding="utf-8")

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline_path)

        assert any("r1 section" in f or "missing or empty" in f for f in failed)


class TestMissingFile:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path)

        assert any("not found" in f for f in failed)


class TestMalformedYaml:
    def test_malformed_contract_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("known_r1_violators: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path)

        assert any("could not read/parse" in f for f in failed)

    def test_non_mapping_contract_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("- just\n- a\n- list\n", encoding="utf-8")

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path)

        assert any("not a YAML mapping" in f for f in failed)

    def test_missing_baseline_config_file_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=tmp_path / "nope.yaml")

        assert any("r1" in f and "missing or empty" in f for f in failed)

    def test_malformed_baseline_config_yaml_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline_path = tmp_path / "baseline.yaml"
        baseline_path.write_text("r1: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline_path)

        assert any("r1" in f and "missing or empty" in f for f in failed)

    def test_non_mapping_baseline_config_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path)
        baseline_path = tmp_path / "baseline.yaml"
        baseline_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline_path)

        assert any("r1" in f and "missing or empty" in f for f in failed)


class TestWiring:
    def test_wiring_registered_in_pre_and_full(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}

        assert "validate_composite_action_shape_rosters" in pre_names
        assert "validate_composite_action_shape_rosters" in full_names

    def test_wiring_resolves_via_registry(self) -> None:
        resolved = registry.resolve("validate_composite_action_shape_rosters")

        assert callable(resolved)
        assert resolved is validate_composite_action_shape_rosters


class TestPassLineOutput:
    """The PASS summary is the ONLY test-observable consequence of the `len(failed) ==
    error_count_before` accounting branch (registry.examined() runs unconditionally above it).

    Asserts the count-bearing PREFIX, never a hardcoded entry total -- the roster grows by
    addition, and an exact-count assertion would red a PR that never touched this file."""

    def test_clean_fixture_prints_the_pass_line(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_contract(tmp_path)
        baseline = _write_baseline(tmp_path, _live_pinned())

        failed: list[str] = []
        validate_composite_action_shape_rosters(failed, contracts_dir=tmp_path, baseline_config_path=baseline)

        assert failed == []
        out = capsys.readouterr().out
        assert "  PASS: composite-action-shape.yaml rosters match the live guard/config surfaces (" in out


class TestAgentLoopCapsGroup:
    """Assertion group 5 (audit finding LSA-05): the contract's own agent_loop_caps entries,
    derive-and-asserted against a fully synthetic action-region tree via the injectable
    `repo_root` override -- independent of `contracts_dir`, so neither tree need share a
    directory with the other."""

    def _run(self, tmp_path: Path, repo_root: Path, *, agent_loop_caps: object) -> list[str]:
        _write_contract(tmp_path, agent_loop_caps=agent_loop_caps)
        baseline = _write_baseline(tmp_path, _live_pinned())
        failed: list[str] = []
        validate_composite_action_shape_rosters(
            failed, contracts_dir=tmp_path, baseline_config_path=baseline, repo_root=repo_root
        )
        return failed

    def test_match_passes(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site)])
        assert failed == []

    def test_literal_only_bump_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 6)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, value=5)])
        assert any("drift" in f for f in failed), failed

    def test_declaration_only_bump_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, value=6)])
        assert any("drift" in f for f in failed), failed

    def test_undeclared_literal_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=None)
        assert any("undeclared" in f for f in failed), failed

    def test_stale_declaration_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", None)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site)])
        assert any("stale" in f for f in failed), failed

    def test_blank_on_exhaustion_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, on_exhaustion="")])
        assert any("on_exhaustion" in f for f in failed), failed

    def test_blank_rationale_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, rationale="")])
        assert any("rationale" in f for f in failed), failed

    def test_floor_clause_too_short_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, on_exhaustion="short")])
        assert any("non-triviality floor" in f for f in failed), failed

    def test_floor_clause_equal_to_kind_name_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, rationale="max_turns")])
        assert any("non-triviality floor" in f for f in failed), failed

    def test_floor_clause_on_exhaustion_equal_to_rationale_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site, rationale=_SYNTH_ON_EXHAUSTION)])
        assert any("must not be equal" in f for f in failed), failed

    def test_missing_site_key_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        entry = _cap_entry(".github/actions/synth-action/run.sh")
        del entry["site"]

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[entry])
        assert any("missing a non-empty 'site'" in f for f in failed), failed

    def test_not_a_list_fails(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"

        failed = self._run(tmp_path, repo_root, agent_loop_caps="not-a-list")
        assert any("agent_loop_caps must be a list" in f for f in failed), failed

    def test_absent_agent_loop_caps_with_no_live_cap_passes(self, tmp_path: Path) -> None:
        """No agent_loop_caps at all against a tree with no cap literal either -- group 5 is
        vacuous for this contract but must not itself fail."""
        repo_root = tmp_path / "repo"
        (repo_root / ".github" / "actions").mkdir(parents=True)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=None)
        assert failed == []

    def test_preexisting_roster_parity_groups_still_pass_alongside_group_5(self, tmp_path: Path) -> None:
        """Groups 1-4 (roster drift, baseline_file, conformant, closing_instance) still resolve
        against the REAL repo root (never repo_root) while group 5 resolves against a fully
        independent synthetic tree, in the same run."""
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        failed = self._run(tmp_path, repo_root, agent_loop_caps=[_cap_entry(site)])
        assert failed == []

    def test_accounting_examined_count_includes_cap_entries(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        site = _write_action_script(repo_root, "synth-action", "run.sh", 5)

        _write_contract(tmp_path, agent_loop_caps=[_cap_entry(site)])
        baseline = _write_baseline(tmp_path, _live_pinned())
        failed: list[str] = []
        validate_composite_action_shape_rosters(
            failed, contracts_dir=tmp_path, baseline_config_path=baseline, repo_root=repo_root
        )
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count >= 1 + len(_live_pinned()) + 1 + 1  # violators + baseline + conformant + closing + 1 cap
