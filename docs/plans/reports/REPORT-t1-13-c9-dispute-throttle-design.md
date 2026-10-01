# REPORT: T1.13 c9 dispute-frequency throttle -- staged design and closeout

> REPORT-ONLY deliverable of `docs/plans/PLAN-t1-13-c9-dispute-throttle-design.yaml` (Decision 86
> cl.2). Stages the throttle that holds T1.13:c9 open (part (a), second conjunct; owner rec-2415),
> the c9 closeout branches and the T1.13 re-grounding, for the operator. Nothing here is built,
> filed, closed, flipped or ratified. Evidence base: origin/main 2349d467 (re-checked unchanged for
> every cited path at e2adb126); live recs read 2026-10-01 via the ducklake-reads named reads
> (`rec_by_id`, `ci_rca_open`).
>
> Gating anchors used below: "parked fork N" means fork N of the Step 6b stand-in report
> `/mnt/project-files/gates/t1-13-c9-step-6b-stand-in-r1.md` (out of repo; project shared folder),
> recorded as the single R5 row of the project MEMORY.md#parked ledger.

## 1. Why this is staged, not built

| # | Fact | Evidence |
|---|---|---|
| F1 | c9's remaining blocker is part (a)'s throttle conjunct; part (c)'s `check_absent` is owned by rec-3666 and does not hold c9 open | roadmap T1.13:c9 text, 2026-09-01 and 2026-09-06 lines ("c9 stays open on part (a)"); PLAN-escape-mode-classifier-repair.yaml:182-184, :946-947 (operator-merged, #1110) |
| F2 | rec-2415 is open and its own context says do NOT build until the gauge shows sustained non-zero dispute traffic; as of 2026-08-27 there were zero `ci_rca_evidence_dispute` rows | live read `rec_by_id rec-2415` (last_updated 2026-08-27T03:07Z); corroborated in-repo by the c9 text's 2026-09-01 block |
| F3 | Dispute traffic is not prompted in warn mode: a cross-check disagreement is logged (the log line still carries the "file a ... dispute rec" text) and the rec files anyway, so nothing pushes an agent to dispute | `config/feature_flags.yaml` (`CI_RCA_STRICT_MODE: warn`); `scripts/ops_portal/ci_rca_runtime.py:311-318` |
| F4 | No automated producer exists: the ci-rca agent never mentions disputes and loads only `--guidance --source ci_rca`; the only text that tells an agent to dispute is the cross-check reject text | `.claude/agents/scheduled/ci-rca.md` (0 matches for "dispute"; :73); `ci_rca_runtime.py:252-253, :265-266, :292` |
| F5 | The operator twice deferred the throttle for want of data | PLAN-ci-rca-evidence-dispute.yaml:217-219 ("explicit human direction"); PLAN-ci-rca-observability-dashboard.yaml:349-351 |
| F6 | Building rec-2415 closes it on merge (Closure Obligation, plan-critique 12k, `Resolves:` trailer), which may be "consuming the recommendation queue" (charter never-list, Decision 67) | planning SKILL.md:390-392; plan-critique SKILL.md:67-70; git-ops.yaml resolves_trailer; parked fork 3 |
| F7 | Where bound 1 lives under Decision 210 has no post-D210 precedent for ops tables | D210 cl.2-3; parked fork 4 |

Consequence: the earliest the throttle can be calibrated is after the c2 strict flip, and even then
only through post-rejection text (F4). In strict mode that text fires after the ci_rca rec was
rejected, i.e. flow B (section 2, assumed_flow), so the reject texts must change before bound 1 can
bite (section 2.3 scope).

## 2. Throttle design (for the future IMPLEMENTATION plan)

