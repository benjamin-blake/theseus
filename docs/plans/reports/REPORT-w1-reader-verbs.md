# REPORT: W1 component 2 - telemetry reader verbs (rec-4024, reader side)

REPORT-ONLY (Decision 86 cl.2). Planning artefact: `docs/plans/PLAN-w1-reader-verbs.yaml`.
Fixture rows: `pwi-telemetry-reader-verbs` in `docs/work-item-pilot/telemetry-feedback-loop.yaml`
(CD.45 pilot, provisional_v0). Nothing is built, filed, closed, flipped or ratified here.

## 0. Verdict

- The component is real and load-bearing. Decision 199 stores no session state, duration, roll-up,
  friction or cost: all of it is DERIVED AT READ by named reader verbs. Every other feedback-loop
  component (component 1's failure_signal, the friction classifier, back-validation, T3.3's anomaly
  agent, T2.36 c3's preflight health check) reads telemetry only through them.
- Seed boundary kept, with one sharpening. The rec-4024 text itself was not readable in this session
  (no warehouse access, q2), so the verb set is taken from the contracts: every field whose
  `populated_by` names "a named reader verb (rec-4024)", plus the dedupe vectors' "rec-4024's reader
  verbs must independently pass" obligation. The component is the read MECHANISM (registry form,
  partition binding, generation-aware dedupe) plus the state, duration and roll-up verbs. The friction
  labels (rec-4032) and the price table (rec-4031) are other owners' inputs that compose on it.
- The mechanism does not exist and cannot be reached by registering verbs alone: the NAMED_READS form
  binds one SCD2 table's current projection, and the telemetry tables are append-only with no current
  projection (VP 1). The design needs a registry extension, not just new rows.
- Two ratified contract rules would derive wrong values if built literally (risks R1, R2): session state
  ignores resume-after-close, and session duration is measured from the ROOT start, which is wrong for
  every sub-agent session. Staged as contested k1; the contract is not edited here.
- One item fits the clause-3 grain (kind task; three criteria; one edge, part_of T2.36). The verbs share
  one failure mode (a wrong derived value), so splitting them would spend the 12-item cap on rows with
  one failure signal.

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | No NAMED_READS verb targets a telemetry table; named_read renders `{tbl}` as the spec's current_table, which is None for an append_only table, so a telemetry verb would read `lake.None` [VP 1] | src/common/ducklake_reads.py:139; src/common/ducklake_scd2_schema.py:225 |
| e2 | Session state rule: "absent a close row, the session is running; present, its outcome IS the session's terminal state" | docs/contracts/telemetry_sessions.yaml:192 |
| e3 | Session duration formula: close.event_timestamp minus session_started_at [VP 4] | docs/contracts/telemetry_sessions.yaml:252 |
| e4 | session_started_at is the ROOT's start, carried by every row of the root AND all its sub-agent sessions [VP 4] | docs/contracts/telemetry-event-envelope.yaml:100-104 |
| e5 | Agent-run duration is paired open/close on agent_run_id, the envelope's span rule; session duration is not | docs/contracts/telemetry_agents.yaml:221; docs/contracts/telemetry-event-envelope.yaml:72 |
| e6 | Read-side dedupe R4/R5 (generation retire, event collapse, model_call entity collapse); the conflict report is normative output | docs/contracts/telemetry-event-envelope.yaml:335-347 |
| e7 | The reader verbs must pass tests/telemetry/fixtures/dedupe_vectors.yaml independently of the stdlib oracle [VP 2] | tests/telemetry/fixtures/dedupe_vectors.yaml:5 |
| e8 | Every derivation is bounded to one session's calendar-day partition (answers Decision 81 cl.8); falsifier `derived-read-too-costly` pulls materialization forward from T2.52 c1 | Decision 199 cl.1 and reversal conditions (docs/DECISIONS.md:697, 715-717) |
| e9 | A held session_id decodes to the root session_started_at (decode_time_prefix) [VP 3] | src/telemetry/identity.py:214 |
| e10 | T2.52 is the analytical-aggregate verb class (c3) with a measured response-size ceiling (c7) and the D88 egress budget (c5) | docs/ROADMAP-PLATFORM.yaml T2.52 |

