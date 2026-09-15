# Fast-tier optimisation findings at 3560909

Base SHA: `35609091fd8482d3116e4b360c6ec2bc9ab25b90`

## Established context

- The working branch is `claude/fast-tier-optimisation`. It was rebased onto `origin/main` at
  `a740b93` before Phase 1 began and at `6b6df4d` before Phase 2 began. The audit base remains pinned at
  `35609091fd8482d3116e4b360c6ec2bc9ab25b90`; rebasing the working branch does not move the corpus.
- This file is the cross-session state file. The committed Phase 0 section is complete and
  authoritative, so later phases must not re-derive, re-measure or re-verify it. Each phase ends in
  a commit pushed to draft PR #1131, and a session assigned one phase stops at that checkpoint.
- Root `AGENTS.md`, `scripts/CLAUDE.md`, `tests/CLAUDE.md`, `docs/contracts/git-ops.yaml`, and the
  audit brief bind this work. In particular: use `bin/venv-python`; keep public-repository data free
  of credentials and operational identifiers; place the standalone harness below
  `scripts/checks/deps/` with a mirrored test; keep it out of the registered validation-check
  surfaces; remain within the 500-SLOC limit; and add an automated test for every behavior change.
- The pre-commit hook is installed. The repository Python 3.12 environment works, and the harness
  builds content-addressed environments from each replay tree's `requirements-fast.txt` and
  `requirements-dev.txt` to reproduce the dependency boundary of `pr-validate`. GitHub PR,
  workflow and artifact reads worked through the GitHub MCP surface; Phase 1 required no AWS
  access.
- The Phase 1 corpus and its SHA evidence live in
  `scripts/checks/deps/fast_tier_corpus.yaml`. Stratum I is the 16 most recent first-parent merged
  PRs strictly before the pinned base whose diff contains Python below `scripts/`, `src/` or
  `tests/`. Stratum P is eight plan-to-implementation pairs with the plan-time prediction and the
  implementation run's archived `budget.test_s` and `n_selected` recorded separately.
- Historical replay means the pinned PR diff is applied to a worktree at that PR's merge parent,
  then passed as status/path tuples to that tree's selector. Replaying the same paths against the
  current tree is explicitly not equivalent. The harness invokes that tree's real
  `run_pytest_diff`, adds JUnit and native node-ID capture externally, and compares the union with
  `deferred` and `not-collected` as distinct verdicts.
- The mutation probe is not a Phase 1 deliverable. Section 8.3 defers it until a candidate first
  edits a test or drops an executed node. Phase 1 contains no performance diagnosis and changes no
  fast-tier behavior.
- The Phase 0 capability deviation remains durable context: the `agent_platform` AWS assume-role
  chain was unavailable. AWS and warehouse operations remain out of scope, and no Phase 1 evidence
  depends on them.

## Phase 0 baseline

The baseline uses 13 implementation-oriented `pr-validate` runs from 2026-09-07 through
2026-09-10. Every run has a live `selection-manifest` artifact and a reachable job log. Ten runs
passed and three reached the fast-tier step before failing. Quantiles use linear interpolation over
the sorted observations.

| Run ID | Result | `--pre` / job | Selected / corpus | Test / allowance | Non-test / 240s | Deferred |
|---:|---|---:|---:|---:|---:|---:|
| 34459640761 | pass | 37 / 126s | 22 / 559 | 8.904 / 180s | 28.603s | 0 |
| 34275095889 | fail | 305 / 371s | 149 / 559 | 242.506 / 298s | 62.119s | 192 |
| 34273985191 | fail | 382 / 445s | 149 / 559 | 308.592 / 298s | 73.220s | 192 |
| 34258249886 | fail | 352 / 423s | 103 / 559 | 252.931 / 206s | 98.924s | 0 |
| 34239943947 | pass | 77 / 144s | 12 / 559 | 7.234 / 180s | 69.714s | 0 |
| 34168799325 | pass | 37 / 98s | 6 / 558 | 4.206 / 180s | 32.371s | 0 |
| 34167833034 | pass | 35 / 115s | 4 / 558 | 4.559 / 180s | 30.306s | 0 |
| 34165486441 | pass | 255 / 458s | 175 / 557 | 190.660 / 350s | 64.233s | 90 |
| 34137114438 | pass | 294 / 347s | 125 / 551 | 201.562 / 250s | 92.398s | 124 |
| 34134979966 | pass | 326 / 396s | 125 / 549 | 229.758 / 250s | 95.822s | 124 |
| 34132131523 | pass | 278 / 352s | 144 / 550 | 180.514 / 288s | 97.435s | 101 |
| 34130613979 | pass | 249 / 317s | 136 / 548 | 144.453 / 272s | 104.187s | 114 |
| 34129245922 | pass | 264 / 348s | 143 / 546 | 167.257 / 286s | 96.173s | 101 |

