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

from unittest.mock import patch

from scripts.checks.verification import _vp_replay_classify as classify


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
