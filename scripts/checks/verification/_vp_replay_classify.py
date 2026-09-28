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
validate_vp_replay re-imports every name here, so
``from scripts.checks.verification.validate_vp_replay import _classify_outcome`` keeps resolving.

The former flat per-step replay cap is RETIRED -- the shared aggregate budget
(validate_vp_replay.MAX_AGGREGATE_SECONDS, via _ReplayBudget.remaining()) is now a replayed step's
only deadline. The four completing self-test fixtures below use their own local
_SELF_TEST_COMPLETING_BOUND_SECONDS instead; the timeout fixture keeps _SELF_TEST_TIMEOUT_SECONDS.

Also carries the scripts.validate recursion-refusal helpers (the sanctioned Decision-128 overflow
destination named in the carrying plan's scope row, fired when the deadline-model rewrite pushed
validate_vp_replay.py back over the 500-SLOC unregistered-file limit): a command-classification
concern already in scope for this module, re-imported by validate_vp_replay.py so every existing
import of them keeps resolving.
"""

from __future__ import annotations

import re
import subprocess
from typing import TypedDict

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

# rec-3835: the timeout short-circuit's named outcome -- _classify_outcome's timed_out branch
# returns it directly, and validate_vp_replay's deadline-kill path (real replay) now sets it
# directly too, never routing back through _classify_outcome for that path. The in-dispatch
# self-test fixture below deliberately keeps consulting _classify_outcome on its own timeout arm
# (see _run_self_test_fixture) -- that is a different call site, exercising the classifier itself.
TIMEOUT_OUTCOME = "unmeasurable"

# Real Ubuntu missing-executable shell spellings (rec-3920): dash (what `shell=True` runs) prints
# "<shell>: <line>: <cmd>: not found"; bash prints "bash: line <n>: <cmd>: command not found".
_MISSING_EXECUTABLE_DASH_RE = re.compile(r"/bin/sh:\s*\d+:\s*(\S+):\s*not found")
_MISSING_EXECUTABLE_BASH_RE = re.compile(r"bash:\s*line\s*\d+:\s*(\S+):\s*command not found")

# Gates collection_hint below on a genuine pytest invocation -- never a bare substring, matching
# this module's other invocation-detection regexes.
_PYTEST_INVOCATION_RE = re.compile(r"\bpytest\b")

# GREEN-AFTER implement-leg divergence label token (docs/contracts/vp-red-before.yaml's
# green_leg_labels.token) -- deliberately NEVER the red-before leg's pinned "actual=<outcome>"
# form (Decision 201 point 1's axis discipline).
GREEN_LEG_LABEL_TOKEN = "raw outcome:"


class _CollectionHint(TypedDict):
    name: str
    requires: list[str]
    forbids: list[str]
    text: str


# Mirrors docs/contracts/vp-red-before.yaml's green_leg_labels.hints EXACTLY -- same order, same
# requires/forbids/text, raw (uncompiled) regex strings so TestGreenLegLabelContractPins can
# derive-assert this structure equal to the YAML-loaded one without a compiled-vs-string mismatch.
# collection_hint below iterates this ordered list; the contract and this module hold one copy.
_COLLECTION_HINTS: tuple[_CollectionHint, ...] = (
    {
        "name": "collection_error",
        "requires": ["found no collectors", r"\d+ errors?\b"],
        "forbids": [],
        "text": "collection error -- see output tail",
    },
    {
        "name": "module_level_skip",
        "requires": [r"\d+ skipped"],
        "forbids": [r"\d+ errors?\b", r"\d+ passed", r"\d+ failed"],
        "text": "module-level skip -- e.g. a dependency absent from requirements-fast.txt (rec-2809)",
    },
    {
        "name": "missing_node",
        "requires": ["not found:"],
        "forbids": [],
        "text": "named node or file missing or renamed",
    },
)

# Classifier self-test fixtures (one per outcome class, PLUS a dedicated timeout arm so a
# regression specific to that arm cannot hide behind the exit-127 fixture alone). Cost-bounded:
# a sub-second timeout keeps the unconditional per-dispatch overhead small. The four completing
# fixtures use their own local bound (never the retired flat per-step cap, and never
# validate_vp_replay.MAX_AGGREGATE_SECONDS -- this self-test has no dispatch budget to share).
_SELF_TEST_COMPLETING_BOUND_SECONDS = 5.0
_SELF_TEST_TIMEOUT_SECONDS = 0.05
_SELF_TEST_FIXTURES: tuple[tuple[str, str, float], ...] = (
    ("true", "tautological", _SELF_TEST_COMPLETING_BOUND_SECONDS),
    ("exit 1", "assertion_failed", _SELF_TEST_COMPLETING_BOUND_SECONDS),
    ("exit 5", "target_absent", _SELF_TEST_COMPLETING_BOUND_SECONDS),
    ("exit 127", "unmeasurable", _SELF_TEST_COMPLETING_BOUND_SECONDS),
    ("sleep 5", "unmeasurable", _SELF_TEST_TIMEOUT_SECONDS),
)

# scripts.validate recursion refusal (docs/contracts/vp-red-before.yaml's recursion_refusal):
# keyed on invocation SHAPE, never a bare substring -- see validate_vp_replay's module docstring
# and the contract for the 11 merged false-positive shapes this must not catch.
_SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|]")
_PYTHON_INTERPRETER_BASENAMES = frozenset({"python", "python3", "venv-python"})
_SCRIPTS_VALIDATE_SCRIPT_PATH = "scripts/validate.py"
_SCRIPTS_VALIDATE_MODULE = "scripts.validate"

# Negated-sweep lint (docs/contracts/vp-red-before.yaml's negated_sweep_lint): a `! rg`/`! grep`
# invocation's tail, up to the next shell control operator. Fails OPEN (returns None -- never
# flagged) on anything but a confident two-token (PATTERN, PATH) parse with a plain,
# unquoted, metacharacter-free PATH token -- over-detection is the worse failure here. Relocated
# from validate_vp_replay.py (Decision 128 sanctioned overflow move -- the deadline-model rewrite
# pushed that module back over the 500-SLOC unregistered-file limit); re-imported there so every
# existing import keeps resolving.
_NEGATED_RG_GREP_RE = re.compile(r"!\s*(?:rg|grep)\b(?P<tail>[^&|;\n]*)")
_QUOTED_TOKEN_RE = re.compile(r"""^(?:"[^"]*"|'[^']*')$""")
_SAFE_PATH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def unmeasurable_arm(command: str, returncode: int | None, combined_output: str) -> str | None:
    """Return docs/contracts/vp-red-before.yaml's unmeasurable_arms name for one NON-TIMEOUT
    outcome, or None if none applies. _classify_outcome delegates its non-timeout unmeasurable
    decision to this helper with byte-identical behaviour (TestUnmeasurableArms,
    TestClassifierArmsDoNotAlias and the in-dispatch self-test prove no drift). The timeout arm
    (subprocess_timeout) is handled separately -- no exit code exists for it, see TIMEOUT_OUTCOME
    and _classify_outcome's timed_out branch."""
    if returncode == 126:
        return "exit_126_not_executable"
    if returncode == 127:
        return "exit_127_command_not_found"
    if returncode == _RG_GREP_ERROR_EXIT_CODE and _RG_GREP_INVOCATION_RE.search(command):
        return "rg_or_grep_error_exit_2"
    if _CREDENTIAL_UNAVAILABLE_MESSAGE_RE.search(combined_output):
        return "credential_absence"
    return None


