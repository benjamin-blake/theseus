variable "github_token" {
  description = "GitHub token, supplied at run time and never committed: the PR-time plan's App installation token, or the classic admin PAT (repo, admin:repo_hook, read:org) as rollback until it is revoked. Leave unset when github_app_auth is true."
  type        = string
  sensitive   = true
  default     = null

  validation {
    condition     = (var.github_token != null) != var.github_app_auth
    error_message = "Set exactly one credential: TF_VAR_github_token, or TF_VAR_github_app_auth=true with GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID and GITHUB_APP_PEM_FILE in the environment."
  }

  validation {
    condition     = var.github_token != ""
    error_message = "github_token is empty; an empty token makes the provider fall back to anonymous access."
  }
}

variable "github_app_auth" {
  description = "true: authenticate as the org-owned terraform/github apply App from the GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID and GITHUB_APP_PEM_FILE environment variables, so its key never enters a variable or a saved plan (rec-4355). false: use github_token."
  type        = bool
  default     = false
}

variable "github_owner" {
  description = "GitHub organisation or user that owns the repository."
  type        = string
  default     = "otl-labs"
}

variable "repository_name" {
  description = "GitHub repository name managed by this module."
  type        = string
  default     = "ontheloop"
}

variable "main_protection_ruleset_id" {
  description = "Numeric id of the main-protection ruleset, used only by its import block. Re-read it from the API after a transfer: rulesets are not documented to carry over."
  type        = number
  default     = 17117072
}

variable "admin_bypass_actor_id" {
  description = "GitHub actor ID granted ruleset bypass. Use 5 for the built-in Repository Admin role (anyone with admin permission). Supplied at apply time."
  type        = number
  default     = 5
}

variable "gated_apply_reviewer_user_ids" {
  description = "List of GitHub numeric user IDs required to approve the tf-gated-apply Environment gate before the gated-apply job may execute. Supplied at apply time -- never committed with a literal default. Resolve before applying: GET /user with the reviewer's PAT (terraform/github/CLAUDE.md runbook step 2) or the GitHub MCP get_me tool."
  type        = list(number)

  validation {
    condition     = length(var.gated_apply_reviewer_user_ids) > 0
    error_message = "gated_apply_reviewer_user_ids must contain at least one GitHub numeric user id; an empty list silently disables the tf-gated-apply required-reviewer gate."
  }
}
