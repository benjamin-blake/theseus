# REPORT: T1.13 c9 dispute-frequency throttle -- staged design and closeout

> REPORT-ONLY deliverable of `docs/plans/PLAN-t1-13-c9-dispute-throttle-design.yaml` (Decision 86
> cl.2). Stages the throttle that holds T1.13:c9 open (part (a), second conjunct; owner rec-2415),
> the c9 closeout branches and the T1.13 re-grounding, for the operator. Nothing here is built,
> filed, closed, flipped or ratified. Evidence base: origin/main 2349d467; live recs read
> 2026-10-01 via the ducklake-reads named reads (`rec_by_id`, `ci_rca_open`).

## 1. Why this is staged, not built

| # | Fact | Evidence |
|---|---|---|
| F1 | c9's remaining blocker is part (a)'s throttle conjunct; part (c)'s `check_absent` is owned by rec-3666 and does not hold c9 open | roadmap T1.13:c9 text, 2026-09-01 and 2026-09-06 lines ("c9 stays open on part (a)"); PLAN-escape-mode-classifier-repair.yaml:182-184, :946-947 (operator-merged, #1110) |
| F2 | rec-2415 is open and its own context says do NOT build until the gauge shows sustained non-zero dispute traffic; as of 2026-08-27 there were zero `ci_rca_evidence_dispute` rows | `rec_by_id rec-2415` (last_updated 2026-08-27T03:07Z) |
| F3 | Dispute traffic cannot accrue in warn mode: a cross-check disagreement is logged and the rec files anyway | `config/feature_flags.yaml` (`CI_RCA_STRICT_MODE: warn`); `scripts/ops_portal/ci_rca_runtime.py:311-318` |
| F4 | No automated producer exists: the ci-rca agent never mentions disputes and loads only `--guidance --source ci_rca` | `.claude/agents/scheduled/ci-rca.md` (0 matches for "dispute"; :73) |
| F5 | The operator twice deferred the throttle for want of data | PLAN-ci-rca-evidence-dispute.yaml:217-219 ("explicit human direction"); PLAN-ci-rca-observability-dashboard.yaml:349-351 |
| F6 | Building rec-2415 closes it on merge (Closure Obligation, plan-critique 12k, `Resolves:` trailer), which may be "consuming the recommendation queue" (charter never-list, Decision 67) | planning SKILL.md:390-392; plan-critique SKILL.md:67-70; git-ops.yaml resolves_trailer; MEMORY.md#parked R5 fork 3 |
| F7 | Where bound 1 lives under Decision 210 has no post-D210 precedent for ops tables | D210 cl.2-3; MEMORY.md#parked R5 fork 4 |

Consequence: the earliest the throttle can be calibrated is after the c2 strict flip, and even then
only through post-rejection text (F4). Bound 1 below needs no calibration; bound 2 does.

## 2. Throttle design (for the future IMPLEMENTATION plan)