Across all 13 runs, the `--pre` step has a 264s median, 228s IQR, 35s minimum, and 382s
maximum. Across the ten passing runs, it has a 252s median, 227.5s IQR, 35s minimum, and 326s
maximum. The whole `pr-validate` job has a 348s median, 252s IQR, 98s minimum, and 458s maximum;
the passing-only job median is 332s.

The non-`--pre` portion of the job has a 70s median and 14s IQR. Dependency-cache restore has a
25s median and dependency installation has a 30s median. All 30 recent job logs inspected reported
a pip-cache hit, so this window contains no cold-cache observation to mix into the primary
population or characterize separately.

| Governed term | Median | Q1-Q3 | Maximum | Constraint |
|---|---:|---:|---:|---|
| `static_s` | 68.572s | 54.021-84.706s | 90.703s | Included in the 240s non-test budget |
| `test_s` | 180.514s | 8.904-229.758s | 308.592s | `max(180s, 2s * n_selected)`, capped at 1260s |
| `replay_s` | 3.442s | 0.208-4.752s | 14.737s | Reported against 150s; included in non-test |
| `unattributed_s` | 3.618s | 2.593-4.751s | 5.592s | Included in the 240s non-test budget |
| Non-test sum | 73.220s | 62.119-96.173s | 104.187s | Hard 240s budget |

No sampled run breached the non-test budget. Runs `34273985191` and `34258249886` breached their
breadth-derived test allowances. Selection spans 4-175 modules from corpora of 546-559 modules,
with a median of 125 selected modules. Eight runs loudly deferred capped transitive residue, for
1,038 deferrals in aggregate. The pinned-base corpus contains 559 test modules.

`pytest_diff` is the dominant named phase in 9 of 13 runs and in every run selecting at least 103
modules. It accounts for 1,943.136s of 2,888.640s of artifact-timed work, or 67.3%. Static work
dominates the four low-breadth runs. The dominant cost is therefore selection breadth plus pytest
execution for broad diffs; static work remains the addressable cost for small diffs.

Evidence came from GitHub Actions job and step timestamps, all 13 `selection-manifest` artifacts,
the 30 most recent reachable job logs for pip-cache classification, and the recursive Git tree at
each artifact SHA for the historical corpus census. The governing formula was checked against
`scripts/checks/deps/selection_budget.py` and the job structure against `.github/workflows/ci.yml`.

## Phase 1 harness

Complete. `scripts/checks/deps/fast_tier_harness.py` validates the pinned two-stratum manifest,
reconstructs each Stratum I implementation tree from its merge parent and merge diff, builds the
tree's fast-tier dependency environment, drives the historical selector and real pytest-diff path,
records JUnit plus native pytest node IDs, and compares baseline/candidate verdicts across the union
of nodes. Per-side captures also retain the selection manifest, deferral map, gate failures,
commands, requirement hashes, environment fingerprint and interpreter. Gate-failure changes are
included in the reported difference count.

Stratum I's same-ref smoke replay of `pr-1120` exercised the real path twice in the isolated
environment, captured 100 union node IDs and both JUnit reports, and reported zero node or gate
differences. Stratum P is emitted separately: all eight pinned plan-to-implementation pairs are
reported, two predicted the observed selection breadth exactly, and none contained the observed
`budget.test_s` within its recorded predicted test-half range. These are calibration outputs, not a
performance diagnosis.

The focused harness suite passes 56 tests with 100% source coverage. This is an instrumentation
check only; no candidate exists in Phase 1, so no optimisation or recall conclusion is drawn here.

## Phase 2 diagnosis

Complete. This diagnosis uses the committed Phase 0 population and Phase 1 harness as fixed inputs. No
baseline or harness replay was rerun, and no tier behavior changed in this phase.

### Cost location

The fast tier has two different latency regimes rather than one general slowdown:

