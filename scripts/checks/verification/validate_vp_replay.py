"""Interactive VP independent re-execution (T3.15 criterion c2, VF-01, Decision 148, re-keyed to
content resolution by the plan-resolution-content-keyed plan; the plan-only leg's polarity is
inverted by Decision 189 / rec-3770). Full outcome vocabulary, eligibility predicate, lint
scope/precedence, and recursion-refusal semantics live in docs/contracts/vp-red-before.yaml --
this module holds no second copy of that prose.

Closes the cooperative-self-evaluation gap named in VF-01: a PLAN-*.yaml's Verification Plan is
self-reported by the implementing agent. Two legs, run every dispatch:

  Implement leg: for every plan resolved by ``_common.resolve_declared_plans`` (content-keyed
    False->True ``implementation_declared`` flip), replay its hermetic pre-deploy steps
    GREEN-AFTER (exit 0 required; opt-in backtick-literal substring match against stdout+stderr;
    a TimeoutExpired always diverges) -- EXCEPT a PR-relative step whose base ref has collapsed
    (measured, never keyed on ``graduation``; see ``_partition_steps``), excluded with a reason.

  Plan-only leg (new, Decision 189): a diff-present plan not resolved by the implement leg still
    prints DEFER; when it is also ELIGIBLE (added in this diff AND ``implementation_declared``
    reads falsy), its ``graduation: graduate`` pre-deploy steps are additionally replayed
    RED-BEFORE -- classified into OUTCOME_CLASSES below, where ``tautological``/``unmeasurable``
    hard-fail and ``target_absent``/``assertion_failed`` pass -- and every pre-deploy step (any
    disposition) is statically linted for a negated-rg/grep absent-path sweep and a
    scripts.validate recursion refusal. A classifier self-test (one fixture per outcome class,
    including the timeout arm) runs unconditionally before any precondition early-return,
    appending to ``failed`` only -- never to ``examined()``.

Steps outside a leg's replay set (for the implement leg: not pre-deploy, or not hermetic) print
EXCLUDED with a reason, never silently skipped. A PLAN-*.yaml failing PlanDocument content
validation is skipped with a note (schema validity is validate_plan_documents' concern); an
``ImportError`` loading ``scripts.roadmap.plan_document`` reddens this check directly (Decision 55
fail-loud, mirrors validate_plan_documents.py's own ImportError/content-error split).

Advisory SKIP (never a failure): no plan in the diff is a no-op PASS (an empty domain, not a
skip); an unreachable origin/main DEFERs every diff-present plan and declares ``skipped``.

One terminal Decision 170 declaration per dispatch (docs/contracts/check-accounting.yaml): an
unreachable base declares ``skipped``; when no diff-present plan is red-before ELIGIBLE,
``examined(len(resolved), unit="declared_plans")`` (byte-identical to the pre-Decision-189 shape);
when at least one plan IS eligible, ``examined(len(resolved | acted_on),
unit="plans_acted_on")`` -- an eligible plan with zero graduate steps contributes nothing, so the
dispatch can still declare vacuous rather than misdescribing it as "declared".

Bounded cost: PER_STEP_TIMEOUT_SECONDS plus an aggregate wall-clock/step-count cap
(MAX_AGGREGATE_SECONDS / MAX_REPLAYED_STEPS), SHARED across both legs in one dispatch (Decision
73, Decision 182 pt 2) -- hitting the cap appends one budget-guard failure and stops replay for
BOTH legs, never a silent truncation. The classifier self-test adds its own small, unconditional,
measured ~0.06s floor (four near-instant fixtures plus one deliberate 0.05s timeout fixture) on
top of the existing 150s green maximum (Decision 182 pt 2), never folded into either budget
constant.

No network and no AWS calls are made BY THIS CHECK. The implement leg trusts the plan author's
``hermetic: true`` marker that a replayed command is creds-free and side-effect-free; the
red-before leg carries no such trust requirement -- it only ever replays a step BEFORE the
implementation exists, so a step needing real infrastructure is simply expected to fail loudly
there too (classified assertion_failed/target_absent/unmeasurable), never silently "worked".
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import yaml

from scripts.checks import _common, registry

PER_STEP_TIMEOUT_SECONDS = 30
MAX_AGGREGATE_SECONDS = 120
# Re-derived (rec-3770, Decision 189) so the 120s aggregate wall clock -- not an arbitrary step
# count -- is the binding constraint on a realistic multi-plan PR. Measured during this plan's
# own critique: per-step cost is 0.29-0.39s (stable) when the replayed target is ABSENT, but LIVE
# cost is step-dependent and ranged 0.8-4.6s (an outlier, not the typical case). A PR carrying two
# plans of this plan's own size (14 graduate steps each = 28) must not hard-fail on the COUNT cap
# under a realistic, non-worst-case step mix -- the old cap of 20 already fails that bar on its
# own (20 x 4.6s = 92s, a premature "budget exceeded" well under the real 120s ceiling). 30 clears
# 28 with headroom while staying close enough to floor(MAX_AGGREGATE_SECONDS /
# worst-measured-live-cost) = floor(120 / 4.6) = 26 that a genuinely pathological all-worst-case
# run (30 x 4.6s = 138s) still trips MAX_AGGREGATE_SECONDS, the true backstop, only a handful of
# steps later than the strict floor would -- never silently exceeding the fast-tier budget by a
# wide margin. MAX_AGGREGATE_SECONDS itself is unchanged (Decision 182 pt 2's 150s green maximum);
# this constant only stops the COUNT from being the artificial bottleneck it was before.
MAX_REPLAYED_STEPS = 30

_BACKTICK_LITERAL_RE = re.compile(r"`([^`]+)`")

# The FOUR frozen outcome classes (docs/contracts/vp-red-before.yaml derive-and-asserts equal to
# this tuple) -- never restated as a fifth class or split further.
OUTCOME_CLASSES: tuple[str, ...] = ("tautological", "target_absent", "assertion_failed", "unmeasurable")

# Genuinely used below (in the classifier self-test's fixture cwd resolution is NOT this -- see
# _run_classifier_self_test) so docs/contracts/vp-red-before.yaml's {check: validate_vp_replay}
# evaluator declaration resolves against THIS module (resolve_evaluator requires an
# executable-context literal, never a docstring mention).
_CONTRACT_BASENAME = "vp-red-before.yaml"

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

# Negated-sweep lint (docs/contracts/vp-red-before.yaml's negated_sweep_lint): a `! rg`/`! grep`
# invocation's tail, up to the next shell control operator. Fails OPEN (returns None -- never
# flagged) on anything but a confident two-token (PATTERN, PATH) parse with a plain,
# unquoted, metacharacter-free PATH token -- over-detection is the worse failure here.
_NEGATED_RG_GREP_RE = re.compile(r"!\s*(?:rg|grep)\b(?P<tail>[^&|;\n]*)")
_QUOTED_TOKEN_RE = re.compile(r"""^(?:"[^"]*"|'[^']*')$""")
_SAFE_PATH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./-]+$")

