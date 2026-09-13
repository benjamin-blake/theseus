# Planning-Workflow Scaling Review -- executive companion

Audited tree: `369a963a`. Full record: `audits/planning-workflow-scaling-369a963a.yaml`.

**Referents.** Surfaces: S1 /plan pipeline (plan.md + planning skill); S2 plan-critique
skill; S3 decision-scout skill; S4 plan schema + mechanical plan checks; S5 executor
planning path; S6 provenance surface (decision-entry.yaml, decisions index); S7 plan
corpus. Dimensions VD1-VD7: evidence grounding, dedup integrity, mechanization fitness,
weak-model operability, governance-vehicle fit, carrying-cost proportionality, provenance
honesty. Diagnosis claims: D1 round telemetry, D2 mechanical mass, D3 discarded
telemetry, D4 reviewer roulette, D5 inward-only alternatives search. Proposals: P1
persist critique findings; P2 plan-lint domain with seed rules P2a gh / P2b bare python /
P2c local terraform / P2d V3 tags / P2e tier fitness / P2f rec cross-ref / P2g suspect
not-applicable / P2h SLOC headroom; P3 lint at three surfaces; P4 provenance rule; P5
Alternatives marker; P6 re-round convergence discipline; P7 zero-context cold read; P8
plan schema v5; P9 critique lanes; P10 per-plan world scout; P11 horizon scan; P12 plan
classes; P13 confidence-gated escalation; P14 ratchet loop; Alt-1 swarm authorship;
Alt-2 separate reviser.

## What to do, in order

No proposal survived as ADOPT-NOW in its original form. Five adopted with modification,
five deferred to the roadmap, five rejected, one duplicate of already-decided work. The
19-item sequence:

1. **Fix the gate-record substrate first (PWS-01, the highest-leverage change).** The
   `gates:` context line -- the prior audit's WF-08 remedy -- is free text that nothing
   validates. 29 plans carry the literal unfilled `<verdict> after <N> round(s)`
   placeholder (including current schema-v4 plans), roughly 20 grammars coexist, and the
   round-count regex the diagnosis rests on reaches 112 of the 230 plans recording any
   critique verdict; 157 of 358 plans (44 percent) carry no parseable verdict at all.
   Root cause is sequencing: the line is authored at Step 8, before the Step 9 gate
   produces the data it records. Pin one grammar (with a gate_run_id slot -- coordinate
   with open recs 3041/2480/2798/2804), validate it on net-new plans inside
   `validate_plan_documents`, name Step 11 as the finalization point. Until this lands,
   every rounds-metering idea in the proposal set reads a corrupted instrument.
2. **The provenance pair (P4 then P5).** One candidate Decision ratifies the honesty
   norm -- absence of a Decision means UNDECIDED; agents never author a rationale for a
   rejected alternative without citing a Decision or a human; `never_evaluated` is an
   honest, expected output -- authorizes an `alternatives` field in the decision-entry
   metadata **envelope** (not a fifth bold marker; the contract's own precedent rules
   that shape) with "none -- default taken" as a first-class value, and carries a
   byte-neutral rewording of plan-critique 12g so the norm reaches the gate question
   that currently invites confabulated rationale.
3. **The lint engine and six of P2's eight seed rules (P2, then P2a/P2b/P2c/P2f/P2g/
   P2h -- ordered by recurrence evidence), then P3's wiring.** Rules land in the
   existing `roadmap/` (or `verification/`) check domain, engine as a library; open
   rec-389 (structural plan constraints) is the plan's natural bundling target. P2d and
   P2e are duplicates: the schema already enforces phase tags on v2+ plans, and the
   tier-fitness check exists -- see PWS-06. P3 rides the two `plan_obligations`
   invocations the workflow already makes; the executor surface waits out the Decision
   67 freeze.
4. **N1 (originated here): shrink plan-critique to judgement-only rows.** All sixteen
   proposals add machinery; the corpus's commitments point the other way -- T2.56 c1
   commits to measurably shrinking the skills layer and plan-critique sits at 7 bytes of
   prose headroom. Once P2/P3 mechanize a Phase 2 row, delete its prose and leave a
   pointer to the contract rule table. Position 13 is PWS-07's stale-citation sweep.
5. **P11, de-scoped and sunset-bounded:** the horizon scan runs off the existing
   `cost_reconciliation` trigger hook or operator invocation -- not a new scheduled
   agent while T4.12 holds -- filing at most 3 recs with a do-nothing row, and retires
   after two zero-yield passes (the adoption rests on a yield hypothesis this audit
   could not sample; confidence HYPOTHESIS).
6. **Roadmap tail, dependency-ordered:** P8 (typed assumptions/rejected-alternatives;
   the verbatim evidence pack must shrink to pointer grade -- as proposed it contradicts
   the shipped context-block discipline), P12 (plan classes -- the best weak-executor
   idea, consumer-less until the freeze reverses; route to T4.10a territory), P9 (lane
   decomposition -- the T4.2/T4.6 critic-persona shape, not an interactive retrofit
   that 3-4x's dispatch cost on an unmeasured gate), P13 (extend the trigger-table
   escalation pattern, not self-reported confidence), P14 (the ratchet -- sound,
   specific, unrunnable until the Decision 87 clause 4 substrate and PWS-01's record
   exist).

