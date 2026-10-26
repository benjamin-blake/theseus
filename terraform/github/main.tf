# Isolated GitHub-settings root module (T2.12 / CD.20).
#
# WHY isolated: terraform/personal/ auto-applies from GitHub Actions via OIDC; the
# terraform_apply_guard.py is AWS-IAM-only and cannot inspect github_* resource diffs.
# A branch-protection change on that auto-apply path would apply ungated and could lock
# out the push-to-main flow the workflow depends on. This module is human-gated LOCAL
# apply only (see CLAUDE.md). NEVER add terraform/github/** to any apply-workflow path.
#
# Apply: see terraform/github/CLAUDE.md; init with the region from config/aws-region (rec-4067):
# terraform -chdir=terraform/github init -backend-config="region=$(tr -d '[:space:]' < config/aws-region)".
# Credentials, exactly one lane per run (variables.tf validates it): TF_VAR_github_app_auth=true with
# the apply App's GITHUB_APP_* environment variables (rec-4355), or TF_VAR_github_token (the PR-time
# plan's App token; the classic admin PAT as rollback until it is revoked).

terraform {
  required_version = ">= 1.10"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
  backend "s3" {
    bucket       = "agent-platform-data-lake"
    key          = "tfstate/github/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "github" {
  owner = var.github_owner
  token = var.github_token

  # Empty on purpose: the provider reads the App id, installation id and private key from the
  # GITHUB_APP_* environment variables, so key material never enters a variable or a saved plan.
  dynamic "app_auth" {
    for_each = var.github_app_auth ? [1] : []
    content {}
  }
}
