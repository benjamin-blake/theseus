# PlatformAdmin AdminOps inline policy (Decision 128/166 decomposition of platform_roles.tf, T2.48).
#
# Split out of platform_roles.tf as a pure move -- no statement added, removed, or reordered
# relative to origin/main, other than the T2.48 observability-read addition below and the
# byte-limit precondition hoist (Decision 156) that addition requires. platform_roles.tf retains
# both aws_iam_role resources; see that file for the PlatformAdmin IMPORT BEFORE APPLY banner.
#
# rec-2793 idiom (DEP-01 anti-recurrence, mirrored from
# terraform/bootstrap/github_ci_apply_policy.tf): hoisted out of the aws_iam_role_policy
# resource's inline `policy = jsonencode({...})` attribute so the lifecycle precondition below
# can self-reference the rendered JSON (a precondition cannot reference `self` -- that is
# postcondition-only).
locals {
  platform_admin_ops_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "IAMFull"
        Effect   = "Allow"
        Action   = "iam:*"
        Resource = "*"
      },
      {
        # Full create+manage lifecycle so AdminOps can provision NEW Lambda infrastructure from
        # terraform/personal (T2.17 ducklake_writer/reader are the first Lambdas created via this
        # module): function + layer-version + function-URL create/read/update/delete + tagging. The
        # prior set was deploy-only (UpdateFunctionCode/Invoke/Get) and could not create functions,
        # publish layer versions, or create Function URLs.
        Sid    = "LambdaAdminManagement"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:GetRuntimeManagementConfig",
          "lambda:GetPolicy",
          # Resource-based-policy lifecycle: T2.18 ducklake_maintenance is the first module Lambda
          # invoked by EventBridge, which requires an AddPermission grant for principal
          # events.amazonaws.com. T2.17 writer/reader used Function URLs (AWS_IAM) only, so the
          # resource-policy actions were never needed. GetPolicy (above) was already present.
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:ListFunctions",
          "lambda:ListVersionsByFunction",
          "lambda:InvokeFunction",
          "lambda:InvokeFunctionUrl",
          "lambda:CreateFunctionUrlConfig",
          "lambda:GetFunctionUrlConfig",
          "lambda:UpdateFunctionUrlConfig",
          "lambda:DeleteFunctionUrlConfig",
          "lambda:PublishLayerVersion",
          "lambda:GetLayerVersion",
          "lambda:DeleteLayerVersion",
          "lambda:ListLayerVersions",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:ListTags",
          # Reserved-concurrency lifecycle: T2.18 ducklake_maintenance is the first Lambda in this
          # module to pin reserved_concurrent_executions (singleton, Decision 81 clause 6). The
          # prior set (T2.17 writer/reader) set no concurrency, so these were never needed.
          "lambda:PutFunctionConcurrency",
          "lambda:DeleteFunctionConcurrency",
          "lambda:GetFunctionConcurrency",
        ]
        Resource = "*"
      },
      {
        # EventBridge schedule-rule lifecycle: T2.18 ducklake_maintenance is the first module
        # resource to use EventBridge (two scheduled cadences: daily merge + weekly GC). Scoped to
        # the agent-platform rule namespace. PutRule with inline tags requires events:TagResource.
        Sid    = "EventBridgeScheduleManagement"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:EnableRule",
          "events:DisableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:TagResource",
          "events:UntagResource",
          "events:ListTagsForResource",
        ]
        Resource = "arn:aws:events:${var.aws_region}:${var.account_id}:rule/agent-platform-*"
      },
      {
        # CloudWatch metric-alarm lifecycle: T2.18 ducklake_maintenance is the first module resource
        # to create an alarm (the circuit-breaker alarm on the DuckLakeMaintenance namespace).
        # PutMetricAlarm/DeleteAlarms support alarm-ARN scoping; DescribeAlarms is a list op that
        # does not support resource scoping, so it sits on "*".
        Sid    = "CloudWatchAlarmManagement"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource",
          "cloudwatch:ListTagsForResource",
        ]
        Resource = "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:*"
      },
      {
        Sid      = "CloudWatchAlarmDescribe"
        Effect   = "Allow"
        Action   = ["cloudwatch:DescribeAlarms"]
        Resource = "*"
      },
      {
        # CloudWatch Logs lifecycle for the Lambda log groups this module creates
        # (/aws/lambda/agent-platform-*). DescribeLogGroups does not support resource scoping (it is
        # a list operation), so it sits on "*"; the mutating actions are scoped to the agent-platform
        # Lambda log-group prefix.
        Sid    = "LambdaLogGroupManagement"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsForResource",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
          "logs:ListTagsLogGroup",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/agent-platform-*"
      },
      {
        Sid      = "LambdaLogGroupDescribe"
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "*"
      },
      {
        # Read access to the Lambda log groups + their streams so AdminOps can diagnose runtime
        # failures (post-deploy smoke-gate RCA) without escalating to break-glass.
        Sid    = "LambdaLogGroupRead"
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
        # Tag/Untag/Update/GetResourcePolicy complete the secret-management set so AdminOps can fully
        # manage TAGGED secrets it creates (e.g. the DuckLake Neon DSN). Creating a secret with tags
        # requires secretsmanager:TagResource even when the tags are passed inline to CreateSecret.
        Sid    = "SecretsManagerAdmin"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:CreateSecret",
          "secretsmanager:UpdateSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource",
        ]
        Resource = "*"
      },
      {
        # Service Quotas: raise the account Lambda concurrent-executions ceiling so
        # ducklake_maintenance can reserve 1 (singleton, Decision 81 clause 6) without breaching
        # AWS's 10-unreserved floor. The unverified-account default (10) leaves no room to reserve.
        # Service Quotas actions do not support resource-level scoping, so they sit on "*"; read
        # actions are needed to confirm the new value applied before re-running PutFunctionConcurrency.
        Sid    = "ServiceQuotasManagement"
        Effect = "Allow"
        Action = [
          "servicequotas:GetServiceQuota",
          "servicequotas:GetAWSDefaultServiceQuota",
          "servicequotas:ListServiceQuotas",
          "servicequotas:RequestServiceQuotaIncrease",
          "servicequotas:GetRequestedServiceQuotaChange",
          "servicequotas:ListRequestedServiceQuotaChangeHistory",
          "servicequotas:ListRequestedServiceQuotaChangeHistoryByQuota",
        ]
        Resource = "*"
      },
      {
        # SSM Parameter Store lifecycle for the DuckLake endpoint-discovery parameters
        # (/agent-platform/ducklake/{reader,writer}_url, T2.19 / Decision 81 cl.7). PlatformDev reads
        # them at runtime (DuckLakeEndpointDiscovery, below); AdminOps must create + tag + manage them
        # at apply time. PutParameter with inline tags requires ssm:AddTagsToResource; the read actions
        # back the AWS provider's plan-time GetParameter + ListTagsForResource refresh. Scoped to the
        # agent-platform parameter namespace -- all listed actions support parameter-ARN scoping.
        Sid    = "SSMParameterProvisioning"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:DeleteParameter",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource",
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/agent-platform/*"
      },
      {
        # ssm:DescribeParameters is the list/metadata API the AWS provider issues during the
        # aws_ssm_parameter create read-back and on every plan-time refresh. Like other AWS list
        # operations (see LambdaLogGroupDescribe / CloudWatchAlarmDescribe above) it does NOT support
        # resource-level scoping, so it must sit on "*". Without it, PutParameter succeeds but the
        # provider's read-back fails with AccessDenied on ssm:DescribeParameters.
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
      {
        # T2.48 (rec-3763): CloudWatch metric reads, CloudTrail event lookup, and S3 bucket listing
        # for alarm triage and billed-storage measurement from the platform itself. None of these six
        # actions supports resource-level scoping (they are all account-wide list/query APIs), so
        # each sits on "*", mirroring the CloudWatchAlarmDescribe / LambdaLogGroupDescribe /
        # SSMDescribeParameters idiom above. Read-only: this repo's terraform grants no cloudtrail
        # mutating verb outside the Decision 202 PlatformSecurityTrailManage grant (rec-2906 is
        # explicitly read-only scope).
        Sid    = "ObservabilityMetricAndTrailRead"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:GetMetricData",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAlarmsForMetric",
          "cloudtrail:LookupEvents",
          "s3:ListAllMyBuckets",
        ]
        Resource = "*"
      },
      {
        # T2.48 (rec-3763): alarm-history read at the SAME Resource as CloudWatchAlarmManagement
        # above -- NOT an agent-platform-* prefix, which would be present-but-inert (measured
        # 2026-09-13: zero live alarms carry that prefix, all four are ducklake-*, the rec-2882 shape).
        Sid      = "CloudWatchAlarmHistoryRead"
        Effect   = "Allow"
        Action   = ["cloudwatch:DescribeAlarmHistory"]
        Resource = "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:*"
      },
      {
        # T2.48 (rec-2906's S3 half, Lever A / Decision 129 pt1): bucket inventory read for
        # billed-storage measurement, expressed at the account-scoped agent-platform-* prefix rather
        # than an enumerated bucket list.
        Sid      = "S3BucketInventoryRead"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:ListBucketVersions"]
        Resource = "arn:aws:s3:::agent-platform-*"
      },
    ]
  })
}

# AdminOps: identity admin (iam:*) + admin Lambda management + secrets. Policy bodies mirror
# terraform/lambda_tooling_iam.tf (work-root, no longer applied); idiom is personal-module.
resource "aws_iam_role_policy" "platform_admin_ops" {
  name   = "AdminOps"
  role   = aws_iam_role.platform_admin.id
  policy = local.platform_admin_ops_policy_json

  lifecycle {
    precondition {
      # Decision 156: AWS excludes whitespace from the 10,240 B inline-policy limit, so measure
      # the WHITESPACE-STRIPPED/minified rendering (mirrors terraform/bootstrap's rec-2793 idiom).
      # This is a PER-POLICY backstop, not the per-ROLE aggregate AWS actually enforces --
      # PlatformAdmin carries FOUR inline policies aggregating toward the same per-role 10,240 B
      # ceiling, so check the role's total headroom (VP steps 12/19 of
      # PLAN-agent-observability-read-axis) before trimming just this document.
      condition     = length(jsonencode(jsondecode(local.platform_admin_ops_policy_json))) <= 10240
      error_message = "PlatformAdmin AdminOps inline policy exceeds the 10,240 B IAM inline-policy limit (whitespace-stripped measure, Decision 156). Move a statement to a customer-managed policy or trim grants."
    }
  }
}
