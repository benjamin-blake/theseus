"""Mirror of scripts/checks/hygiene/validate_declaring_coverage.py -- the REPORT-ONLY
path-aware declaring-coverage metric (Decision 170's deferred-work clause).

The report-only pin is a property over a SYNTHETIC fleet whose rows carry undeclared
success-exit paths, so it holds for every input rather than for today's repository. The
contract-derived-grammar pin points the report_grammar seam at a tmp_path contract carrying a
DIFFERENT grammar and observes the emitted line change -- never re-deriving the same value on
both sides of an assertion.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
from pathlib import Path

import pytest
import yaml

from scripts.checks import _common, registry
from scripts.checks.hygiene import validate_declaring_coverage as vdc
from scripts.checks.hygiene._declaring_coverage import UNDECIDABLE_REASONS, CheckCoverage, measure_check
from scripts.checks.hygiene.validate_declaring_coverage import (
    fleet_line,
    measure_fleet,
    report_grammar,
    validate_declaring_coverage,
)

_CONTRACT_REL = "docs/contracts/check-accounting.yaml"
_KEY = "path_aware_declaring_coverage"


@pytest.fixture(autouse=True)
def _drain_declaration_slot():
    """Pop the per-dispatch declaration slot after every test so a declaration made here never
    leaks into the next test's assertion about an empty slot."""
    yield
    registry.pop_declaration()


def _contract() -> dict:
    return yaml.safe_load((_common.ROOT / _CONTRACT_REL).read_text(encoding="utf-8"))


def _rows() -> list[CheckCoverage]:
    """A synthetic fleet: one fully declared row, one partially undeclared row, one wholly
    undeclared row, and one undecidable row."""
    return [
        CheckCoverage(check="check_declared", success_exits=2, declared=2, undeclared=0, failure_exits=1),
        CheckCoverage(check="check_partial", success_exits=3, declared=1, undeclared=2, failure_exits=0),
        CheckCoverage(check="check_bare", success_exits=1, declared=0, undeclared=1, failure_exits=0),
        CheckCoverage(
            check="check_opaque",
            success_exits=0,
            declared=0,
            undeclared=0,
            failure_exits=0,
            undecidable_reason="opaque_decorator",
        ),
    ]


_DECIDABLE_SOURCE = """from scripts.checks import registry


def validate_decidable(failed):
    registry.examined(1, unit="rows")
    if failed:
        return
    return
"""

_DYNAMIC_SOURCE = """from scripts.checks import registry


def validate_dynamic(failed):
    getattr(registry, "examined")(1)
    return
"""


def _rows_from_sources(tmp_path: Path, sources: dict[str, str]) -> list[CheckCoverage]:
    """Load each synthetic check module off tmp_path and measure it through the REAL walk
    measure_fleet runs per row -- measure_check reading the callable's own source file."""
    rows: list[CheckCoverage] = []
    for name, source in sources.items():
        module_path = tmp_path / f"{name}.py"
        module_path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows.append(measure_check(name, getattr(module, name)))
    return rows


def _write_contract(path: Path, grammar: object) -> Path:
    path.write_text(yaml.safe_dump({_KEY: {"fleet_line_grammar": grammar}}), encoding="utf-8")
    return path


class TestReportOnly:
    """The LOAD-BEARING report-only pin: a fleet whose rows carry undeclared success-exit paths
    still leaves `failed` empty. Holds for every input, not merely for today's fleet."""

    def test_a_fleet_with_undeclared_paths_fails_nothing(self, capsys: pytest.CaptureFixture) -> None:
        failed: list[str] = []
        validate_declaring_coverage(failed, rows=_rows())
        assert failed == []
        assert "undeclared=2" in capsys.readouterr().out

    def test_an_empty_fleet_fails_nothing_and_declares_zero(self) -> None:
        failed: list[str] = []
        validate_declaring_coverage(failed, rows=[])
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_the_declaration_is_examined_over_registered_checks(self) -> None:
        failed: list[str] = []
        rows = _rows()
        validate_declaring_coverage(failed, rows=rows)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "registered_checks"
        assert declaration.count == len(rows)

    def test_no_threshold_or_warned_status_is_introduced(self) -> None:
        contract = _contract()
        assert "warned" not in contract["status_vocabulary"]
        assert set(contract["status_vocabulary"]) == set(registry.STATUS_VOCABULARY)
        assert [k for k in contract[_KEY] if "threshold" in k] == []

    def test_the_module_appends_to_no_list_on_any_path(self) -> None:
        """Structural corroboration of the property above: the check body contains no append or
        extend call at all, so no input can produce a failing run."""
        source = Path(str(inspect.getsourcefile(vdc))).read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validate_declaring_coverage")
        sinks = [
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("append", "extend")
        ]
        assert sinks == []


