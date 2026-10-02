# REPORT: W1 component 1 - capture producer wiring (record_turn -> writer, rec-4026 slice 3b)

REPORT-ONLY (Decision 86 cl.2). Planning artefact: `docs/plans/PLAN-w1-capture-producer-wiring.yaml`.
Fixture rows: `pwi-capture-producer-wiring` in `docs/work-item-pilot/telemetry-feedback-loop.yaml`
(CD.45 pilot, provisional_v0). Nothing is built, filed, closed, flipped or ratified here.

## 0. Verdict

- The component is real and correctly seeded, but NARROWER than "record_turn -> writer": the writer
  half does not exist yet. It is the producer-side runner only (hooks, pass orchestration, cursor
  persistence, chunked transport client). The writer verb, telemetry tables and project registration
  stay with T2.36 / rec-4024 and enter the fixture as a `depends_on: T2.36` edge, not as a pilot item.
- The component is BLOCKED on T2.36 (writer verb unbuilt, VP 2) and gated by three pre-write
  obligations it does not own: T2.36 c5 (GC guard before the first telemetry write), rec-4101 (orphan
  monitor before production rows, PLAN-telemetry-contract-risk-amendments.yaml:352-355) and T3.20 c8
  (smoke-first).
- One item fits the clause-3 grain (kind task; three criteria; two edges). Splitting it would spend
  the 12-item cap on rows that share one failure signal.

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | record_turn is pure: "No file writes, no network, no writer call"; the caller persists next_cursor | src/turn_capture/record_turn.py:6-7 |
| e2 | No caller exists: zero record_turn references under .claude/, scripts/, src/lambdas/; no Stop, SubagentStop or SessionEnd hook is configured [VP 1] | .claude/settings.json |
| e3 | The writer has 17 actions, none telemetry; the transport sends ONE record per call [VP 2] | src/lambdas/ducklake_writer/handler.py:241; scripts/ops_portal/writer_transport.py:127 |
| e4 | append_events (kernel) exists but defers OCC retry, row caps, project_ref/tenant resolution to rec-4024 | src/telemetry/append.py:14-15 |
| e5 | Handed-on list for 3b: Stop, SessionStart catch-up, SessionEnd hooks; cursor persistence and lost-cursor runbook; writer-verb writes; project_ref registration; gate/precommit signatures; attachment system transcripts; smoke writes behind T3.20 c8 | docs/plans/PLAN-telemetry-turn-capture-core.yaml:640-642 |
| e6 | A Stop hook exiting 2 continues the turn, so the live session's latest turn lags one turn until the next prompt or session_final | docs/plans/PLAN-telemetry-turn-capture-core.yaml:629-631 |
| e7 | project_ref is PINNED once at the root's first record; never a re-read of repository config; a producer without it DEFERS | docs/contracts/project-id.yaml:47-51 |
| e8 | rec-4026 owes exact-ms session_started_at and root project_ref handoff, persists project_ref with the cursor, and should not write production rows before rec-4101's monitor | docs/plans/PLAN-telemetry-contract-risk-amendments.yaml:352-355 |
| e9 | Identical re-send under an existing grain key is a no-op; differing content is rejected loudly | Decision 207 (docs/DECISIONS.md:207) |
| e10 | Transcript content over 65,536 bytes spills to the blob port (writer's job) | docs/contracts/telemetry_transcripts.yaml:172 |

Measured (synthetic trees, no real transcript read; VP 3 reproduces the warm leg):

| turns | lines | bytes | cold pass s | warm pass s (one new turn) | rows cold | rows warm |
|---|---|---|---|---|---|---|
| 25 | 550 | 1.3 MB | 0.09 | 0.17 | 1321 | 55 |
| 100 | 2200 | 5.0 MB | 0.37 | 0.69 | 5446 | 55 |
| 400 | 8800 | 20.0 MB | 1.67 | 3.41 | 21946 | 55 |
| 1000 | 22000 | 49.8 MB | 3.84 | 8.80 | 54946 | 55 |

Each turn is a prompt, 10 Bash tool calls with 2 KB results, and a final text block. A warm pass costs
about 0.4 ms per line of the WHOLE tree to emit one turn's 55 rows: it parses the full tree and the
cursor-truncated tree (record_turn.py:96-102). Wire size (render_rows_json) is about 52 KB per such
turn; a 100-turn cold catch-up is 3.2 MB of transcript rows plus 2.1 MB of observations, so batches
must be byte-chunked under the writer's request limit (AWS documents 6 MB for a synchronous Function
URL request; external, not re-verified here).

## 2. Runner shape (the design this item stages)

1. Trigger: Stop (every completed response), SessionStart (catch-up for trees whose cursor lags their
   file) and SessionEnd (session_final=True). SubagentStop is not needed: a child's rows are emitted by
   the root pass once the parent holds its completion.
2. One pass per root tree under an exclusive per-tree lock; a second concurrent pass exits 0
   immediately (the next Stop catches up). The cursor write is monotonic (never replaces a later
   lines_consumed with an earlier one).
3. Send order: observations, transcripts, agents, then the single sessions batch (record_turn.py
   CaptureResult.batches), each table byte-chunked; a chunk failure stops the pass.
4. Persist next_cursor only after every chunk is acknowledged. A failed pass leaves the cursor where it
   was; the next pass recomputes the same rows from the transcript and re-sends them, and Decision 207
   makes the overlap a no-op. The transcript is the replay source, so no outbox exists (Decision 84
   I-4 holds).
