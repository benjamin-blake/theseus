# Criterion shape forks audit at 9d25d91

**Reversal trigger:** `not-tripped`. The proposal has twelve subtype-only nullable columns, but the split is executable/reviewed versus prose criteria, not epic-shaped versus task-shaped parents. A typed method extension absorbs the nulls without reopening Decision 197 clause 3's shared child grain.

**Q1:** `a-periodic-standing-runs` - keep commit-relative differential admission and add an all-live-shards cadence.

**Q2:** `drop-the-field` - verification tier remains plan-grain routing/operator taxonomy, not a criterion column.

**Q3:** `pin-at-migration-time` - mint stable criterion identities during clause 8, preserving explicit aliases for positional legacy rows.

**Q4:** `two-tables-evidence-journal` for both adapters - preserve immutable run history, but require one atomic writer transaction and a current proof projection.

## Deferred walk inputs

- **Merge key:** `parent-plus-criterion-id` (`parent_work_item_ulid, criterion_id`); row ULID identifies a version.
- **Join keys:** `evidence-table-fk`; evidence targets the exact criterion-version ULID, while `(plan_slug, check_id)` remains the optional registry link.
- **Partition:** `event_date` on criteria history and evidence.
- **Current projection:** `scd2-history-plus-type1-current` for efficient kind-generic picks and auditable rewrites.
- **Write boundary:** `portal-writer-verb`, owned by the work-item storage-port writer, not plan authoring.
- **Tenancy:** `project-id-on-parent-only`; child tenancy is inherited, and the local adapter remains single-tenant.
- **Read boundary:** `criteria-on-parent-read`; `pick_work_item` returns the current item with current criteria/proof summary, while detailed evidence has a separate named read.
- **DQ intent:** `per-field-dq-intent`; common identity, text, status and temporal fields are non-null, and typed method extensions enforce their own conditional fields.

The required data-modeling walk's advice-consult escalation for a new table, identity, and merge key remains open; this audit does not discharge it.

## What the converged shape gets wrong

### Factual corrections

- `phase` uses `pre-deploy | post-deploy`, not underscore spellings. The corpus has 4,613 such values and 52 schema-v1 legacy values across 29 other strings.
- `cN` is positional only for bare-string load-time normalization. Six structured ids are `cA`-`cF`, and ten numeric ids disagree with position.
- Decision 189 eligibility is diff status `A`/`??` plus falsy `implementation_declared`; it does not compare `authored_at_sha`.
- The positional assignment source anchor is line 106, not the quoted approximate range.

### Design judgments

- The two-table design is unsafe until one writer atomically appends evidence and advances the current proof projection (`CSF-01`).
- The evidence vocabulary needs an escaped-defect contradiction/reopen event (`CSF-04`) and must retain command/check snapshot, bounded result reference, attempts and nondeterministic classification (`CSF-05`).
- A Class D `EvaluatorSpec` is not a portable criterion discriminator (`CSF-06`). The twelve check/VP fields belong in a typed method extension, not on every common criterion row (`CSF-09`).
- Current positional aliases cannot be treated as stable merge identity (`CSF-03`).

## Highest-leverage change

`CSF-01`: define a single storage-port transaction that appends immutable evidence and advances SCD2/current criterion proof state. This preserves journal history without allowing satisfaction and its proof to become observably inconsistent on either adapter.

## Additional questions

1. **Who owns claim/evidence atomicity?** One storage-port writer operation on both adapters; local execution uses a local database transaction, not a warehouse round trip.
2. **Is evaluator subtype the same axis as parent kind?** No. Either parent kind can carry prose, executable or independently reviewed criteria, so evaluator payload cannot justify separate epic/task criteria shapes.

The six seeded Q5 questions are answered in the YAML: rewrites create a new version of the same criterion; rehome is both claim and joinable edge; the writer allocates parent and criterion identities; text gets a fail-loud byte bound above the observed maximum; the clause-7 rename stays adapter-only; and escaped defects append contradiction evidence that reopens current state.

There are 4 stale-anchor entries; none changed a verdict.

Capability: no origin remote/ref existed, so the harness-provided 9d25d91 snapshot is the audited base.

Capability: preflight produced no recommendation cache, so recommendation dedup and E4/E5 did not run; all affected findings are `HYPOTHESIS` and hit counts are null.

Capability: available history begins after the claimed registry admission dates, so exact decay intervals could not be re-derived.

Capability: subagents were prohibited by this execution environment; all cited leads were re-verified locally.

Capability: no GitHub MCP server or configured remote is available; push/PR creation is expected to fail under the prompt's recorded-deviation path.

Contract note: the base-ref substitution, missing cache, and still-open advice consult are recorded in `meta.contract_notes`.
