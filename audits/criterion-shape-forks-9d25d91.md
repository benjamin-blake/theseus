# Criterion shape forks audit at 9d25d91

**Reversal trigger:** `not-tripped`, conditional on `CSF-09`. Section 10.2 as written adds twelve nullable columns and would trip the literal "before adding nullable columns" text; the split is executable/reviewed versus prose criteria, not epic-shaped versus task-shaped parents, so with CSF-09's typed method extension the nulls are absorbed without reopening Decision 197 clause 3's shared child grain.

**Other reversal conditions:** `merge-authored-edges-lossy` is near-triggered -- `criterion_traces_to` and the rehome edge need the edge target and the criterion-version ulid, which a `Resolves:`-style squash trailer cannot carry; the merge payload must preserve them or clause 5 reopens. `executor-needs-tier-items-pre-mvp` is not near-triggered.

**Q1:** `a-periodic-standing-runs` - keep commit-relative differential admission and add an all-live-shards cadence. This closes only the FAIL-decay half (a permanently-FAIL row is caught on the next cadence); a permanently-TRUE row passes any re-run and is owned by T3.7 c1's scheduled mutation leg. Re-derived intervals on the commit clock: 14 days and 32 days.

**Q2:** `drop-the-field` - verification tier remains plan-grain routing/operator taxonomy, not a criterion column.

**Q3:** `pin-at-migration-time` - mint stable criterion identities during clause 8, preserving explicit aliases for positional legacy rows. Option (c) is subsumed: complete-item bare rows migrate as `text_origin: migrated_bare`, met, no method, and are never converted in YAML (1.13 lines per bare criterion versus 6.52 per structured one today).

**Q4:** `two-tables-evidence-journal` for both adapters - preserve immutable run history, but require one atomic writer transaction and a current proof projection.

## Deferred walk inputs

- **Merge key:** `parent-plus-criterion-id` (`parent_work_item_ulid, criterion_id`); row ULID identifies a version.
- **Join keys:** `evidence-table-fk`; evidence targets the exact criterion-version ULID, while `(plan_slug, check_id)` remains the optional registry link.
- **Partition:** `event_date` on criteria history and evidence.
- **Current projection:** `scd2-history-plus-type1-current` for efficient kind-generic picks and auditable rewrites; the parent-plus-revision sibling is `ops_execution_plans`, so the step-8 advice-consult narrows to the new evidence table and the merge key.
- **Write boundary:** `portal-writer-verb`, owned by the work-item storage-port writer, not plan authoring.
- **Tenancy:** `project-id-on-parent-only`; child tenancy is inherited, and the local adapter remains single-tenant.
- **Read boundary:** `criteria-on-parent-read`; `pick_work_item` returns the current item with current criteria/proof summary, while detailed evidence has a separate named read.
- **DQ intent:** `per-field-dq-intent`; common identity, text, status and temporal fields are non-null, and typed method extensions enforce their own conditional fields.

The required data-modeling walk's advice-consult escalation remains open for the new evidence table and the merge key; the criteria table's grain matches an existing sibling and needs none. This audit does not discharge it.

## What the converged shape gets wrong

### Factual corrections

- `phase` uses `pre-deploy | post-deploy`, not underscore spellings. The corpus has 4,613 such values and 52 schema-v1 legacy values across 29 other strings.
- `cN` is positional only for bare-string load-time normalization. Six structured ids are `cA`-`cF`, and ten numeric ids disagree with position.
- Decision 189 eligibility is diff status `A`/`??` plus falsy `implementation_declared`; it does not compare `authored_at_sha`.
- The positional assignment source anchor is `scripts/platform_roadmap_models.py:104` (normalizer at :98), not the quoted approximate range.
- `text` is not "judged, never executed" today: the bookkeeping walk runs executable-looking criterion text via subprocess (`docs/contracts/tier-item-lifecycle.yaml:131`); E6 counts 11 such texts.

### Design judgments

- The two-table design needs one storage-port writer verb that spans both tables -- ducklake_writer already does history-append plus current projection in one op for a single table, and that control does not reach a two-table write (`CSF-01`, high).
- The evidence vocabulary needs an escaped-defect contradiction/reopen event (`CSF-04`) and must retain command/check snapshot, bounded result reference, attempts and nondeterministic classification (`CSF-05`).
- A Class D `EvaluatorSpec` is not a portable criterion discriminator (`CSF-06`). The twelve check/VP fields belong in a typed method extension, not on every common criterion row (`CSF-09`).
- Current positional aliases cannot be treated as stable merge identity (`CSF-03`).

## Highest-leverage change

`CSF-01`: rescope the storage-port writer so one verb appends immutable evidence and advances the SCD2/current criterion proof state in the same transaction, extending the single-table MERGE-on-ULID plus current-projection path ducklake_writer already has (`docs/contracts/ducklake_writer.yaml:50`) across two tables. The skew it closes is a bounded, join-detectable window rather than an undetectable false proof, which is why it is high, not critical.

## Additional questions

1. **Who owns claim/evidence atomicity?** One storage-port writer operation on both adapters; local execution uses a local database transaction, not a warehouse round trip.
2. **Is evaluator subtype the same axis as parent kind?** No. Either parent kind can carry prose, executable or independently reviewed criteria, so evaluator payload cannot justify separate epic/task criteria shapes.

The six seeded Q5 questions are answered in the YAML: rewrites create a new version of the same criterion; rehome is both claim and joinable edge; the writer allocates parent and criterion identities; text gets a fail-loud byte bound above the observed maximum; the clause-7 rename stays adapter-only; and escaped defects append contradiction evidence that reopens current state.

There are 0 stale-anchor entries (the brief's anchors resolve exactly at 9d25d91); none changed a verdict.

Capability: no origin remote/ref existed, so the harness-provided 9d25d91 snapshot is the audited base.

Capability: preflight produced no recommendation cache, so recommendation dedup did not run; all affected findings are `HYPOTHESIS` and hit counts are null. E4/E5 were filled post-audit by the reviewer (round 1) from a local cache dated 2026-09-20.

Capability: subagents were prohibited by this execution environment; all cited leads were re-verified locally.

Capability: no GitHub MCP server or configured remote is available; push/PR creation is expected to fail under the prompt's recorded-deviation path.

Contract note: the base-ref substitution, missing cache, and still-open advice consult are recorded in `meta.contract_notes`.
