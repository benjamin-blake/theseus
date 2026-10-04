# REPORT: W1 component 10 - Cost and egress budget (a line register in physical units, a daily attributed ledger and a daily verdict priced at read)

Plan: docs/plans/PLAN-w1-cost-egress.yaml. Fixture item: pwi-loop-cost-egress-budget (1 of 12 cap).
REPORT-ONLY (Decision 86 cl.2): nothing here is built, filed, ratified, flipped, provisioned or paid for.
Every table, block, schedule and verb named below describes a future build. The nine sibling W1 components
(#1384, #1390, #1394-#1400) are unmerged: they are read here as evidence at pinned heads, never cited as
precedent. No IAM, Terraform or spend is touched; no envelope here gates anything.

## 0. Verdict

Decision 88 made catalog egress "a FIRST-CLASS cost budget for the platform, ranked beside compute and
storage" after the Neon free tier's 5 GB/month cap was breached on 2026-06-15, and it said why a budget
needs a reading: "a budget you cannot read is a wish" (clause 2). The telemetry feedback loop adds a new
writer (every agent turn), new readers (session verbs and daily detectors), new files (one per table per
turn) and a new human cost (review items), and nine sibling components have designed it without a line
that says what any of it may cost. Seven of them hand that question here (VP 1). This component answers it
with a register of cost lines kept in physical units, a daily ledger with per-component attribution, and a
daily verdict; dollars are derived when read, as Decision 199 derives cost, never stored.

Measured, not argued:

- The repository has no budget for the loop. The roadmap's cost block calls itself "Not a budget; an
  architectural cost sanity-check"; its five re-evaluation triggers, mirrored by six thresholds in
  config/agent/cost_reconciliation.yaml, watch DeepSeek prices, the Anthropic pool, the S3 and Step
  Functions shares of the bill and the runner, and none of them Neon egress, Lambda, S3 requests or review
  load. The monthly reconciliation's telemetry leg returns None ("until T2.36 lands est_cost_usd"), the
  Decision 88 clause 2 egress figure is still "TBD" in the roadmap, no Terraform resource is a budget or a
  cost alarm, and catalog_stats, the supported measurement path, has no schedule (VP 2).
- The siblings know they cost something and say so without numbers: 7 of 9 reports hand cost or egress to
  this component in their W2 boundary notes; 1 of 9 names egress in its failure_signal or triggers (#1399,
  whose egress is the thing it governs, not a cost); 2 of 9 carry a criterion that names egress (#1390 c3
  measures per-call catalog egress before any consumer depends on a verb; #1399 c1, c2); 1 of 9 names a
  budget of its own (#1396's per-run filing cap) and 0 of 9 names a price (VP 1).
- A model built from the siblings' own measurements and the deployed shapes (section 2.3) says the loop's
  catalog egress is the first line to breach and that merge cadence, not session count, is its lever. With
  5 sessions a day of 40 turns, reading only the files each query touches, the loop reads about 1.58 GB of
  catalog metadata a month, over the 1 GiB seed envelope, and 83% of it is the daily detectors (each reads
  28 days of files). Under the access pattern Decision 88 documented (the postgres scanner copies
  ducklake_file_column_stats for the whole catalog per query, ducklake #859), the same 5 sessions read
  27.6 GB a month, five times the cap that was breached in June, because the catalog holds a year of
  un-expired files and every query pays for all of them. At 20 sessions a day, dropping merge_ops from
  four windows a day to one raises touched egress from 5.8 GB to 18.5 GB (VP 3).
- Everything else is cheap at list price: Lambda, S3 requests and storage for the loop come to about
  $0.90, $3.54 and $23.33 a month at 5, 20 and 100 sessions a day, before any free tier and excluding
  egress, which has no unit price anywhere in this repository (O5). The review line is the exception that
  is not priced in dollars at all: the ladder's read_all rung reads about 72 review items a day across six
  components (#1398 R1), 2,160 a month against a seed of 900, so the operator's own time is the line that
  breaches at every scale (VP 3, q3).
- The staged verdict SQL reads the register, the ledger and the attribution rows and returns one of ok,
  warn, projected_breach, breach, dark, unattributed or unregistered per line, raising on malformed input.
  It passes 61/61 vectors (18 by raising with the stated message); each of 70 single-site mutants (38
  named, 32 from a rule sweep) is killed, and one more is equivalent and listed apart (VP 4).

Staged, not decided: ten register lines (section 2.2) in bytes, counts, GB-seconds and tokens, each with an
owner (a sibling item or shared), a cadence (daily or event), a seed monthly envelope and a named source;
one ledger row per line per day and attribution rows per component for shared lines; and one daily
deterministic verdict (section 2.4) whose breach action is k1 (recommended: an alarm filed through the
existing cost reconciliation path, Decisions 55 and 62's alarm-not-gate shape, never a stop). Where the
budget lives (k2), what unit it is kept in (k3), how egress is measured (k4), how shared Lambdas are
attributed (k5) and the item's edge home (k6) are parked as asked. Nothing is ratified; the seed envelopes
are the model's, not a measurement's (q1).

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | Read at their pinned heads, 7 of 9 sibling reports hand cost or egress to this component in their section 5 boundary notes (#1390, #1394, #1395, #1397, #1398, #1399, #1400); #1384 and #1396 do not [VP 1] | the siblings block; sibling reports section 5 |
| e2 | 1 of 9 sibling failure_signals or maturity triggers names egress (#1399); 2 of 9 items carry a criterion naming egress (#1390 c3, #1399 c1 and c2); 1 of 9 items names a budget of its own (#1396's per-run filing cap) and 0 of 9 names a price; 8 of 9 are data-plane only (#1399 is data and control) [VP 1] | sibling fixtures |
| e3 | The roadmap cost_projection block says "Not a budget; an architectural cost sanity-check"; its 5 reevaluation_triggers name DeepSeek, the Anthropic pool, S3 share, the runner and Step Functions share, none egress, Neon, Lambda, catalog, review or telemetry; its neon_catalog_egress line begins "TBD" [VP 2] | docs/ROADMAP-PLATFORM.yaml cost_projection |
| e4 | config/agent/cost_reconciliation.yaml has 6 thresholds mirroring those 5 triggers plus invoice_vs_telemetry_discrepancy_pct 5.0; none names egress, Neon, Lambda or catalog [VP 2] | config/agent/cost_reconciliation.yaml:14 |
| e5 | load_telemetry_cost('2026-09') returns None: the telemetry leg of the monthly reconciliation is a stub "until T2.36 lands est_cost_usd"; no contract under docs/contracts names est_cost_usd, while 2 name cost_usd [VP 2] | scripts/cost_reconciliation.py:149 |
| e6 | 0 Terraform files declare an AWS budget or cost-anomaly resource; 0 non-comment Terraform lines name catalog_stats, so the Decision 88 clause 2 measurement path has no schedule; the reconciliation workflow runs monthly ("0 6 4 * *") [VP 2] | terraform/personal, .github/workflows/cost-reconciliation.yml:11 |
| e7 | .claude/settings.json wires 2 hook events (SessionStart, PreToolUse) and no Stop or SessionEnd hook, so no capture producer writes today and the ledger's writer lines read 0 until #1384 lands [VP 2] | .claude/settings.json |
| e8 | In the model, touched-files catalog egress per month is 1,576,200,000 bytes at 5 sessions a day (detector share 0.834), 5,779,200,000 at 20 and 96,595,200,000 at 100; whole-catalog egress is 27,621,000,000, 71,136,000,000 and 371,616,000,000; 20 sessions at one merge window a day reads 18,544,800,000 [VP 3] | section 2.3 |
| e9 | Against the seed envelopes, 3 lines are over at 5 sessions (catalog_egress_bytes, s3_requests, review_items), 5 at 20 (plus writer_requests, lambda_gb_seconds) and 7 at 100 (all but reader_requests); review_items is over at every scale (2,160 a month against 900) [VP 3] | section 2.3 |
| e10 | At list prices (eu-west-2, external, not re-verified) the loop's Lambda, S3 request and S3 storage lines cost about 0.90, 3.54 and 23.33 USD a month at 5, 20 and 100 sessions a day, before any free tier and excluding egress, which has no unit price in the repository [VP 3] | section 2.3; O5 |
| e11 | The staged verdict SQL passes 61 vectors, 18 of them by raising 'loop_budget: <rule>' with the first failing rule by name [VP 4] | sections 2.4, 2.5 |
| e12 | Each of 70 mutants of the verdict SQL (38 named, 32 from the rule sweep) replaces one unique site and fails at least one vector; one equivalent mutant is listed apart [VP 4] | section 2.6 |
| e13 | Decision 88 clause 1 ranks catalog egress beside compute and storage, with four access-pattern invariants; clause 2 names catalog_stats as the measurement path and defers the figure to a post-deploy measurement; clause 3 cut the DR dump to weekly for egress reasons | docs/DECISIONS.md, Decision 88 |
| e14 | Decision 199 derives state, friction and cost at read (its title); rec-4031's price table is the read-time price source; Decision 206 clause 7 budgets turns and wall-clock, "no dollars", before MVP | docs/DECISIONS.md, Decisions 199 and 206 |
| e15 | #1384 measured about 52 KB of wire and 55 rows per turn, and a 100-turn cold catch-up of 3.2 MB transcripts plus 2.1 MB observations; #1398 counted about 72 reviews a day at read_all across six components; #1397 R5 reads one verb call per pending candidate per run | sibling reports at the pinned heads |
| e16 | Decision 73 halt check: the reader's named verb ci_rca_open returned [] at the start of this thread | Step 0 |

Sibling heads read by VP 1 (pinned by sha, so a later push to a sibling branch does not change the reading):

```yaml
siblings:
  - {pr: 1384, item: pwi-capture-producer-wiring, slug: capture-producer-wiring, head: 1da1cc97f3522e5551ab32bcb41e3bb5b93cf685}  # pragma: allowlist secret
  - {pr: 1390, item: pwi-telemetry-reader-verbs, slug: reader-verbs, head: ab7aad7a36819a10069628577a55b2160cf8bd81}  # pragma: allowlist secret
  - {pr: 1394, item: pwi-friction-classifier, slug: friction-classifier, head: c6a47c5df5c1e50c7ab77730dadbe4456965772d}  # pragma: allowlist secret
  - {pr: 1395, item: pwi-deliberation-capture, slug: deliberation-capture, head: 63b1a50a6926561aac5fb5a9c651c6faba581dc5}  # pragma: allowlist secret
  - {pr: 1396, item: pwi-rec-filing-dedupe, slug: rec-filing-dedupe, head: 51958a0ae48a700963fc5b1351fed00e6a1decec}  # pragma: allowlist secret
  - {pr: 1397, item: pwi-back-validation, slug: back-validation, head: 75ad2896d79d7d83f91ddcb619a183972a716351}  # pragma: allowlist secret
  - {pr: 1398, item: pwi-maturity-ladder-controller, slug: maturity-ladder, head: f618343030ac07ffeab13c0ca2288577ad5d22db}  # pragma: allowlist secret
  - {pr: 1399, item: pwi-allow-list-transport, slug: allow-list-transport, head: 03feaf12dda0bdb6ea8718ccdff85e931e83a942}  # pragma: allowlist secret
  - {pr: 1400, item: pwi-goodhart-register, slug: goodhart-register, head: fc298254dd0e4a0661251217f6653c3dede840e2}  # pragma: allowlist secret
```

### 1.1 What the inventory shows

The siblings are consistent about cost in one way: each names it and hands it on. #1390 says Neon egress
per verb is unmeasured and caps its one parameter-scaled read at 7 days; #1394 reads typed facts only and
names a Decision 88 measurement as the switch to materialization; #1395 warns that reasoning tokens are
already inside tokens_output and must not be priced twice; #1397 reads one verb call per candidate; #1398
says review load is the controller's cost; #1399 asks who pays the egress under each transport; #1400 says
drills are recurring cost. None of them could put an envelope on any of it from inside its own item, and
none should have: a budget shared by ten components needs one owner, or every component sets its own and
the sum is nobody's.

The repository's cost surface was built for a different workload. CD.28's monthly reconciliation watches
the executor's inference bill and the big-ticket shares; its triggers are shares of a bill and price
factors, read once a month from an invoice snapshot (e3, e4). The loop's costs are different in kind:
metered egress with a hard cap already breached once, request counts in the hundreds of thousands, and a
human review line. A monthly share-of-bill trigger cannot see a 5 GB egress cap approaching on day 12, and
an invoice cannot be split between the components of one Lambda. So this component does not replace the
reconciliation; it feeds it (k1, k3): the ledger gives the monthly leg the telemetry side it is stubbed
for (e5), and the reconciliation's discrepancy leg is where the ledger is checked against the bill.

The industry practice applied is the FinOps one: allocate before you optimise (every line has an owner;
shared lines carry attribution), budget in the unit the meter counts and price at read (so a price change
re-prices history without rewriting it), alert on forecast rather than on actuals (projected_breach, warn),
and treat a dark meter as a failure in itself (the failure_signal is dark_line_days, not spend). The
anti-pattern it avoids is the one Decision 88 recorded: nothing measured the egress, so the first signal
was the bill.

## 2. Budget design (what this item stages)

### 2.1 What a budget line answers

A line is a meter with an owner. Each register row names: the unit the meter counts (bytes, count,
GB-seconds, tokens), never dollars; the owner, a pilot item or shared; the cadence, daily (a row is
expected every day and its absence is dark) or event (rows arrive only when the thing happens, so no row
is not dark); a seed monthly envelope in the line's unit with a warn share of 0.8; and the source the ledger
row is read from. Dollars are derived when read: a price table (rec-4031's for tokens, list prices for
Lambda and S3, none yet for Neon egress) applied to the day's quantity, as Decision 199 derives cost from
tokens and Decision 206 clause 7 budgets turns and wall-clock rather than dollars. That keeps the public
repository free of measured dollar figures (Decision 101; the reconciliation's public_summary rule), lets a
price change re-price the whole ledger without a rewrite, and makes the free tier's lines (local adapter,
no bill) meaningful as quantities even where no price applies (q2).

Attribution answers "who pays" for a shared line: the writer and reader Lambdas serve every component, so a
shared line's daily value must be explained by attribution rows, one per component, whose sum matches the
day's value within tolerance; a shared line with no attribution reads unattributed (k5).

### 2.2 The line register

The register (staged; k2 decides its home). Envelopes are seeds from the model in section 2.3, not
measurements (q1); the first measured month replaces them (c3).

```yaml
register:
  - {line: catalog_egress_bytes, unit: bytes, owner: shared, cadence: daily, envelope_month: 1073741824, warn_share: 0.8, source: 'catalog_stats bytes per read times reads per day (a proxy, Decision 88 cl.2), or the Neon consumption API (k4)', price_at_read: 'none in this repository (O5); the line stays in bytes'}
  - {line: writer_requests, unit: count, owner: shared, cadence: daily, envelope_month: 30000, warn_share: 0.8, source: 'CloudWatch Invocations on the writer Lambda (the dev role reads metrics since Decision 192)', price_at_read: 'Lambda request list price'}
  - {line: writer_bytes, unit: bytes, owner: pwi-capture-producer-wiring, cadence: daily, envelope_month: 2147483648, warn_share: 0.8, source: 'request bytes per writer call summed per day (#1384 measured about 52 KB per turn)', price_at_read: 'unpriced; a volume line that explains writer_requests and s3_storage_bytes'}
  - {line: reader_requests, unit: count, owner: shared, cadence: daily, envelope_month: 30000, warn_share: 0.8, source: 'CloudWatch Invocations on the reader Lambda', price_at_read: 'Lambda request list price'}
  - {line: lambda_gb_seconds, unit: GB-s, owner: shared, cadence: daily, envelope_month: 100000, warn_share: 0.8, source: 'CloudWatch Duration times configured memory per function (writer 3008 MB, reader 1024 MB, maintenance 1536 MB)', price_at_read: 'Lambda duration list price'}
  - {line: s3_requests, unit: count, owner: shared, cadence: daily, envelope_month: 300000, warn_share: 0.8, source: 'S3 request metrics on the telemetry prefix (PUT and GET)', price_at_read: 'S3 request list prices, PUT and GET apart'}
  - {line: s3_storage_bytes, unit: bytes, owner: pwi-capture-producer-wiring, cadence: daily, envelope_month: 21474836480, warn_share: 0.8, source: 'S3 BucketSizeBytes on the telemetry prefix (data files; blobs over 64 KiB spill to the blob port, Decision 199 cl.5)', price_at_read: 'S3 storage list price'}
  - {line: review_items, unit: count, owner: pwi-maturity-ladder-controller, cadence: daily, envelope_month: 900, warn_share: 0.8, source: 'rows of the ladder review table per day (#1398; about 72 a day at read_all across six components)', price_at_read: 'operator time; never priced in dollars (q3)'}
  - {line: plane_egress_bytes, unit: bytes, owner: pwi-allow-list-transport, cadence: event, envelope_month: 0, warn_share: 0.8, source: 'bytes of each egress batch, logged in the data plane before sending (#1399 section 2.7 audit row)', price_at_read: 'unpriced; a zero envelope reads any byte as breach until #1399 k1 is answered'}
  - {line: loop_llm_tokens, unit: tokens, owner: shared, cadence: event, envelope_month: 0, warn_share: 0.8, source: 'telemetry_observations tokens_input plus tokens_output for loop-owned producers (reasoning tokens are inside tokens_output, #1395; never add them twice)', price_at_read: 'rec-4031 price table at read (Decision 199)'}
```

Why these ten. The first seven are the meters the deployed shapes expose: the Neon catalog (Decision 88's
budget), the writer and reader Lambdas and the maintenance Lambda (invocations and GB-seconds), and the S3
telemetry prefix (requests and bytes). review_items is the human line every sibling defers to the ladder.
plane_egress_bytes and loop_llm_tokens are event lines with a zero envelope: today no loop component calls
a model (#1394's rules read typed facts; its k3 (b) would change that) and nothing crosses to a control
plane (#1399 k1 is always-ask), so any value on either line is a breach by construction until the operator
sets an envelope. A zero-envelope event line is the register's way of saying "this costs nothing until
someone decides it may" without a gate (v06, v07).

What is not a line. DeepSeek and Anthropic inference for the executor, the self-hosted runner, DynamoDB
and the rest of CD.28's bill stay with the monthly reconciliation; this register covers the loop's own
meters. Transcript blobs over 64 KiB (Decision 199 clause 5) land in the same S3 prefix and are inside
s3_storage_bytes, not a line of their own.

### 2.3 The cost model (VP 3)

The model is deterministic and built from the siblings' measurements and the deployed shapes; it shows
which line breaches first and what moves it, not what the bill will be. Its parameters are data in the
block below so a verifier can change one and re-run.

Shapes read from the repository (read-only; nothing provisioned): four telemetry tables (Decision 199); a
writer Lambda at 3008 MB, a reader at 1024 MB and a maintenance Lambda at 1536 MB; merge_ops every six
hours (four windows a day, raised from daily by the Neon egress work); inlining disabled (CD.34), so every
turn writes one data file per table and the catalog holds one stats row per file per column; no snapshot
expiry on production tables (Decision 88 clause 4 gates GC behind a restore drill), so files accumulate
for the retention period. Measurements read from the siblings: 52 KB of wire and 55 rows per turn (#1384);
72 review items a day (#1398); one verb call per back-validation candidate (#1397). Assumptions, each a
parameter: 40 turns a session; 3 session-verb calls per session (#1390's sessions_window, friction and
deliberation reads); 6 daily detectors over 28-day windows plus 10 back-validation candidates a day; 5,000
bytes of ducklake_file_column_stats per file (about 33 columns per table at roughly 150 bytes per stats
row); Parquet at 0.35 of wire size; 0.5 s per writer call and 1.0 s per reader call; a 365-day retention.

Two egress models, because the measurement does not exist (q1, k4). "touched" charges a query only for the
stats rows of the files it reads: the day's files for a session verb, 28 days for a detector. It is the
floor. "whole_catalog" charges every query the stats rows of every live file, which is the access pattern
Decision 88 clause 1 (D2) recorded: the postgres scanner's sequential COPY of ducklake_file_column_stats per
query (ducklake #859). Whether the scanner still does that after the warm-connection work is exactly what
catalog_stats would measure.

| sessions/day | merge windows/day | egress model | catalog egress bytes/month | detector share | files live at read (today) | lines over seed | list price ex egress, USD/month |
|---|---|---|---|---|---|---|---|
| 5 | 4 | touched | 1,576,200,000 | 0.834 | 116 | 3 | 0.90 |
| 20 | 4 | touched | 5,779,200,000 | 0.352 | 416 | 5 | 3.54 |
| 100 | 4 | touched | 96,595,200,000 | 0.061 | 2,016 | 7 | 23.33 |
| 5 | 4 | whole_catalog | 27,621,000,000 | 0.516 | 116 | 3 | 0.90 |
| 20 | 4 | whole_catalog | 71,136,000,000 | 0.211 | 416 | 5 | 3.54 |
| 100 | 4 | whole_catalog | 371,616,000,000 | 0.051 | 2,016 | 7 | 23.33 |
| 20 | 1 | touched | 18,544,800,000 | 0.222 | 1,604 | 5 | 4.61 |

What it says:

- Catalog egress breaches first at every scale and under both models, and under the Decision 88 pattern
  even the smallest scale reads 27.6 GB a month: a year of un-expired files is 5,824 merged files before
  today's are counted, and every query pays for all of them. The lever is not session count. It is how
  many files are live: merge cadence (one window a day instead of four triples the touched figure at 20
  sessions) and, under whole_catalog, snapshot expiry, which Decision 88 clause 4 keeps gated. That makes
  the GC gate (rec-2113's restore drill) a cost dependency of the loop, named for W2.
- At small scale the detectors, not the sessions, are the egress: 83% at 5 sessions a day under touched,
  because sixteen daily reads each cover 28 days of files. #1397's one-call-per-candidate rule and the
  detectors' windows are the second lever.
- Everything priced in dollars is small: under a dollar a month at 5 sessions, about $23 at 100, before the
  Lambda free tier. The lines that matter are the two without a dollar price: Neon egress (a cap, not a
  rate, with a paid plan already forced once) and review items (the operator's day; 2,160 a month at
  read_all against a seed of 900, so this line is over at every scale and is really the ladder's control
  knob, q3).
- s3_requests is over its seed at 5 sessions because each turn writes four files and each detector reads
  hundreds; at list price that is cents, so the seed is probably low rather than the loop expensive. Seeds
  are seeds (q1).

The model's SQL and parameters:

```yaml
cost_model:
  params:
    scales_sessions_per_day: [5, 20, 100]
    turns_per_session: 40
    wire_bytes_per_turn: 52000
    rows_per_turn: 55
    tables: 4
    requests_per_pass: 4
    merge_windows_per_day: 4
    stats_bytes_per_file: 5000
    per_session_verb_calls: 3
    daily_detectors: 6
    back_validation_candidates: 10
    detector_window_days: 28
    parquet_ratio: 0.35
    retention_days: 365
    writer_seconds: 0.5
    writer_gb: 2.9375
    reader_seconds: 1.0
    reader_gb: 1.0
    review_items_per_day: 72
    days_per_month: 30
  envelopes_month:
    catalog_egress_bytes: 1073741824
    writer_requests: 30000
    writer_bytes: 2147483648
    reader_requests: 30000
    lambda_gb_seconds: 100000
    s3_requests: 300000
    s3_storage_bytes: 21474836480
    review_items: 900
  sql: |
    WITH s AS (SELECT unnest({scales}) AS sessions, unnest({merges}) AS merge_windows, unnest({models}) AS egress_model),
    d AS (
      SELECT sessions, merge_windows, egress_model,
             sessions * {turns_per_session} AS turns,
             sessions * {turns_per_session} * {requests_per_pass} + sessions AS writer_requests,
             sessions * {turns_per_session} * {wire_bytes_per_turn} AS writer_bytes,
             sessions * {turns_per_session} * {rows_per_turn} AS rows_written,
             sessions * {turns_per_session} * {tables} AS files_written,
             {tables} * merge_windows AS files_per_day_merged,
             {tables} * merge_windows + {tables} * sessions * {turns_per_session} / merge_windows / 2.0 AS files_today
      FROM s
    ),
    e AS (
      SELECT *,
             CASE egress_model WHEN 'touched' THEN files_today ELSE files_per_day_merged * ({retention_days} - 1) + files_today END * {stats_bytes_per_file} AS egress_per_session_call,
             CASE egress_model WHEN 'touched' THEN ({detector_window_days} - 1) * files_per_day_merged + files_today ELSE files_per_day_merged * ({retention_days} - 1) + files_today END * {stats_bytes_per_file} AS egress_per_detector_run,
             sessions * {per_session_verb_calls} + {daily_detectors} + {back_validation_candidates} AS reader_requests
      FROM d
    ),
    f AS (
      SELECT *,
             sessions * {per_session_verb_calls} * egress_per_session_call AS egress_sessions,
             ({daily_detectors} + {back_validation_candidates}) * egress_per_detector_run AS egress_detectors,
             files_written + files_per_day_merged AS s3_puts,
             sessions * {per_session_verb_calls} * files_today + ({daily_detectors} + {back_validation_candidates}) * (({detector_window_days} - 1) * files_per_day_merged + files_today) AS s3_gets,
             writer_requests * {writer_seconds} * {writer_gb} + reader_requests * {reader_seconds} * {reader_gb} AS lambda_gb_s
      FROM e
    )
    SELECT sessions, merge_windows, egress_model,
           CAST(round((egress_sessions + egress_detectors) * {days_per_month}) AS BIGINT) AS catalog_egress_bytes,
           round(egress_detectors / (egress_sessions + egress_detectors), 3) AS detector_share,
           writer_requests * {days_per_month} AS writer_requests,
           CAST(writer_bytes AS BIGINT) * {days_per_month} AS writer_bytes,
           reader_requests * {days_per_month} AS reader_requests,
           CAST(round(lambda_gb_s * {days_per_month}) AS BIGINT) AS lambda_gb_seconds,
           CAST(round((s3_puts + s3_gets) * {days_per_month}) AS BIGINT) AS s3_requests,
           CAST(round(s3_puts * {days_per_month}) AS BIGINT) AS s3_puts,
           CAST(round(s3_gets * {days_per_month}) AS BIGINT) AS s3_gets,
           CAST(round(writer_bytes * {parquet_ratio} * {retention_days}) AS BIGINT) AS s3_storage_bytes,
           {review_items_per_day} * {days_per_month} AS review_items,
           CAST(files_today AS INTEGER) AS files_today
    FROM f ORDER BY egress_model DESC, merge_windows DESC, sessions
  prices_external:
    note: list prices, region eu-west-2, external and not re-verified here; applied at read, never stored; the loop's own catalog egress has no public unit price in this repository, so it stays in bytes
    lambda_per_gb_second_usd: 0.0000166667
    lambda_per_million_requests_usd: 0.20
    s3_put_per_thousand_usd: 0.0053
    s3_get_per_thousand_usd: 0.00042
    s3_storage_per_gb_month_usd: 0.024
```

### 2.4 The verdict (staged)

One SQL per daily run. Inputs (all build-time objects; k2): `{budget}`, one row per register line (line,
unit, owner, cadence, envelope, warn_share) with envelope the month's envelope in the line's unit;
`{ledger}`, one row per line per day (line, day, value), value the day's quantity in the line's unit;
`{attribution}`, one row per line per day per component (line, day, component, value). Params are data,
stamped on every verdict record: a rate window of 7 days for the projection and a tolerance of 0.01 for
attribution. The output is one row per line that appears in any of the three tables (VP 4 fails a
repeated row).

One rule governs history: the ledger and attribution are read through a 31-day window (after today minus
31 days, up to and including today), guards included, so rows dated after today or older than the window
are never read (v18, v19) and a malformed row outside it neither raises nor decides. The one exception is a
row with a NULL day, which cannot be placed in time, so it raises wherever it is (e09, e10, e18).

Per line, in order of precedence (v13-v16):

- unregistered: a ledger or attribution line with no budget row (v08, v33). It never halts the run: a
  meter that starts reporting before its register row exists is the finding, not an error.
- breach: the month-to-date sum, rounded to 9 places, exceeds the envelope (v04). Month-to-date starts on
  the first of the calendar month (v17, v22); on the last day of the month nothing is projected (v21).
- dark: a daily-cadence line with no ledger row today (v05, v39). An event line is never dark (v06, v41).
  Dark outranks projection because a meter that stopped is not evidence that spend stopped.
- projected_breach: month-to-date plus the mean daily value over the last 7 days times the days remaining
  in the month exceeds the envelope (v03, v20, v42). A line with no rows in the window projects its
  month-to-date alone (v31).
- unattributed: the line has a row today and either it is shared with no attribution parts (v09), or
  its parts' sum differs from today's value by more than tolerance times today's value (v11, v12, v26,
  v27). An owned line needs no attribution (v40); attribution on another day does not count (v28, v43).
- warn: the projection exceeds warn_share times the envelope (v02, v25, v34).
- ok otherwise (v01, v10, v30, v32).

Every comparison is strict and read at 9 decimal places (v23-v26, v35-v38), so an envelope met exactly is
ok and a sum that differs from its envelope only in floating-point noise does not breach.

Malformed input raises instead of deciding (fail loud, Decision 55 by analogy): a blank or duplicate
budget line, an envelope that is NULL, non-finite or negative, a warn share outside (0, 1], a cadence other
than daily or event, a NULL day anywhere, a ledger or attribution value that is NULL, non-finite or
negative, a duplicate (line, day) in the ledger or (line, day, component) in the attribution, a rate
window outside 1-31 days, a tolerance outside [0, 1). The message names the first failing rule in
alphabetical order (e17), so a run with several defects is repaired in a stable order. A zero envelope is
legal (v07): it is how an event line says "nothing may happen here yet".

What the verdict does not do: it gates nothing. A breach on a line is a reading; what follows is k1. The
verdict reads quantities only; pricing is a separate read over the same ledger, and a price change changes
no verdict.

```yaml
verdict:
  params: {window_days: 7, tolerance: 0.01}
  sql: |
    WITH p AS (
      SELECT {today} AS today, CAST(date_trunc('month', {today}) AS DATE) AS month_start,
             last_day({today}) - {today} AS days_remaining, {window_days} AS window_days, {tolerance} AS tolerance
    ),
    b AS (SELECT * FROM {budget}),
    l AS (SELECT * FROM {ledger} WHERE day IS NULL OR (day > (SELECT today FROM p) - 31 AND day <= (SELECT today FROM p))),
    a AS (SELECT * FROM {attribution} WHERE day IS NULL OR (day > (SELECT today FROM p) - 31 AND day <= (SELECT today FROM p))),
    g AS (
      SELECT 'budget_line' AS rule, count(*) AS n FROM b WHERE line IS NULL OR trim(line) = ''
      UNION ALL SELECT 'duplicate_budget', count(*) - count(DISTINCT line) FROM b
      UNION ALL SELECT 'envelope', count(*) FROM b WHERE envelope IS NULL OR NOT isfinite(envelope) OR envelope < 0
      UNION ALL SELECT 'warn_share', count(*) FROM b WHERE warn_share IS NULL OR NOT isfinite(warn_share) OR warn_share <= 0 OR warn_share > 1
      UNION ALL SELECT 'cadence', count(*) FROM b WHERE cadence IS NULL OR cadence NOT IN ('daily', 'event')
      UNION ALL SELECT 'null_day', count(*) FROM (SELECT day FROM l UNION ALL SELECT day FROM a) WHERE day IS NULL
      UNION ALL SELECT 'ledger_value', count(*) FROM l WHERE value IS NULL OR NOT isfinite(value) OR value < 0
      UNION ALL SELECT 'duplicate_ledger', count(*) - count(DISTINCT (line, day)) FROM l
      UNION ALL SELECT 'attribution_value', count(*) FROM a WHERE value IS NULL OR NOT isfinite(value) OR value < 0
      UNION ALL SELECT 'duplicate_attribution', count(*) - count(DISTINCT (line, day, component)) FROM a
      UNION ALL SELECT 'window_days', CASE WHEN (SELECT window_days FROM p) BETWEEN 1 AND 31 THEN 0 ELSE 1 END
      UNION ALL SELECT 'tolerance', CASE WHEN (SELECT tolerance FROM p) >= 0 AND (SELECT tolerance FROM p) < 1 THEN 0 ELSE 1 END
    ),
    chk AS (SELECT CASE WHEN EXISTS (SELECT 1 FROM g WHERE n > 0) THEN error('loop_budget: ' || (SELECT rule FROM g WHERE n > 0 ORDER BY rule LIMIT 1)) END AS guard),
    lines AS (SELECT line FROM b UNION SELECT line FROM l UNION SELECT line FROM a),
    m AS (
      SELECT line,
             coalesce(sum(value) FILTER (WHERE day >= (SELECT month_start FROM p)), 0) AS mtd,
             avg(value) FILTER (WHERE day > (SELECT today FROM p) - (SELECT window_days FROM p)) AS rate,
             count(*) FILTER (WHERE day = (SELECT today FROM p)) AS today_rows,
             max(value) FILTER (WHERE day = (SELECT today FROM p)) AS today_value
      FROM l GROUP BY line
    ),
    ab AS (SELECT line, sum(value) AS attributed, count(*) AS parts FROM a WHERE day = (SELECT today FROM p) GROUP BY line),
    v AS (
      SELECT x.line,
             b.envelope, b.warn_share, b.cadence, b.owner,
             coalesce(m.mtd, 0) AS mtd,
             coalesce(m.mtd, 0) + coalesce(m.rate, 0) * (SELECT days_remaining FROM p) AS projected,
             coalesce(m.today_rows, 0) AS today_rows,
             m.today_value,
             ab.attributed, coalesce(ab.parts, 0) AS parts
      FROM lines x LEFT JOIN b ON b.line = x.line LEFT JOIN m ON m.line = x.line LEFT JOIN ab ON ab.line = x.line
    )
    SELECT line,
           CASE
             WHEN envelope IS NULL THEN 'unregistered'
             WHEN round(mtd, 9) > envelope THEN 'breach'
             WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'
             WHEN round(projected, 9) > envelope THEN 'projected_breach'
             WHEN today_rows > 0 AND (
                    (owner = 'shared' AND parts = 0)
                    OR (parts > 0 AND abs(round(attributed - today_value, 9)) > round((SELECT tolerance FROM p) * today_value, 9))
                  ) THEN 'unattributed'
             WHEN round(projected, 9) > round(warn_share * envelope, 9) THEN 'warn'
             ELSE 'ok'
           END AS verdict
    FROM v
    WHERE (SELECT guard FROM chk) IS NULL
    ORDER BY line
```

### 2.5 Vectors (VP 4)

Each vector builds the three tables from day offsets relative to its today (2026-10-15 unless the vector
sets one), applies the params (a vector may override window_days or tolerance), runs the SQL and compares
the full {line: verdict} map, or the raise message. v01-v43 pass with a verdict; e01-e18 pass by raising.
Groups: the seven verdicts (v01-v09), attribution (v10-v12, v27-v29, v40, v43), precedence (v13-v16),
history and windows (v17-v22, v31, v42), strict boundaries (v23-v26), independence of lines (v30), the
empty world (v32), rounding to 9 places (v35-v38, each pinned with values whose floating-point sum differs
from the exact one), and each guard with its first-failing-rule order (e01-e18).

```yaml
vectors:
  defaults:
    today: '2026-10-15'
    budget_row: {line: catalog_egress_bytes, unit: bytes, owner: pwi-loop-cost-egress-budget, cadence: daily, envelope: 1000, warn_share: 0.8}
  cases:
  - id: v01-ok-daily-line
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: ok}
  - id: v02-warn-on-projection
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 40}
    expected: {catalog_egress_bytes: warn}
  - id: v03-projected-breach
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 50}
    expected: {catalog_egress_bytes: projected_breach}
  - id: v04-breach-month-to-date
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 200}
    expected: {catalog_egress_bytes: breach}
  - id: v05-dark-daily-line-no-row-today
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: -1, value: 10}
    expected: {catalog_egress_bytes: dark}
  - id: v06-event-line-no-rows-is-ok
    budget:
    - {line: plane_egress_bytes, cadence: event, envelope: 0}
    expected: {plane_egress_bytes: ok}
  - id: v07-event-line-zero-envelope-any-value-breaches
    budget:
    - {line: plane_egress_bytes, cadence: event, envelope: 0}
    ledger:
    - {line: plane_egress_bytes, from: 0, to: 0, value: 1}
    expected: {plane_egress_bytes: breach}
  - id: v08-unregistered-ledger-line
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    - {line: mystery_line, from: 0, to: 0, value: 1}
    expected: {catalog_egress_bytes: ok, mystery_line: unregistered}
  - id: v09-shared-line-needs-attribution
    budget:
    - {line: reader_requests, unit: requests, owner: shared}
    ledger:
    - {line: reader_requests, from: -6, to: 0, value: 10}
    expected: {reader_requests: unattributed}
  - id: v10-shared-line-fully-attributed
    budget:
    - {line: reader_requests, unit: requests, owner: shared}
    ledger:
    - {line: reader_requests, from: -6, to: 0, value: 10}
    attribution:
    - {line: reader_requests, day: 0, component: pwi-telemetry-reader-verbs, value: 6}
    - {line: reader_requests, day: 0, component: pwi-back-validation, value: 4}
    expected: {reader_requests: ok}
  - id: v11-attribution-off-beyond-tolerance
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 90}
    expected: {catalog_egress_bytes: unattributed}
  - id: v12-attribution-within-tolerance
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 99.5}
    expected: {catalog_egress_bytes: ok}
  - id: v13-breach-before-dark
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: -1, value: 200}
    expected: {catalog_egress_bytes: breach}
  - id: v14-dark-before-projected-breach
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: -1, value: 100}
    expected: {catalog_egress_bytes: dark}
  - id: v15-projected-breach-before-unattributed
    budget:
    - {owner: shared}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 50}
    expected: {catalog_egress_bytes: projected_breach}
  - id: v16-unattributed-before-warn
    budget:
    - {owner: shared}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 40}
    expected: {catalog_egress_bytes: unattributed}
  - id: v17-month-to-date-starts-on-the-first
    budget:
    - {envelope: 200}
    ledger:
    - {line: catalog_egress_bytes, from: -20, to: 0, value: 10}
    expected: {catalog_egress_bytes: projected_breach}
  - id: v18-future-rows-ignored
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    - {line: catalog_egress_bytes, from: 1, to: 5, value: 1000}
    expected: {catalog_egress_bytes: ok}
  - id: v19-malformed-row-before-the-guard-window-ignored
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    - {line: catalog_egress_bytes, from: -40, to: -35, value: -5}
    expected: {catalog_egress_bytes: ok}
  - id: v20-rate-reads-the-window-only
    budget:
    - {envelope: 8000}
    ledger:
    - {line: catalog_egress_bytes, from: -14, to: -8, value: 1000}
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: warn}
  - id: v21-last-day-of-month-projects-nothing
    params: {today: '2026-10-31'}
    budget:
    - {envelope: 750}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    expected: {catalog_egress_bytes: warn}
  - id: v22-first-day-of-month
    params: {today: '2026-10-01'}
    budget:
    - {envelope: 320}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: warn}
  - id: v23-breach-boundary-is-strict
    params: {today: '2026-10-31'}
    budget:
    - {envelope: 700}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    expected: {catalog_egress_bytes: warn}
  - id: v24-projection-boundary-is-strict
    budget:
    - {envelope: 230}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: warn}
  - id: v25-warn-boundary-is-strict
    budget:
    - {envelope: 287.5}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: ok}
  - id: v26-tolerance-boundary-is-strict
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 99}
    expected: {catalog_egress_bytes: ok}
  - id: v27-attribution-parts-sum
    budget:
    - {envelope: 100000, owner: shared}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 60}
    - {line: catalog_egress_bytes, day: 0, component: pwi-back-validation, value: 40}
    expected: {catalog_egress_bytes: ok}
  - id: v28-attribution-on-another-day-does-not-count
    budget:
    - {owner: shared}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    attribution:
    - {line: catalog_egress_bytes, day: -1, component: pwi-telemetry-reader-verbs, value: 10}
    expected: {catalog_egress_bytes: unattributed}
  - id: v29-zero-value-attributed-nonzero
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 0}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 0.001}
    expected: {catalog_egress_bytes: unattributed}
  - id: v30-two-lines-independent
    budget:
    - {}
    - {line: writer_bytes, envelope: 100}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    - {line: writer_bytes, from: -6, to: 0, value: 50}
    expected: {catalog_egress_bytes: ok, writer_bytes: breach}
  - id: v31-event-line-mtd-with-no-window-rows
    budget:
    - {line: plane_egress_bytes, cadence: event, envelope: 310}
    ledger:
    - {line: plane_egress_bytes, from: -10, to: -8, value: 100}
    expected: {plane_egress_bytes: warn}
  - id: v32-empty-world
    expected: {}
  - id: v33-attribution-only-line-is-unregistered
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    attribution:
    - {line: ghost_line, day: 0, component: pwi-back-validation, value: 1}
    expected: {catalog_egress_bytes: ok, ghost_line: unregistered}
  - id: v34-warn-share-one
    budget:
    - {envelope: 230, warn_share: 1.0}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: ok}
  - id: v35-breach-exact-to-nine-places
    params: {today: '2026-10-31'}
    budget:
    - {envelope: 0.3}
    ledger:
    - {line: catalog_egress_bytes, from: -1, to: -1, value: 0.1}
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 0.2}
    expected: {catalog_egress_bytes: warn}
  - id: v36-projection-exact-to-nine-places
    budget:
    - {envelope: 2.7}
    ledger:
    - {line: catalog_egress_bytes, from: -1, to: -1, value: 0.1}
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 0.2}
    expected: {catalog_egress_bytes: warn}
  - id: v37-attribution-exact-to-nine-places
    params: {tolerance: 0}
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 0.3}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 0.1}
    - {line: catalog_egress_bytes, day: 0, component: pwi-back-validation, value: 0.2}
    expected: {catalog_egress_bytes: ok}
  - id: v38-tolerance-product-exact-to-nine-places
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 0.7}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 0.693}
    expected: {catalog_egress_bytes: ok}
  - id: v39-dark-even-when-month-to-date-known
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -14, to: -1, value: 10}
    expected: {catalog_egress_bytes: dark}
  - id: v40-owned-line-no-attribution-is-fine
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 100}
    expected: {catalog_egress_bytes: ok}
  - id: v41-shared-event-line-no-rows-is-ok
    budget:
    - {line: plane_egress_bytes, cadence: event, owner: shared, envelope: 0}
    expected: {plane_egress_bytes: ok}
  - id: v42-rate-window-edge-is-exclusive
    budget:
    - {envelope: 1500}
    ledger:
    - {line: catalog_egress_bytes, from: -7, to: -7, value: 1000}
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    expected: {catalog_egress_bytes: warn}
  - id: v43-attribution-compares-todays-value-only
    budget:
    - {envelope: 100000}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: -2, value: 10}
    - {line: catalog_egress_bytes, from: -1, to: -1, value: 100}
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 10}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-telemetry-reader-verbs, value: 10}
    expected: {catalog_egress_bytes: ok}
  - id: e01-envelope-negative
    budget:
    - {envelope: -0.5}
    expected: error
    raises: 'loop_budget: envelope'
  - id: e02-envelope-nan
    budget:
    - {envelope: .nan}
    expected: error
    raises: 'loop_budget: envelope'
  - id: e03-warn-share-zero
    budget:
    - {warn_share: 0}
    expected: error
    raises: 'loop_budget: warn_share'
  - id: e04-warn-share-above-one
    budget:
    - {warn_share: 1.5}
    expected: error
    raises: 'loop_budget: warn_share'
  - id: e05-cadence-unknown
    budget:
    - {cadence: weekly}
    expected: error
    raises: 'loop_budget: cadence'
  - id: e06-ledger-value-negative
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: -0.5}
    expected: error
    raises: 'loop_budget: ledger_value'
  - id: e07-ledger-value-infinite
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: .inf}
    expected: error
    raises: 'loop_budget: ledger_value'
  - id: e08-duplicate-ledger-day
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 1}
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 2}
    expected: error
    raises: 'loop_budget: duplicate_ledger'
  - id: e09-null-day-in-ledger
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: null, to: null, value: 1}
    expected: error
    raises: 'loop_budget: null_day'
  - id: e10-null-day-in-attribution
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 1}
    attribution:
    - {line: catalog_egress_bytes, day: null, component: pwi-back-validation, value: 1}
    expected: error
    raises: 'loop_budget: null_day'
  - id: e11-attribution-value-negative
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 1}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-back-validation, value: -0.5}
    expected: error
    raises: 'loop_budget: attribution_value'
  - id: e12-duplicate-attribution
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 1}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-back-validation, value: 0.5}
    - {line: catalog_egress_bytes, day: 0, component: pwi-back-validation, value: 0.6}
    expected: error
    raises: 'loop_budget: duplicate_attribution'
  - id: e13-duplicate-budget-line
    budget:
    - {envelope: 1000}
    - {envelope: 2000}
    expected: error
    raises: 'loop_budget: duplicate_budget'
  - id: e14-blank-budget-line
    budget:
    - {line: ' '}
    expected: error
    raises: 'loop_budget: budget_line'
  - id: e15-window-days-zero
    params: {window_days: 0}
    budget:
    - {}
    expected: error
    raises: 'loop_budget: window_days'
  - id: e16-tolerance-one
    params: {tolerance: 1}
    budget:
    - {}
    expected: error
    raises: 'loop_budget: tolerance'
  - id: e17-first-failing-rule-by-name
    budget:
    - {envelope: -1}
    ledger:
    - {line: catalog_egress_bytes, from: 0, to: 0, value: 1}
    attribution:
    - {line: catalog_egress_bytes, day: 0, component: pwi-back-validation, value: -1}
    expected: error
    raises: 'loop_budget: attribution_value'
  - id: e18-null-day-raises-even-outside-window
    budget:
    - {}
    ledger:
    - {line: catalog_egress_bytes, from: -6, to: 0, value: 10}
    - {line: catalog_egress_bytes, from: null, to: null, value: 1}
    expected: error
    raises: 'loop_budget: null_day'
```

### 2.6 Mutants (VP 4)

Each mutant replaces one exact substring of the verdict SQL (it must occur exactly once) and must fail at
least one vector. m01-m38 are named: each verdict comparison made inclusive, each precedence pair swapped,
each window and guard widened or dropped, the attribution rule relaxed in each direction, each rounding
removed, the first-failing-rule order reversed. s-guard-* drop each of the twelve guards (always 0);
s-case-* flip every comparison in the verdict CASE to its neighbours; s-window-* widen each of the five
history reads (month-to-date, the rate window, today's rows, today's value, today's attribution). One
mutant from the sweep is equivalent and listed apart: reading `parts > 0` as `parts >= 0` in the tolerance
clause cannot change a verdict, because when parts is 0 the attributed sum is NULL and the comparison is
NULL either way; the shared-line clause before it is what fires. VP 4 counts the kills and the unique
sites and checks that the equivalent mutant passes every vector.

```yaml
mutants:
- {id: m01-breach-inclusive, old: 'round(mtd, 9) > envelope', new: 'round(mtd, 9) >= envelope'}
- {id: m02-dark-ignores-cadence, old: WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark', new: WHEN today_rows = 0 THEN 'dark'}
- {id: m03-projection-inclusive, old: 'round(projected, 9) > envelope', new: 'round(projected, 9) >= envelope'}
- {id: m04-attribution-required-everywhere, old: (owner = 'shared' AND parts = 0), new: (parts = 0)}
- {id: m05-tolerance-inclusive, old: 'abs(round(attributed - today_value, 9)) > round((SELECT tolerance FROM p) * today_value, 9)', new: 'abs(round(attributed - today_value, 9)) >= round((SELECT tolerance FROM p) * today_value, 9)'}
- {id: m06-warn-inclusive, old: 'round(projected, 9) > round(warn_share * envelope, 9)', new: 'round(projected, 9) >= round(warn_share * envelope, 9)'}
- {id: m07-mtd-ignores-month-start, old: FILTER (WHERE day >= (SELECT month_start FROM p)), new: FILTER (WHERE day <= (SELECT today FROM p))}
- {id: m08-rate-reads-all-history, old: FILTER (WHERE day > (SELECT today FROM p) - (SELECT window_days FROM p)), new: FILTER (WHERE day > (SELECT today FROM p) - 31)}
- {id: m09-days-remaining-off-by-one, old: 'last_day({today}) - {today} AS days_remaining', new: 'last_day({today}) - {today} + 1 AS days_remaining'}
- {id: m10-missing-rate-read-as-one, old: 'coalesce(m.rate, 0)', new: 'coalesce(m.rate, 1)'}
- {id: m11-guard-window-widened, old: 'FROM {ledger} WHERE day IS NULL OR (day > (SELECT today FROM p) - 31', new: 'FROM {ledger} WHERE day IS NULL OR (day > (SELECT today FROM p) - 400'}
- {id: m12-future-rows-admitted, old: 'FROM {ledger} WHERE day IS NULL OR (day > (SELECT today FROM p) - 31 AND day <= (SELECT today FROM p))', new: 'FROM {ledger} WHERE day IS NULL OR (day > (SELECT today FROM p) - 31 AND day <= (SELECT today FROM p) + 31)'}
- {id: m13-envelope-guard-loosened, old: OR envelope < 0, new: OR envelope < -1}
- {id: m14-warn-share-guard-loosened, old: OR warn_share > 1, new: OR warn_share > 2}
- {id: m15-cadence-guard-widened, old: 'cadence NOT IN (''daily'', ''event'')', new: 'cadence NOT IN (''daily'', ''event'', ''weekly'')'}
- {id: m16-ledger-value-guard-loosened, old: FROM l WHERE value IS NULL OR NOT isfinite(value) OR value < 0, new: FROM l WHERE value IS NULL OR NOT isfinite(value) OR value < -1}
- {id: m17-attribution-value-guard-loosened, old: FROM a WHERE value IS NULL OR NOT isfinite(value) OR value < 0, new: FROM a WHERE value IS NULL OR NOT isfinite(value) OR value < -1}
- {id: m18-duplicate-ledger-keyed-on-value, old: 'count(DISTINCT (line, day)) FROM l', new: 'count(DISTINCT (line, day, value)) FROM l'}
- {id: m19-duplicate-attribution-keyed-on-value, old: 'count(DISTINCT (line, day, component)) FROM a', new: 'count(DISTINCT (line, day, component, value)) FROM a'}
- {id: m20-duplicate-budget-keyed-on-envelope, old: count(DISTINCT line) FROM b, new: 'count(DISTINCT (line, envelope)) FROM b'}
- {id: m21-null-day-guard-dropped, old: 'SELECT ''null_day'', count(*)', new: 'SELECT ''null_day'', 0 * count(*)'}
- {id: m22-null-day-guard-skips-attribution, old: UNION ALL SELECT day FROM a) WHERE day IS NULL, new: UNION ALL SELECT day FROM l) WHERE day IS NULL}
- {id: m23-unregistered-reads-ok, old: WHEN envelope IS NULL THEN 'unregistered', new: WHEN envelope IS NULL THEN 'ok'}
- {id: m24-attribution-lines-not-listed, old: UNION SELECT line FROM a), new: UNION SELECT line FROM l)}
- {id: m25-dark-before-breach, old: "WHEN round(mtd, 9) > envelope THEN 'breach'\n         WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'", new: "WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'\n         WHEN round(mtd, 9) > envelope THEN 'breach'"}
- {id: m26-projection-before-dark, old: "WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'\n         WHEN round(projected, 9) > envelope THEN 'projected_breach'", new: "WHEN round(projected, 9) > envelope THEN 'projected_breach'\n         WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'"}
- {id: m27-unattributed-before-projection, old: "WHEN round(projected, 9) > envelope THEN 'projected_breach'\n         WHEN today_rows > 0 AND (", new: "WHEN today_rows > 0 AND round(projected, 9) > envelope AND false THEN 'never'\n         WHEN round(projected, 9) > envelope AND today_rows = 0 THEN 'projected_breach'\n         WHEN today_rows > 0 AND ("}
- {id: m28-warn-before-unattributed, old: "              ) THEN 'unattributed'\n         WHEN round(projected, 9) > round(warn_share * envelope, 9) THEN 'warn'", new: "              ) AND NOT round(projected, 9) > round(warn_share * envelope, 9) THEN 'unattributed'\n         WHEN round(projected, 9) > round(warn_share * envelope, 9) THEN 'warn'"}
- {id: m29-attribution-any-day, old: FROM a WHERE day = (SELECT today FROM p) GROUP BY line, new: FROM a GROUP BY line}
- {id: m30-window-days-guard-admits-zero, old: BETWEEN 1 AND 31 THEN 0, new: BETWEEN 0 AND 31 THEN 0}
- {id: m31-tolerance-guard-admits-one, old: (SELECT tolerance FROM p) < 1 THEN 0, new: (SELECT tolerance FROM p) <= 1 THEN 0}
- {id: m32-first-failing-rule-reversed, old: ORDER BY rule LIMIT 1, new: ORDER BY rule DESC LIMIT 1}
- {id: m33-breach-unrounded, old: 'WHEN round(mtd, 9) > envelope', new: WHEN mtd > envelope}
- {id: m34-projection-unrounded, old: 'WHEN round(projected, 9) > envelope', new: WHEN projected > envelope}
- {id: m35-attribution-difference-unrounded, old: 'abs(round(attributed - today_value, 9))', new: abs(attributed - today_value)}
- {id: m36-tolerance-product-unrounded, old: 'round((SELECT tolerance FROM p) * today_value, 9)', new: (SELECT tolerance FROM p) * today_value}
- {id: m37-dark-when-rows-today, old: cadence = 'daily' AND today_rows = 0 THEN 'dark', new: cadence = 'daily' AND today_rows > 0 THEN 'dark'}
- {id: m38-shared-attribution-not-required, old: "(owner = 'shared' AND parts = 0)\n                OR ", new: ''}
- {id: s-guard-budget-line, what: guard budget_line dropped (always 0), old: 'SELECT ''budget_line'' AS rule, count(*) AS n FROM b WHERE line IS NULL OR trim(line) = ''''', new: 'SELECT ''budget_line'' AS rule, 0'}
- {id: s-guard-duplicate-budget, what: guard duplicate_budget dropped (always 0), old: 'SELECT ''duplicate_budget'', count(*) - count(DISTINCT line) FROM b', new: 'SELECT ''duplicate_budget'', 0'}
- {id: s-guard-envelope, what: guard envelope dropped (always 0), old: 'SELECT ''envelope'', count(*) FROM b WHERE envelope IS NULL OR NOT isfinite(envelope) OR envelope < 0', new: 'SELECT ''envelope'', 0'}
- {id: s-guard-warn-share, what: guard warn_share dropped (always 0), old: 'SELECT ''warn_share'', count(*) FROM b WHERE warn_share IS NULL OR NOT isfinite(warn_share) OR warn_share <= 0 OR warn_share > 1', new: 'SELECT ''warn_share'', 0'}
- {id: s-guard-cadence, what: guard cadence dropped (always 0), old: 'SELECT ''cadence'', count(*) FROM b WHERE cadence IS NULL OR cadence NOT IN (''daily'', ''event'')', new: 'SELECT ''cadence'', 0'}
- {id: s-guard-null-day, what: guard null_day dropped (always 0), old: 'SELECT ''null_day'', count(*) FROM (SELECT day FROM l UNION ALL SELECT day FROM a) WHERE day IS NULL', new: 'SELECT ''null_day'', 0'}
- {id: s-guard-ledger-value, what: guard ledger_value dropped (always 0), old: 'SELECT ''ledger_value'', count(*) FROM l WHERE value IS NULL OR NOT isfinite(value) OR value < 0', new: 'SELECT ''ledger_value'', 0'}
- {id: s-guard-duplicate-ledger, what: guard duplicate_ledger dropped (always 0), old: 'SELECT ''duplicate_ledger'', count(*) - count(DISTINCT (line, day)) FROM l', new: 'SELECT ''duplicate_ledger'', 0'}
- {id: s-guard-attribution-value, what: guard attribution_value dropped (always 0), old: 'SELECT ''attribution_value'', count(*) FROM a WHERE value IS NULL OR NOT isfinite(value) OR value < 0', new: 'SELECT ''attribution_value'', 0'}
- {id: s-guard-duplicate-attribution, what: guard duplicate_attribution dropped (always 0), old: 'SELECT ''duplicate_attribution'', count(*) - count(DISTINCT (line, day, component)) FROM a', new: 'SELECT ''duplicate_attribution'', 0'}
- {id: s-guard-window-days, what: guard window_days dropped (always 0), old: 'SELECT ''window_days'', CASE WHEN (SELECT window_days FROM p) BETWEEN 1 AND 31 THEN 0 ELSE 1 END', new: 'SELECT ''window_days'', 0'}
- {id: s-guard-tolerance, what: guard tolerance dropped (always 0), old: 'SELECT ''tolerance'', CASE WHEN (SELECT tolerance FROM p) >= 0 AND (SELECT tolerance FROM p) < 1 THEN 0 ELSE 1 END', new: 'SELECT ''tolerance'', 0'}
- {id: s-case-01, what: verdict comparison '>' read as '>=' at CASE offset 90, old: "nregistered'\n         WHEN round(mtd, 9) > envelope THEN 'breach'\n         WHEN cad", new: "nregistered'\n         WHEN round(mtd, 9) >= envelope THEN 'breach'\n         WHEN cad"}
- {id: s-case-02, what: verdict comparison '>' read as '<' at CASE offset 90, old: "nregistered'\n         WHEN round(mtd, 9) > envelope THEN 'breach'\n         WHEN cad", new: "nregistered'\n         WHEN round(mtd, 9) < envelope THEN 'breach'\n         WHEN cad"}
- {id: s-case-03, what: verdict comparison '>' read as '>=' at CASE offset 212, old: "'dark'\n         WHEN round(projected, 9) > envelope THEN 'projected_breach'\n       ", new: "'dark'\n         WHEN round(projected, 9) >= envelope THEN 'projected_breach'\n       "}
- {id: s-case-04, what: verdict comparison '>' read as '<' at CASE offset 212, old: "'dark'\n         WHEN round(projected, 9) > envelope THEN 'projected_breach'\n       ", new: "'dark'\n         WHEN round(projected, 9) < envelope THEN 'projected_breach'\n       "}
- {id: s-case-05, what: verdict comparison '>' read as '>=' at CASE offset 272, old: "ojected_breach'\n         WHEN today_rows > 0 AND (\n                (owner = 'shared", new: "ojected_breach'\n         WHEN today_rows >= 0 AND (\n                (owner = 'shared"}
- {id: s-case-06, what: verdict comparison '>' read as '<' at CASE offset 272, old: "ojected_breach'\n         WHEN today_rows > 0 AND (\n                (owner = 'shared", new: "ojected_breach'\n         WHEN today_rows < 0 AND (\n                (owner = 'shared"}
- {id: s-case-08, what: verdict comparison '>' read as '<' at CASE offset 357, old: "AND parts = 0)\n                OR (parts > 0 AND abs(round(attributed - today_value", new: "AND parts = 0)\n                OR (parts < 0 AND abs(round(attributed - today_value"}
- {id: s-case-09, what: verdict comparison '>' read as '>=' at CASE offset 405, old: ' abs(round(attributed - today_value, 9)) > round((SELECT tolerance FROM p) * today_', new: ' abs(round(attributed - today_value, 9)) >= round((SELECT tolerance FROM p) * today_'}
- {id: s-case-10, what: verdict comparison '>' read as '<' at CASE offset 405, old: ' abs(round(attributed - today_value, 9)) > round((SELECT tolerance FROM p) * today_', new: ' abs(round(attributed - today_value, 9)) < round((SELECT tolerance FROM p) * today_'}
- {id: s-case-11, what: verdict comparison '>' read as '>=' at CASE offset 528, old: "buted'\n         WHEN round(projected, 9) > round(warn_share * envelope, 9) THEN 'wa", new: "buted'\n         WHEN round(projected, 9) >= round(warn_share * envelope, 9) THEN 'wa"}
- {id: s-case-12, what: verdict comparison '>' read as '<' at CASE offset 528, old: "buted'\n         WHEN round(projected, 9) > round(warn_share * envelope, 9) THEN 'wa", new: "buted'\n         WHEN round(projected, 9) < round(warn_share * envelope, 9) THEN 'wa"}
- {id: s-case-13, what: verdict comparison '=' read as '<>' at CASE offset 137, old: "lope THEN 'breach'\n         WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'\n ", new: "lope THEN 'breach'\n         WHEN cadence <> 'daily' AND today_rows = 0 THEN 'dark'\n "}
- {id: s-case-14, what: verdict comparison '=' read as '<>' at CASE offset 162, old: "   WHEN cadence = 'daily' AND today_rows = 0 THEN 'dark'\n         WHEN round(projec", new: "   WHEN cadence = 'daily' AND today_rows <> 0 THEN 'dark'\n         WHEN round(projec"}
- {id: s-case-15, what: verdict comparison '=' read as '<>' at CASE offset 305, old: "ay_rows > 0 AND (\n                (owner = 'shared' AND parts = 0)\n                ", new: "ay_rows > 0 AND (\n                (owner <> 'shared' AND parts = 0)\n                "}
- {id: s-case-16, what: verdict comparison '=' read as '<>' at CASE offset 326, old: "             (owner = 'shared' AND parts = 0)\n                OR (parts > 0 AND abs", new: "             (owner = 'shared' AND parts <> 0)\n                OR (parts > 0 AND abs"}
- {id: s-window-day-month_start-p, what: month-to-date window excludes the first of the month, old: day >= (SELECT month_start FROM p), new: day > (SELECT month_start FROM p)}
- {id: s-window-day-today-p-window_days-p, what: rate window one day wider, old: day > (SELECT today FROM p) - (SELECT window_days FROM p), new: day >= (SELECT today FROM p) - (SELECT window_days FROM p)}
- {id: s-window-day-today-p-today_rows, what: today_rows counts the whole window, old: day = (SELECT today FROM p)) AS today_rows, new: day <= (SELECT today FROM p)) AS today_rows}
- {id: s-window-day-today-p-today_value, what: today_value reads the whole window, old: day = (SELECT today FROM p)) AS today_value, new: day <= (SELECT today FROM p)) AS today_value}
- {id: s-window-a-day-today-p, what: attribution read over the whole window, old: FROM a WHERE day = (SELECT today FROM p), new: FROM a WHERE day <= (SELECT today FROM p)}
```

```yaml
equivalent:
- {id: q01, what: 'parts > 0 read as parts >= 0 in the tolerance clause: when parts = 0 attributed is NULL, so the comparison is NULL and the branch cannot fire either way', old: "AND parts = 0)\n                OR (parts > 0 AND abs(round(attributed - today_value", new: "AND parts = 0)\n                OR (parts >= 0 AND abs(round(attributed - today_value"}
```

## 3. Settled / contested / risk / open

### Settled (fixture s1-s3)

- **s1.** Catalog egress is a first-class budget with four standing invariants and a measurement
  obligation (Decision 88 clauses 1 and 2; decision). Cost is derived at read from quantities, never stored
  as dollars (Decision 199; Decision 206 clause 7's "no dollars" budgets by analogy). The ledger is the
  customer's own usage and stays in the data plane (Decision 209 clause 2(a)); whether any verdict crosses
  is #1399's k1. Measured dollars never appear in the public repository (Decision 101; the reconciliation's
  public_summary rule).
- **s2.** Measured: 7 of 9 sibling reports hand cost or egress to this component; 1 of 9 names egress in
  its failure_signal or triggers; 2 of 9 carry a criterion naming egress; 1 of 9 names a budget of its own
  (a per-run filing cap) and 0 of 9 names a price (VP 1).
- **s3.** Measured: the repository's 5 cost triggers and 6 thresholds watch no egress, Lambda, catalog or
  review line; the telemetry leg of the monthly reconciliation returns None; the Decision 88 clause 2
  figure is still TBD; no Terraform budget or cost alarm exists and catalog_stats has no schedule (VP 2).

### Contested (k1-k3 in the fixture; k4-k6 report-only, the fixture's contested list is capped at 3)

- **k1 (asked). What a breach does.** (a) Alarm: the daily verdict files one recommendation per breaching
  line through the cost reconciliation's existing rec path (build_rec_fields, find_open_cost_rec_for), so
  the operator decides; nothing in the loop changes on its own. (b) Degrade: the owning component lowers
  its own cadence or window (a detector reads 7 days instead of 28; capture batches more turns per call)
  until the projection returns under the envelope. (c) Stop: the breaching line's schedule is disabled.
  Recommended (a) now and (b) at lift for lines with a single owner; (c) never unattended. (a) is the
  alarm-not-gate shape Decisions 55 and 62 and CD.28's reconciliation already use, and Decision 67's queue
  rule applies to the build (the design files nothing). (b) is a self-tuning loop and needs #1398's
  controller to know a component slowed itself (a cadence change is a version change under its k2). (c)
  stops the measurement with the spend, which is this item's own failure_signal. No Decision decides it;
  the reconciliation's rec path is precedent for the shape of (a), not for applying it to a daily,
  per-line verdict.
- **k2 (asked). Where the budget lives.** (a) A loop_budget block in config/agent/cost_reconciliation.yaml
  (register rows, envelopes, warn share, params), the file that already holds the thresholds and is
  "human-owned: edit when provider pricing or policy thresholds shift". (b) A new Class C contract,
  loop-budget.yaml, with the ledger and attribution tables as Class A entries. (c) This item's register
  rows only (section 2.2), until lift. Recommended (a) plus (c): the register is staged here and lands in
  (a) at build time; (b) is the right home once the ledger is a warehouse table, which is a build decision
  (T2.36 and the reader verbs own that boundary). (a) touches a config file a design slice may not edit.
- **k3 (asked). What unit the budget is kept in.** (a) Physical units per line, priced at read (staged).
  (b) Invoice dollars per line, read from the monthly snapshot. (c) Shares of the bill, as the five
  triggers use. Recommended (a), with (c) as the monthly leg: the daily verdict reads quantities, and the
  reconciliation's discrepancy leg compares the priced ledger with the invoice once a month (its
  invoice_vs_telemetry_discrepancy_pct is the right threshold, and its telemetry leg is the stub e5 names).
  (b) is a month late and cannot split a Lambda between components; (c) cannot see a cap. Consequence to
  weigh: (a) needs a price table per line, and Neon egress has none (O5), so that line stays in bytes until
  one exists.
- **k4 (asked; report-only). How catalog egress is measured.** (a) A proxy: catalog_stats bytes per read
  times reads per day, which the data plane can compute from its own metadata (Decision 88 clause 2's
  supported path) and which the model's "touched" and "whole_catalog" cases bracket. (b) The Neon
  consumption API, which reports the metered figure and needs a Neon API credential in the data plane (a
  new secret: always-ask by the charter if it is ever proposed; not proposed here). (c) The monthly Neon
  invoice, which is a month late. Recommended (a) now, calibrated once against (c) in the first measured
  month; (b) only if (a) and (c) disagree by more than the tolerance. Measurement, not precedent.
- **k5 (asked; report-only). How shared lines are attributed.** (a) Per-call stamps: every writer and reader
  call carries the calling component's id (the producer field Decision 199 already puts on every event; a
  `caller` tag on the Lambda log line), and attribution rows are summed from them. (b) Proportional: a
  shared line is split by each component's share of requests. (c) Unattributed by design for Lambda lines,
  attributed only for the lines with one owner. Recommended (a): it is what the verdict's tolerance rule
  assumes (v10-v12) and it costs one field per call; (b) hides a component whose calls are few and heavy
  (the detectors, e8); (c) leaves the two biggest lines unowned. No precedent.
- **k6 (asked; report-only). The fixture item's edge home.** (a) depends_on T2.36 only (carried
  provisionally): the ledger is a telemetry-side table and the reconciliation's telemetry leg is stubbed
  "until T2.36 lands". (b) part_of T2.52, whose exit criterion already says aggregate verbs "honour the
  Decision 88 Neon egress budget". (c) depends_on the reader verbs and capture items, which the evaluator's
  L4 refuses while they are unmerged. Recommended (a) until W2 places the loop's items together.

### Risks

- **R1 Budget Goodhart.** The cheapest ways to make every line read ok are to raise the envelope and to
  stop measuring. The first is a register change the operator approves with the prior month's residual
  beside it (c3) and every envelope is versioned with the params; the second is this item's own
  failure_signal (dark_line_days), so a silent meter reads as a failure, not as savings (#1400's register
  would carry this row).
- **R2 Shared Lambdas blur attribution.** One writer and one reader serve ten components; without per-call
  stamps (k5) the two largest priced lines are a single number nobody owns.
- **R3 The public boundary.** Quantities and envelopes are public; measured dollars and invoice figures are
  not (Decision 101; public_summary). The ledger's priced read must stay in the private sink the
  reconciliation already uses.
- **R4 Late and lumpy invoices.** The monthly leg (k3 (c)) sees a cap breach weeks after the daily verdict
  does; a daily verdict without a calibrated proxy (k4) can be wrong in either direction for a month.
- **R5 The egress proxy.** touched and whole_catalog differ by 17x at 5 sessions a day (e8). Until
  catalog_stats is run against the live catalog (q1) the envelope for the one line that matters most is a
  guess, and the GC gate (Decision 88 clause 4) decides which model the deployment is in.
- **R6 Price drift.** A list price is an external fact (the roadmap's own rate_basis is "fetched
  2026-08-01"); pricing at read means a stale table misprices every day at once. The reconciliation's
  DeepSeek price trigger is the pattern for re-reading prices; this register would need the same for
  Lambda and S3.

### Open questions (q1-q3 in the fixture)

- **q1.** No measured egress exists. Who runs catalog_stats against the live catalog (Decision 88 clause
  2, never scheduled, e6), and are the seed envelopes set from that reading or from the model here? Until
  then every envelope in section 2.2 is a seed.
- **q2.** On the free tier (local adapter, no cloud account, Decision 184 clause 2) there is no Lambda, no
  Neon and no bill. Which lines exist there (review_items, loop_llm_tokens, local bytes?), and does a
  budget in bytes and seconds mean anything with no price to apply at read?
- **q3.** The review line is over at every scale (2,160 a month against 900). Is operator review a budget
  line here, or the ladder's own control (#1398 R1: afi times output volume is the number of human
  reviews a day), with this register only reading it?

### Named for owners, not filed (Decision 67)

- **O1** scripts/cost_reconciliation.py names the telemetry cost column est_cost_usd (e5), while the
  contracts that name a cost column name cost_usd; whichever lands with T2.36, the stub and the contract
  should agree (cost reconciliation owner).
- **O2** The roadmap's ducklake_catalog_neon line still reads "$0 (Neon serverless Postgres free tier ...)"
  while Decision 88 records the forced paid-plan upgrade of 2026-06-15 (roadmap cost_projection owner; a
  staged roadmap edit, Decisions 79 and 125, not made here).
- **O3** catalog_stats, Decision 88 clause 2's measurement path, has never been scheduled, and the clause 2
  figure is still TBD in the roadmap (e3, e6; maintenance owner).
- **O4** The monthly reconciliation's telemetry leg is a stub with no owning line (e5); the ledger staged
  here is a candidate source for it (cost reconciliation owner; T2.36).
- **O5** No Neon egress unit price exists in the repository, so the one line Decision 88 ranks beside
  compute and storage cannot be priced at read (cost reconciliation owner).

## 4. Consideration register (as authored in the fixture)

- why: nothing budgets the loop: the roadmap cost block is "not a budget", its 5 triggers watch no egress,
  Lambda or review line, the telemetry cost leg returns None, Decision 88 clause 2 is TBD (VP 2); 7 of 9
  siblings hand cost here (VP 1).
- how: one register row per cost line (unit, owner, cadence, envelope, warn share, source), one ledger row
  per line per day plus attribution rows per component, and one daily SQL returning one of seven verdicts
  per line; dollars derived at read.
- planes: data_plane.
- maturity (thresholds are provisional seeds; plan fork line): read_all, the operator re-derives every
  verdict run; to sampled after 30 runs re-derived unchanged since the last overturned one; to spot_check
  after 30 more on a 1-in-5 sample; to anomaly_triggered after 30 consecutive days with no dark or
  unattributed line and the last monthly invoice residual inside tolerance. The return leg and version rule
  are #1398's k1 and k2.
- failure_signal: loop spend or egress nobody reads: a daily cost line with no ledger row, a day with no
  component attribution, or an invoice the ledger cannot explain. Metric dark_line_days: daily lines with
  no ledger row that day; must be 0, read beside the monthly invoice-vs-ledger residual. Source: the daily
  verdict log (dark and unattributed rows) and the monthly cost reconciliation discrepancy leg.
- verification: c1 vectors, c2 ledger coverage over a month of runs, c3 operator review of the register
  with the prior month's residual.
- rollback: stop the daily verdict schedule and drop the loop_budget block; monthly cost reconciliation
  runs as before with its five triggers. Ledger and attribution rows stay as history; no envelope gates
  anything, so stopping unblocks nothing.

## 5. Boundary notes for W2 synthesis

- **Capture (#1384).** Its wire size per turn and its batching choice (k2 there) set writer_requests,
  writer_bytes and the file count every other line pays for. Its SessionEnd catch-up (3.2 MB plus 2.1 MB
  per 100 turns) is the one write shape with a burst; the ledger reads it as a day's value, not a spike.
- **Reader verbs (#1390).** Its q1 (per-call catalog egress, unmeasured) is this register's
  catalog_egress_bytes source under k4 (a); its c3 ("per-call catalog egress measured before any consumer
  depends on a verb") is the first ledger row this component would ever read. Its 7-day cap on
  sessions_window is the only per-call egress bound in W1.
- **Friction (#1394) and deliberation (#1395).** Both read narrow typed columns today; each names the
  option that would move its read onto transcript content (k3 (b) in both). That option changes
  catalog_egress_bytes and, for #1394, opens loop_llm_tokens; its envelope of 0 is the switch the operator
  flips, not a gate.
- **Rec filing (#1396) and back-validation (#1397).** #1397's one-call-per-candidate rule and #1396's
  file_budget of 3 per run are the detector-side egress levers; at 5 sessions a day the detectors are 83%
  of touched egress.
- **Maturity ladder (#1398).** review_items is its cost and its control knob at once (q3). If W2 makes the
  ladder the owner of review load, this register reads the line and the ladder sets the envelope.
  Contradiction for W2: the ladder's read_all rung is defined by review count, this register's by a verdict
  being re-derived; one of them owns "how many reviews a day the operator will do".
- **Allow-list transport (#1399).** plane_egress_bytes reads its audit row (each batch logged before
  sending) under transport (a); under (b) the control plane pays and the line belongs to the control
  plane's own budget, outside this fixture. Its k1 decides whether any verdict here may cross.
- **Goodhart register (#1400).** dark_line_days is this item's failure_signal and belongs in that register
  with a counter (the monthly residual) and a drill (a day withheld from one line should read dark).
  Drills and the reviewer drill are review_items and reader_requests here.
- **Maintenance and GC.** Merge cadence and snapshot expiry decide the file count every catalog read pays
  for (section 2.3); Decision 88 clause 4's GC gate (rec-2113's restore drill) is therefore a cost
  dependency of the loop, and the maintenance Lambda is a reader of the same catalog. W2 should place
  T2.19 and T2.26 beside the loop's items.
- **Monthly reconciliation (CD.28).** This register is its daily, per-line front end and its telemetry
  leg's source (k3 (c), O4); it is not a second reconciliation. k2 (a) puts the register in the same file.

## 6. Staged candidate decision text (for W3; not filed)

This text presumes the recommended options of parked forks k1, k2 and k3. It is not settled.

> "Every meter the telemetry feedback loop turns is a budget line with an owner. A line is kept in the
> unit its meter counts (bytes, requests, GB-seconds, tokens, review items), never in dollars; dollars
> are derived when read, from a versioned price table, and never stored or published. Each line has a
> cadence, a monthly envelope and a warn share, and a shared line's daily value is attributed to the
> components that caused it within a stated tolerance. A daily deterministic verdict reads the register,
> the ledger and the attribution and reports ok, warn, projected_breach, breach, dark, unattributed or
> unregistered per line; a breach files a recommendation through the cost reconciliation path and gates
> nothing. A line that reports nothing on a day it should is a failure of the loop, not a saving. The
> register lives beside the monthly reconciliation's thresholds, and the monthly discrepancy leg
> reconciles the priced ledger against the invoice. Decision 88's catalog egress line is the first line of
> the register, and its envelope is set from a measured reading, never a planning-time guess."