def missing_executable(combined_output: str) -> str | None:
    """Parse the real Ubuntu missing-executable shell spellings out of ``combined_output`` --
    dash's "/bin/sh: 1: foo: not found" (what `shell=True` runs) and bash's "bash: line 1: foo:
    command not found". None if neither spelling is present."""
    match = _MISSING_EXECUTABLE_DASH_RE.search(combined_output) or _MISSING_EXECUTABLE_BASH_RE.search(combined_output)
    return match.group(1) if match else None


def _extract_negated_rg_grep_path(command: str) -> str | None:
    """Return the candidate absent-path argument of a negated ``! rg``/``! grep`` invocation in
    ``command``, or None if the command does not confidently parse as one (fail-open). Relocated
    from validate_vp_replay.py (Decision 128 sanctioned overflow move)."""
    match = _NEGATED_RG_GREP_RE.search(command)
    if match is None:
        return None
    tail = match.group("tail").strip()
    if not tail:
        return None
    non_flag_tokens = [tok for tok in tail.split() if not tok.startswith("-")]
    if len(non_flag_tokens) != 2:
        return None
    path_tok = non_flag_tokens[1]
    if _QUOTED_TOKEN_RE.match(path_tok):
        return None
    if not _SAFE_PATH_TOKEN_RE.match(path_tok):
        return None
    return path_tok


