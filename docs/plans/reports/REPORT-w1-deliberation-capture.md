# REPORT: W1 component 4 - deliberation capture (reasoning visibility, tokens and text; read-time metrics)

REPORT-ONLY (Decision 86 cl.2). Planning artefact: `docs/plans/PLAN-w1-deliberation-capture.yaml`.
Fixture rows: `pwi-deliberation-capture` in `docs/work-item-pilot/telemetry-feedback-loop.yaml`
(CD.45 pilot, provisional_v0). Nothing is built, filed, closed, flipped or ratified here.

## 0. Verdict

- The producer half of this component is already decided, and this item builds on it rather than
  re-deciding it. rec-4028's context records the operator's 2026-09-29 choice ("2a-1 + rec-4028"):
  telemetry_observations gains `reasoning_visibility` (full | summarized | omitted | redacted | none)
  and `reasoning_tokens` (<= tokens_output; zero or NULL when visibility is none) on model_call rows;
  the "2a-1 plan" moves the claude_code producer's mapping to parser_version 2; rec-4028 owns the
  LiteLLM mapping (DeepSeek `reasoning_content` -> full, thinking from the RESPONSE only, never from
  request messages). What no artefact holds is the read side: which metrics derive from those facts,
  and how a silent capture loss would be seen.
- The 2a-1 plan is not in this repository (VP 2): no contract field, no `docs/plans` file, no remote
  branch and none of the last 100 PRs names `reasoning_visibility`, and rec-4028's evidence file
  (`/mnt/project-files/telemetry-reasoning/`) is not in this project's shared folder. Until it lands,
  the live producer stores Claude thinking tokens only under an undocumented metadata key (VP 1, VP 2).
  Where 2a-1 lives is q1, for the operator.
- On Claude Code the deliberation TEXT is not available by default; the token COUNT is. In this
  session's own transcript every thinking block (54 model_calls with thinking tokens) is empty and
  signed, so the producer writes zero thinking rows while 64% of output tokens were thinking (section 1).
  That matches the primary docs: `display` defaults to "omitted" on current models, and "No display
  setting returns the raw chain of thought". Text exists only on the LiteLLM lane (DeepSeek thinking
  mode, on by default), which T4.2 has not built. Whether to opt Claude Code into summaries is k1.
- Capture can fail silently in ways no single row shows: a display default that changes per model
  generation, LiteLLM's message logging switched off, a stream cut mid-flight, a mapping bug. The stored
  `reasoning_visibility` says what the producer saw; the thinking rows say what it stored. Their
  disagreement is this item's failure signal. It is a cross-table rule, so Decision 210 cl.2 makes it a
  DQ monitor plus the read verb, never a write check; the row-local invariants go to the writer
  (cl.1). One SQL statement passes 12 of 12 vectors (VP 4).
- One item fits the clause-3 grain (kind task; three criteria; part_of T3.20, depends_on T2.36 and
  T4.2). The verb and the monitor share one failure mode and one SQL, so a split would spend the cap
  on rows with one failure signal.

## 1. Evidence (each row re-derivable; VP step in brackets)

| id | fact | anchor |
|---|---|---|
| e1 | Operator choice 2026-09-29: reasoning_visibility and reasoning_tokens on telemetry_observations (2a-1), claude_code mapping at parser_version 2 (2a-1), LiteLLM mapping and response-only capture (rec-4028); rec-4028 status open | rec-4028 context, 2026-09-29 entries (rec_by_id) |
| e2 | The claude_code producer reads `usage.output_tokens_details.thinking_tokens` into model_call `metadata`; no typed column holds it [VP 1] | src/turn_capture/observations.py:243-269 |
| e3 | A thinking block becomes a purpose=thinking row owned by the model_call only when its text is non-empty; a `redacted_thinking` block is a diagnostic only [VP 1] | src/turn_capture/transcripts.py:190-210 |
| e4 | The contract has four token columns and no reasoning field; the MODEL_CALL metadata list (purpose_detail, prompt_hash, error) does not name thinking_tokens [VP 2] | docs/contracts/telemetry_observations.yaml:222-265, :408 |
| e5 | `provider` is never set by the claude_code producer, and its vocabulary is the retired copilot set (rec-4135 tracks the vocabulary) [VP 1, VP 2] | docs/contracts/telemetry_observations.yaml:307; src/turn_capture/observations.py:56 |
| e6 | Tier 1 still names `deepseek/deepseek-chat` and `deepseek/deepseek-reasoner` [VP 2] | docs/contracts/inference-provider.yaml:355 |
| e7 | thinking is an accepted transcript purpose, owned by the model_call [VP 2] | docs/contracts/telemetry_transcripts.yaml:85, :131 |
| e8 | R5(c) collapses one model_call seen by two producers to claude_code's row; transcript rows are not collapsed; R8: a non-replayable producer emits no open marker | docs/contracts/telemetry-event-envelope.yaml:344-347, :359 |
| e9 | A transcript-less producer (LiteLLM) receives session_started_at from another producer of the tree, else defers | docs/contracts/telemetry-event-envelope.yaml:115-121 |
| e10 | Decision 209 cl.2(a): agent transcripts never leave the data plane; (b) only an allow-list crosses | docs/DECISIONS.md:75 |
| e11 | Decision 210 cl.1 row-local rules at the writer; cl.2 cross-row rules the write cannot decide are DQ monitors, alarm-not-gate | docs/DECISIONS.md:22-23 |
| e12 | T3.20 c3: an orphan/coverage DQ check for the turn-observation to transcript join, alarm-not-gate | docs/ROADMAP-PLATFORM.yaml T3.20 c3 |

