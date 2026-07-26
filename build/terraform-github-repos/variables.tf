################################################################################
# variables.tf — All configurable values defined here
################################################################################

# ── GitHub credentials ────────────────────────────────────────────────────────

variable "github_owner" {
  description = "GitHub username or organisation name"
  type        = string
  default     = "amar-python"
}

variable "github_token" {
  description = <<EOT
GitHub Personal Access Token (PAT).
Required scopes: repo (full control of private repositories).
Never hard-code this value — pass it via:
  export TF_VAR_github_token="ghp_yourtoken"
EOT
  type      = string
  sensitive = true  # prevents the token appearing in logs or plan output
}

# ── Repository definitions ────────────────────────────────────────────────────
# Add a new entry here to register a new repository.
# All other Terraform code will pick it up automatically.

variable "repos" {
  description = "Map of repository names to their configuration"
  type = map(object({
    description = string
    visibility  = string       # "public" or "private"
    topics      = list(string)
  }))

  default = {

    "PostgreDataMigrationApp" = {
      description = "Parameterised PostgreSQL framework for T&E programme management — VCRM, TEMP, test execution, defect reporting, multi-environment deployment, 85-assertion SQL test suite"
      visibility  = "public"
      topics      = [
        "postgresql",
        "sql",
        "test-evaluation",
        "vcrm",
        "database",
        "devops",
        "idempotent",
        "multi-environment"
      ]
    }

    # ── Add more repos here ──────────────────────────────────────────────────
    # "MyNextRepo" = {
    #   description = "Description of your next project"
    #   visibility  = "public"
    #   topics      = ["python", "automation"]
    # }

  }
}
