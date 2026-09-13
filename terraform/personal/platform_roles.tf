# Platform agent-auth roles for the personal account.
#
# Codifies the previously out-of-band PlatformDev role (see terraform/CLAUDE.md
# "Out-of-band IAM grants") and closes its PENDING runtime grant. SUPERSEDES the
# work-root terraform/lambda_tooling_iam.tf definitions for the personal account;
# that root is retained per CD.21 but is no longer applied.
#
# Scope: PlatformDev (runtime) and PlatformAdmin (provisioning). PlatformAdmin is the
# higher-blast-radius role used only from the rarely-spun-up admin environment; it is now
# codified here (AdminOps + PlatformDataLakeProvisioning) -- see its own IMPORT BEFORE APPLY
# banner below. Both roles pre-exist (breakglass-created) and MUST be imported before apply.
#
# ---------------------------------------------------------------------------
# IMPORT BEFORE APPLY
# ---------------------------------------------------------------------------
# The PlatformDev role already exists in the account (console/breakglass-created).
# Import it so `terraform apply` MODIFIES it rather than trying to re-create it:
#
#   terraform -chdir=terraform/personal import aws_iam_role.platform_dev PlatformDev
#
# SAFETY -- run `terraform plan` and confirm BEFORE applying:
#   - The trust policy (assume_role_policy) shows NO change. If it does, your
#     agent_service_account_user_name or platform_dev_external_id differs from the
#     supplied values -- fix the variable. Do NOT apply a trust-policy change that
#     could lock your agent_static key out of the assume-role chain.
#   - The expected diff is exactly: max_session_duration 3600 -> 36000, plus the
#     ADD of the DailyOps inline policy below (the role is currently permissionless).
#
# platform_dev_external_id is required (no default) and must live in the gitignored
# terraform.personal.tfvars, never in a committed file.

resource "aws_iam_role" "platform_dev" {
  name                 = "PlatformDev"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
  # DEP-02 / Decision 144 (T2.48): PlatformDev carries the MANDATORY boundary (broad-but-bounded
  # runtime identity). PlatformAdmin is DELIBERATELY EXCLUDED (control identity that must remain able
  # to amend the boundary; attaching DenyBoundaryPolicyModification to it would wedge break-glass --
  # Decision 144 pt.3 / Decision 113 two-principal split). PlatformDev's own DEP-13 Denies
  # (DenyStateAndConvergenceWrite / DenyStateRead, slice B) are unaffected -- a boundary is a ceiling
  # and an identity Deny always wins. PlatformDev bounding caps its FUTURE runtime to the boundary's
  # DataPlaneAllow service set until a boundary amendment widens it (design note, Decision 144 pt.7).
  max_session_duration = 36000 # 10h; matches duration_seconds in ~/.aws/config so CC-web sessions run unattended
  description          = "Daily agent ops (runtime): S3 read/write on the data lake, DynamoDB counters, DuckLake verb invokes"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::${var.account_id}:user/${var.agent_service_account_user_name}"
        }
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.platform_dev_external_id
          }
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# PlatformAdmin -- provisioning role (IAM import + admin Lambda/secrets + data-lake provisioning)
# ---------------------------------------------------------------------------
# Codifies the previously out-of-band PlatformAdmin role and its two inline policies
# (AdminOps + PlatformDataLakeProvisioning, see terraform/CLAUDE.md "Out-of-band IAM grants").
# Personal-module idiom: default provider, var.account_id, var.agent_service_account_user_name --
# NOT the work-root aws.platform / var.platform_account_id / aws_iam_user.agent_service_account.
#
# IMPORT BEFORE APPLY
#   terraform -chdir=terraform/personal import aws_iam_role.platform_admin PlatformAdmin
#
# SAFETY -- run `terraform plan` and confirm BEFORE applying:
#   - The trust policy (assume_role_policy) MUST show NO change. PlatformAdmin is the role this
#     very apply assumes (profile agent_platform_admin); a trust-policy diff risks locking the
#     agent_static/breakglass principal out of the assume-role chain. If the trust shows a diff,
#     STOP and reconcile platform_admin_external_id / agent_service_account_user_name against the
#     live role -- do NOT apply.
#   - max_session_duration should already be 3600 on the live role (no change expected).
#   - The expected diff is exactly the ADD of the AdminOps + PlatformDataLakeProvisioning inline
#     policies (the role's inline policies are not imported, only the role).
#
# platform_admin_external_id is required (no default); it lives in the gitignored
# terraform.personal.tfvars, never in a committed file.

resource "aws_iam_role" "platform_admin" {
  name                 = "PlatformAdmin"
  max_session_duration = 3600 # AWS IAM minimum; admin sessions kept short (limit further via duration_seconds in ~/.aws/config)
  description          = "Admin ops (provisioning): iam:* for import, admin Lambda management, secrets, and data-lake provisioning"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::${var.account_id}:user/${var.agent_service_account_user_name}"
        }
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.platform_admin_external_id
          }
        }
      }
    ]
  })
}