**Rejected:** P6 (re-round admission-narrowing contradicts the deliberately ratified
fresh-full-re-evaluation principle, solves a consequence D4 could not prove, and needs
the unbuilt persistence substrate), P7 (Step 9 already dispatches a zero-planning-context
reader with repo access -- exactly the context class the plan's real consumer has; a
repo-blind V1-style read over-tests an artifact whose consumer is never repo-blind), P10
(P11 does the same outward search at portfolio grain for less; the rejection carries a
revisit condition keyed to P11's sunset), Alt-1 and Alt-2 (both original rejections
survive re-derivation on repo-specific grounds: every shipped fan-out is read-only, and
revision deliberately keeps the author's context). **Duplicate:** P1 -- Decision 87
clause 4 as amended already rules where critique imperatives (`critique_history` on the
one plans table) and deliberation (telemetry) live; T4.5/T4.6/T4.16, T2.36/T3.20 and
rec-3080 own building it. A new findings table or per-round artifact would contradict a
ratified consolidation.

## Weak-executor prerequisites vs interactive quality-of-life

Executor-prerequisite, ranked: **PWS-01, P2, P2a, P2b, P2c, P3, P4.** These remove
judgement a weak model cannot be trusted to hold: record discipline (frontier models
already failed it 29 times in this corpus), command-idiom discipline (rec-3301 shows
even frontier sessions keep authoring `gh`), and the do-not-confabulate-provenance rule.
Quality-of-life, ranked: **P2h, P2g, P2f, P5, N1, P11, PWS-07** -- better inputs and
less load for the frontier critic, no guarantee-bearing judgement removed. P12 and P8
would top the executor list but carry ROADMAP verdicts, which win over ranking.

## Diagnosis verdicts (Q1: mixed)

- **D1 CONFIRMED.** 112 matches (claim ~110); 40.2 / 27.7 / 23.2 / 8.9 percent across
  1/2/3/4-5 rounds; exactly 9 REVISE-ended. All within tolerance (per-figure deviations
  0.5 to 11.25 percent). The regex covers 48.7 percent of verdict-recording plans --
  confirmed telemetry over a partial substrate.
- **D2 PARTIAL.** The mechanizable mass is real -- 11 of the pinned 23 obligations carry
  mechanical cores, five already partially mechanized in schema or checks -- but
  "majority" fails by one (47.8 percent) and judgement is the actual majority. The
  Finding-Origin Attribution field tags only registration-closure findings, not the
  whole split.
- **D3 PARTIAL.** True for the interactive path; false for the executor path, where
  `critique_plan()`'s `full_output` persists per round into `ops_execution_plans`.
- **D4 PARTIAL.** The fresh-full-re-dispatch mechanism is verbatim in the skill; the
  tail-inflation consequence is unprovable on a record that discards per-round content
  and squash-merges revisions. One sampled plan shows new findings in rounds 2-3 --
  occurrence, not inflation.
- **D5 CONFIRMED.** Inward-only search on every asserted surface; required markers are
  Status/Date/Decision; zero `never_evaluated`/confabulation vocabulary anywhere.

## Findings that most change the picture

Eight findings; none critical. **PWS-01** (high, observed) is the center of gravity: it
degrades the prior audit's shipped remedy, corrupts the measurement substrate for Q6's
cost/outcome questions, and gates P6/P9/P14. **PWS-06** (medium, observed):
`validate_tier_floor` evaluates only `schema_version == 2` -- 7 of 358 plans, zero of
the 56 current-generation v4 plans -- so the deterministic floor the roadmap records as
complete (T3.17) is dormant on every plan authored today; open rec-3285 owns the fix,
and the gate's 12m judgement is the only live cover. **PWS-02/PWS-05/PWS-03** are the
D2/D5/D3 defects: mechanizable rows executed as judgement (fixed by P2/P3/N1), no
decided-vs-never-evaluated distinction (fixed by P4/P5), and ruled-but-unbuilt critique
persistence (owned by T4.5/T2.36). **PWS-07/PWS-08** are drift-grade: three gate
surfaces still justify bounded reads by the ceiling Decision 179 retired, the
obligations contract counts six registration surfaces against registry.py's seven, and
preflight hardcodes `friction_patterns` empty under a consumer branch that can never
fire.

Two non-findings worth stating plainly. No evidence any gate reported PROCEED on a plan
its rules should have blocked -- anomalous-looking records (a merged REVISE-after-4
plan) trace to the human-escalation path working as designed. And the Step 9 gate's
effectiveness is unmeasured (Q6 seed 8): nothing links a gate verdict to its plan's
implementation outcome, so the entire proposal set optimizes an input metric. That
absence -- not any single proposal -- is what PWS-01 plus the Decision-87-owned
persistence work would repair.

## Method notes

Preflight and dedup caches were live (not degraded). The 25-plan sample spans all ten
4/5-round plans, six no-gate-line plans, three literal-placeholder plans, and a 1-3
round spread; nine were counterfactual-non-discriminating. One prompt anchor re-derived
differently (recorded in `meta.stale_anchors`): nine checks gate `docs/plans/**`, not
eight. The four-perspective self-verification gate ran one REVISE round; outcome in
`meta.self_verification`.