```yaml
throttle_design:
  subject: file_rec writes with source=ci_rca_evidence_dispute (the Section-4 check-8 carve-out,
    scripts/ops_data_portal.py:248-264), evaluated after CiRcaEvidenceDispute validation, skipped
    when _migration_mode is set.
  bound_1:
    rule: reject a dispute when an OPEN ci_rca_evidence_dispute rec already exists with the same
      context_v2_json.parent_rec_id AND disputed_field.
    calibration: none needed (structural).
    marker: "[CI_RCA_DISPUTE_THROTTLE] duplicate open dispute"
  bound_2:
    rule: reject a dispute when the count of ci_rca_evidence_dispute recs with created_timestamp
      inside the rolling window is >= N.
    window_days: 7   # rec-2415's own window
    N: UNSET          # no data (F2-F5); do not choose N against zero traffic
    recalibration_trigger: the existing dispute_count gauge (scripts/preflight/ci_rca_gauges.py,
      _compute_ci_rca_telemetry, 7-day window) reporting non-zero counts; N is set from that series
      by the implementing plan, never guessed.
    marker: "[CI_RCA_DISPUTE_THROTTLE] window cap reached"
  keying: rec-2415 says "per agent"; dispute rows carry no agent identity (CiRcaEvidenceDispute,
    scripts/ops_portal/ci_rca_schema.py:206-217), so bound 1 keys on parent_rec_id+disputed_field
    and bound 2 is a global count. State this re-keying in the implementing plan.
  read_shape: make_reader().current_state("ops_recommendations",
    row_filter="source = 'ci_rca_evidence_dispute'"), status / parent / field / window matched
    in-process (Decision 84 I-3, no caller SQL, no new named verb; the shape of
    find_open_ci_rca_rec_by_fingerprint, ci_rca_runtime.py:56-95). Never the read cache.
  egress: one reader call per dispute write; disputes are rare by construction (F3-F4); Decision 88
    invariant (ii) is not engaged (no warm cache on the CI runner).
  fail_closed_contract: any exception on the pre-read rejects the dispute with
    "[CI_RCA_DISPUTE_THROTTLE] reader unreachable; dispute rejected (fail-closed, Decision 55/155)".
    Never import _is_reader_unreachable_error or is_reader_unavailable to skip (Decision 155 cl.3:
    a new skip site needs a new Decision clause).
  assumed_flow: a dispute presupposes its parent. parent_rec_id is "the existing source=ci_rca rec
    whose detection_gap cross-check result is being disputed" (scripts/executor/rec_write_guidance.py:
    187-193), so the design assumes flow A (parent filed, then disputed). Flow B (strict cross-check
    rejects the ci_rca rec, then a dispute is attempted) has no parent to name: the schema checks only
    the ^rec-\d+$ pattern (ci_rca_schema.py:213), so a flow-B dispute would name a rec that does not
    exist, which the schema cannot detect.
  degraded_path: every reject text carries a two-case instruction, keyed on whether parent_rec_id names
    an OPEN source=ci_rca rec (the same reader rows bound 1 already loaded):
    case_parent_open: "the parent rec stands as the Decision 73 signal; append this dispute's evidence to
      it via update_rec instead of filing a dispute". Do NOT re-file the ci_rca rec: a same-fingerprint
      re-file is deduplicated by the CIRCA-03(c) write-time backstop (scripts/ops_data_portal.py:318-338,
      Decision 142), which bumps the parent and returns its id, so any citation in the re-file is lost.
    case_no_parent: "file the source=ci_rca rec mirroring the bundle's value for the disputed field
      (bundle-authoritative) and cite this rejection in its context". A bundle-mirroring rec passes the
      strict cross-check (ci_rca_runtime.py:311-315), so a main failure always ends with a rec; if an open
      rec with the same fingerprint exists the backstop dedups to it, which is case_parent_open.
    Either way a dispute reject can never leave a main failure with no rec (Decision 73 cl.3). Warn mode
    is unaffected (the rec files anyway).
  placement: logic in a new scripts/ops_portal/ submodule (Decision 124 facade pattern); the
    ops_data_portal.py call site stays within its 11-SLOC headroom (489 of 500, no budget entry;
    Decision 128).
  rationale_home: once built, a dated amendment adding a dispute section to
    docs/contracts/ci-rca-lifecycle.yaml (none today) or code docstrings; never a new INTENT doc
    (Decision 86; docs/INTENT-ci-rca-methodology.md was retired by Decision 178).
  acceptance: rec-2415's live acceptance is
    "bin/venv-python -m pytest tests/ops_data_portal/test_ci_rca_dispute.py::TestCiRcaEvidenceDispute::test_dispute_rate_limit_blocks_excess_disputes -q"
    (the test does not exist today); the implementing plan adds it there.
```

### 2.1 Bound 1 home under Decision 210 (PARKED: MEMORY.md#parked R5 fork 4)

Decision 210 cl.2 makes a cross-row rule write-owned only if it is (a) decidable inside the write's
own transaction with no extra catalog round-trip and (b) independent of producer arrival order.

| Home | D210 (a) | D210 (b) | Can throttle? | Other cost |
|---|---|---|---|---|
| (i) client-side pre-check in the portal (fingerprint-backstop shape) | fails (extra reader round-trip) | fails (two concurrent disputes race) | yes | holds only if classified a POLICY rule on agent behaviour, outside D210's row-validity subject; that classification has no precedent; race disclosed as a two-concurrent-disputes window |
| (ii) ducklake_writer transaction | passes | passes | yes | needs a writer deploy (governed deploy, never-list this week); pre-empts rec-4158's ops single-source choice (D210 cl.3) |
| (iii) DQ monitor | n/a | n/a | no (alarm-not-gate) | requires re-homing c9's conjunct from "throttle" to "monitor" (closeout branch (ii) below) |

Recommended: **(i), OPERATOR-CONFIRM-PENDING.** It is the only home consistent with c9's and
rec-2415's wording and the never-list, and it has an operator-merged in-repo analog (the CIRCA-03(c)
write-time fingerprint backstop). That analog predates D210 and is in rec-4158's coverage, so
rec-4158 may re-home both. Bound 2 rides the same ruling.

### 2.2 rec-2415 spec drift (for the operator, if fork 3 is answered "build")

1. Keying: "N disputes per agent per 7d" has no agent key to read (section 2, keying).
2. "Mirroring the why_chain_terminus_override rate limit": no such rate limit exists; only a gauge
   count (ci_rca_gauges.py, `why_chain_terminus_override_count`). rec-2415's context already says so.
3. File pointer: rec-2415 cites `scripts/ops_data_portal.py:226-244`; the carve-out is now at :248-264.
4. Its acceptance is already the pytest selector in section 2 (re-authored 2026-08-27), not the
   earlier grep on ops_data_portal.py, so the Decision 124 placement does not affect D201 closure.

