"""Mirror test for scripts/checks/deps/validate_check_manifests.py (Decision 168/169): the
grammar evaluator FAILS on an f-string module value, a "module:attr" colon form, a module that
resolves to no graph node, and a segment token present in _schema.py's SEGMENT_TOKENS but not the
contract's declared_segment_tokens (or vice versa). Each negative case is asserted to FAIL; the
clean tree is asserted to pass -- a suite that only asserted the clean case would be vacuous.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import networkx as nx

from scripts.checks.deps.validate_check_manifests import validate_check_manifests

_VALID_CONTRACT = """\
contract:
  id: check-manifest
  class: D
  contract_version: 1
  status: ratified
  ratified_via: "test fixture"
  subject: check-manifest
  evaluator:
    check: validate_check_manifests
amendment_log: []
entry_grammar:
  declared_segment_tokens:
    - full_after_lint
    - full_after_unit_tests
    - full_after_terraform_checks
    - full_after_dependency_health
    - full_after_ensure_fresh_dq
"""


def _write_tree(tmp_path: Path, manifest_body: str, contract_text: str = _VALID_CONTRACT) -> None:
    manifest_dir = tmp_path / "scripts" / "checks" / "fake_domain"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "_manifest.py").write_text(manifest_body, encoding="utf-8")
    contracts_dir = tmp_path / "docs" / "contracts"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "check-manifest.yaml").write_text(contract_text, encoding="utf-8")


def _run(tmp_path: Path, graph_nodes: tuple[str, ...] = ("scripts.checks.fake_domain.validate_x",)) -> list[str]:
    graph = nx.DiGraph()
    for node in graph_nodes:
        graph.add_node(node)
    failed: list[str] = []
    with (
        patch("scripts.checks.deps.validate_check_manifests._common.ROOT", tmp_path),
        patch("scripts.dependency_graph.build_graph", return_value=graph),
    ):
        validate_check_manifests(failed)
    return failed


_ENTRY_LITERAL = (
    "from scripts.checks._schema import Entry\n\n"
    'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain.validate_x", attr="validate_x"),)\n'
)


class TestCleanTreePasses:
    def test_clean_tree_passes(self, tmp_path: Path) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL)
        assert _run(tmp_path) == []

    def test_real_repo_tree_passes(self) -> None:
        """Unlike every other test in this module, this one does NOT patch _common.ROOT -- it
        scans the REAL 18 production manifests. This is the sole test in this file that a
        mutation to a real scripts/checks/<domain>/_manifest.py file can ever redden; every
        other test here is isolated to a synthetic tmp_path fixture."""
        failed: list[str] = []
        validate_check_manifests(failed)
        assert failed == []


class TestFStringModuleValueFails:
    def test_f_string_module_value_fails(self, tmp_path: Path) -> None:
        body = (
            "from scripts.checks._schema import Entry\n\n"
            '_stem = "validate_x"\n'
            'ENTRIES = (Entry(name="validate_x", module=f"scripts.checks.fake_domain.{_stem}", attr="validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path)
        assert any("bare string-literal constant" in f for f in failed), failed


class TestColonFormFails:
    def test_colon_form_fails(self, tmp_path: Path) -> None:
        body = (
            "from scripts.checks._schema import Entry\n\n"
            'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain:validate_x", attr="validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path, graph_nodes=())
        assert any("colon" in f for f in failed), failed


class TestUnresolvableModuleFails:
    def test_module_not_in_dependency_graph_fails(self, tmp_path: Path) -> None:
        body = (
            "from scripts.checks._schema import Entry\n\n"
            'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain.does_not_exist", attr="validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path, graph_nodes=())
        assert any("does not resolve to a real" in f for f in failed), failed


class TestSegmentTokenMismatchFails:
    def test_schema_token_absent_from_contract_fails(self, tmp_path: Path) -> None:
        contract = _VALID_CONTRACT.replace("    - full_after_ensure_fresh_dq\n", "")
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text=contract)
        failed = _run(tmp_path)
        assert any("SEGMENT_TOKENS" in f for f in failed), failed

    def test_contract_token_absent_from_schema_fails(self, tmp_path: Path) -> None:
        contract = _VALID_CONTRACT + "    - an_extra_token_not_in_schema\n"
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text=contract)
        failed = _run(tmp_path)
        assert any("SEGMENT_TOKENS" in f for f in failed), failed


class TestMissingFieldFails:
    def test_entry_missing_attr_kwarg_fails(self, tmp_path: Path) -> None:
        """An Entry() call that omits `attr=` entirely (not merely a non-literal value) exercises
        _kwarg_value's not-found return distinctly from the wrong-type branch above."""
        body = (
            "from scripts.checks._schema import Entry\n\n"
            'ENTRIES = (Entry(name="validate_x", module="scripts.checks.fake_domain.validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path)
        assert any("is missing `attr=`" in f for f in failed), failed

    def test_unnamed_entry_uses_placeholder_display_name(self, tmp_path: Path) -> None:
        """An Entry() with no `name=` kwarg still produces a readable failure message via the
        "<unnamed>" placeholder rather than raising."""
        body = (
            'from scripts.checks._schema import Entry\n\nENTRIES = (Entry(module="scripts.checks.fake_domain.validate_x"),)\n'
        )
        _write_tree(tmp_path, body)
        failed = _run(tmp_path)
        assert any("<unnamed>" in f and "is missing `attr=`" in f for f in failed), failed


class TestNoManifestFilesFails:
    def test_no_manifest_files_found_fails(self, tmp_path: Path) -> None:
        (tmp_path / "scripts" / "checks").mkdir(parents=True)
        contracts_dir = tmp_path / "docs" / "contracts"
        contracts_dir.mkdir(parents=True)
        (contracts_dir / "check-manifest.yaml").write_text(_VALID_CONTRACT, encoding="utf-8")
        failed = _run(tmp_path)
        assert any("no scripts/checks/*/_manifest.py files found" in f for f in failed), failed


class TestManifestSyntaxErrorFails:
    def test_unparseable_manifest_fails(self, tmp_path: Path) -> None:
        _write_tree(tmp_path, "def broken(:\n    pass\n")
        failed = _run(tmp_path)
        assert any("fake_domain/_manifest.py" in f for f in failed), failed


class TestContractFileFails:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / "scripts" / "checks" / "fake_domain"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "_manifest.py").write_text(_ENTRY_LITERAL, encoding="utf-8")
        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        failed = _run(tmp_path)
        assert any("check-manifest.yaml" in f for f in failed), failed

    def test_invalid_yaml_contract_fails(self, tmp_path: Path) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text="contract: [unclosed\n")
        failed = _run(tmp_path)
        assert any("check-manifest.yaml" in f for f in failed), failed

    def test_contract_missing_declared_segment_tokens_key_fails(self, tmp_path: Path) -> None:
        contract = "contract:\n  id: check-manifest\namendment_log: []\n"
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text=contract)
        failed = _run(tmp_path)
        assert any("missing entry_grammar.declared_segment_tokens" in f for f in failed), failed

    def test_contract_not_a_mapping_fails(self, tmp_path: Path) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text="- just\n- a\n- list\n")
        failed = _run(tmp_path)
        assert any("did not parse to a YAML mapping" in f for f in failed), failed


