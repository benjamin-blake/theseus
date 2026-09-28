"""Mirror for scripts/checks/verification/_vp_replay_classify.py.

validate_test_coverage resolves this file as that module's mirror via map_source_to_test and
measures THIS FILE ALONE against the source (no config/coverage_baseline.yaml entry exists for
scripts/checks/verification/**, so the threshold is 100%). It therefore covers all THREE relocated
functions, not just the classifier: _run_self_test_fixture's completing and TimeoutExpired paths
and _run_classifier_self_test's all-correct and mislabel paths are otherwise exercised only by
tests/checks/verification/validate_vp_replay/test_accounting_and_self_test.py, a different file
that contributes nothing to this measurement.

Carries its own fixtures and imports only from the source module -- Decision 131 /
validate_no_cross_test_imports forbids importing from a sibling test_* module.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.checks.verification import _vp_replay_classify as classify

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestOutcomeClassVocabulary:
    """The four frozen classes survived the relocation intact."""

    def test_the_four_classes_are_exactly_these(self) -> None:
        assert classify.OUTCOME_CLASSES == ("tautological", "target_absent", "assertion_failed", "unmeasurable")

    def test_exit_zero_is_tautological(self) -> None:
        assert classify._classify_outcome("true", 0, "", timed_out=False) == "tautological"

    def test_ordinary_nonzero_is_assertion_failed(self) -> None:
        assert classify._classify_outcome("exit 1", 1, "", timed_out=False) == "assertion_failed"

    def test_pytest_collection_errors_are_target_absent(self) -> None:
        for code in sorted(classify._PYTEST_COLLECTION_ERROR_EXIT_CODES):
            assert classify._classify_outcome("pytest x", code, "", timed_out=False) == "target_absent"


class TestUnmeasurableArms:
    """All five arms unmeasurable subsumes -- each asserted separately so none can satisfy another."""

    def test_timeout_arm(self) -> None:
        assert classify._classify_outcome("sleep 5", None, "", timed_out=True) == "unmeasurable"

    def test_exit_126_and_127_arm(self) -> None:
        for code in sorted(classify._UNMEASURABLE_EXIT_CODES):
            assert classify._classify_outcome("x", code, "", timed_out=False) == "unmeasurable"

    def test_rg_grep_exit_2_arm(self) -> None:
        assert classify._classify_outcome("grep p f", 2, "", timed_out=False) == "unmeasurable"

    def test_exit_2_without_an_rg_or_grep_invocation_is_not_unmeasurable(self) -> None:
        """The exit-2 arm is gated on the invocation, so it cannot alias the assertion arm."""
        assert classify._classify_outcome("./thing", 2, "", timed_out=False) == "assertion_failed"

    def test_credential_message_arm(self) -> None:
        assert classify._classify_outcome("aws s3 ls", 1, "Unable to locate credentials", timed_out=False) == "unmeasurable"


class TestSelfTestFixtureRunner:
    """_run_self_test_fixture, both paths."""

    def test_completing_command_is_classified(self) -> None:
        assert classify._run_self_test_fixture("exit 1", classify._SELF_TEST_COMPLETING_BOUND_SECONDS) == "assertion_failed"

    def test_timeout_path_is_classified_unmeasurable(self) -> None:
        assert classify._run_self_test_fixture("sleep 5", classify._SELF_TEST_TIMEOUT_SECONDS) == "unmeasurable"


class TestPerStepTimeoutSecondsRetired:
    """The flat per-step replay cap is gone -- the four completing fixtures carry their own local
    bound instead, and the sleep fixture keeps its own dedicated timeout."""

    def test_module_no_longer_defines_the_retired_constant(self) -> None:
        assert not hasattr(classify, "PER_STEP_TIMEOUT_SECONDS")

    def test_completing_fixtures_carry_the_local_bound_and_the_sleep_fixture_keeps_its_own(self) -> None:
        completing = [f for f in classify._SELF_TEST_FIXTURES if f[0] != "sleep 5"]
        assert completing
        assert all(timeout == classify._SELF_TEST_COMPLETING_BOUND_SECONDS for _cmd, _expected, timeout in completing)
        sleep_fixture = next(f for f in classify._SELF_TEST_FIXTURES if f[0] == "sleep 5")
        assert sleep_fixture[2] == classify._SELF_TEST_TIMEOUT_SECONDS


class TestScriptsValidateRecursionRefusalUnit:
    """Direct unit coverage of the relocated recursion-refusal helpers (Decision 128 overflow
    destination fired by this plan's deadline-model rewrite -- see the module docstring). The
    full-tier per-file coverage floor measures this file against _vp_replay_classify.py ALONE;
    tests/checks/verification/validate_vp_replay/test_lint_and_budget.py's end-to-end fixtures
    exercise these same functions via validate_vp_replay's re-export but do not count toward that
    isolated measurement."""

    def test_module_flag_pair_is_true(self) -> None:
        assert classify._segment_invokes_scripts_validate(["bin/venv-python", "-m", "scripts.validate", "--pre"]) is True

    def test_empty_tokens_is_false(self) -> None:
        assert classify._segment_invokes_scripts_validate([]) is False

    def test_bare_script_path_as_argv_head_is_true(self) -> None:
        assert classify._segment_invokes_scripts_validate(["scripts/validate.py", "--pre"]) is True

    def test_script_path_suffix_match_as_argv_head_is_true(self) -> None:
        assert classify._segment_invokes_scripts_validate(["/abs/path/scripts/validate.py"]) is True

    def test_interpreter_prefixed_script_path_is_true(self) -> None:
        assert classify._segment_invokes_scripts_validate(["python3", "scripts/validate.py"]) is True

    def test_interpreter_prefixed_script_path_suffix_match_is_true(self) -> None:
        assert classify._segment_invokes_scripts_validate(["python", "/abs/scripts/validate.py"]) is True

    def test_interpreter_alone_with_no_second_token_is_false(self) -> None:
        assert classify._segment_invokes_scripts_validate(["python3"]) is False

    def test_unrelated_command_is_false(self) -> None:
        assert classify._segment_invokes_scripts_validate(["ls", "-la"]) is False

    def test_command_invokes_scripts_validate_splits_shell_segments(self) -> None:
        assert classify._command_invokes_scripts_validate("echo hi && bin/venv-python -m scripts.validate --pre") is True

    def test_command_with_no_scripts_validate_segment_is_false(self) -> None:
        assert classify._command_invokes_scripts_validate("echo hi; ls -la") is False


class TestClassifierSelfTest:
    """_run_classifier_self_test, both paths."""

    def test_all_fixtures_classify_correctly(self) -> None:
        failed: list[str] = []
        classify._run_classifier_self_test(failed)
        assert failed == []

    def test_a_mislabelling_classifier_is_reported(self) -> None:
        failed: list[str] = []
        with patch.object(classify, "_classify_outcome", return_value="tautological"):
            classify._run_classifier_self_test(failed)
        assert failed, "a classifier returning one class for every fixture must be reported"
        assert any("self-test" in f and "the outcome classifier is broken" in f for f in failed)


class TestTimeoutShortCircuit:
    """rec-3835's acceptance class: TIMEOUT_OUTCOME is a named short-circuit, _classify_outcome's
    timed_out branch returns it regardless of the other arguments, and the self-test fixture
    deliberately keeps consulting _classify_outcome on its own timeout arm."""

    def test_timeout_outcome_is_unmeasurable_and_in_outcome_classes(self) -> None:
        assert classify.TIMEOUT_OUTCOME == "unmeasurable"
        assert classify.TIMEOUT_OUTCOME in classify.OUTCOME_CLASSES

    def test_classify_outcome_timed_out_short_circuits_regardless_of_other_args(self) -> None:
        assert classify._classify_outcome("anything", 0, "irrelevant output", timed_out=True) == classify.TIMEOUT_OUTCOME
        assert classify._classify_outcome("rg PATTERN missing.py", 2, "", timed_out=True) == classify.TIMEOUT_OUTCOME

    def test_self_test_fixture_still_consults_classifier_on_timeout_arm(self) -> None:
        with patch.object(classify, "_classify_outcome", return_value="SENTINEL") as mock_classify:
            result = classify._run_self_test_fixture("sleep 5", classify._SELF_TEST_TIMEOUT_SECONDS)
        assert result == "SENTINEL"
        mock_classify.assert_called_once()
        _, kwargs = mock_classify.call_args
        assert kwargs["timed_out"] is True


class TestUnmeasurableArmNames:
    """Each arm name is returned for its trigger, and every returned name is in the contract's
    unmeasurable_arms (derive-asserted from docs/contracts/vp-red-before.yaml)."""

    def test_exit_126_arm(self) -> None:
        assert classify.unmeasurable_arm("x", 126, "") == "exit_126_not_executable"

    def test_exit_127_arm(self) -> None:
        assert classify.unmeasurable_arm("x", 127, "") == "exit_127_command_not_found"

    def test_rg_grep_exit_2_arm(self) -> None:
        assert classify.unmeasurable_arm("grep p f", 2, "") == "rg_or_grep_error_exit_2"

    def test_credential_absence_arm(self) -> None:
        assert classify.unmeasurable_arm("aws s3 ls", 1, "Unable to locate credentials") == "credential_absence"

    def test_none_when_no_arm_applies(self) -> None:
        assert classify.unmeasurable_arm("./thing", 1, "") is None

    def test_every_returned_arm_name_is_in_the_contract(self) -> None:
        contract_path = _REPO_ROOT / "docs" / "contracts" / "vp-red-before.yaml"
        contract_arms = yaml.safe_load(contract_path.read_text(encoding="utf-8"))["unmeasurable_arms"]
        returned = {
            classify.unmeasurable_arm("x", 126, ""),
            classify.unmeasurable_arm("x", 127, ""),
            classify.unmeasurable_arm("grep p f", 2, ""),
            classify.unmeasurable_arm("aws s3 ls", 1, "Unable to locate credentials"),
        }
        assert returned <= set(contract_arms)


class TestMissingExecutable:
    """Both real Ubuntu missing-executable shell spellings; None for anything else."""

    def test_dash_spelling(self) -> None:
        assert classify.missing_executable("/bin/sh: 1: foo: not found\n") == "foo"

    def test_bash_spelling(self) -> None:
        assert classify.missing_executable("bash: line 1: foo: command not found\n") == "foo"

    def test_none_for_unrelated_output(self) -> None:
        assert classify.missing_executable("some ordinary assertion failure output") is None


class TestCollectionHint:
    """Output-keyed pytest collection hints -- every shape measured at planning against real
    pytest output (node/class selector vs whole-file, skip vs import-error, missing node vs
    missing file, and the non-hinted arms: a non-pytest command, exit 1, and a deselection)."""

    def test_module_level_skip_node_selector(self) -> None:
        out = "ERROR: found no collectors for x::test_thing\n\n1 skipped in 0.00s\n"
        assert classify.collection_hint("pytest x::test_thing -q", 4, out) == (
            "module-level skip -- e.g. a dependency absent from requirements-fast.txt (rec-2809)"
        )

    def test_module_level_skip_whole_file_selector(self) -> None:
        out = "1 skipped in 0.01s\n"
        assert classify.collection_hint("pytest x.py -q", 5, out) == (
            "module-level skip -- e.g. a dependency absent from requirements-fast.txt (rec-2809)"
        )

    def test_collection_error_never_module_level_skip(self) -> None:
        """A module whose own import raises -- exit 4, "found no collectors" WITH an error
        count -- must classify collection_error, never module_level_skip."""
        out = "1 error in 0.02s\nERROR: found no collectors for x::test_thing\n"
        assert classify.collection_hint("pytest x::test_thing -q", 4, out) == "collection error -- see output tail"

    def test_missing_node(self) -> None:
        out = "no tests ran in 0.00s\nERROR: not found: x.py::test_nonexistent\n(no match in any of [<Module x.py>])\n"
        assert classify.collection_hint("pytest x.py::test_nonexistent -q", 4, out) == "named node or file missing or renamed"

    def test_missing_file(self) -> None:
        out = "no tests ran in 0.00s\nERROR: file or directory not found: nope.py\n"
        assert classify.collection_hint("pytest nope.py -q", 4, out) == "named node or file missing or renamed"

    def test_none_for_non_pytest_command_exiting_4(self) -> None:
        assert classify.collection_hint("some-other-tool", 4, "found no collectors\n1 error in 0.0s") is None

    def test_none_on_exit_1(self) -> None:
        assert classify.collection_hint("pytest x.py", 1, "assert False") is None

    def test_none_for_deselection_no_tests_ran(self) -> None:
        assert classify.collection_hint("pytest x.py -k nomatch", 5, "no tests ran in 0.00s\n") is None


class TestExtractNegatedRgGrepPathUnit:
    """Direct unit coverage of `_extract_negated_rg_grep_path`'s branches -- relocated here from
    validate_vp_replay.py (Decision 128 sanctioned overflow move), so this mirror's isolated
    per-file coverage measurement needs its own direct exercise of every branch (no match, empty
    tail, wrong token count, a quoted or shell-metacharacter-bearing path token, and the
    successful two-token parse)."""

    def test_no_match_is_none(self) -> None:
        assert classify._extract_negated_rg_grep_path("echo hi") is None

    def test_empty_tail_is_unparseable(self) -> None:
        assert classify._extract_negated_rg_grep_path("! rg") is None

    def test_wrong_token_count_is_unparseable(self) -> None:
        assert classify._extract_negated_rg_grep_path("! rg PATTERN path.py extra") is None

    def test_quoted_path_token_is_unparseable(self) -> None:
        assert classify._extract_negated_rg_grep_path("! rg PATTERN 'quoted/path.py'") is None

    def test_metacharacter_path_token_is_unparseable(self) -> None:
        assert classify._extract_negated_rg_grep_path("! rg PATTERN some*glob.py") is None

    def test_valid_negated_grep_returns_the_path(self) -> None:
        assert classify._extract_negated_rg_grep_path("! grep PATTERN docs/contracts/foo.yaml") == "docs/contracts/foo.yaml"


class TestGreenLegLabelContractPins:
    """The token and the ordered hint structure (names, requires, forbids, texts) equal
    docs/contracts/vp-red-before.yaml's green_leg_labels' structured values -- the contract and
    the check hold one copy."""

    def test_token_and_hints_equal_the_contract(self) -> None:
        contract_path = _REPO_ROOT / "docs" / "contracts" / "vp-red-before.yaml"
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))["green_leg_labels"]
        assert data["token"] == classify.GREEN_LEG_LABEL_TOKEN
        assert data["hints"] == list(classify._COLLECTION_HINTS)
