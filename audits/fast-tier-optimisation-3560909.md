# Fast-tier optimisation findings at 3560909

Base SHA: `35609091fd8482d3116e4b360c6ec2bc9ab25b90`

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