class TestFleetSummaryLine:
    """One fleet summary line per run, rendered from the contract's own template."""

    def test_the_fleet_line_totals_the_rows(self) -> None:
        rendered = fleet_line(_rows(), report_grammar() or "")
        assert "checks=4" in rendered
        assert "success_exits=6" in rendered
        assert "declared=3" in rendered
        assert "undeclared=3" in rendered
        assert "undecidable=1" in rendered

    def test_exactly_one_fleet_line_is_printed(self, capsys: pytest.CaptureFixture) -> None:
        validate_declaring_coverage([], rows=_rows())
        out = capsys.readouterr().out
        assert len([line for line in out.splitlines() if "fleet: checks=" in line]) == 1

    def test_only_rows_outside_full_declaration_get_a_per_check_line(self, capsys: pytest.CaptureFixture) -> None:
        validate_declaring_coverage([], rows=_rows())
        out = capsys.readouterr().out
        assert "check_declared:" not in out
        assert "check_partial:" in out
        assert "check_bare:" in out
        assert "check_opaque:" in out

    def test_the_undecidable_row_line_prints_its_reason_and_no_bound_figures(self, capsys: pytest.CaptureFixture) -> None:
        """N1's report-side half: an undecidable row sits OUTSIDE the bound, so its line prints
        the reason and NO declared/undeclared figures that a reader could take for a bound."""
        validate_declaring_coverage([], rows=_rows())
        line = next(ln for ln in capsys.readouterr().out.splitlines() if "check_opaque:" in ln)
        assert "undecidable=opaque_decorator" in line
        assert "declared=" not in line
        assert "undeclared=" not in line
        assert "success_exits=" not in line
        assert "outside the measured bound" in line

    def test_a_row_with_no_success_exit_is_reported_rather_than_read_as_declared(self, capsys: pytest.CaptureFixture) -> None:
        row = CheckCoverage(check="check_all_failure", success_exits=0, declared=0, undeclared=0, failure_exits=2)
        validate_declaring_coverage([], rows=[row])
        assert "check_all_failure:" in capsys.readouterr().out

    def test_the_rendered_field_names_are_the_ones_the_grammar_whitelist_validates(self) -> None:
        """The renderer and the template validator share one field set: a template naming every
        _GRAMMAR_FIELDS member renders from real rows, so the whitelist report_grammar accepts a
        template against can never drift away from the kwargs fleet_line actually supplies."""
        template = " ".join(f"{{{name}}}" for name in vdc._GRAMMAR_FIELDS)
        assert fleet_line(_rows(), template) == "4 6 3 3 1"

    def test_the_report_only_notice_is_printed(self, capsys: pytest.CaptureFixture) -> None:
        validate_declaring_coverage([], rows=_rows())
        assert "REPORT-ONLY" in capsys.readouterr().out