Measured (local only; no production catalog read):

- Dedupe in SQL: the sketch in section 2 passes 17 of 17 committed vectors (17 table checks: 15
  observations, 2 agents) on DuckDB 1.5.4, surviving event_ids and conflicted grain keys both exact
  [VP 2]. The R5 layered rule needs one join (V* from the sessions open rows) and two windows.
- Partition binding on a local DuckLake catalog (pinned extension, UTC, inlining off), 7 calendar days x
  10 sessions x 500 rows, one write per session (70 Parquet files), session ids derived by
  src/telemetry/identity.py: a per-session read filtered by session_id alone reads 1 of 70 files, and
  the same read with the decoded year/month/day triple also reads 1 [VP 3]. The ULID time prefix makes
  the id itself prunable; the triple is cheaper catalog filtering on Neon (unmeasured, q1). A 3-day
  window reads 30 files, linear in days.
- Scratch run at larger scale (not a VP step): 1.12M rows over 14 days, one 80k-row file per day: a
  per-session roll-up took about 9 ms locally and read 1 file; a 7-day per-session window read 7. Local
  latency says nothing about S3 and Neon round trips, which dominate in production (q1).

## 2. Verb design (what this item stages)

Mechanism:

1. Registry form. NamedRead gains an event-journal binding: placeholders for the four append-only
   tables (history only, no current projection) and a MANDATORY partition predicate rendered
   server-side. Per-session verbs take only `session_id`; the server decodes the calendar-day triple
   from its ULID prefix (e9), so no caller can widen the scan. NAMED_READS_VERSION bumps; `describe`
   lists the new class. No caller SQL crosses the boundary (Decision 84 I-3).
2. Shared dedupe. Every telemetry verb composes one rendered R4/R5 block per table it reads, then
   derives. Every response stamps `registry_version`, the V* it used per (producer, session) and the
   conflicted grain keys R5b requires as output (e6). The sketch, verified against the vectors (VP 2;
   `{partition}` is the server-rendered predicate, `{sessions}` and `{table}` the bound tables):

```sql
WITH gen AS (
  SELECT producer, session_id, max(parser_version) AS v_star
  FROM {sessions} WHERE {partition} AND event_kind = 'open' GROUP BY producer, session_id
),
live AS (
  SELECT t.* FROM {table} t LEFT JOIN gen g USING (producer, session_id)
  WHERE {partition} AND (g.v_star IS NULL OR t.parser_version = g.v_star)
),
ev AS (
  SELECT * FROM live
  QUALIFY row_number() OVER (PARTITION BY producer, event_id ORDER BY parser_version DESC, created_timestamp) = 1
)
SELECT event_id FROM ev
QUALIFY observation_id IS NULL OR row_number() OVER (
  PARTITION BY observation_id
  ORDER BY CASE producer WHEN 'claude_code' THEN 0 WHEN 'litellm' THEN 1 ELSE 2 END,
           event_timestamp DESC, created_timestamp, producer, event_id) = 1
```

   The model_call entity collapse applies only to model_call rows (in production the guard is
   `observation_type = 'model_call'`; the vectors mark them by observation_id). Conflicts are the grain
   keys `(producer, event_id, parser_version)` with more than one distinct row content.
3. Response shape. Derived rows only: one row per session (or agent run), never raw observation rows
   and never transcript content. A 1000-turn session holds about 55k rows (component 1, section 1),
   far past a Function URL response; derived rows keep every response small (Decision 88) and keep
   free text inside the data plane (Decision 209 cl.2a; the reader runs there).

