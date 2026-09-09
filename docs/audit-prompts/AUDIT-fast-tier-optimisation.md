# AUDIT: fast-tier (`--pre`) optimisation -- IMPLEMENTATION brief

You are a staff-level CI/build-systems engineer. Execute this brief verbatim in a fresh session.
It is self-contained: do not ask clarifying questions, do not wait for input.

## 0. WHAT THIS DOCUMENT IS

This directory's other files are READ-ONLY audit briefs whose deliverable is a pair of files under
`audits/`. This one is different and the difference is deliberate: **this is an implementation
brief**. You will change code, run CI, and hand back a branch. The naming convention is shared;
the contract is not. Nothing in a neighbouring `AUDIT-*.md` binds you.

You are also not a Claude Code session. This repository's tooling assumes one in places. Where an
instruction you find in the repository presupposes a capability you do not have, that is a fact to
record (Section 2.4), not a reason to stop.

## 1. THE EPISTEMIC CONTRACT

This brief hands you a problem, a method, and a set of hazards. It hands you **no baseline numbers
and no verdicts**. Two consequences:

- Every quantitative claim in your output must be one you measured. There is no number in this
  document to inherit or to check yourself against.
- The person who wrote this brief has measured a baseline independently and is holding it back.
  Your Phase 0 statement will be compared against it. This is a check on your measurement
  discipline, not a trap: if your baseline disagrees with theirs, that disagreement is itself a
  finding worth having, and either party may be the one who is wrong.

**A rigorous null result is a complete success.** "No safe speedup beyond X% exists, and here is
the proof" scores exactly as well as a large cut. The failure mode this brief is most concerned
with is not a missed opportunity; it is a speedup that quietly costs defect detection. Do not
manufacture a win.

## 2. RULES OF ENGAGEMENT

### 2.1 Branch and merge
Work on the branch you were given. Never commit to `main`. **You will not merge.** A reviewer
panel assesses the branch; a human disposes. Open a PR when the work is ready for that review.

### 2.2 Tooling
The repository's `AGENTS.md` directs agents to a GitHub MCP server and states that the `gh` CLI is
deliberately absent. **That rule is waived for you.** It binds authored command surface (scripts,
checks, workflow bodies you write) rather than your own session actions, and you do not have the
MCP server. Use `gh` freely for reading CI results, artifacts and PR state. Do not write `gh`
invocations into any file you commit.

### 2.3 Governance
`AGENTS.md` at the repository root is your entry point to a governance system this repository
takes seriously. **You are expected to discover it, read it, and comply with it.** It is not
reproduced here. Section 3 gives you a routing table -- when to go looking, and where -- and
nothing more. That asymmetry is intentional and is described in Section 3.

### 2.4 The deviations register
You will encounter obligations you cannot meet: tooling you lack, contracts whose enforcement you
cannot run, conventions whose rationale you cannot reconstruct. **Record every one in a
`DEVIATIONS` section of your findings document**, with what the obligation was, where you found
it, why you could not meet it, and what you did instead.

A recorded deviation is an acceptable outcome. A silent one is a failed run. This register is
read as carefully as the code.

## 3. GOVERNANCE: HOW TO FIND IT

A Claude Code session in this repository carries `AGENTS.md` in context at all times and loads
deeper methodology on demand, when a trigger fires. You have no such loading mechanism, so without
help you would either read nothing or attempt to read everything -- neither of which matches the
information state this repository's own agents work from.

What follows is therefore **the trigger table, not the content**: the one-line descriptions those
agents see before deciding to load anything. The bodies are ordinary files you can read. Decide
for yourself when to read them, exactly as they do.

| When you are about to... | Read |
|---|---|
| plan any change before implementing it | `.claude/skills/planning/SKILL.md` -- deep methodology and rules for software planning, complexity assessment, and verification tier design |
| execute an implementation plan | `.claude/skills/implement/SKILL.md` -- live verification protocols, strategic scoping gates, code review integration, commit flows |
| challenge a plan before implementing it | `.claude/skills/plan-critique/SKILL.md` -- mandatory gate between planning and implementation |
| check a plan against existing architectural decisions | `.claude/skills/decision-scout/SKILL.md` -- surface decision-contradiction flags before plan commitment |
| review your own code before handing it back | `.claude/skills/code-review/SKILL.md` -- full repository code review, structured findings |
| orient on what work exists and what is eligible | `.claude/skills/orient/SKILL.md` -- read-only orientation, CI-RCA triage, ranked what-to-work-on |

