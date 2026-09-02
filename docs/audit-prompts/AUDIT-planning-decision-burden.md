# AUDIT: Human-Decision Burden in the Planning Workflow (Bootstrap-Era Remedies)

## TASK

Audit the human-decision burden carried by the interactive planning workflow (`/orient` ->
`/plan` -> `/implement`) against three named burdens, each with candidate remedies to
adjudicate:

- **B1 -- plan-scope splits.** When a planning session splits a plan, the second half has no
  mechanism that carries it back to a future `/plan` session. The requester's candidate: the
  implementation session closes out by drafting a paste-ready follow-on `/plan` prompt.
- **B2 -- design forks.** Design forks reach the human at a technical depth the human need not
  adjudicate, and a fork resolved sensibly today can contradict work the roadmap already plans.
  The requester's candidates: an inward "roadmap scout" subagent modelled on `decision-scout`; a
  mandatory Fable industry-practice consult before any open question reaches the human; or both.
- **B3 -- gate non-convergence.** After three REVISE rounds the plan-critique gate's rule is to
  escalate to the human with the unresolved findings and a menu of human choices
  (accept-with-deferral / re-scope / abandon); no agent-side procedure is stated before or after
  that escalation. The requester has no candidate and asks what the procedure should be; one
  seed is a further Fable consult.

Three jobs, in order: (1) verify each burden against the repository as it stands -- CONFIRMED,
PARTIAL, or REFUTED; (2) adjudicate every pinned candidate remedy (fifteen, listed under Q1-Q3)
to a pinned verdict, and for every burden that is not REFUTED leave it with at least one adopted
mechanism -- originating one when no candidate survives; (3) rate the workflow's human-in-the-loop
design against an external checklist, sweep for at most three burdens the requester did not name,
and answer the questions the requester did not think to ask.

Seven candidates originate from the requester's anecdotal experience (B1-R1..R3, B2-R1..R3,
B3-R1; `origin: requester`) and eight were authored by this prompt's author (B1-R4/R5,
B2-R4/R5, B3-R2..R5; `origin: composer`); none rests on telemetry, a Decision, or a roadmap
item, and neither origin is evidence. Treat each as never-evaluated. REJECT is a fully
acceptable verdict for any
candidate; "burden real, no remedy" is NOT an acceptable outcome for a confirmed burden. An
INSTRUMENTATION-ONLY remedy -- a record or measurement with a declared decision trigger and no
other mechanism -- is an admissible originated remedy when you judge the burden unmeasured
(NS-E); it still needs a landing surface, a carrying cost, and, for B1, a sunset condition. Do
not manufacture agreement with the requester, and do not reject a candidate merely because a
prior audit rejected something with a similar name (see the traps below).

Deliverables: `audits/planning-decision-burden-<sha>.yaml` and
`audits/planning-decision-burden-<sha>.md`. The ONLY files you create or modify in the
repository tree are those two. Regenerating gitignored local caches per SETUP is expected and
does not breach this; never commit them. You draft; the human disposes. You implement nothing, file
nothing through the recommendation portal, and modify no audited surface.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.** Every observation in the GROUNDING
MAP is stated neutrally and deliberately carries no adjective implying a defect. **A run that
merely confirms the candidates below has failed.** The requester experiences these burdens; that
is evidence the burden is felt, not evidence that the workflow is the cause or that the proposed
remedy is the fix.

**The candidate set is exactly 18 items**: the three burdens B1-B3 and the fifteen candidate
remedies B1-R1..R5, B2-R1..R5, B3-R1..R5 pinned under Q1-Q3. Nothing else is a candidate. The
GROUNDING MAP is evidence, not an accusation list: nothing in it is a candidate merely by
appearing there.

Per-candidate adjudication, with its mapping to the output contract pinned:

- A BURDEN verdicted CONFIRMED or PARTIAL files AT LEAST ONE and AT MOST THREE `findings[]` rows:
  one for the burden itself (the defect in the current workflow that produces it) and up to two
  more for DISTINCT defects you traced while establishing it (e.g. an inconsistency between two
  rules is a different defect from the absence of a third). A burden verdicted REFUTED files NO
  finding and gets exactly one `rejected_candidates[]` row naming the compensating control. The
  at-least-one rule binds B1-B3 only, with one exception: a B2 floored at PARTIAL by an
  INDETERMINATE sub-burden (Q2) may carry zero findings. See also the unnamed-burden rule below.
- A legal NON-ACCRETIVE terminal state for a burden that is not REFUTED: an `adopted_set` whose
  single entry is an originated remedy with `vehicle: none`, `instrumentation_only: false`, and
  `owning_end_state_item` naming the tier_item or Decision that already owns the fix --
  admissible only when you judge the owner's remedy sufficient (its finding is then
  `planned-unbuilt`, not `planned-insufficient`) and its `sunset_condition` names the owner's
  landing.
- A REFUTED burden's five candidate remedies are all verdicted `reject` or `defer-to-roadmap`
  by construction and its `adopted_set` is empty. If you judge one of them sound for a DIFFERENT
  burden that is not REFUTED, re-home it: add an originated remedy under that burden whose
  `rationale` opens with the source id (e.g. "from B2-R4"); the original keeps its `reject`.
- A REMEDY never files a finding by being adopted or rejected. Its disposition lives ONLY in
  `burden_dispositions` and is never mirrored into `findings[]` or `rejected_candidates[]`. A
  remedy's adjudication may EXPOSE a defect in the current workflow; that defect files as a
  finding attributed to the burden it belongs to, subject to the per-burden cap above; when that
  burden is REFUTED, the defect files instead as `surface: shared, burden: none` against the
  three-finding outside-burden budget below.
- An UNNAMED burden surfaced under Q6 (cap 3; ids B4-B6 in the order surfaced) gets its own
  `burden_dispositions` entry and files AT MOST ONE finding, and only when it meets the same
  evidence bar as B1-B3. A B4-B6 entry MAY carry `burden_verdict: PARTIAL` with zero findings
  (its evidence and remedies then live only in the disposition, `confidence: HYPOTHESIS`) --
  this overrides the at-least-one rule for unnamed burdens.
- A GROUNDING MAP fact you trace to a defect outside every burden files AT MOST THREE findings
  in total across the whole audit, `surface: shared`; a fact you considered and dismissed goes to
  `rejected_candidates[]`.
- Per finding, `roadmap_crossref.classification` is INDEPENDENT of `confidence`: a defect nobody
  owns -> `novel`, whatever its confidence; owned by an item whose remedy is insufficient or
  unbuilt -> `planned-insufficient` / `planned-unbuilt`; fully covered by the owning item ->
  `rejected_candidates[]`, never a finding. A degraded run changes confidences, never
  classifications.
- A `surface: shared` finding lists in `surfaces_touched` every surface whose files or items its
  evidence names (per the SCOPE table) and counts against each of them; an empty list means it
  counts against none. Per-surface maturity reads `surfaces_touched`.

Hard ceiling: `total_findings` <= 15. If you find yourself above it, you are counting remedies
or restating one defect under several names.

## READ FIRST -- DISAMBIGUATION TRAPS

- **"Convergence" names two things.** In `logs/.preflight-report.json` (`convergence_health`,
  `convergence_sensor_liveness_alert`, `convergence_rca_gap_alert`), in `/orient`'s Best-Practices
  Health Check, and in `docs/contracts/deploy-paths.yaml`, convergence is the TERRAFORM apply
  state (red/green convergence record). In this audit, convergence means ONLY whether a
  gate's PROCEED/REVISE series terminates. The terraform sense is out of scope entirely; do not
  read those preflight keys as evidence about gate rounds.
- **"Split" is overloaded.** The repository uses "split" for config directory splits,
  history/current table splits, IAM identity-policy splits, verb splits, and more. A
  case-insensitive file-level search (`grep -l -i split docs/plans/PLAN-*.yaml`) matches 219 of
  366 plans. Only PLAN-splitting (one intended body of work authored as two or more plans) is in
  scope. The tight pattern that isolates it is given in EMPIRICAL PASS.
- **Inward roadmap scout vs outward world scout.** The requester's B2 candidate is an INWARD
  alignment check against `docs/ROADMAP-PLATFORM.yaml` (planned future work). The prior audit
  `audits/planning-workflow-scaling-369a963a.yaml` REJECTED a proposal named "P10 per-plan world
  scout" -- an OUTWARD industry search per plan, dominated by a portfolio-grain horizon scan
  (P11). These are different mechanisms with different search targets. P10's rejection is not a
  verdict on the roadmap scout; do not inherit it, and do not ignore it either -- its
  cost-profile argument may or may not transfer, and you must say which, in B2-R1's `design_notes`.
- **Two grains of "follow-on plan".** Tier item T-1.23 (complete) built follow-on planning at
  ROADMAP-CRITERION grain: `/orient` emits a follow-on `/plan` prompt for an `in_progress`
  tier_item with open exit criteria, driven by `needs_followon_plan` in the preflight cache. The
  requester's B1 is a DIFFERENT grain: a split half that is not a roadmap criterion and belongs to
  no tier_item -- work whose ruled long-term home is a recommendation (see the NORTH STAR
  bootstrap-vs-end-state principle). T-1.23 is an extension target you must argue against
  before proposing anything new; it is not already the fix.
- **The prior audit is a dedup source, not an inherited verdict.** `audits/
  planning-workflow-scaling-369a963a.yaml` audited the `/plan` pipeline as a SCALING surface and
  adjudicated sixteen proposals. Its dispositions bind your DEDUP DISCIPLINE (a finding it already
  owns is not novel) and its rejections carry stated revisit conditions you must check. Its
  verdicts are not yours: it did not audit human decision load, and it predates the requester's
  framing. Note also that none of its adopted proposals has landed as a Decision, contract change,
  or filed recommendation (GROUNDING MAP).
