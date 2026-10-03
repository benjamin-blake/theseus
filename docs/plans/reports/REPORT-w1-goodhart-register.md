# REPORT: W1 component 9 - Goodhart register (a counter series and a seeded drill for every failure_signal)

Plan: docs/plans/PLAN-w1-goodhart-register.yaml. Fixture item: pwi-goodhart-register (1 of 12 cap).
REPORT-ONLY (Decision 86 cl.2): nothing here is built, filed, ratified or flipped. Every table, verb, schema
change and drill named below describes a future build. The eight sibling W1 components (#1384, #1390,
#1394-#1399) are unmerged: they are read here as evidence at pinned heads, never cited as precedent.

## 0. Verdict

The charter asks that every loop component carry its own failure_signal, and every W1 item does: the pilot
schema requires one (scripts/checks/roadmap/_work_item_pilot_model.py:162). The Goodhart question is the next
one: when that signal looks good, how would we know it is the signal, and not the work, that improved?
Decision 196 clause 7 puts the same question to Tier A decisions ("how would we know we have overfit to
this?"); it binds there, and is used here only by analogy. This component answers it per detector and
measures the answers.

Measured, not argued:

- Every W1 failure_signal is lower-is-better, and every one is read as a promotion trigger by its own item.
  In 7 of 8 items the top-rung trigger (spot_check -> anomaly_triggered) names the item's own failure_signal
  metric; the eighth (#1390) reads "zero mismatches", which is its metric in other words (VP 1).
- The signals carry little protection against their own blind spots. 4 of 8 name a companion series read
  "beside" them, 1 of 8 (#1399's canary) names a seeded known-positive, and 0 of 8 top-rung triggers check
  the recall of the signal they promote on (VP 1). The maturity-ladder report (#1398, unmerged) measured the
  consequence: a monitor that sees half the errors reaches the top rung in 58 of 60 simulated components
  against 25 of 60 for a perfect one, because a signal that sees less breaches less.
- For every one of the 8 detectors there is a cheap path: a change that lowers the failure_signal without
  lowering the failures it names. Five of them come from the siblings' own reports (lost single-turn
  sessions, lumped signatures, consistent misclassification, filing less, rubber-stamp review); three are
  derived here (a common-mode harness, a regression path made blind by a stricter
  filer, a canary seeded where it cannot reach). In a model of each, the cheap path lowers the primary
  metric in 8 of 8, and in 8 of 8 it buys at least as much as a real halving of the failure rate (within
  0.001), so the primary metric alone cannot tell gaming from improvement (VP 3).
- The declared companions do not close that gap. Two of the four are computable series in the model
  (#1396's non-filing counts and #1397's unmeasurable_share); under their own item's cheap path one moves
  (#1396) and one does not (#1397). #1398's stale_rung_days and #1399's withheld share read quantities the
  cheap path does not touch (section 2.3). #1394's c2 guard is static and, as its text reads, passes under
  lumping (inferred).
- A counter per detector does. Each register row names a counter series from a source other than the
  primary's own numerator: a recall measured on seeded known-positives (five rows), a coverage share
  (capture against an out-of-band session count; the canary against the columns it must reach), or a
  consistency check the producer cannot satisfy by misclassifying (deliberation). In the model each counter falls under its floor on the cheap path in 8 of 8 and holds at
  or above its floor on a real improvement in 8 of 8 (VP 3). That split is the register's job.
- Nothing reads any of this today. No file under src/ or scripts/ other than the pilot model and its
  evaluator names failure_signal or Goodhart, and none of the six telemetry contracts carries a field that
  marks a seeded (drill) row (VP 2).

Staged, not decided: one register row per detector (section 2.2) and one deterministic SQL per daily run
(section 2.4) that reads the register, a daily (primary, counter) series per detector and a drill log, and
returns one verdict per detector: ok, dark, breach, counter_dark, counter_low, undrilled, blind,
diverging, upstream_unsound or unregistered. A detector is ok only when its own signal, counter and drill
are sound and so is every detector upstream of it; a series with no register row reads unregistered. It
passes 45/45 vectors, fifteen by raising on malformed input (VP 4), and each of 21 mutants fails at least
one named vector (VP 4). The maturity-ladder controller would read the verdict as an input; what a non-ok
verdict does to a rung is k1.

What is settled is narrow: a failure_signal per item and its Goodhart reading (pilot model code; Decision 196
clause 7 by analogy, section 3), the register's place in the data plane (Decision 209 clause 2(a)), and the
measured facts above. How a verdict acts on the ladder (k1), how drills run (k2), where counters are
declared (k3), harm weights (k4), the fixture's edge home (k5) and the divergence rule (k6) all weigh
credible alternatives with no admissible precedent: they are parked as asked. None touches IAM, security,
spend or a governed deploy.

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | The eight sibling items, read at their pinned heads, carry 8 failure_signals; the register has one row per item and each row's metric equals the item's failure_signal.metric verbatim [VP 1] | the siblings and register blocks |
| e2 | 4 of 8 failure_signals name a companion read "beside" them (#1396, #1397, #1398, #1399); 1 of 8 names a seeded, canary, drill or injected known-positive (#1399) [VP 1] | sibling fixtures |
| e3 | In 7 of 8 items the spot_check -> anomaly_triggered trigger names the item's own failure_signal metric (#1390 reads "zero mismatches"); 0 of 8 such triggers names a recall or a drill [VP 1] | sibling fixtures |
| e4 | The pilot FailureSignal model is three free-text fields (signal, metric, source): no counter, drill or recall field exists | scripts/checks/roadmap/_work_item_pilot_model.py:162 |
| e5 | No file under src/ or scripts/ other than the pilot model and its evaluator names failure_signal or goodhart; the six telemetry contracts carry 0 synthetic or drill markers [VP 2] | repository grep |
| e6 | In the per-detector model, each cheap path lowers the primary (8/8) by at least as much as a real halving of the failure rate (8/8 within 0.001); each counter falls under its floor on the cheap path (8/8) and holds on the real improvement (8/8); 2 declared companions are computable and 1 of them moves [VP 3] | section 2.3 |
| e7 | The staged verdict SQL passes 45 vectors, 15 by raising with the stated message [VP 4] | section 2.5 |
| e8 | Each of 21 mutants of the verdict SQL replaces one unique site and fails at least one named vector [VP 4] | section 2.6 |
| e9 | #1398 (unmerged) measured that a half-blind monitor reaches the top rung in 58 of 60 components at a 5% error rate, against 25 of 60 at recall 1.0, and named reviewer error (R3) and unequal harm (R6) for this register | REPORT-w1-maturity-ladder.md section 0 and Risks, at f6183430 |
| e10 | Four sibling reports carry a Goodhart paragraph naming a cheap path and a guard (#1394, #1395, #1396, #1397); #1384 section 4 names its own blind spot; five (#1394-#1398) name what they hand to this register | sibling reports at the pinned heads |
| e11 | The producer writes a hook row's severity from its exit code: 2 is error, 0 or a missing code is info, anything else warning; an info row is outside unmapped_failure_share's denominator | src/turn_capture/observations.py:311 |
| e12 | Decision 73 halt check: the reader's named verb ci_rca_open returned [] at 2026-10-03T17:44:32Z | Step 0 |

Sibling heads read by VP 1 (pinned by sha, so a later push to a sibling branch does not change the reading):

```yaml
siblings:
  - {pr: 1384, item: pwi-capture-producer-wiring, head: 1da1cc97f3522e5551ab32bcb41e3bb5b93cf685}  # pragma: allowlist secret
  - {pr: 1390, item: pwi-telemetry-reader-verbs, head: ab7aad7a36819a10069628577a55b2160cf8bd81}  # pragma: allowlist secret
  - {pr: 1394, item: pwi-friction-classifier, head: c6a47c5df5c1e50c7ab77730dadbe4456965772d}  # pragma: allowlist secret
  - {pr: 1395, item: pwi-deliberation-capture, head: 63b1a50a6926561aac5fb5a9c651c6faba581dc5}  # pragma: allowlist secret
  - {pr: 1396, item: pwi-rec-filing-dedupe, head: 51958a0ae48a700963fc5b1351fed00e6a1decec}  # pragma: allowlist secret
  - {pr: 1397, item: pwi-back-validation, head: 75ad2896d79d7d83f91ddcb619a183972a716351}  # pragma: allowlist secret
  - {pr: 1398, item: pwi-maturity-ladder-controller, head: f618343030ac07ffeab13c0ca2288577ad5d22db}  # pragma: allowlist secret
  - {pr: 1399, item: pwi-allow-list-transport, head: 03feaf12dda0bdb6ea8718ccdff85e931e83a942}  # pragma: allowlist secret
```

### 1.1 What the inventory shows

Every sibling chose its failure_signal for a good reason; four wrote a Goodhart paragraph for it and a
fifth named its own blind spot.
What none of them can do from inside its own item is measure whether its signal still sees: a signal is
read by the same item whose output it judges, it is lower-is-better, and its top-rung trigger rewards a low
value. That is Goodhart's law in its regressional and adversarial forms at once (Manheim and Garrabrant's
taxonomy): optimisation pressure on a proxy selects for the proxy's blind spots, whether anyone intends it
or not. Most of the cheap paths below are not cheats. A single-turn session lost on reclaim, a rule that
grew too broad, a reviewer who got tired: each lowers a signal by accident, and the ladder then promotes on it.

The industry answers are old and consistent: pair every optimised metric with a guardrail metric that moves
the other way when the first is gamed (A/B-testing practice), measure a detector's recall by injecting
known faults rather than by waiting for real ones (fault injection, canary tokens, honeypots, seeded defects
in software inspection), and never let a monitor's own output be the only evidence that the monitor works.
This register applies those three to each W1 detector.

## 2. Register design (what this item stages)

### 2.1 What a register row answers

For each detector, five questions:

1. What decides on it (decides): the ladder's rungs for its own component, plus whatever the component
   itself gates (a proof close, a filing, an egress batch).
2. What its cheapest improvement is that does not reduce the failure it names (cheap_path).
3. What the item already declares against that (declared_guard), read from its own fixture and report.
4. A counter series from a source other than the primary's numerator, oriented higher-is-better in
   [0, 1], with a floor (counter, counter_floor). Independence is the point: a counter computed by the same
   code from the same rows as the primary inherits its blind spot (risk R2).
5. A drill: a seeded known-positive whose detection the verdict reads as recall (drill). Five rows' counters
   are themselves drill recalls; the other three (capture, deliberation, allow-list) carry a counter series
   and a separate drill.

Plus its upstream detectors: the components whose output feeds the primary's numerator or denominator. A
detector is no sounder than its inputs.

### 2.2 The register

Counter floors are seed values (q2), the same 0.99 for every row. Each row's breach threshold is the one its
own item's top-rung trigger already names (0.05 for capture, friction, rec filing and back-validation;
0.01 for deliberation; 0 for reader verbs and the canary; the AOQL target for the ladder, its q3); the
register reads those, it does not set them.

```yaml
register:
  - detector: pwi-capture-producer-wiring
    pr: 1384
    metric: 'unfinalized_session_share: root sessions whose latest lifecycle row is not close 24 h after their last event'
    decides: its own rungs; and every W1 rate, because landed sessions are their denominator
    cheap_path: 'Lose the failing sessions: a single-turn session killed before SessionEnd lands no row, so it leaves numerator and denominator alike (its report, section 4)'
    declared_guard: none in the failure_signal; its report says the top rung must not promote on it until its q1 out-of-band denominator exists
    counter: 'landed_share: root sessions landed / root sessions counted out of band (the q1 denominator, from a source other than the capture runner)'
    counter_floor: 0.99
    drill: replay seeded transcripts killed at each lifecycle point, single-turn included; each must read as unfinalized
    upstream: []
  - detector: pwi-telemetry-reader-verbs
    pr: 1390
    metric: 'verb_rederivation_mismatch_rate: sampled sessions whose verb output differs from the harness re-derivation'
    decides: its own rungs; and every consumer of derived state, duration and roll-ups
    cheap_path: 'Common-mode re-derivation: a harness that shares the verb''s derivation agrees with its wrong outputs, so mismatches vanish'
    declared_guard: none for state, duration and roll-ups; the conflict stamp covers the dedupe leg only (its q2)
    counter: 'harness_kill_rate: seeded wrong derivations the shadow harness flags / seeded wrong derivations'
    counter_floor: 0.99
    drill: mutant derivations of state, duration and each roll-up injected into the shadow comparison
    upstream: [pwi-capture-producer-wiring]
  - detector: pwi-friction-classifier
    pr: 1394
    metric: 'unmapped_failure_share: non-info process_events labelled only by a generic rule, per classifier_version'
    decides: its own rungs; and the friction totals rec filing and back-validation read
    cheap_path: 'Lumping: the specific rule of one exact, registered signature absorbs failures of unrelated kinds (its q3: a name-only key merges unrelated Bash errors)'
    declared_guard: the c2 rules-file guard (no wildcard, registered signature), which is static and passes under lumping
    counter: 'drill_label_recall: seeded failure events of a kind no rule names that come out generic / seeded events'
    counter_floor: 0.99
    drill: synthetic process_events with known labels, including kinds no rule names, through session_friction_rollup
    upstream: [pwi-capture-producer-wiring, pwi-telemetry-reader-verbs]
  - detector: pwi-deliberation-capture
    pr: 1395
    metric: 'deliberation_drift_share: drifted/classified model_calls, undefined (never 0) if none; per producer, parser_version'
    decides: its own rungs; and the deliberation metrics T3.3 reads beside outcomes
    cheap_path: 'Consistent misclassification: a producer declares none and writes no thinking row while reasoning_tokens > 0 (its report names this lever)'
    declared_guard: visibility_missing drift and write-time NOT NULL; none with reasoning tokens has no read-side arm (its report)
    counter: 'visibility_consistency: 1 - (classified model_calls declaring none with reasoning_tokens > 0) / classified model_calls'
    counter_floor: 0.99
    drill: seeded model_call rows for each drift kind and for none-with-tokens, through the drift monitor
    upstream: [pwi-capture-producer-wiring, pwi-telemetry-reader-verbs]
  - detector: pwi-rec-filing-dedupe
    pr: 1396
    metric: rejected_share (operator marks covered, duplicate or reject) per 30 days per detector, beside run liveness
    decides: its own rungs; and which findings become recs (T3.3's false-positive rate, audit F-035)
    cheap_path: 'File only near-certain findings: a higher min_sessions stops spurious filings and silently drops real recurring findings'
    declared_guard: hold, suppressed and over_budget counts in every run record, read beside it; no threshold reads them
    counter: 'drill_file_recall: seeded recurring findings at the declared min_sessions that are proposed or filed / seeded findings'
    counter_floor: 0.99
    drill: a synthetic recurring finding per detector at the declared thresholds, fingerprinted under a drill detector_id
    upstream: [pwi-telemetry-reader-verbs, pwi-friction-classifier, pwi-deliberation-capture]
  - detector: pwi-back-validation
    pr: 1397
    metric: false_proof_rate (regressions within 28 days of a proof close / proof closes) beside unmeasurable_share, per 90 days
    decides: its own rungs; and whether a filer rec closes on proof (T3.4)
    cheap_path: 'Regression blindness: a stricter filer files regressions late or never, so false proofs stop being counted while unmeasurable_share holds'
    declared_guard: unmeasurable_share and the fails share beside it, which catch proving nothing but not a blind regression path
    counter: 'drill_regression_recall: seeded no-op fix closes whose re-seeded recurrence files a regression within 28 days / seeded closes'
    counter_floor: 0.99
    drill: known no-op fixes (its VP 3 kind) closed under a drill rec, with their friction re-seeded after the close
    upstream: [pwi-rec-filing-dedupe, pwi-friction-classifier]
  - detector: pwi-maturity-ladder-controller
    pr: 1398
    metric: 'est_escaped_share: audited wrong share x unreviewed share, rolling 30 days, per component above read_all'
    decides: every component's rung, so how much of each component's output a human reviews
    cheap_path: 'Rubber-stamp review: a reviewer confirms wrong outputs as correct, so the audited wrong share and the estimate fall (its R3)'
    declared_guard: stale_rung_days beside it (controller lag, not review quality); its drill gates the top rung only (its k5)
    counter: 'reviewer_drill_recall: seeded known-wrong outputs in the review stream marked wrong / seeded outputs'
    counter_floor: 0.99
    drill: known-wrong outputs mixed into each component's review sample, unmarked to the reviewer
    upstream: []
  - detector: pwi-allow-list-transport
    pr: 1399
    metric: 'canary_leaks: tokens of the seeded per-run canary row found in the egress batch; must be 0'
    decides: its own rungs; and whether an egress batch crosses to the control plane
    cheap_path: 'Seed where it cannot reach: a canary written only into columns the egress drops reads 0 whatever the egress leaks'
    declared_guard: the withheld share per column beside it (out-of-vocabulary enum values, not canary placement)
    counter: 'canary_coverage: non-denied string columns carrying the canary this run / non-denied string columns'
    counter_floor: 0.99
    drill: a positive-control run through a known-leaky egress (its mutant m01) that must report leaks above 0
    upstream: [pwi-telemetry-reader-verbs]
```

### 2.3 Cheap-path scenarios (VP 3)

Each scenario is a small deterministic world (DuckDB, `range()` only, no randomness) built from the
detector's own definition of its primary metric. It is evaluated three ways: the baseline (`cheap=0,
better=0`); the cheap path (`cheap=1`), which in five rows hides half of the failures the detector sees and in
three applies the stated change (a min_sessions of 8 instead of 3 for rec filing and back-validation; the
canary seeded only into denied columns); and a real improvement (`better=1`) that halves the true failure
rate (for the canary, one of two leaking columns fixed) and leaves detection alone. Where seeded drill
rows appear (`drill`), they are excluded from the primary, as a build must exclude them (k2). The
claim is not the numbers, which are constructed: it is the direction of each counter under each world.

```yaml
scenarios:
  params: {declared_tolerance: 0.01, as_good_as_real_tolerance: 0.001}
  cases:
    - detector: pwi-capture-producer-wiring
      world: "SELECT i, i % (20 * (1 + {better})) = 0 AS unfinalized, NOT (i % 20 = 0 AND {cheap} = 1 AND i % 40 = 0) AS landed FROM range(1000) t(i)"
      primary: "SELECT count(*) FILTER (WHERE landed AND unfinalized)::DOUBLE / count(*) FILTER (WHERE landed) FROM u"
      counter: "SELECT count(*) FILTER (WHERE landed)::DOUBLE / count(*) FROM u"
      declared: null
    - detector: pwi-telemetry-reader-verbs
      world: "SELECT i, i >= 1000 AS drill, (i >= 1000 OR i % (20 * (1 + {better})) = 0) AND NOT ({cheap} = 1 AND CASE WHEN i >= 1000 THEN i % 2 = 0 ELSE i % 40 = 0 END) AS mismatch FROM range(1040) t(i)"
      primary: "SELECT count(*) FILTER (WHERE mismatch)::DOUBLE / count(*) FROM u WHERE NOT drill"
      counter: "SELECT count(*) FILTER (WHERE mismatch)::DOUBLE / count(*) FROM u WHERE drill"
      declared: null
    - detector: pwi-friction-classifier
      world: "SELECT i, i >= 1000 AS drill, CASE WHEN (i >= 1000 OR i % (20 * (1 + {better})) = 0) AND NOT ({cheap} = 1 AND CASE WHEN i >= 1000 THEN i % 2 = 0 ELSE i % 40 = 0 END) THEN 'generic' WHEN i >= 1000 OR i % (20 * (1 + {better})) = 0 THEN 'specific:broad' ELSE 'specific:exact' END AS label FROM range(1040) t(i)"
      primary: "SELECT count(*) FILTER (WHERE label = 'generic')::DOUBLE / count(*) FROM u WHERE NOT drill"
      counter: "SELECT count(*) FILTER (WHERE label = 'generic')::DOUBLE / count(*) FROM u WHERE drill"
      declared: null
    - detector: pwi-deliberation-capture
      world: "SELECT i, CASE WHEN {cheap} = 1 AND i % 40 = 0 THEN 'none' ELSE 'summarized' END AS visibility, i % (20 * (1 + {better})) <> 0 AS has_thinking_row, 100 + i % 7 AS reasoning_tokens FROM range(1000) t(i)"
      primary: "SELECT count(*) FILTER (WHERE visibility IS NULL OR (visibility IN ('full', 'summarized') AND NOT has_thinking_row) OR (visibility = 'none' AND has_thinking_row))::DOUBLE / count(*) FROM u"
      counter: "SELECT 1 - count(*) FILTER (WHERE visibility = 'none' AND reasoning_tokens > 0)::DOUBLE / count(*) FROM u"
      declared: null
    - detector: pwi-rec-filing-dedupe
      world: "SELECT i, i >= 1000 AS drill, i >= 1000 OR i % (4 * (1 + {better})) <> 0 AS real, CASE WHEN i >= 1000 THEN 5 WHEN i % (4 * (1 + {better})) = 0 THEN 1 + i % 3 ELSE 1 + i % 10 END AS sessions, CASE WHEN {cheap} = 1 THEN 8 ELSE 3 END AS min_sessions FROM range(1040) t(i)"
      primary: "SELECT count(*) FILTER (WHERE sessions >= min_sessions AND NOT real)::DOUBLE / count(*) FILTER (WHERE sessions >= min_sessions) FROM u WHERE NOT drill"
      counter: "SELECT count(*) FILTER (WHERE sessions >= min_sessions)::DOUBLE / count(*) FROM u WHERE drill"
      declared: {series: "SELECT count(*) FILTER (WHERE sessions < min_sessions)::DOUBLE / count(*) FROM u WHERE NOT drill", worse_if: higher}
    - detector: pwi-back-validation
      world: "SELECT i, i >= 1000 AS drill, i >= 1000 OR i % (10 * (1 + {better})) = 0 AS no_op, CASE WHEN i >= 1000 THEN 5 ELSE 2 + i % 7 END AS recurring_sessions, CASE WHEN {cheap} = 1 THEN 8 ELSE 3 END AS min_sessions, i < 1000 AND i % 25 = 0 AS unmeasurable FROM range(1040) t(i)"
      primary: "SELECT count(*) FILTER (WHERE no_op AND recurring_sessions >= min_sessions)::DOUBLE / count(*) FROM u WHERE NOT drill AND NOT unmeasurable"
      counter: "SELECT count(*) FILTER (WHERE recurring_sessions >= min_sessions)::DOUBLE / count(*) FROM u WHERE drill"
      declared: {series: "SELECT count(*) FILTER (WHERE unmeasurable)::DOUBLE / count(*) FROM u WHERE NOT drill", worse_if: higher}
    - detector: pwi-maturity-ladder-controller
      world: "SELECT i, i >= 1000 AS drill, (i >= 1000 OR i % (20 * (1 + {better})) = 0) AND NOT ({cheap} = 1 AND CASE WHEN i >= 1000 THEN i % 2 = 0 ELSE i % 40 = 0 END) AS marked_wrong, 0.8 AS unreviewed_share FROM range(1040) t(i)"
      primary: "SELECT count(*) FILTER (WHERE marked_wrong)::DOUBLE / count(*) * any_value(unreviewed_share) FROM u WHERE NOT drill"
      counter: "SELECT count(*) FILTER (WHERE marked_wrong)::DOUBLE / count(*) FROM u WHERE drill"
      declared: null
    - detector: pwi-allow-list-transport
      world: "SELECT i, i < 12 AS denied, i = 40 OR (i = 60 AND {better} = 0) AS leaks, i < 12 OR {cheap} = 0 AS seeded FROM range(73) t(i)"
      primary: "SELECT count(*) FILTER (WHERE leaks AND seeded)::DOUBLE FROM u"
      counter: "SELECT count(*) FILTER (WHERE seeded)::DOUBLE / count(*) FROM u WHERE NOT denied"
      declared: null
```

| detector | primary base / cheap / real | counter base / cheap / real | declared companion |
|---|---|---|---|
| capture | 0.0500 / 0.0256 / 0.0250 | 1.000 / 0.975 / 1.000 | none |
| reader verbs | 0.0500 / 0.0250 / 0.0250 | 1.000 / 0.500 / 1.000 | none (conflict stamp: dedupe leg only) |
| friction | 0.0500 / 0.0250 / 0.0250 | 1.000 / 0.500 / 1.000 | c2 guard is static: passes under lumping |
| deliberation | 0.0500 / 0.0250 / 0.0250 | 1.000 / 0.975 / 1.000 | none for none-with-tokens |
| rec filing | 0.1215 / 0.0000 / 0.0566 | 1.000 / 0.000 / 1.000 | non-filing share 0.317 -> 0.750: moves (no threshold reads it) |
| back-validation | 0.0708 / 0.0125 / 0.0354 | 1.000 / 0.000 / 1.000 | unmeasurable_share 0.040 -> 0.040: does not move |
| maturity ladder | 0.0400 / 0.0200 / 0.0200 | 1.000 / 0.500 / 1.000 | stale_rung_days reads controller lag, not review |
| allow-list | 2 / 0 / 1 | 1.000 / 0.000 / 1.000 | withheld share reads enum values, not seeding |

Two results matter. First, in five rows the cheap path and the real improvement give the same primary
(within 0.0006), and in three (rec filing, back-validation, allow-list) the cheap path looks better than the
real improvement: a ladder promoting on the primary prefers the gamed component. Second, every counter
separates the two worlds, and no declared companion does except #1396's run-record counts, which nothing
reads with a threshold.

### 2.4 The verdict (staged)

One SQL per daily run. Inputs (all build-time objects; q1): `{register}` one row per detector (detector,
threshold, counter_floor, drill_min, drill_recall_min, upstream); `{signal}` one row per detector per day
(primary_value and counter_value, each NULL when undefined); `{drills}` one row per drill run (detector,
day, injected, detected). Params are data, stamped on every verdict record (seeds, q2): a 28-day window
read as two 14-day halves, eps 0.01 on each half-mean. Malformed input raises instead of deciding (fail
loud, Decision 55 by analogy): a duplicate or incomplete register row, drill_min below 1 (every row must be
drilled), a recall floor outside (0, 1], an upstream that names no register row, an upstream cycle
(self-loop included), a signal row with a NULL key or a duplicate day, and a drill row with a NULL field, a
negative count, more detected than injected, or no register row. A sentinel row makes the guard fire even
when no detector row would be returned (e13).

```yaml
verdict:
  params: {window_days: 28, half_days: 14, eps_primary: 0.01, eps_counter: 0.01}
  sql: |
    WITH RECURSIVE
    edge AS (SELECT detector AS d, unnest(upstream) AS u FROM {register}),
    reach(d, u, depth) AS (
      SELECT d, u, 1 FROM edge
      UNION ALL
      SELECT r.d, e.u, r.depth + 1 FROM reach r JOIN edge e ON e.d = r.u
      WHERE r.depth < (SELECT count(*) FROM {register})
    ),
    g AS (
      SELECT
        (SELECT count(*) - count(DISTINCT detector) FROM {register})
        + (SELECT count(*) FROM {register} WHERE detector IS NULL OR threshold IS NULL OR counter_floor IS NULL
             OR drill_min IS NULL OR drill_recall_min IS NULL OR upstream IS NULL
             OR drill_min < 1 OR drill_recall_min <= 0 OR drill_recall_min > 1) AS bad_register,
        (SELECT count(*) FROM edge WHERE u IS NULL OR u NOT IN (SELECT detector FROM {register})) AS bad_upstream,
        (SELECT count(*) FROM reach WHERE d = u) AS cycle,
        (SELECT count(*) FROM {signal} WHERE detector IS NULL OR day IS NULL)
        + (SELECT count(*) FROM (SELECT detector, day FROM {signal} GROUP BY ALL HAVING count(*) > 1)) AS bad_signal,
        (SELECT count(*) FROM {drills} WHERE detector IS NULL OR day IS NULL OR injected IS NULL OR detected IS NULL
             OR injected < 0 OR detected < 0 OR detected > injected
             OR detector NOT IN (SELECT detector FROM {register})) AS bad_drills
    ),
    w AS (SELECT * FROM {signal} WHERE day > {today} - {window_days} AND day <= {today}),
    s AS (
      SELECT r.detector, any_value(r.threshold) AS threshold, any_value(r.counter_floor) AS counter_floor,
             any_value(r.drill_min) AS drill_min, any_value(r.drill_recall_min) AS drill_recall_min,
             arg_max(w.primary_value, w.day) FILTER (WHERE w.primary_value IS NOT NULL) AS p_last,
             arg_max(w.counter_value, w.day) FILTER (WHERE w.counter_value IS NOT NULL) AS c_last,
             avg(w.primary_value) FILTER (WHERE w.day <= {today} - {half_days}) AS p_early,
             avg(w.primary_value) FILTER (WHERE w.day > {today} - {half_days}) AS p_late,
             avg(w.counter_value) FILTER (WHERE w.day <= {today} - {half_days}) AS c_early,
             avg(w.counter_value) FILTER (WHERE w.day > {today} - {half_days}) AS c_late
      FROM {register} r LEFT JOIN w ON w.detector = r.detector
      GROUP BY r.detector
    ),
    dr AS (
      SELECT r.detector, coalesce(sum(d.injected), 0) AS inj, coalesce(sum(d.detected), 0) AS det
      FROM {register} r LEFT JOIN {drills} d ON d.detector = r.detector AND d.day > {today} - {window_days} AND d.day <= {today}
      GROUP BY r.detector
    ),
    own AS (
      SELECT s.detector,
        CASE
          WHEN s.p_last IS NULL THEN 'dark'
          WHEN s.p_last > s.threshold THEN 'breach'
          WHEN s.c_last IS NULL THEN 'counter_dark'
          WHEN s.c_last < s.counter_floor THEN 'counter_low'
          WHEN dr.inj < s.drill_min THEN 'undrilled'
          WHEN dr.det < s.drill_recall_min * dr.inj THEN 'blind'
          WHEN s.p_late < s.p_early - {eps_primary} AND s.c_late < s.c_early - {eps_counter} THEN 'diverging'
          ELSE 'ok'
        END AS verdict,
        s.p_last, s.c_last, dr.inj, dr.det
      FROM s JOIN dr ON dr.detector = s.detector
    ),
    fin AS (
      SELECT o.detector,
        CASE WHEN o.verdict = 'ok' AND EXISTS (
               SELECT 1 FROM reach a JOIN own x ON x.detector = a.u WHERE a.d = o.detector AND x.verdict <> 'ok')
             THEN 'upstream_unsound' ELSE o.verdict END AS verdict
      FROM own o
      UNION ALL
      SELECT DISTINCT detector, 'unregistered' FROM {signal}
      WHERE detector IS NOT NULL AND detector NOT IN (SELECT detector FROM {register})
      UNION ALL
      SELECT NULL, NULL FROM g WHERE g.bad_register + g.bad_upstream + g.cycle + g.bad_signal + g.bad_drills > 0
    )
    SELECT f.detector,
      CASE
        WHEN g.bad_register > 0 THEN error('malformed register: NULL field, duplicate detector, drill_min below 1 or recall outside (0, 1]')
        WHEN g.bad_upstream > 0 THEN error('malformed register: upstream names an unregistered detector')
        WHEN g.cycle > 0 THEN error('malformed register: upstream cycle')
        WHEN g.bad_signal > 0 THEN error('malformed signal: NULL key or duplicate detector day')
        WHEN g.bad_drills > 0 THEN error('malformed drill: NULL field, negative count, detected above injected or unregistered detector')
        ELSE f.verdict
      END AS verdict
    FROM fin f CROSS JOIN g
```

| verdict | when (precedence top-down) | vectors |
|---|---|---|
| dark | no defined primary in the window | v02, v03, v21 |
| breach | the latest defined primary exceeds the row's threshold (strictly) | v04, v23, v26, v27 |
| counter_dark | no defined counter in the window | v06 |
| counter_low | the latest defined counter is under its floor (strictly) | v07, v28, v29 |
| undrilled | fewer than drill_min faults injected in the window | v09, v10, v13 |
| blind | detected below drill_recall_min x injected in the window | v11, v20, v23 |
| diverging | the primary's late-half mean fell by more than eps AND the counter's fell by more than eps | v15 |
| upstream_unsound | own verdict ok, and some upstream, at any depth, is not ok | v20, v21 |
| unregistered | a signal series whose detector has no register row | v24 |
| ok | otherwise | v01, v05, v08, v12, v14, v16-v19, v22, v25, v30 |

Rows after today and before the window are ignored (v02, v13, v25). A detector's own non-ok verdict
outranks upstream_unsound (v23). breach outranks the counter (v27): a breach is evidence the detector sees.
A low counter outranks a missing drill (v28). Several detectors decide independently (v29).

### 2.5 Vectors (VP 4)

```yaml
vectors:
  defaults:
    today: '2026-10-01'
    register_row: {counter_floor: 0.99, drill_min: 20, drill_recall_min: 0.9, threshold: 0.05, upstream: []}
  cases:
    - {id: v01, note: healthy detector over the full window, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v02, note: signal only before the window, register: [{detector: A}], signal: [{detector: A, from: -40, to: -28, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: dark}}
    - {id: v03, note: primary undefined every day, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: null, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: dark}}
    - {id: v04, note: latest primary above the threshold, register: [{detector: A}], signal: [{detector: A, from: -27, to: -1, primary: 0.02, counter: 1.0}, {detector: A, from: 0, to: 0, primary: 0.06, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: breach}}
    - {id: v05, note: primary equal to the threshold does not breach, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.05, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v06, note: counter undefined every day, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: null}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: counter_dark}}
    - {id: v07, note: latest counter below the floor, register: [{detector: A}], signal: [{detector: A, from: -27, to: -1, primary: 0.02, counter: 1.0}, {detector: A, from: 0, to: 0, primary: 0.02, counter: 0.98}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: counter_low}}
    - {id: v08, note: counter equal to the floor passes, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 0.99}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v09, note: one fault short of drill_min, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 19, detected: 19}], expected: {A: undrilled}}
    - {id: v10, note: no drill at all, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [], expected: {A: undrilled}}
    - {id: v11, note: 17 of 20 injected faults detected is under the 0.9 recall floor, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 17}], expected: {A: blind}}
    - {id: v12, note: 18 of 20 detected meets the recall floor, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 18}], expected: {A: ok}}
    - {id: v13, note: a drill on the day the window opens is outside it, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -28, injected: 20, detected: 20}], expected: {A: undrilled}}
    - {id: v14, note: the first day inside the window counts, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -27, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v15, note: 'primary improves while the counter falls, both by more than eps, counter still above its floor', register: [{detector: A, counter_floor: 0.9}], signal: [{detector: A, from: -27, to: -14, primary: 0.04, counter: 1.0}, {detector: A, from: -13, to: 0, primary: 0.02, counter: 0.95}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: diverging}}
    - {id: v16, note: 'a real improvement, counter flat, is not diverging', register: [{detector: A, counter_floor: 0.9}], signal: [{detector: A, from: -27, to: -14, primary: 0.04, counter: 1.0}, {detector: A, from: -13, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v17, note: counter falls with primary flat is not diverging, register: [{detector: A, counter_floor: 0.9}], signal: [{detector: A, from: -27, to: -14, primary: 0.02, counter: 1.0}, {detector: A, from: -13, to: 0, primary: 0.02, counter: 0.95}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v18, note: moves of exactly eps are not diverging, register: [{detector: A, counter_floor: 0.9}], signal: [{detector: A, from: -27, to: -14, primary: 0.03, counter: 1.0}, {detector: A, from: -13, to: 0, primary: 0.02, counter: 0.99}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v19, note: 'only the late half has data, so no divergence is read', register: [{detector: A, counter_floor: 0.9}], signal: [{detector: A, from: -13, to: 0, primary: 0.02, counter: 0.95}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok}}
    - {id: v20, note: a healthy detector whose upstream is blind is upstream_unsound, register: [{detector: A}, {detector: B, upstream: [A]}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: B, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 10}, {detector: B, day: -1, injected: 20, detected: 20}], expected: {A: blind, B: upstream_unsound}}
    - {id: v21, note: unsoundness propagates through a chain of upstreams, register: [{detector: A}, {detector: B, upstream: [A]}, {detector: C, upstream: [B]}], signal: [{detector: B, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: C, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}, {detector: B, day: -1, injected: 20, detected: 20}, {detector: C, day: -1, injected: 20, detected: 20}], expected: {A: dark, B: upstream_unsound, C: upstream_unsound}}
    - {id: v22, note: sound upstreams leave a detector ok, register: [{detector: A}, {detector: B, upstream: [A]}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: B, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}, {detector: B, day: -1, injected: 20, detected: 20}], expected: {A: ok, B: ok}}
    - {id: v23, note: a detector's own verdict outranks upstream_unsound, register: [{detector: A}, {detector: B, upstream: [A]}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: B, from: -27, to: 0, primary: 0.09, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 10}, {detector: B, day: -1, injected: 20, detected: 20}], expected: {A: blind, B: breach}}
    - {id: v24, note: 'a series with no register row is unregistered, and the registered detector still decides', register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: X, from: 0, to: 0, primary: 0.0, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: ok, X: unregistered}}
    - {id: v25, note: rows after today are ignored, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: A, from: 1, to: 1, primary: 0.5, counter: 0.0}], drills: [{detector: A, day: -1, injected: 20, detected: 20}, {detector: A, day: 1, injected: 20, detected: 0}], expected: {A: ok}}
    - {id: v26, note: the latest defined value is read when today's is undefined, register: [{detector: A}], signal: [{detector: A, from: -27, to: -2, primary: 0.02, counter: 1.0}, {detector: A, from: -1, to: -1, primary: 0.06, counter: 1.0}, {detector: A, from: 0, to: 0, primary: null, counter: null}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: breach}}
    - {id: v27, note: breach outranks a low counter, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.06, counter: 0.5}], drills: [{detector: A, day: -1, injected: 20, detected: 20}], expected: {A: breach}}
    - {id: v28, note: a low counter outranks a missing drill, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 0.5}], drills: [], expected: {A: counter_low}}
    - {id: v29, note: several detectors decide independently, register: [{detector: A}, {detector: B}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}, {detector: B, from: -27, to: 0, primary: 0.02, counter: 0.9}], drills: [{detector: A, day: -1, injected: 20, detected: 20}, {detector: B, day: -1, injected: 20, detected: 20}], expected: {A: ok, B: counter_low}}
    - {id: v30, note: drills sum across the window, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -20, injected: 10, detected: 9}, {detector: A, day: -2, injected: 10, detected: 9}], expected: {A: ok}}
    - {id: e01, register: [{detector: A}, {detector: A}], signal: [], drills: [], expected: error, raises: 'malformed register: NULL field, duplicate detector'}
    - {id: e02, register: [{detector: A, drill_min: 0}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [], expected: error, raises: drill_min below 1}
    - {id: e03, register: [{detector: A, drill_recall_min: 1.5}], signal: [], drills: [], expected: error, raises: 'recall outside (0, 1]'}
    - {id: e04, register: [{detector: A, drill_recall_min: 0}], signal: [], drills: [], expected: error, raises: 'recall outside (0, 1]'}
    - {id: e05, register: [{detector: A, threshold: null}], signal: [], drills: [], expected: error, raises: 'malformed register: NULL field'}
    - {id: e06, register: [{detector: B, upstream: [Z]}], signal: [], drills: [], expected: error, raises: upstream names an unregistered detector}
    - {id: e07, register: [{detector: A, upstream: [B]}, {detector: B, upstream: [A]}], signal: [], drills: [], expected: error, raises: upstream cycle}
    - {id: e08, register: [{detector: A, upstream: [A]}], signal: [], drills: [], expected: error, raises: upstream cycle}
    - {id: e09, register: [{detector: A}], signal: [{detector: A, from: 0, to: 0, primary: 0.02, counter: 1.0}, {detector: A, from: 0, to: 0, primary: 0.03, counter: 1.0}], drills: [], expected: error, raises: duplicate detector day}
    - {id: e10, register: [{detector: A}], signal: [{detector: null, from: 0, to: 0, primary: 0.02, counter: 1.0}], drills: [], expected: error, raises: 'malformed signal: NULL key'}
    - {id: e11, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 10, detected: 11}], expected: error, raises: detected above injected}
    - {id: e12, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: -1, detected: -2}], expected: error, raises: negative count}
    - {id: e13, register: [], signal: [], drills: [{detector: Q, day: -1, injected: 20, detected: 20}], expected: error, raises: unregistered detector}
    - {id: e14, register: [{detector: A, upstream: null}], signal: [], drills: [], expected: error, raises: 'malformed register: NULL field'}
    - {id: e15, register: [{detector: A}], signal: [{detector: A, from: -27, to: 0, primary: 0.02, counter: 1.0}], drills: [{detector: A, day: -1, injected: 20, detected: null}], expected: error, raises: 'malformed drill: NULL field'}
