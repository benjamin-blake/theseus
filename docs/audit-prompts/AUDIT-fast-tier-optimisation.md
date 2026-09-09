# AUDIT: fast-tier (`--pre`) optimisation -- IMPLEMENTATION brief

You are a staff-level CI/build-systems engineer. Execute this brief verbatim in a fresh session.
It is self-contained: do not ask clarifying questions, do not wait for input.

## 0. WHAT THIS DOCUMENT IS

This directory's other files are READ-ONLY audit briefs whose deliverable is a pair of files under
`audits/`. This one is different and the difference is deliberate: **this is an implementation
brief**. You will change code, run CI, and hand back a branch. The naming convention is shared;
the contract is not. Nothing in a neighbouring `AUDIT-*.md` binds you.

You are also not a Claude Code session. This repository's tooling assumes one in places. Where an
instruction presupposes a capability you lack, that is a fact to record (Section 2.4), not a reason
to stop. **A slash command is a prompt, not a capability**: `/plan` names a methodology you can read
and follow by hand. Lacking the invocation mechanism is not licence to skip the methodology.

## 1. THE EPISTEMIC CONTRACT

This brief hands you a problem, a method, and a set of hazards. It hands you **no baseline numbers
and no verdicts**. Every quantitative claim in your output must be one you measured; there is no
number here to inherit.

A baseline has been measured independently and is held back. Your Phase 0 statement will be
compared against it at the Section 5 checkpoint. This is a check on measurement discipline, not a
trap: a disagreement is a finding worth having, and either party may be the one who is wrong.

**A rigorous null result is a complete success.** "No safe speedup beyond X% exists, and here is
the proof" is worth exactly as much as a large cut. The failure mode this brief is most concerned
with is not a missed opportunity; it is a speedup that quietly costs defect detection. Do not
manufacture a win.

## 2. RULES OF ENGAGEMENT

### 2.1 Branch and merge
Work on the branch you were given. Never commit to `main`. **You will not merge.** A reviewer panel
assesses the branch; a human disposes.

### 2.2 Tooling
`AGENTS.md` directs agents to a GitHub MCP server and states the `gh` CLI is deliberately absent.
**That is waived for you** -- you do not have the MCP server. Use `gh` freely.

The repository's actual norm is narrower than a blanket ban: `ci.yml` itself shells `gh pr comment`.
Do not introduce `gh` into `scripts/`, `scripts/checks/`, or verification-plan command strings,
where the MCP-first rule genuinely binds. Workflow YAML already uses it.

### 2.3 Governance
`AGENTS.md` at the repository root is your entry point to a governance system this repository takes
seriously. **You are expected to discover it, read it, and comply with it.** It is not reproduced
here. Section 3 gives you a routing table and nothing more; that asymmetry is explained there.

### 2.4 The deviations register
You will meet obligations you cannot satisfy. Record every one in a `DEVIATIONS` section, split
into two classes that are read very differently:

- **Capability deviations** -- you structurally could not (no subagent, no AWS profile, no MCP
  server). Expected; not a mark against you.
- **Judgment deviations** -- you could have and chose not to, with your reasoning.

A recorded deviation is an acceptable outcome. A silent one is a failed run.

## 3. GOVERNANCE: HOW TO FIND IT

A Claude Code session carries `AGENTS.md` in context at all times, has the nearest `CLAUDE.md`
injected as it moves through the tree, and loads deeper methodology on demand when a trigger fires.
You have no such mechanism, so unaided you would read nothing or attempt everything -- neither
matching the information state this repository's own agents work from.

What follows is **the trigger table, not the content**: the one-line descriptions those agents see
before deciding to load anything. The bodies are ordinary files. Decide for yourself when to read.