- **The missing wave-3 plan is not a lost half.** `docs/plans/` holds
  `PLAN-audit-remediation-wave-1`, `-wave-2-*`, `-wave-4-*`, `-wave-5-*` and no wave-3. Git
  history shows `plan(audit-remediation-wave-3): approved plan (#412)` merged (commit
  `207c6e31`) and the file later deleted by the bulk cleanse commit `7b67e21d` (#969). Decision
  174 rules that a retired planning artefact's provenance lives in git history. This gap is not
  evidence for B1.
- **"Fable" is two things.** It is a value of the `Agent` tool's `model` enum
  (`sonnet | opus | haiku | fable`) AND the name of the overseer skill's advice-consult protocol.
  The protocol prescribes a fresh-context subagent on that model; the model can be dispatched
  without the protocol, and the protocol's settled-vs-contested framing is the substantive part.
  When a candidate says "Fable consult", adjudicate the PROTOCOL and its trigger, not the model.
- **`/overseer` is a meta-layer, not a tier.** Decision 90 pins four tiers and does not mention
  the overseer; the meta-layer rule lives in the overseer skill (`overseer/SKILL.md:15` and
  `:29`, `meta_layer_not_tier: true`), `docs/contracts/overseer-dispatch.yaml:4`, and
  `AGENTS.md:102`. A remedy that routes B1/B2/B3 through the overseer is admissible only if it
  composes existing tiers.
- **Where a split is decided, and which split producers are live.** Two producers are
  unambiguous: the planning skill's Complexity Assessment freeze override
  (`planning/SKILL.md:244-253`: "split into multiple atomic IMPLEMENTATION plans during this
  planning session") and `/plan` Step 9's escalation menu (`plan.md:101`). A third is contested
  inside plan-critique Phase 2 step 8: the branch question at `:39` asks "Too large (suggest
  split)?" under the STRATEGIC branch only (the IMPLEMENTATION branch at `:40` asks only "Are all
  scope entries necessary?"), while the shared output template at `:136` reads "[Area or file
  1]: appropriately scoped / too large (suggest split into: X, Y)" -- and "or file" is the
  IMPLEMENTATION rendering. Whether that template makes the critic a live split producer for
  IMPLEMENTATION plans is yours to adjudicate in DD-A; assume neither answer. B1 is about what
  happens to the second half AFTER a split is decided.
- **"Step 8" names four things.** `/plan` Step 8 writes the plan (`plan.md:85`); `/implement`
  Step 8 captures friction (`implement.md:112`); plan-critique Phase 2 step 8 evaluates scope
  (`plan-critique/SKILL.md:38`); planning Data-Model step 8 is the Fable escalation
  (`planning/SKILL.md:280`). This prompt qualifies every reference; do the same in your
  deliverables.
- **`P<n>` and `NS` ids.** Every `P<n>` in this prompt (P2, P3, P4, P5, P6, P10, P11, P13) names
  a proposal adjudicated by the prior audit `audits/planning-workflow-scaling-369a963a.yaml`;
  this prompt's METHOD phases are M1-M9 and never `P`. `NS-A..NS-F` are this prompt's North Star
  principles; `NS.1-NS.5` are the roadmap's `north_star.principles` ids that plan-critique step 7
  scores against (`plan-critique/SKILL.md:36`). Do not conflate either pair.
- **"CONFIRMED" names two things.** `burden_verdict: CONFIRMED` means the burden is real;
  `confidence: CONFIRMED` means a claim is traced to file:line or a sampled artefact. A degraded
  run downgrades the second and never the first.
- **"Round" and "REVISE" name two gates.** In SCOPE's vocabulary, Q3, and the EMPIRICAL PASS
  histogram they refer to the audited plan-critique gate; in the SELF-VERIFICATION GATE they
  refer to your own verifier passes, recorded in `meta.self_verification.rounds`, which has no
  relation to the corpus histogram.
- **"The escalation menu" names two menus.** At the Step 9 cap, `plan.md:101` offers "narrowing
  scope, re-deriving the approach, or split the plan into smaller IMPLEMENTATION plans";
  `planning/SKILL.md:597`, which `plan.md:101` delegates to, offers "accept-with-deferral /
  re-scope / abandon". The split option exists only in the command's menu. Route this into DD-A
  (the split producer) and Q3 (what the human is actually offered).
- **Audit outputs live under `audits/`, prompts under `docs/audit-prompts/`.** Your deliverables
  go under `audits/`; never write under `docs/audit-prompts/`.

## SCOPE

Surfaces, each with its state:

| id | surface | state |
|---|---|---|
| S1 | `/plan` pipeline: `.claude/commands/plan.md` + `.claude/skills/planning/SKILL.md` | built |
| S2 | `/implement` pipeline: `.claude/commands/implement.md` + `.claude/skills/implement/SKILL.md` | built |
| S3 | gate subagents: `.claude/skills/plan-critique/SKILL.md`, `.claude/skills/decision-scout/SKILL.md` | built |
| S4 | `/orient` follow-on machinery + exit-criteria ledger: `.claude/skills/orient/SKILL.md`, `.claude/commands/orient.md`, `scripts/platform_roadmap_state.py`, `docs/contracts/exit-criteria-ledger.yaml` | built (T-1.23 complete) |
| S5 | Fable advice-consult protocol: `.claude/skills/overseer/SKILL.md` Fable section, `.claude/commands/overseer.md`, `docs/contracts/overseer-dispatch.yaml#fable_triggers`, plus its two conditional call sites in S1/S2 | built; wired conditionally |
| S6 | plan artefact schema + mechanical checks: `scripts/roadmap/plan_document.py`, `scripts/roadmap/plan_obligations.py`, `scripts/prompt_compliance.py`, `config/prose_budgets.yaml`, `config/structural_size_budgets.yaml` | built |
| S7 | carrying surfaces a remedy could land on: `docs/contracts/decision-entry.yaml` (routing rule), `docs/DECISIONS.md`, `docs/ROADMAP-PLATFORM.yaml`, the recommendation portal (`scripts/ops_data_portal`), PR bodies (Decision 115) | built |

Vocabulary:

- **Burden**: a decision the human currently makes, or a memory the human currently keeps, that
  the workflow could carry instead.
- **Remedy**: a mechanism that removes or narrows a burden. A remedy has a **landing surface**
  (the file(s) it changes), a **carrying cost** (bytes or lines added there, against the
  measured headroom), and a **runtime cost** (subagent dispatches, estimated tokens, and
  estimated wall-clock added per `/plan` or `/implement` session, with the basis of the
  estimate; the dispatch count is always stated, and tokens and wall-clock may read
  "unmeasured -- no substrate" because the repository records neither). An
  **instrumentation-only remedy** adds a record or measurement with a declared decision trigger
  and no other mechanism.
- **Bootstrap era**: the present operating state -- Decision 67's STRATEGIC/executor freeze is
  active, no autonomous consumer reads the recommendation queue, and the priority-queue producer
  (T4.3) has not landed. **End state**: the executor consumes the rec queue (Decision 90's fourth
  tier live; CD.17 reversal).
- **Sunset condition**: the observable event at which a bootstrap-era remedy retires or hands
  over to its end-state successor. Every B1 remedy MUST declare one.
- **Decision load**: the count and depth of choices put to the human per plan. "Depth" means how
  much technical context the human must absorb to choose.
- **Round**: one dispatch of a gate subagent producing a verdict. "Convergence" (gate sense):
  the series terminates in PROCEED. "Oscillation": a finding recurs after being addressed.
  "Converging series": each round's finding count is strictly smaller than the prior round's and
  no finding recurs.
- **Mechanical defect**: a plan defect a deterministic check could catch (missing field,
  wrong enum, absent command, budget crossing). **Judgement defect**: one requiring reasoning
  about adequacy or design.
- Gate verdict enums: decision-scout `NO_FLAGS | FLAGS_FOUND | BLOCK`; plan-critique
  `PROCEED | REVISE`; report-critique `PROCEED | REVISE | BLOCK`.

Out of scope, one line each: the terraform convergence pipeline; the executor's own planning
path (`scripts/executor/*`, frozen); the REPORT-ONLY plan type's report-critique gate except as a
comparator for B3; telemetry capture design (T2.36/T3.20) except as a dedup owner; the content
of any specific plan's design; the `/audit` and `/develop-executor` workflows.

**Trust-nothing clause.** Obtain every file, line, size, and count by reading the file or
running the command -- trust no number quoted here; re-derive from the repo and record any
non-resolving anchor in `meta.stale_anchors`. Anchors below were resolved against
`origin/main` at `939eb789`; the tree you audit is whatever `origin/main` is when you run SETUP.

## SETUP

Run these, in order, before anything else.

```
git fetch origin main
git rev-parse --short origin/main          # this sha IS the audited tree; use it everywhere
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

Then cut the audit branch IMMEDIATELY, before drafting anything:

```
git switch -c audit/planning-decision-burden-<sha> origin/main
git branch --show-current                  # must NOT print "main"
```

Branch first because a `PreToolUse` hook (`.claude/hooks/never_on_main.py`) blocks the
`Edit`/`Write`/`MultiEdit`/`NotebookEdit` tools, and any Bash command containing `git commit` or
`git push`, while the current branch is `main`. It does not block Bash-mediated writes, so the
preflight command runs fine on `main`; drafting a deliverable with `Write` would not. IF the
branch already exists, `git switch` to it instead. IF you are ever on `main` later, stop and
re-cut before writing.

The preflight call populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`,
which DEDUP DISCIPLINE and the EMPIRICAL PASS require. The preflight also opens no telemetry
session by itself; do not pass `--open-session`.

**Degraded paths -- never abort, never improvise:**

- IF preflight fails for ANY reason (credentials, egress, import error, or a partial success
  where the report is written but the recommendations sync did not complete): do NOT abort. Set
  `meta.degraded_dedup: true`, set every `findings[].confidence` and every
  `candidate_remedies[].confidence` and `originated_remedies[].confidence` under
  `burden_dispositions` to `HYPOTHESIS` (this overrides the file:line CONFIRMED rule for the
  duration of a degraded run; `roadmap_crossref.classification` is unaffected), set every
  `dedup_hit_count` to null, skip the recommendation-grain rows of the EMPIRICAL PASS (record
  `empirical_sample.recs: []`; `truncated` then reflects the plan reserves only), and proceed.
  `degraded_dedup` never touches `burden_verdict` or any sub-burden verdict. Dedup then runs
  against the git-tracked sources only (`docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`,
  `audits/*.yaml`).
- IF `logs/.recommendations-log.jsonl` is absent or empty: same flag, same downgrade.
- IF an anchor in this prompt does not resolve: record it in `meta.stale_anchors` and re-derive
  the fact from the repo before relying on it.
- IF `bin/venv-python -m scripts.validate --pre` is run and fails on something unrelated to your
  two files: record the failing check name in `meta.contract_notes` and proceed. Repo-wide
  validation is advisory outside CI here (Decision 73). Never fix it -- that breaches the write
  boundary. A clean YAML parse of your two deliverables is the real pre-push gate.
- IF the `Agent` tool is unavailable: see the SELF-VERIFICATION GATE's degraded path.

Read `docs/PROJECT_CONTEXT.md` in full. Do NOT read `docs/ROADMAP-PLATFORM.yaml` or
`docs/DECISIONS.md` in full -- both are large. Use targeted projections: a
`bin/venv-python -c` `yaml.safe_load` projection over the roadmap's `tier_items[]` and
`candidate_decisions[]`, and `rg "^## Decision N:"` plus `awk` range extraction for named
decision sections. Read every S1-S6 file in full; they are the audited surfaces.

## NORTH STAR

The ideal-state bar, as named principles the rubric references. Each is a bar you judge every
surface and every remedy against -- argue the case, do not pattern-match.

- **NS-A Bounded authority.** Agents propose; the human disposes. Reducing the human's decision
  load must never silently transfer authority. A remedy that removes a human decision must say
  which decision, why the agent can now hold it, and what evidence would revoke that.
- **NS-B Agent-first persistence.** State that matters survives the session boundary in a
  machine-parseable store the next agent already reads. A chat message, a transcript, and a
  file nothing reads are not persistence.
- **NS-C The rec queue is the destination form.** Per `docs/contracts/decision-entry.yaml`'s
  `work_item` routing row, recommendations are the DESTINATION form for durable sequencing work
  and the roadmap is the BOOTSTRAP that recs supersede. A bootstrap-era remedy is a bridge with a
  declared sunset, never a second permanent queue.
- **NS-D Consistency over local optimality.** For a design fork whose options are equally
  valid, what matters is that ONE option is chosen, applied consistently across the repository,
  and persisted where the next agent finds it. The human need not adjudicate the technical
  detail of such a fork; the human must adjudicate a fork that changes authority, spend, a
  public surface, or an irreversible act.
- **NS-E Evidence before mechanism.** A signal is not proof. A remedy for a burden nobody has
  measured must either carry its own measurement or be bounded and sunset so its yield can be
  observed.
- **NS-F Shrink, do not accrete.** T2.56 c1 commits the ambient skills layer to measurably
  shrink. A remedy is rated on whether it lands as machine-enforced norm, contract, or code
  rather than as more prose an agent must read every session. This is a rated dimension (VD3),
  not a veto: the requester ruled that carrying cost never vetoes a remedy and that every
  confirmed burden leaves with a mechanism. The counterweight is disclosure -- every adopted
  remedy names the relief valve it takes on each landing surface (Q4's `disposition`), and an
  unauthorized raise is admissible but rated `weak` on VD3 and VD5 and listed in the `.md`.

## THE QUESTIONS

Every question is first-class with its own `question_answers[]` entry. Verdict enums are pinned
per question.

### Q1 -- B1, plan-scope splits (verdict: CONFIRMED | PARTIAL | REFUTED; prose points to `burden_dispositions.B1`)

**The burden as stated.** During `/plan`, the complexity heuristic and the critique gate's
escalation menu can both produce a split into two or more IMPLEMENTATION plans. The plans are
usually sequential and dependent (the second cannot be planned in detail until the first lands).
The human must remember to open a new planning session for the second half. The requester
judges two alternatives unworkable a priori -- planning both halves in parallel (they are
dependent) and planning the second half in a subagent after the first lands (the planning agent's
context is then an overseer's) -- but you must adjudicate them anyway.

**Pinned framing you must apply and state in your answer (a ruling, not a finding).** B1's work
is NON-roadmap grain: a split half is not a tier_item exit criterion. Its ruled long-term home is
a recommendation the end-state executor consumes (NS-C; Decision 67 freeze; T4.3 producer not
landed). So every B1 remedy is a BRIDGE: it must declare its sunset condition, and it must be
compared against extending T-1.23's shipped machinery before anything new is proposed.
**What you establish, not assume:** whether a follow-on rec has a surfacing path today. The
GROUNDING MAP records what `/orient` reads (S4) and how `/plan` suggests recs (S1); trace them,
apply the rec counterfactual in EMPIRICAL PASS, and verdict B1 on that evidence -- B1 is REFUTED
if you find a property-matched surfacing path. Decision 115 rules where transient handoff state
may live (PR description for the ephemeral half; plan YAML or roadmap exit criteria for the
durable half; no standing handoff files) and carries a reversal condition you must quote and
test against B1.

**Candidate remedies (adjudicate every one):**

- **B1-R1** (`origin: requester`) Implementation close-out drafts a paste-ready follow-on
  `/plan` prompt. Sub-questions you must answer in `design_notes`: where is the prompt persisted
  (chat only, PR body per Decision 115, a plan-YAML field, a rec), who reads it next session,
  and what makes it appear at the right moment rather than in a place the human must remember to
  look.
- **B1-R2** (`origin: requester`) Plan both halves in the same session, in parallel.
- **B1-R3** (`origin: requester`) Plan the second half in a subagent dispatched after the first
  half lands.
- **B1-R4** (`origin: composer`) File the second half as a recommendation carrying a follow-on marker (a tag, a
  source value, or a `dependencies` edge to the first plan's rec or slug), and extend `/orient`'s
  section 5/6 to surface follow-on-marked open recs as ready-to-paste `/plan` prompts, ranked
  after in_progress follow-ons. This extends T-1.23 from criterion grain to rec grain.
- **B1-R5** (`origin: composer`) A typed successor link on the plan artefact (a `PlanDocument` field, or a pinned
  grammar for one `context:` line) naming the successor's intent, that `/orient` or preflight
  reads to emit the prompt. Note the schema forbids extra keys and `/orient` reads only the
  preflight cache today.

For each: `verdict` per the pinned remedy enum; `landing_surfaces`; `carrying_cost` against
measured headroom; `runtime_cost`; `human_decision_removed` (what the human stops deciding or
remembering); `sunset_condition`; and `t123_relation` (extends / parallels / conflicts).

### Q2 -- B2, design forks (verdict: CONFIRMED | PARTIAL | REFUTED; prose points to `burden_dispositions.B2`)

**The burden as stated.** At `/plan` Step 6b the human receives "Summary, Proposed approach,
Options, Open questions, Decision flags, Decisions to cite" (GROUNDING MAP S1). Options and open
questions arrive in deep technical detail when what the human needs is: is this fork one where
any consistent, persisted choice is fine (NS-D), or one the human must own? Separately, a fork
resolved sensibly against today's tree can contradict a design the roadmap already commits to
later; scoping the roadmap to check is context-heavy for the planning agent.

**Two sub-burdens you must verdict separately inside the B2 disposition:** B2a
presentation depth (what reaches the human and in what shape) and B2b roadmap-alignment risk
(a design choice contradicting planned future work). B2a is REFUTED if a sampled plan's
`context:` or another artefact records a property-matched presentation control. No artefact in
the repository is known to record a
`/plan` Step 6b presentation, so B2a may be `INDETERMINATE` with that reason stated -- do not
verdict depth from instruction text alone. An INDETERMINATE sub-burden floors B2 at PARTIAL:
when the other sub-burden is REFUTED, B2 is PARTIAL, may carry zero findings (the refuted
half's control goes to `rejected_candidates[]`, the indeterminate half's reason into the
disposition's `evidence`), and its `adopted_set` must still be non-empty -- an
instrumentation-only remedy is the natural fit. A remedy may address one, both, or neither;
say which.

**Candidate remedies (adjudicate every one):**

- **B2-R1** (`origin: requester`) A roadmap scout: a fresh-context subagent modelled on `decision-scout`, reading a
  targeted projection of `tier_items[]` and `candidate_decisions[]` (their `intent`, exit
  criteria, `depends_on`, `related_candidate_decisions`), returning CITE / CONFLICT / RELATED
  flags against the proposed approach, as a gate before Step 6b.
- **B2-R2** (`origin: requester`) A mandatory Fable advice-consult (the overseer skill's protocol: settled consensus
  vs contested, adopt/adapt/reject) before ANY open question is presented to the human, so
  settled-consensus forks are decided by the agent and only contested or always-ask forks reach
  the human.
- **B2-R3** (`origin: requester`) Both B2-R1 and B2-R2, sequenced (scout first, consult second,
  or the reverse -- you rule the order in `design_notes` if adopted).
- **B2-R4** (`origin: composer`) A presentation contract for `/plan` Step 6b: a pinned shape for every option and open
  question (the fork in one sentence; the options; the agent's recommended option; whether the
  fork is consistency-only per NS-D or authority-bearing; reversibility; where the choice will
  be persisted), plus a default-take rule -- consistency-only forks are decided by the agent,
  recorded in the plan's `context:`, and presented as decided-with-notice, not as questions.
  This is the overseer skill's autonomy-boundary policy (settled-consensus, convention-fit,
  reversible, no-credible-alternative; hard always-ask list) applied at `/plan` rather than
  at the overseer. Sub-question you must answer in `design_notes`: can this contract land in
  the `AskUserQuestion` call shape -- `planning/SKILL.md:468-470` already routes subagent-mode
  Step 6b confirmation through that tool -- rather than in skill prose, at zero prose cost?
- **B2-R5** (`origin: composer`) Extend the existing `decision-scout` brief and skill with the roadmap projection
  instead of dispatching a second scout -- one subagent, two corpora, one report with a new
  ROADMAP section.

**Exclusion rules.** Adopting B2-R3 forces B2-R1 and B2-R2 to `reject` with a `rationale`
opening "superseded by B2-R3", and excludes B2-R5 (B2-R3 already carries the scout). B2-R1 and
B2-R5 are mutually exclusive: adopt at most one; the other is `reject`, "superseded by ...". A
superseded `reject` counts as rejected in the summary arithmetic.

For each: `verdict`; `sub_burdens_addressed` (B2a, B2b, both, or neither); `landing_surfaces`;
`carrying_cost`; `human_decision_removed`; `runtime_cost` (a Fable dispatch is not free --
dispatches per plan, estimated tokens and wall-clock relative to the plan's own cost, with the
basis); and `failure_mode_if_wrong` (a scout that misses a conflict; a consult that decides a
fork the human wanted).

### Q3 -- B3, gate non-convergence (verdict: CONFIRMED | PARTIAL | REFUTED; prose points to `burden_dispositions.B3`)

**The burden as stated.** The plan-critique gate loops on REVISE with a cap of three rounds,
then "escalate to the human with the unresolved findings and options (accept-with-deferral /
re-scope / abandon)" (the command-level menu at `plan.md:101` differs -- see the
escalation-menu trap). In practice the human says some form of "fix what is mechanical, run one
final round, merge", and the implementing agent copes. The requester's long-term intent is to
analyse transcripts for WHY convergence failed (a frequent guess: at least one round was spent
on mechanical defects), but that substrate does not exist yet. What should the procedure be NOW?

**Pinned facts to reason from (verify each):** the planning skill carries three convergence
rules (`:462-463`, `:597`, `:631-635`); rec-2944 asserts they differ in KIND (count-based versus
trajectory-based) and records an observed converging series (7 -> 4 -> 3 findings, none
repeated) that tripped the count cap -- whether `:635` ("After 3 rounds without convergence,
escalate") is trajectory-based or merely a count cap with a different rationale sentence is a
CONTESTED claim you adjudicate, not a pinned fact;
the prior audit REJECTED admission-narrowing on re-rounds (P6) on three stated grounds and
named a revisit condition; the round histogram over the plan corpus is in EMPIRICAL PASS; the
fresh-full-re-evaluation on every re-dispatch is a deliberately ratified property. B3 is REFUTED
if the escalation menu at `:597` together with the human's observed dispositions on the
four-or-more-round plans (DD-C) constitutes a property-matched procedure, or if DD-C shows no
non-convergence the count rule itself caused; otherwise verdict it on the evidence. An
all-indeterminate DD-C is NOT a REFUTED trigger: B3 then floors at PARTIAL, its evidence is the
substrate gap itself (no per-round record survives; rec-3080, PWS-01, T4.5), and its one finding
is classified against that owner.

**Candidate remedies (adjudicate every one):**

- **B3-R1** (`origin: requester`) A Fable advice-consult at the cap: a fresh-context subagent reads the plan and the
  three critique reports, classifies each unresolved finding (mechanical / judgement /
  oscillating / contested), and returns a recommended disposition the planning agent applies
  before ONE final gate round; the human is asked only if the consult itself returns contested.
- **B3-R2** (`origin: composer`) Formalise what happens today: at the cap, the planning agent itself classifies the
  unresolved findings as mechanical or judgement, fixes the mechanical set, runs ONE final round,
  and proceeds on PROCEED or escalates only the judgement residue with a pinned escalation
  shape (finding, why it did not converge, the agent's recommendation, the human's choices).
- **B3-R3** (`origin: composer`) Replace the count-based rule with a trajectory rule per
  rec-2944: a converging series (strictly decreasing, no recurrence) continues past three rounds
  up to a hard ceiling; oscillation (any recurrence) escalates immediately regardless of round
  count. You pin the ceiling and the recurrence test in `design_notes`, with the basis; no
  ceiling other than the count-based three exists in the repository today.
- **B3-R4** (`origin: composer`) A mechanical pre-lint before the first gate dispatch, so rounds are never spent on
  defects a deterministic check catches (the prior audit's P2/P3 lineage; `plan_obligations`
  already runs at Step 6b and gate Phase 1 5b). Adjudicate whether the mechanical share of round
  1 findings is observable on the corpus and whether this remedy is a B3 remedy or a general one;
  answer the latter in `design_notes`.
- **B3-R5** (`origin: composer`) A two-lane gate verdict: the critique output tags each finding mechanical or
  judgement (the `Finding-Origin Attribution` field exists for registration-closure findings
  only today), and the round cap counts only rounds whose REVISE carried a judgement finding.

**Exclusion rule.** B3-R3 and B3-R5 may both be adopted only if `design_notes` states how the
trajectory rule and the two-lane round count compose; otherwise adopt at most one of them.

For each: `verdict`; `landing_surfaces`; `carrying_cost`; `runtime_cost`;
`human_decision_removed`; and `property_interactions`, which must cover three things: whether the
remedy preserves the fresh-full-re-evaluation property, how it interacts with rec-2944 and with
P6's revisit condition, and what record it leaves that the requester's future transcript analysis
can read (Decision 87 clause 4 rules where critique imperatives and deliberation live -- check
whether the record contradicts it).

### Q4 -- Net decision load (verdict: reduces | neutral | relocates | increases)

For the ADOPTED set as a whole (every remedy with verdict adopt-as-proposed or adopt-modified
plus every originated remedy): count the human decisions per plan removed and added, name each,
and rate the net. "Relocates" means the same number of decisions reach the human at a different
step or in a different shape; say whether the relocation is itself worth having (e.g. depth
reduced at the same count). Then state the aggregate carrying cost of the adopted set per
landing surface against measured headroom and its aggregate `runtime_cost_total`, itemised per
session type (`/plan`, `/implement`, `/orient`), and rate both on VD3 -- as a rating, not a veto.
Name any remedy carrying `also_serves`; its finding is a tie-break candidate for
`highest_leverage_change` (advisory -- the selector is pinned in EMPIRICAL PASS).
For every adopted remedy, name the relief valve taken on each landing surface (one
`carrying_cost_by_surface` row per remedy-surface pair, carrying `remedy_id` and `disposition`,
pinned in OUTPUT). Finally, give a dependency-ordered
adoption sequence: `sequence_position` unique and consecutive from 1 across every adopted and
originated remedy, each with a `vehicle` from the pinned enum and a `depends_on` list of
`{id, basis}` edges, every edge carrying its stated basis.

### Q5 -- External practice (verdict: sufficient | partial | insufficient; adds `external_checklist`)

Rate the workflow's human-in-the-loop design property-by-property against this EXTERNAL
CHECKLIST, each row `met | partial | missed` with `evidence` citing at least one file:line or
item id (the SCOPE table maps each file citation to the surfaces the row bears on; a row whose
evidence cites only item ids gates no surface's maturity). `partial`
requires an argued, property-matched compensating control in the evidence. This field is the
SOLE source the maturity top tier reads.

1. **Escalation tiering with explicit criteria** -- decisions are classed autonomous / notify /
   ask by stated criteria (reversibility, blast radius, consensus), not by the agent's mood
   (SRE and autonomous-operations practice; the overseer skill's autonomy-boundary policy is the
   in-repo instance -- check whether it reaches `/plan`).
2. **Options-considered convention** -- every design fork is presented as options, a recommended
   option, consequences, reversibility, and a named decision owner (RFC / design-doc practice).
3. **Decision provenance with lifecycle** -- rejected alternatives and default-taken choices are
   recorded with status, so a later reader can distinguish decided from never-evaluated (ADR /
   MADR practice; the prior audit's P4/P5 adopt-modified verdicts are the in-repo precedent and
   have not landed).
4. **Structured handoff artefact** -- work that crosses a session or owner boundary leaves a
   checklist-shaped artefact the receiver reads, not a message the receiver must remember
   (handoff-checklist practice; Decision 115 is the in-repo rule).
5. **WIP-limited, visible follow-on queue** -- deferred work enters a bounded queue with an owner
   and a pull trigger, and the queue is surfaced at the point of choosing work (Kanban practice;
   compare `/orient` section 5/6 and the 872-open-rec queue).
6. **Bounded retry with a tie-breaker** -- review non-convergence resolves by a named tie-breaker
   role or rule within a fixed budget, never by open-ended iteration or an unspecified
   escalation (code-review and SRE practice).
7. **Mechanical-before-judgement gating** -- deterministic checks run before any expensive or
   human review so no review round is spent on lint-class defects (presubmit practice).
8. **Evidence-gated autonomy ratchet** -- a decision moves from human to agent only with
   evidence and a revocation trigger, and the movement is recorded (progressive-autonomy
   practice; T4.4 owns the end-state gates).

### Q6 -- Unnamed burdens and questions not asked (answers shape: `{q: Q6, answers: [{question, answer, basis}]}`)

Sweep S1-S7 for burdens the requester did not name -- decisions the human makes or memories the
human keeps that the workflow could carry -- CAPPED AT THREE, each held to the same evidence bar
as B1-B3 and each given a `burden_dispositions` entry (B4-B6) with at least one originated
remedy if not REFUTED. Then answer AND extend these compose-time seeds:

- Does any adopted remedy make the human's confirmation at Step 6b a rubber stamp -- i.e. does
  reducing depth reduce the human's ability to catch a wrong frame (Decision 75)?
- Which adopted remedies survive the end state unchanged, which retire at their sunset, and
  which need a T4.2-era persona equivalent (VD6)? Route each end-state need to the tier_item
  that owns it, or say none does.
- The prior audit found the round-count substrate corrupted (34 plans now carry the literal
  placeholder). Does anything adopted here make the requester's future transcript analysis
  possible, or does it depend entirely on Decision 87 / T4.5 / T2.36 landing?
- Would the requester be better served by fewer, larger plans (raising the split rate's
  denominator) than by any B1 remedy? Argue from the corpus.
- Where does the `/implement` session's own "Step 8 Capture Friction" and "Medium/Low findings
  become recs" path interact with B1: is the split half already being filed there, and if so
  why does it not resurface?
- Are B1, B2b and B3 three burdens or three symptoms of one absent record -- a planning
  session's decisions leaving no machine-readable trace (the free-text `gates:` line with 34
  placeholders, rec-3080's chat-only verdicts, squash-merged per-round content, no successor
  field)? If one, is a single mechanism cheaper than the adopted set? Express it with
  `also_serves`.
- Is the burden absent machinery or unused machinery? `/overseer` already narrows the human to
  G0/G1/G3, carries decomposition across dispatches, and owns the autonomy-boundary policy that
  B2-R4 proposes porting (`overseer/SKILL.md:171-194`). Is "the overseer is not the default for
  this work class" a live hypothesis, and what would make it one?
- Add at least two questions of your own.

## RUBRIC

Rate every surface S1-S7 on every dimension VD1-VD7 (49 cells). Pinned enum:
`strong | adequate | weak | absent | n/a`. `n/a` is correct and costless where a dimension does
not structurally apply to a surface; never manufacture a rating or a finding to fill a cell.
Every rating carries `evidence` (file:line or item id) and a one-line `note`.

| id | dimension | serves |
|---|---|---|
| VD1 | Decision-load reduction: does the surface remove or narrow a human decision, or push one to the human it could hold? (NS-A, NS-D) | Q1-Q4, Q6 |
| VD2 | Handoff durability: does state that must cross a session boundary land in a store the next agent already reads? (NS-B, NS-C) | Q1, Q3, Q5 rows 4-5 |
| VD3 | Carrying-cost proportionality: bytes/lines the surface adds to ambient prose vs machine-enforced norm, contract, or code, against measured headroom (NS-F). Rated, never a veto. | Q4 |
| VD4 | Mechanization fitness: is the burden or the remedy deterministic-checkable, or does it require judgement; is judgement placed where a fresh context can hold it? (NS-E) | Q2, Q3, Q5 row 7 |
| VD5 | Governance-vehicle fit: does the remedy route per `decision-entry.yaml`'s routing rule (Decision / CD flip / operational fact / field semantics / work item)? | Q4 |
| VD6 | Weak-executor operability: does the surface's behaviour survive the T4.2 persona era, or is it interactive-only quality of life? | Q4, Q6 |
| VD7 | Evidence grounding: is the burden observable on the current substrate (plan corpus, rec cache, gate records) or only anecdotal? (NS-E) | Q1-Q3, Q5 |

## DEEP-DIVES

- **DD-A -- Split-to-successor trace (feeds Q1, Q6).** Trace, end to end, what happens to a split
  half today: where the split is decided (the planning skill's Complexity Assessment freeze
  override, `planning/SKILL.md:244-253`; `/plan` Step 9's escalation menu, `plan.md:101`, whose
  split option the skill's own menu at `planning/SKILL.md:597` omits; and
  plan-critique Phase 2 step 8, where the branch question at `:39`/`:40` and the shared output
  template at `:136` disagree -- adjudicate whether the template is a live split producer for
  IMPLEMENTATION plans), what artefact records the decision (the plan's
  `context:`? the PR body? a rec? nothing?), and what could surface it in a later session
  (`/orient` sections 5-6 read only the preflight cache; `/plan` Step 3 keyword-matches recs
  against the chosen task). Apply the counterfactual per EMPIRICAL PASS to sampled plans. Then
  trace Decision 115's two halves against B1-R1 and B1-R5 specifically.
- **DD-B -- Design-fork path and Fable wiring (feeds Q2, Q5 rows 1-3).** Trace how a fork reaches
  the human: the Step 6a scout (decisions only), Step 6b's one-line presentation rule, the
  confirmation gate. Then trace every call site of the Fable protocol (overseer G1 and
  `fable_triggers`; planning Data-Model step 8; implement deviation-trigger branch a) and state
  for each: its trigger condition, who dispatches, what returns, where the adopt/adapt/reject is
  recorded. Establish whether the protocol is reachable from an interactive `/plan` session at
  all outside the data-model case, and what "settled consensus" would mean for a repo-internal
  consistency fork (NS-D) versus an industry-practice fork.
- **DD-C -- Non-convergence trace (feeds Q3, Q5 row 6).** For every plan in the corpus that
  recorded four or more rounds (EMPIRICAL PASS), reconstruct from the plan's `context:`, its
  commit history (`git log --follow -- docs/plans/PLAN-<slug>.yaml`), and any PR body you can
  reach via `mcp__github__*` tools what the human decided at the cap and what the final round
  found. Classify each as converging / oscillating / indeterminate and mechanical-dominated /
  judgement-dominated / indeterminate. State the evidence ceiling honestly: per-round content is
  squash-merged away and the `gates:` line is free text.
- **DD-D -- Bootstrap-vs-end-state consistency (feeds Q4, Q6).** For every adopted or originated
  remedy, state its end-state disposition: survives unchanged / retires at sunset / needs a T4.2
  persona equivalent (name the owning tier_item). A remedy with no stated disposition is not
  adoptable. Rejected and deferred remedies carry `end_state_disposition: n/a`.

## GROUNDING MAP

This map spends your cognition on judgement, not grep. Verify every anchor before relying on it
(re-derive; record misses in `meta.stale_anchors`). Facts are stated neutrally; none is a
verdict.

**S1 -- `/plan` pipeline**

- `.claude/commands/plan.md:43` -- resume check: an existing `PLAN-*.yaml` matching the intent
  is offered for resume at Step 9 or 11.
- `plan.md:47-48` -- Step 3 delegates decision-contradiction checking to the scout; "Suggest 3-5
  open recommendations from `logs/.recommendations-log.jsonl` that align with the current task."
- `.claude/skills/planning/SKILL.md:177-186` -- Suggest Aligned Recommendations: keyword
  extraction from the task description, matched against `title`, `file`, `context`; top 3-5
  presented with "include rec-XXX or skip".
- `planning/SKILL.md:244-253` -- Complexity Assessment: >5 scope files or >8 steps suggests
  STRATEGIC; "Freeze override (active)": author as one larger IMPLEMENTATION plan "or split into
  multiple atomic IMPLEMENTATION plans during this planning session"; the Presentation Rule at
  `:253`: classification "MUST be presented to the human and confirmed".
- `planning/SKILL.md:280-284` -- Data-Model Assessment step 8 "Fable escalation": for a NEW
  table, NEW identity scheme, or `merge_key` change only, dispatch a `model:"fable"`
  advice-consult per the overseer skill's protocol; routine calls "do not need escalation".
- `plan.md:65-75` -- Step 6: 6a scout gate mandatory before presentation; 6b "Present: Summary,
  Proposed approach, Options, Open questions, Decision flags (if any), and Decisions to cite";
  then "Does this approach look right? Say 'write the plan'"; any other response is feedback.
  No line in `plan.md` or the planning skill states a shape, depth, or count rule for Options or
  Open questions.
- `planning/SKILL.md:430-463` -- Decision Scout Gate: dispatch shape, verdict handling
  (NO_FLAGS / FLAGS_FOUND -> human chooses per flag "pivot, defer with note, or accept-as-is" /
  BLOCK); convergence rule at 462-463: after 3 revisions still BLOCK, escalate with two stated
  causes (intent contradicts the decision; decision needs revisiting).
- `planning/SKILL.md:465-470` -- Confirmation Gate; subagent form obtains the same confirmation
  via `AskUserQuestion`.
- `plan.md:99-101` -- Step 9: loop on REVISE, "3-round cap, then escalate per the skill -- the
  escalation menu includes narrowing scope, re-deriving the approach, or split the plan into
  smaller IMPLEMENTATION plans".
- `planning/SKILL.md:569-599` -- Critique Gate: fresh-context dispatch is "non-negotiable";
  :593 "Each Agent call is a fresh window, so the re-launch genuinely re-evaluates"; :597
  "Convergence rule: after 3 REVISE rounds, escalate to the human with the unresolved findings and
  options (accept-with-deferral / re-scope / abandon), mirroring the Step 6a decision-scout
  convergence rule."
- `planning/SKILL.md:631-635` -- Report Critique Gate convergence rule: stop when both agents
  PROCEED or the human accepts with a defined deferral; "After 3 rounds without convergence,
  escalate to the human for a decision call -- continued iteration typically signals either a
  structural issue with the deliverable's scope or diminishing returns."
- `planning/SKILL.md:648-662` -- Confirmation Messages: the IMPLEMENTATION block names the
  `/implement` command to paste; the REPORT-ONLY block ends "Decide which follow-on items ... to
  start, then open a new planning session for each."
- `planning/SKILL.md:11-20` -- behavioural invariants block (`preflight_run`, `harness_branch`,
  `decision_scout_gate`, `critique_gate`, `report_critique_gate`, `never_on_main`), parsed by
  `scripts/prompt_compliance.py:109-120`; plan-phase invariants checked at :215-227.
- Plan `context:` line grammar for gates (`planning/SKILL.md:455`): "gates:
  decision-scout=<verdict>; plan-critique=<verdict> after <N> round(s)". Open recs rec-3041
  (line written once at `/plan` Step 8, goes stale), rec-2480 (stray paren in the duplicated string).

**S2 -- `/implement` pipeline**

- `.claude/commands/implement.md:52-58` -- IMPLEMENTATION dispatch: count scope files and steps,
  present a summary, execute steps sequentially.
- `implement.md:112-121` -- `/implement` Step 8 Capture Friction: file a rec via the portal with
  `source=manual`; RCA-First for recurring gaps.
- `implement.md:123-126` -- Step 9 Report: "Files changed, verification results ..., code review
  findings fixed, bugs fixed, design decisions"; then close the telemetry session. No step in
  `implement.md` or the implement skill drafts or emits a follow-on `/plan` prompt.
- `.claude/skills/implement/SKILL.md:110-119` -- Deviation trigger, three branches: (a) in-scope
  under-specification -> decide inline, consult `model:"fable"` per the overseer protocol "when
  load-bearing or novel, recorded either way"; (b) scope or contract deviation -> STOP; (c)
  repeated failure -> existing 3-fix-attempt rule. Contract form:
  `docs/contracts/implement-scope-boundary.yaml` `deviation_trigger` (branch `a` names the
  same consult).
- `implement/SKILL.md:188-190` -- Handling Findings: Medium and Low code-review findings "File
  these as new recommendations ... Do not fix them inline -- they will be addressed in future
  sessions."
- `implement/SKILL.md:545` -- PR body carries the `Resolves:` trailer and the VP compliance
  table; Decision 115 is cited for PR-scoped ephemeral evidence vs the durable roadmap record.
- `implement.md:50` -- reads only the decisions the plan context cites (the prior audit's WF-04
  remedy is in place).

**S3 -- gates**

- `.claude/skills/plan-critique/SKILL.md:38-40` -- Phase 2 step 8 Scope evaluation: the
  STRATEGIC branch (`:39`) asks "Too large (suggest split)? Too small (merge ...)?"; the
  IMPLEMENTATION branch (`:40`) asks "Are all scope entries necessary? Does the Scope extend
  beyond the stated phase?"; the output template (`:136`) carries "too large (suggest split
  into: X, Y)".
- `plan-critique/SKILL.md:93-109` -- Phase 2b Frame Challenge (12e-12i, Decision 75) with 12j:
  a concrete contradiction -> REVISE; real questions without contradiction -> surfaced "for human
  consideration", not REVISE.
- `plan-critique/SKILL.md:111-160` -- structured output; `Finding-Origin Attribution` field
  (:157) tags "each registration-closure finding" mechanical vs critic judgement; final line
  `Recommendation: PROCEED / REVISE` (:159).
- `plan-critique/SKILL.md:30` -- Phase 1 5b runs `plan_obligations` independently against the
  written artefact.
- `.claude/skills/decision-scout/SKILL.md:6-18` -- bounded triage over `docs/decisions-index.json`;
  :28-35 the mandated input brief (Intent, Proposed approach, Scope files, Verification Tier,
  cited decisions) with BLOCK on a missing input; :39-50 mechanical tag shortlist then
  CITE / CONTRADICT / RELATED / IRRELEVANT; :76-117 the report shape with a Verdict line and
  "Decisions triaged: N of M"; :119 ~1,200-word cap. The skill reads decisions only; no roadmap
  projection is part of its brief or its Phase 1.
- Prose headroom, measured bytes `budget - current` from `config/prose_budgets.yaml:48-56`
  (re-derive: read the file as raw text, match `^\s{2}(\.claude/[^:]+):\s*(\d+)` per line, and
  subtract `os.path.getsize(path)` -- the inline `# raise-approved` comments make
  `yaml.safe_load` unsuitable):
  planning 76, plan-critique 7, decision-scout 0, implement 95, orient 21, overseer 0,
  code-review 4, audit-prompt 46, executor-rca 0. `config/prose_budgets.yaml:8`: S3
  (`.claude/commands/*.md`) is measured-only with no budget entry. `:23-30` relief valves:
  relocate to `docs/PROJECT_CONTEXT.md` (headroom 125) or a `docs/contracts/*.yaml` contract;
  defer detail to an uncapped auxiliary file; or a loud Decision-cited raise; never split a
  surface into `@`-imported fragments. `config/structural_size_budgets.yaml:92-99`: contracts
  class capped at 500 effective lines; `docs/contracts/overseer-dispatch.yaml` measures 364.
- Surfaces without a prose budget, and how to record their headroom: `.claude/commands/*.md` is
  measured-only -- record `headroom: "n/a -- measured-only"` and `disposition: fits`.
  `scripts/**` is governed by `config/sloc_budgets.yaml` (Decision 128: an unregistered file
  stays under 500 SLOC or is decomposed; `scripts/roadmap/plan_document.py` 354,
  `scripts/roadmap/plan_obligations.py` 176, `scripts/platform_roadmap_state.py` 350 SLOC, none
  registered) -- record `headroom` as `500 - SLOC`. `docs/contracts/*.yaml` is governed by
  `config/structural_size_budgets.yaml:92-99` -- record `headroom` as `500 - effective lines`.

**S4 -- `/orient` follow-on machinery**

- `.claude/skills/orient/SKILL.md:8,17` -- strictly read-only; "Files no recommendations or
  decisions". No section of the skill reads `logs/.recommendations-log.jsonl`; its Inputs table
  reads the preflight cache and roadmap projections. The one recommendation class it does
  surface is ci-rca: `:125` names the `ci_rca_*` preflight keys as the CI-RCA Triage source and
  `:178` ranks HARD BLOCK ci-rca recs as item 0 of the work list -- a rec-surfacing path that
  already exists, at preflight-cache grain.
- `orient/SKILL.md:174-186` -- Section 5 Ranked What-to-Work-On: CI-RCA first; in_progress
  follow-on planning ranked fewest-open-criteria-first with three cases (parked-gated /
  mid-implementing / needs follow-on), reading `needs_followon_plan` from the cache; keystone-
  first within eligible; strategic pending listed last.
- `orient/SKILL.md:188-220` -- Section 6: up to 5 ready-to-paste `/plan` prompts, overlap matrix,
  follow-on prompt grammar `/plan <item-id>: follow-on -- <item-name> (<N> open criteria
  remaining)`, `/implement` suggestion for mid-implementing items.
- `scripts/platform_roadmap_state.py:91` -- `needs_followon_plan: bool (True iff
  open_criteria_count > 0 AND all_plans_actioned)`; computed at :137 for live in_progress items.
- `docs/contracts/exit-criteria-ledger.yaml:9-11` -- per-criterion status ledger on roadmap
  tier_items; `PlanDocument.closes_criteria` names which criteria a plan closes; :47 `/implement`'s
  bookkeeping walk flips open->met per ref; :69-72 `plan_closes_criteria` semantics.
- Roadmap T-1.23 (`docs/ROADMAP-PLATFORM.yaml` tier_items) -- `complete`, criteria c1-c5 met:
  c1 `/orient` emits follow-on prompts; c3 `compute_followon_state` surfaces
  `open_criteria`/`all_plans_actioned`/`needs_followon_plan` for live items only; c4 `/plan`
  follow-on mode + `closes_criteria`; c5 ledger integrity in `validate.py`.

**S5 -- Fable advice-consult protocol**

- `.claude/skills/overseer/SKILL.md:186-194` -- "Before each major design decision, dispatch a
  fresh-context subagent (`Agent`, `model: "fable"`). It reads ... but edits nothing, separating
  advice into 'settled consensus' vs 'contested' ... Reconcile via adopt / adapt / reject, logged
  to the ledger. Triggers beyond G1: workflow-adaptation ... and rec-synthesis".
- `docs/contracts/overseer-dispatch.yaml:327-336` -- `fable_triggers`: `existing` (each major
  design decision; the G1 decomposition shape; any point the overseer must choose an
  architecture) and `broadened` (`workflow_adaptation`, `rec_synthesis`). The ledger the
  adopt/adapt/reject is logged to is `docs/plans/reports/OVERSEER-{slug}.yaml`
  (`overseer/SKILL.md:65-95`), a scratchpad not durable across session loss.
- `overseer/SKILL.md:171-184` -- Autonomy-Boundary Policy: autonomous only when all four hold
  (settled-consensus, convention-fit, reversible, no-credible-alternative), else present 2-3
  options and wait; proceed-with-notice tier; hard always-ask list (IAM/security, spend,
  public-surface artefact change, governed deploy).
- `overseer/SKILL.md:196-201` -- Model Namespace Note: frontmatter `opus[1m]` pin vs the Agent
  tool's `model` enum `sonnet | opus | haiku | fable`.
- `.claude/commands/overseer.md:51-53` -- Step 3 "Advice (Fable Consult)" applies the protocol
  to the decomposition shape, ahead of the G1 gate at `:62`.
- The protocol's call sites outside the overseer are exactly two, both conditional: planning
  Data-Model step 8 and implement deviation-trigger branch (a). The `/plan` Step 6 presentation
  path has no call site.
- Open recs and tier_items carrying "roadmap alignment", "roadmap scout", "design fork",
  "industry practice", or "horizon scan" in title/context: zero hits on each search.

**S6 -- plan schema + mechanical checks**

- `scripts/roadmap/plan_document.py:223-249` -- `PlanDocument` fields: `schema_version`,
  `slug`, `intent`, `plan_type`, `verification_tier`, `plan_path`, `phase`, `scope`,
  `bundled_recommendations`, `closes_criteria`, `infrastructure_dependencies`,
  `acceptance_criteria`, `verification_plan`, `test_obligations`, `constraints`, `context`,
  `pre_implementation_checklist` (`:242`), `execution_steps` (`:243`), `work_areas` (`:244`),
  `rollback` (`:245`), `tier_waiver` (`:246`), `handoff_policy` (`:247`; the `HandoffPolicy`
  submodel at `:73-77` carries `full_validation_required_before_commit` and
  `timeout_disposition`, checked by `_validate_handoff_policy` at `:283`),
  `fallback_reevaluation` (`:248`), `implementation_declared` (`:249`). No field names a
  successor, follow-on, or split sibling. `model_config = ConfigDict(extra="forbid")` on every
  model (:74, :81, :89, :136, :172, :188, and `PlanDocument`'s own at :224).
- `scripts/prompt_compliance.py:109-120, 215-227` -- parses the invariants block; plan-phase
  invariants are "structural invariants enforced by prompt ordering".
- Open recs: rec-389 (High, M) "Plan quality structural constraints ... critique cycling
  originate in planning producing structurally valid but semantically wrong plans"; rec-3285
  (`validate_tier_floor` dormant off schema_version 2); rec-3080 (Low, M) "Design a gate-verdict
  recording surface for plan-critique PROCEED/REVISE outcomes ... verdict itself is still only
  ever recorded in chat transcript".

**S7 -- carrying surfaces and governing rules**

- `docs/contracts/decision-entry.yaml` `significance.bar` and `significance.routing` (the
  `work_item` row at :412): numbered Decision reserved for "a durable architectural commitment
  with reversal-relevant consequences"; `operational_fact` -> rec or progress_note;
  `field_semantics` -> owning contract; `work_item` -> "recs are the DESTINATION form and the
  roadmap the BOOTSTRAP that recs supersede ... Route by CAPABILITY, never topic".
- `docs/DECISIONS.md:3969` Decision 115 -- transient handoffs: ephemeral half rides the PR
  description; durable half goes to the plan YAML (acceptance criteria / context) or roadmap exit
  criteria; `docs/handoffs/` retired by convention, no guard; reversal condition: "revisit if a
  future workflow demonstrates a genuine need for handoff state that outlives both the
  originating PR description and the plan/roadmap structured stores."
- `docs/DECISIONS.md:6257` Decision 66 -- Precision Context Injection: surface authoritative
  semantics at the moment the agent composes, "not injected as a post-rejection error".
- `docs/DECISIONS.md:5809` Decision 75 -- Frame-Lock anti-pattern; plan-critique Phase 2b is its
  enforcement.
- `docs/DECISIONS.md:5261` Decision 87 (as amended; clause 4 at :5279-5280) -- ONE plans table
  `ops_execution_plans`; `critique_history` on the plan row is the home of the critic's
  imperative; deliberation lives in telemetry; authority-flip deferred to T4.x.
- `docs/DECISIONS.md:5205` Decision 90 -- four tiers (`/orient -> /plan -> /implement ->
  /develop-executor`); the section does not mention the overseer. The meta-layer rule:
  `overseer/SKILL.md:15` and `:29` (`meta_layer_not_tier: true`),
  `docs/contracts/overseer-dispatch.yaml:4`, `AGENTS.md:102`.
- `docs/DECISIONS.md:6222` Decision 67 -- STRATEGIC/executor freeze (Amended - Partially Active).
- `docs/DECISIONS.md:5319` Decision 86 and `:3200` Decision 127 -- no standing prose docs; the
  only stored prose is agent-instruction content.
- `docs/DECISIONS.md:6029` Decision 55, `:5960` Decision 72 -- RCA-first; forward-fix.
- `docs/DECISIONS.md:3123` Decision 128 and `:1055` Decision 165 -- raise markers.
- `docs/DECISIONS.md:572` Decision 174 -- retired planning artefacts: provenance in git history.
- `docs/DECISIONS.md:160` Decision 179 -- decision-corpus stock ceilings retired; retrieval
  replaced ambient loading.
- Roadmap: T2.56 `in_progress`, c1 OPEN ("AGENTS.md / CLAUDE.md / the skills layer are
  measurably shrunk to machine-enforced norms plus pointers"), c2 met. T4.2 `not_started`
  (persona nodes). T4.3 `not_started` (priority-queue producer repoint). T4.4 `not_started`
  (autonomy maturity gates A0-A5). T4.5 `deferred_post_mvp` (plan/critique/revision warehouse
  entities). T4.11 `not_started` (executor loop-budget + retry policy contract). T4.16
  `not_started` (executor plan data plane; c4: a critique verdict is written by the critic or the
  gate, never the critiqued persona).
- `docs/contracts/git-ops.yaml:113` -- the `audit({slug}):` commit prefix is registered.

**Prior audits (dedup owners)**

- `audits/planning-workflow-scaling-369a963a.yaml` (+ `.md`): 8 findings, PWS-01 highest
  leverage (the `gates:` line is free text nothing validates; 29 placeholders then); D1
  CONFIRMED round telemetry; D5 CONFIRMED "inward-only alternatives search". Proposal
  dispositions relevant here (read `proposal_adjudication.P2/P3/P4/P5/P6/P10/P11/P13` in
  full): P2 lint engine plus six of eight seed rules ADOPT-MODIFIED (sequence 4; lands in the
  existing `roadmap/` or `verification/` check domain as an importable library, not a new
  domain); P3 lint wiring ADOPT-MODIFIED (sequence 11, depends on P2; two surfaces -- the
  `plan_obligations` advisory CLI at `/plan` Step 6b and critique Phase 1 5b -- with the
  executor surface deferred behind Decision 67); P6
  re-round convergence discipline REJECT on three grounds with revisit condition "if PWS-01's
  typed record later shows real oscillation" and the note "rec-2944's convergence-rule
  reconciliation covers the cap inconsistency without admission-narrowing"; P10 per-plan world
  scout REJECT, dominated by P11 with a revisit condition keyed to P11's sunset; P11 horizon
  scan ADOPT-MODIFIED (operator-run or cost-triggered, at most 3 recs, sunset after two
  zero-yield passes; sequence 14; depends on P4/P5); P4 provenance-honesty norm and P5
  `alternatives` envelope field ADOPT-MODIFIED (sequence 2-3); P13 confidence-gated escalation
  ROADMAP. Whole-word searches (`rg -w`) for `never_evaluated`, `plan_lint`, `plan-lint`, `lint
  engine`, and `horizon` across `docs/DECISIONS.md`, `docs/contracts/decision-entry.yaml`,
  `docs/ROADMAP-PLATFORM.yaml`, and `logs/.recommendations-log.jsonl` return zero hits (a
  substring search for `horizon` matches "horizontal" once, at `docs/ROADMAP-PLATFORM.yaml:6451`).
  `docs/contracts/decision-entry.yaml` contains no `alternatives` key under
  `metadata_envelope.optional_fields` and no occurrence of the word; the word does occur in
  `docs/DECISIONS.md` exactly three times (:15 "rejecting two lighter alternatives", :2377 "Two
  alternatives were considered and rejected", :6715 the heading `**Rejected alternatives:**`)
  and in six rec-cache rows (open rec-228 among them), none a typed envelope field. No lint module exists under
  `scripts/roadmap/`, and `scripts/verification/` does not exist; no rec in the cache cites a
  PWS finding id.
- `audits/workflow-review-d107b4a.yaml`: WF-04 (handoff lost the scout output; since addressed
  at `implement.md:50`), WF-08 (gate verdicts leave no artefact; runtime compliance check
  vacuous), WF-10 (`/plan` command restates skill methodology).
- rec-2944 (open, Medium, S, file `.claude/skills/planning/SKILL.md`): the three rules differ in
  kind; observed converging series 7 -> 4 -> 3 with no repeat tripped the count cap; its cited
  lines 454/579/617 now resolve at 463/597/635 (the bold `**Convergence rule:**` header sits at
  `:462`).

## EMPIRICAL PASS

Sampled artefacts exist; sampling is BOUNDED. Counts below were measured against the tree at
`939eb789`; re-derive them (they are cheap) and record deviations in `meta.stale_anchors`.

**Corpus facts (re-derive):** 366 `docs/plans/PLAN-*.yaml`, 64 at `schema_version: 4`; 243
carry a `gates:` line in `context:`; 34 of those carry the literal `<verdict>` or `<N>`
placeholder; with each plan `yaml.safe_load`ed and its `context:` entries joined by a space,
the regex `plan-critique=\w+ after (\d+) round` parses 119, histogram rounds 1:48, 2:32, 3:27,
4:9, 5:2, 7:1 (12 plans at four or more rounds; a raw-text grep without loading the YAML gives
a different set and is not the method). The twelve at the drafting tree, with round counts:
PLAN-glue-delete-database-grant (7); PLAN-ducklake-applied-schema-gate (5); PLAN-pr-conflict-signal-exit-status (5); PLAN-ci-rca-adjudication-guard (4); PLAN-ci-rca-evidence-scope-declaration (4); PLAN-ci-rca-test-obligation-gate (4); PLAN-decompose-test-plan-document (4); PLAN-esb-text-fix-bundle (4); PLAN-migration-step-5-index-skeleton (4); PLAN-opswriter-never-drain-guard (4); PLAN-pr-validate-heavy-dep-test-deferral (4); PLAN-sync-deps-test-hermeticity (4). The tight plan-split
pattern `split (this |the )?plan|plan (was |is )?split|split into (two|multiple|smaller)
(plans|IMPLEMENTATION)|second (half|plan)|follow-?on plan|follow-?up plan` (case-insensitive,
over `yaml.safe_dump(doc)` at its default 80-column width -- an unwrapped dump gives 37, because
wrapping splits phrases across lines) matches 35 plans; 5 of those reference at least one OTHER `PLAN-*.yaml` by
filename. 16 slugs match `wave|phase|part` case-insensitively (14 `wave`, 2 `phase`, 0 `part`).

**Recommendation facts (re-derive; skip if `degraded_dedup`):** 872 open recs; by source
code-review 486, implement-agent 90, planning 72, manual 69, implement-session 53. 64 open recs
match the case-insensitive substring pattern `follow-?on plan|follow-?up plan|deferred to a
later plan|split` over `title` plus `context` (`created_timestamp` ages against 2026-09-02 by DATE-ONLY
subtraction, `(date(2026,9,2) - created.date()).days` -- full-timestamp arithmetic shifts the min,
median and max by one day and leaves the threshold counts unchanged: min 0, median 33, max 134
days; 33 older than 30 days; 8 older than 90).
Every age in this section uses that method. All open recs: median age 47 days, 169
older than 90. Planning/implement/manual-sourced: 284, median 29 days, 25 older than 90.

**Sample -- do NOT exceed 20 plans and 12 recs:**

- ALL plans recording four or more rounds (12 at the drafting tree; re-derive) (DD-C). This
  reserve always wins: if re-derivation yields more than 12, take all of them and shrink the two
  reserves below (split-pattern first, then placeholder) to stay within 20. If this reserve
  alone exceeds 20, take the 20 with the highest round counts (ties broken by the most recent
  plan commit) and set `truncated: true`.
- 4 plans matching the tight split pattern that name NO other plan file, and 2 that do (DD-A).
- 2 plans carrying the literal placeholder in the `gates:` line.
- 12 open recs from the 64 with follow-on/split language, choosing the 6 oldest and 6 youngest.
  For each: what plan or session produced it, whether any later plan bundled it
  (`bundled_recommendations` across the corpus), and whether anything other than a keyword
  match could have surfaced it.

Record every sampled path/id in `meta.empirical_sample` (`plans: []`, `recs: []`,
`truncated: false`); set `truncated: true` if you could not reach the reserved counts OR had
to shrink a reserve to respect the cap, and say why in `meta.contract_notes`.

**Counterfactual test, applied per sampled plan:**

- For a split plan: "If the split decision had never been written anywhere but chat, would
  anything in the repository differ?" If no -> the durable record of the split is absent
  (evidence for B1, `evidence_kind: observed`). If yes -> name the artefact that differs.
- For a four-or-more-round plan: "If round 3's findings had all been mechanical, would the
  count rule and a trajectory rule have produced different outcomes?" and "Did any finding
  recur?" If the record cannot answer, tag `indeterminate` -- that is itself evidence about the
  substrate, not about the rule.
- For a follow-on rec: "If this rec were deleted, what would the next `/orient` or `/plan`
  session show differently?" If nothing -> the rec has no surfacing path today.

Tag every finding `evidence_kind: static` (traced from instruction text or schema) or
`observed` (from a sampled artefact). Observed findings outrank static ones at equal severity.
`top_improvements` is ordered by severity, then observed over static; `highest_leverage_change`
is selected the same way, with a remedy's `also_serves` breaking any remaining tie (Q4's note
on `also_serves` is advisory, not a selector).

## METHOD

- **M1 Read.** SETUP; `docs/PROJECT_CONTEXT.md`; every S1-S6 file in full; the S7 anchors and
  the prior-audit dispositions named in the GROUNDING MAP; targeted roadmap and decision
  projections only.
- **M2 Trace.** Verify every GROUNDING MAP anchor; run DD-A, DD-B, DD-C.
- **M3 Adjudicate burdens.** Verdict B1-B3 (CONFIRMED / PARTIAL / REFUTED) with the evidence and
  counterfactuals; file their findings.
- **M4 Adjudicate remedies.** All fifteen candidates, per-remedy fields; originate where required;
  DD-D for every adopted or originated remedy.
- **M5 Empirical.** The bounded sample; tag evidence_kind; revise M3/M4 confidences.
- **M6 Rate.** 49 rubric cells; Q5's external checklist.
- **M7 Dedup.** Per DEDUP DISCIPLINE, before any finding is final.
- **M8 Sweep.** Q6's capped unnamed burdens and questions not asked.
- **M9 Synthesize LAST.** Q4's net load and sequence; per-surface maturity (computed last);
  summary; the `.md` companion.

## DEDUP DISCIPLINE

Before filing ANY finding or adopting ANY remedy, search the ownership surfaces:
`docs/ROADMAP-PLATFORM.yaml` (`tier_items[]` names, intents, exit criteria;
`candidate_decisions[]`), `docs/DECISIONS.md` (`^## Decision` headers plus `rg` of 2-3 terms),
`logs/.recommendations-log.jsonl` (unless degraded), and `audits/*.yaml`. Record the search
terms and hit count on the finding (`roadmap_crossref.dedup_search_terms`, `dedup_hit_count`)
and on the remedy (`dedup_search_terms`, `dedup_hit_count`). A hit means a sufficiency
assessment (`planned-insufficient` / `planned-unbuilt`) or a `rejected_candidates` row -- never
a fresh discovery. A finding without a recorded negative search is a HYPOTHESIS.

Known owners to check first: rec-2944 (convergence-rule kind), rec-3080 (gate-verdict recording),
rec-389 (structural plan constraints), rec-3041 and rec-2480 (`gates:` line), rec-3285 (tier
floor), T-1.23 (follow-on planning), T2.56 c1 (skills-layer shrink), T4.5 / T4.16 / Decision 87
(critique persistence), T4.11 (executor loop-budget and retry policy), T4.4 (autonomy gates),
T4.2 / T4.10 (persona contracts), the prior audit's P4 / P5 / P6 / P10 / P11 / P13 and PWS-01.

**Deliberate constraints -- do NOT flag:**

- Decision 67 / CD.17: STRATEGIC plans suspended; the executor is frozen. Do not propose a
  STRATEGIC-plan or executor-consuming mechanism as a bootstrap remedy.
- Decision 90: four tiers. The overseer is a meta-layer (`overseer/SKILL.md:15`, `:29`;
  `overseer-dispatch.yaml:4`; `AGENTS.md:102`). No fifth tier, no new plan type.
- Decision 73: PR `--pre` CI is the authoritative gate; open ci-rca recs halt planning.
- Decision 84: all rec writes go through the portal; no offline outbox; local JSONL is a cache.
- Decisions 86 / 127: no new standing prose-architecture doc; do not propose one.
- Decisions 128 / 165: raises are Decision-cited; do not propose an unmarked raise.
- Decisions 55 / 72: RCA-first; no silent retry or workaround loops.
- The fresh full re-evaluation on every gate re-dispatch (`planning/SKILL.md:593`) is a ratified
  property, and P6's rejection rests on it; a remedy may argue for a bounded exception but may
  not treat the property as a defect.
- The existence of the human confirmation at `/plan` Step 6b. Its CONTENT and SHAPE are in
  scope; removing the checkpoint is not.
- Prose budgets are ratchet-down-only and seeded at zero headroom by design
  (`config/prose_budgets.yaml:15-16`); the headroom numbers are a cost input, not a defect.
- `/orient` is read-only by design (writes nothing); a remedy may have it READ more, never write.

## OUTPUT

Two deliverables. The YAML is the record; the `.md` (<= ~1500 words) is the executive layer a
human reads first: what to do, in order; the three burdens' verdicts in plain words; the
adopted mechanisms and what the human stops deciding; the sunset conditions; the findings that
most change the picture; method notes (sample, degraded flags, stale anchors, self-verification rounds).

```
audit:
  meta: {audited_commit: <sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1, scope_surfaces: [S1, S2, S3, S4, S5, S6, S7],
         # base_branch, model, methodology_version, scope_surfaces are provenance-only:
         # read by the human, by no rule in this prompt. stale_anchors and contract_notes are
         # read by the .md method notes and by verifier R2 (an anchor already recorded in
         # stale_anchors with its re-derived value is not a mismatch).
         degraded_dedup: false, contract_notes: "",
         stale_anchors: [{anchor: "", expected: "", found: ""}],   # empty list is legal
         empirical_sample: {plans: [], recs: [], truncated: false},
         self_verification: {rounds: 0, degraded: false,
                             unresolved_findings: [{lane: R1|R2|R3|R4, finding: ""}]}}
  question_answers:
    - {q: Q1, verdict: CONFIRMED|PARTIAL|REFUTED, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: CONFIRMED|PARTIAL|REFUTED, basis: [], prose: ""}
    - {q: Q3, verdict: CONFIRMED|PARTIAL|REFUTED, basis: [], prose: ""}
    - {q: Q4, verdict: reduces|neutral|relocates|increases, basis: [], prose: "",
       decisions_removed: [<one line each>], decisions_added: [<one line each>],
       carrying_cost_by_surface: [{remedy_id: <remedy id>, surface: <path>,   # one row per (remedy, surface) pair
                                   delta: "<+N bytes or +N lines>",
                                   headroom: "<measured, or n/a -- measured-only>",
                                   disposition: fits|relocate|trade_out|raise_authorized|raise_unauthorized}],
       # fits = within measured headroom; relocate = content moves to a contract, a command,
       # PROJECT_CONTEXT.md, or code per config/prose_budgets.yaml:23-30; trade_out = byte-neutral
       # by deleting named prose on the same surface; raise_authorized = an existing Decision
       # authorizes the raise (name it); raise_unauthorized = no such Decision (admissible;
       # rated weak on VD3 and VD5; listed in the .md)
       runtime_cost_total: {plan: "<dispatches, est. tokens, est. wall-clock, basis>",
                            implement: "<same>", orient: "<same>"}}   # per session type; "none" where the adopted set adds nothing
    - {q: Q5, verdict: sufficient|partial|insufficient, basis: [], prose: "",
       external_checklist: [{property: <1..8 name>, rating: met|partial|missed,
                             evidence: "<file:line or item id, plus argument>"}]}
    - {q: Q6, answers: [{question, answer, basis: [<finding ids>]}]}
  burden_dispositions:
    B1:   # B2, B3 same shape; B4-B6 only if Q6 surfaced them
      burden_verdict: CONFIRMED|PARTIAL|REFUTED
      sub_burdens: {}   # B2 only: {B2a: CONFIRMED|PARTIAL|REFUTED|INDETERMINATE, B2b: CONFIRMED|PARTIAL|REFUTED}; INDETERMINATE needs a stated reason
      evidence: "file:line|item-id|sampled path"
      counterfactual: ""
      what_the_human_does_today: ""
      candidate_remedies:
        - {id: B1-R1, origin: requester|composer|auditor,   # pinned per remedy in Q1-Q3; auditor = your own originations
           verdict: adopt-as-proposed|adopt-modified|reject|defer-to-roadmap,
           modification: "", landing_surfaces: [<paths>], carrying_cost: "",
           runtime_cost: "<dispatches per session; est. tokens and wall-clock, or 'unmeasured -- no substrate'; basis>",
           design_notes: "",    # REQUIRED for B1-R1 (its three sub-questions), B2-R1 (does P10's cost-profile argument transfer), B2-R3 (the order), B2-R4 (the AskUserQuestion carrier question), B3-R3 (ceiling + recurrence test, with basis), B3-R4 (B3 remedy or general one); "n/a" elsewhere
           also_serves: [],    # other burden ids this same mechanism remedies; counted once, under its home burden
           sub_burdens_addressed: [],    # B2 remedies only: subset of [B2a, B2b]; [] elsewhere
           property_interactions: "",    # B3 remedies: REQUIRED non-empty (see Q3); "n/a" elsewhere
           human_decision_removed: "", human_decision_retained: "",   # retained = the decision the human still makes after the remedy; Q4 reads both
           sunset_condition: "",            # REQUIRED for every B1 remedy; "n/a -- end-state form" allowed elsewhere
           t123_relation: extends|parallels|conflicts|n/a,   # B1 remedies only
           end_state_disposition: survives|retires_at_sunset|needs_persona_equivalent|n/a,   # n/a iff verdict is reject or defer-to-roadmap
           owning_end_state_item: "<tier_item id or none>",
           vehicle: skill_prose|command_prose|contract_amendment|schema_change|check|
                    decision|cd_flip|candidate_decision|rec|tier_item|none,
           # routing row -> vehicle: numbered_decision -> decision; cd_state_flip -> cd_flip;
           # operational_fact -> rec; field_semantics -> contract_amendment; work_item -> rec or
           # tier_item by capability; instruction text -> skill_prose | command_prose;
           # deterministic check -> check; schema field -> schema_change; a new CD -> candidate_decision
           rationale: "", failure_mode_if_wrong: "",
           dedup_search_terms: [], dedup_hit_count: 0,
           confidence: CONFIRMED|HYPOTHESIS, sequence_position: <int|null>,
           depends_on: [{id: <remedy id>, basis: ""}]}
      originated_remedies:
        - {id: B1-O1, name: "", instrumentation_only: true|false,   # ids B<n>-O<k>
           <same fields as a candidate remedy, origin: auditor, verdict restricted to
            adopt-as-proposed|adopt-modified; t123_relation only under B1>}
        # an origination you considered and rejected is a rejected_candidates[] row, never an entry here
      adopted_set: [<remedy ids>]    # non-empty iff burden_verdict != REFUTED
  per_surface_assessment:
    - {surface: S1, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: PDB-01, surface: S1..S7|shared, burden: B1|B2|B3|B4|B5|B6|none,   # PDB-NN, consecutive from 01
       surfaces_touched: [],   # on surface: shared, the S ids per the SCOPE table (empty = counts against no surface); [] otherwise
       question: Q1..Q6|none, dimension: VD1..VD7, title,   # B1/B2/B3 -> Q1/Q2/Q3; B4-B6 -> Q6; burden none -> Q5|Q6|none
       evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [finding ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [finding or roadmap ids],
                    note: ""}}
  rejected_candidates:
    - {candidate: "<B1..B6 or B2a|B2b, or 'S<n> <file:line>' for a GROUNDING MAP fact, or
                   'B<n>-O<k>' for a rejected origination>",
       why_dismissed, compensating_control, control_property_match, decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            burden_verdicts: {B1: <v>, B2: <v>, B3: <v>},   # add B4..B6 keys iff surfaced under Q6
            adopted_remedy_count, originated_remedy_count, instrumentation_only_count,
            rejected_remedy_count, deferred_remedy_count,
            top_improvements: [ids], highest_leverage_change: <id>,
            net_decision_load: reduces|neutral|relocates|increases,
            maturity_S1: <value>, maturity_S2: <value>, maturity_S3: <value>,
            maturity_S4: <value>, maturity_S5: <value>, maturity_S6: <value>,
            maturity_S7: <value>}
```

**COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list of defects; `total_findings =
len(findings) = novel_count + planned_insufficient_count + planned_unbuilt_count`, and
`total_findings <= 15`. Fully-covered candidates and dismissed facts live in
`rejected_candidates[]`, NOT in `findings[]`. `burden_dispositions`, `rubric_ratings`,
`question_answers`, and `per_surface_assessment` are systems-of-record referenced FROM findings,
never re-counted. `adopted_remedy_count + rejected_remedy_count + deferred_remedy_count = 15 +
len(originated_remedies across all burdens)`, where adopt-as-proposed and adopt-modified both
count as adopted, every originated remedy carries one of those two verdicts and counts as
adopted, and a remedy is counted once under its home burden even when `also_serves` names
others. `top_improvements` and
`highest_leverage_change` MUST be finding ids, and are `[]` and `null` iff `findings[]` is
empty. `sequence_position` is unique and consecutive from
1 over the adopted set and null on every rejected or deferred remedy. Exactly 6
`question_answers`, exactly 8 `external_checklist` rows under Q5, exactly 49 `rubric_ratings`,
exactly 7 `per_surface_assessment`, exactly 3 to 6 `burden_dispositions`, exactly 15 candidate
remedies across B1-B3 (5 each, ids as pinned). An empty `findings[]` with a stated reason is
legal; a missing block is not. A B4-B6 disposition at PARTIAL with zero findings is legal.

`control_property_match` is REQUIRED whenever a compensating control is the reason for a
dismissal: name the property the control exercises, cite where it operates, and state why the
control would FAIL if the defect were real. CONFIRMED requires the behaviour traced to file:line
or an observed sampled artefact; anything less is HYPOTHESIS. A remedy verdict is `confidence:
CONFIRMED` only when its landing surface, carrying cost, and (where one is required) sunset
condition are all re-derived from the repo, not estimated.

## SEVERITY AND MATURITY

Severity is assigned AFTER judgement, by defect class, never inherited from this prompt's
framing or the requester's emphasis:

- **critical** = the workflow can drop committed work with no surfacing path (a split half or
  a confirmed follow-on that nothing will ever present to the human or an agent), OR an
  escalation clause routes a decision to the human that no mechanism can then act on (a dead
  end that leaves the plan in an undefined state).
- **high** = a burden materially increases human decision load or depth on every plan AND the
  compensating controls you traced are insufficient (property-match rule below).
- **medium** = redundancy, ambiguity, or inconsistency between rules with a clear fix (e.g. two
  convergence rules of different kind).
- **low** = clarity or wording.

Property-match rule: a compensating control lowers severity or justifies dismissal ONLY if it
exercises the same property AND would fail if the defect were real -- apply the counterfactual to
the control itself. A control that cannot catch the break neither lowers severity nor justifies
dismissal.

Maturity per surface, computed LAST, top-down, first match wins:

- **frontier** = 0 open critical or high findings on the surface AND no Q5 `external_checklist`
  row rated `missed` whose `evidence` names this surface. This tier stays reachable when a
  property-matched compensating control was argued for a row (rating it `partial`).
- **strong** = 0 critical AND <= 1 high on the surface.
- **solid** = <= 1 critical AND <= 3 high on the surface.
- **nascent** = otherwise.

A finding counts "on the surface" when its `surface` is that id, or when its `surface` is
`shared` and `surfaces_touched` lists that id; a `shared` finding with an empty
`surfaces_touched` counts against none. The
`external_checklist` gates only the top tier, and only for the surfaces a `missed` row's
evidence names; a surface no checklist row names is rated on finding counts alone.

## SELF-VERIFICATION GATE

**DO NOT COMMIT until this gate passes or its round cap binds.** A single reviewer misses
orthogonal defects by definition.

When both deliverables are drafted, dispatch FOUR verifier perspectives in parallel via the
`Agent` tool, `subagent_type: "general-purpose"`. Each dispatch must: identify both deliverable
files by absolute path; state its perspective and nothing else; forbid all writes of any kind
(file edits, Bash-mediated writes, warehouse writes, any GitHub mutation); require
the output shape below verbatim including a final `Verdict:` line; cap the response at ~900
words. Do NOT tell any verifier what you found hard or what a previous round said.

- **R1 -- Cold reader (self-containedness, consistency, coverage).** Reads ONLY the two
  deliverables; forbidden from reading any other file, running any command, or browsing the
  repository. Task: "You are a senior engineer handed this audit and nothing else. List every
  place you cannot follow the reasoning, every claim whose basis is not stated, every id
  referenced that does not appear elsewhere in these files, every enum value outside its
  declared set, every verdict with no rationale, every remedy with no sunset condition where one
  is required, and every place the two files disagree. Check the counting invariant arithmetic
  yourself." Paste into R1's dispatch, inline and verbatim: the COUNTING INVARIANT paragraph;
  every pinned enum (burden verdict, sub-burden verdict including `INDETERMINATE`, remedy
  verdict, `origin`, `t123_relation`, `end_state_disposition` including `n/a`, `vehicle`,
  `sub_burdens_addressed`, Q4 and Q5 verdicts, `disposition`, checklist rating, rubric rating,
  `change_type`, `evidence_kind`, `effort`, `classification`, `severity`, `confidence`,
  `question` including `none`, maturity), the `stale_anchors`, `unresolved_findings`, and
  `depends_on` entry shapes, `surfaces_touched` (present on shared findings; empty is legal),
  `also_serves`, `remedy_id` on every `carrying_cost_by_surface` row, the originated-remedy
  verdict restriction, the id formats (`PDB-NN` consecutive from 01; `B<n>-O<k>`); the
  maturity ladder including the shared-finding rule; the exclusion rules for B2-R1/R2/R3/R5 and
  B3-R3/R5; and the coverage counts: 6 question answers; exactly 8 `external_checklist` rows
  under Q5, each with a file:line or item-id citation; 3-6 burden dispositions with B1-B3
  present; 15 candidate remedies with ids B1-R1..R5, B2-R1..R5, B3-R1..R5, each carrying
  `origin` and `runtime_cost`, non-empty `design_notes` on B1-R1, B2-R1, B2-R3, B2-R4, B3-R3 and B3-R4, every B3
  remedy a non-empty `property_interactions`, every B1 remedy a non-empty `sunset_condition`; a
  non-empty `adopted_set` for every burden not REFUTED; 49 rubric cells; 7 per-surface entries;
  `total_findings <= 15`; an `empirical_sample` of at most 20 plans and 12 recs. "A silently
  truncated audit must not pass."
- **R2 -- Fact auditor (grounding).** Full repository read access. Task: "Independently verify
  every factual claim, file:line anchor, quoted identifier (Decision, tier_item, rec, contract
  key, schema field, check name), measured headroom, and re-derived count in this audit against
  the repository at the audited commit. Re-run every counting command the audit reports. Verify
  `meta.empirical_sample`: every path exists, the caps hold, every four-or-more-round plan (12 at the
  drafting tree; re-derive) is present unless `truncated` is true. An anchor the audit already
  lists in `meta.stale_anchors` with its re-derived `found` value is not a mismatch." Tag each
  `wrong | stale | unverifiable`.
- **R3 -- Adversarial adjudication challenger (anti-deference).** Full repository read access.
  Task: "Contest the VERDICTS, not the facts. For each burden CONFIRMED: is the cause the
  workflow, or the requester's habit? For each REFUTED: is the compensating control
  property-matched? For each adopted remedy: adopted because it is right, or because of who
  proposed it -- the requester (`origin: requester`), the prompt's author (`origin: composer`),
  or the audit itself (`origin: auditor`)?
  Composer-authored candidates carry the same anchoring risk; contest them with the same force.
  For each rejected remedy: argued or asserted? For each originated
  remedy: is it a real mechanism with a landing surface, or a wish? Does the adopted set silently
  transfer authority (NS-A)? Does any adopted remedy contradict a do-not-flag constraint or a
  prior-audit rejection whose revisit condition has not been met? Name every verdict you would
  reverse and why."
- **R4 -- Dedup and ownership auditor.** Full repository read access. Task: "For every finding
  and every remedy verdict, independently search `docs/ROADMAP-PLATFORM.yaml` (tier_items,
  candidate_decisions), `docs/DECISIONS.md`, `logs/.recommendations-log.jsonl`, and
  `audits/*.yaml`, and judge whether `roadmap_crossref.classification`, `owning_end_state_item`,
  and the recorded `dedup_hit_count` are correct. Report every `novel` an existing item owns and
  every dismissal whose named owner does not actually cover it." If `meta.degraded_dedup` is
  true, say so in R4's dispatch and that the rec cache is absent by design; R4 then judges from
  git-tracked surfaces only and files nothing for the missing cache.

Output shape, required of all four:

```
Findings:
1. [blocking|degrading|cosmetic] <one-line title>
   Quote: "<exact text from the deliverable>"
   Problem: <what is wrong>
   Fix: <what would resolve it>
...
Verdict: PROCEED
```

`REVISE` iff any `blocking` finding, or 3 or more `degrading`. R2 and R4 grade on the same
scale: an error that would change a verdict, a severity, a count, a sunset condition, or a
reader's conclusion is `blocking`; one that is real but changes nothing material (an anchor off
by a line, a truncated quotation) is `cosmetic`. Grade honestly in both directions.

**Verdict handling.** The gate passes only when ALL FOUR return `PROCEED` in the SAME round. On
any `REVISE`: synthesize (consensus first), revise the deliverables, and re-dispatch all four
FRESH -- never reuse a verifier's context. Before accepting a unanimous round-1 PROCEED, read each
output; a verifier with zero findings AND fewer than ~10 substantive lines was dispatched too
generically -- re-dispatch that one ONCE with a sharpened perspective (does not increment
`rounds`; a REVISE from it stands and triggers a full fresh round).

**Round cap and degraded paths.** You have no human to escalate to; you must terminate.

- Cap at 3 REVISE rounds. If the gate has not passed after the 3rd revision, STOP revising:
  record every unresolved finding verbatim in `meta.self_verification.unresolved_findings`,
  downgrade the `confidence` of every finding and remedy those findings touch to `HYPOTHESIS`,
  say so in the `.md`, and proceed to commit.
- IF the `Agent` tool is unavailable: set `meta.self_verification.degraded: true`, run the four
  perspectives yourself as four SEPARATE sequential passes re-reading the deliverables from disk
  under each framing alone, record `rounds` as normal, and say in the `.md` that the gate ran
  degraded.
- IF a verifier errors or returns no `Verdict:` line: re-dispatch that one at most TWICE; if
  still no verdict, record it as an incomplete lane in `unresolved_findings`, treat the lane as
  REVISE for that round, and continue -- never count an incomplete verifier as PROCEED.

`rounds` counts REVISE rounds completed, not dispatches: a first-dispatch pass records
`rounds: 0`.

## COMMIT / PR MECHANICS

1. REUSE the sha derived in SETUP -- do NOT re-fetch or re-derive. It goes in both filenames,
   the branch name, and `meta.audited_commit`. `git rev-parse --short <that sha>` is safe;
   `git fetch` followed by a fresh `rev-parse origin/main` is not.
2. You are ALREADY on `audit/planning-decision-burden-<sha>`. Confirm with
   `git branch --show-current`; only if you are not on it, `git switch` to it (or
   `git switch -c ... origin/main` if it does not exist). Branching off `origin/main` rather than
   a `claude/*` session branch is a deliberate, documented exception: this session needs a clean
   two-file diff off the audited base. The CI signal-green comment wake fires only on `claude/*`
   PRs, which is irrelevant here because you end the turn without merging.
3. Verify both deliverables parse:
   `bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"
   audits/planning-decision-burden-<sha>.yaml`. That clean parse is the real pre-push gate.
   Repo-wide validation is advisory outside CI here; an unrelated failure goes in
   `meta.contract_notes` and is never fixed.
4. Stage ONLY the two deliverables by explicit path --
   `git add audits/planning-decision-burden-<sha>.yaml audits/planning-decision-burden-<sha>.md`
   -- never `git add -A` or `git commit -a`, which would sweep in regenerated caches. Commit with
   `user.name=Claude`, `user.email=noreply@anthropic.com`. Message:
   `audit(planning-decision-burden): human-decision burden in the planning workflow`.
5. `git push -u origin HEAD`. IF the push fails: do not retry in a loop; record the error and
   the local branch name in `meta.contract_notes`, state both in your final message so the human
   can push, and stop.
6. Open the PR via `mcp__github__create_pull_request` (base `main`, ready for review, NOT a
   draft). Title: `audit: human-decision burden in the planning workflow (plan, implement, gates,
   orient follow-on, Fable consult)`. Body: a 2-3 sentence lede plus the `summary` block in a
   yaml fence. IF the PR tool is unavailable or errors: do NOT retry in a loop and do NOT abort;
   the pushed branch is the deliverable of record. Note the failure and the exact branch name in
   `meta.contract_notes` and in your final message, and stop.
7. **END THE TURN.** Do not poll. Do not merge. Do not subscribe to PR activity. Do not
   self-approve. The human disposes of the PR.

## GUARDRAILS

**Write boundary, as a closed list.** The only files you create or modify in the repository tree:

1. `audits/planning-decision-burden-<sha>.yaml`
2. `audits/planning-decision-burden-<sha>.md`

Regenerating gitignored caches per SETUP is expected and is not a breach; never commit them. You
make no warehouse write of any kind: no `file_rec`, no `update_rec`, no `sync`, no invocation of
`scripts.ops_data_portal` beyond what preflight itself runs -- `vehicle: rec` names where the
human would route a remedy, never something you file. Every `mcp__github__*` call is read-only
except the single `create_pull_request` in COMMIT / PR MECHANICS step 6: no issue or PR
comments, no reviews, no branch creation, no labels. You modify no audited surface, no skill, no
command, no check, no contract, no plan, no roadmap or decision file, and nothing under
`docs/audit-prompts/`. If you believe one of them should
change, that belief is a finding with a `proposed_change` or a remedy with a landing surface,
not an edit.

**Honesty clauses.** Fewer than ~5 surviving findings is a valid result -- state it; do not pad.
A REFUTED burden is a valid result if its compensating control property-matches -- state it.
Precision over volume: one traced, counterfactual-tested finding outranks five plausible ones.
An originated remedy you cannot give a landing surface and a carrying cost is not a remedy;
record it in Q6 as a question, not in `originated_remedies`. Where the substrate cannot answer
(per-round content squash-merged away, a free-text `gates:` line), say `indeterminate` and let
that be the evidence.

**Scope discipline.** Adjudicate what is asked. Do not re-audit the `/plan` pipeline as a
scaling surface (the prior audit did), do not redesign telemetry, and do not propose a
transcript-analysis system -- state what record an adopted remedy leaves for one, and stop.