```

### 2.6 Mutants (VP 4)

Each mutant replaces one exact substring of the verdict SQL (it must occur exactly once) and must fail at
least one vector. VP 4 counts the kills and the unique sites; the table lists the killing vectors.

```yaml
mutants:
  - {id: m01, what: breach on equality, old: "WHEN s.p_last > s.threshold", new: "WHEN s.p_last >= s.threshold"}
  - {id: m02, what: counter floor read as strict, old: "WHEN s.c_last < s.counter_floor", new: "WHEN s.c_last <= s.counter_floor"}
  - {id: m03, what: recall floor read as strict, old: "WHEN dr.det < s.drill_recall_min * dr.inj", new: "WHEN dr.det <= s.drill_recall_min * dr.inj"}
  - {id: m04, what: drill window opened one day early, old: "d.day > {today} - {window_days} AND d.day <= {today}", new: "d.day >= {today} - {window_days} AND d.day <= {today}"}
  - {id: m05, what: no upstream propagation, old: "o.verdict = 'ok' AND EXISTS", new: "o.verdict = 'ok' AND FALSE AND EXISTS"}
  - {id: m06, what: direct upstream only, old: "JOIN own x ON x.detector = a.u WHERE a.d = o.detector", new: "JOIN own x ON x.detector = a.u WHERE a.d = o.detector AND a.depth = 1"}
  - {id: m07, what: unregistered series dropped, old: "WHERE detector IS NOT NULL AND detector NOT IN (SELECT detector FROM {register})\n  UNION ALL", new: "WHERE FALSE AND detector NOT IN (SELECT detector FROM {register})\n  UNION ALL"}
  - {id: m08, what: duplicate register rows allowed, old: "(SELECT count(*) - count(DISTINCT detector) FROM {register})", new: "0"}
  - {id: m09, what: no cycle guard, old: "WHEN g.cycle > 0 THEN", new: "WHEN FALSE THEN"}
  - {id: m10, what: no sentinel row, so a malformed input with no detector row returns empty, old: "SELECT NULL, NULL FROM g WHERE", new: "SELECT NULL, NULL FROM g WHERE FALSE AND"}
  - {id: m11, what: only today's value read, old: "arg_max(w.primary_value, w.day) FILTER (WHERE w.primary_value IS NOT NULL)", new: "max(w.primary_value) FILTER (WHERE w.day = {today})"}
  - {id: m12, what: divergence on the primary alone, old: "s.p_late < s.p_early - {eps_primary} AND s.c_late < s.c_early - {eps_counter}", new: "s.p_late < s.p_early - {eps_primary}"}
  - {id: m13, what: divergence on the counter alone, old: "s.p_late < s.p_early - {eps_primary} AND s.c_late < s.c_early - {eps_counter}", new: "s.c_late < s.c_early - {eps_counter}"}
  - {id: m14, what: future signal rows read, old: "WHERE day > {today} - {window_days} AND day <= {today}", new: "WHERE day > {today} - {window_days}"}
  - {id: m15, what: no drill_min, old: "WHEN dr.inj < s.drill_min THEN", new: "WHEN dr.inj < 1 THEN"}
  - {id: m16, what: detected above injected allowed, old: "OR detected > injected", new: ""}
  - {id: m17, what: upstream overrides a detector's own verdict, old: "CASE WHEN o.verdict = 'ok' AND EXISTS", new: "CASE WHEN EXISTS"}
  - {id: m18, what: drills read without a window, old: "AND d.day > {today} - {window_days} AND d.day <= {today}", new: ""}
  - {id: m19, what: counter checked before breach, old: "WHEN s.p_last > s.threshold THEN 'breach'\n      WHEN s.c_last IS NULL THEN 'counter_dark'\n      WHEN s.c_last < s.counter_floor THEN 'counter_low'", new: "WHEN s.c_last IS NULL THEN 'counter_dark'\n      WHEN s.c_last < s.counter_floor THEN 'counter_low'\n      WHEN s.p_last > s.threshold THEN 'breach'"}
  - {id: m20, what: no drill-recall bounds, old: "OR drill_min < 1 OR drill_recall_min <= 0 OR drill_recall_min > 1", new: "OR drill_min < 1"}
  - {id: m21, what: drills for unregistered detectors accepted, old: "\n         OR detector NOT IN (SELECT detector FROM {register})) AS bad_drills", new: ") AS bad_drills"}
```

| mutant | killed by |
|---|---|
| m01 breach on equality | v05 |
| m02 counter floor read as strict | v08 |
| m03 recall floor read as strict | v12, v30 |
| m04 drill window opened one day early | v13 |
| m05 no upstream propagation | v20, v21 |
| m06 direct upstream only | v21 |
| m07 unregistered series dropped | v24 |
| m08 duplicate register rows allowed | e01 |
| m09 no cycle guard | e07, e08 |
| m10 no sentinel row | e13 |
| m11 only today's value read | v26 |
| m12 divergence on the primary alone | v16, v18 |
| m13 divergence on the counter alone | v17 |
| m14 future signal rows read | v25 |
| m15 no drill_min | v09 |
| m16 detected above injected allowed | e11 |
| m17 upstream overrides a detector's own verdict | v23 |
| m18 drills read without a window | v13, v25 |
| m19 counter checked before breach | v27 |
| m20 no drill-recall bounds | e03, e04 |
| m21 drills for unregistered detectors accepted | e13 |

## 3. Settled / contested / risk / open

### Settled (fixture s1-s3)

- **s1.** Every pilot item carries exactly one failure_signal, and that signal is where its Goodhart
  question is answered. Precedent: the pilot model requires a failure_signal and the evaluator's L1 keeps
  it unique per item (merged code, CD.45 W0, operator-approved 2026-10-02); Decision 196 clause 7 asks the same question of
  Tier A decisions and is used only by analogy. Data plane only: the register reads the customer's own
  telemetry and review rows (Decision 209 clause 2(a)); whether any verdict crosses is #1399's k1.
- **s2.** Measured: in 8 of 8 W1 items a stated cheap path lowers the failure_signal at least as far as a
  real halving of failures, and the staged counter separates the two in 8 of 8 (VP 3).
- **s3.** Measured: 4 of 8 failure_signals name a companion, 1 a seeded known-positive, 0 a recall check on
  the top-rung trigger; the companions computable in the model catch 1 of 2 cheap paths (VP 1, VP 3).

### Contested (k1-k3 in the fixture; k4-k6 report-only, the fixture's contested list is capped at 3)

- **k1 (asked). What a non-ok verdict does on the ladder.** (a) It blocks promotion and demotes one rung,
  as #1398's staged dark-signal leg does (its k7 (a)). (b) It blocks promotion only; the rung holds. (c) Advisory: logged beside the
  transition record, nothing gates. Recommended (a) for blind, undrilled, counter_dark, counter_low and
  unregistered, and (b) for diverging and upstream_unsound, which are weaker evidence. #1398 measured that
  a half-blind monitor also lets more errors escape below the top rung (2.09% on its worst seed), so
  blocking promotion alone leaves that. No Decision or contract decides it; #1398 is unmerged and its own
  k1 and k7 are parked. Consequence to weigh: capture's counter needs its q1 out-of-band denominator, which
  does not exist, so under (a) or (b) capture reads counter_dark from day one and every detector downstream
  reads upstream_unsound until it lands (risk R6).
- **k2 (asked). How drills run.** (a) Live: seeded rows written through the real producers under a
  dedicated drill project_id, excluded from every consumer total by that id (the pattern #1390's report
  records for rec-4025's T3.2 assert over a synthetic project_id). (b) Replay: each detector's SQL run
  offline over seeded rows, never touching production tables. (c) Operator-labelled samples only. Recommended
  (b) for the six SQL detectors and (a) only for capture and the canary, whose failures live in the
  pipeline, not in the SQL. (a) needs every consumer to exclude the drill project_id (no contract field marks
  a drill row today, e5); (b) cannot see a live-pipeline loss, which is why capture's counter is an
  out-of-band count. The ladder's reviewer drill (known-wrong outputs in the review sample) is a choice about
  the operator's own review stream and sits inside this fork.
- **k3 (asked). Where counters and drills are declared.** (a) In this item's register rows only (staged).
  (b) Two new FailureSignal fields, counter and drill, on every pilot item, with the evaluator requiring them
  (a pilot-schema change, the evaluator owner's, O1). (c) In each item's prose. Recommended (a) now and (b) at
  lift, so a detector cannot be added without its counter. (b) touches the evaluator, which a design slice may
  not change.
- **k4 (asked; report-only). Harm weights** (#1398 R6). (a) Uniform: every detector's verdict counts the
  same. (b) Per-detector weights the operator sets, read by the ladder's AOQL target. (c) Derived from what the
  detector gates: an egress or a proof close above a filing above a label. Recommended (c) as the starting
  order, set by the operator. No precedent.
- **k5 (asked; report-only). The fixture item's edge home.** (a) depends_on T2.36 only (carried
  provisionally): the signals and drills are telemetry reader rows. (b) part_of T3.4, beside the maturity
  ladder, whose exit criterion 2 asks for gates with rollback. (c) part_of T3.3, whose false-positive
  threshold (audit F-035) is one of these rows. Recommended (a) until W2 places the ladder.
- **k6 (asked; report-only). The divergence rule.** (a) Half-window means with an absolute eps on each
  (staged; v15-v19). (b) A per-row statistical test on both series (for example a two-proportion test at a
  stated alpha), which needs per-day denominators. (c) No divergence leg; the counter floor alone. Recommended
  (a) for the pilot: it is one comparison and fails toward review, and (b) once denominators are recorded.
  (c) misses slow drift above the floor (v15 is above its floor).

### Risks

- **R1 Teaching to the drill.** A rule set, a model or a person that can tell drill rows from real ones
  can pass every drill and still miss real faults. Drills must be drawn from the real distribution and
  rotated, and no detector rule may branch on the drill marker (the exclusion happens after detection).
- **R2 Counters can be gamed too.** A counter computed from the same rows by the same code as the primary
  shares its blind spot (a second-order Goodhart). Each row's counter source is chosen to be independent of
  the primary's numerator; the build's c2 replay checks the counter moves, not that it is independent.
- **R3 Drill rows in the warehouse.** Under k2 (a), a consumer that forgets the drill project_id counts
  seeded failures as real. No contract field marks a drill row (e5).
- **R4 Cost.** Drills are runs, and the reviewer drill adds review items. Both belong to the cost/egress
  component.
- **R5 Small counts.** drill_min 20 per 28 days is under one fault a day; a recall floor of 0.9 over 20
  faults passes a 90%-recall detector only about two times in three (#1398 measured 68%). Seeds, q2.
- **R6 A dark root freezes the loop.** Propagation is fail-safe by design: when capture is not ok, nothing
  downstream promotes. Until capture's q1 denominator exists that is every day (k1).
- **R7 The model is a model.** Section 2.3's worlds are deterministic and built from each sibling's own
  definitions; they show directions, not rates. The build's c2 replays each cheap path on the real metric.

### Open questions (q1-q3 in the fixture)

- **q1.** Where the out-of-band counts and drill logs live: capture's q1 session denominator, rec-4025's
  harness widened to shadow mode (#1390 q2, a queue change for the operator), the friction label review
  (#1394 q2), and the verdict log itself (shares #1398 q2 and #1396 q4).
- **q2.** Seeds are unmeasured: counter floor 0.99, drill_min 20 per 28 days at recall 0.9, eps 0.01 on
  14-day halves. Who sets per-detector values, and from what measurement?
- **q3.** Is the register's verdict one input to #1398's controller, replacing its top-rung drill with a
  drill at every rung (its k5 (a3)), or does the controller keep its own drill and read the register
  beside it? This report reads one input.

### Named for owners, not filed (Decision 67)

- **O1** The pilot FailureSignal model has no counter or drill field (e4), so no item can declare its guard
  in a form the evaluator checks (evaluator owner; k3 (b)).
- **O2** A hook row with no integer exit code is written severity info (e11), so a hook that fails without
  reporting a code leaves unmapped_failure_share's denominator. Whether Claude Code omits exitCode on a hook
  timeout is not verified here (inferred; telemetry producer owner).
- **O3** No telemetry contract carries a field that marks a seeded drill row (e5); a live drill (k2 (a))
  needs one, or a reserved project_id with an exclusion rule every consumer honours (telemetry contract owner).

## 4. Consideration register (as authored in the fixture)

- why: all 8 W1 failure_signals are lower-is-better and each has a cheap path that lowers it as far as a
  real halving of failures (VP 3); 4 name a companion, 1 a seeded positive, 0 a recall check (VP 1).
- how: one register row per detector (metric, cheap path, counter, drill, upstreams) and one daily SQL that
  returns one of ten verdicts per detector; the ladder reads it (k1).
- planes: data_plane.
- maturity (thresholds are provisional seeds; plan fork line): read_all, the operator re-derives every
  verdict; to sampled after 40 verdicts re-derived unchanged since the last overturned one; to spot_check
  after 40 more on a 1-in-5 sample; to anomaly_triggered after 30 consecutive days in which the register's
  own drill (one injected unregistered series a day) reads unregistered. The return leg and version rule are
  #1398's k1 and k2.
- failure_signal: a detector reads sound while it is not. Metric unsound_reads: series that reached the
  ladder with no register row, plus register rows whose counter held over its floor in their own cheap-path
  replay; must be 0. Source: the verdict log (unregistered rows) and the c2 replay run on every register
  version.
- verification: c1 vectors, c2 cheap-path replay per row, c3 operator review of every register row.
- rollback: stop the verdict schedule; the ladder reads its other inputs as before; register rows and drill
  logs stay as history.

## 5. Boundary notes for W2 synthesis

- **Maturity ladder (#1398).** The register's verdict is one series with the controller's inputs: the
  failure_signal it reads per component must be the register row's metric (that report's own boundary note).
  Contradiction for W2: #1398 stages a drill at spot_check only (its k5 (a)) and names a drill at every rung
  as a candidate cure (its k5 (a3)); this register stages a drill verdict at every rung. W2 picks one home.
  R3 (reviewer error) and R6 (harm weights) from that report are rows 7 and k4 here.
- **Capture (#1384).** Its q1 out-of-band denominator is this register's capture counter; until it exists,
  capture is counter_dark and the whole loop is upstream_unsound (R6). W2 should sequence q1 first.
- **Reader verbs (#1390).** Its q2 (rec-4025 widened to shadow mode) is the source of the reader counter;
  "no" leaves that row undrilled.
- **Friction (#1394).** Its c2 guard and this row's drill are complementary: c2 stops wildcards statically,
  the drill catches lumping under an exact signature. O2 is a producer rule in its slice 3b.
- **Deliberation (#1395).** This row adds the read-side arm its report says is missing (none with
  reasoning tokens) as a counter, not as a fourth drift kind; W2 may move it into the drift monitor.
- **Rec filing (#1396) and back-validation (#1397).** They share one cheap path: a stricter filer improves
  both metrics at once. Their drills are one seeded recurring finding read twice (filed; then, after a drill
  no-op close, re-filed as a regression).
- **Allow-list (#1399).** Canary coverage is a property of the seeding, not of the egress: the canary row
  must be read back from the data-plane input each run. Register verdicts are data-plane only; any fleet
  view of them crosses only through #1399's allow-list (its k1, always-ask).
- **Cost/egress (component 10).** Drills and the reviewer drill are recurring cost; under k2 (b) they run
  offline in the data plane.
- **Upstream graph.** The register's upstream lists are the data edges W2 should author as pilot
  depends_on edges between items; the evaluator's L4 refuses an edge to a pilot item absent from this
  branch's fixture, so none is added here.

## 6. Staged candidate decision text (for W3; not filed)

This text presumes the recommended options of parked forks k1, k2 and k3. It is not settled.

> "A loop detector's failure_signal promotes nothing on its own. Every detector whose series gates an
> automated transition carries a register row naming the cheapest way its metric improves without the work
> improving, a counter series from a source independent of the metric's numerator, and a seeded drill
> that measures its recall. A daily deterministic verdict reads the register, the series and the drill
> log; a detector is sound only when its signal, counter and drill are sound and so are its upstream
> detectors. An unsound verdict blocks promotion and demotes one rung; a series without a register row is
> unsound by definition."