Verbs (names from the contracts' `derived_by`):

| verb | derives | input owner |
|---|---|---|
| session_state_and_duration | state, outcome, duration_seconds | this item (rule per k1) |
| session_process_event_rollup | process_event_total, steps_completed_total | this item |
| session_friction_rollup | rework_total, exception_total | this item; labels from rec-4032 (friction classifier component) |
| agent_run_state_and_duration | agent-run state, duration | this item |
| agent_run_token_rollup | tokens_input_total, tokens_output_total over the child's model_calls | this item |
| model_call_cost_estimate | cost per model_call | rec-4031 (price table), composes this item's dedupe |
| sessions_window (proposed, k2) | one derived row per root session over at most 7 days | this item if k2 (a) |

## 3. Settled / contested / risk / open

Settled (consistent with a Decision, a contract or measured; s1-s3 in the fixture):

- s1 Boundary: read side only. Decision 199's derived-at-read verbs over the four tables; the writer verb
  and tables are T2.36 (rec-4024 slice 2); labels (rec-4032) and prices (rec-4031) compose on this
  mechanism.
- s2 The registry needs an event-journal form (e1, VP 1). Adding rows to today's NAMED_READS cannot
  serve an append-only table, and R4 needs a second table (the sessions open rows) in the same verb.
- s3 The read model is feasible as designed: R4/R5 is one SQL statement passing 17/17 vectors (VP 2), and
  a session_id alone yields its partition, read as 1 of 70 files locally (VP 3).

Contested (evidence on both sides, options listed; k1-k2 in the fixture):

- k1 State and duration rule. The contract (e2, e3) says no close row means running and measures
  duration from session_started_at. Against: component 1 emits one close row per finalization and a
  resume row after it, so "a close row exists" reads terminal for a session that is running again; and
  session_started_at is the ROOT start (e4), so a sub-agent spawned two hours into its root reports two
  extra hours. Options: (a) amend telemetry_sessions: state = latest lifecycle row among open, resume,
  compact and close (annotate excluded; running unless it is close), outcome = that close's outcome,
  duration = latest close minus the session's OWN first open row, which is the envelope's span-pairing
  rule (e5) and equals the old formula for a root; (b) keep the text and forbid resume after close (a
  resumed session becomes a new session with execution_attempt + 1), which contradicts component 1's
  per-finalization close design; (c) keep the text and document the child offset as a known bias.
  Recommended: (a). A ratified Class A semantic change, so the operator decides; parked.
- k2 Window verbs. Component 1's unfinalized_session_share, T3.3's daily anomaly baseline and T3.4's
  telemetry delta all need many sessions over a time window. Options: (a) one `sessions_window` verb
  here returning one derived row per root session for at most 7 calendar days (paginable), with every
  share or rate computed by the consumer, so each derivation stays per-session and the scan is a
  bounded partition range (VP 3: linear in days); (b) wait for T2.52's analytical-aggregate class (c3,
  c7), leaving those consumers without a signal until it lands; (c) consumers loop the per-session verb,
  which is one round trip per session. For (a): it stays inside Decision 199's per-session unit and
  is prunable, so Decision 81 cl.8 is not reopened. Against: the contract wording binds each derivation
  to one session's partition and T2.52 owns analytical verbs. Recommended: (a), shaped to T2.52 c3's
  declared response schema and stable ordering so T2.52 can adopt it. Parked.

Risk (known loss modes, not choices):

- R1 Child-session duration bias. A literal build of e3 overstates every sub-agent session's duration by
  its spawn offset from the root start. Nothing downstream can detect it, because the value is
  plausible. Covered by k1 and by c2's child-session fixture.
- R2 Resume-after-close state. A literal build of e2 reads finalized-then-resumed sessions as terminal.
  The same ambiguity component 1 hit in its failure_signal (its G1); covered by k1 and c2.
- R3 Production cost unknown. Decision 199's own falsifier is a consumer latency bound, and no consumer
  has named one. c3 makes the measurement a precondition of any consumer depending on a verb.

Open (q1-q3 in the fixture; none is answerable from the repository):

- q1 Which consumer's latency bound tests Decision 199's `derived-read-too-costly` falsifier, and what are
  the verbs' p95 latency and per-call catalog egress on the production Neon catalog? Unmeasured: no
  credentials in this session, and the local run says nothing about S3 and Neon round trips.
- q2 rec-4024's own text ("item 6") could not be read here. The operator should confirm that the
  contracts' populated_by set above is the whole reader scope.