External facts, checked against primary docs on 2026-10-03 (not VP steps; they can change):

- DeepSeek, Thinking Mode guide (api-docs.deepseek.com/guides/thinking_mode): "Thinking mode is enabled
  by default, with the default effort being high"; the chain of thought "is returned via the
  reasoning_content parameter, at the same level as content"; "for requests carrying the tools
  parameter, the reasoning_content must be fully passed back to the API in all subsequent requests ...
  If your code does not correctly pass back reasoning_content, the API will return a 400 error";
  without tools it "will be ignored".
- DeepSeek, Create Chat Completion reference: `usage.completion_tokens_details.reasoning_tokens`,
  "Tokens generated by the model for reasoning", a breakdown of completion tokens (so reasoning_tokens
  <= completion tokens holds).
- DeepSeek, V4 release note (2026-04-24) and Models page: "deepseek-chat & deepseek-reasoner will be fully
  retired and inaccessible after Jul 24th, 2026, 15:59 (UTC Time)"; the model name is now
  `deepseek-flash` (legacy `deepseek-v4-flash` still accepted) or `deepseek-v4-pro`. e6 is stale.
- Anthropic, Thinking overview (platform.claude.com/docs/en/build-with-claude/thinking): on Opus 5.5,
  Opus 5, Sonnet 5.5, Sonnet 5 and the Fable models "`display` defaults to `"omitted"`"; omitted
  blocks have "an empty `thinking` field" and a signature; summarized text "is a summary of Claude's
  full thinking process rather than the raw chain of thought", produced "by a different model";
  "No display setting returns the raw chain of thought"; you are "charged for the full thinking tokens".
- Anthropic, Extended thinking: `usage.output_tokens_details.thinking_tokens` "reports how many of the
  billed output tokens were internal reasoning" (so reasoning_tokens <= tokens_output holds).
- Claude Code, Model configuration (code.claude.com/docs/en/model-config): "Interactive sessions on the
  Anthropic API receive redacted thinking blocks by default, so set `showThinkingSummaries: true` in
  settings if you want the full summaries"; thinking cannot be turned off on Opus 5.5, Sonnet 5.5 or
  the Fable models. The docs say "redacted", but the stored blocks are type `thinking` with empty text
  (the API's omitted shape), not `redacted_thinking` (section 1). A mapping must key on block shape.

Measured (local only; no production catalog read, no provider call):

- This session's own CC-web transcript run through record_turn locally (counts only, not
  reproducible from the repository, at the time of measurement): 83 model_calls, 54 with
  thinking_tokens > 0, 39,396 of 62,008 output tokens thinking (64%), 0 purpose=thinking rows. Every
  thinking block in the transcript was empty and signed, and every model_call with a thinking block
  had thinking_tokens > 0 while every one without had 0. Under rec-4028's rule all 54 read omitted and
  the rest none.
- LiteLLM 1.102.1 against a mocked transport (VP 3; nothing leaves the process): a DeepSeek response's
  `reasoning_content` surfaces on the message and `reasoning_tokens` on usage. Re-sending the returned
  message echoes the reasoning back. A rebuilt history WITHOUT it gets a single-space placeholder when
  thinking is passed explicitly (a warning only), and nothing at all when thinking is left to
  DeepSeek's default, because LiteLLM's fill runs only for an explicit `thinking: enabled`. Per the
  DeepSeek guide the second case is a 400 on a tools request and the first silently blanks the chain.
  `supports_reasoning` is False for `deepseek-chat` and True for `deepseek-flash` in this version's
  bundled model map.