```yaml
throttle_design:
  subject: file_rec writes with source=ci_rca_evidence_dispute (the Section-4 check-8 carve-out,
    scripts/ops_data_portal.py:245-266), evaluated after CiRcaEvidenceDispute validation, skipped
    when _migration_mode is set.
  assumed_flow: >-
    A dispute presupposes its parent. parent_rec_id is "the existing source=ci_rca rec whose
    detection_gap cross-check result is being disputed" (scripts/executor/rec_write_guidance.py:
    187-193): flow A (parent filed, then disputed). TODAY the strict reject texts direct flow B
    instead: they raise before any rec is written (ci_rca_runtime.py:314-315) and then tell the agent
    to "file a source=ci_rca_evidence_dispute rec" (:252-253, :265-266, :292). A flow-B dispute usually names a
    parent that does not exist (a same-fingerprint open rec can exist if the CIRCA-03(b) skip failed open
    or force_rca was set), which the schema cannot detect (pattern ^rec-\d+$ only,
    ci_rca_schema.py:213), and two flow-B disputes about one failure can name different ids, so bound 1
    would never match. The design therefore depends on the 2.3 scope row that rewrites those texts to
    "file the bundle-mirroring source=ci_rca rec first, then dispute citing its id" (flow A). Without
    that row bound 1 is ineffective against flow B and only bound 2 remains.
  bound_1:
    rule: reject a dispute when an OPEN ci_rca_evidence_dispute rec already exists with the same
      context_v2_json.parent_rec_id AND disputed_field.
    calibration: none needed (structural), effective only under flow A (assumed_flow).
    marker: "[CI_RCA_DISPUTE_THROTTLE] duplicate open dispute"
  bound_2:
    rule: reject a dispute when the count of ci_rca_evidence_dispute recs with created_timestamp
      inside the rolling window is >= N.
    window_days: 7   # rec-2415's own window
    N: UNSET          # no data (F2-F5); do not choose N against zero traffic
    calibration_trigger: the existing dispute_count gauge (scripts/preflight/ci_rca_gauges.py,
      _compute_ci_rca_telemetry, 7-day window) reporting non-zero counts BEFORE the throttle lands;
      N is set from that series by the implementing plan, never guessed.
    post_landing_recalibration: counts [CI_RCA_DISPUTE_THROTTLE] reject markers, not dispute_count --
      once landed, rejected disputes write no rows and case_parent_open diverts evidence into the
      parent, so dispute_count is censored at N. A reject raises a ValueError and writes nothing, so
      the markers live only in the ci-rca workflow's job logs; the implementing plan either emits a
      structured log line or metric per reject, or the series is counted from CI job logs within
      their retention window. Name which in that plan.
    marker: "[CI_RCA_DISPUTE_THROTTLE] window cap reached"
  keying: rec-2415 says "per agent"; dispute rows carry no agent identity (CiRcaEvidenceDispute,
    scripts/ops_portal/ci_rca_schema.py:206-217), so bound 1 keys on parent_rec_id+disputed_field
    and bound 2 is a global count. State this re-keying in the implementing plan.
  read_shape: make_reader().current_state("ops_recommendations",
    row_filter="source = 'ci_rca_evidence_dispute'"), status / parent / field / window matched
    in-process (Decision 84 I-3, no caller SQL, no new named verb; the shape of
    find_open_ci_rca_rec_by_fingerprint, ci_rca_runtime.py:56-95). Never the read cache. The only
    open status is "open" (do not copy scripts/preflight/ci_rca_signals.py:38's "in_progress").
  egress: one reader call per dispute write; disputes are rare by construction (F3-F4); Decision 88
    invariant (ii) is not engaged (no warm cache on the CI runner).
  fail_closed_contract: any exception on the pre-read rejects the dispute with
    "[CI_RCA_DISPUTE_THROTTLE] reader unreachable; dispute rejected (fail-closed, Decision 55/155);
    retry after the reader recovers". Never import _is_reader_unreachable_error or
    is_reader_unavailable to skip (Decision 155 cl.3: a new skip site needs a new Decision clause).
  degraded_path: >-
    Every reject text, including the fail-closed one, carries BOTH cases verbatim. The portal does not
    select the case: bound 1's read loads dispute rows only, not the parent's source=ci_rca row, and the
    fail-closed reject has no rows at all, so no extra portal read is added. The agent selects, with
    the condition "if parent_rec_id names an open source=ci_rca rec whose context_v2_json.fingerprint
    equals this failure's evidence-bundle fingerprint (check both with the rec_by_id named read)" --
    not "a rec you filed", since under F4 the disputer usually did not file it. The fingerprint is
    portal-stamped from the verified bundle (ci_rca_runtime.py:207-208), so an invented or stale id that
    happens to name an open rec for a different failure fails the condition and routes to
    case_no_parent instead of merging evidence into an unrelated rec.
    case_parent_open: "the parent rec stands as the Decision 73 signal; add this dispute's evidence to
    the parent's context instead of filing a dispute (read-modify-write: update_rec replaces the
    context column, ops_data_portal.py:505)". Do NOT re-file the ci_rca rec: a same-fingerprint re-file
    is deduplicated by the CIRCA-03(c) write-time backstop (ops_data_portal.py:318-338, Decision 142),
    which bumps the parent and returns its id, so any citation in the re-file is lost.
    case_no_parent: "file the source=ci_rca rec clearing cross-checks 1-5 (mirror the bundle's
    earliest_viable_gate and escape_mode; for check-4, set escape_mode=check_ran_vacuously or drop the
    author-discipline attribution) and cite this rejection in its context; if file_rec returns an
    existing open id (the CIRCA-03(c) backstop dedup), follow case_parent_open on that id".
  decision_73_scope: >-
    Outside a reader outage, a throttle reject (bound 1 or bound 2) leaves a path that ends in a rec,
    provided parent_rec_id names this failure's rec (the fingerprint condition above) or the re-file
    clears checks 1-5 and is otherwise schema-valid. "Ends in a rec" includes the lifecycle drop verdict
    (ops_data_portal.py:351-359), which returns a closed head's id without inserting -- by design, for
    stale-code reruns; other strict rejects (S3-missing, bundle-absent, schema deficiencies, the SHA
    mismatch) are unchanged by this design. During a reader outage the case_no_parent re-file
    (closed_head_of_chain, ops_data_portal.py:347 -> ci_rca_lifecycle.py:76, unguarded read) and the
    case_parent_open update_rec read (ops_data_portal.py:499) raise like any ci_rca write, which is why
    the fail-closed text adds the retry clause. This is no guarantee that a main failure always ends
    in a rec; that outage hole exists today for every ci_rca filing.
  existing_hazard_out_of_scope: strict check-3 tells the agent to "file a
    source=ci_rca_evidence_dispute rec" (ci_rca_runtime.py:265-266), but escape_mode is not a
    disputed_field value (ci_rca_schema.py:214), so that dispute is schema-rejected and no rec results.
    A Decision 73 hazard that predates this design; the implementing plan's reject-text row (2.3) or a
    follow-on rec closes it: closed by the 2.3 check-3 row if that plan is adopted, else by a
    follow-on rec at the operator's discretion.
  placement: logic in a new scripts/ops_portal/ submodule (Decision 124 facade pattern); the
    ops_data_portal.py call site must fit the headroom of 500 minus PLAN VP 7's sloc (489 at
    2349d467, no budget entry; Decision 128).
  rationale_home: >-
    Once built, code docstrings by default. A dispute section in docs/contracts/ci-rca-lifecycle.yaml
    (none today) fits only within its headroom: 488 of 500 effective lines at 17e4c25b
    (structural_size_budgets counting rule, contracts class, no budget entry); a larger section needs the Decision 128
    decompose path, never a budget raise. Never a new INTENT doc (Decision 86; the CI-RCA methodology
    INTENT doc was retired by Decision 178).
  acceptance: rec-2415's live acceptance is
    "bin/venv-python -m pytest tests/ops_data_portal/test_ci_rca_dispute.py::TestCiRcaEvidenceDispute::test_dispute_rate_limit_blocks_excess_disputes -q"
    (the test does not exist today); the implementing plan adds it there.
```