| Regime | Authoritative evidence | Diagnosis |
|---|---|---|
| Broad diffs | `pytest_diff` is the largest named phase in all sampled runs selecting at least 103 modules. It accounts for 1,943.136s of 2,888.640s of artifact-timed work (67.3%). | Selection breadth and execution of the selected tests are the dominant real work. The breadth is intentional recall, not waste. The addressable part is orchestration paid around the fixed executed-node set. |
| Small diffs | Static work dominates all four low-breadth runs. `static_s` has a 68.572s median (54.021-84.706s IQR); the complete non-test half has a 73.220s median. | Once pytest is small, the serial static floor is exposed. Its assertions stay; repeated discovery, parsing and subprocess setup within those assertions are the target. |
| Outside `--pre` | The job-minus-tier median is 70s; pip-cache restore is 25s and dependency installation is 30s. All 30 inspected runs were cache hits. | This is a separate job-clock target. The existing cache avoids downloads but does not avoid reconstructing the installed environment. It cannot improve the governed tier clock and must be reported separately. |

The 67.3% pytest share is an addressable *envelope*, not an estimated saving. It contains both the actual
execution that supplies the gate's recall and orchestration whose fraction is not yet separately timed.
Likewise, the 73.220s non-test median is not all removable: it includes the checks themselves, replay and
unattributed setup. Phase 1's Stratum P timing predictions did not bracket any of the eight observed test
halves, so they are not used to manufacture a savings estimate. Savings remain unknown until same-ref
local A/B and fresh CI runs exist.

### Addressable mechanisms

The first test-half candidate will remove duplicate collection, not selected tests. Every non-empty
affected set currently enters one whole-selection `pytest --collect-only` process to classify
module-scope excluded-heavy-dependency cases. When at least one module is runnable, the primary pytest
process then collects those modules again before executing them. The intended candidate moves that
narrow deferral classification into the primary collection/execution session: suppress only a collection
result that positively identifies a deliberately excluded and genuinely absent dependency, record the
same per-file reason, and leave every other collection error hard-red. Lazy runtime imports retain the
current reactive fallback. This attacks process startup plus the second import/collection pass while
preserving the selected node set, markers, fixed seed, xdist, timeouts, socket isolation, scoped coverage,
deferral map and failure semantics. It survives only if the Phase 1 differ reports zero node-verdict and
gate-verdict changes over the corpus, including distinct deferred and not-collected outcomes.

The first static-half candidates will reuse immutable work within one validation process. The current
source has concrete duplication independent of timings: the fast-tier SLOC and cyclomatic-complexity
checks walk and read the same repository independently; the complexity pass parses Python files already
parsed while constructing the selector/import graph; and self-scoping checks issue fresh changed-file
git queries after `validate.main` has already derived both diff views. The intended mechanism is a
run-scoped file/diff inventory with shared text and AST results, starting with the shared SLOC/CC file
population and the repeated changed-file queries. Each registered check still dispatches in the same
order and produces its own outcome. Nothing is persisted between runs, and fixture roots and push-
context bases remain part of the cache key or are passed explicitly. Broader shared parsing proceeds
only where a local A/B attributes a material saving; this diagnosis does not assume the entire static
median is redundant I/O.

The workflow-level candidate is a content-addressed installed-environment cache keyed by the runner,
Python version and an exact resolved fast/dev environment, with an ordinary install on a miss. The
declaration files contain ranges, so caching an environment indefinitely from their hashes alone is
ruled out: it would silently freeze a formerly fresh resolution. A safe candidate first needs an exact
resolution fingerprint or equivalently bounded invalidation. A wheel-cache hit still leaves the observed
30s installation median, so tuning the existing download cache is not the mechanism. This candidate is
retained only if fresh CI demonstrates that the larger restore is faster than restore plus install. Its
evidence must state both `--pre` and whole-job clocks; moving work outside the governed timer is not a
tier saving.

These are Class 2 optimisations: they change redundant orchestration while keeping the executed node set,
per-node verdicts, asserted static work and emitted artifacts identical. No Class 1 skip is claimed:
closure-backed precision has not been proved for an eligible cost. No Class 3 recall reduction is
intended. The ordered attack is (1) pytest's second collection pass, because broad diffs dominate the
population; (2) same-run static reuse, because it controls the small-diff floor; and (3) installed-
environment reuse, because it affects only the job clock.

### Mechanisms ruled out

- **Selector narrowing, demotion and promotion rollback:** ruled out. PR #723 repaired additive selector
  recall, and PR #966 added protected channels and promoted 25 checks for a measured aggregate cost of
  only 1.56s. The affected-set breadth is deliberate work. Optimisation will not change which tests or
  checks qualify.
