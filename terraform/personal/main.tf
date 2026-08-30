# Personal-account platform infrastructure (isolated root module) -- PLAN-public-migration Phase B.
#
# WHY a separate root module: the work-account root (terraform/) points its DEFAULT aws provider
# at the work account and only ~8 of ~137 resources use the aws.platform alias. Applying that root
# against the personal account would try to CREATE ~120 work-account resources. This module holds
# ALL personal-account infra with its OWN provider + state and is the ONLY root applied post-CD.21.
#
# Provisioning profile is agent_platform_admin (PlatformAdmin) -- creates IAM + OIDC, which the
# permissionless agent_platform (PlatformDev) runtime role cannot. Runtime stays agent_platform.
# The account ID is supplied at apply time via the gitignored terraform.personal.tfvars; it is
# never a committed literal (PLAN Step 11b parameterisation invariant).
# Retired-resource state reconciliation for this root is governed by Decision 178 clause 4 (docs/DECISIONS.md).

terraform {
  # use_lockfile (native S3 state locking, no DynamoDB lock table) requires Terraform 1.10+.
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # Third-party Neon provider for the DuckLake catalog (T2.16b / CD.34). Pinned to an exact
    # published version; checksums committed in .terraform.lock.hcl (supply-chain control). Terraform
    # allows only ONE required_providers block per module, so the Neon pin lives here rather than in
    # neon_ducklake_catalog.tf. Verify the version on the Terraform Registry before bumping.
    neon = {
      source  = "kislerdm/neon"
      version = "0.13.0"
    }
  }
  # S3 backend with native state locking (use_lockfile). The data-lake bucket was bootstrapped
  # under the prior local backend, so the chicken-and-egg that motivated "local" no longer holds.
  # Partial config: bucket/key/region/encrypt come from -backend-config=backend-sandbox.hcl so this
  # block stays account-agnostic and a future backend-production.hcl is a pure config addition.
  # One-time migration: terraform init -migrate-state -backend-config=backend-sandbox.hcl.
  backend "s3" {
    use_lockfile = true
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = "agent-platform"
      Account   = "personal"
      ManagedBy = "Terraform"
      Owner     = var.owner_email
    }
  }
}

# ---------------------------------------------------------------------------
# Data-lake S3 bucket (platform object storage: tfstate, tfplan, convergence
# records, provider mirror, logs)
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "data_lake" {
  bucket = "agent-platform-data-lake"

  tags = {
    Name    = "Platform Data Lake"
    Purpose = "Platform object storage (tfstate, plans, convergence records, logs)"
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "data_lake_https_only" {
  bucket = aws_s3_bucket.data_lake.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyNonHTTPS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# DynamoDB atomic counters (rec/decision ID allocation, Decision 36/37: SSO, no IAM users)
# Seeded ONCE at greenfield ABOVE the work-account max + 1000 margin (Decision 50 collision guard;
# work maxes 2026-05-28: recommendations=944, decisions=81 -> floors 1944/1081). The counter VALUES
# are app-owned runtime state (atomic UpdateItem ADD), deliberately NOT Terraform-managed -- see the
# note below the table resource.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "counters" {
  name         = "agent-platform-counters"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "counter_name"

  attribute {
    name = "counter_name"
    type = "S"
  }

  tags = {
    Purpose = "Atomic sequential counter allocation for agents and executor"
  }
}

# Counter seed items are intentionally NOT Terraform-managed (removed during the PLAN-public-migration
# S3-backend bootstrap, 2026-05-30). aws_dynamodb_table_item manages a row's VALUE -- but current_value
# is mutable runtime state the ops portal increments via atomic UpdateItem ADD on every ID allocation.
# Terraform must not own a value another system mutates: state here is ephemeral (CD applies run from
# fresh containers), so a fresh apply would treat the seed as "to create" and PutItem the stale floor
# over the live counter, resetting it and reusing already-issued IDs. The greenfield seed has done its
# job (counters are live, well past the 1944/1081 floors). The table stays Terraform-managed; the rows
# are app-owned. A NEW environment seeds its floor once out-of-band (e.g. `aws dynamodb put-item`)
# during that environment's bootstrap, not via Terraform.
