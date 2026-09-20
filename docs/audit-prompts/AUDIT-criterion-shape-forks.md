# AUDIT: unified criterion shape for the Decision 197 clause 3 grain -- design-review brief

You are a staff-level data architect and high-assurance verification engineer. Execute this brief
verbatim in a fresh session. It is self-contained: do not ask clarifying questions, do not wait
for input.

## 1. TASK

Assess a PROPOSED data shape -- the unified acceptance/verification criterion model for the
Decision 197 clause 3 grain, `work_item_criteria` (one row per (work item, criterion)) -- across
six surfaces: two designed-unbuilt (the converged column set in Section 10.2; the candidate
`work_item_criterion_evidence` companion table in Section 10.3) and four built (the roadmap
exit-criteria ledger; the verification graduation registry and its differential admission gate;
the `ops_recommendations` acceptance / verification / verification_tier fields; the red-before
plan gate). Answer the five questions in Section 7, four of which carry a pinned verdict enum
and the fifth a structured answer block; rate seven dimensions per surface
(Section 8); and state, in its own output section, where the converged shape is wrong. Deliver
exactly two files: `audits/criterion-shape-forks-<base-short-sha>.yaml` and
`audits/criterion-shape-forks-<base-short-sha>.md`. The ONLY files you create or modify in the
repository tree are those two; regenerating gitignored local caches per Section 5 is expected and
does not breach that boundary (never commit them).

This audit is INPUT to a data-modeling walk that has not yet run
(`docs/contracts/data-modeling-standard.yaml#design_time_walk`), not its output. Decision 197
clause 3 fixed the grain, three fields and the graduation concept, and DEFERRED merge keys,
identity and join keys to the clause-8 migration. You are being asked to inform those deferred
choices. You draft; the human disposes. Nothing you write is self-executing.

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This brief hands you FACTS and CANDIDATE hypotheses. It hands you no verdicts. Every observation
in Section 10 is stated neutrally on purpose; none is pre-classified as a defect, and no severity
is pre-assigned.

ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT.

A run that merely confirms the candidates below has failed.

Adjudicate each candidate to exactly one of these six destinations:

- CONFIRMED defect, not owned by any existing item -> `findings[]`, `roadmap_crossref.classification: novel`
- Owned by an existing roadmap item / decision / open recommendation whose remedy you judge
  INSUFFICIENT -> `findings[]`, classification `planned-insufficient`
- Owned by an existing item whose remedy is adequate but UNBUILT -> `findings[]`, classification
  `planned-unbuilt`
- Owned and fully covered, or not a defect -> `rejected_candidates[]`, naming the owning id or the
  compensating control and its property match
- A MISSTATEMENT IN THE CONVERGED SHAPE ITSELF (Section 10.2 or 10.3 asserts something the
  repository contradicts) -> `converged_shape_corrections[]`. File a `findings[]` entry as well
  ONLY if the misstatement would change a design decision; a wrong line reference or a wrong
  field-name claim is a correction alone.
- A NEUTRAL CONSTRAINT with no defect reading -- a fact that bounds the design without any surface
  being at fault -> `noted[]`, a bare list of `{candidate, what_it_constrains}`. Do not force such
  an item into `rejected_candidates[]`: it has no compensating control to name, and inventing one
  is noise.

The converged shape in Section 10.2 is a CANDIDATE TO STRESS, not a settled design. It was
produced by two reviewers from the same model family. A foreign model's disagreement with it is
the point of this run. Agreeing with it everywhere is a defensible outcome only if you show the
work that could have disagreed.

## 3. READ FIRST -- DISAMBIGUATION TRAPS

Seven terms in this repository name more than one thing. Misreading any of them will send you to
the wrong surface.

1. **"verification"** names three distinct things: (a) the `verification` FIELD on a
   recommendation -- an advisory prose projection; (b) a plan's `verification_plan[]` VP STEPS;
   (c) repo-wide `scripts/validate.py` VALIDATION. `docs/ROADMAP-PLATFORM.yaml` CD.29 explicitly
   separates (a)/(b) from (c) as "distinct questions ... neither subsumes the other". This audit
   concerns (a) and (b); (c) is context only.
2. **"graduation"** names three things: the per-VP-step DISPOSITION (`graduate | waive |
   not-applicable`); the ADMISSION of a check into the verification registry; and, in tier item
   T1.5 "ops_decisions graduation", a warehouse table MIGRATION PHASE with no relation to either.
   Only the first two are in scope.
3. **"tier"** names two orthogonal axes: verification tier (V1/V2/V3, Decision 48) and roadmap
   tier, whose values are T-1, T0, T1, T2, T3, T4 and T5 -- seven, not four, and this brief cites
   T-1.23, T0.12.5 and T5.5 among them. Q2 concerns only the verification axis.
4. **"status"** is a field name on at least four surfaces with four different enums: the
   criterion ledger (`open | met | rehomed`), a recommendation (`open | closed | in_progress |
   deferred | superseded | declined`), a tier item (`not_started | in_progress | complete |
   reserved | deferred_post_mvp`), and a contract envelope. The converged shape proposes
   `satisfaction` for the criterion axis. That word already appears as PROSE in this repository
   ("satisfaction oracle", "deterministic satisfaction", and a test docstring naming the
   rehomed non-satisfaction case) but
   is not a FIELD NAME on any criterion-bearing surface. Judge the collision on that basis, not
   on novelty.
5. **"criterion" / "acceptance criteria"** names four surfaces Decision 197 clause 3 unifies: a
   recommendation's `acceptance`, a tier item's `exit_criteria[]`, a plan's
   `verification_plan[]` steps, and a plan's own `acceptance_criteria` list (which clause 3 does
   NOT name and which is out of scope).
6. **"severity"** names CD.29 check severity (`required | quarantine`), `telemetry_observations`
   severity, and recommendation `priority`. Only the first is in scope, and it is closed
   (Section 13).
7. **"evidence"** is already taken twice: `docs/contracts/github-actions-evidence.yaml` is a CI
   artifact RETENTION taxonomy, and `docs/contracts/ci-rca-lifecycle.yaml#evidence_scope` is a
   CI-RCA bundle rule. Neither is the proposed `work_item_criterion_evidence` table. If you
   recommend that name, say why the collision is tolerable.

Plausible-but-wrong targets: do not audit the DQ marker vocabulary (CD.12), the plan schema as a
whole, `scripts/validate.py` check accounting, or the executor's Step Functions design. None is
this audit's subject.

## 4. SCOPE

### Surfaces (rate every one; `n/a` is a correct rubric value where a dimension does not apply)

| id | surface | state |
|---|---|---|
| S1 | The converged `work_item_criteria` column set (Section 10.2) | designed-unbuilt |
| S2 | The candidate `work_item_criterion_evidence` table (Section 10.3) | designed-unbuilt |
| S3 | Roadmap exit-criteria ledger: `ExitCriterion` + `docs/contracts/exit-criteria-ledger.yaml` + its validators | built |
| S4 | Verification graduation registry + its differential admission gate (admission-time) | built |
| S5 | `ops_recommendations` `acceptance` / `verification` / `verification_tier` fields | built |
| S6 | The red-before plan gate: `validate_vp_replay` + `docs/contracts/vp-red-before.yaml` (plan-time) | built |

S3-S6 are rated, not merely cited: they are the evidence base from which all four forks are
decided, and a fork answered without reference to what is actually built is an opinion, not an
audit.

### Out of scope

