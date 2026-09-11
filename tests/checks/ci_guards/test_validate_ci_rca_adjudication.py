"""Tests for validate_ci_rca_adjudication -- the bidirectional workflow-coverage,
filter/watched-equality, and entry-shape guard (PLAN-ci-rca-adjudication-guard).

Every negative case asserts a NON-EMPTY failed list -- a guard that cannot fail is the defect
this plan exists to prevent.
"""

from pathlib import Path

import pytest
import yaml

from scripts.checks import registry
from scripts.checks.ci_guards.validate_ci_rca_adjudication import _check_agent_loop_caps, validate_ci_rca_adjudication

_VALID_ENTRY = {"tier": "not_a_gate", "ci_rca": "excluded", "owner": "platform", "rationale": "test fixture"}

_VALID_CAP_ENTRY = {
    "kind": "max_turns",
    "value": 30,
    "on_exhaustion": "the mask lifts, the deterministic gate then fires and reddens the build",
    "rationale": "thirty turns because this agent is multi-bundle read-write, unlike a reviewer",
}


def _write_ci_rca_yml(root: Path, workflows: list[str]) -> None:
    wf_dir = root / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "ci-rca.yml").write_text(
        yaml.dump({"name": "CI RCA", "on": {"workflow_run": {"workflows": workflows, "types": ["completed"]}}}),
        encoding="utf-8",
    )


def _patch_taxonomy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, workflows_map: dict, names: list[str]) -> None:
    taxonomy = {
        "schema_version": 1,
        "taxonomy_version": 1,
        "function_to_category": {},
        "log_pattern_to_category": [],
        "workflows": workflows_map,
    }
    monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", lambda: taxonomy)
    monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_names", lambda: names)
    monkeypatch.setattr("scripts.ci_rca.taxonomy.ROOT", tmp_path)