### 2.1 Bound 1 home under Decision 210 (PARKED: parked fork 4)

Decision 210 cl.2(a), in full: a cross-row rule is write-owned only if "decidable inside the write's
own transaction, bounded to the batch's partitions, with no extra catalog round-trip", and (b) "its
truth does not depend on the arrival order of independent producers".

| Home | D210 (a) | D210 (b) | Can throttle? | Other cost |
|---|---|---|---|---|
| (i) client-side pre-check in the portal (fingerprint-backstop shape) | fails (extra reader round-trip, outside the transaction) | fails (two concurrent disputes race) | yes | holds only if classified a POLICY rule on agent behaviour, outside D210's row-validity subject; that classification has no precedent; race disclosed as a two-concurrent-disputes window |
| (ii) ducklake_writer transaction | contestable: in-transaction and no extra round-trip, but bound 1 scans all dispute rows and bound 2 a 7-day window, not the batch's partitions (ops_recommendations is partitioned bucket(8, id)) | passes | yes | needs a writer deploy (governed deploy, never-list this week); pre-empts rec-4158's ops single-source choice (D210 cl.3) |
| (iii) DQ monitor | n/a | n/a | no (alarm-not-gate) | requires re-homing c9's conjunct from "throttle" to "monitor" (closeout branch (ii) below) |

