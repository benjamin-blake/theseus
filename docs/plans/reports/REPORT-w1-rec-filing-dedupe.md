# REPORT: W1 component 5 - rec filing with dedupe against open recs

REPORT-ONLY (Decision 86 cl.2). Planning artefact: `docs/plans/PLAN-w1-rec-filing-dedupe.yaml`.
Fixture rows: `pwi-rec-filing-dedupe` in `docs/work-item-pilot/telemetry-feedback-loop.yaml`
(CD.45 pilot, provisional_v0). Nothing is built, filed, updated, closed, flipped or ratified here; no
rec was written while preparing it (Decision 67). Every rec operation below is a description.

## 0. Verdict

- The component is a deterministic DECISION over the filer's own recs, not a similarity search. T3.3
  must file anomaly recs and T3.4 needs "rec filed -> ... -> telemetry delta proves fix"
  (ROADMAP-PLATFORM.yaml:6579, :6593), yet nothing turns a telemetry or friction finding into a rec.
  The design stages one SQL statement that, per finding, picks one of ten actions (file, update,
  unchanged, regression, drop, covered, suppressed, unresolved, over_budget, hold) and passes 25 of 25
  hand-written vectors on DuckDB (VP 2). Seventeen mutants were run once by hand; each fails a named vector.
- The repo already has four dedupe mechanisms, and none fits as is (VP 1, VP 3, VP 4):
  - `rec_episode.run_episode`, the shared monitor primitive, keys on SOURCE alone. Over live code, a
    second subject on the same source updates the first subject's rec; a declined head is invisible
    (find_recs keeps status open only), so a declined finding re-files; and below threshold it closes the
    open rec with no proof (VP 1).
  - The relevance evaluator's open_duplicate signal is title Jaccard >= 0.7, composed queue-wide by
    backlog_health. Two templated filer titles for DIFFERENT findings score 0.82 and read as duplicates,
    while a paraphrased title for the SAME problem scores 0.00 (VP 3; that title is constructed for the
    probe, and the nearest live open rec on the same hook, rec-4118, scores 0.03). Title similarity is wrong
    in both directions for a templated filer.
  - backlog_health files one aggregate rec per detector with the finding ids in context_v2_json
    (rec-3702 carries 221 ids). One rec cannot be closed by one fix, so T3.4's per-subject "delta proves
    fix" cannot read it.
  - ci_rca's fingerprint v2 chain (Decision 142) is the right model: a code-computed fingerprint in
    context_v2_json (no new Class A column, VP 4), the newest record in the chain is the head, only an
    open head is bumped, a closed head is never reopened, a recurrence after the fix files a new
    regression rec. Its write-time backstop is wired for source ci_rca only (ops_data_portal.py:315).
  The design reuses the ci_rca model, generalised to a detector-agnostic finding, and adds what a
  telemetry filer needs that ci_rca does not: an idempotent window rule, decline handling, a typed link
  to a covering rec from another source, a hold below the filing floor, and a per-run filing budget.
- Dedupe against OTHER sources' open recs cannot be decided from content without an LLM or a similarity
  score, and both are rejected above (Decision 55: dedup decisions in code; rec-2591's Haiku judge is
  put off until evidence justifies it, and it spends). The design makes the cross-source link explicit and typed: the operator marks a
  filer rec `superseded` with `covered_by: rec-N`, and the filer follows that pointer (action covered
  while rec-N is open, regression or drop by the time rule once rec-N closes). Where the link lives is
  contested and parked (k1). This is also where the retired transcript-review prompt's missing-gotcha
  pattern lands, as the friction report asked (its section 2 table).
- The filer never closes a rec. Below the floor is `hold`, not close. Closure needs a recorded proof
  (Decision 103), and that proof is back-validation's (T3.4, a later W1 component).
- The queue is already 5x over its soft cap: 1244 of 1419 open recs are non-automatable against
  `_NON_AUTOMATABLE_SOFTCAP = 250` (measured, section 1). The item starts at the read_all rung, where the
  filer files nothing and every proposal is reviewed; whether the cap stops filing later is parked (k3).
