# AUDIT: LOOP-SPEC ADOPTION REVIEW (VALIDATION + STANDING LOOPS)

This prompt is self-contained and executes in a fresh session with no prior context. Do not ask
clarifying questions; every judgment call is either assigned to you explicitly or pinned by a
rule below. You audit and draft; you change nothing you audit.

## 1. TASK

Assess whether the proposed "loop-spec architecture" -- five techniques (P1-P5, defined in
SCOPE) for declaring and enforcing the properties of this repository's optimization loops -- is
appropriate for this repository, technique by technique, given what is already built and what is
already planned. The repository is a public, agent-first platform pursuing governed recursive
self-improvement; its existing verification machinery is substantial, and the decisive question
is residual value: what would each technique catch or guarantee that built and planned surfaces
provably do not, and at what cost. You assess eight surfaces (S1-S8 in SCOPE): seven built, one
designed-unbuilt (the proposal itself). You answer five questions (Q1-Q5), rate a rubric
(VD1-VD7), run three deep-dives (DD-A/B/C) and a bounded empirical pass, and render a
per-technique adoption verdict. Deliverables: exactly two files, `audits/loop-spec-adoption-
{base-short-sha}.yaml` (the audit record, schema pinned in OUTPUT) and `audits/loop-spec-
adoption-{base-short-sha}.md` (companion report, <= 1500 words). The ONLY files you create or
modify in the repository tree are those two deliverables; regenerating gitignored local caches
per SETUP is expected and does not breach the boundary (never commit them). Every change you
propose is PROPOSED, never executed. You draft; the human disposes.

## 2. CANDIDATE OBSERVATIONS vs VERDICTS

This prompt hands you FACTS (grounding map, verified at compose time) and CANDIDATE hypotheses
(C1-C7 below), never verdicts. ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run
that merely confirms the candidates below has failed.

Adjudicate each candidate to exactly one disposition:

- CONFIRMED defect after tracing -> `findings[]`, classification `novel`.
- Owned by a roadmap item / decision / open rec whose remedy you judge insufficient ->
  `findings[]`, classification `planned-insufficient`.
- Owned and the owning remedy is sufficient but unbuilt, and the gap matters before it lands ->
  `findings[]`, classification `planned-unbuilt`.
- Owned and fully covered (built, or planned with adequate sequencing) -> `rejected_candidates`,
  naming the owning item.
- Not a defect at all -> `rejected_candidates`, naming the compensating control and its
  property match (see SEVERITY + MATURITY).

The candidates:

- C1 (declaration gap). No surface obliges a standing loop -- a cron sensor workflow, a
  scheduled agent, a validation tier -- to declare its objective, constraints, backstop, and
  stop conditions in one auditable place. The loop-governing invariants that do exist are
  enforced piecewise in separate checks.
- C2 (discrimination gap for the check fleet). Proof that each of the ~46+ glob-gated `--pre`
  checks still DETECTS its target defect class sits between three built/planned mechanisms that
  each exercise a different property: Decision 170 accounting proves a check EXAMINED something
  (activity), `validate_pre_glob_closure` proves a diff REACHES the check (selection), and
  T3.7 mutation targets GRADUATED registry shards' guard lines (a different population). The
  hypothesis: no mechanism, built or planned, demonstrates detection for the check fleet itself.
- C3 (piecewise loosening control). Marker-gated loosening (Decision 165) covers five named
  guards; contract ratchet pins cover `docs/contracts/` population; Decision 135 makes selection
  additive-only. The hypothesis: concrete weakening moves exist that no marker, ratchet, gate,
  or post-hoc detector catches (DD-B enumerates ten to trace).
- C4 (backstop asymmetry). The interactive validation loop has a slower ground-truth oracle with
  attributed escapes (full tier + ci-rca `escape_class`); the hypothesis is that some standing
  non-validation loops (S7) have no declared backstop, escape detector, or ratchet route.
- C5 (anti-proposal candidate). The loop-spec contract may be net-negative: the population gate
  requires a resolving evaluator at landing, census ratchet pins constrain `docs/contracts/`
  growth, and existing surfaces (check-manifest, verification-registry, ci_rca_taxonomy,
  check-accounting) already carry much of the declaration; extending them may beat a new
  contract. Take this candidate as seriously as the others.
- C6 (stop-condition governance). Iteration caps and stop conditions for agentic loops appear
  ad hoc per surface (e.g. a `--max-turns 30` literal in one workflow) rather than declared and
  reviewed anywhere.
- C7 (escape-to-fixture conversion). A confirmed escape produces a REC (a work item) and a fix,
  but no mechanism converts the escape into a permanent machine fixture that must keep failing
  under the fast tier; permanence relies on the fix author's test-writing convention.

## 3. READ FIRST -- DISAMBIGUATION TRAPS