| When you are about to... | Read |
|---|---|
| edit any file | the nearest `CLAUDE.md` up the tree (11 exist; `scripts/CLAUDE.md` carries placement rules and how to add a `validate.py` check -- both load-bearing here) |
| plan a change before implementing it | `.claude/skills/planning/SKILL.md` -- planning methodology, complexity assessment, verification tier design |
| execute an implementation plan | `.claude/skills/implement/SKILL.md` -- live verification protocols, scoping gates, commit flows |
| challenge a plan before implementing | `.claude/skills/plan-critique/SKILL.md` -- mandatory gate between planning and implementation |
| check a plan against existing decisions | `.claude/skills/decision-scout/SKILL.md` (presupposes a subagent you lack -- read and apply by hand) |
| review your own code before handback | `.claude/skills/code-review/SKILL.md` -- structured findings |

Slash-command wrappers are in `.claude/commands/`. Machine-readable contracts are in
`docs/contracts/`; `file-router.yaml` indexes the repository by topic and is the cheapest way to
find the contract governing a file you are about to touch. Decisions are in `docs/DECISIONS.md`.

Two capability notes, so they cost you minutes rather than hours: anything routing through
`scripts/ops_data_portal.py` (`file_rec`, `update_rec`) needs an AWS profile you do not have, and
several skills assume fresh-context subagents. Both are capability deviations (Section 2.4).

## 4. THE MEASUREMENT SURFACE

The subject is `bin/venv-python -m scripts.validate --pre`, which gates every pull request via the
`pr-validate` job in `.github/workflows/ci.yml`.

Facts you may rely on without re-deriving:

- `pr-validate` runs on `ubuntu-latest` and is **credential-free** -- no OIDC, no AWS, no secrets.
  It installs `requirements-fast.txt` and `requirements-dev.txt` into a hosted interpreter, so you
  can reproduce it anywhere.
- The job sets `concurrency: cancel-in-progress`. Repeat runs on one SHA must be `gh run rerun`;
  pushing again cancels the run you were measuring.
- The tier writes `logs/debug/selection-manifest.json`, uploaded as the `selection-manifest`
  artifact on every run (`if: always()`, 14-day retention). Its `budget` block carries
  `static_s`, `test_s`, `replay_s`, `unattributed_s` and `n_selected`. Its `phase_times` keeps
  **only the 10 slowest phases**, so per-check attribution must come from the step log.
- Budgets, the two-term split, and a plan-time reporter CLI live in
  `scripts/checks/deps/selection_budget.py`. Read its module docstring before measuring anything.
- `scripts/checks/deps/affected_tests.py` derives the per-run selection.
- `scripts/checks/_pytest_diff.py` decides what of that selection actually **executes**. Read it
  early; Section 8 depends on the distinction.

Everything else you measure.

## 5. PHASE 0 -- BASELINE, AND THE CHECKPOINT

Produce a written baseline covering:

1. `--pre` step wall clock, from at least 10 `pr-validate` runs inside the 14-day artifact window
   plus as many step-log runs as you can reach. List run IDs. Report median, IQR, min, max.
2. Whole-`pr-validate` job clock, so setup and install are visible separately. Cold pip-cache runs
   are outliers; report them apart.
3. The decomposition into governed terms as `selection_budget.py` defines them, each stated against
   the budget that governs it.
4. Selection breadth across the sample, and the corpus size it is drawn from.
5. Which phase dominates, with evidence rather than assumption.

**Then open your pull request as a DRAFT with this baseline as its body, and continue working.**
Do not wait for a reply. This exists so a wrong baseline is caught after one phase rather than
after all the work. If the dominant cost is not where you expected, say so explicitly.

## 6. THE OBJECTIVE

**True objective: developer wait at constant recall.** The proxy you are handed is wall clock, and
every cheap way to reduce the proxy also reduces detection. A faster tier that rejects fewer bad
diffs is a regression whatever the timer says.

Note before you aim at anything: the tier is already *within* its budgets on recent runs. Budget
compliance is not the goal and `TEST_BASE_SECONDS` is not a target. Reducing real waiting is.

## 7. CLASSIFICATION -- EVERY CHANGE CARRIES ONE

Three classes, exhaustive. An unclassified change is rejected without further reading.

