# PlatformAdmin's detector-management grant for the platform-security-* IAM-change detector
# (rec-4044, Decision 202). A customer-managed policy, not an AdminOps inline statement:
# PlatformAdmin's inline aggregate has ~2.2 KB of its 10,240 B per-role headroom left (Decision 156
# managed-policy remedy). The role is referenced by its literal name because this root does not
# declare PlatformAdmin (PLAN-platform-iam-bootstrap-adopt moves it here later).
#
# Decision 202 clause 2: PlatformAdmin -- and only PlatformAdmin -- holds exactly six
# trail-management verbs on the ONE platform-security trail. cloudtrail:StopLogging,
# cloudtrail:DeleteTrail and cloudtrail:* are banned everywhere (TestCloudTrailWriteGrantScoped).
# No s3:DeleteBucket / s3:DeleteBucketPolicy / logs:DeleteLogGroup: destroying the detector is
# break-glass only. CloudWatch alarm verbs are not re-granted (AdminOps' CloudWatchAlarmManagement
# already covers alarm:*).
locals {
  platform_security_admin_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PlatformSecurityTrailManage"
        Effect = "Allow"
        Action = [
          "cloudtrail:CreateTrail",
          "cloudtrail:UpdateTrail",
          "cloudtrail:PutEventSelectors",
          "cloudtrail:StartLogging",
          "cloudtrail:AddTags",
          "cloudtrail:RemoveTags",
        ]
        Resource = "arn:aws:cloudtrail:${var.aws_region}:${var.account_id}:trail/platform-security-trail"
      },
      {
        # Refresh reads the aws_cloudtrail resource issues every plan, plus DescribeTrails for the
        # pre-apply "no trail exists" check. DescribeTrails supports no resource scoping.
        Sid    = "PlatformSecurityTrailRead"
        Effect = "Allow"
        Action = [
          "cloudtrail:GetTrail",
          "cloudtrail:GetTrailStatus",
          "cloudtrail:DescribeTrails",
          "cloudtrail:GetEventSelectors",
          "cloudtrail:GetInsightSelectors",
          "cloudtrail:ListTags",
        ]
        Resource = "*"
      },
      {
        # Mirrors terraform/personal/platform_admin_data_policies.tf CatalogDrBucketManage verb for
        # verb, plus PutBucketOwnershipControls (BucketOwnerEnforced). Get* entries are the
        # aws_s3_bucket refresh reads; without them every plan AccessDenies.
        Sid    = "PlatformSecurityTrailBucketManage"
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
          "s3:PutBucketOwnershipControls",
          "s3:GetAccelerateConfiguration",
          "s3:GetBucketRequestPayment",
          "s3:GetBucketLogging",
          "s3:GetReplicationConfiguration",
          "s3:GetBucketObjectLockConfiguration",
          "s3:GetBucketCORS",
          "s3:GetBucketWebsite",
        ]
        Resource = "arn:aws:s3:::platform-security-trail-${var.account_id}-${var.aws_region}"
      },
      {
        # The read verbs make the Logs Insights query named in every alarm email runnable by
        # PlatformAdmin, and let the live-proof evidence step read eventIDs from the trail's group.
        Sid    = "PlatformSecurityLogGroupManage"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:PutRetentionPolicy",
          "logs:TagResource",
          "logs:TagLogGroup",
          "logs:ListTagsForResource",
          "logs:ListTagsLogGroup",
          "logs:PutMetricFilter",
          "logs:DeleteMetricFilter",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:StartQuery",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:platform-security-*"
      },
      {
        # None of these four supports resource-level scoping.
        Sid    = "PlatformSecurityLogsRead"
        Effect = "Allow"
        Action = [
          "logs:DescribeMetricFilters",
          "logs:TestMetricFilter",
          "logs:GetQueryResults",
          "logs:StopQuery",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_policy" "platform_security_admin" {
  name        = "platform-security-detector-admin"
  description = "PlatformAdmin management of the platform-security IAM-change detector (Decision 202)"
  policy      = local.platform_security_admin_policy_json

  lifecycle {
    precondition {
      # Managed-policy hard limit is 6,144 B; a LimitExceeded is invisible to plan, surfaces at apply.
      condition     = length(jsonencode(jsondecode(local.platform_security_admin_policy_json))) <= 6144
      error_message = "platform-security-detector-admin policy exceeds the 6,144 B managed-policy limit."
    }
  }
}

resource "aws_iam_role_policy_attachment" "platform_security_admin" {
  role       = "PlatformAdmin"
  policy_arn = aws_iam_policy.platform_security_admin.arn
}
