"""Outcome classification and classifier self-test for validate_vp_replay (Decision 189's four
frozen outcome classes; docs/contracts/vp-red-before.yaml is the sole home of their prose).

Split out of scripts/checks/verification/validate_vp_replay.py under Decision 128's
decompose-by-default rule when the rg-portability lint pushed that module past the 500-SLOC
unregistered-file limit. A private sibling module rather than a facade package, deliberately: 18
graduated registry records carry ``guard_target: scripts/checks/verification/validate_vp_replay.py``
and four more execute that literal path inside their check_spec, so converting the module to a
package would retire a live path out from under all of them. Decision 104 sanctions private
siblings inside scripts/checks/<domain>/.

Relocated VERBATIM -- no renames, no signature changes, no behaviour tuning in flight.
``PER_STEP_TIMEOUT_SECONDS`` moves with the fixtures because ``_SELF_TEST_FIXTURES`` reads it at
module level; leaving it behind would make this module import a partially-initialised
validate_vp_replay, a cycle that raises. validate_vp_replay re-imports every name here, so
``from scripts.checks.verification.validate_vp_replay import _classify_outcome`` keeps resolving.
"""

from __future__ import annotations

import re
import subprocess

PER_STEP_TIMEOUT_SECONDS = 30

# The FOUR frozen outcome classes (docs/contracts/vp-red-before.yaml derive-and-asserts equal to
# this tuple) -- never restated as a fifth class or split further.
OUTCOME_CLASSES: tuple[str, ...] = ("tautological", "target_absent", "assertion_failed", "unmeasurable")

# The five arms "unmeasurable" subsumes (docs/contracts/vp-red-before.yaml's unmeasurable_arms) --
# a subprocess timeout is handled separately (no exit code exists), the rest are exit-code/output
# based.
_UNMEASURABLE_EXIT_CODES = frozenset({126, 127})
_RG_GREP_ERROR_EXIT_CODE = 2
_RG_GREP_INVOCATION_RE = re.compile(r"(?:^|[|&;]|\s)(?:rg|grep)\b")
_PYTEST_COLLECTION_ERROR_EXIT_CODES = frozenset({4, 5})

# Mirrors scripts/checks/_scaffolding.py's _CREDENTIAL_UNAVAILABLE_MESSAGE_RE shape (Decision
# 155/170) -- that classifier is exception-based (a raised botocore exception); this one reads
# combined stdout+stderr TEXT from a replayed shell command instead, so it is kept as its own
# narrow, message-pattern-only regex rather than importing an exception-oriented classifier.
_CREDENTIAL_UNAVAILABLE_MESSAGE_RE = re.compile(
    r"(token (has )?expired|profile.*(not found|could not be found)|unable to locate credentials|"
    r"no credentials|unauthorized.*sso|token.*retriev|expiredtoken)",
    re.IGNORECASE,
)

# Classifier self-test fixtures (one per outcome class, PLUS a dedicated timeout arm so a
# regression specific to that arm cannot hide behind the exit-127 fixture alone). Cost-bounded:
# a sub-second timeout keeps the unconditional per-dispatch overhead small.
_SELF_TEST_TIMEOUT_SECONDS = 0.05
_SELF_TEST_FIXTURES: tuple[tuple[str, str, float], ...] = (
    ("true", "tautological", PER_STEP_TIMEOUT_SECONDS),
    ("exit 1", "assertion_failed", PER_STEP_TIMEOUT_SECONDS),
    ("exit 5", "target_absent", PER_STEP_TIMEOUT_SECONDS),
    ("exit 127", "unmeasurable", PER_STEP_TIMEOUT_SECONDS),
    ("sleep 5", "unmeasurable", _SELF_TEST_TIMEOUT_SECONDS),
)


def _classify_outcome(command: str, returncode: int | None, combined_output: str, *, timed_out: bool) -> str:
    """Classify one replayed graduate step's raw result into the four frozen outcome classes
    (docs/contracts/vp-red-before.yaml) -- the SOLE classification rule, called identically by
    the red-before leg's real replay and by the in-dispatch classifier self-test."""
    if timed_out:
        return "unmeasurable"
    if returncode == 0:
        return "tautological"
    if returncode in _UNMEASURABLE_EXIT_CODES:
        return "unmeasurable"
    if returncode == _RG_GREP_ERROR_EXIT_CODE and _RG_GREP_INVOCATION_RE.search(command):
        return "unmeasurable"
    if _CREDENTIAL_UNAVAILABLE_MESSAGE_RE.search(combined_output):
        return "unmeasurable"
    if returncode in _PYTEST_COLLECTION_ERROR_EXIT_CODES:
        return "target_absent"
    return "assertion_failed"


def _run_self_test_fixture(command: str, timeout: float) -> str:
    """Run one self-test fixture with no `cwd` override: these are generic shell builtins
    (true/exit N/sleep N) that touch no repo file, and this runs unconditionally before `root`
    is known to exist (an injected test `root` may be a nonexistent path on purpose)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _classify_outcome(command, None, "", timed_out=True)
    return _classify_outcome(command, result.returncode, result.stdout + result.stderr, timed_out=False)


def _run_classifier_self_test(failed: list[str]) -> None:
    """Classify one fixture per outcome class -- including the TIMEOUT arm -- as a precondition
    of this check's own verdict (Decision 55: a mislabelled classifier must never silently report
    a trustworthy verdict). A mislabel appends to ``failed`` directly; this function never calls
    ``examined()``/``skipped()`` -- the terminal Decision 170 declaration is composed once,
    elsewhere. Runs unconditionally, before any precondition early-return, so no unrelated skip
    reason can mask a broken classifier."""
    for command, expected, timeout in _SELF_TEST_FIXTURES:
        actual = _run_self_test_fixture(command, timeout)
        if actual != expected:
            failed.append(
                f"vp-red-before self-test: fixture {command!r} classified as {actual!r}, expected {expected!r} "
                "-- the outcome classifier is broken; refusing to report a trustworthy verdict."
            )