- **CAP reduction, protected-channel deferral and silent skipping:** ruled out. The cap applies only to
  transitive residue, while changed tests, direct importers, cochanged-source mirrors and incident
  channels are protected. Current deferral is bounded, loud and observable; weakening it exchanges
  latency for missed pre-merge signal.
- **Persistent selection, import-graph or coverage caches:** ruled out in this audit. The selector is
  intentionally live and cacheless, and a persisted cache is a Decision-level change with invalidation
  and staleness risk. Run-scoped reuse of immutable inputs is deliberately narrower.
- **New or narrower `pre_globs`:** ruled out while closure validation is advisory. A glob omission is
  fail-open and skips the exact check that would expose its own incomplete dependency declaration.
  Existing glob gates remain unchanged.
- **Overlapping the static and pytest halves:** ruled out. The budgets are a serial partition. Hiding
  static work under a longer pytest process makes the non-test term vacuous unless critical-path
  accounting and the synthetic 300s static-sleep probe are preserved. No such budget reinterpretation
  is needed for the identified duplication.
- **More pytest workers:** ruled out. The primary path already uses `-n auto`; a fixed seed addresses the
  cross-worker collection hazard. Worker-count retuning is not a mechanism supported by this baseline.
- **Dropping scoped coverage:** ruled out. Diff coverage consumes its artifact, and the current
  include-scoped sysmon configuration has already reduced a measured 4.3x whole-tree tracing penalty to
  a 2.4% proxy overhead. Removing that remaining work would remove evidence rather than redundant work.
- **Removing `-v` or test/deferral artifacts:** ruled out for the first candidate. The verbose stream is
  consumed by `_attribute_failed_test_files` and ci-rca, while the coverage and deferral maps feed
  `validate_diff_coverage`. The candidate therefore changes neither output. If later measurement makes
  verbosity material, replacements for every consumer and an artifact upload must land before it changes.
- **Optimising the reactive heavy-dependency probes first:** ruled out. They occur only after a primary
  failure with a matching excluded-dependency signature, are already restricted to implicated files and
  run with bounded concurrency. They do not explain passing-run latency.
- **Editing tests or replacing pytest:** ruled out at this stage. The baseline identifies breadth, not a
  particular slow test body, and pytest currently supplies autouse fixtures, socket denial, recursion
  checks, marker policy, heavy-dependency handling, fixed ordering, timeouts and coverage. A replacement
  runner would owe equivalence for all of them. Test edits would additionally trigger the deferred
  mutation probe; neither risk is justified before orchestration-only candidates are exhausted.
- **Budget increases or relabeling:** ruled out. No sampled non-test half breached 240s, and two test-half
  breaches are observations to improve, not reasons to weaken the threshold.

## Change ledger

| Change | Class | Mechanism | Estimated saving | What no longer runs | What is no longer produced | Proof | Residual risk |
|---|---|---|---|---|---|---|---|
| Phase 2 diagnosis only | N/A | Documentation checkpoint before code | 0s | Nothing | Nothing | Diff limited to this findings document | None; candidate rows begin in the implementation phase |
| Candidate 1 - **ABANDONED**; code retained on branch as phase record | Class 2 - identical work, lower cost | The real primary pytest session suppresses only positively identified excluded-and-absent dependency collection reports, records deferrals through xdist worker output, and rolls back coverage produced while importing a deferred module. The former collect-only implementation remains only as a frozen compatibility surface. | The 3.395s orchestration-remainder saving at 144 modules is real (non-overlapping IQRs), but only 1.3% of the Phase 0 264s `--pre` median. Against the Phase 0 CI noise floor of roughly +/-24s, it is below the authoritative surface's resolution and cannot satisfy section 12. Gross-wall saving is null within spread. | **No test nodes are removed.** On this branch, one collect-only process no longer runs. The corrected committed-ref differ from `9cecaab2` to `015a0240` completed all 16 cases and compared 27,878 union-node observations: zero node-verdict changes, zero gate-verdict changes, and identical deferral maps. `deferred` and `not-collected` remain distinct outcomes in the capture vocabulary. | **No loss is observed.** The differ reports identical executed nodes, per-node verdicts, gate verdicts and deferral maps across the corpus. | The initial checkpoint's 72 fixture-only node changes were corrected in `015a0240` by making the shared subprocess double emit the primary-plugin completion record and carrying both new `_pytest_diff` modules into synthetic verifier fixtures. The mandatory 10-case baseline/candidate mutation probe caught all 10 mutations. The original 102 focused tests passed; the correction's 368-test focused suite passed after the one sandbox-denied Git-worktree test was rerun with permission. Ruff and format checks pass. | Costs exceed an unresolvable saving: rewrite of the fail-closed classification path, permanently frozen `_pytest_diff_collect.py` compatibility surface, test-double changes across the suite, rebase conflict in `_pytest_diff.py` after main also modified it, and a full corpus re-proof because all requirements files and the derived heavy-dependency deferral set moved. Do not integrate Candidate 1; no code revert or rebase in this session. |