- Two registries share one word. The "check registry" is `scripts/checks/registry.py` plus 17
  per-domain `_manifest.py` files (which checks exist and when they run). The "verification
  registry" is the T3.1 graduation registry: per-check_id shards under
  `config/agent/verification_registry/entries/` (which verification steps graduated from plans).
  They are different populations with different contracts.
- Two vacuous-pass mechanisms. Decision 170's `examined(0)` -> "vacuous" outcome is in-run
  accounting inside validate; `scripts/ci_rca/vacuous_pass.py` is post-hoc CI-log parsing used
  by CI-RCA evidence. Related purpose, different layers; neither subsumes the other by name.
- Three "budgets". The fast-tier SECONDS budget (300s, S1), SLOC budgets
  (`config/sloc_budgets.yaml`), and AWS cost budgets (cost-reconciliation workflow). This audit
  concerns the first; the second matters only as the marker-mechanism precedent; the third is a
  standing loop in S7's population.
- "Fixture" in this prompt means a known-bad input a verifier must flag (P4), not a pytest
  fixture.
- `validate_pre_glob_closure` is ADVISORY by design (staged wave 4a; wave 4c flips it to
  blocking once the backlog is paid down). Reading its advisory status as an oversight is a
  misread; assessing whether the staged tail has an owner is in scope.
- The prior audit `audits/verification-system-review-f80508b.yaml` (finding ids VF-*) predates
  recent landings: its VF-05 evidence cites a monolithic `config/agent/verification_registry/
  registry.yaml` with `entries: []`; that file no longer exists (Decision 176 re-grained the
  registry to per-check_id shards) and the shard population is now large. Re-derive current
  state; do not inherit the audit's observations.
- `docs/contracts/verification-registry.yaml` says `ratified_via: "dec-102: PLAN-t3-1-verifier-
  harness merge to main"`, while the `## Decision 102:` header in `docs/DECISIONS.md` is the
  SLOC Waiver Ratchet. Do not resolve graduation-registry provenance through the DECISIONS.md
  number alone; if the mismatch matters to a finding, record it in `meta.stale_anchors` and move
  on -- decision-log citation integrity at large is another audit's territory.
- The strings "D2-2b" and "D2-3" appear in two module docstrings as provenance labels and
  resolve to no on-disk artifact. Do not chase them.
- "Loop" appears in unrelated names: the `/loop` harness skill, `docs/plans/PLAN-closure-
  loop.yaml`, and the prior audit `audits/unclosed-loops-44ef5c6.yaml` (governance-state
  bookkeeping loops). This audit's subject is OPTIMIZATION loops as defined in SCOPE.

## 4. SCOPE

Vocabulary, pinned for this audit:

- An OPTIMIZATION LOOP (here, "loop"): any recurring automated process that acts on the
  repository or its operational state toward a goal -- a validation tier run per PR, a cron
  sensor workflow, a scheduled agent, an RCA agent invocation.
- OBJECTIVE: the one quantity a loop optimizes. CONSTRAINT: a property the loop must preserve,
  each backed by an ORACLE (a deterministic check or gate). BACKSTOP: a slower, more complete
  oracle that catches what the fast one misses. ESCAPE: a defect the fast oracle passed and the
  backstop caught. RATCHET: the mechanism making a caught escape permanently un-reopenable.
  LOOSENING: any edit that weakens what "passing" means; TIGHTENING: the reverse.
- The five proposed techniques (surface S8, designed-unbuilt; no repo artifact exists):
  - P1: a Class D contract `docs/contracts/loop-spec.yaml` carrying (a) a loop-entry grammar --
    one objective, oracle-backed constraints, write-scope vs frozen-scope disjointness, a
    backstop plus ratchet route, stop conditions -- and (b) the registry of declared standing
    loops.
  - P2 (L1): a registered evaluator check enforcing the grammar: required fields, every
    constraint's oracle resolves in the check registry or names a workflow job, declared
    fixtures exist, scope globs disjoint, numeric literals (e.g. the 300s budget) derived-and-
    asserted against their live source rather than restated.
  - P3 (L2): coverage enumeration -- mechanically enumerate loop-bearing surfaces (workflows
    with schedules or agent invocations, scheduled-agent manifest entries, validation tiers)
    and fail when one lacks a loop-spec entry.
  - P4 (L3): a fixture-parity harness -- every declared oracle must red on at least one
    committed known-bad fixture; confirmed escapes ratchet in as new mandatory fixtures.
  - P5 (L4): a loosening gate -- edits that weaken a declared loop invariant require an inline
    `# loop-approved: dec-NNN` marker authorized by a numbered Decision, via the existing shared
    marker-guard mechanism; tightening stays unrestricted ("tighten free, loosen gated").

Surfaces:

- S1 (built): the fast-tier validation loop -- `--pre` selection, budget, fail-closed skips.
- S2 (built): the full-tier/canary ground truth plus the CI-RCA escape loop.
- S3 (built): budget governance -- the 300s objective, breach handling, warehouse ingestion.
- S4 (built): the selection-soundness stack -- Decision 135 derivation, Decision 170
  accounting, the pre_glob closure auditor, check-manifest grammar.