Recommended: **(i), OPERATOR-CONFIRM-PENDING.** It is the only home consistent with c9's and
rec-2415's wording and the never-list, and it has an operator-merged in-repo analog (the CIRCA-03(c)
write-time fingerprint backstop). That analog predates D210 and is in rec-4158's coverage, so
rec-4158 may re-home both. Bound 2 rides the same ruling.

### 2.2 rec-2415 spec drift (for the operator, if parked fork 3 is answered "build")

1. Keying: "N disputes per agent per 7d" (filing command, PLAN-ci-rca-evidence-dispute.yaml:198) has
   no agent key to read (section 2, keying).
2. "Mirroring the why_chain_terminus_override rate limit" (same line): no such rate limit exists;
   only a gauge count (ci_rca_gauges.py, `why_chain_terminus_override_count`). rec-2415's live
   context already says so.
3. File pointer (live read, not verifiable from the repo): rec-2415's context cites
   `scripts/ops_data_portal.py:226-244`; the carve-out is now at :245-266.
4. Its acceptance is already the pytest selector in section 2 (live read; re-authored 2026-08-27),
   not the filing-time grep on ops_data_portal.py, so the Decision 124 placement does not affect
   D201 closure.

### 2.3 Implementation outline (gated; not to be started by a delegate)

Gated on parked forks 3 and 4, and on F2's data precondition.

- Scope: scripts/ops_portal/ci_rca_dispute_throttle.py (Create); scripts/ops_data_portal.py (call
  site); scripts/ops_portal/ci_rca_runtime.py (check-2 :252-253 and check-4 :292 reject texts direct flow
  A -- "file the bundle-mirroring rec first, then dispute citing its id"; the check-3 abstention text
  :265-266 drops its dispute clause and says mirror 'undetermined' only, since escape_mode is not
  disputable); scripts/executor/
  rec_write_guidance.py (dispute branch documents both bounds, Decision 66 Tier A);
  tests/ops_data_portal/test_ci_rca_dispute.py (the rec-2415 acceptance test) and a mirror test for
  the new module; rationale per section 2 rationale_home.
- Tier V2; closes_criteria [T1.13:c9]; bundled_recommendations [rec-2415].
- VP: red-before for bound 1, bound 2 and the fail-closed reject; every reject, including the
  fail-closed one, carries both cases verbatim (case_parent_open names the read-modify-write
  update_rec on the parent and never a re-file; case_no_parent names the bundle-mirroring re-file on
  checks 1-5) and the fail-closed text carries the retry clause; case_parent_open's condition requires the
  fingerprint match; the check-2 and check-4 texts each name flow A and the check-3 text carries no
  dispute clause, asserted separately; ops_data_portal.py SLOC <= 500 with no budget entry; zero net-new suppressions. Not a
  registered check, so check_accounting and `examined()` are not involved.

## 3. Staged T1.13 c9 closeout (PARKED: the R5 closeout question)

**Apply-time precondition (sections 3 and 4):** re-run PLAN VP 1-7 immediately before applying;
every expected_literal must match, else follow that step's fix_if. Both branches touch
docs/ROADMAP-PLATFORM.yaml (Lambda-bundled asset, Decision 79/125); regenerate `.secrets.baseline`
in the same commit (a 40-hex met_by or any hex-like string trips detect-secrets).

