# AUDIT: Planning-Workflow Scaling Review (Proposal Verification)

## TASK

Audit the `/plan` planning workflow as a scaling surface. Three jobs, in order: (1) verify five
diagnosis claims (D1-D5) against the repository as it stands; (2) adjudicate sixteen proposals
(P1-P14, Alt-1, Alt-2) to a pinned verdict each; (3) produce a dependency-ordered adoption
sequence naming a concrete expression vehicle per adopted item, plus a ranking of adopted items
by whether they are load-bearing prerequisites for a weak-model autonomous executor or
quality-of-life for interactive sessions.

Every proposal below originates from an AI advisory conversation. NONE is backed by a Decision,
a roadmap item, or a human ruling. Treat each as never-evaluated. REJECT is a fully acceptable
verdict; so is DUPLICATE. Do not manufacture agreement, and do not treat the originating
analysis as correct because it is stated confidently. The Group A / Group B split below is the
originating analysis's ASSUMPTION, not a finding -- rederive placement per proposal.

Deliverables: `audits/planning-workflow-scaling-<sha>.yaml` and
`audits/planning-workflow-scaling-<sha>.md`. The ONLY files you create or modify in the
repository tree are those two. Regenerating gitignored local caches per SETUP is expected and
does not breach this; never commit them. You draft; the human disposes. You do not implement
anything, and you modify no audited surface.

## CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts.

**ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.** Every observation in the GROUNDING
MAP and CANDIDATE OBSERVATIONS sections is stated neutrally and deliberately carries no
adjective implying a defect. **A run that merely confirms the candidates below has failed.**

Per-candidate adjudication enum, with its mapping to the output contract pinned:

- CONFIRMED-defect -> `findings[]`, `roadmap_crossref.classification: novel`
- planned, but the owning item's remedy is insufficient or unbuilt -> `findings[]`,
  classification `planned-insufficient` or `planned-unbuilt`
- planned and fully covered by the owning item -> `rejected_candidates[]`
- not-a-defect -> `rejected_candidates[]`, naming the compensating control

A proposal verdict is a separate axis from a finding: a proposal may be REJECTED without any
finding, and a finding may exist with no proposal attached to it.

## READ FIRST -- DISAMBIGUATION TRAPS

Five hazards where one name denotes two things. Misreading any of these will produce a wrong
audit.

1. **`WF-08`, `WF-17`, `WF-05`, `WF-06` are finding ids from a PRIOR AUDIT of these same files**
   (`audits/workflow-review-d107b4a.yaml`, 20 findings, scope_files = the nine orient/plan/
   implement commands and skills). They are not schema fields. That audit's remedies are
   partially shipped and are load-bearing dedup surface for this one. Read its findings list
   before adjudicating anything.
2. **Two different critique systems share the word "critique."** (a) The `plan-critique` SKILL
   -- the interactive Step 9 gate, dispatched as a fresh-context subagent. (b) The executor's
   `critique_plan()` in `scripts/executor/plan_generation.py`, a single LLM round-trip against
   `config/agent/executor/prompts/critique.prompt.md` that parses a free-text
   `VERDICT: APPROVED|NEEDS_REVISION` line. **The executor does not invoke the plan-critique
   skill at all.** Claims about "the critique gate" are true of one, both, or neither -- say
   which.
3. **Two different "plan critique gates" inside `/plan`.** Step 9 critiques the PLAN artefact
   (single subagent, loop-on-REVISE). Step 10 critiques a REPORT-ONLY deliverable and is
   already a parallel multi-perspective fresh-context gate with orthogonal-lens rules, a
   re-critique-after-revision rule, and a 3-round cap. Step 10 exists today; do not report it
   as absent.
4. **"Convergence" denotes two unrelated things.** `convergence_health` /
   `convergence_rca_gap_alert` / `convergence_sensor_liveness_alert` in
   `logs/.preflight-report.json` are TERRAFORM apply/drift signals. Critique-round convergence
   is unrelated and has no preflight key.
5. **Plan persistence differs by path.** `ops_execution_plans` (DuckLake, SCD2) holds
   EXECUTOR-authored plans and carries a registered `critique_history` column. Interactive
   `docs/plans/PLAN-{slug}.yaml` remains git-authoritative (Decision 87 cl.2/cl.3), with
   `ops_execution_plans` scoped as a downstream read-projection until a T4.x authority flip.
   "Plans are persisted in the warehouse" is true of one path only.

## SCOPE

**Built surfaces (in scope).**

- S1 `/plan` pipeline: `.claude/commands/plan.md`, `.claude/skills/planning/SKILL.md`
- S2 `.claude/skills/plan-critique/SKILL.md` (the Step 9 gate)
- S3 `.claude/skills/decision-scout/SKILL.md` (the Step 6a gate)
- S4 Plan schema + the mechanical plan-gating checks: `scripts/roadmap/plan_document.py`,
  `scripts/roadmap/plan_obligations.py`, `docs/contracts/plan-obligations.yaml`, and the checks
  under `scripts/checks/` that gate `docs/plans/**` (enumerated in the GROUNDING MAP)
- S5 Executor planning path: `scripts/executor/plan_generation.py`,
  `scripts/executor/acceptance_lint.py`
- S6 Provenance surface: `docs/contracts/decision-entry.yaml`, `docs/decisions-index.json`
- S7 Plan corpus: `docs/plans/*.yaml` as a telemetry substrate

**Context-only (read to judge, never audit as a target).** `.claude/skills/audit-prompt/SKILL.md`
and `.claude/skills/overseer/SKILL.md` are cited as precedents by proposals P7 and P13; assess
whether the precedent transfers, do not rate those skills. `/orient` and `/implement` are in
scope ONLY where a proposal touches their seam with `/plan`.

**Out of scope.** The four-tier workflow's existence (Decision 90). The Decision 67 executor
freeze and its STRATEGIC-plan suspension. The choice of executor model. Terraform, IAM, CI
workflow design, and the DuckLake substrate except where a proposal writes to it.

**Trust-nothing clause.** Obtain every file, line, size and count by reading the repository.
Trust no number quoted in this prompt. Re-derive each one and record any anchor that does not
resolve in `meta.stale_anchors` with what you found instead. A quoted count that re-derives to a
different value is itself worth recording; it is not a reason to abort.