def collection_hint(command: str, returncode: int | None, combined_output: str) -> str | None:
    """docs/contracts/vp-red-before.yaml's green_leg_labels.hints: the first ordered hint (of
    _COLLECTION_HINTS) whose ``requires`` all match and ``forbids`` none match against
    ``combined_output``, gated once on a pytest invocation exiting 4/5. None otherwise -- e.g.
    exit 5 "no tests ran" from a deselection, or a non-pytest command exiting 4/5."""
    if returncode not in _PYTEST_COLLECTION_ERROR_EXIT_CODES or not _PYTEST_INVOCATION_RE.search(command):
        return None
    for hint in _COLLECTION_HINTS:
        requires = hint["requires"]
        forbids = hint["forbids"]
        if all(re.search(p, combined_output) for p in requires) and not any(re.search(p, combined_output) for p in forbids):
            return hint["text"]
    return None


def _classify_outcome(command: str, returncode: int | None, combined_output: str, *, timed_out: bool) -> str:
    """Classify one replayed graduate step's raw result into the four frozen outcome classes
    (docs/contracts/vp-red-before.yaml) -- the SOLE classification rule, called identically by
    the in-dispatch classifier self-test. The red-before leg's REAL replay deadline-kill path no
    longer calls this function for its timeout arm -- it sets TIMEOUT_OUTCOME directly (rec-3835);
    this function's own timed_out branch stays, since the self-test fixture below still exercises
    it (docs/contracts/vp-red-before.yaml's replay_bound.kill)."""
    if timed_out:
        return TIMEOUT_OUTCOME
    if returncode == 0:
        return "tautological"
    if unmeasurable_arm(command, returncode, combined_output) is not None:
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


def _segment_invokes_scripts_validate(tokens: list[str]) -> bool:
    for i in range(len(tokens) - 1):
        if tokens[i] == "-m" and tokens[i + 1] == _SCRIPTS_VALIDATE_MODULE:
            return True
    if not tokens:
        return False
    head = tokens[0]
    if head == _SCRIPTS_VALIDATE_SCRIPT_PATH or head.endswith("/" + _SCRIPTS_VALIDATE_SCRIPT_PATH):
        return True
    head_base = head.rsplit("/", 1)[-1]
    if head_base in _PYTHON_INTERPRETER_BASENAMES and len(tokens) > 1:
        second = tokens[1]
        if second == _SCRIPTS_VALIDATE_SCRIPT_PATH or second.endswith("/" + _SCRIPTS_VALIDATE_SCRIPT_PATH):
            return True
    return False


def _command_invokes_scripts_validate(command: str) -> bool:
    """True iff ``command``'s argv head, in any shell segment, dispatches ``scripts.validate`` --
    an ``-m scripts.validate`` module-flag pair, or ``scripts/validate.py`` used as the executed
    program (never a bare substring match -- docs/contracts/vp-red-before.yaml's
    recursion_refusal names the 11 merged false-positive shapes this must not catch)."""
    return any(_segment_invokes_scripts_validate(segment.split()) for segment in _SHELL_SEGMENT_SPLIT_RE.split(command))