class TestContractDerivedGrammar:
    """Decision 168 evidence of reading: the emitted line CHANGES when the contract changes."""

    def test_a_different_contract_grammar_changes_the_emitted_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fixture = _write_contract(tmp_path / "check-accounting.yaml", "TOTALS>>{checks}/{undeclared}")
        validate_declaring_coverage([], rows=_rows(), contract_path=fixture)
        out = capsys.readouterr().out
        assert "TOTALS>>4/3" in out
        assert "fleet: checks=" not in out

    def test_report_grammar_reads_the_live_contract_value(self) -> None:
        assert report_grammar() == _contract()[_KEY]["fleet_line_grammar"]

    def test_the_module_names_the_contract_in_executable_context(self) -> None:
        from scripts.checks.contracts._population import module_contains_literal  # noqa: PLC0415

        module_path = Path(str(inspect.getsourcefile(vdc)))
        assert module_contains_literal(module_path, "check-accounting.yaml")

    def test_a_grammar_from_a_fixture_contract_is_returned_verbatim(self, tmp_path: Path) -> None:
        fixture = _write_contract(tmp_path / "check-accounting.yaml", "x={checks}")
        assert report_grammar(fixture) == "x={checks}"


class TestFleetLineRegexDerivation:
    """fleet_line_grammar (a str.format template) and fleet_line_regex (a match regex) are two
    values, and their agreement is pinned against a line the check ACTUALLY emits."""

    def test_the_contract_regex_matches_an_emitted_fleet_line(self, capsys: pytest.CaptureFixture) -> None:
        validate_declaring_coverage([], rows=_rows())
        out = capsys.readouterr().out
        pattern = _contract()[_KEY]["fleet_line_regex"]
        assert re.search(pattern, out), out

    def test_the_shard_expected_is_the_contract_regex_verbatim(self) -> None:
        shard_rel = "config/agent/verification_registry/entries/declaring-coverage-fleet-report-line.yaml"
        shard = yaml.safe_load((_common.ROOT / shard_rel).read_text(encoding="utf-8"))
        assert shard["check_spec"]["use_regex"] is True
        assert shard["check_spec"]["expected"] == _contract()[_KEY]["fleet_line_regex"]

    def test_the_regex_is_unanchored_so_an_indented_line_still_matches(self) -> None:
        pattern = _contract()[_KEY]["fleet_line_regex"]
        rendered = "    " + fleet_line(_rows(), _contract()[_KEY]["fleet_line_grammar"])
        assert re.search(pattern, rendered)

    def test_the_regex_rejects_a_line_missing_a_field(self) -> None:
        pattern = _contract()[_KEY]["fleet_line_regex"]
        assert re.search(pattern, "fleet: checks=4 success_exits=6 declared=3 undeclared=3") is None


_MALFORMED_TEMPLATES = {
    "unknown_placeholder": "fleet: {checks} {typo}",
    "unclosed_brace": "fleet: {checks",
    "positional_placeholder": "fleet: {0}",
    "bad_format_spec": "fleet: {checks:%Y}",
    "indexed_placeholder": "fleet: {checks[0]}",
}

_UNAVAILABLE_MODES = (
    "missing_file",
    "undecodable_bytes",
    "malformed_yaml",
    "non_mapping_document",
    "missing_key",
    "non_mapping_key",
    "non_string_grammar",
    *sorted(_MALFORMED_TEMPLATES),
)


def _unavailable_contract(tmp_path: Path, mode: str) -> Path:
    """One contract fixture per way fleet_line_grammar can be unavailable. Each must route to
    the SAME skipped(reason) exit -- a raise from any of them would abort the whole full tier,
    because validation_result dispatches a check with no try/except.

    _MALFORMED_TEMPLATES covers the shapes where the value IS a string and the failure is in the
    template itself: an unknown placeholder name (KeyError), an unclosed brace (ValueError), a
    positional field (IndexError), an invalid format spec (ValueError) and an indexing field name
    (TypeError). str.format raises on each of those, so a check that accepted any str would carry
    the raise out through the tier dispatch."""
    path = tmp_path / "check-accounting.yaml"
    if mode == "missing_file":
        return tmp_path / "absent.yaml"
    if mode == "undecodable_bytes":
        path.write_bytes(b"\xff\xfe\x00garbage")
        return path
    if mode == "malformed_yaml":
        path.write_text("key: [unclosed\n", encoding="utf-8")
        return path
    if mode == "non_mapping_document":
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        return path
    if mode == "missing_key":
        path.write_text(yaml.safe_dump({"status_vocabulary": ["failed"]}), encoding="utf-8")
        return path
    if mode == "non_mapping_key":
        path.write_text(yaml.safe_dump({_KEY: "not-a-mapping"}), encoding="utf-8")
        return path
    if mode in _MALFORMED_TEMPLATES:
        return _write_contract(path, _MALFORMED_TEMPLATES[mode])
    assert mode == "non_string_grammar", mode
    return _write_contract(path, 17)