5. Exit codes: 0 on success or lock contention; 1 (non-blocking, stderr names the table, chunk and
   status) on any failure. NEVER 2: on Stop, exit 2 forces the turn to continue (e6).
6. Pins: project_ref and billing_shape are passed in from the runner's configuration ONCE, at the
   pass that creates the cursor, and travel in the cursor (record_turn checks them via check_pins).

## 3. Settled / contested / open

Settled (consistent with a Decision, a contract or the 3a plan; mirrored as s1-s3 in the fixture):

- s1 Boundary: producer side only. Writer verb, tables, project registration = T2.36 / rec-4024 (e3,
  e4). The gate/precommit signatures on the handed-on list (e5) belong to the read-side friction
  classifier over tool_result rows (rec-4032), which keeps the producer transcript-pure; this report
  recommends that reading and moves nothing.
- s2 Data plane only (Decision 209 cl.2a: agent transcripts never leave the data plane). The hook
  writes to the operator-owned writer; the allow-list transport (rec-4141) never carries these rows.
- s3 Failure semantics: cursor-after-ack plus transcript replay plus Decision 207 no-op re-send (e1, e9;
  runner steps 2-5). Loud failure = non-zero non-2 exit with the cursor unadvanced.

Contested (evidence on both sides; k1-k3 in the fixture):

- k1 Synchronous Stop hook vs detached pass. For: loud, attributable failure in the session (D84 I-4
  spirit). Against: per-pass cost grows linearly with the session (8.8 s warm at 22k lines, measured)
  and is paid on EVERY response. Options: (a) sync with a wall-clock budget, deferring to the next
  pass when exceeded; (b) detached pass whose failure is surfaced by the next pass; (c) make the warm
  pass O(new lines) by caching the prior emission set beside the cursor, which re-opens the 3a
  "positions only" cursor rule. Recommended: (a); (c) only if the budget is breached in practice.
- k2 Cursor home. A local file is lost when a CC-web container is reclaimed. Losing it is safe for
  rows (full re-send, all no-ops) but not for the pin: re-reading project_ref from repository config
  after loss is exactly what project-id.yaml:47-51 forbids. Options: (a) accept config re-read for the
  root producer only and amend the contract (operator, always-ask); (b) make the pin a transcript
  fact by having the SessionStart hook emit it as additional context, which Claude Code writes into the
  transcript, so a lost cursor re-derives it from the tree (needs a parser rule and a PARSER_VERSION
  bump); (c) defer emission for cursor-less trees. Recommended: (b), pending q2.
- k3 Final-turn loss. Emission is per CLOSED turn (e6); a session whose container is reclaimed without
  SessionEnd never closes its last turn. This is the dominant expected loss on CC-web. The
  failure_signal below is chosen to see it.

Open (q1-q3 in the fixture; none is answerable from the repository):

- q1 Are Stop hook runs written into the transcript as hook attachments (they become process_event
  rows named hook:<runner stem>)? The failure_signal metric counts them; if not, the metric must use
  the runner's own diagnostics instead.
- q2 Does SessionEnd fire on CC-web reclaim, and is a resumed session's transcript restored whole (so
  catch-up sees the prefix)?
- q3 billing_shape for API-key sessions (rec-4147): the default fixed_non_rollover_allowance mislabels
  unattended API-key runs (Decision 205) as subscription spend.

## 4. Consideration register (as authored in the fixture)

- planes: data_plane.
- failure_signal: turn_coverage_gap, the share of root sessions whose capture-hook process_events
  exceed their turn_close rows by more than 1 (the inherent one-turn lag). Source: telemetry_observations
  through the rec-4024 reader verbs. It sees k3 (lost final turns) and failed passes alike, from the
  warehouse alone.
- maturity: starts at read_all (every captured session reconciled by the conformance walk,
  tests/turn_capture/test_real_transcript_conformance.py). read_all -> sampled at >= 20 consecutive
  clean sessions; sampled -> spot_check at 0 violations across the last 30 sampled; spot_check ->
  anomaly_triggered at >= 30 days without a turn_coverage_gap breach. The numbers are seed values for
  the maturity-ladder controller component to challenge.
- verification: c1 (hooks, ordering, chunking, cursor-after-ack, never exit 2), c2 (failed/killed
  pass and lost cursor replay as no-ops or defer), c3 (T3.20 c8 smoke plus a rec-4101 monitor run,
  review method). All open.
- rollback: remove the hook entries; rows stay (append-only); cursors hold positions only.
- edges: part_of T3.20; depends_on T2.36.

## 5. Boundary notes for W2 synthesis

- Deliberation capture (DeepSeek reasoning_content) is a transcript-less producer: it must RECEIVE the
  root's project_ref and session_started_at (epoch-ms or a decoded held key, telemetry-event-envelope.yaml
  session_started_at handoff rule). This item is that handoff's source; the deliberation item should
  carry `depends_on: pwi-capture-producer-wiring`.
- Reader verbs (rec-4024 item 6) are this item's failure_signal source; back-validation (T3.4) and the
  friction classifier both read only rows this item writes.
- No seed component owns the WRITER verb. It is already tracked (T2.36 c1/c2, rec-4024 slice 2), so
  the pilot should point at it by edge rather than add an item.

## 6. Not done here (and why)

- No hook, runner, test or writer code: REPORT-ONLY by brief.
- No rec filed, updated or closed (Decision 67; the brief's never-list). rec-4026 stays open; the note
  this report would add to it is the operator's call.
- No T3.20 or T2.36 criterion text or status change.
