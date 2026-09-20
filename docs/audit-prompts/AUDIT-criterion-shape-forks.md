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

Adjudicate each candidate to exactly one disposition:

- CONFIRMED defect, not owned by any existing item -> `findings[]`, `roadmap_crossref.classification: novel`
- Owned by an existing roadmap item / decision / open recommendation whose remedy you judge
  INSUFFICIENT -> `findings[]`, classification `planned-insufficient`
- Owned by an existing item whose remedy is adequate but UNBUILT -> `findings[]`, classification
  `planned-unbuilt`
- Owned and fully covered -> `rejected_candidates[]`, naming the owning id
- Not a defect -> `rejected_candidates[]`, naming the compensating control and its property match

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
   tier (T1/T2/T3/T4). Q2 concerns only the first.
4. **"status"** is a field name on at least four surfaces with four different enums: the
   criterion ledger (`open | met | rehomed`), a recommendation (`open | closed | in_progress |
   deferred | superseded | declined`), a tier item (`not_started | in_progress | complete |
   reserved | deferred_post_mvp`), and a contract envelope. The converged shape proposes
   `satisfaction` for the criterion axis. That word already appears as PROSE in this repository
   ("satisfaction oracle", "deterministic satisfaction", "the rehomed non-satisfaction case") but
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

