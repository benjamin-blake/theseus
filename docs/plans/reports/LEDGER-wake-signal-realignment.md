# Planning ledger -- wake signals + executor verdict wait

Session: 2026-09-14/15. Branch `agent/quirky-dijkstra-iupj7e`. Telemetry session
`28b7ea4f-8071-486a-a478-df7e261dd37d` (opened Step 1; close with
`bin/venv-python -m scripts.session.postflight --close-session --outcome success`).

Purpose: durable record of verified facts, operator directions and gate findings, so a compacted
or restarted session can resume without re-deriving. Everything marked [VERIFIED] was checked
against the tree or a live API in this session.

COMMITTED to git at this path (commit 7dd6bd72) precisely because the scratchpad copy it was
drafted in does not survive a new session. Read it here, not from any scratchpad path an older
note may name. Its companions are docs/plans/PLAN-conflict-wake-prefix-realignment.yaml (P1) and
docs/plans/PLAN-verify-ci-workflow-decomposition.yaml (P0); neither has passed plan-critique yet.

---

## 1. How the task changed shape

Original request: migrate agent-branch convention `claude/*` -> `agent/*` across every surface and
re-align the two comment-based wake signals to it.

It changed three times on evidence:

1. **Decision 76 exists and governs branch topology** -- the original prompt asserted no numbered
   Decision did. Its clause 2 removed the agent-CREATED `agent/{slug}` ceremony; its Context
   assumed the harness assigns `claude/...`. The RULE is intact; the PREMISE went stale.
2. **Two live probes** (section 3) proved the green-wake doc claim stale and the conflict-wake doc
   claim standing. The two wake paths are ASYMMETRIC.
3. **Operator direction** (section 4) settled the design after a Fable architecture consult and
   three decision-scout runs.

---

## 2. Verified repo facts (with anchors)

- [VERIFIED] `.github/workflows/ci.yml:315` -- `signal-green` gate:
  `if: ${{ success() && github.event_name == 'pull_request' && startsWith(github.head_ref, 'claude/') }}`
- [VERIFIED] `scripts/ci/pr_conflict_signal.sh:72` -- `select(.headRefName | startswith("claude/"))`.
  Also lines 76, 78 carry `claude/*` in messages.
- [VERIFIED] `scripts/checks/ci_guards/validate_pr_conflict_signal.py:171` --
  `("claude/* head filter", "claude/" in script_text)`. Bare substring; existence-only.
- [VERIFIED] `scripts/verify_ci_workflow.py:329` -- `assert signal_green is not None,
  "signal-green job missing from ci.yml"` inside `_check_signal_green_needs` (lines 323-343).
  Its docstring property is "Every PR-gating job in ci.yml must be listed in signal-green.needs" --
  a workflow-completeness invariant INDEPENDENT of the wake.
- [VERIFIED] `_check_signal_green_needs` filters `job_name != "signal-green"`, so widening
  signal-green's own `if:` cannot trip it.
- [VERIFIED] `scripts/verify_ci_workflow.py` = **499 SLOC against the 500 cap**, and is
  **UNREGISTERED** in `config/sloc_budgets.yaml`.
- [VERIFIED] `ci.yml` has exactly four jobs: `pr-validate`, `main-validate`, `terraform-validate`,
  `signal-green`. signal-green is the ONLY aggregating job -- nowhere to re-point the needs
  assertion.
- [VERIFIED] `config/check_accounting_baseline.yaml` line 45 = `validate_ci_workflow_guards`,
  line 76 = `validate_pr_conflict_signal`. NEITHER module declares `examined()`/`skipped()`
  (grep count 0 on both). Decision 170 touch-it-fix-it fires on BOTH.
- [VERIFIED] `docs/contracts/github-actions-evidence.yaml:120` declares
  `job: signal-green` / `diagnostic_id: ACTIONS_CI_SIGNAL_GREEN`, and `validate_actions_evidence`
  is globbed on both `.github/workflows/**` and that contract
  (`scripts/checks/ci_guards/_manifest.py:49`).
- [VERIFIED] Tests referencing signal-green: `tests/checks/ci_guards/test_validate_masked_errexit_steps.py:159`
  (reads the step body by name); `tests/verify_ci_workflow/test_ci_data_guards.py` ~8 refs incl. a
  test asserting the "signal-green job missing" string.
- [VERIFIED] Other signal-green comment surfaces: `.github/workflows/pr-conflict-signal.yml:3,5,11`;
  `.github/workflows/cost-reconciliation.yml:5`; `scripts/preflight/dependabot.py:4` docstring
  (states the now-false rationale); `scripts/ci/branch_cleanup.py:8` docstring.
- [VERIFIED] `tests/test_pr_conflict_signal_wiring.py` has a full `gh` shim harness keyed on call
  kind. It IGNORES `--jq` and returns canned stdout, so the prefix filter is currently NOT
  exercised behaviourally -- which is why the guard degenerated to a substring check.
- [VERIFIED] `scripts/ci/` has no `__init__.py` but is importable as a namespace package;
  `python3 scripts/ci/<mod>.py` works with no venv (relevant: `pr-conflict-signal.yml` has NO
  python setup step).
- [VERIFIED] `terraform/personal/oidc_ci_roles.tf:32` trusts `refs/heads/agent/*` for the CI branch
  write role. Decision 94 records `agent/*` and `pull/*` cannot assume `github_ci_apply`. Must stay
  unweakened; not in scope.
- [VERIFIED] AGENTS.md `claude/` hits: lines 51, 146 (branch rule) + lines 52, 67, 113 which are
  `.claude/` PATHS. The registry entry `agents-md-retains-enforced-norms-and-pointer.yaml:14`
  greps `claude/` in AGENTS.md -- it survives any branch-rule rewording because `.claude/` paths
  keep the substring. (I initially flagged this as a blocker; it is NOT.)
- [VERIFIED] `scripts/ops_portal/cli.py` has NO `__main__` guard; `python -m scripts.ops_portal.cli
  --help` exits 0 with ZERO output. Filed as rec-3875.
- [VERIFIED] Executor already hardcodes `agent/` branches: `scripts/executor/postflight.py:70-78`,
  `postflight_gates.py:216,218`, `batch_compound.py:173-175`.
- [VERIFIED] Executor already POLLS: `scripts/executor/postflight_ciwait.py` --
  `wait_for_ci(branch, timeout=600, interval=30)`.