**Class 1 -- precision.** Work no longer done that *provably could not* have detected a regression
in the diff at hand. Unlimited; take every one you can prove. Accepted proof forms, and you need at
least one:
  (a) import-closure disjointness via `scripts.dependency_graph.import_subgraph` -- the same view
      `validate_pre_glob_closure` uses;
  (b) the check's declared **data** inputs disjoint from the diff. Most governance checks read YAML
      the import graph cannot see, so (a) alone is insufficient for them;
  (c) the Section 8.2 executed-set differ empty across the corpus.

**Class 2 -- identical work, lower cost.** The same assertions, cheaper: parallelism, caching,
fixture cost, process startup. Proof is an **identical executed node set, identical per-node
verdicts, and identical emitted artifacts**. This is the safest class and often the largest.

**Class 3 -- recall reduction.** Work no longer done that *could* have detected a regression.
Sometimes justified, never free: it carries the case for the trade and survives review on that case
or is reverted.

Classes 1 and 3 both require a filled "what no longer runs" ledger column. Class 2 requires proof
that the column is empty.

## 8. PHASE 1 -- THE HARNESS (GATE)

Build the instrument before you use it. "Coverage was maintained" must be a measurement.

### 8.1 Selection is not execution -- instrument the right stage
Three stages sit between the manifest and an assertion, and a differ at the wrong one certifies the
very moves this brief exists to prevent:

1. **Selection** -- `derive_affected_tests` produces `selected`.
2. **Execution** -- `run_pytest_diff` then runs a `--collect-only` partition that defers modules
   importing an excluded heavy dependency, plus a reactive per-file probe that defers more. The
   excluded set is derived at runtime as `requirements.txt - requirements-fast.txt`. Removing a
   package from `requirements-fast.txt` therefore defers every test importing it to post-merge --
   and a selection-level differ reads *identical*.
3. **Assertion** -- markers (`-m "not integration"`), `--deselect`, `collect_ignore`,
   `pytest_collection_modifyitems` and the test bodies themselves decide what is actually checked.
   None of it is visible at module granularity.

### 8.2 The executed-node differ (mandatory)
For each corpus diff, run the real `run_pytest_diff` path under the unmodified head and under your
candidate, capturing `--junitxml` (the tier does not emit it today; your harness adds it). Compare
over the **union** of node IDs, with `not-collected` and `deferred` as first-class verdicts
alongside pass and fail. Any node executed before and not after is a ledger obligation under
Section 7.

### 8.3 Test edits are their own class, and the mutation probe is mandatory for them
Section 14 puts making individual tests faster in scope. That is legitimate and potentially large,
and it is also the easiest way to weaken the suite while every differ reads clean. So: **any edit
under `tests/**` requires, per modified test, a named mutation of its subject that the original
caught, and a demonstration that the modified test still catches it.** Not escalation. Mandatory.

For non-test changes that drop nodes, the mutation probe remains the escalation instrument: inject
synthetic breaking changes into a sample of source files and show the post-change selection still
executes a test that fails.

### 8.4 The corpus
Pin a base SHA and record it -- merges move "most recently merged" under you.

- **Stratum I (implementation):** the 16 most recently merged PRs before that SHA whose diff
  includes at least one `.py` under `scripts/`, `src/` or `tests/`.
- **Stratum P (predictor calibration):** 8 **plan-to-implementation pairs**. A plan-only diff
  selects zero test modules by design (`docs/plans` is deliberately outside the glob-scanned dirs),
  so a plan diff compared against itself is vacuous. What is worth measuring is whether the
  plan-time reporter's prediction matched what the *implementation* PR that followed actually cost:
  compare its predicted range against that run's `budget.test_s` and `n_selected`.

Report the strata separately. They measure different things: Stratum I measures the gate, Stratum P
measures whether the advice given at planning time is true.

Diversity matters more than count here. `tests/checks/deps/affected_tests/` is the reference set of
diff shapes: `test_recall_channels.py` carries roughly one class per selection channel,
`test_conftest_subtree.py` the forcing cases, and `test_residue_budget.py` the cap and survival
behaviour. Cover the channels, not just the file count.

### 8.5 Hold-out
A second corpus drawn by the same rule from an earlier window is reserved and undesignated. Build
something that generalises.

## 9. DISAMBIGUATION TRAPS -- READ BEFORE FORMING A HYPOTHESIS