## Candidate 1 timing row - fixed-tree local attribution

Prediction stated before measurement: removing one pytest process start and one whole-selection
collection pass should save roughly a constant amount per run, not an amount proportional to
selection breadth. This local A/B tests that prediction; it is not Phase 4 CI timing evidence.

Both scratch worktrees were fixed at `dec04c6d`. The baseline restored **only**
`scripts/checks/_pytest_diff.py` from `9cecaab2`; the candidate kept the `dec04c6d` file. Git
status confirmed that this was the only tracked source difference throughout. Both sides used the
same content-addressed Python 3.12 fast/dev environment and the same `dec04c6d` requirements.
The broad selection was the exact 144-module selected list in the `pr-1114` capture produced by
the committed-ref corpus replay; the breadth control was its first 18 modules. Each side ran the real
`run_pytest_diff` five times per selection, alternating baseline then candidate. Every invocation
kept the real pytest flags, coverage setup, timeout and xdist path. Outer wall time was measured
locally; pytest's own summary duration was subtracted only for a secondary orchestration-remainder
readout. Raw timing and pytest logs stayed in gitignored `logs/debug/`.

| Selection | Side | Five outer wall times (s), in run order | Median (s) | Q1-Q3 (s) | Min-max (s) |
|---|---|---|---:|---:|---:|
| 144 modules, 3,176 outcomes | Baseline | 358.436, 305.504, 410.900, 365.706, 312.854 | 358.436 | 312.854-365.706 | 305.504-410.900 |
| 144 modules, 3,176 outcomes | Candidate 1 | 351.011, 365.540, 360.720, 318.053, 315.390 | 351.011 | 318.053-360.720 | 315.390-365.540 |
| 18 modules, 503 outcomes | Baseline | 9.380, 9.518, 9.111, 9.038, 9.682 | 9.380 | 9.111-9.518 | 9.038-9.682 |
| 18 modules, 503 outcomes | Candidate 1 | 9.124, 8.387, 8.169, 8.301, 8.436 | 8.387 | 8.301-8.436 | 8.169-9.124 |

The representative broad-set median difference is 7.425s, but the paired differences range from
-60.036s to +50.180s and both per-side spreads dwarf 7.425s. The gross-wall improvement is
therefore **null** under section 12's noise rule. The 18-module control has a 0.993s difference
between medians (0.942s median paired saving), outside its IQR spread; it is a small-set result,
not an extrapolated broad-set claim. All ten narrow runs passed the same 503 tests. All ten broad
runs had the same 3 failed, 3,172 passed and 1 skipped summary: the three failures come from a
reused environment's `lint-imports` launcher pointing to a vanished path, common to both sides.
No new test or gate-verdict claim is inferred from these timing-only runs.

| Selection | Baseline outer-minus-pytest median (Q1-Q3), s | Candidate median (Q1-Q3), s | Median difference, s |
|---|---:|---:|---:|
| 144 modules | 4.836 (4.424-7.820) | 1.441 (1.433-1.510) | 3.395 |
| 18 modules | 1.618 (1.571-1.620) | 0.796 (0.731-0.814) | 0.822 |

The non-overlapping orchestration remainders show that Candidate 1 removes some local work, but
the saving grows from 0.822s to 3.395s as selection breadth grows eightfold. The pre-measurement
constant-saving prediction is **rejected**: the whole-selection collection pass has a
breadth-dependent cost. This decomposition does not override the null gross-wall result on the
representative set, and it makes no CI-based timing claim.

