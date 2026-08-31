# Loop-Spec Adoption Review (validation + standing loops) -- 4d8bac4a

Companion to `audits/loop-spec-adoption-4d8bac4a.yaml` (the system of record). Counting
invariant, restated: `findings[]` is the sole enumerated list (6 = 3 novel + 2
planned-insufficient + 1 planned-unbuilt); fully-covered candidates live in
`rejected_candidates`; every other block is referenced from findings, never re-counted.

## Technique verdicts

- **P1 (loop-spec contract + registry): REJECT.** The declaration function already exists in
  three live, evaluator-backed registers: the `ci_rca_taxonomy.yaml` workflows map (22 rows,
  owner + rationale, with a BLOCKING two-way census against the real workflow fleet), the
  scheduled-agent manifest, and the check-manifest/registry pair. A fourth register spanning
  the same populations is the drift-by-design second surface NS6 and AGENTS.md prohibit, and
  the population gate would force P2 to land atomically with it. This is candidate C5
  (anti-proposal) CONFIRMED for P1-P3.
- **P2 (grammar evaluator): REJECT.** Enforces a surface that will not exist; every technique
  it specifies (shape grammar, oracle-resolution bar, derived-not-restated literals) has a
  live precedent to copy if P1 is ever revisited -- where the population gate makes P2
  mandatory at landing anyway.