class TestContractReadErrorIsReportedDistinctly:
    """The contract-READ except branch (validate_check_manifests.py:112) must emit its own entry.

    Line 113 leaves contract_data=None, so line 126's "... did not parse to a YAML mapping."
    message keeps firing and by itself satisfies the `any("check-manifest.yaml" in f)` assertions
    of TestContractFileFails -- which is why neutering line 112 survives them. Per Decision 181
    point 3 the masking message is stripped by an EXACT suffix match first, and every assertion on
    what remains is POSITIVE (the except-branch message is present), never an absence claim.
    """

    @staticmethod
    def _read_errors(failed: list[str]) -> list[str]:
        return [f for f in failed if not f.endswith(" did not parse to a YAML mapping.")]

    def test_missing_contract_file_reports_the_read_error_distinctly(self, tmp_path: Path) -> None:
        manifest_dir = tmp_path / "scripts" / "checks" / "fake_domain"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "_manifest.py").write_text(_ENTRY_LITERAL, encoding="utf-8")
        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        read_errors = self._read_errors(_run(tmp_path))
        assert read_errors, "only the masking not-a-mapping message was emitted; the OSError branch is silent"
        assert any("check-manifest.yaml:" in f and "No such file or directory" in f for f in read_errors), read_errors

    def test_invalid_yaml_contract_reports_the_parse_error_distinctly(self, tmp_path: Path) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL, contract_text="contract: [unclosed\n")
        read_errors = self._read_errors(_run(tmp_path))
        assert read_errors, "only the masking not-a-mapping message was emitted; the yaml.YAMLError branch is silent"
        assert any("check-manifest.yaml:" in f and "flow sequence" in f for f in read_errors), read_errors

    def test_filter_keeps_a_second_genuine_error(self, tmp_path: Path) -> None:
        """The suffix filter strips ONLY the not-a-mapping message: a genuine failure from another
        site (here the manifest-SyntaxError arm at :79) survives it alongside the read error."""
        manifest_dir = tmp_path / "scripts" / "checks" / "fake_domain"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "_manifest.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
        (tmp_path / "docs" / "contracts").mkdir(parents=True)
        read_errors = self._read_errors(_run(tmp_path))
        assert any("Check-manifest grammar:" in f and "fake_domain/_manifest.py" in f for f in read_errors), read_errors
        assert any("check-manifest.yaml:" in f for f in read_errors), read_errors


class TestScanSummaryLine:
    """The terminal PASS/FAIL summary is the check's only operator-visible verdict -- no
    incumbent test reads stdout, so the branch that selects it was unasserted."""

    def test_clean_tree_prints_the_pass_summary(self, tmp_path: Path, capsys) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL)
        assert _run(tmp_path) == []
        assert "PASS: 1 manifest(s) scanned." in capsys.readouterr().out

    def test_violating_tree_prints_the_fail_summary(self, tmp_path: Path, capsys) -> None:
        _write_tree(tmp_path, _ENTRY_LITERAL.replace("fake_domain.validate_x", "fake_domain.absent"))
        failed = _run(tmp_path)
        assert len(failed) == 1
        assert "FAIL: 1 violation(s)." in capsys.readouterr().out
