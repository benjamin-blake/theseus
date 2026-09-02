# AGENTS.md — Theseus Platform

Universal rules. For full project context, see `docs/PROJECT_CONTEXT.md` on demand.

## PUBLIC repository / confidential-data boundary

This repository is PUBLIC (Decisions 73, 83, 101). Public-content boundary (Decision 101):
- NEVER publish: AWS account IDs or ARNs, IAM ExternalIds, credentials or API keys, private operational data, or any internal hostname that provides an attack surface.
- SAFE to publish: platform engineering, infrastructure patterns, tooling, CI/CD design, and general LLM-agent architecture -- publish the engineering, never the operational secrets.
- Confidential data lives ONLY in: the personal AWS account (Secrets Manager, gitignored tfvars, S3 private prefixes), and gitignored local files (e.g. `terraform/personal/terraform.personal.tfvars`, `~/.aws/credentials`). Nothing confidential is ever committed.
- The pre-commit `never-commit` hook (shape-pattern) blocks 12-digit AWS account IDs, secret-like strings, and ExternalId patterns from reaching the repo.

## Role and environment
You are a Lead Software Developer writing production-quality Python. Primary dev surface: Claude Code on the web
(CC-web; Ubuntu 24.04). Bash is the primary shell.

## Code style
- Python 3.12+, type hints required, `async` for I/O.
- Every behavior-changing code, script, workflow, hook, or configuration edit must add or update
  an automated test that fails without the change; running an existing suite is not a substitute.
- ruff formatting; line length 127.
- No emojis in code, scripts, or documentation. Use plain ASCII hyphens (`-`) instead of em dashes.
- Default to no comments. Only add a comment when the *why* is non-obvious.
- Use Bash syntax in scripts; never emit PowerShell unless explicitly asked.

## Shell invocations
- Always invoke `bin/venv-python` instead of `python` or `python3`.
- Each Bash tool invocation is independent -- do not rely on `source .venv/bin/activate` or `source .venv/Scripts/activate`; use `bin/venv-python` directly instead.
- GitHub access is via the `github` MCP server (`mcp__github__*`) -- the gh CLI and hub CLI are deliberately not installed in either container (DEV or ADMIN); this binds any authored command surface, not merely the git-ops flow -- prefer mcp__github__* over gh in new scripts, checks, and verification-plan commands.

## Safety
- Never `eval()` or `exec()`. Parse untrusted expressions with a restricted, purpose-built parser instead.
- Never raise exceptions during module import. Defer validation to explicit calls.
- Always wrap `filemd5()` and `file()` Terraform calls on optional artifacts with `try()`.
- Terraform apply model: see `environment-taxonomy.yaml` (Axis A + Guard classification subsection) -- that file is the sole SoT. Short form: sandbox auto-applies behind the deterministic guard (Decision 77); in-budget IAM inline-policy/attachment UPDATEs on managed boundary-carrying roles now auto-apply (T2.25 / Decision 92 point 5); trust/destroy/out-of-budget IAM route to the `tf-gated-apply` Environment. Bootstrap root is admin-only out-of-band.
- **Deployment model (Decision 126):** three agent intents, one trigger each -- infra = open a PR touching `terraform/**`, CI plans and applies; code = the governed code-deploy channel (Terraform not involved); red/drift = run the one-input Reconcile action. Agents never run terraform apply as a self-directed, routine action -- the sole exception is the human-gated break-glass admin tier (below/`terraform/CLAUDE.md`), where a human reviews and explicitly directs the apply before an agent executes it; operators may always invoke it directly. See `docs/contracts/deploy-paths.yaml` for the full intent -> trigger -> recovery index (it points at, and never restates, this file's apply-model/guard rules).
- **Lambda deploy channel (Decision 125/126):** the five DuckLake Lambdas' code is decoupled from `terraform/personal` infra apply as of #544 (see `environment-taxonomy.yaml` (conformance) and `docs/contracts/build-lambda.yaml`'s `deploy_channels`) and deploy through a governed code-deploy CD channel; `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` is break-glass-only, never the routine default. See `docs/contracts/deploy-paths.yaml` for the authoritative channel status. Heuristic: when a production action (e.g. a Lambda code deploy) is auto-denied or has no obvious in-session path, check `docs/contracts/deploy-paths.yaml` first, then grep `.github/workflows/` for a governed CD path before falling back to a local permission grant.
- Windows subprocess: pass `encoding='utf-8', errors='replace'` with `text=True`. Use `sys.executable` — not the string `'python'` or `'pip'`.
- Scope boundary (LOCATION touched-files + CONTENT never-weaken invariants, evaluator `validate_scope_boundary`) is `docs/contracts/implement-scope-boundary.yaml` (Decision 59); out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`, not inline fixes.

## SLOC governance -- decompose by default, don't raise (Decision 128, amends Decision 102)
- The 500-SLOC-per-file limit (`config/sloc_budgets.yaml`, `validate_sloc_limits`) is load-bearing (rationale: Decision 128) -- a raise is never a frictionless edit.
- **When a change pushes a file past its budget (or past 500 for an unregistered file), decompose it** into a facade package (Decision 80/104/124 pattern: `__init__.py` facade re-exporting the full public surface, cohesive submodules each under budget) -- this is the default response, not a raise.
- A budget raise is a deliberate, reviewable exception: the entry line in `config/sloc_budgets.yaml` must carry an inline `# raise-approved: dec-NNN <reason>` marker naming a real `## Decision NNN:` header that AUTHORIZES the entry (Decision 165) -- `validate_sloc_budget_raises` fails the PR on any unmarked increase, new >500-SLOC registration, or unauthorized marker; decreases and removals are always unrestricted.
- `--update-sloc-budgets` never auto-seeds a newly-oversized, unregistered file -- decompose it, or register it deliberately with the marker.