- The SQL in section 2 passes 12 of 12 vectors on DuckDB 1.5.4 (VP 4). Six mutants were run once by hand
  and each is caught: counting thinking rows instead of their existence (11/12), counting any transcript
  purpose (11/12), treating redacted as text-bearing (11/12), summing output tokens of calls with no
  reported count (10/12), an inner join (5/12), dropping the unclassified arm (11/12).

## 2. Design (what this item stages)

Inputs, both after the shared R4/R5 dedupe the reader-verbs item stages (W1-2, its report section 2), so
partition binding, generation retirement and the model_call collapse are inherited, not restated:
`{calls}` is one session's model_call rows (observation_id, producer, model, tokens_output,
reasoning_tokens, reasoning_visibility, as 2a-1 lands them); `{thinking}` is the same session's
transcript rows, projected to observation_id and purpose only. The verb never selects `content` or
`content_uri`. Text-bearing visibilities are full and summarized; omitted, redacted and none hold none.

```sql
WITH t AS (
  SELECT DISTINCT observation_id FROM {thinking} WHERE purpose = 'thinking'
),
c AS (
  SELECT m.*, t.observation_id IS NOT NULL AS has_text,
         CASE
           WHEN m.reasoning_visibility IS NULL THEN 'unclassified'
           WHEN m.reasoning_visibility IN ('full', 'summarized') AND t.observation_id IS NULL THEN 'text_missing'
           WHEN m.reasoning_visibility NOT IN ('full', 'summarized') AND t.observation_id IS NOT NULL THEN 'text_unexpected'
         END AS drift
  FROM {calls} m LEFT JOIN t USING (observation_id)
)
SELECT producer, model, reasoning_visibility,
       count(*) AS calls,
       count(*) FILTER (WHERE reasoning_tokens > 0) AS reasoning_calls,
       coalesce(sum(reasoning_tokens), 0) AS reasoning_tokens,
       coalesce(sum(tokens_output) FILTER (WHERE reasoning_tokens IS NOT NULL), 0) AS counted_output_tokens,
       count(*) FILTER (WHERE has_text) AS text_calls,
       count(*) FILTER (WHERE drift = 'unclassified') AS unclassified,
       count(*) FILTER (WHERE drift = 'text_missing') AS text_missing,
       count(*) FILTER (WHERE drift = 'text_unexpected') AS text_unexpected
FROM c GROUP BY producer, model, reasoning_visibility
```