1. **The slowdown is mostly the price of deliberate recall investment.** A frontier audit of this
   surface was executed at `4df4d48` (`audits/validate-test-suite-4df4d48.*`) and its top
   recommendations were then implemented -- see PRs #723 and #966. Over the same window the test
   corpus grew substantially. The material cost is **selection breadth and corpus growth**: #966's
   own body measures its 25 check promotions at **+1.56s aggregate**, so demoting checks back to
   the full tier buys about a second and a half at real recall cost. Read that audit and those PRs
   before proposing anything touching selection breadth. An optimiser who narrows selection back
   has rediscovered a decision, not found a defect.

2. **Read `audits/validate-test-suite-4df4d48.*` as a dated snapshot.** Several findings have since
   been fixed. Verify before relying on any of it. Prior art to build on, not a baseline to inherit.

3. **The selection invariant, precisely.** Protected channels are never deferred; only the
   transitive import-closure residue is capped, and overflow is deferred **loudly**, never dropped
   silently -- on a real recent diff the derivation selected 149 modules and loudly deferred 192 of
   288 transitive candidates, so you will see deferral and it is not a bug. `CAP = 35` is a
   Decision-135 constant. The derivation is also deliberately **cacheless**; introducing a
   persisted graph or selection cache is a Decision-level change, not an optimisation.

4. **`validate_pre_glob_closure` exists because narrowing `pre_globs` is fail-open.** Read it,
   including its staging commentary and measured backlog. Tightening glob gating looks like free
   speed and is the exact defect class it was built to detect.

5. **The budget clock is not the job clock, and the split assumes serial phases.** `non_test_s` is
   computed as `elapsed - test_s`. The pre-sequence runs the static checks *after* `pytest_diff`,
   so running them concurrently with pytest would hide the entire static half under the test half
   and drive `non_test_s` toward zero -- making the unwaivable 240s budget vacuous without touching
   a constant. That is reinterpreting the budget, which Section 14 puts out of scope. Concurrency
   is permitted **only** if per-term critical-path accounting is preserved and you demonstrate,
   with a synthetic 300s sleep injected into one static check, that `non_test_breach` still fires.
   Separately, work moved out of the timer entirely (a parallel job, a cache warm) may be
   legitimate but must be declared as such, with both clocks reported.

6. **Replaying a historical diff against today's tree is not replaying it against the tree as it
   was.** `repo_root` is threaded through every channel including the mirror map, so
   `git worktree add <merge-parent>` plus `repo_root=` replays against the historical tree. Note
   also that `derive_affected_tests` takes a status-aware diff as `(status, path)` tuples, so a
   replay needs the changed-path list rather than a checkout. Decide your approach, state it, and
   state its consequence for your conclusions.

7. **Pinning tests are obligations, not walls.** You will hit the frozen pre-sequence order test,
   `validate_hermeticity_flags` (which pins `_PYTEST_FLAGS` and the seed), per-domain manifest tier
   pins, `validate_actions_evidence` (every `upload-artifact` step needs a contract row), and
   Decision 170 accounting for any new check. A pin is updated in the same ledgered commit as the
   change it guards -- never deleted, never routed around.

## 10. PHASES 2 AND 3 -- DIAGNOSIS, THEN CHANGES

Before changing anything, **commit** a written diagnosis of where the time goes and which of it is
addressable, naming the mechanisms you intend to attack and those you have ruled out, with reasons.
It is committed before the changes deliberately: it records what you believed before you had a
result to defend.

Then every change lands in one table. A change described only in a commit message is not ledgered.

| Change | Class (Sec. 7) | Mechanism | Est. saving | What no longer runs | What is no longer produced | Proof | Residual risk |
|---|---|---|---|---|---|---|---|

"What no longer runs" is filled from the executed-node differ, not from memory. "What is no longer
produced" catches a distinct failure: `logs/debug/diff-coverage.json` and the deferral map feed
`validate_diff_coverage`, and `-v` output is parsed by `_attribute_failed_test_files` and by
ci-rca. Dropping `--cov` or `-v` looks like a precision win and breaks a downstream consumer.

