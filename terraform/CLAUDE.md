# Terraform — directory-scoped rules

Loaded automatically when Claude reads or edits files in this directory. Universal rules in repo-root `CLAUDE.md` still apply.

Some rules below restate root rules for proximity. Root `CLAUDE.md` is authoritative if they ever drift.

## Hard rules
- **Optional artifacts**: Always wrap `filemd5()` and `file()` calls on optional artifacts with `try()`. Bad: `source_code_hash = filemd5("build/lambda.zip")`. Good: `source_code_hash = try(filemd5("build/lambda.zip"), md5(file("module_file.tf")))`.
- **Tag value charset**: Every literal tag value must stay inside the S3 TagValue charset -- letters, digits, whitespace, and `+ - = . _ : / @` only. No parentheses, no commas, no em dashes; use plain ASCII hyphens. S3 is the strictest AWS tag-value charset in this repo's tree (other services tolerate parentheses/commas), so authoring to the S3 charset everywhere is the safe default rather than tracking a per-service exception. Enforced by `validate_terraform_tag_charset` (scripts/checks/iam_tf/).
- **Plan before apply**: Plans modifying `.tf` files must present `terraform plan` output to the human before any `terraform apply`. Apply model: see `environment-taxonomy.yaml` Axis A + Guard classification subsection (sole SoT, Decision 77). Short form: sandbox auto-applies behind the deterministic guard; in-budget IAM inline-policy/attachment UPDATEs on managed boundary-carrying roles now auto-apply (T2.25); trust/destroy/out-of-budget IAM route to gated-apply. SIT/PROD remain human-gated and are future-state. See `planning` skill, Step 4 (Infrastructure Assessment).
- **IAM precedence**: If a change modifies IAM (`*.tf` IAM resources or roles attached to Lambdas), `terraform apply` must precede any Lambda code deploy.

## AWS context
- Region: `eu-west-2`
- Account: personal platform account (ID supplied via gitignored `terraform/personal/terraform.personal.tfvars`; never committed).
- Profile: `agent_platform` (PlatformDev, runtime) for agent operations; `agent_platform_admin` (PlatformAdmin) for provisioning (creates IAM + OIDC).
- Personal-account infra lives in the isolated `terraform/personal/` root module (own provider + state); it is the only live root module. The legacy work-account root's `.tf` files (retained for a while as architectural-evolution artefacts per CD.21, never applied) were removed in the platform cleanse.
- The personal account has no SCP restricting IAM users or external OIDC (Decisions 36/37 do not apply to this account). OIDC provider + CI roles are created in `terraform/personal/oidc.tf`.

## Running terraform/personal/ on CC-web
**This project runs ONLY on Claude Code on the web. There is no operator local machine.**

Read `docs/contracts/terraform-cc-web-operations.yaml` before touching `terraform/personal/` -- it
carries the full CC-web operating procedure (provider-mirror init, remote-state variable recovery,
the speculative-plan + apply-the-saved-plan pipeline, alarm-only drift detection, the convergence
anchor, and the operator-only break-glass loop). This stub carries only what the ROUTINE
(non-admin) loop needs unaided.

**Agents never run terraform apply as a self-directed, routine action; operators may always invoke
it directly. The sole agent exception is the human-gated break-glass admin tier in
`docs/contracts/terraform-cc-web-operations.yaml` -- an agent may execute `terraform apply` there
only after a human has reviewed the plan and explicitly directed it (Decision 126).**

**Deployment model (Decision 126):** the PR -> CI apply pipeline below is the default, ambient
path. Local/manual apply is operator-only break-glass, not a routine agent action -- see
`docs/contracts/terraform-cc-web-operations.yaml`'s operator-only / break-glass section. Full
intent -> trigger -> recovery wayfinding: `docs/contracts/deploy-paths.yaml`. Guard classification
(what auto-applies vs what blocks) is authoritative SOLELY in `environment-taxonomy.yaml` Axis A +
Guard classification (T2.25 / Decision 92 point 5) -- the table below names the channel, it does
not restate that classification.