Response (Decision 88; Decision 209 cl.2a): the rows above, the drift counts, and the producer
parser_versions read; never text. The deliberation share is a consumer's division,
`reasoning_tokens / counted_output_tokens`, over calls whose count was reported (a NULL count is
never estimated; rec-4028 forbids LiteLLM's local token counter). deliberation_drift_share is
`(unclassified + text_missing + text_unexpected) / calls`.

Writer-side, not here (Decision 210 cl.1, rec-4024 slice 2a): reasoning_visibility in its accepted set,
reasoning_tokens <= tokens_output, and reasoning_tokens zero or NULL when visibility is none. Those are
row-local, so a violating row is rejected at write and the read never re-checks them.

Vectors (hand-written for this report; VP 4 runs every one). `calls` rows are `[observation_id,
producer, model, tokens_output, reasoning_tokens, reasoning_visibility]`, `thinking` rows are
`[observation_id, purpose]`, and `expected` rows follow the SELECT column order:

```yaml
vectors:
  - id: v01-omitted-claude-code-counts-only
    calls: [[m1, claude_code, claude-opus-5-5, 371, 52, omitted], [m2, claude_code, claude-opus-5-5, 112, 0, none]]
    thinking: []
    expected: [[claude_code, claude-opus-5-5, omitted, 1, 1, 52, 371, 0, 0, 0, 0], [claude_code, claude-opus-5-5, none, 1, 0, 0, 112, 0, 0, 0, 0]]
  - id: v02-summarized-with-text
    calls: [[m1, claude_code, claude-opus-4-6, 300, 120, summarized]]
    thinking: [[m1, thinking]]
    expected: [[claude_code, claude-opus-4-6, summarized, 1, 1, 120, 300, 1, 0, 0, 0]]
  - id: v03-deepseek-full-with-text
    calls: [[d1, litellm, deepseek-flash, 40, 31, full]]
    thinking: [[d1, thinking]]
    expected: [[litellm, deepseek-flash, full, 1, 1, 31, 40, 1, 0, 0, 0]]
  - id: v04-full-text-lost
    calls: [[d1, litellm, deepseek-flash, 40, 31, full]]
    thinking: []
    expected: [[litellm, deepseek-flash, full, 1, 1, 31, 40, 0, 0, 1, 0]]
  - id: v05-two-thinking-rows-count-once
    calls: [[d1, litellm, deepseek-flash, 40, 31, full]]
    thinking: [[d1, thinking], [d1, thinking]]
    expected: [[litellm, deepseek-flash, full, 1, 1, 31, 40, 1, 0, 0, 0]]
  - id: v06-omitted-but-text-stored
    calls: [[m1, claude_code, claude-opus-5-5, 371, 52, omitted]]
    thinking: [[m1, thinking]]
    expected: [[claude_code, claude-opus-5-5, omitted, 1, 1, 52, 371, 1, 0, 0, 1]]
  - id: v07-unclassified-legacy-row
    calls: [[m1, claude_code, claude-opus-5-5, 371, null, null]]
    thinking: []
    expected: [[claude_code, claude-opus-5-5, null, 1, 0, 0, 0, 0, 1, 0, 0]]
  - id: v08-response-row-is-not-thinking
    calls: [[m1, claude_code, claude-opus-4-6, 300, 120, summarized]]
    thinking: [[m1, response]]
    expected: [[claude_code, claude-opus-4-6, summarized, 1, 1, 120, 300, 0, 0, 1, 0]]
  - id: v09-orphan-thinking-row-ignored
    calls: [[m1, claude_code, claude-opus-5-5, 112, 0, none]]
    thinking: [[zz, thinking]]
    expected: [[claude_code, claude-opus-5-5, none, 1, 0, 0, 112, 0, 0, 0, 0]]
  - id: v10-deepseek-thinking-disabled
    calls: [[d1, litellm, deepseek-flash, 25, 0, none]]
    thinking: []
    expected: [[litellm, deepseek-flash, none, 1, 0, 0, 25, 0, 0, 0, 0]]
  - id: v11-redacted-holds-no-text
    calls: [[m1, litellm, claude-sonnet-5, 200, 64, redacted]]
    thinking: []
    expected: [[litellm, claude-sonnet-5, redacted, 1, 1, 64, 200, 0, 0, 0, 0]]
  - id: v12-full-with-unreported-count
    calls: [[d1, litellm, deepseek-flash, 40, null, full], [d2, litellm, deepseek-flash, 50, 20, full]]
    thinking: [[d1, thinking], [d2, thinking]]
    expected: [[litellm, deepseek-flash, full, 2, 1, 20, 50, 2, 0, 0, 0]]
```

## 3. Settled / contested / risk / open

Settled (consistent with a Decision, a contract, an operator choice or measured; s1-s3 in the fixture):

- s1 The producer facts are decided (e1): reasoning_visibility and reasoning_tokens on model_call, the
  claude_code mapping in 2a-1, the LiteLLM mapping in rec-4028. This item checks them against the
  primary docs and the measurement above and finds them consistent: both providers report reasoning
  tokens as a subset of output tokens, Claude Code's empty signed blocks read omitted, and capture from
  the response only avoids LiteLLM's placeholder (VP 3).
- s2 Data plane only. Thinking text is agent transcript (Decision 209 cl.2a). The verb reads visibility,
  counts and transcript purpose, never content, so only derived counts are candidates for rec-4141's
  allow-list; the visibility vocabulary and the counts are a closed set, the model ids are not.
- s3 The drift rule is cross-table (a model_call row and its thinking rows travel in different batches,
  W1-1 runner step 3), so Decision 210 cl.2 makes it a DQ monitor, alarm-not-gate, with T3.20 c3's
  observation-to-transcript join check as its home; the verb runs the same SQL. 12/12 vectors (VP 4).

Contested (evidence on both sides, options listed; k1-k3 in the fixture; parked for the operator):

- k1 Claude thinking text. Claude Code stores empty signed blocks by default, so deliberation text never
  reaches telemetry from the only live producer. Options: (a) counts only, no settings change; (b) set
  `showThinkingSummaries: true` in `.claude/settings.json` for every session; (c) set it only for
  sessions an RCA will read. For (b)/(c): the summary costs no extra billed tokens (thinking is billed
  in full either way) and is the only Claude text there is. Against: it is a summary written by a
  different model, so it says what a summarizer saw, not how the agent reasoned; it adds content rows
  and blob reads; and it changes every session's request. Untested here: whether the setting reaches
  CC-web and headless sessions at all (q-level, would be measured first). Recommended: (a) until an RCA
  consumer names a need; visibility then flips to summarized for those models and the drift rule
  follows with no change.
- k2 LiteLLM-lane durability. DeepSeek's chain of thought exists in the live response and in the
  persona's own message history, which a tools request must carry anyway (the 400 rule above). A
  callback producer that fails to write loses it; Decision 84 I-4 bars an outbox. Options: (a) make the
  LiteLLM producer replayable (R7) from the persona's durable checkpoint (CD.27), with an open marker;
  (b) keep it non-replayable (R8) and count each lost write in the producer's diagnostics, as rec-4028
  item (4) already does for a stream cut mid-flight; (c) an outbox, barred. Recommended: (b) now, and
  (a) as a T4.2 design input once the checkpoint exists. A design choice for rec-4028 and T4.2; no
  precedent.
- k3 Who reads chain-of-thought text. Options: (a) metrics only; text is retained in the data plane
  for a forensic read by session (no verb); (b) a per-call text verb (egress on every read, Decision
  88); (c) LLM labels over CoT (spends; would mirror rec-4032's materialization trigger). Recommended:
  (a). No consumer has named a need, and DeepSeek reasoning can exceed 64 KiB and spill to the blob
  port, so every read is a blob fetch.

Risk (known loss modes, not choices):

- R1 2a-1 absent. Until it lands the claude_code rows carry no visibility and keep thinking_tokens in an
  undocumented metadata key, so every legacy row reads unclassified (v07). Owner: whoever holds 2a-1
  (q1).
- R2 Bytes are not deliberation. Claude text is empty or a summary by another model, so any metric over
  thinking-row `content_bytes` measures the summarizer. Only reasoning_tokens measures deliberation;
  the verb sums no bytes.
- R3 Pass-back degradation (T4.2's, named here because capture must never feed it). If the persona
  rebuilds history from anything but the provider message, LiteLLM blanks the chain (explicit
  thinking) or the call 400s (default thinking) (VP 3). rec-4028 item (2) already takes thinking from
  the response only; the new fact for T4.2 is that LiteLLM's fill does not run under DeepSeek's
  default-on thinking.
- R4 Stale tier ids. e6 names models DeepSeek retired on 2026-07-24, and LiteLLM's bundled map marks
  `deepseek-chat` as non-reasoning, so a cost or capability lookup keyed on it is wrong. Owner: T4.2 and
  inference-provider.yaml (Decision 173 cl.2 makes it a contract edit). Named, not filed.
- R5 Grouping key. `provider` is NULL on claude_code rows (e5), so the verb groups by producer and model.
  A Claude Code session pointed at DeepSeek's Anthropic-format endpoint would land under claude_code
  with a DeepSeek model id; grouping by model keeps it apart.
- R6 One call, two producers. R5(c) keeps claude_code's model_call row, but both producers' thinking rows
  survive; the verb tests existence per observation_id (v05).
- Goodhart. deliberation share is the obvious efficiency lever, and lowering effort lowers it while
  making outcomes worse. It is diagnostic only: no consumer ranks, alarms or files a rec on it alone,
  and T3.3 reads it only beside an outcome (acceptance_passed, cost per verified merge). The drift share
  cannot be gamed by a wildcard the way a rule set can; its lever is a producer that stops writing
  visibility, which the unclassified arm counts.

Open (q1-q3 in the fixture; none is answerable from the repository):

- q1 Where is the 2a-1 plan? rec-4028 says it was accepted on 2026-09-29 and owns the contract fields and
  the claude_code parser_version 2 mapping. Checked: contract, `docs/plans`, remote branch names, the
  last 100 PRs, open recs (only rec-4028 names it), and this project's shared folder.
- q2 Does deliberation predict outcome? One session spent 64% of output tokens thinking; nothing joins
  that to an outcome yet, so T3.3 must not alarm on a deliberation share until a measurement shows it
  means something.
- q3 Who roots a LiteLLM-only persona tree? rec-4028 has the executor loop propagate session_ref, the root
  session_started_at and project_ref (e9), but a non-replayable producer emits no open marker (e8), so a
  persona run with no Claude Code transcript has no telemetry_sessions rows, and W1-2's session verbs
  cannot see it. The deliberation verb is unaffected (it reads model_call rows by session_id).

## 4. Consideration register (as authored in the fixture)

- planes: data_plane.
- failure_signal: stored visibility disagrees with stored text (full or summarized with no thinking row;
  a thinking row where none was declared; no visibility at all). Metric `deliberation_drift_share`,
  per producer and parser_version. Source: the verb's response and the T3.20 c3 monitor. Why this and
  not a count or latency: every way capture breaks here is silent (a display default flips, logging is
  switched off, a stream is cut, a mapping regresses), and each shows up as a disagreement between the
  producer's own classification and what it stored. What it cannot see: a producer that misclassifies
  and stores consistently (omitted with no text when text was available). That is the producer
  conformance tests' job (rec-4028's acceptance node `test_reasoning_visibility_matrix` and 2a-1's),
  and c3's review.
- maturity: starts at read_all, meaning the operator reviews every drift row. read_all -> sampled at >= 20
  consecutive reviewed sessions with zero drift rows; sampled -> spot_check at 0 drift rows across the
  last 200 sampled model_calls; spot_check -> anomaly_triggered at >= 30 consecutive days with
  deliberation_drift_share <= 0.01 per producer at one parser_version. A parser_version bump (2a-1 is
  one) is a rung event for the maturity-ladder controller. Seed values for that component to challenge.
- verification: c1 (the verb on DuckLake passes every vector and selects no content column), c2 (the
  monitor flags each drift kind and stays silent on clean vectors), c3 (the operator's read_all review
  before T3.3 or T3.4 reads the metrics). Each execution command names two distinct test node ids, so
  one thin test cannot satisfy it (pytest exits non-zero on a missing node id). All open.
- rollback: drop the verb and the monitor; nothing is stored, so every metric re-derives on the next
  read.
- edges: part_of T3.20 (its c3 join check is the monitor's home and its turn-grain rows carry the
  Claude Code facts); depends_on T2.36 (the reader mechanism and the writer's row-local rules); depends_on
  T4.2 (the LiteLLM lane, rec-4028 "lands with/after T4.2's LiteLLM transport").

## 5. Boundary notes for W2 synthesis

- Capture producer wiring (W1-1, #1384): its boundary note calls deliberation a transcript-less producer
  that must receive project_ref and session_started_at. True for the LiteLLM lane only; the Claude Code
  half rides W1-1's own rows. On merge W2 should add `pwi-deliberation-capture depends_on
  pwi-capture-producer-wiring`; the evaluator's L4 refuses an edge to a pilot item absent from this
  branch's fixture, so it is not added here. A parser_version bump for 2a-1 re-parses every tree under
  W1-1's runner (R7), so its warm-pass cost (W1-1 k1) applies once per tree at the bump.
- Reader verbs (W1-2, #1390): this verb composes on its shared dedupe and needs its multi-table binding
  (calls plus transcripts). W2 should add `depends_on pwi-telemetry-reader-verbs`.
- Friction classifier (W1-3, #1394): reasoning text is content, like W1-3's k3 signatures. If W2 adopts
  read-side content regex (W1-1 P1), CoT would be its largest input; this report recommends it stays out
  (k3 (a)).
- Back-validation (T3.4): a delta in deliberation share across a fix is valid only at one parser_version
  and one model; a model change moves it with no behaviour change.
- Cost/egress: reasoning tokens are already inside tokens_output and are never priced separately (both
  providers' docs, section 1), so the cost verb must not add them twice. The verb reads two narrow
  column sets; the CoT bytes it skips are the egress k3 (b) would add.
- Allow-list (rec-4141): the visibility vocabulary, the counts and the drift share are candidates; model
  ids and every text are not.
- Goodhart register: the deliberation-share rule above is this item's entry.

## 6. Not done here (and why)

- No verb, monitor, test, contract or producer code: REPORT-ONLY by brief.
- No telemetry_observations amendment: the fields are 2a-1's, already chosen; the stale tier ids (R4) are
  T4.2's contract edit.
- No `.claude/settings.json` change for k1, and no LiteLLM or DeepSeek call: a live call spends.
- No rec filed, updated or closed (Decision 67). rec-4024, rec-4026, rec-4028, rec-4029, rec-4135 and
  rec-4141 are named as owners only.
- No T3.20, T2.36, T4.2, T3.3 or T3.4 criterion text or status change.