met_by per exit-criteria-ledger.yaml#fields.met_by (a plan slug or a full 40-hex sha). T1.13 is
non-terminal, so replaced wording may go to progress_note (realized-differently rule). The re-grounded
text below is applied in the SAME staged edit as the flip, never before it
(exit-criteria-ledger.yaml#fields.status), and keeps every still-true conjunct:

> Failure-category integrity + gate-escape modeling. (a) The ci_rca_evidence_dispute disputed_field
> accepts failure_category (scripts/ops_portal/ci_rca_schema.py) and the dispute-frequency throttle is
> enforced on the dispute write path. (b) Priority-0 validation-result attribution outranks the
> step-name/substring ladder, regression-guarded by registry shards
> ci-rca-priority-zero-outranks-step-name, ci-rca-generator-consumes-validation-result and
> ci-rca-validation-result-uploads-always; the test_collection_empty and gate_escape failure
> categories exist (config/ci_rca_taxonomy.yaml). (c) Gate-escape is modeled as the
> detection_gap.escape_mode sub-field, NOT a recurrence_class value; escape_mode is bundle-derived,
> agent-mirrored and portal-cross-checked (bundle-wins) for three of the four escape modes c9 names
> (check_ran_vacuously, tier_misplaced, no_premerge_gate_by_design; undetermined is the abstention
> sentinel); escape-classified recs carry the Decision 186 closure obligation (a fix-bound gate
> artifact at closure, scripts/ops_portal/closure_gate.py), with no_premerge_gate_by_design a waiver
> category, which realizes the original corrective_action fork between the gate-defect modes
> (check_ran_vacuously, tier_misplaced, check_absent) and the by-design canary catch; check_absent is
> owned by rec-3666.

- **Branch (i), throttle lands:** runs through /implement, not a micro-commit. The IMPLEMENTATION
  plan of section 2.3 declares closes_criteria [T1.13:c9]; its bookkeeping walk applies the text
  above and flips c9 met with met_by = that plan's slug, in one staged edit.
- **Branch (ii), re-home the conjunct:** the freshness gate's "own micro-commit on human
  confirmation" branch, and an OPERATOR-CONFIRMED EXCEPTION to the /implement-only flip rule
  (exit-criteria-ledger.yaml#fields.met_by, "Never flip a criterion not named in
  closes_criteria"). The operator moves part (a)'s throttle conjunct out of c9 (to rec-2415 alone --
  re-check it is still open with `rec_by_id` first -- or to a new criterion), applies the text above
  without the throttle clause, and flips c9 met with met_by = `escape-mode-classifier-repair` (the
  plan that realized the last surviving part; docs/plans/PLAN-escape-mode-classifier-repair.yaml).
  Fallback form: the full 40-hex sha of that plan's squash commit,
  8741871b84713f88737ac9c4336bbee12e6198d4 (#1110). Never the sha of
  the bookkeeping commit itself (a commit cannot carry its own sha, and a branch-local sha never
  reaches squash-merged main).

## 4. Staged T1.13 re-grounding (freshness gate check 2; PARKED with the closeout)

Same apply-time precondition as section 3. All 11 files_in_scope paths exist: no files_in_scope
change. c9's own text cites no retired path. Retired-path citations (docs/INTENT-*.md,
docs/intent-migration/MANIFEST.yaml) elsewhere in T1.13:

| Where | Current text (abridged) | Staged disposition |
|---|---|---|
| c2 text | "after Phase 4 back-validation per docs/INTENT-ci-rca-methodology.md Section 6" | replace with "after Phase 4 back-validation (back_validate_ci_rca, scripts/ops_portal/ci_rca_runtime.py; CLI --back-validate) has run and its report is reviewed at /plan" (keeps the retired Section 6's review condition) |
| note (two citations) | "See docs/INTENT-ci-rca-methodology.md 'Follow-on plans'" and "Plans AMEND the grandfathered docs/INTENT-ci-rca-methodology.md" | append one dated line, carrying no retired path: "2026-10-01: the CI-RCA methodology INTENT doc cited above was retired by Decision 178 (7b67e21d); CI-RCA semantics now live in docs/contracts/ci-rca-lifecycle.yaml and code." |
| progress_note (2026-06-30 MANIFEST cross-link; 2026-07-01 bucket-name correction; 2026-07-04 Section 7 amendment) | dated history | left as is: progress_note is history, stripped at completion (tier-item-lifecycle.yaml#completion_compaction) |
| met c7, c10, c11 text; `related_intents: [ci-rca-methodology]` | met-criterion history; a roadmap-wide slug convention | left as is: met criteria are not re-adjudicated by this slice, and related_intents is not a path |

## 5. Decision 73 halt check

`ci_rca_open` via the ducklake-reads named read returned zero rows at about 17:58Z on 2026-10-01 (the
first call timed out at 60s; the retry answered). Preflight in the same sandbox still reported
`recs_read_status=reader_unreachable`.
