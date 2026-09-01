"""VP step 9: regression and census against the REAL population with the baseline legs ENABLED
(real git, not the merge_base_rc=1 shortcut) -- so the census and ratchet are genuinely
exercised, and docs/contracts/contract-population.yaml passes the gate it defines."""

from __future__ import annotations

from pathlib import Path

from .conftest import validate_contract_drift

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REAL_CONTRACTS_DIR = _REPO_ROOT / "docs" / "contracts"

# The 20 seedable free-form files migration-step-3-grandfathering (PLAN-migration-step-3-
# grandfathering) converted to Class D -- see that plan's scope. exit-criteria-ledger.yaml was
# exempted from that sweep (genuinely Class-A-field-shaped) and is deliberately excluded from
# this roster; PLAN-cfg-migration-closeout later converted it to a Class A ritual contract in
# its own right (see TestExitCriteriaLedgerIsClassA below), never added to this Class D roster.
_SEEDED_CONTRACT_FILES = [
    "_joins.yaml",
    "build-lambda.yaml",
    "candidate-decision-ratification.yaml",
    "ci-rca-lifecycle.yaml",
    "composite-action-shape.yaml",
    "data-modeling-standard.yaml",
    "decision-entry.yaml",
    "deploy-paths.yaml",
    "file-router.yaml",
    "github-actions-evidence.yaml",
    "iam-simulate-fixture.yaml",
    "inference-provider.yaml",
    "instruction-architecture.yaml",
    "log-storage.yaml",
    "marker-grammar.yaml",
    "overseer-dispatch.yaml",
    "read-engine.yaml",
    "recommendation-relevance.yaml",
    "storage-substrate.yaml",
    "telemetry-lexicon.yaml",
]


class TestRealPopulationRegression:
    def test_real_population_passes_with_baseline_legs_enabled(self) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        assert failed == [], failed

    def test_real_population_census_counts_are_derived_and_nonzero(self, capsys) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        out = capsys.readouterr().out
        census_line = next(line for line in out.splitlines() if line.strip().startswith("Census:"))
        counts = dict(pair.split("=") for pair in census_line.strip().removeprefix("Census:").split())
        assert int(counts["scanned"]) > 0
        assert int(counts["ritual"]) > 0
        assert int(counts["skipped"]) == 0
        assert failed == []

    def test_every_seeded_contract_declares_a_resolving_evaluator(self) -> None:
        """Each of the 20 seeded files (migration-step-3-grandfathering) declares a valid Class D
        envelope with a unique subject and an evaluator that genuinely RESOLVES (check /
        agent_surface) -- the shared guard the per-file test_obligations rows are all proven by.
        UNCONDITIONAL since rec-3059 wave 2 retired the routed none_grandfathered debt-record
        escape: there is no longer a routed half to branch on, so this is the standing proof that
        the debt class is empty. Genuinely red before this plan lands (composite-action-shape.yaml
        and iam-simulate-fixture.yaml still carry none_grandfathered on main, and the retired kind
        is unrepresentable once this plan's schema deletion lands, so an unconverted file would
        fail to even LOAD); green after."""
        from scripts.checks.contracts import _population
        from scripts.contracts import load_contract_meta

        for name in _SEEDED_CONTRACT_FILES:
            path = _REAL_CONTRACTS_DIR / name
            assert path.is_file(), f"{name}: not found under {_REAL_CONTRACTS_DIR}"
            meta = load_contract_meta(path)  # raises ContractValidationError if malformed
            assert meta.class_.value == "D", f"{name}: contract.class is not D"
            assert meta.subject, f"{name}: subject is empty"
            assert meta.evaluator is not None, f"{name}: evaluator is absent"

            resolves, detail = _population.resolve_evaluator(name, meta.evaluator, root=_REPO_ROOT)
            assert resolves, f"{name}: evaluator does not resolve -- {detail}"


class TestExitCriteriaLedgerIsClassA:
    """VP step 5 / graduated check_id 'exit-criteria-ledger-is-class-a' (PLAN-cfg-migration-
    closeout): docs/contracts/exit-criteria-ledger.yaml is a genuine Class A ritual contract,
    proven by driving it through the three DISCRIMINATING ritual legs (load_contract,
    resolve_refs, check_required_inline_fields) and asserting class/ratified_via directly --
    not by grepping for a contract: block."""

    def test_exit_criteria_ledger_is_class_a_with_no_inline_field_errors(self) -> None:
        from scripts.contracts import load_contract, resolve_refs
        from scripts.contracts_enforcement import check_required_inline_fields

        path = _REAL_CONTRACTS_DIR / "exit-criteria-ledger.yaml"
        doc = load_contract(path)
        resolve_refs(doc, path.parent)
        errors = check_required_inline_fields(doc)

        assert doc.contract.class_.value == "A", doc.contract.class_
        assert errors == [], errors
        assert doc.contract.ratified_via and "dec-136" in doc.contract.ratified_via, doc.contract.ratified_via


class TestContractPopulationSelfHosting:
    def test_contract_population_yaml_passes_the_gate_it_defines(self) -> None:
        failed: list[str] = []
        validate_contract_drift(failed, contracts_dir=_REAL_CONTRACTS_DIR)
        assert not any("contract-population.yaml" in f for f in failed), failed

    def test_contract_population_yaml_is_ratified_with_a_resolving_evaluator(self) -> None:
        from scripts.contracts import load_contract_meta

        meta = load_contract_meta(_REAL_CONTRACTS_DIR / "contract-population.yaml")
        assert meta.status.value == "ratified"
        assert meta.ratified_via
        assert meta.evaluator.check == "validate_contract_drift"
