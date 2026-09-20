# PlatformDev runtime inline policy (Decision 128/166 decomposition of platform_roles.tf, T2.48).
#
# Split out of platform_roles.tf as a pure move -- no statement added, removed, or reordered
# relative to origin/main, other than the T2.48 observability-read addition below and the
# byte-limit precondition hoist (Decision 156) that addition requires. platform_roles.tf retains
# both aws_iam_role resources; see that file for the PlatformDev IMPORT BEFORE APPLY banner.
#
# rec-2793 idiom (DEP-01 anti-recurrence, mirrored from
# terraform/bootstrap/github_ci_apply_policy.tf): hoisted out of the aws_iam_role_policy
# resource's inline `policy = jsonencode({...})` attribute so the lifecycle precondition below
# can self-reference the rendered JSON (a precondition cannot reference `self` -- that is
# postcondition-only).
locals {
  platform_dev_runtime_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3ReadWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/*"]
      },
      {
        Sid      = "S3List"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        Sid    = "DynamoDBCounters"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:UpdateItem",
        ]
        Resource = [aws_dynamodb_table.counters.arn]
      },
      {
        # T2.19 recs cutover: the ops portal runs as PlatformDev at RUNTIME and reaches the closed
        # DuckLake boundary by SigV4-invoking the writer/reader AWS_IAM Function URLs (file_rec /
        # update_rec -> writer; recs reads -> reader). Without this grant every post-cutover recs op
        # fails 403 AccessDenied at the Function-URL auth layer. Scoped to the two function ARNs.
        #
        # ACTION: lambda:InvokeFunction is the action the Function-URL IAM authorizer actually checks.
        # Verified live 2026-06-09: InvokeFunction alone, scoped to these ARNs, authorizes the URL invoke
        # (stable past propagation), while lambda:InvokeFunctionUrl alone is INSUFFICIENT -- reproducible
        # 403 over 3 min, even at Resource:"*" and even with a resource-based aws_lambda_permission added.
        # PlatformAdmin works only because its AdminOps lambda statement (below) includes InvokeFunction.
        # The IAM policy simulator reports InvokeFunctionUrl as "allowed" but the live URL denies it -- do
        # not trust the simulator for Function-URL authorization. InvokeFunctionUrl is retained alongside
        # InvokeFunction for AWS-doc alignment / forward-compat (harmless, not sufficient on its own; this
        # matches the two-action grant in lambda_tooling_iam.tf). Maintenance ops stay break-glass on PlatformAdmin.
        Sid    = "DuckLakeInvokeRuntime"
        Effect = "Allow"
        Action = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl"]
        # Scoped to writer + reader, both the unqualified ARN and the :* qualified form (the URLs are on
        # $LATEST/unqualified; the :* form covers any future qualifier/alias). Verified live with this
        # exact 4-ARN scoping.
        Resource = [
          aws_lambda_function.ducklake_writer.arn,
          "${aws_lambda_function.ducklake_writer.arn}:*",
          aws_lambda_function.ducklake_reader.arn,
          "${aws_lambda_function.ducklake_reader.arn}:*",
        ]
      },
      {
        # DuckLake endpoint-discovery: SSM GetParameter on the /agent-platform/ducklake/* path so
        # the runtime client can resolve the Function URLs without an env var or terraform binary.
        # Decision 81 (endpoint-discovery only -- not a data-plane expansion; write/read transit the
        # InvokeFunction grant above). MANUAL admin-apply required (IAM change, Decision 77 guard).
        Sid    = "DuckLakeEndpointDiscovery"
        Effect = "Allow"
        Action = ["ssm:GetParameter"]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/ducklake/*",
        ]
      },
      {
        # Inference-credential read for CD.28 T0.4: the PlatformDev runtime (smoke-test CLI,
        # future T4.2 LiteLLM transport) fetches the DeepSeek and Anthropic API keys via
        # get_secret_value. Scoped to exactly the two inference-credential secret ARNs defined
        # in inference_credentials.tf -- no wildcard (least-privilege per the IAM grant pattern
        # established by DuckLakeEndpointDiscovery and DuckLakeInvokeRuntime above).
        # MANUAL admin-apply required (IAM change, Decision 77 guard fail-closes). # pragma: allowlist secret
        Sid    = "InferenceCredentialsRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.deepseek_api_key.arn,
          aws_secretsmanager_secret.anthropic_api_key.arn,
        ]
      },
      {
        # T2.48 (rec-2851): observability reads so the PlatformDev runtime can triage alarms and
        # tail Lambda logs from the platform itself instead of only via GitHub Actions job logs.
        # cloudwatch:DescribeAlarms and logs:DescribeLogGroups are list operations that do not
        # support resource-level scoping, so they sit on "*" alongside the metric read verbs. No
        # cloudtrail verb here: the permissions boundary's DataPlaneAllow has no cloudtrail entry,
        # so a grant on this bounded identity would be inert (PlatformAdmin carries it instead).
        Sid    = "ObservabilityMetricRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:GetMetricData",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarms",
          "logs:DescribeLogGroups",
        ]
        Resource = "*"
      },
      {
        # Log-stream reads scoped to the agent-platform Lambda log-group prefix, mirroring
        # AdminOps' own LambdaLogGroupRead Sid so the runtime identity can tail the same log
        # groups AdminOps diagnoses from, without escalating to break-glass.
        Sid    = "ObservabilityLogStreamRead"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*",
          "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*:log-stream:*",
        ]
      },
      {
        # DEP-13 (T2.44 / Decision 144 pt.3, pt.7): explicit Deny overriding the bucket-wide
        # S3ReadWrite Allow above -- fences the ambient PlatformDev runtime identity (every CC-web
        # session) off the convergence-record anti-masking anchor and the tfplan/tfstate prefixes,
        # so the runtime identity cannot spoof a green convergence record or tamper with a saved
        # plan.bin. Explicit Deny always overrides an Allow elsewhere in the same policy.
        Sid    = "DenyStateAndConvergenceWrite"
        Effect = "Deny"
        Action = ["s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/convergence/personal/*",
          "${aws_s3_bucket.data_lake.arn}/tfplan/personal/*",
          "${aws_s3_bucket.data_lake.arn}/tfstate/personal/*",
        ]
      },
      {
        # DEP-13 (T2.44 / Decision 113): deny tfstate READ too -- both ExternalIds (PlatformDev's
        # own and PlatformAdmin's) live in tfstate's assume_role_policy trust documents, so a
        # DEV-container key theft that only reaches PlatformDev must not be able to read them out
        # of state and escalate to PlatformAdmin. ExternalId-based state recovery is admin-tier-only
        # (see terraform/CLAUDE.md).
        Sid      = "DenyStateRead"
        Effect   = "Deny"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/tfstate/personal/*"]
      },
      {
        # T2.18 c2 (PLAN-datalake-read-visibility): GcDebtRatio's storage term comes from a
        # current-versions-only listing, so on this versioned bucket it cannot see the bytes it
        # purports to measure. GetLifecycleConfiguration and GetBucketVersioning are bucket-config
        # reads with no version-level exposure -- no fence needed for either.
        Sid      = "DataLakeBucketConfigRead"
        Effect   = "Allow"
        Action   = ["s3:GetLifecycleConfiguration", "s3:GetBucketVersioning"]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        # s3:ListBucketVersions is BUCKET-level (Resource is the bucket ARN, prefix-scopable only
        # via the s3:prefix condition key) -- distinct IAM action-type from the OBJECT-level
        # GetObjectVersion grant below. The s3:prefix condition is the PRIMARY fence admitting only
        # the two DuckLake data prefixes; the DenyStateAndConvergenceVersionList statement below is
        # defence-in-depth, not the sole guard (a prefix-conditioned Deny cannot fence an unprefixed
        # or shorter-prefix list request).
        Sid      = "DataLakeVersionListRead"
        Effect   = "Allow"
        Action   = ["s3:ListBucketVersions"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "${local.ducklake_prod_data_prefix}/*",
              "${local.ducklake_smoke_data_prefix}/*",
            ]
          }
        }
      },
      {
        # s3:GetObjectVersion is OBJECT-level -- scoped directly to the two DuckLake data object
        # prefixes, never bucket-wide. A bucket-wide grant would reopen the DEP-13
        # ExternalId-in-state escalation path the two Deny statements below exist to close.
        Sid    = "DataLakeObjectVersionRead"
        Effect = "Allow"
        Action = ["s3:GetObjectVersion"]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/${local.ducklake_prod_data_prefix}/*",
          "${aws_s3_bucket.data_lake.arn}/${local.ducklake_smoke_data_prefix}/*",
        ]
      },
      {
        # DEP-13 (T2.18 / PLAN-datalake-read-visibility): OBJECT-level Deny covering the whole
        # version-read verb family -- not just the one verb granted above -- so a later grant of a
        # sibling verb (GetObjectVersionAcl/Tagging/Attributes) cannot silently land outside the
        # fence. Mirrors DenyStateRead's resource shape (bucket.arn/prefix/*), which is what makes
        # this Deny's action family match the OBJECT-level GetObjectVersion Allow above.
        Sid    = "DenyStateAndConvergenceVersionRead"
        Effect = "Deny"
        Action = [
          "s3:GetObjectVersion",
          "s3:GetObjectVersionAcl",
          "s3:GetObjectVersionTagging",
          "s3:GetObjectVersionAttributes",
        ]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/convergence/personal/*",
          "${aws_s3_bucket.data_lake.arn}/tfplan/personal/*",
          "${aws_s3_bucket.data_lake.arn}/tfstate/personal/*",
        ]
      },
      {
        # DEP-13: separate BUCKET-level, s3:prefix-conditioned Deny for s3:ListBucketVersions --
        # an object-prefix Resource shape (bucket.arn/tfstate/personal/*) would be INERT against
        # this bucket-level action, since ListBucketVersions is never evaluated against an object
        # ARN. The Resource here MUST be the bucket ARN, fenced by the same s3:prefix condition key
        # the Allow above uses, mirroring the two-statement Deny pattern DenyStateAndConvergenceWrite
        # already sets for the object-level write actions.
        Sid      = "DenyStateAndConvergenceVersionList"
        Effect   = "Deny"
        Action   = ["s3:ListBucketVersions"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = [
              "convergence/personal/*",
              "tfplan/personal/*",
              "tfstate/personal/*",
            ]
          }
        }
      },
    ]
  })
}

# Runtime grant. Mirrors the github_ci_branch policy (oidc.tf) -- the proven,
# write-capable permission set scoped to this account's actual resources -- so the
# runtime role can do exactly what CI's branch role does (ops portal MERGE writes,
# OPTIMIZE/VACUUM). This is the grant flagged PENDING in terraform/CLAUDE.md.
resource "aws_iam_role_policy" "platform_dev_runtime" {
  name   = "DailyOps"
  role   = aws_iam_role.platform_dev.id
  policy = local.platform_dev_runtime_policy_json

  lifecycle {
    precondition {
      # Decision 156: AWS excludes whitespace from the 10,240 B inline-policy limit, so measure
      # the WHITESPACE-STRIPPED/minified rendering (mirrors terraform/bootstrap's rec-2793 idiom).
      # This is a PER-POLICY backstop, not the per-ROLE aggregate AWS actually enforces -- PlatformDev
      # carries a second inline policy too, so check the role's total headroom (VP steps 12/19 of
      # PLAN-agent-observability-read-axis) before trimming just this document.
      condition     = length(jsonencode(jsondecode(local.platform_dev_runtime_policy_json))) <= 10240
      error_message = "PlatformDev DailyOps inline policy exceeds the 10,240 B IAM inline-policy limit (whitespace-stripped measure, Decision 156). Move a statement to a customer-managed policy or trim grants."
    }
  }
}