- The `work_items` table, except exactly as far as Q3 and Q4 require. `work_item_edges` is in scope only
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
bin/venv-python -c "import yaml, pydantic; print('ok')"
```

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
is an opinion; ground it.

### Q1 -- Standing versus admitted

Should a graduated registry check ever mean "standing" -- that is, a live, continuously re-proven
guarantee -- or does it mean only "admitted once", a claim proven at one commit and never
re-tested?

Today's answer is "admitted once": `docs/contracts/verification-registry.yaml` governance_notes
records a row that had gone "permanently FAIL, unnoticed because graduated records are never
re-executed as a standing suite", and a sibling found "permanently TRUE" by the same migration.
Both had been unnoticed for months. The differential gate re-runs a row only when that row is
ADDED or MODIFIED in the diff.

Options:
(a) add `standing_run` and re-differential-on-`guard_target`-touch evidence legs, so graduated
becomes a live guarantee;
(b) CD.29's mutation testing (T3.7) plus mark-then-drop retirement remains the whole answer and
graduated stays "admitted once";
(c) a bounded middle -- re-differential only when `guard_target` appears in the diff.

Constraint you must weigh, not ignore: CD.29 is `state: pending`, so answering (a) or (c) is a
CD.29 amendment, and T3.7 is `deferred_post_mvp`. Decision 176 clause 4 is the standing argument
against a warehouse home for admission: "the differential gate reads its baseline at a GIT REF
(`git show origin/main:...`), which DuckLake cannot serve; admission is a property of a commit,
runs pre-merge and hermetically, and must revert atomically with the code it verifies."

**Verdict enum:** `a-standing-legs | b-admitted-once | c-bounded-middle | d-other-argued`

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

**Verdict enum:** `derive-from-phase-x-slot | extend-plan-grain-floor |
keep-stored-until-derivation-exists | drop-the-field | other-argued`

### Q3 -- Identity for the bare-string exit criteria

Measured at `04a402a4`: 801 roadmap criteria = 407 bare strings + 394 structured dicts; 259 of
the 407 sit on `status: complete` items, which the touched-item rule in
`scripts/checks/roadmap/validate_platform_roadmap.py` never fires on, so lazy migration never
reaches them. Bare-string ids are auto-assigned positionally at model-load time. In-YAML
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

This question additionally requires an `external_checklist` block. Assess THE DESIGN YOU ENDORSE
in your own verdict -- if you answer (i), rate the one-table proposal; if (ii), rate the two-table
proposal; if `other-argued`, rate what you propose -- property-by-property against these named
external practices, each rated `met | partial | missed` with evidence. `partial` requires an
argued, property-matched compensating control. This field gates the maturity top tier for S1 and
S2 ONLY (Section 15); it has no bearing on S3, S4, S5 or S6.

1. Event-sourced journal plus current-state projection, rather than state mutation in place.
2. Type-2 slowly-changing dimension paired with a separate fact table, rather than a widened
   dimension.
3. Test/build result history as a first-class fact table keyed on (test, run) -- the standard
   shape behind flake detection and suite-health analytics.
4. Provenance modelling in the W3C PROV sense: entity / activity / agent separated, so "what was
   claimed", "what was run" and "who ran it" are distinguishable.
5. Assurance-case separation (Goal Structuring Notation): CLAIM, ARGUMENT and EVIDENCE are
   distinct node types, and evidence is never merged into the claim it supports.
6. Quarantine registry keyed on (test, run) with a bounded, expiring lifetime rather than a
   permanent advisory state.
7. Mutation score, or an equivalent adequacy metric, treated as a decay signal on an existing
   suite rather than a one-time admission test.

**Verdict enum:** `one-table-proof-struct | two-tables-evidence-journal | other-argued`
**Additionally required on this entry:** `precedent: <table or artifact name> | none`, and
`external_checklist: [{property, rating, evidence}]` covering all seven properties above.

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

**Additionally required on Q5 -- the `deferred_walk_inputs` block.** Decision 197 clause 3
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
  join_keys:
    verdict: registry-fk-only | registry-fk-plus-plan-slug | evidence-table-fk | other-argued
    targets: [<the tables or surfaces this criterion row joins to>]
    rationale: ""
  partition_column:
    verdict: "<column name>" | none-argued
    applies_to: [work_item_criteria, work_item_criterion_evidence]
    rationale: ""
```

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
| VD7 | Shipped-mechanism portability -- Decision 197 clauses 1 and 4; no operator taxonomy in columns | Q2, Q5 |

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
| `docs/DECISIONS.md:59` | Decision 196 (context only; out of scope). |
| `docs/DECISIONS.md:7778`, `:7819` | Decision 48 tier definitions; its Limitation clause ("documentation-enforced only. No automated detection currently exists"). |
| `docs/DECISIONS.md:4126`, `:4174` | Decision 132 (graduation as an enforced obligation); residual limitation A, the classification seam. |
| `docs/DECISIONS.md:1695`, `:1749` | Decision 176 (registry re-grain); clause 4, why not the warehouse. |
| `docs/DECISIONS.md:581` | Decision 189 (red-before polarity for added, undeclared plans). |
| `docs/DECISIONS.md:5329`, `:3352`, `:5442` | Decisions 114 (10,000-line ceiling), 147 (compaction response and the named valves), 110 (single-file roadmap). |
| `docs/DECISIONS.md:6662`, `:6775`, `:3893` | Decisions 87 (plans as entities; clause 6 rec-vs-plan grain), 84 (portal invariants, I-2 id allocation, I-3 named verbs), 137 (partition every table). |
| `docs/DECISIONS.md:1236` | Decision 181 (declare-your-coverage: an unenforced arm is declared with a named owner). |
| `docs/contracts/exit-criteria-ledger.yaml` | Ledger field semantics. `fields.status` spans `:49`-`:92` and carries the realized-differently rule (`:57`) and Status-Trusted-Never-Inferred (`:71`). `fields.met_by` begins at `:93` and carries the `closes_criteria` flip procedure and its own Status-Trusted-Never-Inferred restatement (`:108`). `fields.blocked_by` begins at `:120`. `fields.blocked_by` carries the edge semantics and the foreign-ratification anti-pattern. |
| `docs/contracts/verification-registry.yaml` | Registry schema. `check_id` immutability and the (plan_slug, check_id) T3.21 join; `guard_target`/`guard_symbol` as the orphan-detection keys; `check_spec` as the materialization key. Line `:244` carries "permanently FAIL, unnoticed because graduated records are never re-executed as a standing suite". Lines `:222`-`:225`: filename-equals-check_id; `entries/deprecated/` is loader-excluded. |
| `docs/contracts/vp-red-before.yaml` | `outcome_classes` (`:97`), `unmeasurable_arms` (`:105`), `eligibility_predicate` (`:126`), `graduation_disposition_authoring` (`:216`), `self_satisfying_lint` (`:257`). |
| `docs/contracts/tier-item-lifecycle.yaml:131` | The bookkeeping walk EXECUTES executable-looking criterion text via subprocess, passing on exit 0; prose criteria fall through to agent judgement with a conservative bias. The only existing execution hook on the exit-criteria surface. |
| `docs/contracts/data-modeling-standard.yaml` | `rules`, `write_modes` (scd2 / append_only / control), and `design_time_walk` -- the walk this audit feeds. |
| `docs/contracts/storage-substrate.yaml:126` | `ops_smoke_events`: `write_mode: append_only`, grain "one row per event_id". |
| `docs/contracts/ops_recommendations.yaml:416` | `execution_result`: "Executor-internal write-only signal. Not read by the planning or triage paths. DQ-EXCLUDED (Decision 63)." |
| `docs/contracts/_joins.yaml` | The cross-table join / correlation-key registry. `design_time_walk` step 4 makes consulting it mandatory when a new table's join keys are chosen. Required reading for Q5's `join_keys`. |
| `scripts/checks/roadmap/validate_tier_floor.py:49`, `:62` | `_compute_floor` (Decision 48 semantics over a plan's scope paths) and the registered CI check that enforces it on `schema_version: 2` plans, with a `tier_waiver` escape. Owning item T3.17 is `complete`. |
| `docs/ROADMAP-PLATFORM.yaml` CD.29 | The six-slot closed kernel; the admission gate; severity `required` with a transient `quarantine`, "never a permanent `advisory`"; the consolidation clause absorbing the rec `verification` projection "as additional typed checks on the same field". `state: pending`. |

### 10.2 The converged shape (verbatim -- this is the artifact under audit)

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
   That predicate, at `vp-red-before.yaml:126`, is stated as diff status `A` or `??` AND a falsy
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

Bounded measurement. Tag every finding `evidence_kind: static` or `observed`. "Outranks" is
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
- E7. Every append-only per-entity event table that EXISTS today: enumerate from
  `docs/contracts/storage-substrate.yaml`, `docs/contracts/*.yaml`, and
  `config/lambda/ducklake/field_semantics*.yaml`. Note that `migrations/ducklake_ops_schema.sql`
  is the Neon CATALOG metadata schema, not the ops-table DDL -- do not expect table definitions
  there. This is Q4's precedent search; a null result is a real answer.

Sampling caps -- do NOT exceed: at most 25 registry entry shards; at most 25 plan documents; at
most 15 tier items read in full. Counting sweeps are not sampling and are uncapped: E1, E2, E3,
E5 and E7 are counting sweeps, and E7's contract glob is explicitly one -- read each contract's
`write_mode` / `grain` keys only, never a contract in full, and stop once every file is
classified.

The counterfactual test, applied to every candidate compensating control you accept: if the defect
were real, would this control FAIL? A control that cannot catch the break neither lowers severity
nor justifies dismissal.

## 12. METHOD

- **P1 Read.** Section 10's decisions and contracts; the six surfaces; Section 3's traps.
- **P2 Trace.** DD-A, DD-B, DD-C. Do not form verdicts yet.
- **P3 Empirical.** Section 11, E1-E7.
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
(`roadmap_crossref.dedup_search_terms`, `dedup_hit_count`). A hit means a sufficiency assessment
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
  converting the bare strings (rejected by both prior reviewers on the grounds that a bulk backfill
  of verification methods manufactures tautologies at scale). You may argue that one of these is
  wrong IN PROSE under Q5; you may not file it as a finding or answer a fork with it.

## 14. OUTPUT

Write exactly two files. `<sha>` is your base short sha throughout.

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
    - {q: Q1, verdict: a-standing-legs|b-admitted-once|c-bounded-middle|d-other-argued,
       basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: derive-from-phase-x-slot|extend-plan-grain-floor|
               keep-stored-until-derivation-exists|drop-the-field|other-argued,
       basis: [], prose: ""}
    - {q: Q3, verdict: pin-ids-in-yaml-now|pin-at-migration-time|terminal-migrated-bare|
               other-argued, basis: [], prose: ""}
    - {q: Q4, verdict: one-table-proof-struct|two-tables-evidence-journal|other-argued,
       precedent: [<table or artifact names; empty list means none found>],
       basis: [], prose: "",
       external_checklist: [{property: "<one of the seven>", rating: met|partial|missed,
                             evidence: ""}]}
    - {q: Q5, answers: [{question: "", answer: "", basis: [<finding ids>]}],
       deferred_walk_inputs:
         merge_key: {verdict: parent-plus-criterion-id|surrogate-ulid-only|
                              content-hash-composite|other-argued, value: "", rationale: ""}
         join_keys: {verdict: registry-fk-only|registry-fk-plus-plan-slug|evidence-table-fk|
                              other-argued, targets: [], rationale: ""}
         partition_column: {verdict: "<column name>"|none-argued, applies_to: [], rationale: ""}}
  converged_shape_corrections:
    - {element: "<field or claim in Section 10.2 or 10.3>", what_it_says: "",
       what_is_true: "", evidence: "file:line", consequence: "",
       confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: S1..S6, maturity: frontier|strong|solid|nascent,
       strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1..S6, dimension: VD1..VD7, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: CSF-01, surface: S1..S6|shared, question: Q1..Q5|none, dimension: VD1..VD7|none,
       title, evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior, ideal_behavior, gap, compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       # change_type: add = a field/table/leg that does not exist; rescope = an existing element's
       #   meaning or coverage changes; enforce = an existing rule gains a mechanical check;
       #   unify = two surfaces collapse to one; persist = something computed or discarded becomes
       #   stored; clarify = wording/semantics only, no shape change; retune_gate = an existing
       #   gate's threshold, trigger population or polarity changes.
       # acceptance: how a reviewer would know your proposed_change had landed. NOT a shell
       #   command and NOT a recommendation acceptance value -- you file no recommendations.
       # effort: XS <= 1 plan step, S = 2-3, M = 4-8, L > 8 or spans a migration.
       severity_rationale, confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [finding ids],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate, why_dismissed, compensating_control, control_property_match,
       decision_or_item_id}
  summary: {total_findings, novel_count, planned_insufficient_count, planned_unbuilt_count,
            top_improvements: [ids], highest_leverage_change: <id>}
  # maturity lives ONLY in per_surface_assessment[].maturity -- it is not restated in summary.
```

`audits/criterion-shape-forks-<sha>.md` -- prose, at most ~1500 words, the executive layer a human
reads first. It must carry, in this order: the four fork verdicts (Q1-Q4) in one line each; the
`deferred_walk_inputs` answers in one line each; the "what the converged shape gets wrong"
section; the single highest-leverage change; the open questions you added under Q5; and a closing
line stating how many entries `meta.stale_anchors[]` holds and whether any changed a verdict.

### Invariants

- COUNTING INVARIANT: `findings[]` is the SOLE enumerated list.
  `total_findings = len(findings) = novel_count + planned_insufficient_count +
  planned_unbuilt_count`. Fully-covered candidates live in `rejected_candidates[]`, NOT in
  findings. `rubric_ratings`, `question_answers` and `converged_shape_corrections` are
  systems-of-record referenced FROM findings, never re-counted. `top_improvements` and
  `highest_leverage_change` MUST be finding ids.
- `control_property_match` is REQUIRED whenever a compensating control is the reason for
  dismissal: name the property the control exercises, cite where it operates (mechanism or
  file:line), and state why the control would FAIL if the defect were real.
- `CONFIRMED` requires the behaviour traced to a file:line or an observed measurement. Anything
  less is `HYPOTHESIS`.
- `converged_shape_corrections[]` may be empty, but an empty one requires a sentence in the
  companion report saying you looked and found nothing -- not silence.

## 15. SEVERITY AND MATURITY

Assign severity AFTER judgment, by defect class. Never inherit it from this brief's framing.

- **critical** -- the shape as proposed would let a criterion be recorded as satisfied on a proof
  that does not hold, and nothing downstream could detect it; or an irreversible migration would
  proceed on an unsound identity.
- **high** -- a weakness that materially reduces the guarantee AND whose compensating controls you
  judged insufficient under the counterfactual test.
- **medium** -- redundancy, ambiguity or inconsistency with a clear fix.
- **low** -- clarity or wording.

Compensating controls must PROPERTY-MATCH: the control must exercise the same property AND fail if
the defect were real. Apply the counterfactual to the control itself.

Maturity is computed LAST, per surface, top-down, first match wins. Every finding you file counts
as open -- findings carry no open/closed axis. A finding whose `surface` is `shared` counts
against EVERY surface it names in its prose; if it names none, it counts against S1.

- **frontier** -- 0 `critical` and 0 `high` findings on that surface, AND (for S1 and S2 only) no
  property in Q4's `external_checklist` rated `missed`. The checklist does not gate S3, S4, S5 or
  S6, which have no stake in the one-versus-two-table fork.
- **strong** -- 0 `critical` and at most 1 `high`.
- **solid** -- at most 1 `critical`.
- **nascent** -- otherwise.

The top rating stays reachable where you argued a property-matched compensating control. This
brief's framing does not foreclose it.

## 16. COMMIT AND PR MECHANICS

1. Derive the base ONCE: `git fetch origin main` then `git rev-parse --short origin/main`. That
   commit IS the audited tree. Use its short sha in both filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/criterion-shape-forks-<sha> origin/main` so the PR diff contains only your
   two deliverables. This is a deliberate, documented exception to the `AGENTS.md` session-branch
   rule.
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