- q3 Is rec-4025's derived-layer harness the right shadow re-derivation source for the failure_signal,
  or should the reader own a production raw-rows path? The stdlib oracle is a test fixture
  (tests/fixtures/telemetry_dedupe_reference.py) and cannot run in production (Decision 84 I-3).

## 4. Consideration register (as authored in the fixture)

- planes: data_plane. The reader runs in the data plane; any fleet view over these verbs crosses to a
  control plane only through rec-4141's allow-list (allow-list transport component).
- failure_signal: verb_rederivation_mismatch_rate, the share of sampled sessions whose verb output
  (state, outcome, duration, roll-ups) differs from an independent re-derivation over the same
  session's raw rows. Source: rec-4025's derived-layer harness in shadow mode (q3); CI's dedupe vectors
  cover the R4/R5 leg on every change. Why this and not latency: a slow or failing verb is loud (a 500
  or a timeout at the consumer), while a wrong derived value is silent and skews every consumer at once:
  component 1's signal, the classifier's counts and T3.4's "telemetry delta proves fix". The conflict
  count stamped in every response (section 2) is a second, cheaper runtime read of the dedupe leg.
- maturity: starts at read_all, meaning every verb response for the first sessions is shadow-compared.
  read_all -> sampled at >= 50 consecutive sessions with zero mismatches; sampled -> spot_check at 0
  mismatches across the last 200 sampled sessions; spot_check -> anomaly_triggered at >= 30
  consecutive days with zero mismatches and zero conflicted grain keys. Seed values for the
  maturity-ladder controller component to challenge.
- verification: c1 (event-journal registry form, server-decoded partition, shared dedupe passing every
  vector on DuckLake with the conflict report), c2 (derivation verbs on golden fixtures with the k1
  rule, children and resume-after-close included), c3 (production latency and egress measured against
  a named consumer bound before any consumer depends on a verb; review method). All open.
- rollback: remove the telemetry verbs from NAMED_READS and bump the registry version. Reads have no side
  effects and stored rows are untouched.
- edges: part_of T2.36 (rec-4024 is T2.36's slice carrier; T2.36 c3 is a reader-side criterion).

## 5. Boundary notes for W2 synthesis

- Component 1 (capture producer wiring): its failure_signal source is this item's sessions_window verb
  (k2) with the latest-lifecycle-row state rule (k1). On merge of both PRs, W2 should add an edge
  `pwi-capture-producer-wiring depends_on pwi-telemetry-reader-verbs`. It is not added here: the capture
  item is not on main yet, so the evaluator's L4 would fail the edge.
- Friction classifier (rec-4032): owns the labels table and its form. session_friction_rollup is built
  on this item's dedupe and binding; whether the labels are a DuckLake table joined in the verb or
  bundled registry config is the classifier's call, and it decides whether that verb reads one table
  or two.
- Back-validation (T3.4): "telemetry delta proves fix" is a before/after comparison over windows, so it
  needs k2 (a) or T2.52. Deltas must be read at one registry_version; a version bump between the
  windows makes the delta meaningless, so the response stamp is load-bearing.
- Maturity-ladder controller: this item's rungs are measured by shadow re-derivation (q3), not by
  telemetry it emits itself. The controller needs the harness to report per verb.
- Cost/egress budget: Neon catalog egress per verb is unmeasured (q1). The sessions_window range is the
  one read shape whose cost scales with the caller's parameter; it is capped at 7 days.
- T2.36 c3 (preflight telemetry health check) is a reader consumer: a sessions_window count is the
  natural probe, and per Decision 88 (ii) preflight must call it once, from the warm-up, never per gauge.

## 6. Not done here (and why)

- No verb, registry, test or contract code: REPORT-ONLY by brief.
- No telemetry_sessions contract amendment for k1: a ratified Class A semantic change, parked for the
  operator.
- No rec filed, updated or closed (Decision 67; the brief's never-list). rec-4024, rec-4025, rec-4031
  and rec-4032 are named as owners only.
- No T2.36 or T2.52 criterion text or status change.