## Branching — never edit or commit on `main`
**Hard rule: do not run `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or any `git commit` / `git push` command while the current branch is `main`.** If you're on main, the only allowed actions are read-only commands and creating a new branch. See `## Git-ops procedure` for the full branching topology.

- **See current branch**: the statusline at the bottom of the prompt shows it. It will read `WARNING: ON MAIN` if you're on main. Or run `git branch --show-current`.
- **Create a working branch**: on Claude Code on the web you are already on a harness-assigned session branch (e.g. `claude/...`) -- verify with `git branch --show-current`. Do NOT create an `agent/` branch.
- A `PreToolUse` hook at `.claude/hooks/never_on_main.py` enforces this at the harness level: it blocks `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, and `Bash(git commit/push ...)` while on `main`. Other Bash commands (e.g. `git status`, `ls`) still run.

## Temporary Operational Constraints
- **STRATEGIC plans suspended (Decision 67):** during this window all plans must be
  IMPLEMENTATION type -- STRATEGIC plan-type declarations are refused (enforced by /plan,
  the planning skill, and plan-critique). The planning skill's complexity heuristic (>5 files
  or >8 steps) is also suspended -- author the work as a single larger IMPLEMENTATION plan OR
  split it into multiple atomic IMPLEMENTATION plans yourself. Restores when CD.17 / T4.2
  reverses.
- **Lambda deployment -- per-Lambda gating (Decision 79, CD.16 + CD.24):** gating is per-Lambda,
  not blanket. Active artifacts (`status: active` in `src/lambdas/<slug>/manifest.yaml`) require
  build + deploy + smoke-test (V3 tier); stub artifacts do not. `config/agent/` is NOT
  Lambda-packaged. See the planning skill for the affected-artifact detection method.

## Memory policy — CLAUDE.md is canonical persistence
Do **not** write to the auto-memory system (`~/.claude/projects/.../memory/`) in this project. The user's persistence model is git-tracked CLAUDE.md files (root + per-directory) plus structured logs (`docs/SESSION_LOG.md`, `docs/DECISIONS.md`, `logs/.recommendations-log.jsonl`).

- When you learn something durable, **propose** adding it to the appropriate CLAUDE.md and let the user approve. Do not silently save.
- When the user says "remember this", propose a CLAUDE.md edit — don't reach for auto-memory.

## Agent-First Repository

This repository is designed for agent consumption. All artefacts -- docs, configs, YAMLs,
skills, slash commands -- are optimised for agent loading efficiency, not human readability.

- Prefer machine-parseable formats (YAML, structured tables) over narrative prose.
- Collocate semantic definitions with their enforcement counterparts in a single file.
  One file is better than two files covering the same subject from different angles.
- Narrative summaries are query results, not stored artefacts. When a human wants a
  summary, they query an agent -- do not store human-readable summaries as primary artefacts.
- Anti-pattern: creating a human-readable companion document alongside a machine-readable
  source. This produces a second surface that agents must sync, which is drift by design.
- When two design approaches are equally valid and one is more machine-parseable, choose
  machine-parseable.
- Precision Context Injection: call `get_rec_write_guidance()` before `file_rec()` so
  LLM-judgment fields (title, context, acceptance) get authoritative field semantics before
  composition, not as a post-rejection error (rationale: Decision 66).
- No new standing prose-architecture docs (Decision 86): forward intent to tier_items,
  rationale to Decisions, field semantics to contracts. Creating docs/INTENT-*.md or any
  equivalent standing prose-architecture doc under docs/ is forbidden.

## Skills and slash commands

Decision 90 four-tier workflow (end-goal: /orient -> /plan -> /implement -> /develop-executor; current: /orient -> /plan -> /implement, executor frozen per Decision 67):
- `/orient` — read-only orientation: surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and up to 5 disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Run before `/plan` to choose what to work on. Produces a chat reply only; writes nothing. Invokes the `orient` skill.
- `/plan` — clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.yaml`. Assumes a specific item has been chosen (run `/orient` first). Invokes the `planning` skill.
- `/implement` — executes an IMPLEMENTATION plan or scopes a STRATEGIC plan into recommendations. Invokes the `implement` and `code-review` skills.
- `/develop-executor` — supervisor for executor (Lambda) development.
- `/audit` — composes a self-contained audit prompt (`docs/audit-prompts/AUDIT-{slug}.md`) for a high-capability model to execute in a fresh session; deep recon + zero-context subagent verification happen in the composing session so the expensive model pays only for judgment. Performs no audit itself. Invokes the `audit-prompt` skill.