- One item fits the clause-3 grain (kind task; three criteria; part_of T3.3, depends_on T2.36).

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | T3.3 exit criteria: the agent "files anomaly recs via log-rec"; its false-positive rate threshold is undefined (audit F-035). T3.4: "Anomaly detected -> rec filed -> priority queued -> ... -> telemetry delta proves fix" | docs/ROADMAP-PLATFORM.yaml:6579-6580, :6593 |
| e2 | find_recs keeps rows whose status equals the requested status (default open), so a declined, superseded or closed head is never seen by run_episode [VP 1] | scripts/rec_episode.py:97 |
| e3 | decide() returns close when below threshold with an open rec; run_episode then calls update_rec to close it [VP 1] | scripts/rec_episode.py:149-150, :227-234 |
| e4 | rec_episode keys on source alone unless the caller passes a sub_key predicate; budget_breach is the one caller that does [VP 1] | scripts/rec_episode.py:100-133; scripts/checks/_budget_recs.py:145 |
| e5 | open_duplicate: another open rec with title Jaccard >= 0.7, file compared only when both recs carry one [VP 3] | scripts/rec_relevance.py:158-168 |
| e6 | backlog_health composes that evaluator over every open rec each episode | scripts/backlog_health/classify.py:124-126 |
| e7 | ci_rca fingerprint: sha256 over a scheme salt and cause fields, run-invariant; newest-first chain; only an open head is bumped; a closed head is never reopened; recurrence after the fix is a new REGRESSION rec with regression_of | docs/contracts/ci-rca-lifecycle.yaml:119-124, :153-171 |
| e8 | ci_rca's fingerprint and every dedup decision are computed in code, never by the LLM (Decision 55) | docs/contracts/ci-rca-lifecycle.yaml:396 |
| e9 | The write-time dedup backstop (bump the open match, return its id, insert nothing) runs only for source ci_rca | scripts/ops_data_portal.py:315-332 |
| e10 | ops_recommendations has no fingerprint column; context_v2_json is a nullable string whose shape is unvalidated; ci_rca keeps its fingerprint there [VP 4] | docs/contracts/ops_recommendations.yaml:534-545; docs/contracts/ci-rca-lifecycle.yaml:75-78 |
| e11 | The open_recs named read projects id, title, context, created_timestamp and automatable only: no source, status, file or context_v2_json [VP 4] | src/common/ducklake_scd2_schema.py:348-350 |
| e12 | No telemetry filer source is registered; transcript-review (the retired friction prompt's source) still is [VP 4] | config/agent/data_quality/source_registry.yaml:43 |
| e13 | Decision 103: semantic verdicts (duplicate, superseded) produce close_proposed for human or policy confirmation, never a direct close | docs/DECISIONS.md:6739-6741 |
| e14 | Non-automatable open-rec soft cap is 250 [VP 4] | scripts/preflight/_common.py:25 |
| e15 | rec-2952 (open): a machine filer (reconcile_starved) calls file_rec unconditionally and "would file N recs" during one outage; rec-2591 (open; its context puts it off until evidence justifies it): a Haiku dedup judge on fingerprint collision; rec-3702 (open): backlog_health's aggregate rec over 221 ids | rec_by_id reads (status open) |

Measured (live reads, counts only; no rec content is reproduced and nothing was written):

- Decision table: the SQL in section 2 passes 25 of 25 vectors, and DuckDB's `sha256` over the salted,
  NUL-joined key equals Python's `hashlib.sha256` (fingerprint parity, so the in-code key and the SQL
  key agree) [VP 2]. Seventeen mutants were run once by hand, not as a VP step; each fails the vectors
  named: a string-sorted chain head (v17), no window idempotence (v05), an unknown close time dropping
  instead of failing closed (v09), detector_version folded into the fingerprint (v18 alone when heads are
  hashed at the filing version, per verification r1; every vector with a head when they are hashed
  without one), no detector_id in the fingerprint (v19), the cover pointer returned for a closed head
  (v22), no collapse of one fingerprint's findings within a run (v25), a deferred head suppressed (v23), a
  deferred cover unresolved (v24), updates counted against the budget (v21), regressions exempt from the
  budget (v21), a dangling cover suppressed instead of unresolved (v15), a declined or bare-superseded
  head re-filing as rec_episode does (v10, v14), the two floors joined by OR (v01, v02), a closed covering
  rec still read as covered (v12, v13), the budget keeping the smallest findings (v20, v21) and any head
  status updating (twelve vectors, v07-v15, v21, v22 and v24).
