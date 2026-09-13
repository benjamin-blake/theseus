# PlatformAdmin data-lake, bootstrap-state and DuckLake break-glass inline policies (Decision
# 128/166 decomposition of platform_roles.tf, T2.48).
#
# Verbatim move out of platform_roles.tf -- NO statement added, removed, or reordered, and NO
# locals hoist (this file grows no grant, so it needs no byte-limit precondition; Decision 156's
# hoist requirement applies only to the two documents T2.48 actually grows -- see
# platform_dev_policies.tf and platform_admin_policies.tf). rec-2696's proposed statement reorder
# is deliberately NOT applied here: live order was re-measured 2026-09-13 and already matches this
# file's order, so the swap would introduce drift rather than remove it. platform_roles.tf retains
# both aws_iam_role resources; see that file for the PlatformAdmin IMPORT BEFORE APPLY banner.

# PlatformDataLakeProvisioning: the data-plane rights AdminOps (iam:*/lambda/secrets) lacks, so
# `terraform apply` under agent_platform_admin can provision + manage terraform/personal's data lake.
# Least-privilege: ENUMERATED actions (no service wildcards) scoped to the agent-platform
# data lake -- no Resource "*" where the action supports a resource, no legacy bblake-* ARNs. This is
# the surface terraform apply of THIS module actually exercises: the same data-plane action set as the
# github_ci_apply CI role (oidc.tf), minus the IAM/OIDC reconcile statements (those come from iam:* in
# AdminOps) and minus item-level DynamoDB (counter VALUES are PlatformDev runtime's domain).
resource "aws_iam_role_policy" "platform_admin_datalake" {
  name = "PlatformDataLakeProvisioning"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # S3 bucket configuration terraform manages (versioning, encryption, public-access-block,
        # policy, tagging) -- read + write variants. CreateBucket included for greenfield provisioning.
        Sid    = "DataLakeBucketManage"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:GetBucketAcl",
          "s3:GetBucketVersioning",
          "s3:PutBucketVersioning",
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration",
          "s3:GetBucketPublicAccessBlock",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:GetBucketTagging",
          "s3:PutBucketTagging",
          "s3:GetBucketOwnershipControls",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketLogging",
          "s3:GetLifecycleConfiguration",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
          # T2.43 gap: aws_s3_bucket_notification.data_lake_prod_triggers is provisioned by
          # PlatformAdmin directly (admin-apply), so the admin role itself needs the write action
          # too, not just the CI roles' refresh-read grant.
          "s3:GetBucketNotification",
          "s3:PutBucketNotification",
        ]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        # S3 object IO: platform objects (tfstate, tfplan, convergence records, logs) under this
        # one bucket. Multipart actions cover large object writes.
        Sid    = "DataLakeObjectIO"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = ["${aws_s3_bucket.data_lake.arn}/*"]
      },
      {
        # DynamoDB: manage the counters TABLE only, scoped to the single table. NOT item-level
        # (GetItem/PutItem/UpdateItem) -- counter VALUES are PlatformDev runtime's domain and the seed
        # items are no longer Terraform-managed. The Describe* reads (continuous-backups/TTL/SSE) are
        # refresh-time reads the provider issues on aws_dynamodb_table every plan; omitting any one
        # breaks `terraform plan` (and therefore CD) even though apply succeeds.
        Sid    = "DynamoDBCountersTable"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable",
          "dynamodb:DescribeTable",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:UpdateTable",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
          "dynamodb:ListTagsOfResource",
        ]
        Resource = [aws_dynamodb_table.counters.arn]
      },
      {
        # T2.18 FP-B: provision the dedicated catalog-DR bucket (versioning, SSE, public-access-block,
        # lifecycle, tagging). Scoped to the DR bucket ARN ONLY -- object IO is the DR Lambda role's
        # domain, not the provisioning role's. Mirrors DataLakeBucketManage for the new bucket.
        Sid    = "CatalogDrBucketManage"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:GetBucketAcl",
          "s3:GetBucketVersioning",
          "s3:PutBucketVersioning",
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration",
          "s3:GetBucketPublicAccessBlock",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:GetBucketTagging",
          "s3:PutBucketTagging",
          "s3:GetLifecycleConfiguration",
          "s3:PutLifecycleConfiguration",
          "s3:GetBucketOwnershipControls",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketLogging",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
        ]
        Resource = ["arn:aws:s3:::agent-platform-ducklake-catalog-dr"]
      },
      {
        # T2.18 FP-B: read DR dump objects (smoke-gate head_object verification + restore-drill
        # readback). Object-level read on the DR bucket only; the DR Lambda's own role writes them.
        Sid    = "CatalogDrObjectRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectTagging",
          "s3:GetObjectVersion",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::agent-platform-ducklake-catalog-dr",
          "arn:aws:s3:::agent-platform-ducklake-catalog-dr/*",
        ]
      },
      {
        # T2.18 FP-B: manage the shared SNS alerts topic + its email subscription (Decision 39).
        # Scoped to the alerts topic ARN and its subscription ARNs. The provisioning role creates
        # and configures the topic; alarms publish to it at runtime (no publish grant needed here).
        Sid    = "AlertsTopicManage"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:ListTagsForResource",
          "sns:TagResource",
          "sns:UntagResource",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:GetSubscriptionAttributes",
          "sns:SetSubscriptionAttributes",
          "sns:ListSubscriptionsByTopic",
        ]
        Resource = [
          "arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts",
          "arn:aws:sns:${var.aws_region}:${var.account_id}:agent-platform-alerts:*",
        ]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Bootstrap state backend (PLAN-terraform-cicd-bootstrap-root / T2.23): PlatformAdmin provisions and