`/overseer` is an orchestration meta-layer, not a fifth tier: it composes the existing `/plan`
and `/implement` subagents to drive an entire platform roadmap item or audit to completion largely
unattended, with the human gating intake and completion. It never bypasses the four-tier workflow
above or the Decision 67 executor freeze -- it is interactive/human-gated, IMPLEMENTATION-only, and
does not consume the recommendation queue. Invokes the `overseer` skill.

When a slash command instructs you to "apply" or "invoke" a skill, use the `Skill` tool — do **not** manually `Read` `SKILL.md` files. The Skill tool loads them on demand.

## Operational data governance — Single Portal Invariant
All recommendation and decision writes go through `python -m scripts.ops_data_portal`. Never `Edit` or `Write` to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` directly -- `validate.py` will fail CI. Recommendation IDs are allocated BY THE WRITER atomically with the insert (`file_ops`, Decision 84 I-2) -- never client-side; decision numbering authority is `DECISIONS.md` (callers supply `decision_id`). The local JSONL files are read-only caches.

Agent surface is three functions: `file_rec`, `update_rec`, `sync`. Do not call `sync.ops` or any pull CLI directly. Portal calls require the `agent_platform` (PlatformDev) assume-role profile to reach the reader/writer Function URLs. If unreachable, confirm the chain with `aws sts get-caller-identity --profile agent_platform` (the session-start hook `.claude/hooks/session_start_aws.sh` reports this each session); locally, refresh the `agent_static` key if it has been rotated. There is no SSO login in the static-key model. A write that cannot complete FAILS LOUDLY at the call site -- there is no offline outbox (Decision 84 I-4); re-file after restoring connectivity.

## Warehouse-as-source-of-truth invariant
This is an append-only lakehouse. The warehouse is the single source of truth for all operational data; local files are never upstream of it.

**Source-of-truth by table (Decision 84 consolidation, 2026-06-11):**
- **`ops_recommendations`, `ops_decisions`, `ops_priority_queue` = DuckLake-on-Neon, SOLE backend.** Reads transit the closed `ducklake_reader` boundary via NAMED VERBS (Decision 84 I-3; no caller SQL); writes transit `ducklake_writer` (`file_ops` allocates rec ids in-transaction). There is exactly one backend and NO rollback flag (`OPS_STORAGE_BACKEND` retired -- the frozen legacy copy stopped being coherent the day writes moved). `ops_decisions` rebuilds from `DECISIONS.md` via `ops_data_portal --backfill-decisions-md`.

Local files have exactly one valid role:

1. **Read cache** (`logs/.recommendations-log.jsonl`, `logs/.decisions-index.jsonl`) — derivative projection rebuilt FROM the warehouse via `sync.ops pull` (all tables from the DuckLake reader). Downstream of the warehouse, never upstream. There is no staging outbox: a write that cannot reach the warehouse fails loudly (Decision 84 I-4).

**Hard rule: a read cache is never a write source.** Reading any file in `logs/` and replaying it
back into the warehouse is the CRUD anti-pattern in lakehouse clothing, and the row-resurrection
failure mode it produces is recorded in Decision 84 -- recs writes go only through the writer.

The legitimate write paths are: (a) `file_rec` / `update_rec` portal calls, and (b) ETL from a non-warehouse source of truth (e.g., `DECISIONS.md` -> `ops_decisions`). Anything else that writes warehouse rows must be reviewed for replay-from-cache violations.

If a clone or runner shows stale data, an operator may rebuild that environment's local cache by running `bin/venv-python -m scripts.sync.ops sync` (which pulls every table from the DuckLake reader and overwrites local). Never fix drift by replaying the local file back upstream.

## Data-modeling default
Before designing any table, decide **grain first** -- "one row per ___" -- before picking a write
mode; never design "one row per entity, mutate in place." Full rules (write-mode branch, identity,
merge-on-business-key, partitioning) live in `docs/contracts/data-modeling-standard.yaml` -- this
is the ambient trigger; read the contract at design time. The `planning` skill's Data-Model
Assessment walks the full checklist.

## Git-ops procedure
Read `docs/contracts/git-ops.yaml` before any push/PR/CI/merge action -- it carries the full
procedure (branching topology, commit-message conventions, rebase mechanics, wake-signal detail,
and the CI-credential/OAuth-token runbook); AGENTS.md keeps only the machine-enforced norms and
one-line triggers below.

- **Branch rule**: work on the harness-assigned `claude/...` session branch; never commit directly to `main`.
- **Presubmit tier**: see the table below -- fast `--pre` gates PRs, full tier runs pre-handoff (local) + post-merge.
- **Squash-merge**: `mcp__github__merge_pull_request(..., merge_method="squash")` once CI is green.
- **Never-poll wake**: event-driven only (`subscribe_pr_activity` plus the CI-green/merge-conflict comment signals) -- never sleep/poll for CI or merge status.
- **Resolves: trailer**: when a plan bundles recommendations, name them (`Resolves: rec-NNNN[, rec-MMMM]`) in the squash-merge commit body to trigger `rec-autoclose.yml`.
- **Decision-record routing**: whether content clears the bar for a numbered Decision, and where it routes when it does not, is governed by `docs/contracts/decision-entry.yaml`'s `significance.routing_rule` -- never restated here.

### Two-tier presubmit model
| Tier | When | Command | Gate |
|---|---|---|---|
| Fast (`--pre`) | PR / edit loop | `bin/venv-python -m scripts.validate --pre` | Authoritative pre-merge gate when run by PR CI (Decision 73); advisory only when run outside CI |
| Full | Pre-handoff (local) + post-merge on `main` | `bin/venv-python -m scripts.validate` | See `## Merge protocol` (post-merge disposition). |