- S5 (built): verifier change control -- marker guards, contract population ratchets.
- S6 (built + designed): graduation and discrimination machinery -- T3.1 registry and shards,
  differential admission, T3.7 meta-validation (designed).
- S7 (built, heterogeneous): standing non-validation loops -- the cron sensor workflow fleet
  and the inert scheduled-agent fleet. Automated loops only: the interactive human-gated
  workflows (/orient, /plan, /implement, overseer) are context, not rated surfaces.
- S8 (designed-unbuilt): the P1-P5 proposal itself.

Out of scope, one line each: the terraform apply/guard model (environment-taxonomy Axis A) except
as change-control precedent; product/ML-output correctness; executor Step Functions internals
beyond loop-governance interactions; secrets/IAM specifics; SLOC policy content (only its marker
mechanism); prompt quality of interactive skills; decision-log citation integrity at large.

Trust nothing quoted here: obtain every file, line, count, and identifier by reading the
repository -- trust no number quoted in this prompt; re-derive from the repo and record any
non-resolving anchor in `meta.stale_anchors` (readers: the human disposer and the next audit).

## 5. SETUP

Run, in order; on failure take the named degraded path -- never abort, never improvise:

1. `git fetch origin main` then `git rev-parse --short origin/main` -- this base IS the audited
   tree; record it once and use it everywhere (filenames, branch, `meta.audited_commit`).
   Degraded (fetch fails): audit the checkout's HEAD, note it in `meta.contract_notes`.
2. `git switch -c audit/loop-spec-adoption-<sha> origin/main` (mechanics rationale in section
   16).
3. `bin/venv-python --version` -- the repo's mandatory interpreter wrapper. Degraded (missing or
   broken venv): note in `meta.contract_notes`, skip step 4 via the hatch below.