- The `work_items` table, except exactly as far as Q3, Q4 and Q5 require (Q5's `merge_key` leads
  with `parent-plus-criterion-id` and Section 10.2 asserts "SCD2 with parent", neither answerable
  without the parent's identity and versioning scheme). `work_item_edges` is in scope only
  where the criterion-level edges bear on Q4 and Q5 (`criterion_traces_to`, `blocked_by`) -- its own
  vocabulary, cardinality and write path are not yours to design.
- Decision 196 and the three-tier decision model. Adjacent, not this audit.
- Any hosted-product or infrastructure surface.

### Trust nothing

Obtain every file path, line number, count and identifier by reading the repository yourself.
Every number quoted in this brief was measured at `04a402a4` and is stated so you know what to
compare against, never so you can inherit it. Re-derive each one on YOUR audited commit. Record
every anchor that does not resolve in `meta.stale_anchors[]` with what you found instead. An
anchor that has moved is expected -- this repository is under active development, and the roadmap
gained five structured criteria and 24 lines in the 24 hours before this brief was written.

## 5. SETUP

You are not a Claude Code session and this repository's tooling assumes one in places. Where an
instruction presupposes a capability you lack, record it (Section 5.3) and proceed; never stop.

### 5.1 Environment

```bash
git fetch origin main
git rev-parse --short origin/main          # THIS is your base sha; use it everywhere
git switch -c audit/criterion-shape-forks-$(git rev-parse --short origin/main) origin/main
bin/venv-python -c "import yaml, pydantic; print('ok')"
```

Create the branch NOW, before any measurement. Every count you re-derive must come from the tree
you name in `meta.audited_commit`; measuring on some other checkout and labelling it with this sha
would be an honest measurement of the wrong tree. Section 16 then only commits and pushes this
same branch -- it does not create it again.

Always invoke `bin/venv-python`, never bare `python` or `python3`. Each shell invocation is
independent; do not rely on `source .venv/bin/activate` persisting.

IF `bin/venv-python` fails: set `meta.contract_notes` to say so, fall back to any Python 3.12+
with PyYAML for the measurement commands, and downgrade to HYPOTHESIS any finding whose evidence
depended on a model-loading command you could not run. A dead interpreter also makes Section 5.2
unrunnable: in that case set BOTH `meta.contract_notes` and `meta.degraded_dedup: true`, and take
Section 5.2's degraded path. `degraded_dedup` means "I could not search the recommendation cache",
whatever the cause; `contract_notes` records what the cause was.

### 5.2 Dedup cache (MANDATORY -- Section 13 depends on it)

```bash
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`. Both are
gitignored; they are read caches, never write sources, and you never commit them.

IF cache-gen fails (credentials or egress down): do NOT abort. Set `meta.degraded_dedup: true`,
mark every `roadmap_crossref` entry `confidence: HYPOTHESIS` with `dedup_hit_count: null`,
proceed using the recommendation-side dedup pointers in Section 10.6 as your only recs signal,
and still perform your own greps over the two git-tracked surfaces (`docs/DECISIONS.md`,
`docs/ROADMAP-PLATFORM.yaml`), which need no credentials.

### 5.3 Capability deviations register

You will meet obligations this repository's own agents satisfy with tooling you may not have.
Record every one in `meta.capability_deviations[]`, each tagged with its class:

- `capability` -- you structurally could not (no MCP server, no slash-command harness, a tool
  absent from your container). Expected; not a mark against you.
- `judgment` -- you could have and chose not to, with your reasoning.

A recorded deviation is an acceptable outcome. A silent one is a failed run.

Known in advance:

- **No MCP servers.** `AGENTS.md` routes all GitHub access through an MCP server and states the
  `gh` CLI is deliberately absent. **That rule is WAIVED for you**: use `gh` freely for the PR in
  Section 16. Do not introduce `gh` into any file you author -- you author only two YAML/Markdown
  deliverables, so this cannot arise.
- **No slash commands.** `/plan`, `/implement`, `/audit` name methodologies in
  `.claude/skills/*/SKILL.md` and `.claude/commands/*.md`, which are ordinary files you may read.
  A slash command is a prompt, not a capability.
- **Subagents and AWS credentials ARE available to you.** Use subagents to widen the Section 11
  sweep and to cold-check a finding you suspect you are too attached to. Every anchor a subagent
  returns is a LEAD, not evidence: re-verify it yourself before it enters a finding.
- **The operational-data portal is reachable but OFF LIMITS for writes.** Do not call `file_rec`
  or `update_rec`, and do not file a recommendation for anything you discover. This audit is
  read-only; findings live in your two deliverables and nowhere else. Portal READS (the
  Section 5.2 cache-gen) are expected and correct.

## 6. NORTH STAR

Seven principles. Each is a bar you JUDGE each surface against, not a rule to pattern-match.
Argue with any of them where the repository's own evidence warrants it -- a reasoned disagreement
recorded as a finding is worth more than compliance.

- **NS1 -- Grain first, never CRUD.** State "one row per ___" before choosing a write mode. SCD2
  for mutable entities, append-only for events, and no "one row per entity, mutate in place"
  default. (`docs/contracts/data-modeling-standard.yaml#rules`, `#design_time_walk`.)
- **NS2 -- Status is trusted, never inferred.** A status value is an AUTHORED claim with a named
  resolver, never something derived from prose, file existence or commit activity. The corollary
  the ledger already enforces: when reality satisfied an intent differently from how the
  criterion text describes it, the TEXT is rewritten in the same edit as the status flip -- a
  status that no longer re-adjudicates true against the repo is an audit finding, not a
  convenience.
- **NS3 -- A check that cannot fail guards nothing.** The differential admission property (a
  candidate must demonstrably FAIL on revert of the change it guards) and the four-class
  red-before outcome vocabulary exist because green-by-construction assertions are the dominant
  failure mode of a machine-curated suite.
- **NS4 -- Semantic intent is not provable by execution.** No command, no exit code and no status
  value demonstrates that a criterion meant what its author intended, or that the implementation
  satisfies that intent rather than the literal text that survived review. The platform's only
  mechanisms against that gap are independent pre-implementation review, lowest-level
  traceability from a shipped behaviour back to the clause that demanded it, and escaped-defect
  feedback that re-opens a criterion the world proved wrong. The schema's job is to record those
  three mechanisms -- who reviewed, before what, against which clause, and what later
  contradicted it -- rather than to pretend a status value can stand in for them.
- **NS5 -- The mechanism ships; the operator's data does not.** Decision 197 clause 1 and clause
  4: tier membership, verification tiers and `source: ci_rca` are grouping items, edges or
  extension values, never columns, so a downstream user's work items carry none of this
  operator's vocabulary.
- **NS6 -- Every stored field has a reader; derived state is derived.** A field nothing reads is
  drift with a schema. A value recomputable from its inputs is stored only with a stated reason.
- **NS7 -- A declared residual with a named owner beats a silent gap.** Where a rule cannot be
  mechanically enforced, the platform's norm is to declare the unenforced arm and name who owns
  closing it, rather than assert the rule unqualified.

## 7. THE QUESTIONS

Answer all five. Q1-Q4 each get a `question_answers[]` entry carrying that question's pinned
verdict enum. Q5 uses a different shape -- an `answers[]` list plus the `deferred_walk_inputs`
block defined under Q5 -- and carries no top-level verdict. A verdict with no `basis` finding ids
is an opinion; ground it. The one exception: a verdict that endorses the status quo may carry an
empty `basis` IF you also filed no correction bearing on it -- say so in `prose`. Never
manufacture a finding to satisfy this rule.

### Q1 -- Standing versus admitted

Should a graduated registry check ever mean "standing" -- that is, a live, continuously re-proven
guarantee -- or does it mean only "admitted once", a claim proven at one commit and never
re-tested?

Today's answer is "admitted once": `docs/contracts/verification-registry.yaml` governance_notes
records a row that had gone "permanently FAIL, unnoticed because graduated records are never
re-executed as a standing suite", and a sibling found "permanently TRUE" by the same migration.
Neither the contract nor Decision 176 states how long either row had been broken. Measured from
git at compose time: `plan-obligations-enumeration-homed` entered the registry 2026-08-11 and was
retired in the 2026-08-25 sharding migration (14 days); `no-retired-ci-role-in-live-surfaces`
entered 2026-07-24 and was retired in the same migration (about 32 days). Re-derive both
intervals yourself -- DD-A asks you to establish how long a break survives, and an inherited
figure would prejudge it. Note what surfaced them: an unrelated migration that touched the rows,
not any standing mechanism. The differential gate re-runs a row only when that row is ADDED or
MODIFIED in the diff.

Options, stated so they are mutually exclusive -- pick by MECHANISM, not by sentiment:
(a) PERIODIC re-execution: a `standing_run` leg that re-runs graduated checks on a schedule
independent of what any diff touches (with or without a guard_target trigger as well), so
graduated becomes a live guarantee;
(b) NO new re-execution: CD.29's mutation testing (T3.7) plus mark-then-drop retirement remains
the whole answer and graduated stays "admitted once";
(c) TRIGGERED re-execution ONLY: re-differential when `guard_target` appears in the diff, and no
scheduled or periodic run. If you would add both a schedule and a trigger, that is (a).

Constraint you must weigh, not ignore: CD.29 is `state: pending`, so answering (a) or (c) is a
CD.29 amendment, and T3.7 is `deferred_post_mvp`. Decision 176 clause 4 is the standing argument
against a warehouse home for admission: "the differential gate reads its baseline at a GIT REF
(`git show origin/main:...`), which DuckLake cannot serve; admission is a property of a commit,
runs pre-merge and hermetically, and must revert atomically with the code it verifies."

**Verdict enum:** `a-periodic-standing-runs | b-admitted-once | c-guard-target-triggered-only |
d-other-argued`

### Q2 -- Who owns `verification_tier` derivation

A deterministic tier floor ALREADY EXISTS at PLAN grain.
`scripts/checks/roadmap/validate_tier_floor.py:49` (`_compute_floor`, documented "Highest-tier-wins
floor over a plan's scope files (Decision 48 semantics)") returns V3 for an active-manifest Lambda
code file or a `.tf` path, V2 for a `.py` path, and V1 otherwise; `:62` registers a CI check that
fails a `schema_version: 2` plan whose declared `verification_tier` is below its computed floor,
unless `tier_waiver` is set. Its owning tier item T3.17 is `complete`.

Decision 48's own Limitation clause at `docs/DECISIONS.md:7819` still reads "documentation-enforced
only. No automated detection currently exists." Establish for yourself which of those two is
current before you answer -- one of them is out of date, and which one is a finding in its own
right.

What does NOT exist, as far as this brief could establish: any tier derivation at CRITERION grain,
and any writer that populates the recommendation `verification_tier` field from scope. Verify both.

Options:
(a) derive the tier from `phase` x `primitive_slot`;
(b) extend the existing plan-grain `_compute_floor` to criterion grain;
(c) keep the field stored until a derivation exists;
(d) drop the field from the criterion row.

Weigh the recommendation-side semantics (`docs/contracts/ops_recommendations.yaml`
`verification_tier`: V3 = build + deploy + smoke, Decision 79 / CD.16) against the measured
population in Section 10.6. A stored tier on a criterion row, a floor over a plan's scope, and a
routing signal on a work item are three different things; say which you mean.

Reconcile your answer with Decision 197 clause 4, which NS5 carries: verification tiers "are
grouping items, edges or extension values, never columns". Option (c) keeps a stored column and
Section 10.2 already lists verification tier under "Derived, never stored", so (c) is in apparent
tension with a ratified clause. Say whether you read (c) as foreclosed by clause 4, or as
admissible because clause 4 governs the work-item row rather than the criterion row -- do not
answer (c) without addressing it.

**Verdict enum:** `derive-from-phase-x-slot | extend-plan-grain-floor |
keep-stored-until-derivation-exists | drop-the-field | other-argued`

### Q3 -- Identity for the bare-string exit criteria

Measured at `04a402a4`: 801 roadmap criteria = 407 bare strings + 394 structured dicts; 259 of
the 407 sit on `status: complete` items. Read the touched-item rule at
`scripts/checks/roadmap/validate_platform_roadmap.py:111`-`:132` and establish for yourself what
population it fires on and what that implies for those 259 -- whether they are beyond the gate's
reach by construction, or merely seldom in its path. The options below turn on exactly that
distinction, so form it from the code rather than from any characterisation. Bare-string ids are auto-assigned positionally at model-load time. In-YAML
conversion costs roughly three lines each against a roadmap at 9,925 of a 10,000-line ceiling,
and a per-tier split is forbidden (Decisions 110/114/147). rec-3660 is the named owner. Decision
197 clause 8 forbids lift-and-shift before the clause-8 migration.

Options:
(a) pin ids in-YAML now under a Decision 147 sanctioned valve;
(b) pin at migration time and accept positional ids until then;
(c) declare complete-item bare strings terminal (text + met, no method,
`text_origin: migrated_bare`) and never convert them.

Both prior reviewers rejected a deadline, on the grounds that a bulk LLM backfill of verification
methods would manufacture tautologies at scale. You may re-examine that reasoning; you may not
re-propose a deadline as the answer (Section 13).

**Verdict enum:** `pin-ids-in-yaml-now | pin-at-migration-time | terminal-migrated-bare |
other-argued`

### Q4 -- One table or two (the industry-rating question)

Should the clause-8 walk model criteria as (i) ONE SCD2 table carrying a mutate-in-place proof
struct, or (ii) the criteria table PLUS the append-only evidence table in Section 10.3?

The prior reviewers converged on (ii) from first principles -- append-only events per the
data-modeling standard; the decay Decision 176 documents needs history; the four-class outcome
vocabulary collapses to a bit in a binary struct -- but neither found repository PRECEDENT for a
per-criterion evidence journal. Find or rule out that precedent (Section 11 seeds it) and answer.

Answer for BOTH adapters. Decision 197 clause 2 (quoted in Section 10.1) puts the same mechanism
behind a storage port with a file-catalog LOCAL adapter and a DuckLake-on-Neon CLOUD adapter,
user-selected by configuration. A second append-only table per criterion version, leg and run is
a different proposition under a local file catalog than under a lakehouse -- join cost, write
amplification, and whether an evidence row can even be written without a warehouse round-trip all
change. If your verdict holds under one adapter but not the other, say so explicitly rather than
answering for the lakehouse alone; that split is itself a finding.

This question additionally requires an `external_checklist` block. Assess THE DESIGN YOU ENDORSE
in your own verdict -- if you answer (i), rate the one-table proposal; if (ii), rate the two-table
proposal; if `other-argued`, rate what you propose -- property-by-property against these named
external practices, each rated `met | partial | missed` with evidence, or `n/a`. `partial` requires an
argued, property-matched compensating control. This field feeds the maturity top tier under the
CHECKLIST CONDITION in Section 15, which is the sole statement of its scope -- do not infer the
scope from here.

P1. Event-sourced journal plus current-state projection, rather than state mutation in place.
P2. Type-2 slowly-changing dimension paired with a separate fact table, rather than a widened
   dimension.
P3. Test/build result history as a first-class fact table keyed on (test, run) -- the standard
   shape behind flake detection and suite-health analytics.
P4. Provenance modelling in the W3C PROV sense: entity / activity / agent separated, so "what was
   claimed", "what was run" and "who ran it" are distinguishable.
P5. Assurance-case separation (Goal Structuring Notation): CLAIM, ARGUMENT and EVIDENCE are
   distinct node types, and evidence is never merged into the claim it supports.
P6. Quarantine registry keyed on (test, run) with a bounded, expiring lifetime rather than a
   permanent advisory state.
P7. Mutation score, or an equivalent adequacy metric, treated as a decay signal on an existing
   suite rather than a one-time admission test.
P8. Transactional read consistency: a criterion's current proof state is readable in a single row
   read, with no join and no window in which a reader sees claim and evidence from different
   points in time.
P9. Single-writer atomicity: a criterion's claim and its proof advance in one write, so the row
   never asserts a state its own evidence does not yet support.

Properties P1-P7 favour separation; P8-P9 favour consolidation. The 7-2 split is not a verdict --
it reflects how much of the published literature addresses separation, not how much weight it
deserves here. Three rating rules keep the count from becoming a thumb on the scale:
`n/a` for a property structurally inapplicable to the design you endorse; `partial` for a
property your design DELIBERATELY TRADES AWAY, naming the countervailing property it buys as the
compensating control (a one-table design trading P1 for P8 and P9 is the obvious case, and it is
a trade, not a failure); and `missed` reserved for a property the design neither meets nor
deliberately trades. Neither `n/a` nor `partial` gates maturity.

**Verdict enum:** `one-table-proof-struct | two-tables-evidence-journal | other-argued`
**Additionally required on this entry:** `precedent: [<table or artifact names>]` -- a LIST, empty
when you find none (never the string `none`) -- and
`external_checklist: [{property, rating, evidence}]` covering ALL NINE properties above,
each identified by its `P1`..`P9` id -- rating seven of nine would silently drop exactly the two
that argue for consolidation.

### Q5 -- Questions the requester did not think to ask

Answer AND extend: add at least two and at most six questions of your own beyond the seeds.
Seeds, each of which you must answer or explicitly dismiss:

- What happens to a criterion whose text is rewritten under the realized-differently rule -- is
  that a new criterion, a new version of the same criterion, or an amendment, and what does the
  answer imply for a merge key?
- If a criterion row can be `rehomed` to another work item, is `rehomed` a status, an edge, or
  both -- and which one does a downstream consumer join on?
- What identifies a criterion whose parent work item is a recommendation, given that recommendation
  ids are writer-allocated in-transaction while criterion ids are authored?
- The converged shape stores `text` as the requirement. What bounds it? One criterion text in the
  roadmap today is 6,581 characters.
- Where does an ESCAPED DEFECT re-enter this model? Neither the converged shape nor the evidence
  table has a leg for it (NS4 names it as one of the platform's three real mechanisms).

**Additionally required on Q5 -- the `reversal_trigger_assessment` block.** Decision 197 clause
3 carries its own reversal condition, `two-shapes-after-all`, verbatim: "Epic-shaped and
task-shaped items need required fields the criteria child table cannot absorb: reopen clause 3
before adding nullable columns." The converged shape in Section 10.2 proposes roughly seventeen
columns, of which a substantial group (`evaluator_kind`, `primitive_slot`, `check_spec`,
`guard_target`, `guard_symbol`, `hermetic`, `phase`, `severity`, `disposition`,
`graduated_check_id`, `plan_slug`, `authored_at_sha`) is populated only when a criterion
originates from a plan VP step or a registry row -- count them yourself against what a tier-item
exit criterion carries today, and against what a recommendation `acceptance` carries. Then answer
whether the converged shape ALREADY TRIPS that trigger. This is not a rhetorical question: if it
does, clause 3 must be reopened before the clause-8 walk proceeds, which changes what every other
answer in this audit is for.

```
reversal_trigger_assessment:
  verdict: not-tripped | tripped-reopen-clause-3 | tripped-but-absorbable | other-argued
  nullable_column_count: <int, by your own count>
  which_columns: [<the columns structurally null for one of the two WORK-ITEM KINDS>]
  rationale: ""
  basis: [<finding ids, or empty>]
```

Answer on the TRIGGER'S OWN AXIS: epic-shaped versus task-shaped work items (`kind`, per clause
3), not plan-origin versus ledger-origin criteria. The origin framing above is how you FIND the
candidate columns -- a criterion on an epic-shaped item does not come from a plan VP step today --
but the question the reversal condition asks is whether the two KINDS need required fields the
child table cannot absorb. If you conclude the two axes are not equivalent, that is itself worth
saying.

`tripped-but-absorbable` means the nulls exist but a named mechanism (a kind discriminator, a
sub-table, an extension map) absorbs them without required fields the child table cannot carry --
name the mechanism, do not gesture at one.

**Also required on Q5 -- the `deferred_walk_inputs` block.** Decision 197 clause 3
deferred THREE things to the clause-8 migration: merge keys, identity and join keys. Only identity
carries a fork of its own (Q3). Answer the other two here, plus the partition column that
`docs/contracts/data-modeling-standard.yaml#design_time_walk` step 6 requires any new table to
name, each with a pinned verdict:

```
deferred_walk_inputs:
  merge_key:
    verdict: parent-plus-criterion-id | surrogate-ulid-only | content-hash-composite | other-argued
    value: "<the key you propose, as a column list>"
    rationale: ""
    basis: [<finding ids, or empty>]
  join_keys:
    verdict: registry-fk-only | registry-fk-plus-plan-slug | evidence-table-fk | other-argued
    targets: [<the tables or surfaces this criterion row joins to>]
    rationale: ""
    basis: []
  partition_column:
    verdict: "<column name>" | none-argued
    applies_to: [<only the tables your Q4 verdict endorses>]
    rationale: ""
    basis: []
  current_projection:
    verdict: scd2-history-plus-type1-current | history-only | other-argued
    rationale: ""
    basis: []
```

Every `deferred_walk_inputs` verdict answers a question Decision 197 clause 3 explicitly DEFERRED,
so there is no status quo to endorse and often no defect to cite: an empty `basis` is EXPECTED
here, and `rationale` carries the argument. The grounding rule in the Section 7 preamble does not
bind these four blocks.

One walk step is explicitly NOT yours: step 8's advice-consult escalation for a new table, a new
identity scheme or a merge-key change is a Claude-side protocol this run does not discharge. State
in your report that it remains open, so the requester can see how much of the walk your deliverable
actually closes.

`current_projection` answers `design_time_walk` step 2's second half -- whether
`work_item_criteria` needs a Type-1 current table alongside its SCD2 history, as
`ops_priority_queue` and `ops_execution_plans` have, or is history-only. It is adjacent to Q4 but
not the same question: Q4 asks whether evidence is a separate table, this asks whether the
criteria table itself is served by a current projection.

Consult `docs/contracts/_joins.yaml` -- this repository's cross-table join/correlation-key
registry, which `design_time_walk` step 4 makes mandatory reading -- before answering `join_keys`.
Do not re-derive its content from first principles.

## 8. RUBRIC

Rate every dimension on every surface. Pinned enum: `strong | adequate | weak | absent | n/a`.
`n/a` is correct and costless where a dimension does not structurally apply -- never manufacture
a rating or a finding to fill a cell.

| id | dimension | serves |
|---|---|---|
| VD1 | Grain discipline -- one row per ___ stated and honoured; no CRUD default | Q4 |
| VD2 | Identity and business-key stability -- never renumbered, minted at a named boundary, merge key distinguishable from row id | Q3, Q4 |
| VD3 | Evidence integrity / anti-vacuity -- is a tautological or decayed proof DETECTABLE from what the shape stores | Q1, Q4 |
| VD4 | Status honesty -- NS2 and NS4; does a status value carry weight it cannot bear | Q1, Q5 |
| VD5 | Migration feasibility under declared constraints -- roadmap ceiling, no lift-and-shift, no per-tier split, no deadline | Q3 |
| VD6 | Derivation discipline -- stored vs derived; every field has a reader; no write-only signal | Q2, Q4 |
| VD7 | Shipped-mechanism portability -- Decision 197 clauses 1, 2 and 4: no operator taxonomy in columns, and the shape must run on BOTH the file-catalog local adapter and the DuckLake cloud adapter | Q2, Q4, Q5 |

## 9. DEEP-DIVES

### DD-A -- The decay trace (feeds Q1, Q4, VD3)

Trace end to end what happened to the two registry rows Decision 176 found broken. Read
`docs/contracts/verification-registry.yaml` governance_notes for the narrative; then establish
mechanically: what re-ran them, why nothing had re-run them before, and what in the current
mechanism would or would not catch the same shape tomorrow. Read
`scripts/checks/verification/validate_verification_registry.py` (`_added_entries`,
`_modified_entries`, and how `candidates` is assembled) and
`scripts/verification_graduation.py::run_differential`. Then answer: under each of Q1's options,
which of the two rows is caught, and how long after it breaks.

### DD-B -- The four ways this repository records "done" (feeds Q4, Q5, VD1, VD4)

Decision 197 clause 3 subsumes three shapes into criterion rows. Enumerate what each actually
stores today and what is LOST if it becomes a criterion row:
(a) a recommendation's `acceptance` plus `execution_result`;
(b) a tier item's `ExitCriterion` (`status`, `met_by`, `blocked_by`);
(c) a plan's `verification_plan[]` step (`graduation`, `hermetic`, `phase`, `expected_literals`);
(d) the PR-body VP compliance table that T3.15 c1 makes mandatory on every merged `feat(...)` PR.
(d) is not named by clause 3 and is not a table. Decide whether it is the existing evidence
journal in prose form, and what that implies for Q4.

### DD-C -- Identity under the two live id schemes (feeds Q3, Q4, VD2)

Establish how a criterion is identified today on each parent type, and where the two schemes
collide. Read `scripts/platform_roadmap_models.py` (`ExitCriterion`, the
`_normalize_exit_criteria` validator), `docs/contracts/exit-criteria-ledger.yaml#fields.id`, the
`closes_criteria` referential rule, and `docs/contracts/ops_recommendations.yaml` on
writer-allocated ids versus `docs/contracts/ops_decisions.yaml` on the caller-supplied id
exception. Then test the converged shape's claim that `cN` is positional against the actual data.

## 10. GROUNDING MAP

This map exists to spend your cognition on JUDGMENT, not on grep. Every entry was read from disk
at `04a402a4`. Verify each anchor before you rely on it; record non-resolving anchors in
`meta.stale_anchors[]` and continue.

### 10.1 Governing decisions and contracts

| anchor | what is there |
|---|---|
| `docs/DECISIONS.md:5` | Decision 197. Clause 3 (the audited grain) at `docs/DECISIONS.md:32`. |
| `docs/DECISIONS.md:44`-`:46` | Decision 197's `two-shapes-after-all` reversal condition (`- id:` at `:44`, its `description:` at `:46`), verbatim: "Epic-shaped and task-shaped items need required fields the criteria child table cannot absorb: reopen clause 3 before adding nullable columns." Q5's `reversal_trigger_assessment` turns on it. |
| `docs/DECISIONS.md:31` | Decision 197 CLAUSE 2, the storage port -- load-bearing for Q4, Q5 and VD7 and quoted here because the whole design must run on both adapters: "Work items are reached through a named port (Decision 184 clause 2); the local adapter is a file catalog, the cloud adapter is DuckLake-on-Neon; the user selects by configuration. T4.23 is that port's tracked local-adapter item. Tenancy (`project_id`) is a cloud-adapter property, not a mechanism requirement; the local adapter is single-tenant by construction." T4.23 (`deferred_post_mvp`) carries SIX exit criteria: c1-c4 are the local adapter proper (in-process reachability of every named verb; a local DuckDB-or-SQLite catalog selected by configuration; no caller SQL and writer-allocated rec ids; contract parity across the in-process and Function URL adapters), and c5-c6 are Decision 197 forward-work carriers naming clause 2's storage port and clause 3's `work_items` / `work_item_criteria` / `work_item_edges` target model respectively. Read c5 and c6 -- they are this audit's own subject written as roadmap criteria. |
| `docs/DECISIONS.md:59` | Decision 196 (context only; out of scope). |
| `docs/DECISIONS.md:7778`, `:7819` | Decision 48 tier definitions; its Limitation clause ("documentation-enforced only. No automated detection currently exists"). |
| `docs/DECISIONS.md:4126`, `:4174` | Decision 132 (graduation as an enforced obligation); residual limitation A, the classification seam. |
| `docs/DECISIONS.md:1695`, `:1749` | Decision 176 (registry re-grain); clause 4, why not the warehouse. |
| `docs/DECISIONS.md:581` | Decision 189 (red-before polarity for added, undeclared plans). |
| `docs/DECISIONS.md:5329`, `:3352`, `:5442` | Decisions 114 (10,000-line ceiling), 147 (compaction response and the named valves), 110 (single-file roadmap). |
| `docs/DECISIONS.md:6662`, `:6775`, `:3893` | Decisions 87 (plans as entities; clause 6 rec-vs-plan grain), 84 (portal invariants, I-2 id allocation, I-3 named verbs), 137 (partition every table). |
| `docs/DECISIONS.md:1236` | Decision 181 (declare-your-coverage: an unenforced arm is declared with a named owner). |
| `docs/contracts/exit-criteria-ledger.yaml` | Ledger field semantics. `fields.status` spans `:49`-`:92` and carries the realized-differently rule (`:57`) and Status-Trusted-Never-Inferred (`:71`). `fields.met_by` begins at `:93` and carries the `closes_criteria` flip procedure and its own Status-Trusted-Never-Inferred restatement (`:108`). `fields.blocked_by` begins at `:120`. `fields.blocked_by` carries the edge semantics and the foreign-ratification anti-pattern. |
| `docs/contracts/verification-registry.yaml` | Registry schema. `check_id` immutability and the (plan_slug, check_id) T3.21 join; `guard_target`/`guard_symbol` as the orphan-detection keys; `check_spec` as the materialization key. Lines `:244`-`:245` carry "permanently FAIL, unnoticed because graduated records are never re-executed as a standing suite" -- YAML folding splits it across the two. Several quotes in this map fold the same way. A quoted string that fails to match on its cited line ALONE is not a stale anchor; resolve the fold or grep the file before recording one. Lines `:222`-`:225`: filename-equals-check_id; `entries/deprecated/` is loader-excluded. |
| `docs/contracts/vp-red-before.yaml` | `outcome_classes` (`:97`), `unmeasurable_arms` (`:105`), `eligibility_predicate` (`:126`), `graduation_disposition_authoring` (`:216`), `self_satisfying_lint` (`:257`). |
| `docs/contracts/tier-item-lifecycle.yaml:131` | The bookkeeping walk EXECUTES executable-looking criterion text via subprocess, passing on exit 0; prose criteria fall through to agent judgement with a conservative bias. The only existing execution hook on the exit-criteria surface. |
| `docs/contracts/data-modeling-standard.yaml` | `rules`, `write_modes` (scd2 / append_only / control), and `design_time_walk` -- the walk this audit feeds. Its `identity-ulid-at-boundary` rule (`:68`-`:72`) is already pinned and binds Q3 and Q5's `merge_key`: "Identity is a ULID (Crockford base32), minted once at the write boundary ..., never client-side and never a natural-key primary key. Propagated to child rows as foreign keys, never re-derived downstream." `design_time_walk` step 3 restates it. Argue with this pin if you must, but do not answer as though it did not exist. |
| `docs/contracts/storage-substrate.yaml:126` | `ops_smoke_events`: `write_mode: append_only`, grain "one row per event_id". |
| `docs/contracts/ops_recommendations.yaml:416` | `execution_result`: "Executor-internal write-only signal. Not read by the planning or triage paths. DQ-EXCLUDED (Decision 63)." |
| `docs/contracts/_joins.yaml` | The cross-table join / correlation-key registry. `design_time_walk` step 4 makes consulting it mandatory when a new table's join keys are chosen. Required reading for Q5's `join_keys`. |
| `scripts/checks/roadmap/validate_tier_floor.py:49`, `:62` | `_compute_floor` (Decision 48 semantics over a plan's scope paths) and the registered CI check that enforces it on `schema_version: 2` plans, with a `tier_waiver` escape. Owning item T3.17 is `complete`. |
| `docs/ROADMAP-PLATFORM.yaml` CD.29 | The six-slot closed kernel; the admission gate; severity `required` with a transient `quarantine`, "never a permanent `advisory`"; the consolidation clause absorbing the rec `verification` projection "as additional typed checks on the same field". `state: pending`. |

### 10.2 The converged shape (verbatim -- this is the artifact under audit)

Reproduced unedited, including any anchor or claim that does not hold. It is a PROPOSAL: where it
names an enum value or a field that no current surface carries (for example `waived` on the
satisfaction axis, whose ledger enum today is `open | met | rehomed`), that is the proposal
extending the existing shape, not a description of what exists. Treat every line as a claim to
test.

> `work_item_criteria` -- one row per (work item, criterion) version; SCD2 with parent.
> `ulid` + business key: writer-minted row envelope plus `:cN` / `rec-NNNN` / `check_id`, never
> renumbered (data-modeling standard; D197 c3). `cN` is POSITIONAL today
> (`scripts/platform_roadmap_models.py` ~L95-101).
> `text`: the requirement, preferably a concrete example; mandatory for NEW rows only; judged,
> never executed (ledger text, `docs/contracts/exit-criteria-ledger.yaml`).
> `text_origin`: `authored | migrated_bare | migrated_from_oracle`.
> `evaluator_kind`: `check | agent_surface` (`scripts/contracts_schema.py` `EvaluatorSpec`) --
> replaces both manual and an LLM judgement slot.
> `primitive_slot`: one of the six CD.29 slots; meaningful only under `check`
> (`scripts/verification_checks.py` `CANONICAL_SLOTS`, `SLOT_COUNT == 6` hard invariant).
> `check_spec`: slot-keyed, validated per slot at write; null iff `agent_surface`
> (`docs/contracts/verification-registry.yaml`).
> `guard_target` / `guard_symbol`: what the check is coupled to; enables a narrow-revert leg
> (registry orphan-detection keys).
> `hermetic`, `phase` (`pre_deploy | post_deploy`): from `VerificationStep`
> (`scripts/roadmap/plan_document.py`).
> `severity`: `required | quarantine`; quarantine carries a rec id (CD.29,
> `docs/ROADMAP-PLATFORM.yaml` ~L1103-1129: a permanent advisory is forbidden).
> `authored_at_sha`: tree the criterion was written against; red-before proof is only meaningful
> when this predates the implementing change (Decision 189's eligibility predicate).
> `satisfaction`: `open | met | rehomed | waived(reason >= 20 chars)` -- the work axis only
> (ledger status; Status-Trusted-Never-Inferred).
> `disposition`: `graduate | waive | not-applicable` with iff companions (`plan_document.py`;
> Decision 132 cl.1).
>
> [Reader's note, not part of the converged shape: "iff companions" means the co-required field
> each disposition value carries -- `graduate` requires a non-empty `graduation_check_id`, `waive`
> requires a non-empty `graduation_waiver_reason`, `not-applicable` requires neither. Enforced by
> `_validate_graduation_disposition` at `scripts/roadmap/plan_document.py:91`-`:114` (graduate arm
> `:95`-`:101`, which also rejects a `graduation_waiver_reason` on a graduate step; waive
> `:102`-`:108`; not-applicable `:109`-`:113`).]
> `graduated_check_id` + `plan_slug`: registry FK, the existing T3.21 join; LINK never merge;
> means ADMITTED, not STANDING (`verification-registry.yaml` governance_notes: graduated records
> are never re-executed as a standing suite; Decision 176 cl.4: admission is a commit property
> at a git ref DuckLake cannot serve).
> Edges, not columns (D197 c3/c5, closed vocabulary, authored at merge): `criterion_traces_to`
> (target restricted to a decision CLAUSE or the parent item; NS.n forbidden from task-shaped
> items) and `blocked_by` (live consumer: `validate_roadmap_liveness`).
> Derived, never stored: proof state (`none | proven | stale`), verification tier, consequence.

### 10.3 The candidate companion table (verbatim -- the Q4 subject)

> `work_item_criterion_evidence`, append-only, one row per (criterion version, leg, run).
> `leg`: `red_before | green_after | differential_admission | differential_modified |
> narrow_revert | standing_run | review | manual_attestation`.
> `outcome`: the frozen four-class vocabulary from `docs/contracts/vp-red-before.yaml`
> (`tautological | target_absent | assertion_failed | unmeasurable`) plus `pass | fail |
> skipped`.
> `at_sha`, `base_sha` (staleness derives from base reachability / target presence). `run_ref`
> (validator must dereference or reject). `producer`, `independent: bool`,
> `before_implementation: bool` for review rows.

### 10.4 Observed facts -- code surfaces

- `scripts/platform_roadmap_models.py:73` defines `ExitCriterion` (`id`, `text`, `status`,
  `met_by`, `blocked_by`). `:98` is `_normalize_exit_criteria`; `:104` assigns `f"c{i + 1}"` when
  normalizing a bare string. Structured entries are read verbatim.
- `scripts/verification_checks.py:302`-`:310` derive `CANONICAL_SLOTS` from the check classes and
  raise if `SLOT_COUNT != 6`.
- `scripts/contracts_schema.py:137` defines `EvaluatorSpec` with exactly two kinds, `check` and
  `agent_surface` -- specified for a Class D CONTRACT's evaluator: a registered `scripts/checks/*`
  name, or a non-Python agent-consumed surface that names the contract.
- `scripts/roadmap/plan_document.py:69` defines `VerificationStep`; `:24` pins
  `_V2_PHASE_ENUM = {"pre-deploy", "post-deploy"}`; `:50` pins `GraduationDisposition`. `phase` is
  typed `str`, enum-gated only at `schema_version >= 2`.
- `scripts/checks/roadmap/validate_platform_roadmap.py:128` is the bare-string rejection, applied
  only to tier items appearing in the git diff. `:15` pins `_ROADMAP_MAX_LINES = 10_000`.
- `scripts/checks/verification/validate_verification_registry.py:27` (`_modified_entries`) and
  `:194`-`:198` assemble `added + modified` as the differential candidate set.
- `scripts/verification_graduation.py:486` is `run_differential`: PASS on HEAD, then a worktree
  revert at `origin/main` that must FAIL, else "not admitted -- revert did not produce FAIL
  (tautological)".
- `scripts/executor/acceptance_lint.py:25` is `_classify_non_discriminating` -- a pure-string
  classifier that NEVER executes the command.
- `blocked_by` has three readers: `scripts/platform_roadmap_liveness.py:135` emits a
  `criterion_blocked_by` blocking edge into the liveness graph;
  `scripts/checks/roadmap/validate_roadmap_liveness.py:160` reads `crit.blocked_by` into
  `blocked_refs` to fail a criterion whose text names a non-terminal id with a blocking phrase but
  carries no matching edge; and `scripts/platform_roadmap_models.py:281` validates each blocker's
  ref / `until` kind agreement at model-load time.

### 10.5 Candidate observations (neutral; adjudicate each)

1. The converged shape writes `phase (pre_deploy | post_deploy)`. `_V2_PHASE_ENUM` and the merged
   plan corpus use `pre-deploy` / `post-deploy` (4,015 and 598 steps of 4,665 carrying a `phase`);
   the corpus also carries 29 distinct non-enum `phase` values across 52 occurrences, all on
   `schema_version: 1` plans.
2. The converged shape states `cN` is positional. Six structured criteria use `cA`..`cF`; ten more
   carry `cN` ids that do not match their position.
3. Of the cached recommendation rows, none carried a list-form (TypedCheck) `acceptance` value;
   all carried a scalar string. CD.29's consolidation clause specifies the typed-check structure
   as the evolved shape of that field.
4. The large majority of cached recommendation rows carry no `verification_tier` value.
5. One roadmap criterion out of 801 carries a `blocked_by` entry.
6. No tier item mixes bare-string and structured criteria: every bare-string-carrying item is
   wholly bare.
7. The converged shape attributes `authored_at_sha` to "Decision 189's eligibility predicate".
   That predicate, at `docs/contracts/vp-red-before.yaml:126`, is stated as diff status `A` or `??` AND a falsy
   `implementation_declared`; it names no sha comparison.
8. `T3.15` c1 requires every merged `feat(...)` PR body to contain the executed VP compliance
   table (command, truncated output, attempts, PASS/FAIL); c4 requires a synthetic flaky step
   (attempts > 1, empty intervening diff) to be marked NONDETERMINISTIC rather than silently
   passing. No warehouse table holds either.
9. `ops_recommendations.execution_result` is documented as write-only and DQ-excluded.
10. Decision 176's Related line writes "CD.29 (superseded)"; the roadmap records CD.29
    `state: pending`. Treat CD.29's live state as what the roadmap says, and note the discrepancy
    if you rely on either reading.
11. The roadmap stands near its 10,000-line ceiling; rec-3960 is an open High recommendation for
    the headroom escalation plus two unowned residuals from the plan that landed Decisions
    196/197.
12. rec-3660's own title and context measure "88 of 166 tier_items"; the tree today holds 172
    tier items, of which 85 carry bare strings.
13. `evaluator_kind` reuses `EvaluatorSpec`, a model defined for Class D contract evaluators
    rather than for criteria.
14. The registry holds 894 live entry files under `config/agent/verification_registry/entries/`
    and 10 under `entries/deprecated/`, with no status column on any record; retirement is
    `git mv`.
15. The longest structured criterion text is 6,581 characters; the median is 193.5 over 394
    structured criteria.
16. The converged shape (Section 10.2) cites `scripts/platform_roadmap_models.py` "~L95-101" for
    the positional-`cN` behaviour. `_normalize_exit_criteria` is at `:98` and the positional
    assignment at `:104`. The verbatim block is reproduced unedited; the anchor is part of the
    artifact under audit.

### 10.6 Dedup pointers

Regenerate the cache per Section 5.2 and search it yourself; the counts below were measured at
`04a402a4` and are a CROSS-CHECK, not a substitute for your own search. If they disagree with what
you measure, yours wins and the disagreement goes in `meta.stale_anchors[]`.

Open recommendations owning nearby territory: **rec-3660** (the named owner of the bare-string
conversion and the criterion-(ii) gate flip); **rec-3094** (a single item's bare-string
conversion); **rec-3960** (roadmap headroom escalation plus unowned residuals from the Decisions
196/197 plan); **rec-3713** (the liveness detector emits `blocked_by` edges from met/rehomed
criteria, so a rehome never prunes its ring); **rec-3927** / **rec-3928** (`roadmap_items_complete`
behaviour on rehomed and empty criteria); **rec-3527** / **rec-3534** (ledger contract coverage
gaps); **rec-3932** (a closed VP command-shape vocabulary); **rec-3777** (the incentive toward
under-classifying a disposition as `not-applicable`).

Roadmap items owning nearby territory: **T-1.23** (the exit-criteria ledger itself, complete);
**T3.1** / **T3.18** / **T3.21** (the registry, the producer, the enforcement gate -- all
complete); **T3.15** (VP re-execution and durable evidence persistence, complete); **T3.7**
(mutation testing and orphan detection, `deferred_post_mvp`); **T3.10** (retire the legacy
`verification` projection, `not_started`); **T3.9** (post-merge recommendation reconciliation,
`not_started`); **T4.23** / **T4.24** (the Decision 197 forward-work carriers,
`deferred_post_mvp`); **T4.3** (the kind-generic pick surface, `not_started`).

## 11. EMPIRICAL PASS

Bounded measurement. Tag every finding `evidence_kind`: `observed` means you RAN something on the
audited tree (a command, a count, a replay) and the result is the evidence; `static` means you
reasoned over file content you read without executing anything. A re-derived count is `observed`.
"Outranks" is
operational, not decorative: at equal severity, an `observed` finding is ordered ahead of a
`static` one in `summary.top_improvements`, and is preferred as `summary.highest_leverage_change`.

Required measurements (re-derive on YOUR base sha):

- E1. The bare/structured criteria split and the bare-on-complete count.
- E2. The count of tier items carrying at least one bare string, by item status, and whether any
  item mixes the two forms.
- E3. Structured criterion ids that are not `cN`-shaped, and `cN` ids that do not match their
  position.
- E4. The `acceptance` value shapes across the recommendation cache: scalar versus list. If the
  cache is unreachable, record the deviation and mark dependent findings HYPOTHESIS.
- E5. `verification_tier` population across the recommendation cache.
- E6. Criterion texts that LOOK executable (a command head such as `bin/venv-python`, `pytest`,
  `grep`, `test -f`). State the exact rule you used -- a broader or narrower regex changes the
  count, and a prior measurement of this using a different rule returned a different number.
  Report the rule and the count together, never the count alone.
- E7. The `phase` population across the merged plan corpus: how many VP steps carry a `phase`, how
  many are `pre-deploy` and `post-deploy`, and how many DISTINCT non-enum values appear over how
  many occurrences. This is a counting sweep over every plan, not a 25-plan sample.
- E8. Every append-only per-entity event table that EXISTS today: enumerate from
  `docs/contracts/storage-substrate.yaml`, `docs/contracts/*.yaml`, and
  `config/lambda/ducklake/field_semantics*.yaml`. Note that `migrations/ducklake_ops_schema.sql`
  is the Neon CATALOG metadata schema, not the ops-table DDL -- do not expect table definitions
  there. This is Q4's precedent search; a null result is a real answer.

Sampling caps -- do NOT exceed: at most 25 registry entry shards; at most 25 plan documents; at
most 15 tier items read in full. ANY count this brief states in Section 10.5 is re-derivable as a counting sweep, whether or not it
appears as a numbered measurement below -- the caps bound how many artifacts you READ IN FULL, never
how many you count over. Counting sweeps are uncapped: ALL of E1-E8 are counting sweeps, E6 included
(it ranges over every criterion, not a 15-item sample, since a capped count would not be the
count E6 asks you to report), and E8's contract glob is explicitly one -- read each contract's
`write_mode` / `grain` keys only, never a contract in full, and stop once every file is
classified.

The counterfactual test, applied to every candidate compensating control you accept: if the defect
were real, would this control FAIL? A control that cannot catch the break neither lowers severity
nor justifies dismissal.

## 12. METHOD

- **P1 Read.** Section 10's decisions and contracts; the six surfaces; Section 3's traps.
- **P2 Trace.** DD-A, DD-B, DD-C. Do not form verdicts yet.
- **P3 Empirical.** Section 11, E1-E8.
- **P4 Adjudicate.** Every Section 10.5 candidate to a disposition per Section 2.
- **P5 Rate.** The Section 8 rubric, every surface.
- **P6 Dedup.** Section 13, before any finding is written.
- **P7 Answer.** Q1-Q5, each with its pinned verdict and finding-id basis. Write the
  "what the converged shape gets wrong" section here.
- **P8 Synthesize.** Severity, then maturity, LAST.

## 13. DEDUP DISCIPLINE

Before filing ANY finding, grep the three ownership surfaces: `docs/ROADMAP-PLATFORM.yaml`
(tier items and candidate decisions), `docs/DECISIONS.md`, and
`logs/.recommendations-log.jsonl`. Record your search terms and hit count on the finding
(`roadmap_crossref.dedup_search_terms`, `dedup_hit_count`). `dedup_hit_count` is the number of
DISTINCT OWNING ARTIFACTS your searches surfaced -- recommendations, tier items, candidate
decisions and Decisions that plausibly own this territory -- summed across all three surfaces,
never the raw grep line count. List those artifacts in `roadmap_crossref.item_ids`; the count and
that list must agree.

These two fields record the SEARCH, not the verdict. `classification` records the ADJUDICATION.
A finding may legitimately carry `dedup_hit_count: 3` with three `item_ids` AND
`classification: novel` -- that combination says you found three plausible owners, examined each,
and judged that none actually owns this defect. Say so in `roadmap_crossref.note`. Never zero the
count to make a `novel` classification look cleaner: a `novel` finding with an honest non-zero
hit count and a stated reason is stronger evidence than one with an empty search. A hit means a sufficiency assessment
or a rejection, never a fresh discovery. A finding with no recorded negative search is
`confidence: HYPOTHESIS`.

### Deliberate constraints -- DO NOT FLAG

Each is a live, deliberate decision. Flagging one as a defect is a failed adjudication.

- **Decision 67** -- only IMPLEMENTATION plans are authorable during the current window; the
  absence of STRATEGIC plans is deliberate.
- **Decision 197 clause 8** -- design now, migrate once post-MVP. No lift-and-shift of the
  roadmap's current shape into the warehouse meanwhile. "This should be built now" is not a
  finding.
- **Decision 176** -- one registry record per file, NO status column, retirement by `git mv` to
  `entries/deprecated/`, no index and no cached aggregate.
- **CD.29 six-slot closure** -- a seventh primitive requires a new candidate decision. Proposing
  one is in bounds; treating the closure itself as a defect is not.
- **Decisions 110 / 114 / 147** -- the roadmap is a single agent-first file; a per-tier split is
  forbidden. The sanctioned relief valves are compaction in place, lifecycle archival, and a
  consciously-cited raise.
- Closed by the requester before this audit was commissioned, each with the authority that closed
  it, none reopenable here: the severity values `required | quarantine` (CD.29's hard-gate clause,
  which forbids a permanent `advisory`); judgement as a seventh primitive slot (CD.29's six-slot
  closure -- modelled instead as `evaluator_kind` plus an evidence leg of `review`); the registry
  relationship being a LINK rather than a merge (Decision 176 clause 4, `docs/DECISIONS.md:1749`);
  intent as an edge rather than a column (Decision 197 clauses 3 and 5); and a DEADLINE for
  converting the bare strings (closed by the REQUESTER, on their own authority, when commissioning
  this audit -- not by the prior reviewers, whose agreement would be circular grounds here since
  Section 2 asks you to disagree with them). You may argue that one of these is
  wrong IN PROSE under Q5; you may not file it as a finding or answer a fork with it.

## 14. OUTPUT

Write exactly two files. `<sha>` is your base short sha throughout.

The block below is a SCHEMA SKETCH, not literal YAML: it uses `a|b|c` for enums, `<int>` for
placeholders, and flow mappings for compactness. Your deliverable must be VALID YAML carrying
these keys with these value types -- render it in whatever block style parses cleanly, since
Section 16 makes a clean parse the pre-push gate. Key order does not matter; key names and enum
values do.

`audits/criterion-shape-forks-<sha>.yaml`:

```
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>,
         methodology_version: 1, scope_surfaces: [S1, S2, S3, S4, S5, S6],
         degraded_dedup: false, contract_notes: "",
         stale_anchors: [{kind: anchor|measurement, ref: "<file:line or measurement name>",
                          prompt_says: "", found_instead: ""}],
         capability_deviations: [{class: capability|judgment, obligation: "", detail: ""}]}
  question_answers:
    - {q: Q1, verdict: a-periodic-standing-runs|b-admitted-once|c-guard-target-triggered-only|
               d-other-argued,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: derive-from-phase-x-slot|extend-plan-grain-floor|
               keep-stored-until-derivation-exists|drop-the-field|other-argued,
       basis: [], prose: ""}
    - {q: Q3, verdict: pin-ids-in-yaml-now|pin-at-migration-time|terminal-migrated-bare|
               other-argued, basis: [], prose: ""}
    - {q: Q4, verdict: one-table-proof-struct|two-tables-evidence-journal|other-argued,
       precedent: [<table or artifact names; empty list means none found>],
       basis: [], prose: "",
       external_checklist: [{property: P1|P2|P3|P4|P5|P6|P7|P8|P9,
                             rating: met|partial|missed|n/a, evidence: ""}]}
    - {q: Q5, answers: [{question: "", disposition: answered|dismissed, answer: "",
                        basis: [<finding ids>]}],
       reversal_trigger_assessment:
         {verdict: not-tripped|tripped-reopen-clause-3|tripped-but-absorbable|other-argued,
          nullable_column_count: <int>, which_columns: [], rationale: "", basis: []},
       deferred_walk_inputs:
         merge_key: {verdict: parent-plus-criterion-id|surrogate-ulid-only|
                              content-hash-composite|other-argued, value: "", rationale: "",
                     basis: []}
         join_keys: {verdict: registry-fk-only|registry-fk-plus-plan-slug|evidence-table-fk|
                              other-argued, targets: [], rationale: "", basis: []}
         partition_column: {verdict: "<column name>"|none-argued, applies_to: [], rationale: "",
                            basis: []}
         current_projection: {verdict: scd2-history-plus-type1-current|history-only|other-argued,
                              rationale: "", basis: []}}
  converged_shape_corrections:
    - {element: "<field or claim in Section 10.2 or 10.3>", what_it_says: "",
       what_is_true: "", evidence: "file:line", consequence: "",
       confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: S1..S6, maturity: frontier|strong|solid|nascent,
       strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1..S6, dimension: VD1..VD7, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id|null", note: ""}
    # evidence is null ONLY on an n/a cell, where `note` carries the one-line reason the
    # dimension does not structurally apply. Every other rating requires an anchor.
  findings:
    - {id: CSF-01, surface: S1..S6|shared, affects_surfaces: [S1..S6],
       question: Q1..Q5|none, dimension: VD1..VD7|none,
       title, evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [],
                          dedup_hit_count: <int, or null under degraded_dedup>, note: ""},
       effort: XS|S|M|L, depends_on: [finding ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
    # change_type: add = a field/table/leg that does not exist; rescope = an existing element's
    #   meaning or coverage changes; enforce = an existing rule gains a mechanical check;
    #   unify = two surfaces collapse to one; persist = something computed or discarded becomes
    #   stored; clarify = wording/semantics only, no shape change; retune_gate = an existing
    #   gate's threshold, trigger population or polarity changes.
    # acceptance: how a reviewer would know your proposed_change had landed. NOT a shell
    #   command and NOT a recommendation acceptance value -- you file no recommendations.
    # effort: XS <= 1 plan step, S = 2-3, M = 4-8, L > 8 or spans a migration.
  deep_dives:
    - {id: DD-A|DD-B|DD-C, conclusion: "", feeds: [Q1..Q5], basis: [<finding ids>]}
  measurements:
    - {id: E1..E8, rule: "<the exact command or predicate you used>", result: "",
       matches_brief: true|false|null, note: ""}
    # Every E1-E8 entry is REQUIRED even when it produced no finding -- a measurement that
    # yields nothing is a result. E6 must carry its regex in `rule`. matches_brief is null whenever
    # this brief states no NUMERIC compose-time figure to compare against -- E6, E8, and E5,
    # whose only statement is the qualitative "the large majority". E4 IS comparable: candidate 3
    # states a count of zero list-form values, so true/false applies. false when the brief states
    # a number (zero included) and yours differs -- and a false ALSO gets a meta.stale_anchors[] entry with
    # kind: measurement, which is the single home the .md closing line counts.
  noted:
    - {candidate: "", what_it_constrains: ""}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match,
       owner_ref: "rec-NNNN|T-id|CD.n|dec-NNN|null"}
    # owner_ref names what owns or excuses the candidate: a recommendation, tier item, candidate
    # decision or Decision. Use null for a "not a defect" dismissal with no owner; the
    # compensating_control and control_property_match carry the argument in that case.
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [ids], highest_leverage_change: <id>}
  # maturity lives ONLY in per_surface_assessment[].maturity -- it is not restated in summary.
```

`audits/criterion-shape-forks-<sha>.md` -- prose, at most ~1500 words, the executive layer a human
reads first. It must carry, in this order: the four fork verdicts (Q1-Q4) in one line each; the
`deferred_walk_inputs` answers in one line each; the "what the converged shape gets wrong" section -- which draws on BOTH
`converged_shape_corrections[]` (factual misstatements) and any S1/S2 `findings[]` entry (design
judgment), and must say which of the two each item is; the single highest-leverage change; the open questions you added under Q5; and a closing
line stating how many entries `meta.stale_anchors[]` holds, whether any changed a verdict, and
every `meta.capability_deviations[]` entry of class `capability` in one line each, and -- if
`meta.degraded_dedup` is true -- one line saying the recommendation-side dedup did not run and
why; and any `meta.contract_notes` entry in one line. A capability gap or an unsearched dedup surface the human never sees is indistinguishable
from work you chose not to do.

### Invariants

- Finding ids are `CSF-NN`, zero-padded, numbered from `CSF-01` in the order you file them.
  `summary.top_improvements` holds AT MOST 5 finding ids ordered by severity first, then
  `observed` ahead of `static` at equal severity, and fewer when
  fewer exist -- an empty list is correct with 0 findings. `summary.highest_leverage_change` is a
  finding id, or `null` when `findings[]` is empty. Neither is ever padded with a correction id,
  a `noted[]` entry or an invented finding.
  `findings[]`, `converged_shape_corrections[]`, `rejected_candidates[]` and `noted[]` are
  uncapped -- Section 17's anti-padding rule governs them, not a number.
- COUNTING INVARIANT: `findings[]` is the SOLE enumerated list.
  `total_findings = len(findings) = novel_count + planned_insufficient_count +
  planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates[]`, NOT in
  findings. `rubric_ratings`, `question_answers` and `converged_shape_corrections` are
  systems-of-record referenced FROM findings, never re-counted. `deep_dives[]`, `measurements[]`
  and `noted[]` are likewise never counted into `total_findings`. `top_improvements` entries and
  a non-null `highest_leverage_change` MUST be finding ids.
- `control_property_match` is REQUIRED whenever a compensating control is the reason for
  dismissal: name the property the control exercises, cite where it operates (mechanism or
  file:line), and state why the control would FAIL if the defect were real.
- `CONFIRMED` on a BUILT surface (S3-S6) requires the behaviour traced to a file:line or an
  observed measurement. `CONFIRMED` on a DESIGNED surface (S1, S2) requires the gap traced to a
  named constraint the proposal violates or fails to satisfy -- a contract rule, a ratified
  decision clause, or a measured property of the data it must carry, cited by file:line -- with
  the proposal itself cited as Section 10.2 or 10.3. A design finding is not condemned to
  `HYPOTHESIS` merely because the table does not exist yet; it is `HYPOTHESIS` when you cannot
  name what it collides with. `evidence` on such a finding carries the CONSTRAINT's anchor, not a
  nonexistent implementation's.
- `converged_shape_corrections[]` may be empty, but an empty one requires a sentence in the
  companion report saying you looked and found nothing -- not silence.

## 15. SEVERITY AND MATURITY

Assign severity AFTER judgment, by defect class. Never inherit it from this brief's framing.

- **critical** -- on S1/S2: the shape as proposed would let a criterion be recorded as satisfied
  on a proof that does not hold, with nothing downstream able to detect it, or an irreversible
  migration would proceed on an unsound identity. On S3-S6: the surface as BUILT already does
  that today. For a finding whose `affects_surfaces` spans both groups, the BUILT reading
  governs -- a defect that is live today outranks the same defect merely proposed.
- **high** -- a weakness that materially reduces the guarantee AND whose compensating controls you
  judged insufficient under the counterfactual test.
- **medium** -- redundancy, ambiguity or inconsistency with a clear fix.
- **low** -- clarity or wording.

Compensating controls must PROPERTY-MATCH: the control must exercise the same property AND fail if
the defect were real. Apply the counterfactual to the control itself.

Maturity is computed LAST, per surface, top-down, first match wins. Every finding you file counts
as open -- findings carry no open/closed axis. A finding counts against every surface listed in
its `affects_surfaces` field. For a finding whose `surface` is a single id, `affects_surfaces` is
that one id; for `shared`, list every surface it genuinely bears on. `affects_surfaces` is never
empty.

- **frontier** -- 0 `critical` and 0 `high` findings on that surface, AND the checklist condition
  below where it applies.
  CHECKLIST CONDITION, stated once and nowhere else: no property in Q4's `external_checklist`
  rated `missed`. It gates ONLY the designed surface your Q4 verdict endorses -- S1 under
  `one-table-proof-struct`, S2 under `two-tables-evidence-journal`, and BOTH S1 and S2 under
  `other-argued` (you rated what you proposed, which spans them). It never gates S3, S4, S5 or S6.
  A surface it does not gate reaches `frontier` on finding counts alone.
- **strong** -- 0 `critical` and at most 1 `high`.
- **solid** -- at most 1 `critical`.
- **nascent** -- otherwise.

The top rating stays reachable where you argued a property-matched compensating control. This
brief's framing does not foreclose it.

## 16. COMMIT AND PR MECHANICS

1. You already derived the base in Section 5.1 and it is baked into your branch name. Do NOT
   re-fetch or re-derive it here: `origin/main` may have advanced mid-run, and a second sha would
   contradict the branch name, the filenames and `meta.audited_commit`. Use the Section 5.1 sha
   everywhere. If you notice `origin/main` has moved, that is not a problem to fix -- your audit
   is of the tree you measured, and `meta.audited_commit` names it correctly.
2. You are already on `audit/criterion-shape-forks-<sha>`, created off `origin/main` in Section
   5.1, so the PR diff contains only your two deliverables. This is a deliberate, documented
   exception to the `AGENTS.md` session-branch rule. Do not create or switch branches again.
3. Validate before pushing: a clean YAML parse of your `.yaml` deliverable is the real pre-push
   gate (`bin/venv-python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" audits/...`).
   Repo-wide validation is advisory outside CI in this repository; if `bin/venv-python -m
   scripts.validate --pre` fails for a reason unrelated to your two files, record it in
   `meta.contract_notes` and do NOT fix it -- that is outside your write boundary.
   `meta.contract_notes` is a single free-text string with more than one possible writer (here and
   Section 5.1); APPEND to it, separating entries with `; `, rather than overwriting.
4. Commit with `user.name=Claude`, `user.email=noreply@anthropic.com`, subject
   `audit(criterion-shape-forks): findings at <sha>` (the `audit({slug}):` prefix is a registered
   convention in `docs/contracts/git-ops.yaml`), body = two or three lines naming the four fork
   verdicts. No co-author or session trailers are required of you. Then `git push -u origin HEAD`.
   `audits/` already exists and is not gitignored; you are adding two files to it.
5. Open the PR with `gh pr create --base main --title "audit: unified criterion shape for the
   Decision 197 clause 3 grain (criteria model, evidence journal, live ledger/registry/rec
   fields)"`, ready for review (not a draft), body = a 2-3 sentence lede plus your `summary` block
   in a yaml fence.
   IF `gh` is absent, unauthenticated, or the PR call fails: do NOT abort and do NOT hunt for
   another route. The PUSHED BRANCH is the deliverable. Record the failure in
   `meta.capability_deviations[]` as class `capability`, print the branch name and the two file
   paths as your closing output, and stop. IF the push itself is rejected, commit locally, record
   the same way, and print `git log --oneline -1` plus the two paths.
6. END THE TURN. Do not poll CI, do not merge, do not self-approve, do not subscribe to the PR.
   The human disposes.

## 17. GUARDRAILS

- **Write boundary, closed list.** `audits/criterion-shape-forks-<sha>.yaml` and
  `audits/criterion-shape-forks-<sha>.md`. Nothing else in the tree. Not a contract, not a
  decision, not the roadmap, not a plan, not a test, not a recommendation through the portal.
  Regenerated gitignored caches are expected and never committed.
- **Precision over volume.** Fewer than ~8 surviving findings is a valid result -- state it
  plainly; do not pad. A rubric cell rated `n/a` with a one-line reason is a better answer than a
  manufactured `weak`.
- **A null result is a success.** "The converged shape is right on all four forks, and here is the
  disconfirming work I did" is a complete and valuable outcome -- provided Section 12's P2 and P3
  actually ran and the companion report shows what could have changed your mind.
- **You are not the second opinion on a settled design.** Two reviewers already agreed. Your value
  is in the places where a different prior sees a different answer. Where you agree, say so
  briefly and move on; spend the words where you do not.