### Commit signing (CC-web: SSH-signed via harness signer)
- CC-web commits ARE SSH-signed (commit.gpgsign=true, gpg.format=ssh, host-held key); GitHub
  reports them Verified.
- Local `git log --format=%G?` reads `N`/`B` only because this container cannot verify SSH
  signatures locally (no ssh-keygen) -- not evidence of a missing signature.
- `session_start_commit_signing.py` sets `gpg.ssh.allowedSignersFile` so the harness Stop hook's
  signature check stops false-positiving. If it still fires, check which half: the committer-email
  half (`%ce != noreply@anthropic.com`) is a real trigger whose remediation is correct.
- Do NOT reset-author or `git commit --amend -S` to chase the signature flag -- it only churns
  SHAs.

## Merge protocol
**Canonical authority: `docs/contracts/git-ops.yaml` for the full PR/CI/squash-merge flow, two-tier presubmit model, and Resolves trailer.**

- **Post-merge full-tier failure on `main`**: ci-rca automatically files a `source=ci_rca`, `priority=critical` rec (forward-fix, never auto-revert). Do NOT manually patch until the rec is reviewed in `/plan` -- inline fixes reproduce the workaround anti-pattern (Decision 55, Decision 72).
- **PR-branch `--pre` failure**: per `docs/contracts/ci-rca-lifecycle.yaml` trigger_scope, no rec is filed and nothing gates -- ci-rca watches `main` only; diagnose and fix on the branch (Git-ops step 6).
- Manual confirmation: if `validate.py` appears to skip tests, run `pytest` directly to confirm.

## Instruction architecture
The layered contract (Layer 1 universal rules through Layer 5 executor prompts) is at
`docs/contracts/instruction-architecture.yaml` -- see it for the full layer table.

The `.github/prompts/scheduled/` and `.github/agents/schedule.yaml` surfaces are retained for
live scheduled agents.