- Queue state (named reads `count_by_status` and `open_recs`, 2026-10-03 about 07:35Z): 1419 open,
  1188 closed, 183 superseded, 72 declined; of the open, 1244 non-automatable and 175 automatable.
  That is 4.98 times the soft cap (e14). rec-3702's own monitor counts 196 open recs that are premise-dead
  or a near-duplicate of another open rec, so queue noise is an existing cost, not a hypothetical.
- Source scope: a `current_state` read scoped to source telemetry-audit returned 15 recs; scoped to
  transcript-review it returned 0. The retired friction prompt left no recs to dedupe against.

## 2. Filing design (what this item stages)

Input is a FINDING, never a raw row and never a single session: one row per (detector_id, subject_key)
per window, produced by a detector verb from derived counts only. First detectors: the friction
classifier's per-label counts (W1-3, subject `label` or `label:tool`), the deliberation drift share (W1-4)
and the friction coverage share (unmapped_failure_share); T3.3's anomaly detectors later. Columns:
detector_id, detector_version (classifier_version or equivalent), subject_key (closed per detector),
window_start, window_end, sessions (distinct sessions) and events.

Identity: `fingerprint = sha256(salt NUL detector_id NUL subject_key)`, computed in code (e8), stored in
the filer rec's context_v2_json with detector_id, subject_key, occurrence_count, last_seen_end and, when
set, regression_of or covered_by. detector_version is NOT in the key: a rules edit must not re-file every
open finding (v18); the version rides in the run record and the update. The salt versions the key scheme
the way ci_rca's "v2" does. One registered filer source holds every detector (one source plus a
fingerprint, the Decision 142 shape), so one scoped `current_state` read per run returns the whole chain
set; never the open_recs bulk read, which lacks source and context_v2_json (e11, the rec-3291 defect
class).

Params are data, stamped as `params_version` in every run record (seed values, all unmeasured, q3):

```yaml
params_version: 1
salt: tfl-v1
min_sessions: 3
min_events: 5
window_days: 7
file_budget: 3
```

The decision, verified against the vectors below (VP 2). `{findings}` is one run's findings;
`{heads}` is the filer source's recs projected to rec_id, fingerprint, status, covered_by, closed_at (the
closing update's time), last_seen_end and created; `{targets}` is one `rec_by_id` read per distinct
covered_by id, projected to rec_id, status and closed_at. Placeholders render from the params block.
Precondition handled in `f`: one finding per fingerprint per run; a catch-up run that yields two windows
for one fingerprint keeps the latest (v25), so one run can never file twice. A rec_id with no trailing
digits makes the chain-order CAST raise; that is deliberate (fail loud, Decision 55) and the build keeps
it so:

```sql
WITH f AS (
  SELECT *, sha256('{salt}' || chr(0) || detector_id || chr(0) || subject_key) AS fingerprint,
         sessions >= {min_sessions} AND events >= {min_events} AS fileable
  FROM {findings}
  QUALIFY row_number() OVER (PARTITION BY fingerprint ORDER BY window_end DESC, window_start DESC, sessions DESC) = 1
),
head AS (
  SELECT * FROM (
    SELECT *, row_number() OVER (PARTITION BY fingerprint
             ORDER BY created DESC, CAST(regexp_extract(rec_id, '([0-9]+)$', 1) AS BIGINT) DESC) AS rk
    FROM {heads}) WHERE rk = 1
),
j AS (
  SELECT f.detector_id, f.subject_key, f.fingerprint, f.fileable, f.window_start, f.window_end, f.sessions,
         h.rec_id AS head_id, h.status AS head_status, h.covered_by, h.closed_at AS head_closed_at,
         h.last_seen_end, t.rec_id AS target_id, t.status AS target_status, t.closed_at AS target_closed_at
  FROM f LEFT JOIN head h ON h.fingerprint = f.fingerprint
  LEFT JOIN {targets} t ON t.rec_id = h.covered_by
),
d AS (
  SELECT *,
    CASE
      WHEN NOT fileable THEN 'hold'
      WHEN head_id IS NULL THEN 'file'
      WHEN head_status IN ('open', 'in_progress', 'deferred') THEN
        CASE WHEN last_seen_end IS NULL OR window_end > last_seen_end THEN 'update' ELSE 'unchanged' END
      WHEN head_status = 'closed' THEN
        CASE WHEN head_closed_at IS NULL OR window_start > head_closed_at THEN 'regression' ELSE 'drop' END
      WHEN head_status = 'superseded' AND covered_by IS NOT NULL THEN
        CASE
          WHEN target_status IN ('open', 'in_progress', 'deferred') THEN 'covered'
          WHEN target_status = 'closed' THEN
            CASE WHEN target_closed_at IS NULL OR window_start > target_closed_at THEN 'regression' ELSE 'drop' END
          WHEN target_status = 'declined' THEN 'suppressed'
          ELSE 'unresolved'
        END
      ELSE 'suppressed'
    END AS action
  FROM j
),
r AS (
  SELECT *,
    CASE WHEN action IN ('file', 'regression')
         THEN row_number() OVER (PARTITION BY action IN ('file', 'regression') ORDER BY sessions DESC, fingerprint) END AS nth
  FROM d
)
SELECT detector_id, subject_key,
       CASE WHEN nth > {file_budget} THEN 'over_budget' ELSE action END AS action,
       CASE
         WHEN action IN ('hold', 'file') OR nth > {file_budget} THEN NULL
         WHEN head_status = 'superseded' AND covered_by IS NOT NULL AND action IN ('covered', 'regression', 'drop', 'unresolved') THEN covered_by
         ELSE head_id
       END AS ref
FROM r
```

What each action does, as the build would wire it (none of it runs here):

| action | when | write (described only) | ref |
|---|---|---|---|
| hold | below either floor | none | - |
| file | fileable, no chain head | file_rec: templated title and context, context_v2_json identity, source priority | - |
| update | open, in_progress or deferred head, window advanced (a deferred rec is parked, not resolved: v23) | update_rec on the head: occurrence_count + 1, last_seen_end, detector_version, latest counts | head |
| unchanged | same head, window not advanced (re-run) | none | head |
| regression | closed head, or a superseded head's closed cover, and the window starts after that close, or the close time is unknown (fail closed) | file_rec: "REGRESSION: " prefix, regression_of = ref, priority one step up | the rec whose close decided it: head when the head is closed (even if it still carries covered_by, v22), cover only for a superseded head |
| drop | the window still includes sessions from before that close | none; logged | as for regression |
| covered | superseded head whose covered_by rec is open, in_progress or deferred (v24) | none | cover |
| suppressed | declined head, superseded head with no cover, or a declined cover | none; counted with its sessions | head |
| unresolved | covered_by names a rec the read cannot resolve or that is itself superseded | none; listed for triage | cover |
| over_budget | a file or regression past the run's file_budget, smallest sessions first (named apart from the rec status deferred) | none; refiles next run if still fileable | - |

Every run writes one run record (counts per action, params_version, the detector versions, and the
fingerprints with sessions per suppressed, unresolved and over_budget finding), so nothing the filer declines
to file is silent (Decision 55: dedup never swallows a finding). The filer never calls update_rec to close:
a filer rec closes only through back-validation's proof (T3.4) or a human. A concurrent second run is
prevented by a schedule concurrency group and caught by the generalised write-time backstop (R2).