## 11. SPECIAL CASE -- A REPLACEMENT TEST RUNNER

Building a diff-aware runner to replace or bypass pytest is **in scope** and, if you conclude the
runner is the bottleneck, is a legitimate thing to demonstrate.

> **Equivalence before speed.** Run the corpus through both paths and demonstrate **identical
> per-test pass/fail verdicts** over the union of node IDs. Not identical module selection; not
> identical exit codes. Per-node.

A replacement runner that collects 400 of a module's 500 test functions -- a swallowed import
error, an unsupported fixture, an unexpanded `parametrize` -- is faster on every diff in a
scrupulously fair corpus and green throughout. Only per-node comparison sees the missing 100.

To be equivalent it must reproduce at minimum: the 9 autouse fixtures in `tests/conftest.py`,
`--disable-socket`, the `_VALIDATE_DEPTH` recursion guard, `-m "not integration"`, the heavy-dep
partition and its deferral map, a fixed seed under xdist, `--timeout 60`, and the coverage artifact.

Report equivalence before any timing claim. If verdicts differ, that difference is the finding.

## 12. PHASE 4 -- EVIDENCE AND THE NOISE FLOOR

- **CI aggregate comparisons: 3-5 runs per side**, median and spread. Use the Phase 0 historical
  population for baseline spread rather than three fresh runs.
- **Any claimed improvement inside the spread is reported as null.** Not "promising", not
  "directionally positive". Null.
- **Per-change attribution is local A/B on one machine** -- that is the right instrument for
  isolating one mechanism, and it is exempt from the CI-only rule that binds Phase 0. Say which
  numbers are which.
- Compare like with like. A best-run candidate against a median baseline is a false equivalence.
- Report both `--pre` step clock and `pr-validate` job clock (trap 5).
- State selection breadth alongside every timing. Breadth varies per diff and dominates the test
  term, so a timing without it is uninterpretable.

## 13. SCOPE

**In scope:** the selection machinery; the tier's dispatch and check corpus; the test suite,
including making individual tests faster (under 8.3); the plan-time predictor and its calibration;
a replacement runner (under Section 11); CI workflow structure, caching and installation.

**Out of scope:**
- **Raising, relaxing or reinterpreting the budgets.** Fixed constraints -- optimise under them.
  Trap 5's concurrency variant is a reinterpretation. If you think they are mis-derived, write it
  up; do not act on it.
- Weakening the gate to move the number (Sections 6 and 7).
- Credentials, cloud infrastructure, deployment paths, anything requiring AWS.
- Merging your own work.

## 14. HANDBACK

1. **The branch**, with the PR promoted from draft to ready.
2. **A findings document** at `audits/fast-tier-optimisation-<sha>.md`, containing as separately
   identifiable sections: the Phase 0 baseline; the Phase 2 diagnosis as committed before the
   changes; the Section 10 ledger; the Phase 4 evidence; and the two-class `DEVIATIONS` register.
3. **The harness**, committed and runnable by someone else, with its corpus and base SHA recorded.
   Put it under `scripts/ci/` (exists) or alongside `scripts/checks/deps/`. Do not create new
   depth-1 files under `docs/` or `scripts/` -- both roots carry allowlists enforced by
   `validate_placement`, and a 500-SLOC-per-file limit applies.
4. If you built a replacement runner: **the equivalence result, stated before the timings.**

## 15. WHAT A GOOD OUTCOME LOOKS LIKE

These are of comparable value, not ranked:

- A precision improvement (class 1), proven on the corpus, removing work no diff could have needed.
- A class-2 cost reduction with identical executed nodes, verdicts and artifacts.
- A correct account of where the time goes that survives scrutiny, even if little is addressable.
- A rigorous null result. To count, it must state its **measured ceiling**: the largest change your
  harness rejected, and why it failed.
- A large speedup whose recall cost is measured, ledgered and argued -- for a human to accept or
  reject on that argument.

And one anti-outcome: **a large speedup whose recall cost is unmeasured is the worst result
available**, worse than doing nothing, because it looks like the best one.