# uses the terraform/bootstrap root's S3 state backend. The bucket (agent-platform-bootstrap-tfstate)
# is created out-of-band by the documented runbook (terraform/bootstrap/CLAUDE.md) and is NOT a
# Terraform resource in any root -- codifying it would be circular (the bootstrap root's own state
# lives in it). This is the admin provisioning path; it does NOT weaken the bootstrap isolation, which
# fences the github_ci_apply CI role (the pipeline) out of bootstrap state. PlatformAdmin is the admin
# tier. Scoped to the one bucket; no provider refresh-read set (the bucket is not Terraform-managed).
# Provenance: applied out-of-band under agent_platform_admin (terraform -target) during the T2.23
# bootstrap provisioning ahead of this PR's merge; the merge-time CD apply reconciles it to a no-op.
# ---------------------------------------------------------------------------
resource "aws_iam_role_policy" "platform_admin_bootstrap_state" {
  name = "BootstrapStateProvisioning"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # One-time CLI provisioning (CreateBucket + versioning/SSE/public-access-block) and the
        # backend's bucket-level reads (ListBucket for state discovery). Get* variants cover
        # idempotent re-runs + post-provision verification. Scoped to the bootstrap bucket ARN only.
        Sid    = "BootstrapStateBucketManage"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:PutBucketVersioning",
          "s3:GetBucketVersioning",
          "s3:PutEncryptionConfiguration",
          "s3:GetEncryptionConfiguration",
          "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPublicAccessBlock",
        ]
        Resource = ["arn:aws:s3:::agent-platform-bootstrap-tfstate"]
      },
      {
        # Terraform S3 backend object IO: the state object + the use_lockfile=true native lock object
        # (terraform.tfstate.tflock). Get/Put/Delete cover read, write, and lock acquire/release.
        # Scoped to objects under the bootstrap bucket only.
        Sid    = "BootstrapStateObjectIO"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = ["arn:aws:s3:::agent-platform-bootstrap-tfstate/*"]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# DuckLake break-glass (CD.33 O-1 / Decision 81): an EXPLICIT, auditable PlatformAdmin grant to
# attach the DuckLake catalog read-only for inspect/repair -- the Neon DSN secret + S3 read on the
# ducklake-* data prefixes. AdminOps (secretsmanager GetSecretValue *) and PlatformDataLakeProvisioning
# (s3 GetObject on the bucket) already cover these capabilities broadly; this dedicated, narrowly-scoped
# policy is the NAMED surface the catalog-operations runbook (Section 1) points to so the break-glass
# read is auditable rather than implicit. See docs/runbooks/ducklake-catalog-operations.md.
# ---------------------------------------------------------------------------
resource "aws_iam_role_policy" "platform_admin_ducklake_breakglass" {
  name = "DuckLakeBreakGlass"
  role = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "NeonCatalogDsnRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn]
      },
      {
        # Read the DuckLake Parquet data files for catalog inspect/repair (smoke + future ops prefixes).
        Sid      = "DuckLakeDataRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/ducklake-*"]
      },
      {
        Sid      = "DuckLakeDataList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["ducklake-*"]
          }
        }
      },
    ]
  })
}