- [VERIFIED] PR head-ref population: 9 of last 12 agent-session PRs were `agent/*`, 3 `claude/*`.
  2 remote `claude/*` heads open at 2026-09-15.

---

## 3. Measured probe evidence (the load-bearing new facts)

### Probe 1 -- GREEN wake. Result: POSITIVE, n=2. Conclusive.
Native `check_suite.completed` wakes arrived 2/2 on all-green rollups from an `agent/*` branch,
with `signal-green` confirmed `skipped` both times (so no repo mechanism could have produced them).
Latencies ~145s and ~161s from last required check. A deliberate failure push produced a
`check_run.completed` failure wake as liveness control.
=> `docs/contracts/git-ops.yaml:193-199` ("subscribe_pr_activity delivers failure events but NOT a
CI-success webhook") is **STALE**. Tracked by **rec-3866**.

### Probe 2 -- CONFLICT wake. Result: NEGATIVE, n=1. Weak evidence, premise stands.
PR #1190 (`agent/conflict-wake-probe-p`) went `blocked` -> `dirty` after #1191 squash-merged to
main at 10:21:09Z. Across ~16 min of genuine session idle with a live subscription, ZERO wake
envelopes referenced the transition. Control held: the sweep's job log for that push printed
`PR #1185:` and `PR #1131:` but no `PR #1190:` line, and no `<!-- conflict-wake:` marker was ever
posted. Cleanup complete; main restored byte-identical (revert PR #1192). Tracked by **rec-3874**.
=> The harness's "PR state notice" for merge conflicts is documented **best-effort** and
"may arrive late or not at all". `pr-conflict-signal.yml` is the ONLY reliable path.

### Probe methodology lessons (cost real time; do not repeat)
- A probe measuring "does an idle session get woken" **CANNOT run in a subagent** -- a subagent must
  hand back at the end of its turn and cannot idle across turns. Run from a top-level session.
- REST `mergeable_state` vocabulary (the `gh` CLI is absent in these containers, so
  `pull_request_read` is the substitute): **`dirty` = conflict**; `blocked`/`clean`/`unstable`/
  `behind` all mean not-conflicting; `unknown` = still computing. Do NOT wait for `clean` -- required
  checks hold a PR at `blocked` indefinitely.
- The sweep prints `No open claude/* PRs against main.` ONLY when the set is empty; otherwise one
  `PR #N: mergeable=..., no wake needed.` line per PR. Absence test = no line beginning
  `PR #<probe-number>:`.
- A positive proves capability; a NEGATIVE is weak (rec-3335 showed a live subscription can drop a
  signal). Never retire a mechanism on one negative.

---

## 4. Operator directions (Decision 151 authority -- SETTLED, not proposals)

### Plan A family
- **A1** Do NOT supersede rec-3046 with a competing rec. Re-scope IN PLACE: naming half and
  merge-conflict half land as written; CI-green half is RETIRED (harness delivers natively).
  Record the three-way split in the rec's resolution.
- **A2** Invert `AGENTS.md:51` and `:146` to say the harness-assigned branch is `agent/...`; the
  "do NOT create an `agent/` branch" sentence goes.
- **A3** RETIRE `signal-green` from `ci.yml`. Rewrite `git-ops.yaml` `wake_signals.ci_green_comment`
  and `coverage_note` to state CI success is delivered natively. KEEP `auto_merge_relationship`.
  Exit criterion: one PR observed waking on green with signal-green absent.
- **A4** KEEP `pr-conflict-signal.yml` + `pr_conflict_signal.sh`, REPOINTED to `agent/`.
  Transitional BOTH-prefix acceptance permitted; drop `claude/` once no open `claude/*` PR remains
  (currently 2). Retire the sweep only if a later plan observes the harness notice firing reliably
  across N pushes-to-main -- as its own rec.
- **A5** Guard the conflict sweep's BRANCH-SCOPE predicate (rec-3046 surface 4 is why it recurred
  silently across two PRs).
- **A6** Do NOT unify interactive wake and executor verdict wait. They share a SOURCE OF TRUTH
  (check rollup + mergeable state bound to head SHA), not a DELIVERY. CC-web = push consumer
  (cannot poll: no sleep/idle tool; `send_later` harness-gated per `git-ops.yaml`
  `cc_web_permission_gotcha`). Executor = level consumer (Step Functions `Wait`). **One predicate,
  two deliveries.** What MAY be shared is code: the "read PR state by head SHA" routine.

### Plan B (executor verdict wait) -- CONFIRMED shape
- **B1** Keep Step Functions. NO Decision 39 supersession. Replace
  `lambda:invoke.waitForTaskToken` with `Wait -> Task(poll by head SHA) -> Choice` for the
  CI-verdict wait (`await_verdict`) and the gated-apply convergence wait (`deploy_dispatch`).
- **B2** ONE new numbered Decision, `amends: [185]` ONLY (clause 1's construct subset), with dated
  append-only annotations (Decision 177) on Decision 185 and on CD.27's layer-1 boundary diagram.
  Decision 39 untouched because the cloud engine is unchanged. The amendment SHRINKS the subset
  (drops `waitForTaskToken`; `Wait`/`Task`/`Choice` already allowlisted).
- **B3** Decision 100 reading to state in the entry: the primitive being replaced is NOT the wait,
  it is the callback TRANSPORT (T4.9a's inbound endpoint, the Actions OIDC role holding
  `states:SendTaskSuccess`, token-by-SHA correlation storage, MECH-2's always-run reporting step).
  None of that is a Step Functions primitive; all is repo-owned code. Polling REMOVES repo-owned
  code, so Decision 75's third frame-challenge question cuts FOR the change.
- **B4** Heartbeat semantics move from `HeartbeatSeconds`/`TimeoutSeconds` on the token state to a
  definition-carried deadline (T4.11 counter pattern), with a Choice branch to the ci-rca Fail
  state -- never a silent re-wait (Decision 72). REWORD, do not delete: T4.1's heartbeat criterion,
  T4.19 c4, T4.20 c5, T4.9a's callback endpoint (becomes "verdict read by head SHA"). PRE_PASS on
  merge survives as "polled rollup head SHA == PR head".
- **B5** Persona-dispatch wait NOT decided here. Record as a T4.15 constraint scored across the four
  arms: "no inbound surface on either tier".
- **B6** NOTHING deleted. T4.19/T4.20/T4.22 stay alive with narrower scope (Decision 93 tombstone
  semantics; live `depends_on` edges). T4.22 NOT dropped -- Decision 184's no-free-tier reversal
  condition has not fired and the free-tier host is the constituency the portability argument rests
  on.
- **ADDITION I flagged, operator has not yet ruled on**: Decision 76 clause 4 ("never `sleep`/
  `/loop`") is unqualified and now reads as forbidding what B1 adopts. Needs a dated annotation
  scoping it to the CC-web interactive harness, with `AGENTS.md` and `git-ops.yaml:182,192`
  (which restate the norm) in scope.

### Plan C (fold into the T4.19 plan when authored -- no separate item)
- **C1** Typed graph canonical, ASL the projection. Keep 185's letter (committed ASL is byte-equal
  rendered, T4.19 c1) but write the builder as typed nodes with explicit edges and retry/deadline
  policies, rich enough that a local engine walks the Python object graph rather than interpreting
  ASL JSON. Drops T4.22 from "write an ASL interpreter" (L) to "write a graph walker" (M) and moots
  185's moto-engine-adoptable reversal condition. Reword T4.22 intent to "walks the T4.19 graph".
  MUST happen before T4.19 lands -- a builder emitting dicts cannot be walked.
- **C2** Hexagonal steps, enforced. Step logic under `src/executor_loop/` with NO boto3 import; glue
  Lambdas are one-line adapters over ports (Decision 184 clause 2). Add a registered import-boundary
  check alongside `validate_loop_asl_subset`.

### Operator sequencing
1. rec-3046 as re-scoped (XS) -- outage is live for every `agent/*` PR now. Do NOT couple to Plan B.
2. Plan B amendment entry + criteria rewordings + T4.15 constraint.
3. C1/C2 fold into the T4.19 plan.

---

## 5. Corrections and retractions (things I got wrong -- do not re-adopt)

- **Decision 39 does NOT stop biting.** I relayed Fable's "a control loop is not a DAG, so 39
  doesn't apply". [VERIFIED] 39's **Decision** clause reads "Step Functions is the orchestrator.
  Each workflow is a Step Function state machine" -- shape-agnostic. Only its Options line rejects a
  custom DAG engine. Moot under B1 (Step Functions retained) but never re-use the argument.
- **`watch_url` cannot be CI's adapter.** Its signing secret is encrypted to the artifact service;
  only that service can sign deliveries. I proposed a transport CI structurally cannot use.
- **"Registration not inference" is still edge-triggered.** It relocates the guess from CI to a
  table but still needs the edge delivered; rec-3335's failure class survives it.
- **The AGENTS.md registry-grep is not a blocker** (see section 2).
- **Deleting tier items is not the governed retirement path** -- Decision 93 names `reserved` +
  supersession note; deletion breaks live `depends_on` edges (T4.1, T4.11, T4.15, T4.24).
- **A subagent cannot run an idle-wake probe** (section 3).
- **"Keep signal-green as backup" was argued on inverted evidence** by me at one point: native
  green delivery is 2/2, the comment path is 0/1 (rec-3335). Superseded anyway by operator
  direction A3 (retire it).

---

## 6. Decision-scout findings still binding on the plans

Three gate runs, all `FLAGS_FOUND`, all `144 of 144` triaged (copy the count lines verbatim into
each plan's scout context line; re-run per plan since scope now differs).

- **Decision 170** -- touch-it-fix-it. BOTH `validate_ci_workflow_guards` (baseline line 45) and
  `validate_pr_conflict_signal` (line 76) must adopt `examined()`/`skipped()` and be removed from
  the baseline in the SAME PR that edits their module. Shrink-only; no marker escape grammar.
- **Decision 187** -- "Retiring a pin whose property is unreplaced requires a filed carrier; silence
  is not a disposition." Applies to `_check_signal_green_needs`. Operator ruled: BUILD the
  replacement guard. Also [VERIFIED] no `# tier-demotion-approved` marker is needed -- both checks
  are `pre=True, full_segment="full_after_lint"` with no `pre_globs`, so tightening is free.
- **Decision 128** -- `verify_ci_workflow.py` at 499/500 and unregistered. Operator ruled: DECOMPOSE
  (facade package), not raise.
- **Decision 103** -- rec-3046's acceptance oracle is its closure proof. Its FIRST conjunct
  (`grep -qE "head_ref, *'agent/'" .github/workflows/ci.yml`) becomes unsatisfiable once
  signal-green is retired. `update_rec` the acceptance BEFORE any `Resolves:` trailer, or it closes
  against a failing oracle -- exactly the rec-3867 defect.
- **Decision 191** [SPIRIT, dischargeable] -- the scout's HONEST read: element 2 does NOT literally
  contradict 191 (its binding clauses are scoped to `action_merge_ops` /
  `ducklake_maintenance_scope.VERB_UNIVERSE` / `validate_maintenance_policy_matrix`, none in scope;
  the prior gate's use of it as deletion doctrine OVERREACHED). But its Rationale names a FAILURE
  SHAPE that rec-3046 is an instance of. Discharge by RECORDING three things:
  (1) a dated rationale for why the sweep's universe is a declared prefix set rather than
      enumerate-all-open-PRs-with-declared-exclusions -- the blast-radius argument written down as
      the `reason` half of a declared exclusion, not left as an absence;
  (2) the semantic guard asserts the DECLARED PREFIX SET EXACTLY (read from one named source), not
      mere membership -- this is what converts silent degradation into CI failure;
  (3) a filed carrier rec for the `claude/`-drop step with its trigger condition, so the
      transitional window cannot outlive its premise.
- **Decision 163** [NOTE] -- the transitional both-prefix window's end is discretionary; nothing
  distinguishes "correctly transitional" from "forgot to narrow". Mitigated by (2) above:
  asserting the exact set makes narrowing a one-line visible edit.
- **Decision 181** -- new assertion must strictly DOMINATE the replaced one; `coverage_note` must
  publish per-surface either the enforcing check or the unenforced residual with an owning rec.
- **Decision 177** -- corpus append-only. Premise corrections to Decision 76 land as dated
  annotations, never in-place edits. Guard `validate_live_entry_immutability` was retired by
  Decision 178, so this is policy-only and easy to violate silently.
- **Decision 165** -- existence -> authorization doctrine for the substring->semantic guard upgrade.
- **Decision 86 / T2.56** -- route the prefix fact to `git-ops.yaml` `branching_topology`; keep
  AGENTS.md to a thin one-line trigger.
- **Decision 131** -- test-colocation mirror rule for the four test files.
- **Decision 132 / 189** -- every pre-deploy VP step needs a `graduate|waive|not-applicable`
  disposition; `graduate` steps are replayed RED-BEFORE against the un-implemented tree on the
  plan's own PR and an exit-0 HARD-FAILS. Negated sweeps (`! grep ...`) over existing paths are
  ineligible for the graduate partition -- use `waive`.
- **Decision 138** -- DROPPED: nothing in the revised shape touches `never_on_main.py`.
- **T2.54:c1** -- use its clause-to-check naming convention for the coverage declarations; do not
  invent a competing annotation shape.

---

## 7. The three-plan split (CONFIRMED by operator)

- **P0 -- `verify_ci_workflow.py` decomposition. DELEGATED to a subagent planner.**
  Facade package (Decision 80/104/124 pattern), each submodule under budget, full public surface
  re-exported. Plus `examined()`/`skipped()` adoption on `validate_ci_workflow_guards` and its
  baseline line-45 removal. Pure hygiene, ZERO behaviour change. Independent; unblocks P2.
- **P1 -- conflict-wake correctness. Authored by me. GOES FIRST (live outage).**
  `pr_conflict_signal.sh` repointed to `agent/` + declared transitional `claude/`; semantic
  branch-scope guard **in `validate_pr_conflict_signal.py`** (operator-confirmed home -- makes P1
  self-sufficient, no dependency on P0); `examined()`/`skipped()` + baseline line-76 removal;
  `tests/checks/ci_guards/test_validate_pr_conflict_signal.py`;
  `tests/test_pr_conflict_signal_wiring.py` (behavioural enumeration via the existing gh shim);
  AGENTS.md 51/146 inversion + `git-ops.yaml` `branching_topology`; rec-3046 acceptance
  `update_rec` BEFORE the trailer; carrier rec for the `claude/`-drop trigger.
- **P2 -- signal-green retirement. Authored by me. AFTER P0.**
  `ci.yml` job removal; `github-actions-evidence.yaml` ACTIONS_CI_SIGNAL_GREEN entry;
  `_check_signal_green_needs` removal + the REPLACEMENT needs-completeness guard (assert the
  declared PR-gating job set, e.g. against branch-protection required checks) in the decomposed
  package; `validate_ci_workflow_guards._load_guards()` pair drop;
  `tests/verify_ci_workflow/test_ci_data_guards.py`;
  `tests/checks/ci_guards/test_validate_masked_errexit_steps.py`; comment surfaces
  (`pr-conflict-signal.yml`, `cost-reconciliation.yml`, `dependabot.py`, `branch_cleanup.py`);
  `git-ops.yaml` `wake_signals.ci_green_comment` + `coverage_note` rewrite, KEEPING
  `auto_merge_relationship`.

Each plan defends ONE claim: "this file is decomposed" / "the conflict wake fires for every agent
session" / "the green comment is retired because the harness delivers natively".

---

## 8. Recommendations touched this session

- **rec-3046** (open) -- the original. RE-SCOPE IN PLACE per A1; acceptance must be `update_rec`'d
  before any Resolves trailer.
- **rec-3866** (open) -- green-wake doc stale. Filed by probe 1.
- **rec-3874** (open) -- conflict-wake entry lacks live-probe evidence. Filed by probe 2.
- **rec-3867** (open, High) -- FILED BY ME. `rec-autoclose` closes recs from a `Resolves:` trailer
  without verifying the acceptance command. rec-940 is the demonstrated instance (status `closed`,
  resolution names merge `e542706`, yet its acceptance
  `grep -q "enable_pr_auto_merge" .claude/skills/implement/SKILL.md` FAILS today).
- **rec-3875** (open, Medium) -- FILED BY ME. `scripts/ops_portal/cli.py` silent no-op.
- **rec-3335** (open, High) -- CI-green comment wake failed to deliver once on a green PR (PR #987).
  The reason single-path delivery is treated as disproven.
- **rec-3861 / rec-3863** -- CLOSED. The ruff 0.16.7 ISC004 regression; fixed by PRs #1186-#1189
  (`tool-pin-lint-escalation`), which ALSO closed the defect class: `run_lint_checks` now lints
  tree-wide unconditionally in both tiers, and `run_precommit_checks` escalates to `--all-files`
  fail-closed when a `--pre` diff touches a global input. New Class D contract
  `docs/contracts/presubmit-tool-pin-escalation.yaml`.
- **rec-3844 / rec-3845** -- CLOSED by PR #1183. (Session-start preflight data showing them open is
  STALE.)

---

## 9. Open items / not yet ruled on

- Decision 76 clause 4 scoping annotation for Plan B (section 4, "ADDITION I flagged").
- Whether to file a carrier rec for the needs-completeness property in ADDITION to building the
  replacement guard (operator chose build; Decision 187 may be satisfied by the build alone).
- `signal-green` retirement exit criterion (A3) needs a concrete observation step in P2.
- P0's delegated brief has not yet been dispatched.

## 10. Workflow state

Step 6a decision-scout gates: run 1 (original approach), run 2 (Plan B), run 3 (revised Plan A) --
all returned FLAGS_FOUND. Scope has since changed again (three-way split), so EACH plan needs its
own fresh scout run before its Step 6b presentation. Step 9 plan-critique gate not yet run on
anything. Nothing written to `docs/plans/` yet.

---

## 11. P1-specific scout findings (gate run 4, FLAGS_FOUND, 144/144)

Run against the NARROWED P1 scope after the three-way split. Scout's own judgment on the split:
"the three-way split is sound -- the only cross-plan coupling found is rec-3046's shared acceptance
oracle."

- **Decision 177 -- RESOLVED, does NOT force `docs/DECISIONS.md` into P1's scope.** 177 constrains
  HOW a body correction lands; it imposes no obligation to annotate a stale premise. Decision 76's
  body stays untouched; the corrected fact routes to `git-ops.yaml`. Precedent cited: Decision 83
  corrected Decision 89's premise without editing it. (This was my flagged open question.)
- **Decision 181 [WARN] -- the only literal contradiction.** rec-3046's acceptance has FOUR
  conjuncts and **TWO** are unsatisfiable under P1's scope, not one:
  `grep -qE "head_ref, *'agent/'" .github/workflows/ci.yml` (P2 retires signal-green) AND
  `grep -q "agent/" scripts/verify_ci_workflow.py` (P0/P2 own that file). 181 point 1 is a standing
  prohibition: "no acceptance criterion is ever weakened to obtain green... whatever file it lives
  in." OPERATOR DECISION: re-scope, do not drop -- each removed conjunct lands on the sibling
  plan's carrier rec BEFORE P1's `update_rec`, and P1 states both migrations.
- **Decision 165 caveat [VERIFIED]** -- `scripts/ci/pr_conflict_signal.sh` carries `claude/` at
  THREE sites: the jq predicate at :72 and PROSE LOG STRINGS at :76 and :78. Any assertion over
  `script_text` membership is satisfied by the prose alone and reproduces the defect it replaces.
  The replacement guard MUST parse a structured declaration of the predicate, never whole-file
  membership.
- **Decision 168 [NEW]** -- `docs/contracts/git-ops.yaml` is Class D with evaluator
  `validate_git_ops_contract` and an `amendment_log` [VERIFIED at line 32]. Editing
  `branching_topology.branch_rule` [VERIFIED lines 88-90, carrying the stale `claude/...` premise
  verbatim] owes an `amendment_log` entry.
- **Decision 186 [NEW, conditional]** -- `rec-3046.context_v2_json` is null, so the closure-artifact
  gate's predicate is unset and a `Resolves:` closure will NOT be refused today. BUT if the plan
  sets an `escape_class` on this rec (the substring guard is a textbook gate escape), closure then
  owes a fix-bound `closure_artifact`. Decide deliberately.
- **Decision 163 [NOTE, sharpened]** -- the exact-set assertion makes narrowing the transitional
  window VISIBLE but nothing makes it HAPPEN; a carrier rec with a human-evaluated trigger is still
  discretionary. Suggested fix: make the trigger MACHINE-CHECKABLE -- have the sweep warn once no
  open `claude/*` head exists, so the window expires structurally rather than by memory.
- **Decision 191 [SPIRIT WARN, dischargeable]** -- confirms the earlier gate's delete-the-predicate
  reading OVERREACHES (191's binding clauses are scoped to table maintenance). Discharge by
  RECORDING: state in `git-ops.yaml` `branching_topology` and the plan rationale that the head-ref
  prefix is the only discriminator the `gh pr list` surface exposes for the agent-session
  population, that the exactly-pinned DECLARED SET substitutes for a declared class universe, and
  carry a reversal condition. Alternative discharge: price the enumerate-all-open-PRs variant and
  reject it on record.
- **Decision 55 [rationale citation]** -- "a missing and a passing oracle must never look alike" is
  the precise diagnosis of the substring guard. Name it in P1's rationale.
- **Decision 170 [VERIFIED]** -- `validate_pr_conflict_signal` is in `config/check_accounting_baseline.yaml`
  AND in the frozen `_BASELINE_SEED` at `scripts/checks/hygiene/validate_check_accounting.py:38`.
  Removal from the YAML baseline is a shrink (allowed); **`_BASELINE_SEED` must NOT be edited.**
- **Decision 131** -- `tests/checks/ci_guards/test_validate_pr_conflict_signal.py` is the correct
  mirror; `tests/test_pr_conflict_signal_wiring.py` targets a `.sh`, outside the Python mirror
  mapping, so keeping it at top level is correct.
- **Decision 187 [CONFIRMED]** -- no `tier-demotion-approved` marker owed; tightening is free and
  unmarked, and no check Entry is removed or glob-narrowed.
- **Decision 100 [NOTE]** -- no clause contradiction; record the measured basis and the n=1 caveat
  so retaining the sweep is a conscious choice rather than an inherited one.
- **T2.54:c1 [CITE]** -- element 2's "one named source" for the declared prefix set duplicates c1's
  traceability-annotation shape; adopt c1's convention rather than inventing a competing one.

## 12. Operator decisions taken after gate run 4

- Branch-scope guard home: **`validate_pr_conflict_signal.py`** (makes P1 self-sufficient, no
  dependency on P0's decomposition).
- Three-way split CONFIRMED, P0 delegated to a subagent planner (dispatched), P1 + P2 authored by me.
- rec-3046 oracle: **re-scope onto sibling carrier recs first**, do not narrow-and-note.
- Filter placement (jq vs bash): **Fable consult dispatched**, pending. The question is whether the
  head-ref predicate should stay in `gh --jq` (minimal diff, matches A4 literally, stays untestable
  by the existing shim) or move into the script's bash loop (one named declared set the guard can
  parse, testable through the shim, expiry notice for free -- at the cost of a wider diff in a file
  with deliberately careful documented errexit semantics).

---

## 13. Plan-critique round 1 (2026-09-15, post-compaction)

Both plans went through the mandatory zero-context plan-critique gate. **Both returned REVISE.**
Every finding below was independently re-verified against the tree before being acted on; two were
found overstated and are recorded as such rather than silently adopted.

### P1 -- 11 findings, all addressed

| Finding | Verified? | Disposition |
|---|---|---|
| F1 cites a sibling plan that does not exist | YES, half | See "overstated" below. ci.yml:315 brought INTO scope as a WIDENING (operator direction 2026-09-15) |
| F2 rec-3874 bundled, oracle undelivered | YES | VP step 9 now DELIVERS the oracle (`conflict-wake-probe` + `no native wake` into git-ops.yaml) |
| F3 git-ops.yaml stale premises at :176/:194/:201 | YES | Folded into the same edit; VP step 9 asserts all four stale phrases gone |
| F4 AGENTS.md waiver cites a pin that does not exist | YES | Waiver struck; VP step 7 strengthened to assert the RULE survives, not the wording |
| F5 TSV arity migration unnamed, step 8 `fix_if` forbade it | YES | Named as a mandated migration in execution steps; `fix_if` now discriminates migration from regression |
| F6 step 7 waiver misstates the negated-sweep lint | YES | Inverted clause struck and the correction recorded in place |
| F7 step 6 regex over-broad | YES | Anchored to the parenthesised array body |
| F8 acceptance criterion 3 "one-line edit" false of the system | YES | Reworded: narrowing is a coordinated 3-site edit |
| F9 "TWO undeliverable conjuncts" | YES, worse | True count was THREE. With ci.yml in scope it is now THREE DELIVERED / ONE CARRIED |
| F10 Decision 76 Context still states the dead premise | YES | Left to a later amendment; Decision 177 forbids in-place body edits |
| F11 residual consumers | YES | `pr-conflict-signal.yml` + `dependabot.py` brought into scope; VP step 10 sweeps them |

**Overstated, corrected rather than adopted:** F1 claimed `PLAN-pr-subscribe-wake-reconcile.yaml`
"states the opposite" and so contradicts the operator's A3. It is a MERGED HISTORICAL PLAN from
PR #352 (V1, pre-dates the `status`/`implementation_declared` schema). Plans in `docs/plans/` are
per-change briefs, not governance -- governance is DECISIONS.md and the contracts. Its premise
(CC-web has no native green wake) is the same one rec-3866 falsified. It is not a standing
directive and was not treated as one.

### P0 -- 7 findings, 6 addressed, 1 pending

- **BLOCKING, confirmed red on the branch:** `config/check_accounting_baseline.yaml` had no
  `test_obligations` row, so `validate_plan_documents` failed. FIXED; that check now passes across
  all 432 plan documents.
- **Patch-count dispute settled by measurement.** Plan said 70, critique said 79. Measured:
  **79 targets move** -- `_load` 70, `Path` 6, `_read_ci_rca_authority_sources` 3. The plan's "70"
  was the `_load` count mislabelled as the aggregate. Both figures were real; neither was the total.
- **Docstring count:** plan said 8, critique said 9. Measured **9** (5 under `scripts/`, 4 under
  `tests/`); the plan omitted `scripts/ci/reconcile_reachability.py:18`. Corrected.
- `_get_step_run_text` is `_ci_rca`-only (call sites 442-443), not cross-group. The placement is
  fine; the stated reason was false. Corrected.
- Patch move re-framed on **Python name-binding semantics** (the guard resolves `_load` from its
  own submodule globals), with Decision 169 kept as precedent rather than as the requirement.
- AC 7 narrowed to say what it actually sweeps, with every residual enumerated as a DECLARED
  exclusion (Decision 191) rather than an absence.
- **rec-3882 filed** for the five uncorrectable `guard_target`s: `_modified_entries` compares whole
  parsed mappings, so a provenance-only edit is indistinguishable from a `check_spec` edit and
  would hard-fail as tautological. `followon_recs: ["rec-3882"]`.
- **PENDING:** P0's decision-scout gate. Its `context` still reads `NOT_RUN`; a fresh zero-context
  scout is in flight and its verdict must replace that line before P0 enters `/implement`.

### Operator directions this round (2026-09-15)

1. **ci.yml:315 widens, it does not retire.** `agent/` joins `claude/` in the signal-green
   predicate. Retirement stays with the unwritten P2, consistent with A3's parallel-run sequencing.
2. **Keep the prefix discriminator; record the deferral.** Label-based self-registration at PR
   creation is the structurally better primitive and is available today, but P1 is a live-outage
   fix. The reversal condition now carries a review trigger that is NOT solely executor unfreeze:
   revisit at the first of (a) executor unfreeze, (b) a second measured miss, or (c) any change
   adding a third consumer of the prefix fact.

### Gate state

- Both plans validate against `PlanDocument` schema v4.
- `plan_obligations`: clean on both.
- `validate_plan_documents`: 432/432 PASS (was RED on P0 before this round).
- `validate_vp_replay` red-before: **16 graduate steps proven genuinely red**, 0 tautological.

## 14. P0 decision-scout gate (2026-09-15)

Ran fresh after the compaction, since P0's `context` still read `NOT_RUN` and the earlier run's
result was lost. **Verdict: FLAGS_FOUND. Decisions triaged: 145 of 145. CONTRADICT: 0.**

CITE: Decision 55, 59, 80, 104, 124, 128, 132, 163, 165, 169, 170, 187, 189.
**New relative to the draft's provisional list: 132, 187, 189.**

- **Decision 187** governs the four Entry `pre_globs` re-points. Verified to owe no
  `# tier-demotion-approved` marker: `_globs_narrowed()` measures the coverage superset at HEAD and
  its own docstring names the same-PR-rename case. Cited so a LATER narrowing is not assumed free.
- **Decision 189** is the red-before rule P0's six `waive` dispositions argue against; citing it
  makes that argument checkable.

### Two SPIRIT flags, both carried

- **Decision 131 [WARN] -- verified, and the plan's framing was wrong.** Clause 1 reads verbatim:
  "`scripts/executor/**` and `scripts/ops_portal/**` continue to return `None` on both rules."
  Exactly two prefixes. P0 removed `scripts/verify_ci_workflow.py` from
  `_CONCERN_SPLIT_TEST_PACKAGES`, registered nothing, and called the result "the sanctioned
  `scripts/ops_portal/**` disposition". Nothing sanctions a third prefix. The pin is RETIRED, and
  Decision 187's "silence is not a disposition" requires a carrier -> **rec-3883**. The plan's cost
  argument for declining it in scope (~30-test pin surface, zero behaviour change) is real and is
  kept; only the false "sanctioned/inherited" framing is struck. Precedent for the eventual fix sits
  in the same frozenset: `scripts/convergence_health/code_drift.py` is a registered package module.
- **Decision 187 [NOTE] -- the five `guard_target` rows.** Already carried by **rec-3882**, filed
  in the plan-critique round.

Both plans now carry a real scout verdict and a real plan-critique verdict in `context.gates`.

---

## 15. Plan-critique round 2 (2026-09-15) -- and what it exposed about red-before

Both plans were re-critiqued after revision, because the round-1 verdicts were REVISE and the
sequencing is "loop on REVISE; on PROCEED, merge". Neither plan had a PROCEED. **Both returned
REVISE again**, and round 2 earned its cost.

### The finding that matters: red-before cannot prove a command is correct

P1's VP step 9 (round 1) embedded backticks inside a double-quoted shell string:

    stale=[..., 'harness-assigned `claude/...`']

`bash` performed command substitution on it, so the fourth phrase reached Python as
`'harness-assigned '` -- a substring the CORRECTED contract still contains. Three consequences:

1. The step asserted three phrases, not the four the plan claimed.
2. It would have stayed RED after implementation, forever.
3. It is a `graduate` step, so the broken command would have been frozen into a standing
   verification-registry row.

**The red-before gate passed it**, classifying it `assertion_failed, exit 1`. That classification
was correct and useless: a broken command is red before AND red after. Red-before proves a step is
not tautological. It does NOT prove the step is correct, and it cannot -- the green-after tree does
not exist when it runs.

The fix on the second attempt was mangled AGAIN, differently: `'-\\"'` in the YAML reaches bash as
`\"`, where `\\` collapses to `\` and the following `"` CLOSES the string. Caught only because a
new check was run. Final form uses `chr(34)`/`chr(39)` and contains no backslash and no literal
quote character.

**Practice adopted for the rest of this work:** every new or changed VP command is (a) extracted
verbatim from the plan -- never re-typed -- (b) executed against the real tree and checked that the
failure is an `AssertionError`, not a shell error, and (c) executed against a SIMULATED
post-implementation tree to prove green-after. Steps 7, 8, 9 and 10 of P1 all passed all three.
Simulations swap files in and `git checkout --` restores them; both restores verified at 0
modifications.

### P1 round 2 -- 10 findings

Blocking: F1 (step 9 backticks, above), F2 (the AGENTS.md obligation asserted nothing about the
stale prefix -- it would have passed with lines 51 and 146 untouched), F3 (step 7 waived for
"pinning editorial prose" while steps 9/10 graduated over prose -- both defensible, not
simultaneously). F3 is resolved by stating the line once: STRUCTURAL ABSENCE of a token class
graduates; PRESENCE of specific wording waives; a step doing both takes the weaker disposition.

Substantive: F4 (execution step 7 rewrites `wake_signals.ci_green_comment`, which is open rec-3866's
exact oracle surface -- now a non-interference constraint, since half-satisfying an open rec's
oracle in passing is the rec-3867 defect in different clothes), F5 (the unmatched-prefix tally was
stdout-only in a `continue-on-error` job, so the NEXT rename would be as silent as this one -- now
mirrored to `GITHUB_STEP_SUMMARY`), F8 (step 14 checked rec status but never RAN the rewritten
oracles -- now runs both).

F7 is the same error class this plan already struck once: it claimed the decomposition plan "owns"
rec-3046's carried conjunct. It does not -- it makes room for that guard without adding it. Now
recorded as CARRIED AND UNOWNED. The identical claim was found and struck in P0's constraint 3.

### P0 round 2 -- narrow, all in one criterion

Six of eight revisions verified exactly (79/70/6/3 patch targets, `_get_step_run_text` call sites,
Decision 131's two-prefix family, the 145 denominator, both carrier recs). Three blockers, all in
acceptance criterion 7:

- It listed `validate_ci_workflow_guards.py:13,:69` as surviving docstrings while execution step 5
  updates those exact lines. The post-implementation residual is SEVEN, not nine -- the round-1 fix
  measured HEAD for a criterion that describes the end state.
- `docs/` is 84 hits across 31 files, not 83 plan documents: five are not plan documents
  (`SESSION_LOG.md`, three `AUDIT-*.md`, one contract).
- `audits/` (4 hits, 2 files) was neither swept nor excluded, so the Decision 191 completeness
  claim was false.

**rec-3884** filed for `validate_dispatch_gated_apply_topology.py:44`, which asserts the flat module
"sits at exactly 500 SLOC" -- already off by one (499) and false outright once deleted.

### Gate state after round 2

- Both plans PASS `PlanDocument` schema, both clean on `plan_obligations`, no advisory warnings.
- `validate_plan_documents`: 432/432.
- `validate_vp_replay`: 16 graduate steps red-before, 0 tautological.
- Recs filed across both rounds: rec-3882, rec-3883, rec-3884.

---

## 16. Plan-critique round 3 -- P1 (2026-09-15)

REVISE again, five blocking findings, all four mechanical ones independently re-verified before
action. **This triggers the stopping rule set before the round ran: apply round 3, do NOT start
round 4, put the convergence question to the operator.**

| # | Finding | Verified how |
|---|---|---|
| F1 | Step 9 `graduate` violated the graduation principle this plan itself states -- it carried two English-phrase assertions beside its structural sweep | Read the step against its own waiver text |
| F2 | The mandated transitional-zero notice breaks three existing `summary_text == ""` assertions (:244, :262, :320), and step 11's `fix_if` routed :244 to "retry regression" | Three assertion sites confirmed; critic reproduced the failure empirically |
| F3 | rec-3046 accounting wrong for the SECOND time | Conjunct-by-conjunct against a simulated tree: C3 confirmed unsatisfiable (`grep -c 'agent/' scripts/verify_ci_workflow.py` = 0) |
| F4 | The carrier rec named `scripts/verify_ci_workflow.py` -- a path the SIBLING plan deletes | Confirmed: P0 scope row `action: Delete` on that exact path |
| F5 | The `rollback` field was false | `validate_check_accounting:231-243` computes `grown = current - base(origin/main)`; a revert re-adding the entry FAILS |

### Two patterns worth carrying forward

**The "names a surface someone else removes" error, third instance.** It was struck from P1's
constraints (the signal-green ownership claim), struck from P0's constraint 3 (the identical claim),
and then committed again in P1's own carrier-rec instruction. Three independent occurrences in one
work item means it is not carelessness, it is a structural blind spot: a plan reasons about the tree
as it is now, while sibling plans on the same branch are changing it. Nothing mechanical catches
it -- the sibling plan is committed and readable, but no check cross-reads plans on a branch.

**Accounting slippage under Decision 181.** The rec-3046 conjunct count has now been wrong twice.
Round 2 fixed "two undeliverable" to "three delivered, one carried"; round 3 showed that scoring a
permanently-unsatisfiable conjunct as "delivered by OBSOLESCENCE" is precisely the weakening
Decision 181 clause 1 forbids. Correct accounting: TWO delivered, ONE superseded-and-recorded, ONE
carried. Also newly named: rec-3046's title says "repoint CI wake filters off claude/" and this plan
KEEPS claude/ transitionally, so the acceptance rewrite NARROWS the rec -- legitimate under the
operator direction, but it must be recorded as a narrowing, not presented as completion.

### Also fixed

F6 (ci.yml:311-312's comment becomes false the moment the predicate widens, in a plan whose thesis
is that stale self-descriptions rot), F7 (the rec-3866 non-interference constraint was prose-only --
now an assertion in waived step 7: `'NOT a CI-success webhook' in g` and
`'check_suite.completed' not in g`, both halves confirmed to be the current state), F8 (the AGENTS.md
obligation claimed to "pin the rule"; it is a waived step creating no standing row, while the
previously-pinning registry entry goes vacuous -- coverage is NET LOST, deliberately, and the
trade-off is now stated instead of overclaimed), plus the acceptance-criterion-1 conjuncts
(GITHUB_STEP_SUMMARY mirror, retirement notice) that no step or obligation asserted.

Step 7 is now the single home for every presence-of-wording assertion; step 9 is pure structure.
All four changed commands re-verified: zero quoting hazards, red-before on the intended assertion
(no shell errors), and steps 7 and 9 proven green-after on a simulated tree, restored at 0
modifications.

## 17. Plan-critique round 3 -- P0 (2026-09-15)

REVISE with exactly ONE blocker, mechanically verified, one-token fix. P0's trajectory across three
rounds is 7 findings -> 3 blockers (all in one criterion) -> 1 blocker. That is convergence.

**The blocker, and why it matters more than its size.** `test_obligations` for `_manifest.py` named
`test__manifest.py::TestCiGuardsManifest::test_ci_rca_trigger_is_gated_on_its_full_closure`. That
class exists (line 14) but the method lives in `TestGatedEntryInputClosures` (line 42, method at 61).
Run verbatim the selector returns `ERROR: not found ... (no match in any of [<Class
TestCiGuardsManifest>])`, pytest exit 4 -- **before AND after implementation**. The row claimed
"red before, green after"; in fact it was `target_absent` for a wrong-class reason at both ends, so
it could never discriminate. It escapes every deterministic gate: `plan_obligations` reports no
unmet obligation, `validate_plan_documents` checks only that exactly one of
`test_selector`/`command` is non-blank, and `validate_vp_replay` replays `verification_plan` steps
and never touches `test_obligations` selectors.

### The pattern across all three rounds, stated plainly

Three of the most serious findings in this work are ONE defect class: **an assertion that fails for
the wrong reason, and therefore can never discriminate.**

1. P1 round 2 -- VP step 9's backticks: bash command substitution silently rewrote the assertion.
2. P1 round 2 -- the FIX for that was mangled differently (`\\"` closing the shell string early).
3. P0 round 3 -- a test selector naming the wrong class.

All three would have merged as permanently-red or permanently-vacuous checks. All three are
mechanically detectable. None is detected today. Red-before cannot catch them by construction: it
proves a step is not tautological, and a broken assertion is red before AND after.

**Sweep run over both plans as a result:** all 12 `test_selector` node ids resolved or are declared
Create targets. The `_manifest.py` one was the only genuine dangling pointer.

### Also applied (nits)

N1 (step 10's docstring count is a HEAD figure, now labelled as such against criterion 7's
post-implementation seven), N2 (the step-4 waiver cited 617 for two directories while the step's own
selector spans three and expects 728 -- both measured, both now stated), N5 (the Decision 191
citation is analogical, not literal governance -- 191 clause 1 governs DuckLake maintenance scope),
N6 (a tenth residual: `main()`'s usage string names the bare basename `verify_ci_workflow.py` and
moves verbatim into `_cli.py`; a bare basename, so criterion 7's path-scoped sweep correctly misses
it, and ZERO-BEHAVIOUR-CHANGE argues against touching it).

---

## 18. Plan-critique round 4 -- P1 (2026-09-15). The loop is NOT converging.

REVISE, six findings. Report integrity checked first, given that a branch switch had briefly swapped
the working tree during the run: its Files Read lists all 10 scope files, its claimed 730-line plan
matches `wc -l` exactly, its red-before table matches measurements taken independently, and it left
`git status --porcelain` empty. The report is sound.

### The finding that changes the recommendation

**FOUR of the six findings are regressions introduced by ROUND 3's own fixes.**

| # | Finding | Introduced by |
|---|---|---|
| F1 | `rollback` still not executable | round 3's fix for `rollback` |
| F2 | step 9's `graduation_check_id` claims probe coverage its command no longer carries | round 3 moving the probe assertions to step 7 |
| F4 | step 9 silently required BLOCK-style YAML and forbade `claude/` in any new prose | round 3's structural rewrite of step 9 |
| F5 | step 1's `-k declared_prefixes` selects neither new observability test | round 3 adding those obligations |
| F3 | AGENTS.md has ONE byte of prose headroom | pre-existing, missed by rounds 1-3 |
| F6 | disclosed residuals carry no owning rec id (Decision 181 clause 2) | pre-existing |

P1's finding counts by round: **11 -> 10 -> 5 -> 6**. It went UP. The loop is trading defects, not
removing them, and each round's fixes perturb interlocking assertions elsewhere in a 730-line plan
with 14 VP steps. That is a COMPLEXITY signal, not a diligence one.

**The `rollback` field specifically has now been wrong twice, in opposite directions.** Draft 1
claimed the shrink-only ratchet made a plain revert safe -- false, leg (c) fails. Round 3 fixed that
by exempting the baseline line -- which created a leg (a) failure, because reverting the
squash-merge also reverts the `examined()/skipped()` declaration, leaving the module undeclared AND
unbaselined. Verified by simulating that exact state and running the real check:
`validate_pr_conflict_signal: declares no examined()/skipped() outcome and is not in
config/check_accounting_baseline.yaml`. Round 3's text was internally self-contradictory too,
asserting both that the guard "returns to its prior row" and that it "keeps its declaration". Only
one post-rollback state is legal: **declared AND unbaselined**.

### F4 fixed by SIMPLIFICATION rather than documentation

Round 3's step 9 compared each raw LINE against the declared set, which silently required block-style
YAML. The fix was not to document that trap but to remove it: the command now walks PARSED YAML
values keyed by path. Proven green-after under BOTH block and flow style, where round 3's version
reddened on flow. The one real remaining constraint -- no string value outside the
`agent_branch_prefixes*` keys may contain `claude/` -- is now stated rather than latent.

### F3 is the catch no earlier round could have made

`config/prose_budgets.yaml:36` caps S1 `root_ambient_load_set` at 18943 bytes; the current set is
18942 (AGENTS.md 18931 + CLAUDE.md 11). **One byte.** `validate_prose_limits` is blocking in the
fast tier. The plan mandates editing AGENTS.md at two lines; a net-additive reword fails CI, and
step 12's `fix_if` attributed a fast-tier red to entirely different causes. Now a stated constraint
(the reword must be net non-additive; no second contract pointer -- line 143 already has one) and
named in the fast-tier `fix_if`.

### Gate state

Schema PASS, `plan_obligations` clean, `validate_plan_documents` 432/432, 9 graduate steps
red-before with zero tautological, and a hazard scan over all 14 commands returning zero backticks.