# scripts.validate recursion refusal (docs/contracts/vp-red-before.yaml's recursion_refusal):
# keyed on invocation SHAPE, never a bare substring -- see the module docstring and the contract
# for the 11 merged false-positive shapes this must not catch.
_SHELL_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|]")
_PYTHON_INTERPRETER_BASENAMES = frozenset({"python", "python3", "venv-python"})
_SCRIPTS_VALIDATE_SCRIPT_PATH = "scripts/validate.py"
_SCRIPTS_VALIDATE_MODULE = "scripts.validate"


class _ReplayBudget:
    """Cross-leg step-count/wall-clock accumulator shared by the implement leg and the
    red-before leg within ONE dispatch -- MAX_REPLAYED_STEPS/MAX_AGGREGATE_SECONDS govern the
    union of both legs' replayed steps, never each leg independently (docs/contracts/
    vp-red-before.yaml's shared-counter requirement)."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.count = 0
        self.hit = False

    def exhausted(self) -> bool:
        return self.hit or self.count >= MAX_REPLAYED_STEPS or self.elapsed >= MAX_AGGREGATE_SECONDS

    def spend(self, elapsed: float) -> None:
        self.elapsed += elapsed
        self.count += 1


# PR-relative authoring predicate (docs/contracts/vp-red-before.yaml's implement_leg_partition) --
# ADVISORY, never refuses: a false negative only skips the exclusion/lint for an unrecognised
# shape (76 merged steps use the origin/main diff idiom legitimately and must never be refused).
# Recognises both live shapes: `git diff origin/main -- <path>` and `git show origin/main:<path>`
# (PLAN-vp-red-before-gate.yaml step 16, the command behind rec-3845).
_PR_RELATIVE_RE = re.compile(r"\bgit\b.*?\b(?:diff|show)\b.*?\borigin/main\b", re.DOTALL)


def _is_pr_relative(command: str) -> bool:
    return bool(_PR_RELATIVE_RE.search(command))


def _base_ref_collapsed(root: Path) -> bool:
    """True iff HEAD is an ancestor of (or equal to) origin/main -- the post-merge condition
    under which a PR-relative step's origin/main comparison has become vacuous. Ancestry, never
    strict SHA equality: origin/main may have advanced past HEAD since the merge, and the step
    is still vacuous either way (rec-3845's own failure mode)."""
    result = _common.run(["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], capture_output=True, cwd=root)
    return result.returncode == 0


def _partition_steps(verification_plan, root: Path) -> tuple[list, list[tuple]]:
    """Split VP steps into (replay set, EXCLUDED set with reason) for the GREEN-AFTER (implement)
    leg only -- the red-before leg partitions by ``graduation`` instead (see ``_red_before_leg``).

    Phase eligibility is checked before hermetic eligibility: a post-deploy step is reported
    as "post-deploy" regardless of its hermetic marker (phase alone disqualifies it from
    replay), and "not-hermetic" is reserved for a pre-deploy step that isn't marked hermetic.
    A hermetic pre-deploy step whose command is PR-relative (``_is_pr_relative``) is additionally
    excluded, keyed on the MEASURED base-ref collapse (``_base_ref_collapsed``, cached at most
    once per call) -- never on ``graduation``, which stays untouched by this partition.
    """
    replay = []
    excluded = []
    collapsed: bool | None = None
    for step in verification_plan:
        if step.phase != "pre-deploy":
            excluded.append((step, "post-deploy"))
        elif not step.hermetic:
            excluded.append((step, "not-hermetic"))
        elif _is_pr_relative(step.command):
            if collapsed is None:
                collapsed = _base_ref_collapsed(root)
            if collapsed:
                excluded.append((step, "pr-relative-base-collapsed"))
            else:
                replay.append(step)
        else:
            replay.append(step)
    return replay, excluded


def _extract_literals(expected: str) -> list[str]:
    return _BACKTICK_LITERAL_RE.findall(expected)


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


def _added_plan_paths(root: Path) -> set[str]:
    """Diff-present docs/plans/PLAN-*.yaml paths ADDED (status "A" or "??") in this diff, per
    ``_common.get_status_aware_diff(root)`` -- the same added-in-diff population
    ``validate_plan_documents._added_plan_names`` already derives (there keyed on filename; here
    on the full repo-relative path, since every caller below loads the file at that exact path)."""
    return {
        path
        for status, path in _common.get_status_aware_diff(root)
        if status in ("A", "??") and _common.PLAN_PATH_RE.match(path)
    }


def _is_red_before_eligible(plan_rel: str, root: Path, added: set[str]) -> bool:
    """docs/contracts/vp-red-before.yaml's eligibility_predicate: added in this diff AND
    ``implementation_declared`` reads falsy in the CURRENT working tree. Both conjuncts are
    required -- never ``resolve_declared_plans``' edge trigger, and never
    ``implementation_declared`` alone (335 of 422 plans predate that field and read falsy
    forever)."""
    if plan_rel not in added:
        return False
    plan_path = root / plan_rel
    if not plan_path.exists():
        return False
    try:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return not (isinstance(data, dict) and data.get("implementation_declared"))


def _extract_negated_rg_grep_path(command: str) -> str | None:
    """Return the candidate absent-path argument of a negated ``! rg``/``! grep`` invocation in
    ``command``, or None if the command does not confidently parse as one (fail-open)."""
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


def _negated_sweep_findings(plan_rel: str, pre_deploy_steps: list, root: Path) -> dict[int, str]:
    """{step_number: finding} for every pre-deploy step (ANY disposition) whose command is a
    negated rg/grep naming an absent path -- the lint's distinct value over the dynamic leg,
    which only ever touches ``graduate`` steps."""
    findings: dict[int, str] = {}
    for step in pre_deploy_steps:
        path_tok = _extract_negated_rg_grep_path(step.command)
        if path_tok is None or (root / path_tok).exists():
            continue
        findings[step.step] = (
            f"vp-red-before-lint {plan_rel}:{step.step}: negated rg/grep names absent path {path_tok!r} -- "
            f"shell negation maps rg/grep's missing-path exit 2 to a false success (command={step.command!r})"
        )
    return findings


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


def _replay_step(
    plan_rel: str, step, root: Path, failed: list[str], *, expected_polarity: str = "green"
) -> tuple[float, str | None]:
    """Execute one VP step; append a divergence to failed[] if any.

    ``expected_polarity == "green"`` (the implement leg): the existing green-after contract --
    exit 0 required, opt-in backtick-literal substring match, TimeoutExpired always diverges.
    ``expected_polarity == "red"`` (the inverted plan-only leg, docs/contracts/vp-red-before.yaml):
    the step must classify as ``target_absent`` or ``assertion_failed``; ``tautological`` or
    ``unmeasurable`` diverge.

    Returns (elapsed wall-clock seconds, outcome classification -- None for the green polarity,
    always one of OUTCOME_CLASSES for the red polarity) -- the elapsed figure feeds the shared
    cross-leg aggregate budget guard, the outcome feeds the lint-precedence rule.
    """
    start = time.monotonic()
    try:
        result = subprocess.run(
            step.command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PER_STEP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        if expected_polarity == "green":
            failed.append(
                f"vp-replay {plan_rel}:{step.step}: actual=TIMEOUT after {PER_STEP_TIMEOUT_SECONDS}s "
                f"!= expected={step.expected!r}"
            )
            return elapsed, None
        outcome = _classify_outcome(step.command, None, "", timed_out=True)
        failed.append(
            f"vp-red-before {plan_rel}:{step.step}: actual={outcome} (TIMEOUT after {PER_STEP_TIMEOUT_SECONDS}s) "
            "-- unmeasurable is a hard failure, never counted as red"
        )
        return elapsed, outcome

    elapsed = time.monotonic() - start
    combined_output = result.stdout + result.stderr

    if expected_polarity == "green":
        if result.returncode != 0:
            failed.append(
                f"vp-replay {plan_rel}:{step.step}: actual=exit {result.returncode} "
                f"!= expected=exit 0 (expected={step.expected!r}; output tail={combined_output[-500:]!r})"
            )
            return elapsed, None
        missing = [lit for lit in _extract_literals(step.expected) if lit not in combined_output]
        if missing:
            failed.append(
                f"vp-replay {plan_rel}:{step.step}: actual=missing literal(s) {missing} "
                f"!= expected={step.expected!r} (output tail={combined_output[-500:]!r})"
            )
        else:
            print(f"  PASS: {plan_rel}:{step.step} replayed ({step.command[:80]})")
        return elapsed, None

    # Inverted (red) polarity from here.
    outcome = _classify_outcome(step.command, result.returncode, combined_output, timed_out=False)
    if outcome in ("tautological", "unmeasurable"):
        failed.append(
            f"vp-red-before {plan_rel}:{step.step}: actual={outcome} (exit {result.returncode}) -- a graduate "
            f"step must be genuinely red on the un-implemented tree (output tail={combined_output[-500:]!r})"
        )
    else:
        print(f"  PASS: {plan_rel}:{step.step} red-before ({outcome}, exit {result.returncode})")
    return elapsed, outcome


def _implement_pr_leg(root: Path, resolved: list[str], failed: list[str], budget: _ReplayBudget) -> None:
    """Replay every resolved plan's hermetic pre-deploy steps against the complete
    (implementation-bearing) tree. `resolved` is the content-keyed resolution from
    `_common.resolve_declared_plans` -- every path in it already exists on disk.
    """
    if not resolved:
        print("  PASS: no plan(s) with a newly-true implementation_declared in this diff -- no-op.")
        return

    replayed_count = 0
    plans_resolved = 0

    for plan_rel in resolved:
        try:
            doc = _common.load_plan(plan_rel, root)
        except ImportError as exc:
            failed.append(f"vp-replay {plan_rel}: could not import scripts.roadmap.plan_document: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP: {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

        plans_resolved += 1
        replay_steps, excluded_steps = _partition_steps(doc.verification_plan, root)

        for step, reason in excluded_steps:
            print(f"  EXCLUDED: {plan_rel}:{step.step} ({reason})")

        for step in replay_steps:
            if budget.exhausted():
                failed.append(
                    f"vp-replay: aggregate replay budget exceeded "
                    f"(steps={budget.count}, elapsed={budget.elapsed:.1f}s) -- stopping replay"
                )
                budget.hit = True
                break
            elapsed, _outcome = _replay_step(plan_rel, step, root, failed, expected_polarity="green")
            budget.spend(elapsed)
            replayed_count += 1

        if budget.hit:
            break

    if not any(f.startswith("vp-replay") for f in failed) and replayed_count:
        print(f"  PASS: {replayed_count} hermetic pre-deploy step(s) replayed clean across {plans_resolved} plan(s).")
    elif not replayed_count and not budget.hit and plans_resolved:
        print(f"  PASS: {plans_resolved} plan(s) resolved via implementation_declared, no hermetic step(s) to replay.")


def _compute_eligible_plans(plan_files: list[str], root: Path, resolved: set[str]) -> set[str]:
    added = _added_plan_paths(root)
    return {plan_rel for plan_rel in plan_files if plan_rel not in resolved and _is_red_before_eligible(plan_rel, root, added)}


def _red_before_leg(
    plan_files: list[str],
    root: Path,
    resolved: set[str],
    eligible: set[str],
    failed: list[str],
    budget: _ReplayBudget,
) -> set[str]:
    """Inverted-polarity plan-only leg (docs/contracts/vp-red-before.yaml). Every diff-present
    plan not already handled by the implement leg still prints the original DEFER line, unchanged
    -- a MODIFIED-not-added plan, or an added-but-already-declared-elsewhere plan, still defers
    with no execution. ADDITIONALLY, for every ELIGIBLE plan (``eligible``, precomputed by the
    caller): runs the static negated-sweep lint over every pre-deploy step (any disposition), the
    static scripts.validate recursion refusal over every ``graduate`` pre-deploy step, and -- for
    a graduate step that does not trip the recursion refusal -- the dynamic inverted-polarity
    replay, applying the lint-vs-tautology precedence rule (a tautological dynamic outcome
    suppresses that same step's lint finding).

    Returns the set of plan paths this leg genuinely replayed >=1 graduate step for -- the
    accounting-declaration "acted on" grain. An eligible plan with zero graduate pre-deploy steps
    contributes nothing here even though it was eligible.
    """
    acted_on: set[str] = set()

    for plan_rel in plan_files:
        if not (root / plan_rel).exists():
            print(f"  SKIP: {plan_rel} (not present on disk -- deleted in this diff)")
            continue
        if plan_rel in resolved:
            print(f"  PASS: {plan_rel} -- implementation_declared newly true in this diff; replayed by the implement leg.")
            continue

        print(
            f"  DEFER: {plan_rel} -- implementation_declared not newly true in this diff; replay deferred until "
            "the plan declares its implementation."
        )

        if plan_rel not in eligible:
            continue

        try:
            doc = _common.load_plan(plan_rel, root)
        except ImportError as exc:
            failed.append(f"vp-red-before {plan_rel}: could not import scripts.roadmap.plan_document: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 -- schema validity is validate_plan_documents' concern
            print(f"  SKIP: {plan_rel}: load error ({exc}) -- not double-reported here")
            continue

        pre_deploy_steps = [s for s in doc.verification_plan if s.phase == "pre-deploy"]
        lint_findings = _negated_sweep_findings(plan_rel, pre_deploy_steps, root)
        graduate_steps = [s for s in pre_deploy_steps if s.graduation == "graduate"]

        for step in graduate_steps:
            if _command_invokes_scripts_validate(step.command):
                failed.append(
                    f"vp-red-before-recursion {plan_rel}:{step.step}: graduate step invokes scripts.validate -- "
                    "refused statically before execution (recursion risk); disposition should be waive or not-applicable"
                )
                continue

            if budget.exhausted():
                failed.append(
                    f"vp-red-before: aggregate replay budget exceeded "
                    f"(steps={budget.count}, elapsed={budget.elapsed:.1f}s) -- stopping replay"
                )
                budget.hit = True
                break

            elapsed, outcome = _replay_step(plan_rel, step, root, failed, expected_polarity="red")
            budget.spend(elapsed)
            acted_on.add(plan_rel)
            if outcome == "tautological":
                lint_findings.pop(step.step, None)

        for step_number in sorted(lint_findings):
            failed.append(lint_findings[step_number])

        if budget.hit:
            break

    return acted_on


@registry.register("validate_vp_replay", owner="platform")
def validate_vp_replay(failed: list[str], changed_files: list[str] | None = None, root: Path | None = None) -> None:
    """Independently re-execute hermetic pre-deploy VP steps (implement leg, green-after) and,
    since Decision 189, dynamically red-before-gate an eligible plan-only PR's graduate pre-deploy
    steps (docs/contracts/vp-red-before.yaml) -- see the module docstring for the full two-leg
    contract.

    changed_files / root are test/dogfood injection seams -- default to
    _common.get_changed_files(root) (vs origin/main) and _common.ROOT respectively.

    Composes exactly ONE terminal Decision 170 declaration (docs/contracts/check-accounting.yaml)
    -- see the module docstring's accounting-declaration paragraph for the exact branch rule.
    """
    print("\n=== Interactive VP replay (T3.15 c2, VF-01; red-before gate, Decision 189/rec-3770) ===")
    root = root if root is not None else _common.ROOT
    _run_classifier_self_test(failed)

    changed = changed_files if changed_files is not None else _common.get_changed_files(root)

    plan_files = _common.plan_paths_from_changed(changed)
    if not plan_files:
        print("  PASS: no docs/plans/PLAN-*.yaml in the diff -- no-op.")
        registry.examined(0, unit="declared_plans")
        return

    if not _common.origin_main_reachable(root):
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI) -- deferring every in-diff plan.")
        for plan_rel in plan_files:
            print(f"  DEFER: {plan_rel} -- diff base unreachable.")
        registry.skipped("diff base unreachable")
        return

    base = _common.push_context_base(root) or "origin/main"
    resolved = _common.resolve_declared_plans(changed, root, base)
    resolved_set = set(resolved)
    eligible = _compute_eligible_plans(plan_files, root, resolved_set)

    budget = _ReplayBudget()
    _implement_pr_leg(root, resolved, failed, budget)
    acted_on = _red_before_leg(plan_files, root, resolved_set, eligible, failed, budget)

    if not eligible:
        registry.examined(len(resolved), unit="declared_plans")
    else:
        registry.examined(len(resolved_set | acted_on), unit="plans_acted_on")