Vectors (hand-written for this report; VP 2 runs every one). findings rows are `[detector_id,
detector_version, subject_key, window_start, window_end, sessions, events]`; heads rows are `[rec_id,
detector_id, subject_key, status, covered_by, closed_at, last_seen_end, created]` (the harness computes each
head's fingerprint in Python from detector_id and subject_key); targets rows are `[rec_id, status,
closed_at]`; times are day numbers; `expected` lists `[detector_id, subject_key, action, ref]`:

```yaml
vectors:
  - id: v01-below-session-floor-holds
    findings: [[friction, 1, 'tool_error:Bash', 1, 7, 2, 40]]
    heads: []
    targets: []
    expected: [[friction, 'tool_error:Bash', hold, null]]
  - id: v02-below-event-floor-holds
    findings: [[friction, 1, 'tool_error:Bash', 1, 7, 3, 4]]
    heads: []
    targets: []
    expected: [[friction, 'tool_error:Bash', hold, null]]
  - id: v03-new-fingerprint-files
    findings: [[friction, 1, 'tool_error:Bash', 1, 7, 3, 5]]
    heads: []
    targets: []
    expected: [[friction, 'tool_error:Bash', file, null]]
  - id: v04-open-head-advanced-window-updates
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', open, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-100]]
  - id: v05-same-window-rerun-is-unchanged
    findings: [[friction, 1, 'tool_error:Bash', 1, 7, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', open, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', unchanged, rec-100]]
  - id: v06-in-progress-head-updates
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', in_progress, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-100]]
  - id: v07-recurs-after-close-is-regression
    findings: [[friction, 1, 'tool_error:Bash', 11, 17, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', closed, null, 10, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', regression, rec-100]]
  - id: v08-window-spanning-the-close-drops
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', closed, null, 10, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', drop, rec-100]]
  - id: v09-close-time-unknown-fails-closed-to-regression
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', closed, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', regression, rec-100]]
  - id: v10-declined-head-suppresses
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 9, 30]]
    heads: [[rec-100, friction, 'tool_error:Bash', declined, null, 5, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', suppressed, rec-100]]
  - id: v11-covered-by-open-rec-writes-nothing
    findings: [[friction, 1, 'unmapped_block:PreToolUse.Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'unmapped_block:PreToolUse.Bash', superseded, rec-50, 6, 7, 1]]
    targets: [[rec-50, open, null]]
    expected: [[friction, 'unmapped_block:PreToolUse.Bash', covered, rec-50]]
  - id: v12-recurs-after-covering-fix-is-regression
    findings: [[friction, 1, 'unmapped_block:PreToolUse.Bash', 11, 17, 4, 9]]
    heads: [[rec-100, friction, 'unmapped_block:PreToolUse.Bash', superseded, rec-50, 6, 7, 1]]
    targets: [[rec-50, closed, 10]]
    expected: [[friction, 'unmapped_block:PreToolUse.Bash', regression, rec-50]]
  - id: v13-window-spanning-covering-fix-drops
    findings: [[friction, 1, 'unmapped_block:PreToolUse.Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'unmapped_block:PreToolUse.Bash', superseded, rec-50, 6, 7, 1]]
    targets: [[rec-50, closed, 10]]
    expected: [[friction, 'unmapped_block:PreToolUse.Bash', drop, rec-50]]
  - id: v14-superseded-without-cover-suppresses
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', superseded, null, 6, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', suppressed, rec-100]]
  - id: v15-dangling-cover-is-unresolved-not-silent
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', superseded, rec-50, 6, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', unresolved, rec-50]]
  - id: v16-newest-head-wins-the-chain
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', declined, null, 3, 2, 1], [rec-120, friction, 'tool_error:Bash', open, null, null, 7, 2]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-120]]
  - id: v17-chain-tie-breaks-on-the-number-not-the-string
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-9, friction, 'tool_error:Bash', declined, null, 3, 2, 1], [rec-10, friction, 'tool_error:Bash', open, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-10]]
  - id: v18-rules-edit-keeps-the-identity
    findings: [[friction, 2, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', open, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-100]]
  - id: v19-same-subject-other-detector-is-distinct
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9], [deliberation_drift, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', open, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-100], [deliberation_drift, 'tool_error:Bash', file, null]]
  - id: v20-file-budget-defers-the-smallest
    findings: [[friction, 1, 'tool_error:Bash', 1, 7, 9, 20], [friction, 1, 'tool_error:Edit', 1, 7, 3, 6], [friction, 1, 'tool_blocked:Edit', 1, 7, 7, 9], [friction, 1, 'scope_creep', 1, 7, 5, 5]]
    heads: []
    targets: []
    expected: [[friction, 'tool_error:Bash', file, null], [friction, 'tool_blocked:Edit', file, null], [friction, 'scope_creep', file, null], [friction, 'tool_error:Edit', over_budget, null]]
  - id: v21-regressions-share-the-budget-updates-do-not
    findings: [[friction, 1, 'tool_error:Bash', 11, 17, 3, 9], [friction, 1, 'tool_error:Edit', 11, 17, 8, 9], [friction, 1, 'scope_creep', 11, 17, 6, 9], [friction, 1, 'hook_fault', 11, 17, 4, 9], [friction, 1, 'tool_blocked:Edit', 11, 17, 9, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', closed, null, 10, 7, 1], [rec-101, friction, 'hook_fault', open, null, null, 10, 1]]
    targets: []
    expected: [[friction, 'tool_blocked:Edit', file, null], [friction, 'tool_error:Edit', file, null], [friction, 'scope_creep', file, null], [friction, 'tool_error:Bash', over_budget, null], [friction, 'hook_fault', update, rec-101]]
  - id: v22-closed-head-keeps-its-own-regression-pointer
    findings: [[friction, 1, 'tool_error:Bash', 11, 17, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', closed, rec-50, 10, 7, 1]]
    targets: [[rec-50, open, null]]
    expected: [[friction, 'tool_error:Bash', regression, rec-100]]
  - id: v23-deferred-head-updates
    findings: [[friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'tool_error:Bash', deferred, null, null, 7, 1]]
    targets: []
    expected: [[friction, 'tool_error:Bash', update, rec-100]]
  - id: v24-deferred-cover-is-covered
    findings: [[friction, 1, 'unmapped_block:PreToolUse.Bash', 8, 14, 4, 9]]
    heads: [[rec-100, friction, 'unmapped_block:PreToolUse.Bash', superseded, rec-50, 6, 7, 1]]
    targets: [[rec-50, deferred, null]]
    expected: [[friction, 'unmapped_block:PreToolUse.Bash', covered, rec-50]]
  - id: v25-one-finding-per-fingerprint-per-run
    findings: [[friction, 1, 'tool_error:Bash', 1, 7, 3, 5], [friction, 1, 'tool_error:Bash', 8, 14, 4, 9]]
    heads: []
    targets: []
    expected: [[friction, 'tool_error:Bash', file, null]]
```

v19 uses `tool_error:Bash` as a deliberation subject only to show that the detector, not the subject text,
separates identities; the real deliberation subjects are drift classes per producer (W1-4).

Rec content (described only). Title and context are filled from a fixed template per detector, never
LLM-authored (Decision 55), with get_rec_write_guidance() read at build time (Decision 66). Word order in
the title does not matter to the duplicate signal (a token-set Jaccard): two titles of n tokens that
differ in one subject token score (n-1)/(n+1), which reaches 0.7 at n >= 6. The only title-side lever is a
template of at most five tokens, which leaves no room for what a title must say, so R1's evaluator fix
is the real mitigation. Context is derived counts only: sessions, events, window, detector_version and the
response stamps of the verb that produced the finding (classifier_version, registry_version,
parser_version: the friction report's R5). It carries no raw signature, stderr or path. The acceptance
probe is open (q1).

## 3. Settled / contested / risk / open

Settled (consistent with a Decision, a contract or measured; s1-s3 in the fixture):

- s1 Identity is one rec per finding fingerprint (salt, detector_id, subject_key), kept in context_v2_json
  under one filer source, newest record per fingerprint as the head. The model is ci_rca's (Decision 142,
  e7-e10). It is not backlog_health's aggregate rec (rec-3702: one rec over 221 ids cannot be closed by
  one fix), and it is not rec_episode's source-only key (VP 1: a second subject updates the first
  subject's rec).
- s2 The filing decision is one SQL statement over the filer's own source plus one read per covering
  rec. It passes 25/25 vectors across ten actions; every non-filing outcome is counted in the run record
  (VP 2).
- s3 The filer never closes. Below the floor is hold. Closure needs a recorded proof (Decision 103, e13),
  which belongs to back-validation (T3.4). VP 1 shows that rec_episode's truth table would close an open
  rec with no proof the moment a detector goes quiet, which can also happen because no sessions ran.
  The loop_liveness_stale monitor already follows the same rule ("Never auto-closed",
  scripts/convergence_health/sensor_liveness_episodes.py:135).

Contested (evidence on both sides, options listed; k1-k3 in the fixture; all parked, see
/mnt/project-files/gates/w1-c5-parked-forks.md):

- k1 Cross-source link: how a finding learns that another source's open rec already covers it.
  - (a) A typed `covered_by: rec-N` on the filer's OWN rec, set by the operator at triage (status
    superseded), which the filer follows (v11-v15). It is deterministic, one hop, and writes nothing on
    the other source's rec. Precedent: ci_rca's typed regression_of pointer in context_v2_json. Against
    (a): a new key in an unvalidated blob (e10), so it needs a filer lifecycle contract like
    ci-rca-lifecycle.yaml; and the first sighting of an already-known issue still produces one proposal
    for the operator to mark.
  - (b) Title similarity: the existing open_duplicate signal. VP 3: a false duplicate at 0.82 between
    distinct findings, and a miss at 0.00 on the same problem.
  - (c) An LLM judge (rec-2591's shape). It spends (charter never-list) and breaks Decision 55's
    dedup-in-code rule.
  - (d) No cross-source dedupe at filing; backlog_health's close_proposed catches duplicates afterwards.
    It inherits (b)'s errors.
  Recommended: (a). It has no precedent outside ci_rca, so it is parked.
- k2 What a declined head means.
  - (a) The fingerprint stays suppressed until the operator acts (v10), and the run record keeps counting
    its sessions.
  - (b) A snooze: re-file after N days.
  - (c) Re-file when sessions grow k-fold since the decline.
  For (a): a decline is the operator's word, and no closed->open flip exists anywhere (e7). Against (a):
  a growing problem stays unfiled until someone reads the run record. Recommended: (a), with the
  suppressed sessions trend surfaced to the maturity-ladder controller. No precedent, so parked.
- k3 Filing under an over-cap queue (1244 non-automatable against a soft cap of 250).
  - (a) The per-run budget only (file_budget 3).
  - (b) No new file or regression while the queue is over the cap, with update, covered and the run
    record unaffected. At today's numbers it never files.
  - (c) File with automatable false and the source's Low priority, and let /orient rank.
  Recommended: (a) for the sampled rung; read_all files nothing either way. This is the operator's
  queue policy, so it is parked.

Risk (known loss modes, not choices):

- R1 Templated titles trip backlog_health. Two filer recs for distinct findings share most title tokens
  (VP 3: 0.82). backlog_health's monitor then lists them as near-duplicates and a close_proposed follows.
  Reordering the title does nothing, because the score ignores word order (a subject-first template also
  scores 0.82). The fix is in the relevance evaluator: skip a pair whose context_v2_json fingerprints
  differ. That is named for the owners of rec_relevance and backlog_health (rec-3702's monitor); no rec
  is filed.
- R2 Race. Two concurrent filer runs can both choose `file` (DuckLake enforces no uniqueness; rec-4063).
  ci_rca's write-time backstop (e9) covers source ci_rca only. The build generalises it to any source
  whose context_v2_json carries a fingerprint, adds a schedule concurrency group, and c2's guard alarms
  on a second open rec per fingerprint.
- R3 Version floods. A new classifier_version can surface many labels at once (friction R5). The budget
  holds back everything past 3 per run as over_budget, smallest first (v20, v21), so the queue sees at most
  3 new recs per run, and the over_budget fingerprints are listed.
- R4 Egress. One scoped `current_state` read per run plus one `rec_by_id` per distinct cover. Never the
  open_recs bulk read: it is unscoped and lacks source and context_v2_json (e11). The registered
  validate_episode_lookup_projection guard exists because of that defect class.
- R5 Free text. Subject keys carry repo-specific labels and tool names, which are free text under
  Decision 209 cl.2b (friction report section 4). Filer recs stay in the data plane; a control-plane
  view sees per-action counts only unless rec-4141's allow-list names more.
- R6 Queue input. Filing is not consuming the queue (Decision 67), but every filed rec becomes /orient
  input and, once T4.2 lands, executor input. The read_all rung files nothing for that reason.

Open (q1-q3 in the fixture; none is answerable from the repository):

- q1 What acceptance does a filer rec carry? file_rec requires a discriminating probe (rec-3220), and
  "telemetry delta proves fix" needs back-validation's verb, which does not exist yet. Until it does, a
  filer rec has no honest acceptance command; the back-validation component owns the answer.
- q2 Where does a read_all verdict persist? A "covered_by rec-N" verdict on a proposal has no rec to live
  on, because read_all files nothing. Options are an operator sheet, or filing the proposal straight
  into the superseded state with covered_by set (a recorded lifecycle closure, not a deletion).
- q3 Seed values: min_sessions 3, min_events 5, window 7 days, budget 3. All are unmeasured, because no
  friction rows exist in production until W1-1's producer wiring lands.

## 4. Consideration register (as authored in the fixture)

- planes: data_plane. The filer reads and writes ops_recommendations through the portal; its findings
  come from data-plane verbs. What a control plane sees is per-action counts, under rec-4141's allow-list.
- failure_signal: queue noise or silent loss. Noise is a known issue re-filed, distinct findings merged,
  or a declined or covered finding re-filed. Loss is a recurring finding never filed. Metric
  `rejected_share`: the share of filer proposals (read_all) or filed recs (later rungs) that the operator
  marks covered, duplicate or reject, per 30 days per detector. Source: the operator verdicts plus the run
  record's per-action counts. Why this metric: a filer graded on recs filed floods the queue, and one
  graded on dedupe rate merges everything into one rec. rejected_share is also the T3.3 false-positive
  rate that audit F-035 found undefined, so W3 can stage it as that criterion's formula.
- Goodhart guard: the cheap way to a low rejected_share is to file nothing, or to absorb everything into
  a few open recs. Filing nothing shows as the hold, suppressed and over_budget counts in every run record,
  read beside rejected_share. Over-absorption is blocked by construction: an update is an exact
  fingerprint match (no similarity, no wildcard), and one open rec per fingerprint is c2's guard. A cover
  link is written only by the operator and is one hop.
- maturity: read_all means propose-only; the filer files nothing and the operator reviews every
  proposal (c3). read_all -> sampled at >= 20 consecutive proposals accepted unchanged; sampled ->
  spot_check at 0 rejected filings across the last 50 sampled filer recs; spot_check -> anomaly_triggered
  at >= 30 consecutive days with rejected_share <= 0.05 and no duplicate open fingerprint. A params_version
  change is a new rule set; the maturity-ladder controller decides whether it restarts the ladder.
- verification: c1 (the decision passes these vectors over the filer's projection, with per-action counts
  and params_version in each run record), c2 (the guard: one open rec per fingerprint, the identity keys
  present on every filer rec, a backstop refusing a second open insert), c3 (the operator's read_all
  proposal review). All open.
- rollback: stop the filer's schedule. Filed recs remain ordinary recs the operator can decline, close or
  mark covered. The decision is stateless over its projection, so a params revert re-derives on the next
  run.
- edges: part_of T3.3 (its exit criteria file anomaly recs and leave the false-positive threshold
  undefined; this item is that filing half); depends_on T2.36 (findings come from telemetry reader verbs on
  DuckLake).

## 5. Boundary notes for W2 synthesis

- Friction classifier (W1-3, #1394): the filer files on label counts per classifier_version and never on
  raw signatures, as that report asked. Its missing-gotcha row resolves here as the `covered` action. On
  merge, W2 should add `pwi-rec-filing-dedupe depends_on pwi-friction-classifier`. The evaluator's L4
  refuses an edge to a pilot item absent from this branch's fixture, so it is not added here.
- Deliberation capture (W1-4, #1395): deliberation_drift_share is a detector input. A drift finding's
  subject is (producer, drift class), and its version stamp is parser_version.
- Reader verbs (W1-2, #1390): detector verbs produce findings, so the filer depends on that mechanism,
  through T2.36 here and through the pilot item at W2.
- Back-validation (next W1 component): it owns the close-with-proof step, the acceptance probe (q1), and
  the post-fix delta that this design's `regression` action mirrors. The two must agree on the window
  rule: a window that spans the fix is neither proof nor regression (v08, v13).
- Maturity-ladder controller and Goodhart register: this item's rungs and its rejected_share and
  hold/suppressed counts are inputs to both.
- Allow-list transport (rec-4141): per-action counts are a closed vocabulary; subject keys are not (R5).
- Contradiction for W2: the friction report's k3 recommends producer-side signatures, so subject keys
  stay a small closed set. If W2 picks W1-1's read-side regex instead, subject keys can grow without
  bound, and the budget (R3) becomes the only guard on volume.