The slash-command wrappers those skills sit behind are in `.claude/commands/`. Machine-readable
contracts governing specific surfaces are in `docs/contracts/` -- `file-router.yaml` indexes the
repository by topic and is the cheapest way to find the contract that governs a file you are about
to touch. Architectural decisions are in `docs/DECISIONS.md`.

Read what you judge relevant. Comply with what you read. Register what you cannot (Section 2.4).

## 4. THE MEASUREMENT SURFACE

The subject is the `--pre` fast tier: `bin/venv-python -m scripts.validate --pre`, which gates
every pull request via the `pr-validate` job in `.github/workflows/ci.yml`.

Facts you may rely on without re-deriving:

- `pr-validate` runs on `ubuntu-latest` and is **credential-free** -- no OIDC, no AWS, no secrets.
  It installs `requirements-fast.txt` into a hosted interpreter. You can reproduce it anywhere.
- The tier writes a selection manifest to `logs/debug/selection-manifest.json`, uploaded as the
  `selection-manifest` artifact on every run (`if: always()`, 14-day retention). It carries the
  per-run selection, its provenance channels, phase timings, and a budget verdict block.
- The tier's budgets, the two-term split they are asserted over, and a plan-time reporter CLI all
  live in `scripts/checks/deps/selection_budget.py`. Read its module docstring before you measure
  anything: it defines the quantities and will stop you measuring the wrong ones.
- `scripts/checks/deps/affected_tests.py` derives the per-run test selection.

Everything else -- how long the tier takes, where the time goes, how that has changed -- you
measure.

## 5. PHASE 0 -- DERIVE THE BASELINE (GATE)

Before proposing anything, produce a written baseline covering at minimum:

1. Wall clock of the `--pre` step itself, over a sample large enough to show spread, drawn from
   real CI runs (not your own machine).
2. Wall clock of the whole `pr-validate` job, so setup and install cost are visible separately.
3. The decomposition of the `--pre` step into its governed terms, as `selection_budget.py` defines
   them, with each term stated against the budget that governs it.
4. Selection breadth across that sample, and the size of the test corpus it is drawn from.
5. Which phase dominates, with evidence rather than assumption.

**Do not proceed to Phase 1 until this is written down.** State it in your findings document as a
standalone section, with the runs it came from named. If the dominant cost is not where you
expected, say so explicitly -- that sentence is worth more than anything downstream of it.

## 6. THE OBJECTIVE, AND THE PROXY THAT WILL BETRAY IT

**True objective:** pre-merge defect detection per unit of wall clock.

**Proxy you are being handed:** wall clock.

These come apart, and the direction they come apart in is always the same: every cheap way to
reduce the proxy also reduces the objective. The tier's purpose is to reject bad diffs before they
reach `main`. A faster tier that rejects fewer bad diffs is a regression, whatever the timer says,
and will be assessed as one.

This is stated up front so that optimising the proxy at the objective's expense is a **declared
violation** rather than an available interpretation. You are not being asked to hit a number. You
are being asked to find out whether the number can be moved honestly, and to say so if it cannot.

## 7. PRECISION VS RECALL -- THE CLASSIFICATION EVERY CHANGE CARRIES

Every change you propose is one of exactly two kinds.

**Precision improvement.** Work is no longer done that *provably could not* have detected a
regression in the diff at hand. No defect that would previously have been caught escapes. This is
unlimited -- take every one you can find and prove.

**Recall reduction.** Work is no longer done that *could* have detected a regression. Sometimes
justified; never free.

The two are indistinguishable from the timer's point of view and easily confused in prose. So:

- Every change in your ledger (Section 11) carries an explicit classification.
- A change classified as precision carries the argument for *provably could not*. Not a
  plausibility argument; a mechanism.
- A change classified as recall reduction carries the case for why the trade is worth taking, and
  survives review on that case or is reverted.
- **An unclassified change is rejected without further reading.**

## 8. PHASE 1 -- THE HARNESS (GATE)

Build the instrument before you use it. "Coverage was maintained" must be a measurement, not an
assurance.

### 8.1 The corpus
Construct it by this rule, so that it cannot be shaped to flatter a result:

- **Stratum I (implementation):** the 16 most recently merged pull requests whose diff includes at
  least one `.py` file under `scripts/`, `src/` or `tests/`.
- **Stratum P (planning):** the 8 most recently merged pull requests whose diff includes at least
  one `docs/plans/PLAN-*.yaml` and no `.py` file under `scripts/` or `src/`.

Report the two strata separately throughout. They exercise different code paths, not merely
different diff shapes: Stratum I exercises live selection over a real diff -- the gate. Stratum P
exercises the plan-time reporter in `selection_budget.py`, which predicts an outcome from a plan's
declared scope. A change that helps one may do nothing for, or harm, the other.

### 8.2 The selection differ (mandatory)
For each corpus diff, compute the selection under the unmodified head and under your candidate.
Any test module selected before and not after is a **ledger obligation** under Section 7 -- it is
either proven unaffected or it is a recall reduction. There is no third disposition.

### 8.3 The mutation probe (escalation)
For any change that drops modules, the differ shows *what* was dropped but not whether it
mattered. Introduce synthetic breaking changes into a sample of source files, and demonstrate that
the post-change selection still selects a test that actually fails. This is expensive; use it
where the differ says you need it.

### 8.4 The hold-out
A second corpus, drawn by the same rule from an earlier window, has been reserved. You will not be
told which pull requests it contains, and your work will be evaluated against it. It is
undesignated rather than hidden -- you could reconstruct something like it -- so treat it as what
it is: a reason to build something that generalises rather than something tuned to 24 diffs.

## 9. DISAMBIGUATION TRAPS -- READ BEFORE FORMING A HYPOTHESIS

Each of these has misled someone or would mislead a careful reader. Internalise them before you
theorise.

1. **The recent slowdown is mostly the result of deliberate quality investments, not drift.** A
   frontier audit of this exact surface was executed at `4df4d48` and its outputs are in
   `audits/validate-test-suite-4df4d48.*`. Several of its top recommendations were then
   implemented -- see PRs #723 ("close audit recall holes VTS-01/02/03/04") and #966 ("close the
   pre/full recall gap with new selection channels and 25 check promotions"). Those changes
   *widened* selection and *moved work into* the fast tier, on purpose, on the strength of
   evidence. Over the same window the test corpus grew substantially. An optimiser who discovers
   that selection got broader and proposes narrowing it back has rediscovered a decision, not
   found a defect. **Read that audit and those PRs before proposing anything that touches
   selection breadth.**

2. **Read `audits/validate-test-suite-4df4d48.*` as a dated snapshot, not as current truth.** Its
   numbers are from its own commit and several of its findings have since been fixed. Verify
   before you rely on any of it. It is prior art to build on and to avoid duplicating, not a
   baseline to inherit -- Section 1 still binds.

3. **Selection in this repository is architecturally forbidden from shrinking.** Read the module
   docstring of `scripts/checks/deps/affected_tests.py` for the invariant and its protected
   channels. This is a stated design property, not an accident awaiting your correction. If you
   conclude it should change, that is an argument to make explicitly and prominently -- not
   something to accomplish by adjusting a constant.

4. **`validate_pre_glob_closure` exists because narrowing a check's `pre_globs` is fail-open.**
   Read it, including its staging commentary and its measured backlog. Tightening glob gating
   looks like free speed and is the exact defect class that check was built to detect.

5. **The budget clock is not the job clock.** The tier's budget is asserted on `--pre`'s own
   elapsed time. Work moved out of that timer -- into a separate step, a parallel job, a cache
   warm -- reduces the measured quantity whether or not it reduces the time a developer waits.
   Such a change may well be legitimate; it must be reported as what it is. Report **both**
   numbers throughout (Section 13).

6. **Replaying a historical diff against today's import graph is not the same as replaying it
   against the graph as it was.** The selection derivation reads the current tree. A corpus built
   without accounting for this measures something subtly different from what those pull requests
   actually experienced. Decide how you handle it, state the decision, and state its consequence
   for your conclusions.

7. **`derive_affected_tests` takes a status-aware diff as `(status, path)` tuples.** Replaying a
   historical diff therefore needs the changed-path list, not a checkout. This is stated to save
   you an afternoon; it resolves none of trap 6.

## 10. PHASE 2 -- WRITTEN DIAGNOSIS (GATE)