def _write_cap_workflow(tmp_path: Path, filename: str, max_turns_value: int | None) -> Path:
    """Write a synthetic workflow .yml (under tmp_path/.github/workflows/) carrying a
    `--max-turns <value>` literal in a real `run: |` block, or no cap literal at all when
    `max_turns_value` is None."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    path = wf_dir / filename
    text = "name: CI\non:\n  push: {}\n"
    if max_turns_value is not None:
        text += f"jobs:\n  j:\n    steps:\n      - run: |\n          foo --max-turns {max_turns_value}\n"
    path.write_text(text, encoding="utf-8")
    return path


class TestWorkflowCoverageBidirectional:
    def test_unregistered_workflow_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A real workflow file with no taxonomy entry must fail (direction 1)."""
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": dict(_VALID_ENTRY)}, ["CI", "NewWorkflow"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'NewWorkflow'" in f and "absent from workflows" in f for f in failed), failed

    def test_stale_map_entry_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A taxonomy entry naming no real workflow file must fail (direction 2)."""
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": dict(_VALID_ENTRY), "GhostWorkflow": dict(_VALID_ENTRY)}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'GhostWorkflow'" in f and "stale entry" in f for f in failed), failed


class TestFilterEqualsWatchedBidirectional:
    def test_watched_but_absent_from_filter_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])  # filter omits CI despite it being watched

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "absent from ci-rca.yml" in f for f in failed), failed

    def test_filter_has_unwatched_workflow_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": dict(_VALID_ENTRY)}, ["CI"])
        _write_ci_rca_yml(tmp_path, ["CI"])  # CI is excluded in the taxonomy but present in the filter

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "is not ci_rca: watched" in f for f in failed), failed


class TestEntryShape:
    def test_missing_owner_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "owner": ""}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "missing a non-empty owner" in f for f in failed), failed

    def test_invalid_owner_type_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "owner": None}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "missing a non-empty owner" in f for f in failed), failed

    def test_missing_rationale_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "rationale": "   "}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "missing a non-empty rationale" in f for f in failed), failed

    def test_invalid_ci_rca_value_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "ci_rca": "maybe"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "ci_rca='maybe'" in f for f in failed), failed

    def test_non_mapping_entry_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": "not-a-dict"}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "is not a mapping" in f for f in failed), failed


class TestHappyPath:
    def test_synthetic_consistent_state_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        excluded_entry = dict(_VALID_ENTRY)
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry, "Lint": excluded_entry}, ["CI", "Lint"])
        _write_ci_rca_yml(tmp_path, ["CI"])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, failed

    def test_real_repo_state_passes(self) -> None:
        """No monkeypatching -- runs against the actual repo state post-migration."""
        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, f"Expected no failures against real repo state, got: {failed}"


class TestErrorPaths:
    def test_taxonomy_load_error_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise():
            raise ValueError("boom")

        monkeypatch.setattr("scripts.ci_rca.taxonomy.load_taxonomy", _raise)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("CI-RCA adjudication: boom" in f for f in failed), failed

    def test_malformed_ci_rca_yml_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry}, ["CI"])
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        (wf_dir / "ci-rca.yml").write_text("key: [unclosed", encoding="utf-8")

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("could not read/parse" in f for f in failed), failed


class TestSharedAccumulatorIsolation:
    """Regression guard: `failed` is the SHARED cross-check accumulator scripts/validate.py
    dispatches every check into, not a private result list. A branch that reads `failed` itself
    (instead of a locally-scoped result) to decide whether to run a later assertion group would
    silently skip that group whenever an EARLIER, unrelated check in the same dispatch had already
    appended to it -- exactly the failure mode this test seeds and asserts against."""

    def test_filter_check_still_runs_with_preexisting_unrelated_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        watched_entry = {**_VALID_ENTRY, "ci_rca": "watched"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": watched_entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])  # filter omits CI despite it being watched

        failed: list[str] = ["some unrelated check already failed"]
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "absent from ci-rca.yml" in f for f in failed), failed


class TestAgentLoopCapsGroup:
    """Assertion group (d) (audit finding LSA-05): a workflow row's optional agent_loop_caps
    list, derive-and-asserted against the live workflow-region agent-loop cap census."""

    def _setup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        row_caps: list[dict] | None,
        max_turns_value: int | None,
    ) -> None:
        entry = dict(_VALID_ENTRY)
        if row_caps is not None:
            entry["agent_loop_caps"] = row_caps
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])
        wf_path = _write_cap_workflow(tmp_path, "ci.yml", max_turns_value)
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_name_paths", lambda: [("CI", wf_path)])

    def test_matching_row_and_literal_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup(monkeypatch, tmp_path, row_caps=[dict(_VALID_CAP_ENTRY)], max_turns_value=30)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, failed

    def test_literal_only_bump_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup(monkeypatch, tmp_path, row_caps=[dict(_VALID_CAP_ENTRY)], max_turns_value=31)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("drift" in f for f in failed), failed

    def test_row_only_bump_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bumped_row = {**_VALID_CAP_ENTRY, "value": 31}
        self._setup(monkeypatch, tmp_path, row_caps=[bumped_row], max_turns_value=30)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("drift" in f for f in failed), failed

    def test_cap_with_no_declared_row_fails_as_undeclared(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup(monkeypatch, tmp_path, row_caps=None, max_turns_value=30)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("undeclared" in f for f in failed), failed

    def test_declared_row_whose_file_carries_no_literal_fails_as_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup(monkeypatch, tmp_path, row_caps=[dict(_VALID_CAP_ENTRY)], max_turns_value=None)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("stale" in f for f in failed), failed

    def test_nameless_workflow_with_cap_fails_rather_than_escaping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A workflow .yml with NO `name:` key can never be a taxonomy row (rows key on display
        name), but a live cap literal inside it must still be discovered and reddened as
        undeclared -- namelessness is not an escape from the census."""
        self._setup(monkeypatch, tmp_path, row_caps=None, max_turns_value=None)
        nameless = tmp_path / ".github" / "workflows" / "nameless.yml"
        nameless.write_text(
            "on:\n  push: {}\njobs:\n  j:\n    steps:\n      - run: |\n          foo --max-turns 7\n",
            encoding="utf-8",
        )

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("undeclared" in f and "nameless.yml" in f for f in failed), failed

    def test_preexisting_groups_still_pass_with_new_group_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No agent_loop_caps anywhere -- the three pre-existing assertion groups (coverage,
        filter, entry-shape) stay green with group (d) present but vacuous for this row."""
        self._setup(monkeypatch, tmp_path, row_caps=None, max_turns_value=None)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, failed

    def test_non_mapping_row_entry_skipped_directly(self, tmp_path: Path) -> None:
        """Defensive branch, exercised directly since group (c) upstream already guarantees every
        workflows_map entry reaching this helper is a mapping (see the module's own comment) --
        a non-mapping entry here must be silently skipped, never crash."""
        failures, examined = _check_agent_loop_caps({"CI": "not-a-dict"}, tmp_path)
        assert failures == []
        assert examined == 0

    def test_agent_loop_caps_not_a_list_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = {**_VALID_ENTRY, "agent_loop_caps": "not-a-list"}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])
        wf_path = _write_cap_workflow(tmp_path, "ci.yml", None)
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_name_paths", lambda: [("CI", wf_path)])

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("agent_loop_caps must be a list" in f for f in failed), failed

    def test_agent_loop_caps_shape_invalid_entry_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A shape-invalid cap entry (here: unknown kind) must fail via check_cap_entry_shape and
        must not be added to the declared map (the `continue` on a non-empty shape_failures)."""
        bad_row = [{**_VALID_CAP_ENTRY, "kind": "bogus_kind"}]
        self._setup(monkeypatch, tmp_path, row_caps=bad_row, max_turns_value=30)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("kind" in f and "bogus_kind" in f for f in failed), failed

    def test_row_name_missing_from_name_to_path_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Defensive branch: even though group (a)'s coverage check guards this in normal
        operation, a row whose name does not resolve through enumerate_workflow_name_paths must
        fail rather than silently drop the row's cap declaration from the comparison."""
        entry = {**_VALID_ENTRY, "agent_loop_caps": [dict(_VALID_CAP_ENTRY)]}
        _patch_taxonomy(monkeypatch, tmp_path, {"CI": entry}, ["CI"])
        _write_ci_rca_yml(tmp_path, [])
        monkeypatch.setattr("scripts.ci_rca.taxonomy.enumerate_workflow_name_paths", list)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert any("'CI'" in f and "does not resolve to a workflow file" in f for f in failed), failed

    def test_accounting_declares_nonzero_examined_count_on_green_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decision 170: the green path declares examined(n) with n > 0 -- examined(0) derives to
        'vacuous', which would register this newly-adopted group as a vacuous pass."""
        self._setup(monkeypatch, tmp_path, row_caps=[dict(_VALID_CAP_ENTRY)], max_turns_value=30)

        failed: list[str] = []
        validate_ci_rca_adjudication(failed)
        assert not failed, failed
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count > 0
