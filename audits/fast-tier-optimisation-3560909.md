# Fast-tier optimisation findings at 3560909

Base SHA: `35609091fd8482d3116e4b360c6ec2bc9ab25b90`

## Established context

- The working branch is `claude/fast-tier-optimisation`. It was rebased onto `origin/main` at
  `a740b93` before Phase 1 began. The audit base remains pinned at
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

Pending the Phase 1 executed-node harness. This section will be committed before optimisation code.

## Change ledger

| Change | Class | Mechanism | Estimated saving | What no longer runs | What is no longer produced | Proof | Residual risk |
|---|---|---|---|---|---|---|---|
| Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

## Phase 4 evidence

Pending candidate implementation and A/B evidence.

## DEVIATIONS

### Capability deviations

- The `agent_platform` AWS assume-role chain was unavailable during preflight. The audit's AWS and
  warehouse scope is explicitly out of scope, so no implementation evidence depends on it.

### Judgment deviations

- None at the Phase 0 checkpoint.