class TestGrammarUnavailableSkips:
    """An unavailable grammar is a declared skipped(reason) -- never a raise, never an append.
    Parameterized over EVERY unavailability shape the contract's grammar_unavailable_routing
    names, because one uncaught shape would abort the entire full tier from inside a check the
    dispatcher wraps in no try/except."""

    @pytest.mark.parametrize("mode", _UNAVAILABLE_MODES)
    def test_every_unavailable_shape_yields_no_grammar_and_never_raises(self, tmp_path: Path, mode: str) -> None:
        assert report_grammar(_unavailable_contract(tmp_path, mode)) is None

    @pytest.mark.parametrize("mode", _UNAVAILABLE_MODES)
    def test_every_unavailable_shape_routes_to_the_same_declared_skip(self, tmp_path: Path, mode: str) -> None:
        failed: list[str] = []
        validate_declaring_coverage(failed, rows=_rows(), contract_path=_unavailable_contract(tmp_path, mode))
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert "check-accounting.yaml" in str(declaration.reason)
        assert f"{_KEY}.fleet_line_grammar" in str(declaration.reason)

    @pytest.mark.parametrize("mode", _UNAVAILABLE_MODES)
    def test_no_unavailable_shape_emits_a_fleet_line(self, tmp_path: Path, mode: str, capsys: pytest.CaptureFixture) -> None:
        validate_declaring_coverage([], rows=_rows(), contract_path=_unavailable_contract(tmp_path, mode))
        out = capsys.readouterr().out
        assert "SKIP" in out
        assert "fleet: checks=" not in out

    def test_the_module_catches_only_named_exception_classes(self) -> None:
        """No bare except anywhere in the check module -- a bare handler would swallow the
        KeyboardInterrupt and SystemExit the tier runner needs to see. The set is pinned by
        EQUALITY, so it stays exact: the read seam catches the three file/YAML classes and the
        template seam the three str.format classes, and nothing wider ever creeps in."""
        tree = ast.parse(Path(str(inspect.getsourcefile(vdc))).read_text(encoding="utf-8"))
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
        assert handlers
        assert all(handler.type is not None for handler in handlers)
        caught = {
            node.id if isinstance(node, ast.Name) else node.attr
            for handler in handlers
            if isinstance(handler.type, ast.Tuple)
            for node in handler.type.elts
            if isinstance(node, (ast.Name, ast.Attribute))
        }
        assert caught == {"OSError", "UnicodeDecodeError", "YAMLError", "KeyError", "IndexError", "ValueError"}


class TestMeasureFleet:
    """The default population is the live registry roster; `names` is the injection seam."""

    def test_the_default_population_is_the_whole_roster(self) -> None:
        rows = measure_fleet()
        assert {row.check for row in rows} == set(registry.all_checks())

    def test_an_injected_name_set_is_measured_in_sorted_order(self) -> None:
        rows = measure_fleet(["validate_vacuity_justified", "validate_check_accounting"])
        assert [row.check for row in rows] == ["validate_check_accounting", "validate_vacuity_justified"]

    def test_a_synthetic_fleet_partitions_into_decidable_and_undecidable_rows(self, tmp_path: Path) -> None:
        """RE-SHAPE, not a loosening (recorded here deliberately). This node used to assert
        `undecidable_reason is None` for every row of measure_fleet(), which coupled the whole
        LIVE fleet's decidability to CI -- a de-facto fleet gate this plan declares out of scope,
        and a moving target the diff-aware --pre tier would never select -- while its companion
        `declared + undeclared == success_exits` was tautological (the walker CONSTRUCTS
        success_exits as that sum). It is now a property over a SYNTHETIC fleet walked for real
        off tmp_path: the population partitions by decidability, and each row's figures are the
        ones its own source shape entails. The live-fleet obligation that remains is the SELF row
        in TestMetricReportsItselfFullyDeclared."""
        rows = _rows_from_sources(tmp_path, {"validate_decidable": _DECIDABLE_SOURCE, "validate_dynamic": _DYNAMIC_SOURCE})
        decidable = [row for row in rows if row.undecidable_reason is None]
        undecidable = [row for row in rows if row.undecidable_reason is not None]
        assert [row.check for row in decidable] == ["validate_decidable"]
        assert [row.check for row in undecidable] == ["validate_dynamic"]
        assert undecidable[0].undecidable_reason in UNDECIDABLE_REASONS
        assert (decidable[0].success_exits, decidable[0].declared, decidable[0].undeclared) == (2, 2, 0)
        assert decidable[0].failure_exits == 0
        assert (undecidable[0].success_exits, undecidable[0].declared, undecidable[0].undeclared) == (0, 0, 0)
        assert undecidable[0].failure_exits == 0


