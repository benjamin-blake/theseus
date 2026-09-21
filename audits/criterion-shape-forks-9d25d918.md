Reversal trigger: **not-tripped**. Twelve proposed method/provenance columns are nullable on at least one parent kind: ten have no native counterpart on either kind, and primitive_slot and severity are null only for epic-shaped items (a rec's acceptance contract already admits TypedCheck {type, severity}, though no cached rec uses it); that origin sparsity does not establish incompatible epic/task requirements that the child model cannot absorb.

Q1: **b-admitted-once**. Keep graduation historical; T3.7 remains the deferred mutation/orphan policy. A periodic green sweep detects permanent failure, not permanent truth. CSF-07 records the unbounded post-admission detection latency as the declared residual on the built registry, owned by T3.7 (planned-unbuilt).

Q2: **drop-the-field**. Keep V-tier policy at plan scope or in extensions. Phase and primitive slot cannot derive deployment obligations.

Q3: **pin-at-migration-time**. Preserve authored IDs and pin bare IDs with a reviewed mapping at the clause-8 migration; no deadline or invented verification methods.

Q4: **two-tables-evidence-journal**, for both adapters. Local writes remain in-process; cloud writes use the same named port. Costs and AWS behavior were not measured.

Deferred merge key: immutable logical parent identity plus opaque criterion_id; version ULIDs are separate.

Deferred joins: evidence-to-criterion-version FK, parent identity/version, registry key qualified by git ref, plan revision, typed edges, and ops_execution_plans via the ledger's declared met_by forward FK.

Deferred partition: the existing SCD2 envelope created_timestamp -- history day(created_timestamp) on criterion revisions and evidence, current bucket(8, merge key) on the criteria projection; occurred_at is a new evidence column for event causality, not the partition column.

Deferred current projection: SCD2 history plus a transactional Type-1 current criterion projection, reusing write_scd2's existing history-plus-write-through pair; evidence remains append-only.

Deferred writer: shared storage-port writer verbs allocate and validate, extending write_scd2 (which already commits history, current projection and entity counter in one transaction); merge ingestion calls them rather than becoming another writer.

Deferred tenancy: cloud project_id on criteria/evidence and all filtered joins; local single tenancy needs no exposed tenant field.

Deferred reader: pick_work_item returns actionable criteria and version/proof-as-of tokens; separate named reads return history and evidence.

Deferred DQ: per-field intent with required identities, time, provenance and authored satisfaction; conditional method, disposition and evidence constraints. No borrowed execution_result exemption.

### What the converged shape gets wrong

**Factual corrections:** phase uses hyphens; only bare-string IDs are positional; Decision 189 eligibility is a diff/declaration predicate, not SHA ordering; EvaluatorSpec identifies a Class D contract consumer, not a criterion adjudicator; the positional assignment is at line 104; current bookkeeping does execute command-like criterion text. These six corrections were checked against source. Two also warrant design findings because they change migration or evaluation decisions.

**Design judgments:** CSF-01 requires evidence applicability and review provenance beyond reachable bases, existing paths and authored booleans. CSF-02 requires run/attempt identity so a successful retry cannot erase failure. CSF-03 requires a criterion-specific method union, including explicitly unresolved legacy methods. CSF-04 bounds quarantine lifetime and uses a generic owner link. CSF-05 preserves executable legacy oracles separately from requirement intent. CSF-06 separates logical parent/criterion keys from revision ULIDs and optional registry links.

Seven findings survive: six proposed-model issues classified planned-insufficient against the general Decision 197/T4.23 migration carriers, and CSF-07 on the built registry (S4), classified planned-unbuilt against T3.7. All have HYPOTHESIS confidence because recommendation-side ownership could not be checked. There are no live critical findings. Under the brief's mechanical maturity rule S1 is strong, S2 solid, S4 strong (one high, CSF-07) and S3, S5 and S6 frontier; frontier here does not mean every rubric dimension is strong or every future hardening item is built.

The highest-leverage change is **CSF-01: define the evidence applicability and reduction contract before freezing columns**. A proof must identify the claim version, check, observed tree/environment, producer and review boundary. An escaped defect must invalidate current applicability without rewriting history. The artifact reference must resolve to compatible retained content, not merely a reachable URL.

The independent sweep challenged the preferred two-table answer. One-table SCD2 can retain proof history and provides simpler atomic reads/writes; treating it as historyless would be a strawman. Two tables earn their place by giving repeated observations an independent grain, not by winning a checklist vote. [Type-2 dimensional modeling](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/) supports facts bound to an applicable dimension version. [Event-sourcing guidance](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) also exposes projection-consistency costs. The proposed writer and snapshot-read contracts must address those costs on both adapters; table separation alone does not. The atomic-write half already has a repository mechanism: write_scd2 commits the history append, the current projection and the entity counter in one transaction, so two-tables P9 is met by extending that primitive rather than by a new protocol.

The existing append-only precedent is only the ops_smoke_events kernel smoke table. For the criteria table itself, ops_execution_plans (one row per (rec_id, revision), current = latest revision) is the SCD2-with-parent sibling, so design_time_walk step 8's existing-sibling exemption may apply to work_item_criteria; the evidence table has no sibling and remains the one new table to escalate. T3.15's PR-body VP table is a prose evidence precursor, not an immutable criterion journal. Neither proposed design specifies expiring quarantine or continuing adequacy, so both miss P6 and P7. The exact test/run-expiry formulation is this audit's bar, not a demonstrated universal industry convention. Evidence history also cannot replace the scheduled mutation policy T3.7 already owns.

Local measurements reproduce 801 criteria: 407 bare, 394 structured, including 259 bare criteria on 57 completed items. Completed items are still reached by the touched-item gate. Minimal bulk conversion would grow 9,925 lines to 10,739; practical observed spans average 1.140 versus 6.525 lines. Six structured IDs use cA-cF and ten cN IDs are off-position. The full plan sweep found 4,665 steps: 4,015 pre-deploy, 598 post-deploy, and 52 legacy occurrences across 29 other phases. A stated lexical rule found 30 command-looking criterion texts; these were not executed.

Git history confirms 14-day and 32-day admission-to-retirement intervals for the two decay examples. These are residence intervals, not measured durations of continuous breakage. The role-check graduated_at predates its introducing commit by one day. Modified-record differential discovery, not standing surveillance, exposed the issue; CSF-07 files that unbounded interval as the built-surface residual. Re-running a historical one-shot check against a moving baseline is not the same as continuously verifying its intended behavior.

The additional Q5 questions are answered in the YAML and remain implementation obligations: how retry/duplicate/late delivery preserves nondeterminism; how both adapters atomically advance claim and proof; and what survives artifact expiry or access loss. Advice-consult design_time_walk step 8 remains open for the evidence table; the criteria table may fall under step 8's existing-sibling exemption (ops_execution_plans). The human disposes; this audit does not authorize a migration or amend CD.29.

Stale anchors: **2 entries** (one line anchor, one rename-population measurement); neither changes a verdict.

Capability: AWS access is unavailable, so cache regeneration, E4/E5 and recommendation-side dedup could not run.

Capability: pinned Python 3.12 launcher is unavailable; the authorized Python 3.14 fallback performed local counts, model probes and YAML validation.

Capability: the Claude slash-command/advice-consult harness is unavailable; step 8 remains open.

Recommendation-side dedup did not run because AWS access is unavailable; supplied rec pointers are unverified leads, not measured ownership.

Contract notes: bin/venv-python and repository presubmit/cache launcher obligations could not run; fallback local checks succeeded. No AWS commands or portal calls were attempted. Advice-consult remains open.