| Want | Do | If blocked |
|---|---|---|
| Apply a guard-PASS (non-IAM or in-budget IAM) `terraform/personal` change | Open a PR; CD (`terraform-apply-sandbox.yml`) plans on the PR and applies the SAME reviewed plan.bin at merge (T2.21, no re-plan) | N/A -- this is the primary path |
| Apply an out-of-budget IAM / trust / destroy `terraform/personal` change | Open a PR; CD routes to the `tf-gated-apply` GitHub Environment | Approve in GitHub Actions (benjamin-blake); CD applies the same reviewed plan.bin -- never from a laptop |
| Recover from a red convergence record (failed/refused apply, or drift) | Red commit's HCL still right: dispatch Reconcile (`reconcile.yml`). Fix merged after the red commit: `terraform-apply-sandbox` `workflow_dispatch` acknowledge-and-retry. Rule + admin split-apply: `docs/contracts/deploy-paths.yaml` reconcile row | None |
| Apply `terraform/` (legacy hashicorp/*-only roots) or `terraform/github` | Same PR -> CD path where a workflow exists | See `docs/contracts/terraform-cc-web-operations.yaml`'s operator-only / break-glass section |
| Apply `terraform/bootstrap`, or apply `terraform/personal` by hand (bootstrap, reversing a manual admin change, or a guard-BLOCKed case with no CD path yet) | Operator action only | See `docs/contracts/terraform-cc-web-operations.yaml`'s operator-only / break-glass section |

## Out-of-band IAM grants (drift -- not managed by this module)

The `PlatformDev` and `PlatformAdmin` roles pre-exist the module and are now BOTH codified (see the
CODIFIED bullets below). The only item still applied out-of-band via the `platform_breakglass` IAM
user (full admin) and NOT codified in `terraform/personal/` is the redundant `AgentPlatformRuntime`
inline policy (slated for removal) -- re-creating infra elsewhere will not restore it; reapply manually if needed.

- **`PlatformAdmin` + `PlatformDataLakeProvisioning` (CODIFIED 2026-05-29 in `terraform/personal/platform_roles.tf`;
  datalake policy narrowed to least-privilege 2026-05-30):**
  `aws_iam_role.platform_admin` (import ID `PlatformAdmin`, `max_session_duration = 3600`) plus its two inline
  policies -- `aws_iam_role_policy.platform_admin_ops` (`AdminOps`: identity admin -- `iam:*` + admin Lambda +
  secretsmanager) and `aws_iam_role_policy.platform_admin_datalake` (`PlatformDataLakeProvisioning`: the data-plane
  rights AdminOps lacks). The datalake grant is required so `terraform apply` under `agent_platform_admin` can
  provision + manage the data lake and counters table. It is ENUMERATED least-privilege (no
  service wildcards; no legacy `bblake-platform-*` ARNs), scoped to the agent-platform data lake:
  `s3` bucket-config + object IO on `agent-platform-data-lake` only; DynamoDB TABLE-level actions (NOT item-level
  -- counter VALUES are PlatformDev runtime's domain) on `agent-platform-counters` only. The action set mirrors the
  `github_ci_apply` CI role's data-plane statements. NOTE: the set includes refresh-time READS the AWS provider
  (v5.100) issues on every `plan` -- `dynamodb:DescribeContinuousBackups`/`DescribeTimeToLive` --
  which apply does not exercise but `plan` (and therefore CD) requires; do not prune them as "unused". IMPORT the
  role before apply; the trust policy MUST show NO change in `plan` (lockout guard -- this is the role the apply
  assumes). If a future module addition needs a new data-plane action, expect the FIRST `plan` after the apply to
  surface it as an AccessDenied refresh read; add it (scoped) and re-apply with `-refresh=false` (state is fresh
  from the apply), then a full `plan` converges.
- **PlatformDev runtime grant (CODIFIED 2026-05-29 in `terraform/personal/platform_roles.tf`):** the
  `agent_platform` (PlatformDev) runtime role is now Terraform-managed. `aws_iam_role.platform_dev`
  (imported, ID `PlatformDev`) sets `max_session_duration = 36000` (was 3600 -- the 3600 max blocked
  CC-web's 10h unattended sessions); `aws_iam_role_policy.platform_dev_runtime` codifies the `DailyOps`
  inline policy (S3 read-write on `agent-platform-data-lake`;
  DynamoDB on `agent-platform-counters`; DuckLake verb invokes). Applied via `platform_breakglass`
  with `-target` on the two role resources. Trust policy verified unchanged at apply time.
  Reconciliation at import time (the role was NOT permissionless, contrary to the prior PENDING note):
    - A stale pre-rename `DailyOps` (dead `bblake-*` targets + a live Bedrock invoke-model grant) already
      existed and was imported; the apply overwrote it with the agent-platform grant. Net live capability
      dropped: the Bedrock invoke-model grant (treated as unused -- `AgentPlatformRuntime` never granted Bedrock
      and ops works without it; no Bedrock consumer was found for this role, but no exhaustive audit was run).
    - A separate out-of-band `AgentPlatformRuntime` inline policy already granted the same agent-platform
      ops set, so ops calls succeeded both before and after this change. It is now a redundant duplicate of
      the codified `DailyOps`. FOLLOW-UP: remove `AgentPlatformRuntime` via `platform_breakglass`.

Follow-up (remaining): remove the now-redundant `AgentPlatformRuntime` inline policy via `platform_breakglass`
(its grants are fully covered by the codified `DailyOps`). A formal Decision recording the static-key credential
model (PlatformDev + PlatformAdmin codification, Decision-57 SSO-recovery supersession) is filed via the ops portal.

- **DuckLake IAM read-wildcard closure (PLAN-terraform-sandbox-convergence-closure, 2026-06-18; SSM List* completion PLAN-ci-apply-ssm-list-closure rec-2276, 2026-06-18, `github_ci_apply` inline policy, out-of-band admin apply):**
  The iterative-discovery anti-pattern for `github_ci_apply` refresh-READ grants (rec-2223 round, rec-2251 round) is
  permanently closed. Seven READ-only Sids use per-service wildcards (`Describe*/List*` or `Get*/List*`) scoped to the
  same resource ARNs as before: `CloudWatchLogsRead`, `LambdaRead`, `EventBridgeRead`, `SNSRead`, `CloudWatchAlarmsRead`,
  `SecretsManagerReadOnly`, `SSMParameterRead`. WRITE Sids (`EventBridgeWrite`,
  `CloudWatchAlarmsWrite`, `LambdaPermissionWrite`, `SSMFeatureFlagsManage`, `ConvergenceRecordWrite`,
  `IAMRoleReconcile`, `OIDCProviderReconcile`) remain enumerated and ARN-scoped (no wildcards). IAM read Sids
  (`IAMRolesRead`) remain enumerated per Decision 35 (policy defined in `terraform/bootstrap/github_ci_apply.tf`).
  `SSMParameterRead` grants `ssm:Get*/Describe*/List*` scoped to `parameter/agent-platform/*` (the original
  closure shipped `Get*/Describe*`; `ssm:ListTagsForResource` is a `List*`-class action the AWS provider calls
  on every `aws_ssm_parameter` refresh, surfaced by rec-2276 as a missed gap on the first apply-sandbox run
  under the `github_ci_apply` CI identity -- the SSM List* completion round landed with rec-2276).
  All seven READ Sids now use per-service wildcards covering all refresh-read actions (`Describe*/List*` or
  `Get*/List*` for six Sids; `Get*/Describe*/List*` for `SSMParameterRead`); no further iterative-discovery
  rounds are expected.

## Lambda interaction
- Lambda zipped deployment limit ~262144000 bytes. `scripts/build_lambda.py` asserts this.
- Lambda runtime: Python 3.12.

For Lambda deployment workflow rules, see `src/data/handlers/CLAUDE.md`.