class TestMetricReportsItselfFullyDeclared:
    """The metric's own module has ZERO undeclared success-exit paths -- the self-test the
    whole accounting channel exists to make possible."""

    def test_its_own_module_has_no_undeclared_success_exit(self) -> None:
        row = next(r for r in measure_fleet() if r.check == "validate_declaring_coverage")
        assert row.undecidable_reason is None
        assert row.success_exits >= 1
        assert row.undeclared == 0
        assert row.declared == row.success_exits

    def test_the_walker_helper_is_not_itself_a_registered_check(self) -> None:
        assert "_declaring_coverage" not in registry.all_checks()

    def test_the_live_run_leaves_failed_empty_and_declares(self) -> None:
        failed: list[str] = []
        registry.resolve("validate_declaring_coverage")(failed)
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.unit == "registered_checks"


class TestRegisteredSurfaces:
    """The registration surfaces a dispatch alone does not prove: the hygiene manifest Entry
    and the ci_rca_taxonomy row."""

    def test_resolve_reaches_this_module_s_own_callable(self) -> None:
        assert registry.resolve("validate_declaring_coverage") is vdc.validate_declaring_coverage
        assert "validate_declaring_coverage" in registry.all_checks()

    def test_the_manifest_entry_targets_this_module(self) -> None:
        """Named for what it asserts: the Entry's RUNTIME values point at this module and its
        callable. validate_check_manifests is the oracle for the bare-string-literal grammar
        itself (docs/contracts/check-manifest.yaml), and step 3 re-runs it against this Entry."""
        from scripts.checks.hygiene._manifest import ENTRIES  # noqa: PLC0415

        entry = next(e for e in ENTRIES if e.name == "validate_declaring_coverage")
        assert entry.module == "scripts.checks.hygiene.validate_declaring_coverage"
        assert entry.attr == "validate_declaring_coverage"

    def test_the_check_is_full_tier_only(self) -> None:
        from scripts.checks.hygiene._manifest import ENTRIES  # noqa: PLC0415

        entry = next(e for e in ENTRIES if e.name == "validate_declaring_coverage")
        assert entry.full_segment == "full_after_lint"
        assert entry.pre is False
        assert entry.pre_globs is None
        assert "validate_declaring_coverage" in {step.name for step in registry.full_sequence()}
        assert "validate_declaring_coverage" not in {step.name for step in registry.pre_sequence()}

    def test_the_taxonomy_row_names_a_declared_failure_category(self) -> None:
        taxonomy = yaml.safe_load((_common.ROOT / "config/ci_rca_taxonomy.yaml").read_text(encoding="utf-8"))
        category = taxonomy["function_to_category"]["validate_declaring_coverage"]
        assert category == "code_regression"
        assert category in taxonomy["failure_categories"]

    def test_the_registration_shard_exists_with_its_check_id_name(self) -> None:
        from scripts.verification_graduation import load_entries  # noqa: PLC0415

        rows = {row["check_id"]: row for row in load_entries()}
        assert rows["declaring-coverage-check-registered"]["primitive_slot"] == "command_exit_zero"
        assert rows["declaring-coverage-fleet-report-line"]["primitive_slot"] == "command_output_matches"
