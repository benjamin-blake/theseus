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
        assert classify._run_self_test_fixture("exit 1", classify.PER_STEP_TIMEOUT_SECONDS) == "assertion_failed"

    def test_timeout_path_is_classified_unmeasurable(self) -> None:
        assert classify._run_self_test_fixture("sleep 5", classify._SELF_TEST_TIMEOUT_SECONDS) == "unmeasurable"


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
