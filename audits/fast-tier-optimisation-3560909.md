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
| Candidate 1 checkpoint - primary-session heavy-dependency classification | Class 2 - identical work, lower cost | The real primary pytest session suppresses only positively identified excluded-and-absent dependency collection reports, records deferrals through xdist worker output, and rolls back coverage produced while importing a deferred module. The former collect-only implementation remains only as a frozen compatibility surface. | Unknown pending completed local A/B; no timing claim | **Pending - no claim.** The required 16-case differ was interrupted during `pr-1128` baseline before its first complete capture. A separate `pr-1120` smoke replay compared 100 union nodes with zero node-verdict and zero gate-verdict changes. | **Pending full-corpus proof.** Focused integration tests preserve the deferral map, scoped coverage JSON, verbose pytest execution and distinct all-deferred/non-heavy-error outcomes; the corpus artifact comparison is incomplete. | 102 focused tests passed; ruff and focused mypy passed; real xdist tests cover mixed runnable/deferred, all-deferred `importorskip`, non-heavy collection failure and exact scoped-coverage rollback. All eight named baseline/candidate mutations were caught. | High until the complete corpus reports zero node/gate differences and matching deferral maps. The interrupted replay is not evidence. Candidate 2 has not started. |

## Phase 4 evidence

Pending candidate implementation and A/B evidence.

## DEVIATIONS

### Capability deviations

- The `agent_platform` AWS assume-role chain was unavailable during preflight. The audit's AWS and
  warehouse scope is explicitly out of scope, so no implementation evidence depends on it.

### Judgment deviations

- None at the Phase 0 checkpoint.