**Vocabulary.** *Mechanical* = decidable by a deterministic program from the plan file plus repo
state, with no model judgement. *Semi-mechanical* = a deterministic trigger followed by a
judgement call. *Judgement* = neither the trigger nor the verdict is deterministic. *Vehicle* =
the governed artifact through which a change is expressed (see Q3's enum). *Gate* = a blocking
step that emits a verdict. *Lane* = one parallel fresh-context subagent within a decomposed gate.

## SETUP

Run these, in order, before anything else.

```
git fetch origin main
git rev-parse --short origin/main          # this sha IS the audited tree; use it everywhere
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

The preflight call populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`,
which DEDUP DISCIPLINE requires.

**Degraded paths -- never abort, never improvise:**

- IF preflight fails on credentials or egress: do NOT abort. Set `meta.degraded_dedup: true`,
  mark every `roadmap_crossref.confidence` as HYPOTHESIS, set every `dedup_hit_count` to null,
  and proceed. Dedup then runs against the git-tracked sources only
  (`docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`, `audits/*.yaml`).
- IF `logs/.recommendations-log.jsonl` is absent or empty: same flag, same downgrade.
- IF an anchor in this prompt does not resolve: record it in `meta.stale_anchors` and re-derive
  the fact from the repo before relying on it.
- IF `bin/venv-python -m scripts.validate --pre` is run and fails on something unrelated to your
  two files: record the failing check name in `meta.contract_notes` and proceed. Repo-wide
  validation is advisory outside CI here (Decision 73). **Never fix it** -- that breaches the
  write boundary. A clean YAML parse of your two deliverables is the real pre-push gate.

Read `docs/PROJECT_CONTEXT.md` in full. Do NOT read `docs/ROADMAP-PLATFORM.yaml` or
`docs/DECISIONS.md` in full -- both are large. Use targeted projections: a
`bin/venv-python -c` `yaml.safe_load` projection over the roadmap's `tier_items[]` and
`candidate_decisions[]`, and `rg "^## Decision N:"` plus `awk` range extraction for named
decision sections.

## NORTH STAR

The bar each surface is judged against. These are principles you ARGUE a surface against, not
rules you pattern-match. A surface may fall short of one and still be right; say why.

- **NS-A Agent-first artifacts.** Machine-parseable beats prose when both are available. A
  human-readable companion alongside a machine-readable source is drift by design.
- **NS-B Mechanical floor, judgement ceiling.** Anything decidable by a program should be
  decided by a program, so scarce model judgement is spent only on what is genuinely
  undecidable. The converse is equally load-bearing: mechanizing a judgement call produces a
  confident wrong answer, which is worse than an honest uncertain one.
- **NS-C Evidence over assertion.** A control that is promised but not instantiated is a
  phantom control. A signal is not proof; a recommendation is not authority.
- **NS-D Provenance honesty.** A record must distinguish what was decided from what was never
  evaluated. An agent must never author a rationale for a choice nobody made.
- **NS-E Bounded, governed change.** Every change is expressed through a governed vehicle and
  carries its real cost -- surfaces touched, budget consumed, contracts re-ratified.
- **NS-F Weak-model operability.** The workflow must eventually be executable by a model
  materially weaker than the one running it interactively today, without silently degrading the
  guarantee.

## THE QUESTIONS

Each question gets its own first-class answer slot in the output.

**Q1 -- Diagnosis verification.** For each of D1-D5: CONFIRMED, PARTIAL, or REFUTED, with
evidence. PARTIAL is the right verdict when the claim's mechanism holds but its stated scope,
magnitude, or causal inference does not; say precisely which half fails. Record per-claim
verdicts in the `diagnosis_verdicts` block. Q1's own verdict enum:
`all-confirmed | mixed | all-refuted`.

The five claims, as asserted by the originating analysis:

- **D1 (round telemetry).** ~110 plans carry a context line `plan-critique=<verdict> after <N>
  round(s)`; distribution ~40% converge in 1 round, ~28% in 2, ~23% in 3, ~8% in 4-5, 9 ended
  REVISE. Re-derive with `rg -o --no-filename "plan-critique=\w+ after \d+ round" docs/plans/`
  (note: `-h` is ripgrep's help flag, use `--no-filename`). Then determine what fraction of the
  corpus, and of plans that record a critique verdict at all, that regex actually captures.
- **D2 (mechanical mass).** plan-critique Phase 2 (checks 6 through 12p) is majority mechanical
  or semi-mechanical; genuine judgement (Phase 2b frame challenge Q1-Q5, adequacy calls) is a
  small fraction of the skill's total obligations. The output template's `Finding-Origin
  Attribution` field already tags the split.
- **D3 (discarded telemetry).** Critique finding CONTENT is discarded with the subagent
  transcript; only verdict and round count persist. No artifact or table stores findings.
- **D4 (reviewer roulette).** Each REVISE round re-launches a fresh full re-evaluation, so new
  unrelated findings can appear per round, inflating the D1 tail.
- **D5 (inward-only alternatives search).** plan-critique's Frame Challenge searches only
  repo-resident capabilities; no gate searches the external option space.
  `docs/contracts/decision-entry.yaml`'s `required_markers` are Status/Date/Decision with no
  alternatives-considered marker, so a deliberate choice and a default-taken-for-lack-of-
  knowledge are indistinguishable in the corpus.

D2 and D4 each contain a mechanism claim and a consequence claim. Verify them separately. For
D4 specifically: the re-dispatch mechanism is one thing; that it *inflates the tail* is a causal
claim that needs evidence beyond the mechanism's existence.

**Q2 -- Proposal adjudication.** For each of P1-P14, Alt-1, and Alt-2, exactly one of:
`ADOPT-NOW | ADOPT-MODIFIED | ROADMAP | REJECT | DUPLICATE`, with a one-paragraph rationale,
and for ADOPT-MODIFIED the specific modification. DUPLICATE requires naming the existing check,
rec, tier_item, Decision, or in-flight work that already owns it, AND a property-match argument
(see SEVERITY). Dedup BEFORE assigning a verdict. Record per-item verdicts in the
`proposal_adjudication` block. Q2's own verdict enum:
`adjudicated | partially-adjudicated | not-adjudicable`.

*Group A, assumed by the originating analysis to be immediately implementable:*

- **P1 Persist critique findings.** Store each plan-critique report's findings durably.
  Candidate shape offered: one row per finding, append_only, via the ops portal; alternative
  offered: a committed artifact per round. Prerequisite for P14. You pick the vehicle, or reject
  the premise.
- **P2 `plan_lint` check domain** under `scripts/checks/`, seeded from plan-critique's
  mechanical rows and known pitfalls: `gh ` CLI in VP commands; bare `python`/`python3` instead
  of `bin/venv-python`; local `terraform init/validate/plan` in VP steps (Decision 119); missing
  pre/post-deploy tags on V3; tier-fitness computation (check 12m); a rec id named in
  intent/context but absent from `bundled_recommendations` (12k trigger 1); suspect
  `not-applicable` graduation where the command matches a `CANONICAL_SLOTS` shape (12o); an SLOC
  headroom table for scope files (current SLOC vs `config/sloc_budgets.yaml` budget) so
  decomposition is planned up front (Decision 128). Adjudicate the DOMAIN proposal and each of
  the eight seed rules separately -- they do not share a fate.
- **P3 Run the same lint at three surfaces:** plan-authoring time (self-lint before critique
  dispatch), critique time (lint report attached; critic judges only judgement rows), executor.
- **P4 Provenance rule.** Absence of a Decision means UNDECIDED, not decided. Agents must never
  author a rationale for a rejected alternative without citing a Decision or a human statement;
  the honest output is `never_evaluated -- no recorded decision, flagging to human`.
- **P5 Optional-but-canonical `Alternatives` marker** in `decision-entry.yaml`, with honest
  values including "none -- default taken, not deliberately chosen"; forward-enforced on new
  entries only, like the existing markers.
- **P6 Convergence discipline for critique re-rounds.** Pin the prior round's findings; a
  re-round verifies pinned findings resolved plus lint-clean; new findings admissible only at
  WARN+ or on sections the revision redesigned; full fresh re-critique only when the design
  changed.
- **P7 Zero-context cold-read gate on the plan artefact** ("execute step 1 mentally; what is
  missing from the plan?"), testing self-containedness directly. Cited precedent: the
  audit-prompt skill's V1 cold-executor verifier.

*Group B, assumed by the originating analysis to be future ambitions:*

- **P8 Plan schema v5:** `assumptions`, `rejected_alternatives`, and an evidence pack (scout
  report verbatim, affected-artifacts computation, SLOC headroom, precedent list) so downstream
  agents verify recorded evidence instead of re-deriving it.
- **P9 Decompose plan-critique into parallel fresh-context lanes:** precedent scout (corpus of
  existing plans, checks, contracts), frame challenger (strongest model; fed a machine-readable
  capability index instead of prose), adequacy judge (test obligations, waiver honesty, VP
  depth), thin alignment/verdict merge. Lane admission recipe offered: bounded question +
  bounded corpus + mechanical-first evidence procedure + typed output + fresh context. Lanes
  evictable by finding telemetry (P1).
- **P10 Outward frame-challenge lane ("world scout"):** for plans making substrate-shaped
  commitments only, name the top 2-3 external ways to reach the same goal, one-line tradeoff
  each, each tagged `considered_and_rejected(dec-NNN)` / `rejected_here` / `never_evaluated`,
  plus a mandatory do-nothing row.
- **P11 Telemetry-triggered horizon scan (portfolio level):** periodically, or when cost
  reconciliation shows a dominating bill line, enumerate load-bearing substrate commitments
  (derivable from Decisions plus `terraform/`) and ask what the world has produced for that role
  since the Decision's date. Output at most 3 evidence-linked recs with a horizon-scan source
  tag, a switching-cost estimate, and a do-nothing row; never proposes migrations directly;
  substrate changes still route through a Decision with reversal conditions.
- **P12 Plan classes/templates for the executor:** a `plan_class` field with per-class skeletons
  (pre-filled VP shapes, known obligations) for recurring families visible in the corpus
  (`PLAN-sloc-*`, `PLAN-ci-rca-*`, `PLAN-close-audit-*`); executor planning becomes slot-filling;
  blank-page planning stays interactive.
- **P13 Generalized confidence-gated escalation valve:** extend the overseer skill's Fable
  advice-consult protocol so critique lanes and the executor emit confidence and escalate
  low-confidence load-bearing calls to a frontier model or the human instead of guessing.
- **P14 The ratchet loop:** a periodic pass over persisted findings (P1); any judgement-tagged
  finding category recurring 3+ times becomes a candidate lint rule or contract row, filed as a
  rec.

*Rejected by the originating analysis -- adjudicate these too; you may overturn either rejection:*

- **Alt-1 Swarm decomposition of plan AUTHORSHIP** (sub-planning the design itself). Rejected as
  seam-mismatch-prone; fan-out was endorsed for evidence-gathering and critique only.
- **Alt-2 A separate fresh-context REVISER agent** (drafter hands off, reviser applies critique).
  Rejected as losing rejected-alternative knowledge and manufacturing oscillation; the analysis
  replaced it with P6 + P8.

**Q3 -- Adoption sequence and vehicle.** For everything adopted (ADOPT-NOW or ADOPT-MODIFIED, and
each ROADMAP item at its position), give a dependency-ordered sequence and, per item, the
concrete expression vehicle. Vehicle enum, pinned:
`implementation_plan | rec | tier_item | candidate_decision | contract_amendment | none`.
Constraints that bind every vehicle choice: Decision 67 permits IMPLEMENTATION plans only (no
STRATEGIC decomposition) while the freeze holds; Decision 86 forbids new standing prose-
architecture docs, so anything that would become one routes to a contract, a tier_item, or a
Decision -- say which. State the dependency basis for each edge, not just the order. Q3's verdict
enum: `sequenced | partially-sequenced | not-sequenceable`.

**Q4 -- Weak-executor prerequisite vs interactive quality-of-life.** Rank the adopted items into
two ordered lists: those that are load-bearing prerequisites for a weak-model autonomous
executor (NS-F), and those that are quality-of-life for interactive frontier-model sessions.
Justify each placement by naming the specific judgement load the item removes or fails to
remove. An item may appear in both lists only if you argue the two roles separately. Q4's
verdict enum: `ranked | partially-ranked | not-rankable`.

**Q5 -- What the requester did not think to ask.** Answer AND extend these. Seeds, each of which
you must answer explicitly:

1. The prose-budget registry is ratchet-down-only and seeded at zero headroom. Does that change
   which proposals are cheap and which are expensive, and does it change any verdict?
2. Roadmap item T2.56 c1 (in_progress) commits to measurably SHRINKING the skills layer to
   machine-enforced norms plus pointers. Several proposals add skill prose. Is that a
   contradiction, and if so which proposals lose?
3. The `plan-critique=... after N round(s)` line is free-text and matched by the D1 regex on only
   part of the corpus. Is round count a sound measurement substrate for any proposal that
   depends on it (P6, P9, P14)?
4. Does the D1 tail indicate a critique-quality problem or a plan-complexity problem, and does
   any proposal distinguish them?
5. Should this audit have rated the workflow against named external/industry practice? It was
   deliberately not asked to, and you are NOT authorized to perform outward web research here
   (see GUARDRAILS). Say whether that omission materially weakened the audit.
6. Is `plan-critique` the right place for judgement at all, given what `/implement` re-derives
   downstream?

Q5's shape differs from the others: `{q: Q5, answers: [{question, answer, basis: [finding ids]}]}`.

## RUBRIC

Rate each surface S1-S7 on each dimension. Pinned enum: `strong | adequate | weak | absent | n/a`.
`n/a` is correct and costless where a dimension does not structurally apply to a surface -- never
manufacture a rating or a finding to fill a cell. These ratings establish the baseline the
proposals act on; a proposal's value depends on the rating of the surface it targets.

- **VD1 Evidence grounding** -- are the surface's own claims and rationales traceable to live
  repo state, or do they cite retired or superseded premises? (serves Q1, Q5)
- **VD2 Dedup integrity** -- does the surface duplicate an obligation another surface already
  enforces, or leave one unowned? (serves Q2)
- **VD3 Mechanization fitness** -- is anything decidable left to judgement, and is any judgement
  call being decided mechanically? (serves Q1/D2, Q2 for P2/P3/P6)
- **VD4 Weak-model operability** -- could a materially weaker model execute this surface's
  obligations without silently degrading the guarantee? (serves Q4)
- **VD5 Governance-vehicle fit** -- are the surface's obligations expressed through the right
  governed artifact under Decisions 67/86/128/169? (serves Q3)
- **VD6 Carrying-cost proportionality** -- does the surface's maintenance cost (prose budget,
  registration surfaces, contract re-ratification) match the defect class it catches? (serves
  Q2, Q3, Q5)
- **VD7 Provenance honesty** -- does the surface distinguish decided from never-evaluated?
  (serves Q1/D5, Q2 for P4/P5)

## DEEP-DIVES

Four threads that need end-to-end tracing rather than a rubric cell.

**DD-A -- The mechanical/judgement boundary.** Enumerate every obligation in plan-critique Phase
2 (checks 6, 7, 8, 9, 10, 11, 12, 12b, 12c, 12c-1, 12d, 12k, 12l, 12m, 12n, 12o, 12p) and Phase
2b (12e-12j). Classify each as mechanical, semi-mechanical, or judgement using the SCOPE
vocabulary. Then cross it against the checks that already gate `docs/plans/**` and determine,
per obligation: already mechanized elsewhere / deliberately left to judgement with a recorded
rationale / mechanizable but unmechanized. Note especially where a check's own docstring states
that it declined to mechanize something and assigned it to this gate. Feeds Q1(D2), Q2(P2/P3/P6),
VD3.

**DD-B -- What actually persists from a critique round.** Trace both paths end to end. Interactive:
Step 9 subagent output -> what reaches `PLAN-{slug}.yaml` -> what reaches any store. Executor:
`critique_plan()` -> `ExecutionPlan.critique_history` -> `save_plan` -> `ops_execution_plans`.
Then read Decision 87 clause 4 as amended 2026-08-19 and determine what it already rules about
where critique directives and critique deliberation live, and what T4.5/T4.6/T4.16 already own.
Feeds Q1(D3), Q2(P1/P9/P14), VD2.

**DD-C -- The option-space search axis.** Determine what searches the option space today and how
far each reaches: decision-scout Phase 2, plan-critique Frame Challenge 12e-12i, the
`fallback_reevaluation` carrier, `cost_reconciliation.py`'s reevaluation triggers. For each,
state the corpus it searches and the corpus it does not. Then determine what P4, P5, P10 and P11
each add versus duplicate, and for P5 specifically, adjudicate the SHAPE question: a bold
`required_markers`/`optional_markers` entry versus a YAML-envelope field, given what
`decision-entry.yaml` records about which of those two homes new decision metadata belongs in.
Feeds Q1(D5), Q2(P4/P5/P10/P11), VD7.

**DD-D -- Carrying-cost accounting.** For every item you adopt (ADOPT-NOW or ADOPT-MODIFIED),
enumerate the concrete surfaces its adoption must touch: registration surfaces for a new check;
prose bytes plus the Decision-cited raise marker for skill prose; contract fields plus any
re-ratification trigger tripped; schema version bump plus corpus compatibility for a plan-schema
field. An item whose carrying cost you cannot enumerate is not ready for ADOPT-NOW -- say so and
move it. Feeds Q2, Q3, VD6.

## GROUNDING MAP

This map spends your cognition on judgement, not grep. Every entry was read from the repository,
but anchors rot: **verify each before relying on it**, and record non-resolvers in
`meta.stale_anchors`. Facts here are stated neutrally and carry no verdict.

**The Step 9 critique loop**
- `.claude/skills/planning/SKILL.md:569` opens the Critique Gate section. `:593` reads "re-launch
  the same subagent invocation against the revised plan. Each Agent call is a fresh window, so
  the re-launch genuinely re-evaluates." `:594` "Loop if REVISE. Proceed if PROCEED." `:597`
  "Convergence rule: after 3 REVISE rounds, escalate to the human."
- `.claude/skills/planning/SKILL.md:525` makes the context line a REQUIRED plan-template item:
  `"gates: decision-scout=<verdict>; plan-critique=<verdict> after <N> round(s)"`, annotated
  `# REQUIRED ITEM (WF-08)`. `:524` is the companion `# REQUIRED ITEM (WF-04a)` scout-CITE item.
- `.claude/commands/plan.md:99` is Step 9; `:105` is Step 10, the REPORT-ONLY multi-perspective
  gate (parallel dispatch, orthogonal-lens rule, re-critique-after-revision rule, 3-round cap,
  and an explicit anti-pattern list including "single critique agent" and "auto-accepting PROCEED
  on round 1").

**plan-critique structure**
- `.claude/skills/plan-critique/SKILL.md:32` opens Phase 2; `:93` opens Phase 2b (Frame
  Challenge, MANDATORY); `:99`-`:107` are frame questions 12e-12i; `:109` is 12j, the rule that
  a frame challenge yields REVISE only on a concrete contradiction.
- `:157` is the output template's `**Finding-Origin Attribution:** mechanical
  (scripts.roadmap.plan_obligations) / critic judgement -- tag each registration-closure
  finding`. Note the scope of the trailing clause when assessing D2's claim that this field
  "already tags the split."
- `:26` instructs a targeted decision extraction rather than a full read, justified as "it is
  large (near its Decision 134 size ceiling)". The same phrase appears at
  `.claude/skills/planning/SKILL.md:432` and `.claude/commands/plan.md:47`.

**Decision 179 (2026-08-31, on the audited tree)** retired three decision-corpus stock ceilings:
the live-header ceiling, the combined-bytes ceiling, and the committed-index ceiling; it amends
Decisions 134, 160 and 166. Its stated premise is that "no consumer loads the live corpus
wholesale." What survives is Decision 167 clause 3's per-entry authoring cap of 6,144 bytes
(heading-to-next-heading), hard-failing in `--pre` via
`scripts/checks/decisions/validate_decisions_size.py`, whose reversal condition (a) states the
response to cap pressure is compaction or trimming, "never a raise to fit."

**Provenance surface**
- `docs/contracts/decision-entry.yaml:87` `required_markers: [Status, Date, Decision]`. `:94`
  `optional_markers_fixed_spelling: [Problem, Intent, Rationale, Reversal conditions, Related,
  Warehouse ID]`.
- `:364`-`:365` record that a claim is carried "as a `required_fields` entry, NEVER as a fifth
  top-level required_markers bold marker ... 'not as a fifth bold marker'". `:378`-`:379` give
  the YAML envelope's `required_fields: [number, significance]` and
  `optional_fields: [status, decided_date, amends, supersedes]`.
- The optional `Intent` marker was added by Decision 151 from a prior audit finding (DCG-06) --
  a shipped precedent for adding an optional marker forward-enforced.
- `docs/decisions-index.json` is a committed projection generated solely from `DECISIONS.md` and
  `DECISIONS_ARCHIVE.md`. Per `.claude/skills/decision-scout/SKILL.md:26`, each live entry
  carries `title`, `triage_excerpt`, `currency` and `category_tags`; `:43` describes a mechanical
  `category_tags` set-intersection as the shortlisting step.
- Repository-wide searches for `never_evaluated`, `confabulat`, and "absence of a decision"
  return no hits in `docs/DECISIONS.md`, `docs/contracts/*.yaml`, or `.claude/skills/*/SKILL.md`.

**Plan schema and the checks that gate `docs/plans/**`**
- `scripts/roadmap/plan_document.py` defines `PlanDocument` (`extra="forbid"`). It has no
  `assumptions`, `rejected_alternatives`, `plan_class`, or evidence-pack field.
  `:92` `phase: str = Field(min_length=1)` on `VerificationStep` (compare with the values
  downstream consumers branch on). `:232` is the document-level `phase`. The schema already
  performs command-semantics analysis: `_partition_command` (shlex) and `_argument_selects`
  decide test-obligation hosting by pytest argument semantics and hard-reject explicit exclusion.
- Checks gating `docs/plans/**`, all registered under `scripts/checks/roadmap/_manifest.py` or
  `scripts/checks/verification/_manifest.py`: `validate_plan_documents` (schema),
  `validate_plan_scope_closure` (registration closure, delegating to
  `scripts/roadmap/plan_obligations.py`), `validate_tier_floor` (deterministic V-tier floor for
  schema_version >= 2 plans, VF-04/T3.17), `validate_fallback_reevaluation` (CD.27 substrate
  re-evaluation carrier), `check_graduation_guard`, `validate_graduation_completeness`
  (graduation-disposition presence on every pre-deploy VP step; its docstring states it performs
  "field presence only, no kernel-expressibility inference (that classification judgement is the
  fresh-context plan-critique gate's job, at plan time)"), and `validate_vp_replay` (independently
  re-executes every `phase == "pre-deploy"` AND `hermetic == True` VP step in the `--pre` tier).
- `docs/contracts/plan-obligations.yaml` is a Class D contract at `status: provisional_v0`
  holding a data-driven `registration_surfaces` map with exactly one rule today
  (`new_check_module`), a `re_ratification_trigger` of
  `first_of: [registration_surfaces_rule_count >= 3, days_since_authored_at >= 90]`, and an
  explicit statement that "rules needing semantic judgement (e.g. the Closure Obligation /
  Related-Work Check) are explicitly out of scope and stay owned by
  `.claude/skills/planning/SKILL.md`."
- `scripts/checks/registry.py`'s module docstring states that registering a new check touches
  SEVEN surfaces, three of them outside `scripts/checks/`.
- No registered check scans VP `command` strings for `gh`, bare `python`/`python3`, or local
  `terraform init/validate/plan`. `scripts/checks/hygiene/validate_cli_tools_in_prompts.py`
  scans only `.github/prompts/scheduled/` and lists `gh` in `_OPTIONAL_CLI_TOOLS` (a skip, not a
  failure). `scripts/checks/hygiene/validate_sys_executable.py` matches
  `subprocess.run(["python"...])` under `scripts/` only.
- Decision 119 states: "Plan authors write local terraform VP steps as grep-only ... never a
  local terraform validate/init/plan for third-party-provider roots."

**The multi-surface lint precedent**
- `scripts/executor/acceptance_lint.py`'s `lint_acceptance_command` is called from four places:
  `scripts/ops_data_portal.py:357` (portal write boundary, `require_discrimination=True`),
  `scripts/checks/ops_governance/validate_acceptance_literals.py:73` (repo-wide static CI check),
  `scripts/execute_recommendation.py:290` (executor runtime), and
  `scripts/cost_reconciliation.py:389`.

**Executor planning path**
- `scripts/executor/plan_generation.py`: `critique_plan()` is a single LLM round-trip parsing
  `VERDICT: APPROVED|NEEDS_REVISION` from free text and collecting following lines as
  `suggestions`. `refine_plan()` carries `critique_history` forward.
  `_detect_critique_cycling()` extracts `(step_n, rule_n)` violation pairs from the last two
  iterations and returns True on any repeat, at which point "the caller should auto-approve the
  plan rather than looping indefinitely"; `scripts/executor/batch_compound.py` is a caller.
- `scripts/executor/plan.py`: `ExecutionPlan` carries `critique_history: list[dict]`; `save_plan`
  appends to a JSONL log and writes through to `ops_execution_plans` via
  `scripts/ops_portal/execution_plans.py`, where `_JSON_BLOB_FIELDS = ("steps",
  "critique_history")`. `config/lambda/ducklake/field_semantics.yaml:469` registers the
  `critique_history` VARCHAR column on `ops_execution_plans`.

**Budgets and direction of travel**
- `config/prose_budgets.yaml` is documented as ratcheting DOWN only, with every entry "seeded at
  the surface's CURRENT byte size (zero-headroom)". Raising one requires an inline
  `# raise-approved: dec-NNN` marker naming a real Decision header, enforced by
  `validate_prose_budget_raises` in `--pre`. Named relief valves are relocation to
  `PROJECT_CONTEXT.md` or a contract, deferral to an uncapped auxiliary file, or the cited raise;
  splitting a surface into fragments is explicitly forbidden. Current entries include
  `.claude/skills/planning/SKILL.md` and `.claude/skills/plan-critique/SKILL.md`, both already
  carrying `raise-approved` markers, plus `.claude/skills/decision-scout/SKILL.md`. Re-derive
  each surface's current bytes and its budget; the headroom figures are small and are the point.
- Roadmap `T2.56` (`in_progress`) c1: "AGENTS.md / CLAUDE.md / the skills layer are measurably
  shrunk to machine-enforced norms plus pointers -- prose rationale and field semantics move to
  contracts." c2 concerns `docs/DECISIONS.md` operating as a retrieved-by-id ADR log.

**Precedents cited by proposals**
- P7 cites `.claude/skills/audit-prompt/SKILL.md`'s zero-context verification gate (three
  parallel fresh-context perspectives; V1 is forbidden repo access because "V1's blindness IS
  the test").
- P13 cites `.claude/skills/overseer/SKILL.md:186` (Fable Advice-Consult Protocol: a fresh-context
  `model: "fable"` subagent separating "settled consensus" from "contested", reconciled via
  adopt/adapt/reject) and its Autonomy-Boundary Policy (four criteria: settled-consensus,
  convention-fit, reversible, no-credible-alternative; plus a proceed-with-notice tier and a hard
  always-ask list). Triggers are in `docs/contracts/overseer-dispatch.yaml#fable_triggers`.
- P11's candidate hooks: `scripts/cost_reconciliation.py` (a monthly monitor evaluating
  `cost_projection.reevaluation_triggers` and filing recs through the portal, alarm-not-gate) and
  the `fallback_reevaluation` block on `PlanDocument` enforced by `validate_fallback_reevaluation`.

**Telemetry substrate**
- `scripts/session/preflight.py:378` sets the report's `"friction_patterns"` key to a literal
  empty list.

**Ownership surfaces for dedup (see DEDUP DISCIPLINE)**
- Prior audit `audits/workflow-review-d107b4a.yaml`, 20 findings WF-01..WF-20 over these same
  files. WF-08 concerned gate verdicts leaving no artifact; WF-17 concerned the Step 9 loop
  having no convergence cap; WF-05 concerned plan-critique's mandatory required-context size;
  WF-06 concerned missed PlanDocument-era failure modes including tier fitness. Determine which
  remedies shipped before treating any related proposal as novel.
- Open roadmap items in proposal territory: `T4.5` (deferred_post_mvp -- "Plan / critique /
  revision warehouse entities -- EXTEND the single plans table ops_execution_plans"), `T4.6`
  (deferred_post_mvp -- "Autonomous plan -> critique -> revision loop"), `T4.16` (not_started --
  "Executor plan data plane -- named read verb, content pin, critique-authorship boundary"),
  `T4.7` (deferred_post_mvp -- plan staleness), `T3.7` (deferred_post_mvp -- validation-suite
  meta-validation), `T1.13` (in_progress -- typed RCA schema enforced at portal write time),
  `T2.56` (in_progress, above).
- Open recs in territory, as starting points not a closed list: rec-228 (add a Rejected
  Alternatives section to a Decision), rec-2672 (plan scope tables and mechanically-required
  side-effect files), rec-2736 (planning skill should flag CI-RCA taxonomy registration),
  rec-2409 (a VP `-k` selector matching zero tests), rec-2631 (hermetic VP commands invoking
  `bin/venv-python` in CI), rec-2650 (comment-only `.tf` plan authoring note).

## EMPIRICAL PASS

The plan corpus is the only sampled artifact class. Bounds, hard:

- Sample **at most 25** plan files from `docs/plans/`. **Do NOT exceed 25.** Choose them to span
  the round-count distribution (include every plan recording 4 or 5 rounds, plus a spread of 1-,
  2- and 3-round plans), not the most recent 25.
- Corpus-wide `rg` counts over all plans are NOT sampling and are unbounded -- use them freely
  for distribution claims.

Per sampled plan, apply the counterfactual test: **would this plan's recorded gate line, scope
table, or VP steps look any different if the gate that is supposed to produce them had been
skipped entirely?** If not, the control is not discriminating on that plan; record it.

Tag every finding with `evidence_kind: static | observed`. `static` = derived from reading a
surface. `observed` = derived from a sampled artifact or an executed command. At equal severity,
an `observed` finding outranks a `static` one in `top_improvements` ordering.

## METHOD

Phases, in order. Synthesis and maturity are computed LAST.

- **P1 Read.** SETUP, then `docs/PROJECT_CONTEXT.md`, then every S1-S6 surface named in SCOPE.
- **P2 Trace.** Re-derive every GROUNDING MAP anchor. Record non-resolvers in
  `meta.stale_anchors`.
- **P3 Diagnose.** Verify D1-D5. Separate each claim's mechanism from its consequence.
- **P4 Deep-dive.** DD-A through DD-D.
- **P5 Empirical.** The bounded corpus pass above.
- **P6 Rate.** Fill `rubric_ratings` for S1-S7 across VD1-VD7.
- **P7 Dedup.** Per DEDUP DISCIPLINE, before any finding or proposal verdict is fixed.
- **P8 Adjudicate.** Assign every proposal verdict, then sequence (Q3), then rank (Q4).
- **P9 Synthesize.** Write both deliverables. Compute maturity last.
- **P10 Self-verify.** Run the SELF-VERIFICATION GATE. Revise and re-run until it passes or the
  round cap binds.
- **P11 Ship.** COMMIT / PR MECHANICS, then end the turn.

## DEDUP DISCIPLINE

Mandatory. Before filing ANY finding and before fixing ANY proposal verdict, search the ownership
surfaces and record the result on the finding.

Ownership surfaces, all four: `docs/ROADMAP-PLATFORM.yaml` (`tier_items[]` and
`candidate_decisions[]`, via a `yaml.safe_load` projection); `docs/DECISIONS.md` (via
`rg "^## Decision"` over headers, then targeted section extraction); `logs/.recommendations-log.jsonl`
(open recs); and `audits/*.yaml` (prior audit findings -- `workflow-review-d107b4a.yaml` above
all, plus `decision-log-premise-integrity-*`, `decisions-authoring-format-*`, `unclosed-loops-*`).

Record on every finding: `dedup_search_terms` (the actual terms used), `dedup_hit_count`, and
`item_ids`. **A hit means sufficiency-assessment or rejection, never a fresh discovery.** A
finding filed without a recorded negative search is `confidence: HYPOTHESIS`, not CONFIRMED.

**Deliberate constraints -- do NOT flag these as defects.** Each is a settled ruling:

- Decision 67 -- executor freeze; STRATEGIC plans suspended; IMPLEMENTATION-only.
- Decision 90 -- the four-tier workflow's existence and shape.
- Decision 86 -- no new standing prose-architecture docs.
- Decision 128 / Decision 165 -- SLOC decompose-by-default; raise markers must be
  Decision-authorized.
- Decision 169 / Decision 170 -- the per-domain manifest dispatch and the check-accounting
  channel, including the resulting registration-surface count.
- Decision 119 -- terraform validate/plan for third-party-provider roots is CI-delegated.
- Decision 73 -- local `validate.py` is advisory outside CI; PR CI is authoritative.
- Decision 87 clause 2 -- git/PR remains the authoritative approval surface for interactive
  plans until the T4.x authority flip.
- Decision 179 -- the stock ceilings are retired; do not propose reinstating them.
- The choice of executor model.

Noting that a settled constraint CONSTRAINS a proposal is not flagging it -- that is required
analysis. Arguing the constraint itself is wrong is out of scope.

## OUTPUT

Two files, both required.

`audits/planning-workflow-scaling-<sha>.yaml`:

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4, S5, S6, S7],
         degraded_dedup: false, contract_notes: "", stale_anchors: [],
         self_verification: {rounds: <int>, degraded: false,
                             final_verdicts: {R1: PROCEED|REVISE, R2: ..., R3: ..., R4: ...},
                             unresolved_findings: []}}
  question_answers:
    - {q: Q1, verdict: all-confirmed|mixed|all-refuted, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: adjudicated|partially-adjudicated|not-adjudicable, basis: [], prose: ""}
    - {q: Q3, verdict: sequenced|partially-sequenced|not-sequenceable, basis: [], prose: ""}
    - {q: Q4, verdict: ranked|partially-ranked|not-rankable, basis: [], prose: ""}
    - {q: Q5, answers: [{question, answer, basis: [<finding ids>]}]}   # different shape
  diagnosis_verdicts:            # Q1's system of record
    - {claim: D1, verdict: CONFIRMED|PARTIAL|REFUTED, mechanism_holds: true|false,
       consequence_holds: true|false|n/a, evidence: "", rederived_values: "",
       confidence: CONFIRMED|HYPOTHESIS}
    # one entry per D1..D5
  proposal_adjudication:         # Q2/Q3/Q4's system of record
    <P1..P14, Alt-1, Alt-2>:
      {verdict: ADOPT-NOW|ADOPT-MODIFIED|ROADMAP|REJECT|DUPLICATE,
       group_placement_rederived: A|B|neither,
       modification: "",          # required iff ADOPT-MODIFIED
       vehicle: implementation_plan|rec|tier_item|candidate_decision|contract_amendment|none,
       sequence_position: <int|null>, depends_on: [<proposal ids>],
       executor_prerequisite: true|false, executor_rank: <int|null>,
       qol_rank: <int|null>, carrying_cost: "", rationale: "",
       owning_items: [], confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: S1..S7, maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1..S7, dimension: VD1..VD7, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: PWS-01, surface: <S1..S7|shared>, question: Q1..Q5, dimension: VD1..VD7,
       title, evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [<finding ids>],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match,
       decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [<finding ids>], highest_leverage_change: <finding id>,
            adopt_now_count, adopt_modified_count, roadmap_count, reject_count,
            duplicate_count, maturity_S1: <value>, maturity_S2: <value>,
            maturity_S3: <value>, maturity_S4: <value>, maturity_S5: <value>,
            maturity_S6: <value>, maturity_S7: <value>}
```

**COUNTING INVARIANT.** `findings[]` is the SOLE enumerated list.
`total_findings == len(findings) == novel_count + planned_insufficient_count +
planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates`, never in
`findings`. `rubric_ratings`, `question_answers`, `diagnosis_verdicts` and
`proposal_adjudication` are systems-of-record referenced FROM findings, never re-counted into
`total_findings`. `top_improvements` and `highest_leverage_change` MUST be finding ids. The five
proposal-verdict counts MUST sum to 16.

`control_property_match` is REQUIRED whenever a compensating control is the reason for
dismissal: name the property the control exercises, cite where it operates (mechanism or
file:line), and state why the control would FAIL if the defect were real.

CONFIRMED requires the behavior traced to a file:line or an observed sampled artifact. Anything
less is HYPOTHESIS.

`audits/planning-workflow-scaling-<sha>.md`: prose companion, **<= 1500 words**, the executive
layer a human reads first. Lead with the adoption sequence and the Q4 ranking, then the
diagnosis verdicts, then the findings that most change the picture. Do not restate the YAML.

## SEVERITY AND MATURITY

Assign severity AFTER judgement, by defect class. Never inherit it from this prompt's framing.

- **critical** -- the planning workflow can produce a wrong-but-trusted verdict (a gate reports
  PROCEED on a plan its own rules should have blocked), or adopting a proposal as stated would
  contradict a ratified Decision.
- **high** -- a weakness that materially reduces the guarantee AND whose compensating controls
  you judged insufficient; or a diagnosis claim wrong in a way that changes an adoption decision;
  or a proposal that duplicates a shipped control while presenting as novel.
- **medium** -- redundancy, ambiguity, or inconsistency with a clear fix.
- **low** -- clarity or wording.

**Property-match rule for compensating controls.** A control lowers severity or justifies
dismissal ONLY if it exercises the same property AND would fail if the defect were real. Apply
the counterfactual to the control itself. A control that cannot catch the break neither lowers
severity nor justifies dismissal -- say so explicitly rather than gesturing at adjacency.

**Maturity**, computed LAST, per surface, top-down, first match wins:

- `frontier` = 0 open critical AND 0 open high findings on that surface
- `strong` = 0 critical AND <= 1 high
- `solid` = <= 1 critical
- `nascent` = otherwise

The top rating stays reachable where you argued a property-matched compensating control. This
framing does not foreclose it.

## SELF-VERIFICATION GATE

**DO NOT COMMIT until this gate passes or its round cap binds.** This audit's conclusions are
consequential and expensive to get wrong; a single reviewer misses orthogonal defects by
definition.

When both deliverables are drafted, dispatch **FOUR** verifier perspectives **in parallel** via
the `Agent` tool, `subagent_type: "general-purpose"`. Each dispatch must: identify both
deliverable files by absolute path; state its perspective and nothing else; forbid all file
edits; require the structured output shape below verbatim including a final `Verdict:` line; and
cap the response at ~900 words.

**Do NOT tell any verifier what you found hard, what you were unsure about, or what a previous
round said.** That biases the read and destroys the gate's value.

- **R1 -- Cold reader (self-containedness and internal consistency).** Reads ONLY the two
  deliverable files. **Forbidden from reading any other file, running any command, or browsing
  the repository** -- its blindness IS the test. Task: "You are a senior engineer handed this
  audit and nothing else. List every place you cannot follow the reasoning, every claim whose
  basis is not stated, every reference to an id that does not appear elsewhere in these files,
  every enum value outside its declared set, every verdict with no supporting rationale, and
  every place the two files disagree. Check the counting invariant arithmetic yourself."
- **R2 -- Fact auditor (grounding).** Full repository read access. Task: "Independently verify
  every factual claim, file:line anchor, quoted identifier (Decision, tier_item, rec, contract
  key, schema field, check name), and re-derived count in this audit against the repository at
  the audited commit. Re-run any counting command the audit reports. A single wrong fact poisons
  the conclusions -- treat every mismatch as a finding." Tag each: `wrong | stale | unverifiable`.
- **R3 -- Adversarial adjudication challenger (anti-deference).** Full repository read access.
  Task: "Contest the VERDICTS, not the facts. For each ADOPT verdict: is the audit agreeing
  because the proposal is right, or because it was stated confidently? For each REJECT: is it
  argued or asserted? For each DUPLICATE: does the named owner actually exercise the same
  property, and would it fail if the gap were real? For each ROADMAP: is the deferral reasoned or
  is it a way to avoid deciding? Then challenge the sequence: does every dependency edge have a
  stated basis, or is the order aesthetic? Name any verdict you would reverse and why."
- **R4 -- Dedup and ownership auditor.** Full repository read access. Task: "For every finding
  and every proposal verdict in this audit, independently search the ownership surfaces
  (`docs/ROADMAP-PLATFORM.yaml` tier_items and candidate_decisions, `docs/DECISIONS.md`,
  `logs/.recommendations-log.jsonl`, `audits/*.yaml`) and judge whether the audit's
  `roadmap_crossref.classification` and `owning_items` are correct. Report every item the audit
  classified `novel` that an existing item already owns, and every item it called DUPLICATE that
  the named owner does not actually cover."

**Output shape, required of all four:**

```
Findings:
1. [blocking|degrading|cosmetic] <one-line title>
   Quote: "<exact text from the deliverable>"
   Problem: <what is wrong>
   Fix: <what would resolve it>
...
Verdict: PROCEED
```

`REVISE` iff any `blocking` finding, or 3 or more `degrading` findings. R2 and R4 return `REVISE`
on ANY finding of their own kind -- a wrong fact and a wrong ownership call both ship a false
conclusion.

**Verdict handling.** The gate passes only when ALL FOUR return `PROCEED` in the SAME round. On
any `REVISE`: synthesize (consensus findings across verifiers first), revise the deliverables,
then **re-dispatch all four fresh** -- a fix for X can introduce Y, and only a fresh cold read
catches it. Reusing a verifier's context across rounds destroys its coldness; always dispatch new
subagents.

**Round-1 quality check.** Before accepting a unanimous round-1 PROCEED, read each verifier's
output. Any verifier that returned zero findings AND fewer than ~10 lines of substantive output
was dispatched too generically -- re-dispatch that one ONCE with a sharpened perspective. One
re-dispatch maximum; its verdict is final.

**Round cap and degraded paths.** You have no human to escalate to; you must terminate.

- Cap at **3 REVISE rounds**. If the gate has not passed after the 3rd revision, STOP revising.
  Record every unresolved finding verbatim in `meta.self_verification.unresolved_findings`,
  downgrade the `confidence` of every finding and proposal verdict those findings touch to
  `HYPOTHESIS`, note the situation in the companion `.md`, and proceed to commit. Shipping with
  a recorded, honest gate failure is correct; looping forever is not.
- IF the `Agent` tool is unavailable in your session: set
  `meta.self_verification.degraded: true`, run the four perspectives yourself as four SEPARATE
  sequential passes, each one re-reading the deliverables from disk under that perspective's
  framing alone, and record `rounds` as normal. Say plainly in the `.md` that the gate ran
  degraded -- a same-context self-review is weaker evidence than four cold reads.
- IF a verifier errors or returns output with no `Verdict:` line: it has NOT completed.
  Re-dispatch that one. Never count an incomplete verifier as PROCEED.

Record the outcome in `meta.self_verification` regardless of how the gate terminated.

## COMMIT / PR MECHANICS

1. Derive the base ONCE: `git fetch origin main`, then `git rev-parse --short origin/main`. That
   sha IS the audited tree. Use it in both filenames, in the branch name, and in
   `meta.audited_commit`.
2. `git switch -c audit/planning-workflow-scaling-<sha> origin/main` so the PR diff is exactly
   your two files. This is a deliberate, documented exception to the repository's `claude/*`
   session-branch rule: this session needs a clean two-file diff off the audited base.
3. Verify both deliverables parse: `bin/venv-python -c "import yaml,sys;
   yaml.safe_load(open(sys.argv[1]))" audits/planning-workflow-scaling-<sha>.yaml`. That clean
   parse is the real pre-push gate. Repo-wide validation is advisory outside CI here; an
   unrelated failure goes in `meta.contract_notes` and is never fixed.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`. Message:
   `audit(planning-workflow-scaling): planning-workflow scaling review`.
5. `git push -u origin HEAD`.
6. Open the PR via `mcp__github__create_pull_request` (base `main`, ready for review, NOT a
   draft). Title: `audit: planning-workflow scaling review (plan pipeline, critique gate,
   executor planning path)`. Body: a 2-3 sentence lede plus the `summary` block in a yaml fence.
7. **END THE TURN.** Do not poll. Do not merge. Do not subscribe to PR activity. Do not
   self-approve. The human disposes of the PR.

## GUARDRAILS

**Write boundary, as a closed list.** The only files you create or modify in the repository tree:

1. `audits/planning-workflow-scaling-<sha>.yaml`
2. `audits/planning-workflow-scaling-<sha>.md`

Regenerating gitignored caches per SETUP is expected and is not a breach; never commit them. You
modify no audited surface, no skill, no check, no contract, no plan, and no roadmap or decision
file. If you believe one of them should change, that belief is a finding with a
`proposed_change`, not an edit.

**No outward research.** Do not use web search or fetch. P10 and P11 are adjudicated on design
merit, on whether the repository has the hooks they would need, and on whether their output would
be actionable -- NOT by you performing an outward scan to see whether such a scan would be
useful. If you judge that the adjudication genuinely requires external information you cannot
obtain, say so in that proposal's `rationale` and set its `confidence: HYPOTHESIS`.

**Honesty clauses.**

- Fewer than ~8 surviving findings is a valid result. State it plainly; do not pad. Precision
  over volume.
- Verdicts are not required to be balanced. All-REJECT is a legitimate outcome, and so is
  all-ADOPT -- but each must be argued item by item. A verdict distribution that looks
  reassuringly mixed is not evidence of a good audit.
- If a diagnosis claim re-derives cleanly, say CONFIRMED without hedging. If it does not, say
  REFUTED without softening.
- `n/a` in a rubric cell and an empty `findings[]` for a surface are both real answers.
- Where you are uncertain, `confidence: HYPOTHESIS` is the honest record. Do not upgrade
  confidence to make a recommendation feel firmer.