- **P3 (coverage enumeration): REJECT.** Already built and blocking where it matters:
  `validate_ci_rca_adjudication` asserts two-way name-set equality between the taxonomy map
  and `.github/workflows/*.yml` -- a new workflow cannot land without a declaration row. The
  real gap is row *content* (P1's business), not row existence.
- **P4 (fixture-parity harness): ADOPT-AMENDED.** Two DD-A-surviving defect classes, one
  observed: a registered check with no demonstrated red case anywhere (LSA-03), and a
  confirmed escape whose fix never became a machine fixture (LSA-04, rec-3131 -> rec-3328
  recurrence). Amendments: decouple from loop-spec entirely -- (1) a static registry-level
  red-case floor over mirror tests; (2) a closure obligation on escape-classified recs (no
  close without a named, landed artifact); (3) execution-grade replay routed to the full tier
  or T3.7's scheduled alarm lane, never `--pre` (rec-2875 is the cost precedent).
- **P5 (loosening gate): ADOPT-AMENDED.** DD-B proves the surviving class directly: three
  weakening moves land with no gate, no marker, and no detector, while the positive control
  (SLOC raise) gates at authorization grade. Amendment: extend the existing shared
  `_marker_guard` (RegistrySpec pattern, no new contract) to exactly the proven-open surfaces
  -- manifest tier demotion, mirror-test deletion, sensor `schedule:` removal. Tighten stays
  free.

**Highest-leverage change: LSA-04** -- make closure of an escape-classified rec contingent on
naming its landed permanent artifact. It converts every future escape into permanent machine
coverage and is the one finding backed by an observed in-the-wild failure of the current
convention (a closed rec's claimed preventive check was never built; the class recurred under
the same fingerprint; only the candidate-grade back-validation sensor noticed).

## Q1 -- interactive validation loop: INSUFFICIENT

Two of the four guarantees are materially reduced. (a) Goal-as-predicate largely holds (one
300s budget, fail-closed selection, additive derivation, five-outcome accounting). (c)
Backstop-with-attribution is the system's strongest property: full tier + canary, escape
attribution via the merged PR's own selection manifest (35 escape-classified recs observed),
and the credential-free-CI budget gap closed into the warehouse. But (b)
optimizer/oracle separation fails at fleet level -- DD-B moves 2/5/7 land undetected, the
pinning tests are same-PR-editable without markers, and the only same-PR guard scans the
retired, empty `scripts/verifiers/` population. And (d) the permanent ratchet is convention,
with observed recurrences (rec-3131 -> rec-3328; the RCA-truncation class five times).
Counter-reading recorded in the YAML: both reductions degrade future recall/permanence rather
than admitting a wrong change green today; weighed heavily, Q1 reads partial.

## Q2 -- standing loops: PARTIAL

All 22 workflows are adjudicated with owner + rationale; excluded rows name their alternative
backstop row by row; the agent fleet is explicitly manifested inert. What fails "every loop
declares": no loop has a *liveness* backstop (a dead cron alarms nothing -- and
convergence-health's cron carries the budget warehouse ingest), stop conditions are scattered
undeclared literals, and terraform-drift's declared re-enable condition has no owner. The
population is mechanically enumerable (P3's premise confirmed -- the census already does it);
judgment was needed only for in-workflow agent invocations and interactive skills.

## Q4 -- external checklist: PARTIAL (1 missed, 6 partial, 2 met)

Met: tier split with escape attribution; budgets with breach telemetry reaching the warehouse
(observed: 4 breaches / 8 bypasses in 7 days, all pytest_diff). Missed: escape-to-artifact
ratcheting (LSA-04). Partial, each with an argued property-matched compensating control: TIA
soundness (closure auditing is advisory; 39/46 gated checks under-declare -- LSA-06, observed,
grown from 33/46, unowned tail); discrimination evidence (real fail-on-revert differentials
for the 475-shard graduated population -- all 5 sampled shards pass the broken-guard
counterfactual -- but nothing for the 114-check fleet, LSA-03); anti-vacuity (met, in fact:
Decision 170 + post-hoc evidence + a ratified-narrow fail-closed alarm); flake policy
(chain-escalation + quarantine built; VF-08's bare re-run gap owned by deferred T3.19);
two-key weakening control (authorization-grade on five surfaces, single-key elsewhere,
LSA-01); cap governance (every loop bounded, caps declared nowhere, LSA-05).

## Deep-dive outcomes in brief

- **DD-B (ten weakening moves):** 6 gated-at-merge, 1 advisory-at-pr, 3 undetected
  (pre-flag demotion on ~78 unpinned entries; mirror-test deletion; sensor-schedule removal).
  The positive control gated as expected. The sharpest pattern: policy files get
  authorization-grade markers; the check fleet's own membership and test substrate get plain
  same-PR-editable test pins or nothing.
- **DD-C (three most recent escapes: rec-3292, rec-3293, rec-3328):** all three are
  environment-class escapes the fast tier structurally cannot catch; detection and no-edge
  attribution worked correctly in all three; zero have a permanent artifact yet; the third is
  a recurrence of a closed rec whose claimed preventive check was never built. The loop's
  detect/attribute legs are healthy; its permanence leg is the gap.
- **Shard samples (5, one per populated slot):** all five would fail if their guarded
  artifact broke; two are pattern-tied (a reworded regression passes); `guard_symbol` is null
  in all five, so T3.7's symbol-level orphan indexing is unused in practice.

## Notable findings

- **LSA-01 (high, novel):** fleet-level verifier weakening is single-key and largely
  undetected; fix is a small extension of the existing marker mechanism.
- **LSA-02 (high, novel):** no sensor-loop liveness backstop; one credentialed last-run-age
  leg on the existing convergence-health cron closes it without new surfaces. This is the
  narrow, buildable slice of the unclosed-loops audit's unadopted "dormant transitions" idea.
- **LSA-04 (high, planned-insufficient, observed):** escape ratcheting by convention fails in
  practice; closure obligation at the portal edge fixes it inside the Decision 55/72 posture.
- **LSA-06 (medium, planned-unbuilt, observed):** the closure auditor's advisory tail is
  unowned and its backlog grew 33/46 -> 39/46 (853 findings); the staged 4b/4c path is moving
  away from its own flip condition.
- **LSA-03 (medium, planned-insufficient)** and **LSA-05 (medium, novel)** complete the set:
  fleet red-case evidence and declared caps.

## Rejected candidates

- **C1 (declaration gap):** dismissed -- the obliged, census-complete declaration surface C1
  says is missing exists for the workflow population (two-way blocking census with owner and
  rationale per row); the genuine residuals are LSA-02 and LSA-05, which are liveness and cap
  defects, not declaration-existence defects.
- **budget-objective-ownership (self-discovered):** dismissed -- the observed breach/bypass
  pressure is being consumed exactly as designed (breach recs, bypass alerts, warehouse
  ingest); the pipeline *is* the 300s re-derivation loop.
- **C5** is adjudicated inside the technique verdicts (confirmed for P1-P3, dismissed for
  P4/P5 in their amended forms).

## Maturity

S1 frontier, S2 strong, S3 frontier, S4 strong, S5 strong, S6 frontier, S7 strong (S8 n/a).
No critical findings anywhere; the three highs (LSA-01/-02/-04) share one theme: this
repository's loops detect and attribute exceptionally well, and ratchet or gate their own
weakening only where a marker or differential was deliberately wired. The adoption answer
follows the same line: build no new declaration surface; wire the two missing enforcement
legs onto the mechanisms already ratified.