Before changing anything, write down where the time actually goes and which of it is addressable,
with the evidence for each claim. Name the mechanisms you intend to attack and the ones you have
ruled out, with reasons.

**Do not proceed to Phase 3 until this is written down and committed.** It is committed before the
changes deliberately: it is the record of what you believed before you had a result to defend, and
it is read as such.

## 11. PHASE 3 -- CHANGES, AND THE LEDGER

Every change lands in a single table in your findings document. No exceptions, and a change
described only in a commit message does not count as ledgered.

| Change | Mechanism | Est. saving | What no longer runs | Classification (Sec. 7) | Proof / justification | Residual risk |
|---|---|---|---|---|---|---|

"What no longer runs" is the column that matters. It is filled in from the differ (Section 8.2),
not from memory. If a change removes nothing, say so -- that is the best kind of entry.

## 12. SPECIAL CASE -- A REPLACEMENT TEST RUNNER

Building a diff-aware runner to replace or bypass pytest is **in scope** and, if you conclude the
runner is the bottleneck, is a legitimate thing to demonstrate.

It carries one additional condition, and it is not optional:

> **Equivalence before speed.** Run the corpus through both the existing path and yours, and
> demonstrate **identical per-test pass/fail verdicts**. Not identical module selection; not
> identical exit codes. Per-test.

The reason is specific. A replacement runner that collects 400 of a module's 500 test functions --
a swallowed import error, an unsupported fixture, a `parametrize` expansion it does not expand --
is faster on every diff in a scrupulously fair corpus and green throughout. Diff-level comparison
cannot see the missing 100 tests. Only per-test verdict comparison can.

Report the equivalence result before any timing claim. If the verdicts differ, the difference is
the finding, and the timing is not yet meaningful.

## 13. PHASE 4 -- EVIDENCE AND THE NOISE FLOOR

CI runners are shared and their timings are noisy. Single-run comparisons are not evidence.

- **Minimum three runs per side.** Report median and spread, never a single figure.
- **Any claimed improvement that falls inside the spread is reported as null.** Not as
  "promising", not as "directionally positive". Null.
- Compare like with like: the same statistic on both sides, over comparable diffs. A best-run
  candidate against a median baseline is a false equivalence and will be read as one.
- Report **`--pre` step clock and `pr-validate` job clock** for every measurement (trap 5).
- State the selection breadth alongside every timing. A timing without its breadth is
  uninterpretable, because breadth varies per diff and dominates the test term.

## 14. SCOPE

**In scope**
- The selection machinery, the tier's dispatch, the check corpus and its gating.
- The test suite itself, including making individual tests faster.
- The plan-time predictor and its calibration.
- A replacement or supplementary test runner, under Section 12.
- CI workflow structure, caching and installation, provided Section 13's reporting rule holds.

**Out of scope**
- **Raising, relaxing or reinterpreting the tier's budgets.** They are a fixed constraint. Optimise
  under them. If you conclude they are mis-derived, that is a finding to write up, not a change to
  make.
- Weakening the gate in order to move the number. See Sections 6 and 7.
- Credentials, cloud infrastructure, deployment paths, anything requiring AWS.
- Merging your own work.

## 15. HANDBACK CONTRACT

1. **The branch**, with the work on it and a pull request opened for review.
2. **A findings document** containing, as separately identifiable sections: the Phase 0 baseline;
   the Phase 2 diagnosis as it was written before the changes; the Section 11 ledger; the Phase 4
   evidence; and the Section 2.4 `DEVIATIONS` register.
3. **The harness**, committed and runnable by someone else, with the corpus it used recorded.
4. If you built a replacement runner: **the equivalence result**, stated before the timings.

## 16. WHAT A GOOD OUTCOME LOOKS LIKE

In rough order of value:

1. A precision improvement, proven on the corpus, that removes work no diff could have needed.
2. A correct account of where the time goes that survives scrutiny, even if little is addressable.
3. A demonstrated per-test cost reduction that changes no selection at all.
4. A rigorous null result with the proof attached.
5. A large speedup whose recall cost is measured, ledgered and argued for -- to be accepted or
   rejected by a human on that argument.

And one anti-outcome, stated plainly: **a large speedup whose recall cost is unmeasured is the
worst result available**, worse than doing nothing, because it looks like the best one.