### 2.3 Implementation outline (gated; not to be started by a delegate)

Gated on MEMORY.md#parked rows R5 fork 3 and R5 fork 4, and on F2's data precondition.

- Scope: scripts/ops_portal/ci_rca_dispute_throttle.py (Create); scripts/ops_data_portal.py (call
  site); scripts/executor/rec_write_guidance.py (dispute branch documents both bounds, Decision 66
  Tier A); tests/ops_data_portal/test_ci_rca_dispute.py (the rec-2415 acceptance test) and a mirror
  test for the new module; docs/contracts/ci-rca-lifecycle.yaml (dispute section).
- Tier V2; closes_criteria [T1.13:c9]; bundled_recommendations [rec-2415].
- VP: red-before for bound 1, bound 2 and the fail-closed reject; the degraded-path text asserted on
  every reject in both cases (case_parent_open names update_rec on the parent and never a re-file;
  case_no_parent names the bundle-mirroring re-file); ops_data_portal.py SLOC <= 500 with no budget entry; zero net-new suppressions.
  Not a registered check, so check_accounting and `examined()` are not involved.

## 3. Staged T1.13 c9 closeout (PARKED: MEMORY.md#parked R5 closeout)

Contract branch: tier-item-lifecycle.yaml#tier_item_freshness_gate output discipline, "its own
micro-commit on human confirmation". T1.13 is non-terminal, so replaced wording goes to
progress_note. met_by per exit-criteria-ledger.yaml#fields.met_by (plan slug or full 40-hex sha).

- **Branch (i), throttle lands:** the IMPLEMENTATION plan of section 2.3 declares closes_criteria
  [T1.13:c9]; /implement flips c9 met with met_by = that plan's slug. Before the flip, c9's text is
  re-grounded so it adjudicates true (realized-differently rule):
  > Failure-category integrity + gate-escape modeling. (a) disputed_field accepts failure_category
  > (scripts/ops_portal/ci_rca_schema.py) and the dispute-frequency throttle is enforced on the
  > dispute write path (met_by plan). (b) Priority-0 validation-result attribution outranks the
  > step-name/substring ladder, regression-guarded by registry shards
  > ci-rca-priority-zero-outranks-step-name, ci-rca-generator-consumes-validation-result,
  > ci-rca-validation-result-uploads-always. (c) escape_mode is bundle-derived, agent-mirrored and
  > portal-cross-checked for three of four values (check_ran_vacuously, tier_misplaced,
  > no_premerge_gate_by_design); check_absent is owned by rec-3666.
- **Branch (ii), re-home the conjunct:** the operator moves part (a)'s throttle conjunct out of c9
  (to rec-2415 alone, or to a new criterion), re-grounds c9's text as above without the throttle
  clause, and flips c9 met with met_by = the full 40-hex sha of that bookkeeping commit. This is a
  criterion rewrite plus flip: operator-only.

## 4. Staged T1.13 re-grounding (freshness gate check 2; PARKED with the closeout)

All 11 files_in_scope paths exist at 2349d467: no files_in_scope change. c9's own text cites no
retired path. Retired references remain in c2's text, in the note (two citations), and in historical
progress_note entries (three INTENT-doc citations plus the MANIFEST cross-link, left as is):

| Where | Current text (abridged) | Staged replacement |
|---|---|---|
| c2 text | "after Phase 4 back-validation per docs/INTENT-ci-rca-methodology.md Section 6" | "after Phase 4 back-validation (back_validate_ci_rca, scripts/ops_portal/ci_rca_runtime.py; CLI --back-validate)" |
| note (two citations) | "See docs/INTENT-ci-rca-methodology.md 'Follow-on plans'" and "Plans AMEND the grandfathered docs/INTENT-ci-rca-methodology.md" | append one dated line: "2026-10-01: docs/INTENT-ci-rca-methodology.md was retired by Decision 178 (7b67e21d); CI-RCA semantics now live in docs/contracts/ci-rca-lifecycle.yaml and code." |
| progress_note (2026-06-30 MANIFEST cross-link; 2026-07-01 bucket-name correction; 2026-07-04 Section 7 amendment) | dated history citing docs/INTENT-ci-rca-methodology.md and docs/intent-migration/MANIFEST.yaml | historical entries, left as is; the note's dated line above covers them (Decision 147 compact storage) |

Applying this edit is a roadmap change (Lambda-bundled asset, Decision 79/125; regenerate
`.secrets.baseline` in the same commit) and rides the operator's closeout row.

## 5. Decision 73 halt check

`ci_rca_open` via the ducklake-reads named read returned zero rows at about 17:58Z on 2026-10-01 (the
first call timed out at 60s; the retry answered). Preflight in the same sandbox still reported
`recs_read_status=reader_unreachable`.
