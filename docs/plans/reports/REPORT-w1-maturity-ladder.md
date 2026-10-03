# REPORT: W1 component 7 - maturity ladder controller (read_all -> sampled -> spot_check -> anomaly_triggered)

Plan: docs/plans/PLAN-w1-maturity-ladder.yaml. Fixture item: pwi-maturity-ladder-controller (1 of 12 cap).
REPORT-ONLY (Decision 86 cl.2): nothing here is built, filed, ratified or flipped. Every rec, table,
verb and schema change named below is a description of a future build.

## 0. Verdict

Every W1 component carries a maturity block, and none of those blocks can be run as written. The six
open items (#1384, #1390, #1394, #1395, #1396, #1397) declare 18 triggers. All 18 point upward; the
pilot schema accepts only the three upward adjacent pairs, so no item can declare a way back down (VP 1).
Every trigger metric is free text, no item states how many outputs a rung reviews, and nothing at runtime
reads a rung (VP 1, VP 2). Two consequences are measured, not argued:

- A clearance count with no return leg measures patience, not quality. "20 consecutive clean reviews" is
  reached after about 36 reviews at a 5% error rate and about 72 at 10%, and once passed nothing brings the
  component back (VP 2). In a seeded one-year simulation run through the controller SQL below, the declared
  triggers let a 20%-error component ship 10.7-12.0% of its outputs wrong and unreviewed (VP 4).
- A blinder monitor promotes faster. At a 5% error rate, 95% of components whose failure_signal sees half
  the errors reach anomaly_triggered under the declared triggers, against 40% of those whose monitor sees
  all of them (VP 4). The spot_check -> anomaly_triggered trigger is read off the same signal the top rung
  then relies on, so a weaker signal is rewarded.

The staged controller is one deterministic SQL per daily run (Decision 55). It reads a review log, the
component's failure_signal series, monitor drills and operator approvals. For each component it returns
promote, propose_promote, hold, demote or restart, with one of 11 reasons. It passes 45/45 vectors (VP 3),
eight of them by raising on malformed input, and each of 32 hand-run mutants fails at least one vector.
It is a multi-level continuous sampling plan in the Dodge (CSP-1) and Lieberman-Solomon family: a
clearance count per rung, a return leg on any wrong output found above read_all, a restart on a version
change, a demotion on a breaching or dark failure_signal, and an injected-fault drill before the top rung.
In the same simulation, escaped-wrong share stays at or below 1.6% at every error rate tested (the
closed-form CSP-1 bound for the first level is 1.76%), and no half-blind monitor ever reaches
anomaly_triggered. That is paid for in review load: a 2%-error component is reviewed on 20% of its outputs
instead of 3.5% (VP 4, section 2.6).

What is settled is narrow: the four rungs and their order (evaluator code), a deterministic decision
(Decision 55), and the measured facts above. The return leg, the version-change rule and promotion
authority are forks with credible alternatives and no admissible precedent (T3.4 and T4.4 call for per-gate
rollback, but that is roadmap text, not a Decision or contract), so they are parked (k1-k3). The decision
rule's family and seeds (k4) and the drill (k5) are parked report-only. Both #1396 and #1397 defer one
question to this component: whether a params_version change restarts the ladder. That is k2, and its
recommendation is restart at read_all.

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | Rungs are a closed Literal of four, and `Maturity.transitions` must be exactly the three upward adjacent pairs in order; a downward pair is refused and no other maturity field exists [VP 1] | scripts/checks/roadmap/_work_item_pilot_model.py:48, :151-158 |
| e2 | `Trigger.metric` is free text (3-120 printable characters); "anything at all" validates, so no trigger names a computable series [VP 1] | scripts/checks/roadmap/_work_item_pilot_model.py:131-133 |
| e3 | No file under src/ or scripts/ outside the pilot model and its evaluator mentions anomaly_triggered or spot_check: nothing at runtime reads or writes a rung [VP 1] | repository grep |
| e4 | The six open W1 items declare 18 transitions, 18 upward and 0 downward. First-rung clearances are 20 (five items) or 50 consecutive clean reviews; second-rung clearances are zero failures in the last 30, 50 or 200 sampled; five of six third-rung triggers are 30 days of a failure_signal at or under a threshold [VP 2; fidelity against the branch heads, VP 2b] | section 1.1 |
| e5 | Zero failures in n reviews bounds the error rate at 95% only to 1 - 0.05^(1/n): 13.9% at n=20, 5.8% at n=50, 1.5% at n=200 [VP 2] | section 1.2 |
| e6 | With no return leg, a consecutive-n trigger fires eventually at any error rate; the expected number of reviews before 20 consecutive clean ones is 36 at p=0.05, 72 at p=0.1 and 429 at p=0.2 [VP 2] | section 1.2 |
| e7 | CSP-1 (Dodge 1943): 100% review until i consecutive clean outputs, then a fraction f, back to 100% on any defect found. Its average outgoing quality limit at f=0.2 is 3.44% for i=20 and 1.76% for i=40 [VP 2] | section 1.2 |
| e8 | T3.4 exit criterion 2 asks for maturity gates A0-A3 with a per-gate rollback criterion; T4.4 asks that every gate carry a numeric threshold with its denominator, window and data source, and that rollback be automatic on breach (roadmap text, not a Decision) | docs/ROADMAP-PLATFORM.yaml:6594, T4.4 exit criteria |
| e9 | Both #1396 and #1397 end their maturity text with the same deferral: "A params_version change is a new rule set; the maturity-ladder controller decides whether it restarts the ladder" | REPORT-w1-rec-filing-dedupe.md section 4; REPORT-w1-back-validation.md section 4 (unmerged) |
| e10 | Decision 73 halt check: the reader's named verb ci_rca_open returned [] at 2026-10-03T12:07:41Z | Step 0 |

### 1.1 Trigger inventory (copied from the six branch heads; VP 2b re-reads them)

`kind` and `n` are this report's classification of each trigger; `transitions` is copied byte for byte.

```yaml
inventory:
  read_at: '2026-10-03T12:15Z'
  items:
    - item: pwi-capture-producer-wiring
      pr: 1384
      branch: claude/w1-capture-producer-wiring
      head: 1da1cc97f3522e5551ab32bcb41e3bb5b93cf685
      kind: [consecutive, zero_in_last, days_clean]
      n: [20, 30, 30]
      transitions:
        - {from: read_all, to: sampled, trigger: {metric: consecutive finalized sessions whose runner-side conformance check reports zero violations, comparator: '>=', threshold: 20}}
        - {from: sampled, to: spot_check, trigger: {metric: runner-side conformance violations across the last 30 sampled sessions, comparator: ==, threshold: 0}}
        - {from: spot_check, to: anomaly_triggered, trigger: {metric: consecutive days with unfinalized_session_share <= 0.05 over the q1 out-of-band session denominator, comparator: '>=', threshold: 30}}
    - item: pwi-telemetry-reader-verbs
      pr: 1390
      branch: claude/w1-reader-verbs
      head: ab7aad7a36819a10069628577a55b2160cf8bd81
      kind: [consecutive, zero_in_last, days_clean]
      n: [50, 200, 30]
      transitions:
        - {from: read_all, to: sampled, trigger: {metric: consecutive sessions whose verb outputs match the harness re-derivation, comparator: '>=', threshold: 50}}
        - {from: sampled, to: spot_check, trigger: {metric: verb re-derivation mismatches across the last 200 sampled sessions, comparator: ==, threshold: 0}}
        - {from: spot_check, to: anomaly_triggered, trigger: {metric: consecutive days with zero mismatches and zero conflicted grain keys reported, comparator: '>=', threshold: 30}}
    - item: pwi-friction-classifier
      pr: 1394
      branch: claude/w1-friction-classifier
      head: c6a47c5df5c1e50c7ab77730dadbe4456965772d
      kind: [consecutive, zero_in_last, days_clean]
      n: [20, 200, 30]
      transitions:
        - {from: read_all, to: sampled, trigger: {metric: consecutive reviewed sessions whose every label the operator judged correct, comparator: '>=', threshold: 20}}
        - {from: sampled, to: spot_check, trigger: {metric: mislabels across the last 200 sampled labels, comparator: ==, threshold: 0}}
        - {from: spot_check, to: anomaly_triggered, trigger: {metric: consecutive days with unmapped_failure_share <= 0.05 at one classifier_version, comparator: '>=', threshold: 30}}
    - item: pwi-deliberation-capture
      pr: 1395
      branch: claude/w1-deliberation-capture
      head: 63b1a50a6926561aac5fb5a9c651c6faba581dc5
      kind: [consecutive, zero_in_last, days_clean]
      n: [20, 200, 30]
      transitions:
        - {from: read_all, to: sampled, trigger: {metric: reviewed sessions in a row per producer with >= 1 classified model_call and zero drift rows, comparator: '>=', threshold: 20}}
        - {from: sampled, to: spot_check, trigger: {metric: drift rows per producer in a full window of the last 200 sampled classified model_calls, comparator: ==, threshold: 0}}
        - {from: spot_check, to: anomaly_triggered, trigger: {metric: days in a row per producer with deliberation_drift_share defined and <= 0.01 for every parser_version present, comparator: '>=', threshold: 30}}
    - item: pwi-rec-filing-dedupe
      pr: 1396
      branch: claude/w1-rec-filing-dedupe
      head: 51958a0ae48a700963fc5b1351fed00e6a1decec
      kind: [consecutive, zero_in_last, days_clean]
      n: [20, 50, 30]
      transitions:
        - {from: read_all, to: sampled, trigger: {metric: consecutive reviewed proposals the operator accepted unchanged, comparator: '>=', threshold: 20}}
        - {from: sampled, to: spot_check, trigger: {metric: rejected filings across the last 50 sampled filer recs, comparator: ==, threshold: 0}}
        - {from: spot_check, to: anomaly_triggered, trigger: {metric: consecutive days with rejected_share <= 0.05 and no duplicate open fingerprint, comparator: '>=', threshold: 30}}
    - item: pwi-back-validation
      pr: 1397
      branch: claude/w1-back-validation
      head: 2b19380fd2b0e646760b3aca5d3d32939d8c0191
      kind: [consecutive, zero_in_last, rate_window]
      n: [20, 50, 90]
      transitions:
        - {from: read_all, to: sampled, trigger: {metric: consecutive verdicts the operator confirmed unchanged, comparator: '>=', threshold: 20}}
        - {from: sampled, to: spot_check, trigger: {metric: overturned verdicts across the last 50 sampled verdicts, comparator: ==, threshold: 0}}
        - {from: spot_check, to: anomaly_triggered, trigger: {metric: 'false_proof_rate over the last 90 days, with at least 20 proof closes', comparator: <=, threshold: 0.05}}
```

### 1.2 What the declared clearances certify

Computed in VP 2 from the inventory block. `ucb95` is the 95% upper bound on the error rate certified by n
clean reviews in a row; `reviews_to_clear` is the expected number of reviews before the first run of n
clean ones at error rate p ((1 - q^n) / (p q^n), q = 1 - p), which is how long a component with that error
rate waits before the trigger fires anyway when nothing ever sends it back.

| first-rung n | items | ucb95 | reviews_to_clear p=0.05 | p=0.10 | p=0.20 |
|---|---|---|---|---|---|
| 20 | capture, friction, deliberation, rec-filing, back-validation | 0.139 | 36 | 72 | 429 |
| 50 | reader-verbs | 0.058 | 240 | 1930 | 350320 |

The second rung's "zero in the last n sampled" (n = 30, 50 or 200) is the same statistic on sampled
outputs. With no return leg it is reachable at n=30 or 50 for error rates up to about 5%, and at n=200
almost never above 2%. A component that stalls at sampled keeps shipping p(1 - f) of its outputs
unreviewed.

CSP-1 is the textbook fix for exactly this ladder. Its clearance number is the same consecutive count, and
its guarantee (the AOQL) holds only because a defect found while sampling returns to 100% review. At f=0.2
the AOQL is 3.44% for i=20 and 1.76% for i=40 (VP 2; AOQ(p) = p(1 - f)q^i / (f + (1 - f)q^i), maximised
over p). The declared triggers keep CSP-1's clearance and drop its return leg.

## 2. Controller design (what this item stages)

### 2.1 Rung semantics

| rung | routine review | effects the sibling items allow (their text) |
|---|---|---|
| read_all | every output (f = 1) | proposals only: the filer files nothing (#1396 c3), back-validation closes nothing (#1397 c3) |
| sampled | f_sampled of outputs | filer files under its per-run budget (#1396 k3 (a)); a holds verdict is close_proposed (#1397 k1) |
| spot_check | f_spot_check of outputs | as sampled |
| anomaly_triggered | an audit floor f_anomaly_triggered, plus review on a failure_signal breach | back-validation may close directly (#1397 k1 recommendation) |

Selection is per output and deterministic: an output is reviewed when the rung is read_all or when
md5(salt, component, output_id) maps below the rung's fraction. The salt is per component and version, so
a version change re-draws the sample. The levels follow multi-level plans (f, f^2, f^3 with f = 0.2), with
a non-zero audit floor at the top so the monitor is never the only witness. Effects stay the siblings'
business; the controller decides only the rung.

### 2.2 Inputs

`{state}`: one row per component: component, rung, entered_day (first day at this rung), version (the
component's rule-set stamp: classifier_version, parser_version or params_version), signal_threshold.
`{reviews}`: one row per selected output: component, output_id, day, version, rung (at production), outcome
(correct, wrong or unsure; NULL while pending). `{signal}`: one row per component per day: the
failure_signal value, NULL when undefined (deliberation's "undefined, never 0" maps here). `{drills}`: one
row per injected-fault run: component, day, injected, detected. `{approvals}`: one row per operator
approval: component, to_rung, day. `{today}` is the run's day. All five are build-time objects (q2).

Params are data, stamped as params_version on every transition record (seed values, unmeasured, q3):

```yaml
params_version: 1
clear_read_all: 40
clear_sampled: 40
clear_spot_check: 20
review_sla_days: 3
dark_days: 2
signal_window_days: 30
drill_min: 10
on_wrong: read_all
signal_demotes: true
signal_gates_promotion: true
version_restart: true
promotion_authority: operator
f_sampled: 0.2
f_spot_check: 0.04
f_anomaly_triggered: 0.008
```

### 2.3 The decision

Six malformed inputs raise instead of deciding (fail loud, Decision 55): an unknown rung, a NULL state field
or a duplicate component (e01, e07, e08); a review row with a NULL key (e04); a duplicate output_id (e02); an
outcome outside the vocabulary (e03); a duplicate failure_signal day (e05); a NULL key in signal or drills,
or a drill that detected more than it injected (e06). Each raise vector matches its error message, not any
DuckDB error. The guards are aggregates read by the final CASE, so no optimiser can skip them.

Clearance counts correct reviews at the current rung and version since the last breaker. A breaker is a
wrong or unsure review, or a selected output still unreviewed after review_sla_days. A pending review
inside the SLA neither counts nor breaks (v07, v36). An unreviewed sample therefore resets the count:
skipping the hard cases cannot buy a promotion (Goodhart).

```sql
WITH st AS (
  SELECT component, rung, entered_day, version, signal_threshold,
         CASE rung WHEN 'read_all' THEN 0 WHEN 'sampled' THEN 1 WHEN 'spot_check' THEN 2 WHEN 'anomaly_triggered' THEN 3 END AS ri,
         count(*) OVER (PARTITION BY component) AS n_state
  FROM {state}
),
gz AS (
  SELECT (SELECT count(*) FROM {reviews} WHERE component IS NULL)
       + (SELECT count(*) FROM {signal} WHERE component IS NULL OR day IS NULL)
       + (SELECT count(*) FROM {drills} WHERE component IS NULL OR day IS NULL OR injected IS NULL OR detected IS NULL OR detected > injected) AS bad
),
g AS (
  SELECT s.component,
         count(r.component) FILTER (WHERE r.output_id IS NULL OR r.day IS NULL OR r.version IS NULL OR r.rung IS NULL) > 0 AS has_null,
         count(r.component) > count(DISTINCT r.output_id) AS dup,
         count(r.component) FILTER (WHERE r.outcome NOT IN ('correct', 'wrong', 'unsure')) > 0 AS bad_outcome
  FROM st s LEFT JOIN {reviews} r ON r.component = s.component
  GROUP BY s.component
),
gs AS (
  SELECT s.component, count(x.component) > count(DISTINCT x.day) AS dup_day
  FROM st s LEFT JOIN {signal} x ON x.component = s.component
  GROUP BY s.component
),
rv AS (
  SELECT r.component, r.output_id, r.day, r.version, r.rung, r.outcome
  FROM {reviews} r JOIN st s ON s.component = r.component
  WHERE r.day >= s.entered_day AND r.day <= {today}
),
vc AS (
  SELECT s.component, count(rv.component) FILTER (WHERE rv.version <> s.version) > 0 AS changed
  FROM st s LEFT JOIN rv ON rv.component = s.component
  GROUP BY s.component
),
cur AS (
  SELECT rv.*,
         row_number() OVER (PARTITION BY rv.component ORDER BY rv.day, rv.output_id) AS pos,
         (rv.outcome IN ('wrong', 'unsure') OR (rv.outcome IS NULL AND rv.day < {today} - {review_sla_days})) AS breaker
  FROM rv JOIN st s ON s.component = rv.component AND rv.rung = s.rung AND rv.version = s.version
),
lb AS (SELECT component, max(pos) FILTER (WHERE breaker) AS last_break FROM cur GROUP BY component),
cl AS (
  SELECT s.component,
         count(c.component) FILTER (WHERE c.outcome = 'correct' AND c.pos > coalesce(lb.last_break, 0)) AS clearance,
         count(c.component) FILTER (WHERE c.outcome = 'wrong') AS wrong_n,
         count(c.component) FILTER (WHERE c.outcome IS NULL AND c.day < {today} - {review_sla_days}) AS overdue_n
  FROM st s LEFT JOIN cur c ON c.component = s.component LEFT JOIN lb ON lb.component = s.component
  GROUP BY s.component
),
sg AS (
  SELECT s.component,
         max(x.value) FILTER (WHERE x.day = {today}) AS v_today,
         count(x.value) FILTER (WHERE x.day > {today} - {dark_days}) AS defined_recent,
         count(x.value) FILTER (WHERE x.day > {today} - {signal_window_days} AND x.day >= s.entered_day
                                  AND x.value <= s.signal_threshold) AS clean_days
  FROM st s LEFT JOIN {signal} x ON x.component = s.component AND x.day <= {today}
  GROUP BY s.component
),
dr AS (
  SELECT s.component, coalesce(sum(d.injected), 0) AS inj, coalesce(sum(d.detected), 0) AS det
  FROM st s LEFT JOIN {drills} d ON d.component = s.component AND d.day >= s.entered_day AND d.day <= {today}
  GROUP BY s.component
),
ap AS (
  SELECT s.component, count(a.component) > 0 AS approved
  FROM st s LEFT JOIN {approvals} a ON a.component = s.component AND a.day >= s.entered_day AND a.day <= {today}
       AND a.to_rung = ['read_all', 'sampled', 'spot_check', 'anomaly_triggered', 'none'][s.ri + 2]
  GROUP BY s.component
),
d AS (
  SELECT s.component, s.ri,
    CASE
      WHEN s.ri IS NULL OR s.entered_day IS NULL OR s.version IS NULL OR s.signal_threshold IS NULL OR s.n_state > 1
      THEN error('malformed ladder state: unknown rung, NULL field or duplicate component')
      WHEN gz.bad > 0 THEN error('malformed ladder input: NULL key or detected > injected')
      WHEN g.has_null THEN error('malformed review row: NULL output_id, day, version or rung')
      WHEN g.dup THEN error('duplicate output_id: one review row per output')
      WHEN g.bad_outcome THEN error('review outcome outside correct, wrong, unsure')
      WHEN gs.dup_day THEN error('duplicate failure_signal day: one value per component per day')
      WHEN {version_restart} AND vc.changed THEN 'restart:version_change'
      WHEN s.ri > 0 AND '{on_wrong}' <> 'none' AND cl.wrong_n > 0 THEN 'demote:wrong_found'
      WHEN s.ri > 0 AND {signal_demotes} AND sg.v_today > s.signal_threshold THEN 'demote:signal_breach'
      WHEN s.ri > 0 AND {signal_demotes} AND sg.defined_recent = 0 THEN 'demote:signal_dark'
      WHEN s.ri = 3 THEN 'hold:top'
      WHEN cl.overdue_n > 0 THEN 'hold:review_overdue'
      WHEN cl.clearance < [{clear_read_all}, {clear_sampled}, {clear_spot_check}][s.ri + 1] THEN 'hold:clearing'
      WHEN {signal_gates_promotion} AND (sg.v_today IS NULL OR sg.v_today > s.signal_threshold) THEN 'hold:signal_not_clean'
      WHEN s.ri = 2 AND sg.clean_days < {signal_window_days} THEN 'hold:signal_window'
      WHEN s.ri = 2 AND {drill_min} > 0 AND (dr.inj < {drill_min} OR dr.det < dr.inj) THEN 'hold:awaiting_drill'
      WHEN '{promotion_authority}' = 'auto' OR ap.approved THEN 'promote:cleared'
      ELSE 'propose_promote:cleared'
    END AS ar
  FROM st s
  CROSS JOIN gz
  JOIN g ON g.component = s.component
  JOIN gs ON gs.component = s.component
  JOIN vc ON vc.component = s.component
  JOIN cl ON cl.component = s.component
  JOIN sg ON sg.component = s.component
  JOIN dr ON dr.component = s.component
  JOIN ap ON ap.component = s.component
)
SELECT DISTINCT component,
       split_part(ar, ':', 1) AS action,
       CASE split_part(ar, ':', 1)
         WHEN 'restart' THEN 'read_all'
         WHEN 'demote' THEN CASE WHEN ar = 'demote:wrong_found' AND '{on_wrong}' = 'read_all' THEN 'read_all'
                                 ELSE ['read_all', 'sampled', 'spot_check'][ri] END
         WHEN 'hold' THEN ['read_all', 'sampled', 'spot_check', 'anomaly_triggered'][ri + 1]
         ELSE ['sampled', 'spot_check', 'anomaly_triggered'][ri + 1]
       END AS to_rung,
       split_part(ar, ':', 2) AS reason
FROM d
```

| action | reason | when (precedence top-down) | vectors |
|---|---|---|---|
| restart | version_change | a review in the stint carries a version other than the state's, when version_restart (k2) | v18, v19, v25 |
| demote | wrong_found | a wrong review at the current rung above read_all; to read_all or one rung down per on_wrong (k1); never at read_all | v08, v09, v26, v30, v31 |
| demote | signal_breach | above read_all, today's failure_signal exceeds the threshold (strictly), when signal_demotes; one rung down | v11 |
| demote | signal_dark | above read_all, no defined failure_signal value in the last dark_days days; one rung down | v12, v32 |
| hold | top | at anomaly_triggered with nothing to demote | v13 |
| hold | review_overdue | a selected output in the stint is past the SLA unreviewed | v06 |
| hold | clearing | clearance below the rung's clear_* | v03, v04, v05, v29, v36 |
| hold | signal_not_clean | today's failure_signal undefined or above threshold, when signal_gates_promotion | v20, v21, v22 |
| hold | signal_window | at spot_check, fewer than signal_window_days clean days inside the stint | v15 |
| hold | awaiting_drill | at spot_check, fewer than drill_min injected faults or any missed (when drill_min > 0) | v16, v17 |
| promote | cleared | an approval for the next rung dated inside the stint, or promotion_authority auto (k3) | v02, v27 |
| propose_promote | cleared | otherwise | v01, v07, v10, v14, v23, v24, v28, v33, v34, v35, v37 |

Rows outside the stint (before entered_day, after today) and rows recorded at another rung are ignored
(v28, v29, v37). Several components decide independently in one run (v30).

### 2.4 Vectors (VP 3)

`reviews` rows expand to n outputs on one day; `signal` rows cover a day range with one value.
`expected: error` vectors carry the message substring they must raise.

```yaml
vectors:
  - {id: v01, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: [[a, propose_promote, sampled, cleared]]}
  - {id: v02, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], approvals: [[a, sampled, 50]], expected: [[a, promote, sampled, cleared]]}
  - {id: v03, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 39, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: [[a, hold, read_all, clearing]]}
  - {id: v04, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 20, v1, read_all, correct], [a, 21, 1, v1, read_all, wrong], [a, 22, 39, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: [[a, hold, read_all, clearing]]}
  - {id: v05, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct], [a, 21, 1, v1, read_all, unsure]], signal: [[a, 49, 50, 0.0]], expected: [[a, hold, read_all, clearing]]}
  - {id: v06, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct], [a, 46, 1, v1, read_all, null]], signal: [[a, 49, 50, 0.0]], expected: [[a, hold, read_all, review_overdue]]}
  - {id: v07, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct], [a, 47, 1, v1, read_all, null]], signal: [[a, 49, 50, 0.0]], expected: [[a, propose_promote, sampled, cleared]]}
  - {id: v08, today: 50, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 30, v1, spot_check, correct], [a, 21, 1, v1, spot_check, wrong]], signal: [[a, 10, 50, 0.0]], expected: [[a, demote, read_all, wrong_found]]}
  - {id: v09, today: 50, params: {on_wrong: one_down}, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 30, v1, spot_check, correct], [a, 21, 1, v1, spot_check, wrong]], signal: [[a, 10, 50, 0.0]], expected: [[a, demote, sampled, wrong_found]]}
  - {id: v10, today: 50, params: {on_wrong: none}, state: [[a, sampled, 10, v1, 0.05]], reviews: [[a, 20, 1, v1, sampled, wrong], [a, 21, 40, v1, sampled, correct]], signal: [[a, 49, 50, 0.0]], expected: [[a, propose_promote, spot_check, cleared]]}
  - {id: v11, today: 50, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 30, v1, spot_check, correct]], signal: [[a, 10, 49, 0.0], [a, 50, 50, 0.08]], expected: [[a, demote, sampled, signal_breach]]}
  - {id: v12, today: 50, state: [[a, anomaly_triggered, 10, v1, 0.05]], signal: [[a, 10, 48, 0.0]], expected: [[a, demote, spot_check, signal_dark]]}
  - {id: v13, today: 50, state: [[a, anomaly_triggered, 10, v1, 0.05]], reviews: [[a, 30, 2, v1, anomaly_triggered, correct]], signal: [[a, 10, 50, 0.01]], expected: [[a, hold, anomaly_triggered, top]]}
  - {id: v14, today: 50, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 20, v1, spot_check, correct]], signal: [[a, 10, 50, 0.01]], drills: [[a, 30, 10, 10]], expected: [[a, propose_promote, anomaly_triggered, cleared]]}
  - {id: v15, today: 50, state: [[a, spot_check, 22, v1, 0.05]], reviews: [[a, 30, 20, v1, spot_check, correct]], signal: [[a, 1, 50, 0.01]], drills: [[a, 30, 10, 10]], expected: [[a, hold, spot_check, signal_window]]}
  - {id: v16, today: 50, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 20, v1, spot_check, correct]], signal: [[a, 10, 50, 0.01]], drills: [[a, 30, 10, 9]], expected: [[a, hold, spot_check, awaiting_drill]]}
  - {id: v17, today: 50, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 20, v1, spot_check, correct]], signal: [[a, 10, 50, 0.01]], drills: [[a, 30, 9, 9]], expected: [[a, hold, spot_check, awaiting_drill]]}
  - {id: v18, today: 50, state: [[a, sampled, 10, v1, 0.05]], reviews: [[a, 20, 30, v1, sampled, correct], [a, 40, 1, v2, sampled, correct]], signal: [[a, 10, 50, 0.0]], expected: [[a, restart, read_all, version_change]]}
  - {id: v19, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct], [a, 41, 1, v2, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: [[a, restart, read_all, version_change]]}
  - {id: v20, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 40, 49, 0.0]], expected: [[a, hold, read_all, signal_not_clean]]}
  - {id: v21, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 40, 50, 0.2]], expected: [[a, hold, read_all, signal_not_clean]]}
  - {id: v22, today: 50, params: {signal_demotes: false}, state: [[a, sampled, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, sampled, correct]], signal: [[a, 40, 50, 0.2]], expected: [[a, hold, sampled, signal_not_clean]]}
  - {id: v23, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], approvals: [[a, spot_check, 50]], expected: [[a, propose_promote, sampled, cleared]]}
  - {id: v24, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], approvals: [[a, sampled, 9]], expected: [[a, propose_promote, sampled, cleared]]}
  - {id: v25, today: 50, state: [[a, sampled, 10, v1, 0.05]], reviews: [[a, 20, 1, v1, sampled, wrong], [a, 40, 1, v2, sampled, correct]], signal: [[a, 10, 50, 0.0]], expected: [[a, restart, read_all, version_change]]}
  - {id: v26, today: 50, params: {on_wrong: one_down}, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 1, v1, spot_check, wrong]], signal: [[a, 10, 49, 0.0], [a, 50, 50, 0.3]], expected: [[a, demote, sampled, wrong_found]]}
  - {id: v27, today: 50, params: {promotion_authority: auto}, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: [[a, promote, sampled, cleared]]}
  - {id: v28, today: 50, state: [[a, sampled, 30, v1, 0.05]], reviews: [[a, 20, 3, v1, read_all, wrong], [a, 25, 1, v0, read_all, correct], [a, 31, 40, v1, sampled, correct]], signal: [[a, 30, 50, 0.0]], expected: [[a, propose_promote, spot_check, cleared]]}
  - {id: v29, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 39, v1, read_all, correct], [a, 51, 5, v1, read_all, correct], [a, 52, 1, v2, read_all, wrong]], signal: [[a, 49, 50, 0.0]], expected: [[a, hold, read_all, clearing]]}
  - {id: v30, today: 50, state: [[a, read_all, 10, v1, 0.05], [b, sampled, 10, w1, 0.1]], reviews: [[a, 20, 40, v1, read_all, correct], [b, 20, 5, w1, sampled, correct], [b, 21, 1, w1, sampled, wrong]], signal: [[a, 49, 50, 0.0], [b, 49, 50, 0.0]], expected: [[a, propose_promote, sampled, cleared], [b, demote, read_all, wrong_found]]}
  - {id: v31, today: 50, state: [[a, anomaly_triggered, 10, v1, 0.05]], reviews: [[a, 30, 1, v1, anomaly_triggered, wrong]], signal: [[a, 10, 50, 0.0]], expected: [[a, demote, read_all, wrong_found]]}
  - {id: v32, today: 50, state: [[a, anomaly_triggered, 10, v1, 0.05]], signal: [[a, 10, 48, 0.0], [a, 49, 50, null]], expected: [[a, demote, spot_check, signal_dark]]}
  - {id: v33, today: 50, state: [[a, sampled, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, sampled, correct]], signal: [[a, 10, 50, 0.05]], expected: [[a, propose_promote, spot_check, cleared]]}
  - {id: v34, today: 50, params: {signal_gates_promotion: false}, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 40, v1, read_all, correct]], signal: [[a, 40, 50, 0.2]], expected: [[a, propose_promote, sampled, cleared]]}
  - {id: v35, today: 50, params: {drill_min: 0}, state: [[a, spot_check, 10, v1, 0.05]], reviews: [[a, 20, 20, v1, spot_check, correct]], signal: [[a, 10, 50, 0.01]], drills: [[a, 30, 4, 1]], expected: [[a, propose_promote, anomaly_triggered, cleared]]}
  - {id: v36, today: 50, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 39, v1, read_all, correct], [a, 48, 1, v1, read_all, null]], signal: [[a, 49, 50, 0.0]], expected: [[a, hold, read_all, clearing]]}
  - {id: v37, today: 50, state: [[a, sampled, 10, v1, 0.05]], reviews: [[a, 12, 1, v1, read_all, wrong], [a, 20, 40, v1, sampled, correct]], signal: [[a, 10, 50, 0.0]], expected: [[a, propose_promote, spot_check, cleared]]}
  - {id: e01, today: 50, raises: 'malformed ladder state', state: [[a, audit, 10, v1, 0.05]], expected: error}
  - {id: e02, today: 50, raises: 'duplicate output_id', dup_review: true, state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 2, v1, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: error}
  - {id: e03, today: 50, raises: 'review outcome outside', state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 1, v1, read_all, maybe]], signal: [[a, 49, 50, 0.0]], expected: error}
  - {id: e04, today: 50, raises: 'malformed review row', state: [[a, read_all, 10, v1, 0.05]], reviews: [[a, 20, 1, null, read_all, correct]], signal: [[a, 49, 50, 0.0]], expected: error}
  - {id: e05, today: 50, raises: 'duplicate failure_signal day', state: [[a, read_all, 10, v1, 0.05]], signal: [[a, 49, 50, 0.0], [a, 50, 50, 0.0]], expected: error}
  - {id: e06, today: 50, raises: 'detected > injected', state: [[a, spot_check, 10, v1, 0.05]], signal: [[a, 49, 50, 0.0]], drills: [[a, 30, 2, 3]], expected: error}
  - {id: e07, today: 50, raises: 'malformed ladder state', state: [[a, read_all, 10, v1, 0.05], [a, sampled, 10, v1, 0.05]], expected: error}
  - {id: e08, today: 50, raises: 'malformed ladder state', state: [[a, read_all, null, v1, 0.05]], signal: [[a, 49, 50, 0.0]], expected: error}
```

### 2.5 Mutants (hand-run once, reported, not a VP step)

Each mutant is one textual edit of the SQL above; every one fails at least one vector:

| mutant | edit | killed by |
|---|---|---|
| m01 | on_wrong ignored (always demote on a wrong review) | v10 |
| m02 | a pending review counts toward clearance | v36 |
| m03 | a pending review inside the SLA breaks clearance | v07 |
| m04 | SLA boundary < becomes <= | v07 |
| m05 | unsure is not a breaker | v05 |
| m06 | rows before entered_day read | v28 |
| m07 | rows after today read | v29 |
| m08 | wrong_found checked before version_change | v25 |
| m09 | a demotion targets the current rung | v09, v11, v12, v26, v32 |
| m10 | dark window boundary > becomes >= | v12, v32 |
| m11 | a NULL signal value counts as defined | v32 |
| m12 | signal window counts days before the stint | v15 |
| m13 | an approval for any rung promotes | v23 |
| m14 | an approval from before the stint promotes | v24 |
| m15 | a drill with a missed fault passes | v16 |
| m16 | the drill applies when drill_min is 0 | v35 |
| m17 | duplicate output_id guard removed | e02 |
| m18 | outcome vocabulary guard removed | e03 |
| m19 | NULL review key guard removed | e04 |
| m20 | duplicate signal day guard removed | e05 |
| m21 | detected > injected guard removed | e06 |
| m22 | duplicate component guard removed | e07 |
| m23 | breach comparator > becomes >= | v33 |
| m24 | signal_demotes ignored | v22 |
| m25 | signal_gates_promotion ignored | v34 |
| m26 | a wrong review demotes at read_all | v04 |
| m27 | rows recorded at another rung count | v37 |
| m28 | hold top checked before the demotions | v12, v31, v32 |
| m29 | promotion_authority auto ignored | v27 |
| m30 | one clearance (clear_read_all) for every rung | v14, v15, v16, v17, v35 |
| m31 | signal window check removed | v15 |
| m32 | signal_dark demotion removed | v12, v32 |

### 2.6 Simulation (VP 4)

One year, 12 outputs a day per component (the order of magnitude #1397 measured for sessions), 20
replicate components per (error rate p, monitor recall r) cell, error rates 0.005 to 0.2, recall 1.0 or
0.5. The failure_signal is the 7-day share of outputs that are wrong and seen by the monitor; threshold
0.05. A drill injects one fault per spot_check day, detected with probability r. The reviewer is perfect
and immediate, errors are independent at a constant p, and every proposal is approved (the most permissive
operator). Draws are md5 over the seed, the component, the day and the output, so the result is identical
on every run. Both rules use the staged review fractions, because no declared item states one (e1).

The `declared` rule is the controller with the declared shape: clearance 20 then 50, a 30-day clean signal
window to the top, no return leg, no signal demotion, no version restart, no drill. `staged` is the params
block. Each simulated day runs the controller SQL above, unchanged, over every component.

```yaml
simulation:
  seed: w1-c7
  days: 365
  n_per_day: 12
  signal_days: 7
  signal_threshold: 0.05
  reps: 20
  p: [0.005, 0.02, 0.05, 0.1, 0.2]
  recall: [1.0, 0.5]
  rules:
    declared: {clear_read_all: 20, clear_sampled: 50, clear_spot_check: 0, on_wrong: none, signal_demotes: false, signal_gates_promotion: false, version_restart: false, drill_min: 0, promotion_authority: auto}
    staged: {promotion_authority: auto}
```

```sql
CREATE TABLE sim_state AS
  SELECT 'c:' || p || ':' || r || ':' || i AS component, 'read_all' AS rung, CAST(1 AS BIGINT) AS entered_day, 'v1' AS version,
         CAST({signal_threshold} AS DOUBLE) AS signal_threshold, p, r AS recall
  FROM (SELECT unnest({p}) AS p) CROSS JOIN (SELECT unnest({recall}) AS r) CROSS JOIN range({reps}) t(i);
CREATE TABLE sim_out (component VARCHAR, day BIGINT, k BIGINT, wrong BOOLEAN, selected BOOLEAN, seen BOOLEAN, rung VARCHAR);
CREATE TABLE sim_rv (component VARCHAR, output_id VARCHAR, day BIGINT, version VARCHAR, rung VARCHAR, outcome VARCHAR);
CREATE TABLE sim_sg (component VARCHAR, day BIGINT, value DOUBLE);
CREATE TABLE sim_dr (component VARCHAR, day BIGINT, injected INT, detected INT);
CREATE TABLE sim_ap (component VARCHAR, to_rung VARCHAR, day BIGINT)
```

```sql
INSERT INTO sim_out
  SELECT component, {day}, k, u_w < p, rung = 'read_all' OR u_s < CASE rung WHEN 'sampled' THEN {f_sampled}
         WHEN 'spot_check' THEN {f_spot_check} ELSE {f_anomaly_triggered} END, u_d < recall, rung
  FROM (SELECT s.*, t.k,
               CAST('0x' || substr(md5(concat_ws(':', '{seed}', s.component, {day}, t.k, 'w')), 1, 8) AS UBIGINT) / 4294967296.0 AS u_w,
               CAST('0x' || substr(md5(concat_ws(':', '{seed}', s.component, {day}, t.k, 's')), 1, 8) AS UBIGINT) / 4294967296.0 AS u_s,
               CAST('0x' || substr(md5(concat_ws(':', '{seed}', s.component, {day}, t.k, 'd')), 1, 8) AS UBIGINT) / 4294967296.0 AS u_d
        FROM sim_state s CROSS JOIN range({n_per_day}) t(k));
INSERT INTO sim_rv
  SELECT component, component || ':' || day || ':' || k, day, 'v1', rung, CASE WHEN wrong THEN 'wrong' ELSE 'correct' END
  FROM sim_out WHERE day = {day} AND selected;
INSERT INTO sim_sg
  SELECT component, {day}, count(*) FILTER (WHERE wrong AND seen) / count(*)
  FROM sim_out WHERE day > {day} - {signal_days} AND day <= {day} GROUP BY component;
INSERT INTO sim_dr
  SELECT component, {day}, 1,
         CASE WHEN CAST('0x' || substr(md5(concat_ws(':', '{seed}', component, {day}, 'drill')), 1, 8) AS UBIGINT) / 4294967296.0 < recall
              THEN 1 ELSE 0 END
  FROM sim_state WHERE rung = 'spot_check';
CREATE OR REPLACE TABLE sim_act AS {controller};
UPDATE sim_state SET rung = a.to_rung, entered_day = {day} + 1
  FROM sim_act a WHERE a.component = sim_state.component AND a.action IN ('promote', 'demote', 'restart');
DELETE FROM sim_rv USING sim_state s WHERE sim_rv.component = s.component AND sim_rv.day < s.entered_day
```

```sql
SELECT s.p, s.recall,
       count(*) FILTER (WHERE o.wrong AND NOT o.selected) / count(*) AS aoq,
       count(*) FILTER (WHERE o.selected) / count(*) AS afi,
       count(*) FILTER (WHERE o.rung = 'anomaly_triggered') / count(*) AS top_share,
       count(DISTINCT o.component) FILTER (WHERE o.rung = 'anomaly_triggered') / count(DISTINCT o.component) AS reached_top
FROM sim_out o JOIN sim_state s USING (component)
GROUP BY s.p, s.recall ORDER BY s.p, s.recall
```

Result (VP 4; aoq is wrong outputs that escaped review per output; afi the share reviewed; reached_top the
share of components that ever reached anomaly_triggered):

| p | recall | declared aoq | declared afi | declared reached_top | staged aoq | staged afi | staged reached_top |
|---|---|---|---|---|---|---|---|
| 0.005 | 0.5 | 0.0049 | 0.029 | 1.00 | 0.0046 | 0.080 | 0.00 |
| 0.005 | 1.0 | 0.0047 | 0.032 | 1.00 | 0.0047 | 0.041 | 1.00 |
| 0.02 | 0.5 | 0.0182 | 0.041 | 1.00 | 0.0149 | 0.218 | 0.00 |
| 0.02 | 1.0 | 0.0192 | 0.035 | 1.00 | 0.0156 | 0.204 | 0.95 |
| 0.05 | 0.5 | 0.0460 | 0.068 | 0.95 | 0.0160 | 0.678 | 0.00 |
| 0.05 | 1.0 | 0.0456 | 0.079 | 0.40 | 0.0110 | 0.775 | 0.00 |
| 0.1 | 0.5 | 0.0822 | 0.196 | 0.15 | 0.0025 | 0.974 | 0.00 |
| 0.1 | 1.0 | 0.0820 | 0.190 | 0.00 | 0.0011 | 0.989 | 0.00 |
| 0.2 | 0.5 | 0.1199 | 0.400 | 0.00 | 0.0001 | 0.999 | 0.00 |
| 0.2 | 1.0 | 0.1070 | 0.461 | 0.00 | 0.0000 | 1.000 | 0.00 |

Read across: the declared rule's escape rate tracks p (0.107-0.120 at p=0.2); the staged rule's never
exceeds 0.016, because a bad component keeps returning to read_all (afi near 1). A half-blind monitor
helps a component up the declared ladder (p=0.05: 0.95 against 0.40) and never gets one to the staged
top. The price is review load on middling components: at p=0.02 the staged rule reviews 20-22% of outputs
against 3.5-4.1%, for an escape rate of 1.5-1.6% against 1.8-1.9%. Whether that trade is worth it is the
AOQL target, a seed (q3). Simplifications that matter: a real reviewer errs (R3), errors cluster after a
change (which version_restart addresses and the simulation does not exercise), and harm per escaped
output differs by component (R6).

## 3. Settled / contested / risk / open

### Settled (fixture s1-s3)

- s1 The rungs are read_all, sampled, spot_check and anomaly_triggered in that order (pilot model code, e1),
  and the transition decision is deterministic code over recorded reviews, never an LLM (Decision 55).
- s2 Measured: the 18 declared triggers are upward-only free text and no item states a review rate, so no
  controller can evaluate them as written (VP 1, VP 2).
- s3 Measured: without a return leg the declared triggers let escaped-wrong share track the error rate
  (0.12 at p=0.2) and promote half-blind monitors faster (VP 4). Any rule must bound outgoing quality and
  must not reward a weaker monitor; which rule does so is k1, k4 and k5.

### Contested (k1-k3 in the fixture; k4, k5 report-only, the fixture's contested list is capped at 3)

- k1 The return leg.
  - (a) Any wrong output found above read_all returns the component to read_all (CSP-1; v08).
  - (b) One rung down (multi-level plans; on_wrong one_down, v09).
  - (c) None, as the six items declare (on_wrong none, v10).
  Recommended: (a). It is the only option with a closed-form outgoing-quality bound, and the cost is review
  load on a component that just proved it errs. (c) is measured in VP 4. Precedent: none admissible; T3.4
  criterion 2 and T4.4 call for per-gate rollback (e8), but they are roadmap criteria, and the pilot schema
  today forbids a downward pair (e1). Class asked.
- k2 A version change (classifier_version, parser_version or params_version), the question #1396 and
  #1397 both defer here (e9).
  - (a) Restart at read_all with the new version (v18, v19).
  - (b) Drop one rung and keep counting.
  - (c) Keep the rung; the change rides on the existing sample.
  Recommended: (a). A rule-set change is a new process, and a clearance earned by the old rules says
  nothing about the new ones (the acceptance-sampling convention for a process change). Its cost falls on
  frequent small edits, so the build may want a declared cosmetic class (for example a rules-file comment)
  that does not bump the stamp. No precedent. Class asked.
- k3 Who moves a component.
  - (a) The operator approves every promotion (propose_promote until an approval exists, v01/v02);
    demotions and restarts apply automatically.
  - (b) Both automatic (promotion_authority auto, v27).
  - (c) The operator ratifies both, with only the record automatic (T4.4's last exit criterion reads this
    way for A-gates).
  Recommended: (a). A promotion loosens oversight and is rare; a demotion tightens it and must not wait for
  a human who may be away. No Decision or contract decides it. Class asked.
- k4 (report-only) The rule family and its seeds. (a) The staged multi-level CSP: consecutive clearance per
  rung with k1's return leg (as above). (b) A sequential probability ratio test per rung (Wald), which
  decides on all reviews, not runs, with stated error rates at two quality levels. (c) A fixed-sample
  bound: promote when the 95% upper bound on the error rate since rung entry is under a target. Also inside
  k4: unsure counts as a breaker (v05), an overdue sample is a breaker (v06), and a promotion needs a clean
  signal today (signal_gates_promotion, v20-v22). Recommended: (a) for the pilot, because its bound is
  closed-form and it matches what the siblings already wrote; revisit (b) if review volume is the
  constraint. Measurement is not precedent. Class asked.
- k5 (report-only) Monitor validation before anomaly_triggered. (a) A drill: drill_min injected faults
  during the spot_check stint, every one detected (v14, v16, v17). (b) Historical recall: the share of
  reviewer-found wrong outputs on whose day the signal breached, over at least m findings. (c) None, as
  declared. Recommended: (a). (b) cannot be computed for a component that rarely errs, and (c) is the
  half-blind result in VP 4. The drill for back-validation already exists in kind: #1397's VP 3 feeds known
  no-op fixes through the verdict SQL. No precedent. Class asked.

### Risks

- R1 Review load. At read_all the operator reviews every output: at 12 a day for each of six components,
  about 72 reviews a day, and a component that keeps returning stays there (VP 4 afi near 1 at p >= 0.1).
  Unreviewed samples hold the ladder by construction (review_overdue), so an absent operator freezes
  promotion rather than loosening review.
- R2 Predictable sampling. md5 selection over a known salt lets anyone who knows the salt see which
  outputs will be reviewed. The producers are deterministic SQL today, so the risk is a future adaptive
  producer; the salt is per component and version and can be withheld from the producer.
- R3 Reviewer error. Clearance trusts the review outcome. A reviewer who confirms everything inflates it;
  seeded known-wrong outputs in the review stream (a reviewer drill) would measure that. Named for the
  Goodhart register.
- R4 Small daily denominators. At about 12 outputs a day a daily share threshold of 0.05 is an "any error"
  alarm (one wrong output is 0.083). The declared signal triggers name thresholds but not windows; T4.4
  asks for both (e8). The simulation uses a 7-day window.
- R5 Coupled components. An upstream component at read_all (capture, reader verbs) makes a downstream
  component's review outcomes partly about its inputs. A rung ceiling by dependency is W2's question
  (section 5).
- R6 Unequal harm. One escaped wrong proof close (back-validation) costs more than one escaped mislabel.
  The AOQL target may need to be per component; the Goodhart register owns the weights.

### Open questions (q1-q3 in the fixture, q4 report-only)

- q1 Is this ladder T3.4's A0-A3 (executor autonomy gates) or a separate per-component review ladder that
  shares the controller? T3.4 and T4.4 describe autonomy of the executor; these rungs describe how much of
  a loop component's output a human reviews. Recommended reading: separate ladders, one controller, and
  T4.4's numeric pinning (threshold, denominator, window, source) applied to both.
- q2 Where review records, transition records and the current rung live. Nothing reads a rung today (e3).
  Shares rec-filing q4 (Decision 199 journal recommended there) and back-validation q4.
- q3 Seeds are unmeasured: AOQL target (2% assumed), clearances 40/40/20, fractions 0.2/0.04/0.008,
  review_sla_days 3, dark_days 2, a 30-day window, 10 drill faults; operator review capacity at read_all.
- q4 (report-only) Is a failure_signal breach at sampled a demotion or only a hold? The staged rule
  demotes one rung (v11). A component whose signal and reviews disagree needs a reviewer's look either way.

### Named for owners, not filed (Decision 67)

- O1 Pilot schema (evaluator owner): Maturity cannot express a return leg, a review fraction or a version
  rule, and Trigger.metric is free text (e1, e2). Whatever k1, k4 and k5 decide needs a schema change
  before any item can declare it; until then the fixture records the forks, not the rule.
- O2 T3.4 exit criterion 2 grounds its rollback requirement on "Decision 92 points 6-9", but Decision 92 is
  the agent-native Terraform CI/CD ratification and no Decision mentions MED-9 (grep). The anchor looks
  stale (inferred; the roadmap owner should confirm).

## 4. Consideration register (as authored in the fixture)

- why: the six items' 18 triggers are upward-only free text with no review rate (VP 1, VP 2), so promotion
  measures patience, and a blinder monitor promotes faster (VP 4).
- how: one SQL per daily run over the review log, failure_signal series, drills and approvals per component
  returns promote, propose_promote, hold, demote or restart with a reason; the rule's legs are k1-k5.
- planes: data_plane (it runs over the customer's own review and telemetry rows; rung and transition
  counts are candidates for the rec-4141 allow-list, not decided here).
- maturity: the controller is itself a component. read_all means every transition is a proposal the
  operator re-derives before any rung moves (c3). read_all -> sampled at >= 40 controller decisions the
  operator re-derived unchanged since the last overturned one; sampled -> spot_check at >= 40 more on a
  1-in-5 sample; spot_check -> anomaly_triggered at >= 30 consecutive days with stale_rung_days 0 and
  escaped_wrong_share at or under the AOQL target (q3). These are clearance counts; their return leg is k1,
  which the schema cannot yet express (O1).
- failure_signal: a component sits at a rung its own evidence contradicts. Metric: escaped_wrong_share
  (wrong outputs found by the audit floor or a breach review, per output, at rungs above read_all) beside
  stale_rung_days (days a demote condition held with no transition recorded). Source: the review log and
  the transition log (q2).
- verification: c1 (the SQL passes these vectors over the build's tables, each transition record carrying
  reason, counts and params_version), c2 (a seeded simulation through the controller keeps escaped-wrong
  share at or under the AOQL target at every error rate and never promotes a component whose drill misses),
  c3 (the operator's read_all review of every transition). All open.
- rollback: stop the schedule and set every component to read_all; the transition log stays as history and
  review returns to 100% until a controller resumes. Failing safe means more review, never less.
- edges: part_of T3.4 (exit criterion 2: gates with a per-gate rollback criterion); depends_on T2.36 (the
  inputs are telemetry reader rows on DuckLake, like every sibling).

## 5. Boundary notes for W2 synthesis

- Rec filing (W1-5, #1396): its k2 recommendation surfaces the suppressed-sessions trend "to the
  maturity-ladder controller"; here that trend is a failure_signal input, and a breach demotes (v11). Its
  rejected_share is the review outcome stream (rejected = wrong). Its params_version change restarts the
  ladder under k2 (a). Its read_all files nothing, so a read_all review is a review of proposals.
- Back-validation (W1-6, #1397): "close_proposed until anomaly_triggered" makes this controller the gate for
  direct proof closes. Under k5 (a) its drill is its own VP 3 simulation run on known no-op fixes: a holds
  on a drill fix is a missed detection. Its spot_check -> anomaly_triggered trigger (false_proof_rate over 90
  days with at least 20 proof closes) is a signal window in this vocabulary. Same k2 answer.
- Friction classifier (W1-3, #1394): its version stamp is classifier_version, and every rules edit bumps
  it; under k2 (a) that restarts the ladder, which is why k2 suggests a cosmetic class. Its precision comes
  only from label review (its q2), so its review log is the controller's main input.
- Deliberation capture (W1-4, #1395): deliberation_drift_share is "undefined, never 0" when nothing is
  classified; the controller reads undefined as dark, so a silent producer demotes rather than looks clean.
- Capture producer wiring (W1-1, #1384) and reader verbs (W1-2, #1390): upstream of everything. W2 should
  decide a rung ceiling by dependency (a component's rung at most its upstream's, or one above), using the
  pilot depends_on edges W2 adds.
- Goodhart register (later W1): R3 (reviewer drift) and R6 (unequal harm) belong there, and each
  component's failure_signal is the controller's signal input, so a detector's failure_signal in that
  register and here must be one series.
- Cost/egress budget (later W1): review load is the controller's cost; afi times output volume is the
  number of human reviews a day.
- Contradiction for W2: the six items write first-rung clearances of 20 and 50 and second-rung windows of
  30 to 200. One controller needs one rule family (k4) with per-component seeds, or the inventory stays
  six dialects.

## 6. Staged candidate decision text (for W3; not filed)

"A loop component's review rung moves only by a deterministic controller over recorded reviews. Every
upward transition is paired with a return leg: a wrong output found above read_all returns the component
to read_all, a failure_signal that breaches or goes dark demotes it, and a rule-set version change
restarts it at read_all. Promotion needs operator approval; demotion and restart apply on the run that
finds them. The top rung needs a passed monitor drill. Thresholds are stated with their denominator,
window and source."
