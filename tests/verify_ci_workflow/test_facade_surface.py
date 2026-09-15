"""Mirror test for scripts/verify_ci_workflow/__init__.py -- the facade re-exporting the full
public surface of the former flat scripts/verify_ci_workflow.py module (Decision 128
decomposition)."""

from __future__ import annotations

from pathlib import Path

import scripts.verify_ci_workflow as facade
from scripts.verify_ci_workflow import _apply, _ci_rca, _ci_yaml, _cli, _shared

_NAME_TO_DEFINING_SUBMODULE = {
    "_load": _shared,
    "_get_steps_text": _shared,
    "_get_step_run_text": _shared,
    "_assert_runtime_lock": _shared,
    "_check_jobs_and_flags": _ci_yaml,
    "_is_truthy_concurrency_flag": _ci_yaml,
    "_check_concurrency": _ci_yaml,
    "_check_fetch_depth": _ci_yaml,
    "_check_full_tier_runtime_lock": _ci_yaml,
    "_MODULE_INVOCATION_RE": _ci_yaml,
    "_CHECK_LIKE_RE": _ci_yaml,
    "_check_validate_single_source": _ci_yaml,
    "_admits_pull_request": _ci_yaml,
    "_check_signal_green_needs": _ci_yaml,
    "_check_canary": _ci_rca,
    "_REQUIRED_CI_RCA_WORKFLOWS": _ci_rca,
    "_check_ci_rca_filter": _ci_rca,
    "_PATTERN_MATCHING_CONSTRUCT_RE": _ci_rca,
    "_CI_RCA_FETCH_STEP": _ci_rca,
    "_read_ci_rca_authority_sources": _ci_rca,
    "_ci_rca_fetch_source_comment": _ci_rca,
    "_decision_72_entry": _ci_rca,
    "_check_ci_rca_authority_anchor": _ci_rca,
    "_check_ci_rca_fetch_classification": _ci_rca,
    "_check_apply_rca_fallback": _apply,
    "_check_terraform_apply_concurrency": _apply,
    "_RECOVERY_FALLTHROUGH_STEP_IDS": _apply,
    "_RECOVERY_FRESH_PLAN_SIGNAL": _apply,
    "_RECOVERY_LEGACY_STALE_SIGNAL": _apply,
    "_RECOVERY_STALE_DETECTION_MARKERS": _apply,
    "_RECOVERY_FRESH_PLAN_PENDING": _apply,
    "_RECOVERY_FRESH_PLAN_NOT_PENDING": _apply,
    "_recovery_step_body": _apply,
    "_check_recovery_workflow_topology": _apply,
    "_COMMANDS": _cli,
    "main": _cli,
}


class TestFacadeSurface:
    def test_name_to_defining_submodule_map_covers_all_36_names(self) -> None:
        assert len(_NAME_TO_DEFINING_SUBMODULE) == 36
        assert set(_NAME_TO_DEFINING_SUBMODULE) == set(facade.__all__)

    def test_every_all_entry_resolves_through_the_facade(self) -> None:
        missing = [name for name in facade.__all__ if not hasattr(facade, name)]
        assert not missing, missing

    def test_every_name_resolves_to_its_expected_defining_submodule(self) -> None:
        mismatched = [
            name
            for name, submodule in _NAME_TO_DEFINING_SUBMODULE.items()
            if getattr(facade, name) is not getattr(submodule, name)
        ]
        assert not mismatched, mismatched

    def test_load_normalises_bare_on_key_to_data_on(self, tmp_path: Path) -> None:
        workflow = tmp_path / "workflow.yml"
        workflow.write_text("on:\n  push: {}\njobs: {}\n", encoding="utf-8")
        data = facade._load(str(workflow))
        assert "on" in data
        assert True not in data
        assert data["on"] == {"push": {}}

    def test_every_package_module_is_under_the_sloc_cap(self) -> None:
        pkg_dir = Path(facade.__path__[0])
        over = []
        for path in pkg_dir.glob("*.py"):
            sloc = sum(
                1
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
            if sloc > 500:
                over.append((path.name, sloc))
        assert not over, over