4. Cache generation for dedup: `bin/venv-python -m scripts.session.preflight --roadmap-detail
   full` (populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`; its
   stdout also carries the budget-breach/bypass telemetry lines S3 samples). IF cache-gen fails
   (creds/egress down): do NOT abort -- set meta.degraded_dedup=true, mark every
   roadmap_crossref confidence=HYPOTHESIS and dedup_hit_count=null, proceed. (Reader of
   `degraded_dedup`: the dedup-discipline rule in section 13 and the human disposer.)
5. Do NOT run `scripts.validate` or any tier as part of this audit; repo-wide validation is
   advisory outside CI here, and an unrelated failure would burn your budget. A clean YAML
   parse of your two deliverables is the real pre-push gate. If you nonetheless observe a
   pre-existing red anywhere, record it in `meta.contract_notes`; fix nothing.

## 6. NORTH STAR

Judgment-bearing bars, not absolutes: argue each surface against them; do not pattern-match.

- NS1 (goal as predicate): a loop's goal is one optimized objective plus frozen constraints,
  each constraint backed by a deterministic oracle -- never a naked metric.
- NS2 (optimizer/oracle separation): whoever optimizes inside a loop cannot redefine passing;
  loosening is gated and attributable, tightening is free.
- NS3 (demonstrated discrimination): the repository's own ratified bar, quoted from
  `docs/PROJECT_CONTEXT.md`: "A proposed verifier must itself demonstrate useful discrimination
  before becoming authoritative, including differential or mutation evidence where
  appropriate."
- NS4 (backstop with attribution): no fast oracle is trusted alone; a disagreement with the
  backstop is itself a tracked defect, attributed to the decision that admitted it.
- NS5 (permanent ratchet): a gap, once observed, cannot silently reopen.
- NS6 (declaration economy): one machine-readable surface per semantic, collocated with its
  enforcement; a NEW surface must beat extending an existing one (this repo treats a second
  surface covering the same subject as drift by design). NS6 is the counterweight to NS1-NS5:
  a technique can be right in principle and still wrong for this repo.

## 7. THE QUESTIONS

- Q1. For the interactive validation loop (S1-S4: fast tier -> full tier/canary -> CI-RCA ->
  recs -> planning), does the built system deliver the four loop-engineering guarantees --
  (a) goal-as-predicate, (b) optimizer/oracle separation with gated loosening, (c) backstop
  with attributed escapes, (d) permanent ratchet? Address each sub-guarantee in prose; verdict
  pinned: `sufficient | partial | insufficient`.
- Q2. Do the standing non-validation loops (S7) carry declared equivalents -- objective,
  constraints, backstop, ratchet, stop conditions? Rate the population, naming the loops you
  examined. Verdict: `sufficient | partial | insufficient`.
- Q3. For each technique P1-P5: adopt, adopt amended, defer, or reject? Answer via the
  `technique_verdicts` block (OUTPUT); this question's `prose` field summarizes and points
  there. The block's verdict enum: `adopt | adopt-amended | defer | reject`.
- Q4. Rate the repository's loop/verifier governance against this EXTERNAL CHECKLIST,
  property by property (`met | partial | missed`; `partial` requires an argued property-matched
  compensating control in the evidence). This checklist is the SOLE source the maturity top
  tier reads:
  1. presubmit/postsubmit tier split with escape attribution;
  2. test-impact-analysis soundness (additive selection, fail-closed skips, closure auditing);
  3. mutation or fault-injection evidence of verifier discrimination;
  4. verifier anti-vacuity accounting;
  5. enforced time budgets with breach telemetry reaching a system of record;
  6. flake policy (re-run discipline, quarantine rules, no silent re-run-to-green);
  7. escape-to-permanent-regression-artifact ratcheting;
  8. two-key change control on verifier weakening;
  9. stop-condition and iteration-cap governance for autonomous loops.
- Q5. Questions the requester did not think to ask. Seeds -- answer each, then add at least two
  of your own:
  1. Should escape-to-fixture conversion be mechanical, or stay rec-mediated per the RCA-first
     posture (Decision 55/72)?
  2. Does a monotone ratchet accumulate un-tightenable constraints over time (Decision 165's
     own reversal condition raises the small-grandfather-hook version of this) -- and what is
     the principled un-ratchet path?
  3. Can one PR today both change behavior and weaken the verifier that judges it? Trace what
     the "same-PR guard" named in graduation-registry material actually covers.
  4. Where should agentic loops' iteration caps and stop conditions live, if anywhere?
  5. Is 300s still the right fast-tier objective given the observed breach/bypass rate, and
     which surface owns re-deriving it?

## 8. RUBRIC

Rate each surface S1-S8 on each dimension, enum `strong | adequate | weak | absent | n/a`.
`n/a` is correct and costless where a dimension does not structurally apply -- never manufacture
a rating or a finding to fill a cell. Derivation: every question is served by at least one
dimension; every dimension feeds at least one question or deep-dive.

- VD1 declared-goal completeness (objective + constraints stated, in one findable place) --
  Q1, Q2.
- VD2 oracle separation and change control (loosening gated, attributable) -- Q1, Q4.8, DD-B.
- VD3 discrimination evidence (detection demonstrated, not declared) -- Q3/P4, Q4.3, DD-A.
- VD4 backstop and escape attribution -- Q1, Q2, DD-C.
- VD5 ratchet permanence -- Q1, Q2, Q5.1, DD-C.
- VD6 stop and feasibility governance (budgets, caps, breach handling) -- Q2, Q4.5, Q4.9.
- VD7 cost and duplication economy (NS6; new surface vs extension) -- Q3, DD-A.

S8 takes rubric ratings where dimensions apply to its DESIGN (VD7 always applies) and
`maturity: n/a` -- a proposal has no operational maturity; its disposition lives in
`technique_verdicts`.

## 9. DEEP-DIVES

- DD-A (overlap matrix; feeds Q3, VD3, VD7). For each technique P1-P5, identify every built or
  planned mechanism exercising the same property (grounding map section 10 lists the known
  ones; verify and extend). Apply the counterfactual: name a concrete defect class the
  technique would catch that the existing mechanisms, as built and as planned, provably would
  not. No such class -> the technique's verdict cannot be `adopt` unamended.
- DD-B (monotonicity walk; feeds Q1, Q2, VD2, and candidate C3). Trace each of these ten
  weakening moves as a hypothetical diff: which gate, marker, ratchet, or post-hoc detector
  fires, if any? Classify each: `gated-at-merge | detected-post-hoc | undetected`. Do NOT
  execute the moves; static tracing only.
  1. Narrow or delete one `pre_globs` pattern on a check's manifest Entry.
  2. Flip a check's Entry from `pre=True` to `pre=False`.
  3. Remove a check's `full_segment` so it runs in no tier.
  4. Raise the `_FAST_TIER_BUDGET_SECONDS` literal.
  5. Delete a check's mirror test file under `tests/checks/`.
  6. Remove one workflow name from the CI-RCA `workflows:` trigger filter.
  7. Comment out a cron sensor workflow's `schedule:` block.
  8. Edit a graduation-registry shard's `check_spec.node_id` to point at a trivial test.
  9. Add an entry to `validate_pre_glob_closure`'s `_PRUNED_EDGES`.
  10. Raise a SLOC budget without a marker (positive control -- expected `gated-at-merge`).
- DD-C (escape-ratchet traces; feeds Q1, VD4, VD5, candidate C7). For up to three real escapes
  (fast tier green, ground truth red), trace end to end: detection, attribution
  (`escape_class`/category), the filed rec, the fix, and the permanent artifact (test, fixture,
  closure rule) that now prevents recurrence -- or the absence of one. Source escapes from the
  regenerated recs cache (CI-RCA categories such as gate_escape) after SETUP; degraded path
  (cache absent): use the two incidents recorded inside Decision 135's Problem statement and
  trace their fixes.

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Verify each anchor before relying on it;
line numbers were resolved at compose time against a near-current main and may have drifted --
re-derive by header/identifier, and record non-resolving ones in `meta.stale_anchors`. Facts are
stated neutrally; classification is yours.

S1 fast tier:
- `scripts/validate.py:69` -- `_FAST_TIER_BUDGET_SECONDS = 300`; `:75` --
  `_FORCED_FULL_SUITE_CEILING_SECONDS = 1500`, comment derives it from the pr-validate job
  timeout (Decision 153).
- `scripts/validate.py:113-120` -- `_should_run_in_pre`: a gated check runs when ungated, when
  diff derivation failed, when the changed set is empty, or on a glob match; skip only on a
  successful non-empty derivation with zero matches; docstring: "never silently skip on doubt".
- `docs/DECISIONS.md` header `## Decision 135:` -- four-channel affected-set selection unioned
  "STRICTLY ADDITIVELY (selection can only grow)"; cap overflow "defers LOUDLY"; motivating
  incidents include rec-2638.
- Header `## Decision 153:` -- the budget assertion warns-instead-of-fails ONLY for a
  `full_suite_forced` run bounded by the forced ceiling; every non-forced breach files a budget
  rec, prints an ERROR, and exits 1.
- `.github/workflows/ci.yml:74-93` -- pr-validate runs `--pre` and uploads
  `logs/debug/selection-manifest.json` as artifact `selection-manifest`, `if: always()`,
  commented as an observability output "never a selection input"; `ci.yml:2-4` -- validate.py
  is the single source of truth; new checks enter it first.

S2 ground truth + escape loop:
- `ci.yml:95-146` -- main-validate runs the full suite on push; uploads `pytest-junit` and
  `validation-result` artifacts. A separate Main Canary workflow exists
  (`.github/workflows/main-canary.yml`).
- `.github/workflows/ci-rca.yml:22-30` -- the `workflows:` trigger filter; a comment at
  `:19-21` names `config/ci_rca_taxonomy.yaml`'s workflows map, enforced by
  `validate_ci_rca_adjudication`, as "the sole source of truth for this filter".
- `ci-rca.yml:242-274` -- on a main failure, the job fetches the merged PR's own `--pre`
  selection-manifest artifact ("Decision 135 escape-attribution"); resolution failure degrades
  to omitting `escape_class`.
- `ci-rca.yml` step "Run ci-rca agent" -- the agent is invoked with `--max-turns 30` and an
  `--allowedTools` list.
- `scripts/ci_rca/vacuous_pass.py:1-13` -- post-hoc log evidence: `vacuous_pass` tri-state,
  `merge_gate_test_coverage`, `coverage_regression` (deleted test files).
- `scripts/ci_rca/back_validation.py:1-18` -- flags a CLOSED ci_rca rec whose
  `preventive_action` did not hold (new open rec on the same file); "CANDIDATES only"; cites
  Decisions 55 and 57.
- `config/ci_rca_taxonomy.yaml:4-18` -- `failure_categories` includes `gate_escape` and
  `test_collection_empty`.

S3 budget governance:
- `scripts/convergence_health/budget_ingest.py:1-44` -- pr-validate is credential-free, so a CI
  breach cannot file a warehouse rec from the job; this cron module ingests the manifest's
  budget block instead; episode grain `(branch, dominant_phase)`; "A RESOLVED REC IS NEVER
  RESURRECTED".
- Compose-time preflight stdout reported 8 fast-tier budget breaches and 8 `--ignore-budget`
  invocations in the prior 7 days (dominant phase `pytest_diff`); re-derive from YOUR preflight
  run before treating as observed evidence.
- Compose-time open recs (re-derive from the regenerated cache): rec-3117 and rec-3253
  (fast-tier breach episodes), rec-2875 (a named cost-attribution defect in the differential
  gate's budget accounting).

S4 selection-soundness stack:
- `scripts/checks/registry.py:10-22` -- registering a check touches SEVEN surfaces (module,
  decorator, manifest Entry, taxonomy row, graduation shard per graduated step, mirror test,
  accounting declaration); `:24-36` -- Decision 170 accounting: outcomes
  `failed/skipped/vacuous/enforced/undeclared`; `examined(0)` yields `vacuous`.
- `docs/contracts/check-accounting.yaml:1-8` -- Class D, `ratified_via` Decision 170.
- `scripts/checks/deps/validate_pre_glob_closure.py:1-31` -- ADVISORY auditor (wave 4a): does
  each glob-gated pre check's `pre_globs` cover its own import closure; motivated by rec-3289;
  "Waves 1 and 2 found 12 such defective globs BY HAND"; wave 4c "flips it to blocking once the
  backlog is zero"; `_PRUNED_EDGES` is intentionally empty at introduction.
- Closed rec-3289's title reports 33 of 46 glob-gated pre checks under-declared their closure
  at measurement.
- `docs/contracts/check-manifest.yaml:39-51` -- `declared_segment_tokens` must equal
  `_schema.SEGMENT_TOKENS`, derived-and-asserted "rather than either side restating the other".

S5 verifier change control:
- `scripts/checks/_marker_guard.py:1-6` -- shared raise-marker authorization consolidating five
  guards (SLOC, prose, coverage-baseline, mypy-baseline, composite-action R3).
- `docs/contracts/marker-grammar.yaml:1-9` -- the mechanism's field-semantics contract.
- Header `## Decision 165:` -- marker validation upgraded from existence to AUTHORIZATION; its
  reversal conditions name a considered-and-deferred `Governs:` declared-marker design.
- `docs/contracts/contract-population.yaml:135-141` -- a NEW depth-1 `docs/contracts/*.yaml`
  must carry a valid contract block; Class D requires a non-empty RESOLVING evaluator;
  `:76-115` -- the `none_grandfathered` evaluator kind is retired and unrepresentable; ratchet
  pins `grandfathered_max` 17 and `status_active_max` 16.
- `AGENTS.md` SLOC section -- raises need `# raise-approved: dec-NNN`; "decreases and removals
  are always unrestricted".

S6 graduation and discrimination:
- `docs/contracts/verification-registry.yaml:1-23` -- Class A contract; six primitive slots;
  `guard_target` + `guard_symbol` indexing "so downstream orphan detection (T3.7) is
  deterministic"; data files are per-check_id shards (Decision 176).
- `config/agent/verification_registry/` contains only `entries/`; 471 shard files at compose
  time; sample shard `affected-set-retains-driver-tests-under-synthetic-diff.yaml`:
  `primitive_slot: test_selector`, `guard_target: scripts/checks/deps/affected_tests.py`,
  `graduated_at: '2026-08-11'`, `check_spec.node_id` naming a pytest node.
- `docs/ROADMAP-PLATFORM.yaml` item `id: T3.7` -- "Validation-suite meta-validation": scheduled
  mutmut ALARM-NOT-GATE (CD.12) aimed at graduated checks' guarded lines, `mutation_survivor`
  recs, equivalent-mutant allowlist; AST assertion-free lint as a BLOCKING check; registry
  orphan detection; coverage-uniqueness; CD.30 diff-line ratchet -- with an embedded VTS-07
  correction stating the coverage gate "is structurally inert in every CI context today".
- `audits/verification-system-review-f80508b.yaml` -- prior audit, findings VF-01..VF-14;
  its external-checklist prose states the system "LAGS the frontier on mutation testing";
  its T3.7 crossref row records that mutation targets only graduated checks and that T3.7 is
  "explicitly NOT on the CD.17 reversal path".

S7 standing loops:
- `.github/workflows/` held 22 workflow files at compose time, including cron-scheduled
  sensors: convergence-health, terraform-drift, main-canary, dedup-probe, ghas-probe,
  cost-reconciliation, ci-rca-inactivity-sweep, dependabot-stranded, branch-cleanup,
  rec-autoclose, reconcile.
- `.github/agents/schedule.yaml:1-30` -- scheduled-agent manifest; "The fleet is currently
  inert: every entry is enabled:false" pending T4.12.
- `scripts/verifiers/__init__.py` -- `REGISTRY: list[type[Verifier]] = []`, commented: legacy
  verifier fleet retired; harness retained for the executor tier.
- `audits/unclosed-loops-44ef5c6.yaml` -- prior audit of governance-state bookkeeping loops;
  its `systemic_fix` proposes a "dormant transitions" preflight surface.
- `docs/PROJECT_CONTEXT.md:36-48` -- the platform's canonical improvement loop; `:29` -- end
  state includes "a closed improvement loop that can complete one bounded iteration without a
  human in the critical path"; `:142` -- the NS3 discrimination sentence, and: "`scripts.
  validate` remains the single source of truth for CI checks".

## 11. EMPIRICAL PASS

Hard bounds -- do NOT exceed any of them:

- DD-B: exactly the 10 listed moves, static tracing only.
- DD-C: <= 3 escape traces.
- Graduation shards: <= 5 shards sampled. Per shard, apply the counterfactual as an operation:
  read `guard_target`/`guard_symbol` and the `check_spec` test; answer "if the guarded symbol
  were deleted or its behavior inverted, would this recorded check fail?" -- a NO is evidence
  for Q4.3/VD3.
- Budget evidence: <= 5 artifacts (preflight stdout lines plus budget recs from the cache).
- Tag every finding's `evidence_kind`: `static` (read from source) or `observed` (a sampled
  artifact or your own command output). At equal severity, observed findings outrank static
  ones in `top_improvements` ordering.

## 12. METHOD

- M1: SETUP; derive base; generate caches (or take the degraded path).
- M2: read the grounding-map surfaces, verifying anchors (bounded by the map; no repo-wide
  sweeps).
- M3: DD-A overlap matrix.
- M4: DD-B monotonicity walk.
- M5: DD-C traces plus the shard and budget sampling.
- M6: rate the rubric; answer Q1, Q2, Q4.
- M7: dedup every candidate finding per section 13; adjudicate C1-C7.
- M8: LAST -- `technique_verdicts`, Q3, Q5, severity assignment, maturity computation, summary,
  report. Then section 16 mechanics.

## 13. DEDUP DISCIPLINE

Before filing ANY finding: search the ownership surfaces -- `docs/ROADMAP-PLATFORM.yaml`
(tier_items and candidate_decisions; T3.1/T3.7/T3.2/T3.4/T4.12-T4.14 and gates CD.12/CD.17/
CD.29/CD.30 are known-nearby), `docs/DECISIONS.md` `^## Decision` headers, the regenerated
`logs/.recommendations-log.jsonl`, `audits/*.yaml` (verification-system-review VF-*,
unclosed-loops ULF-*, validate-test-suite), and `docs/plans/PLAN-*.yaml`. Record
`dedup_search_terms` and `dedup_hit_count` on every finding. A hit means
sufficiency-assessment (`planned-insufficient` / `planned-unbuilt`) or `rejected_candidates`,
never a fresh discovery. A finding without a recorded negative search is a HYPOTHESIS.

Deliberate constraints -- do NOT flag these as findings:

- Decision 67: strategic-plan and executor freeze; T4.12: scheduled-agent fleet inert.
- Decisions 55/72: RCA-first; sensors surface work, never remediate inline.
- Decision 153: the forced-full-suite budget waiver is designed behavior.
- CD.12 / T3.7: mutation testing as ALARM-NOT-GATE -- mutation as a merge gate was considered
  and rejected.
- Wave-4a advisory staging of `validate_pre_glob_closure` (the staging itself; the tail's
  ownership is fair game).
- Decision 86: no standing prose-architecture docs (any adopted artifact must be a
  machine-readable contract).
- The empty `scripts/verifiers` REGISTRY (deliberate retirement).
- Decision 84: warehouse as source of truth; no offline outbox.
- Decisions 77/92: the sandbox auto-apply guard model (out of scope entirely).

## 14. OUTPUT

Write `audits/loop-spec-adoption-{sha}.yaml` exactly in this shape (enums are pinned inline;
`{sha}` is the base short sha):

```
audit:
  meta: {audited_commit: <sha>, base_branch: main,
         model: "Claude (Anthropic); exact model id withheld from repo artifacts per harness policy",
         methodology_version: 1,
         scope_surfaces: [S1, S2, S3, S4, S5, S6, S7, S8],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: ""}
    - {q: Q3, verdict: see-technique_verdicts, basis: [<finding ids>],
       prose: "<one-paragraph synthesis pointing at technique_verdicts>"}
    - {q: Q4, verdict: sufficient|partial|insufficient, basis: [<finding ids>], prose: "",
       external_checklist:
         - {property: "<one of the nine, verbatim>", rating: met|partial|missed, evidence: ""}
         # exactly nine rows, in section-7 order; partial requires an argued
         # property-matched compensating control in evidence
    - {q: Q5, answers: [{question: "", answer: "", basis: [<finding ids>]}]}
      # the five seeds first, then >= 2 of your own
  technique_verdicts:
    P1: {verdict: adopt|adopt-amended|defer|reject, mechanism: "", what_changes: "",
         cost: XS|S|M|L, rationale: "", confidence: CONFIRMED|HYPOTHESIS,
         sequencing: {when: now|after-wave-4c|after-unfreeze|never,
                      blocked_behind: [<finding or roadmap ids>], note: ""}}
    P2: {...}  # same shape for P2-P5
  per_surface_assessment:
    - {surface: S1..S8, maturity: <per section 15; n/a for S8>, strengths: "",
       top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: S1..S8, dimension: VD1..VD7, rating: strong|adequate|weak|absent|n/a,
       evidence: "file:line|item-id", note: ""}
  findings:
    - {id: LSA-01, surface: S1..S8|shared, question: Q1..Q5, dimension: VD1..VD7,
       title: "", evidence: "file:line|item-id", evidence_kind: static|observed,
       current_behavior: "", ideal_behavior: "", gap: "",
       compensating_controls_considered: "",
       change_type: add|rescope|enforce|unify|persist|clarify|retune_gate,
       proposed_change: "", acceptance: "", severity: critical|high|medium|low,
       severity_rationale: "", confidence: CONFIRMED|HYPOTHESIS,
       roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: XS|S|M|L, depends_on: [<finding ids>],
       sequencing: {safe_to_queue_now: true|false, blocked_behind: [], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "",
       control_property_match: "", decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [<finding ids>],
            highest_leverage_change: <finding id>,
            maturity_S1: "", maturity_S2: "", maturity_S3: "", maturity_S4: "",
            maturity_S5: "", maturity_S6: "", maturity_S7: ""}
```

COUNTING INVARIANT, stated verbatim in your report: `findings[]` is the SOLE enumerated list;
`total_findings = len(findings) = novel + planned_insufficient + planned_unbuilt`;
fully-covered candidates live in `rejected_candidates`, NOT findings; `rubric_ratings`,
`question_answers`, and `technique_verdicts` are systems-of-record referenced FROM findings,
never re-counted; `top_improvements` and `highest_leverage_change` MUST be finding ids.

`control_property_match` is REQUIRED whenever a compensating control is the reason for
dismissal: name the property the control exercises, cite where it operates (file:line or
mechanism), and state why the control would FAIL if the defect were real. CONFIRMED requires
the behavior traced to file:line or an observed sampled artifact; anything less is HYPOTHESIS.

The companion `audits/loop-spec-adoption-{sha}.md` (<= 1500 words) is the executive layer:
lead with the five technique verdicts and the highest-leverage change, then Q1/Q2/Q4 in brief,
then notable findings and rejected candidates. Prose, no new claims absent from the YAML.

## 15. SEVERITY + MATURITY

Severity is assigned AFTER judgment, by defect class -- never inherited from this prompt's
framing:

- critical: a loop can deliver a wrong-but-trusted green (its optimizer can defeat or bypass
  the oracle with no surface reddening and nothing filed), or a verifier-weakening act can land
  with no gate, no marker, and no post-hoc detector.
- high: one of the four guarantees (declared goal, gated loosening, backstop with attribution,
  ratchet) is materially reduced AND the compensating controls you traced are insufficient.
- medium: redundancy, ambiguity, or inconsistency with a clear fix (including a duplicated
  declaration surface).
- low: clarity or wording.

Maturity: compute LAST, per surface S1-S7 (S8 is n/a), top-down, first match wins:

- frontier: 0 open critical or high findings on the surface AND every Q4 external-checklist
  property rated met or partial -- never missed.
- strong: 0 critical AND <= 1 high.
- solid: <= 1 critical.
- nascent: otherwise.

The top rating remains reachable when you argued a property-matched compensating control for a
checklist property -- this prompt's framing must not foreclose it. Fewer than ~4 surviving
findings is a valid result -- state it; do not pad.

## 16. COMMIT / PR MECHANICS

1. The base sha was derived in SETUP step 1; you are on branch
   `audit/loop-spec-adoption-<sha>` cut from `origin/main` (SETUP step 2), so the PR diff is
   only the two deliverables. This branch name is a deliberate, documented exception to the
   AGENTS.md `claude/*` session-branch rule: the audit needs a clean two-file diff off the
   audited base. The CI signal-green comment wake fires only on `claude/*` PRs -- irrelevant
   here, because you end your turn without merging; the human disposes of the PR.
2. Verify both deliverables parse as YAML/read cleanly (e.g.
   `bin/venv-python -c "import yaml,sys; yaml.safe_load(open('audits/loop-spec-adoption-<sha>.yaml'))"`).
   This is your pre-push gate. Do not run the repo's validation tiers; a pre-existing,
   unrelated failure is recorded in `meta.contract_notes`, never fixed.
3. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit`. Include no
   model identifier in the commit message, the PR title or body, or either deliverable.
   Message: `audit(loop-spec-adoption): adoption review of loop-spec techniques P1-P5`.
4. `git push -u origin HEAD` (on network failure retry up to 4 times with 2s/4s/8s/16s
   backoff).
5. Open the PR ready-for-review via `mcp__github__create_pull_request`: base `main`, title
   `audit: loop-spec adoption review (validation + standing loops)`, body = the `summary:`
   block in a yaml fence plus a 2-3 sentence lede. Then END THE TURN -- do not poll, do not
   merge, do not subscribe, do not self-approve.

## 17. GUARDRAILS

- Write boundary, closed list: `audits/loop-spec-adoption-<sha>.yaml`,
  `audits/loop-spec-adoption-<sha>.md`. Nothing else in the tree -- no fixes, no doc edits, no
  config changes, regardless of what you find. Gitignored caches regenerated by SETUP are
  expected local state; never commit them.
- Read-only elsewhere: no terraform commands, no AWS mutations, no ops-portal writes
  (`file_rec`/`update_rec` are out of bounds for this session -- recommendations are proposed
  inside the deliverables only).
- Honesty: precision over volume. A run that merely confirms the candidates has failed; fewer
  than ~4 surviving findings is a valid result -- state it; do not pad. Argue against your own
  classifications once per finding (the strongest rejected counter-reading goes in the
  finding's `note` or `compensating_controls_considered`).
- Budget: respect every sampling bound in section 11; no repo-wide sweeps beyond the grounding
  map and the dedup greps.