At this checkpoint, `dec04c6d` was pushed to draft PR #1131. The PR is marked conflicting with
main. The GitHub check returned no PR workflow run associated with that head, and there was no
CI-green signal for it at the last check. Main has changed
`scripts/checks/_pytest_diff.py` and all requirements files since the candidate branch diverged,
so its prior identical-deferral-map proof cannot be reused after any integration. This session
did not rebase, re-run the corpus differ, or start Candidate 2.

## Candidate 2 pre-implementation profile - no tier change

This is a local static-work profile at the current committed branch tree, not a production
change or a new Phase 0/CI timing population. Runtime-only instrumentation drove the registered
`--pre` sequence with the Candidate 1 pytest-diff scaffold omitted, so Candidate 1 was not
re-run. A clean scratch checkout at `1ac7ff91` avoided the Codespace's gitignored
`logs/debug/` replay environments: the working directory had 14,107 gated Python files and
would overstate CI-like scan cost, while the clean checkout had 984. The clean profile kept all
static checks and their pre-glob dispatch real. A second pass supplied a synthetic single-test
changed path on the same tree to profile a low-breadth Python-diff context; neither pass edited
tracked source.

The normal `--pre` path calls `iter_gated_py_files()` **twice**, not four times: once from
`validate_cc_limits` and once from `validate_sloc_limits`. SLOC's second call is only in the
separate `--update-sloc-budgets` command, and `validate_sloc_budget_raises` never calls the
iterator. Each clean-tree iterator returned 984 files and cost 15-23ms, including its whole-repo
walk. The budget-raise guard made no AST parse; CC parsed 954 files, skipping 30 waivered files.

| Clean-tree static context | AST parses | Later same-path/source-hash/mode parses | Their measured parse time | Repeated-read time | All git-call time |
|---|---:|---:|---:|---:|---:|
| Current branch diff | 8,720 | 7,561 | 12.160s | 1.757s | 0.212s (51 calls) |
| One edited test module | 5,952 | 4,847 | 7.507s | 0.999s | 0.096s (26 calls) |

The CC check's own repeated parses accounted for 948 calls / 1.774s in the current branch
context and 624 calls / 1.207s in the single-test context. These are direct timed
`ast.parse()` bodies, not a subtraction from gross `--pre` wall time. Five direct, uninstrumented
check invocations on the clean tree gave these medians (Q1-Q3): CC 4.333s (4.329-4.394), SLOC
0.172s (0.167-0.178), SLOC budget-raise guard 0.004s (0.003-0.008), contract drift 7.057s
(6.944-7.075), test-count coupling 4.285s (4.213-4.288), and raises discrimination 3.698s
(3.672-3.712). The direct check timings corroborate that walks are tiny and repeated parsing,
not the iterator itself, is the larger static cost.

The diagnosed SLOC/CC-first reuse has a **generous ceiling**, not an achieved saving: removing
one iterator, all CC repeated parses and file reads, and even **all** measured git-call time
would recover at most 2.153s on the current branch diff and 1.463s on the single-test context.
An impossible perfect cache across every repeated parse and read in the entire measured pre
path, plus one walk and all git calls, has a still-generous ceiling of 14.146s and 8.624s
respectively. Some AST consumers may not safely share an object, and many git calls are not
redundant, so actual recoverable time is lower. These are local per-operation ceilings, not
CI-based timing claims.

Against the authoritative Phase 0 regimes, the current-branch perfect-cache ceiling is 20.6%
of the 68.572s overall static-half median, but only 5.4% of the 264s `--pre` median and below
its roughly +/-24s CI noise floor. The four reported low-breadth `--pre` clocks are 35, 37,
37 and 77s (median 37s, cross-case IQR 10.5s, range 42s). The single-test perfect-cache
ceiling is 8.624s, or 11.2-24.6% of those total clocks, yet remains below even that 10.5s
observed spread. The cross-case IQR is descriptive, not a controlled same-diff noise estimate;
it is nevertheless the available Phase 0 resolution bar, and the diagnosed first scope's
1.463s is well beneath it. **Recommendation: abandon Candidate 2 as scoped**, pending the
user's decision. No Candidate 2 implementation, rebase, or Candidate 3 work occurred.

## Phase 4 evidence

Pending candidate implementation and A/B evidence.

## DEVIATIONS

### Capability deviations

- The `agent_platform` AWS assume-role chain was unavailable during preflight. The audit's AWS and
  warehouse scope is explicitly out of scope, so no implementation evidence depends on it.

### Judgment deviations

- None at the Phase 0 checkpoint.
