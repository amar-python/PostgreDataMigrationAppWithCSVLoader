################################################################################
# main.tf — GitHub Repository Management via Terraform
# Manages all repositories for github.com/amar-python
################################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }

  # Optional: store state remotely so teammates share the same state.
  # Uncomment and fill in if you have an Azure Storage Account.
  # backend "azurerm" {
  #   resource_group_name  = "rg-terraform-state"
  #   storage_account_name = "stterraformstate"
  #   container_name       = "tfstate"
  #   key                  = "github-repos.tfstate"
  # }
}

################################################################################
# Provider
################################################################################

provider "github" {
  owner = var.github_owner   # your GitHub username
  token = var.github_token   # Personal Access Token (set via env var)
}

################################################################################
# Repositories — one resource block per repo
################################################################################

# ── PostgreDataMigrationApp ───────────────────────────────────────────────────
resource "github_repository" "postgres_data_migration_app" {
  name        = "PostgreDataMigrationApp"
  description = var.repos["PostgreDataMigrationApp"].description
  visibility  = var.repos["PostgreDataMigrationApp"].visibility

  has_issues      = true
  has_projects    = true
  has_wiki        = false
  has_downloads   = true
  auto_init       = false

  # Prevent accidental deletion via terraform destroy
  lifecycle {
    prevent_destroy = true
  }
}

# Apply topics to PostgreDataMigrationApp
resource "github_repository_topics" "postgres_data_migration_app" {
  repository = github_repository.postgres_data_migration_app.name
  topics     = var.repos["PostgreDataMigrationApp"].topics
}

# ── Add more repositories below by copying the block above ───────────────────
# Example — uncomment and customise to add a second repo:
#
# resource "github_repository" "my_next_project" {
#   name        = "MyNextProject"
#   description = var.repos["MyNextProject"].description
#   visibility  = var.repos["MyNextProject"].visibility
#   has_issues  = true
#   auto_init   = false
#   lifecycle { prevent_destroy = true }
# }
#
# resource "github_repository_topics" "my_next_project" {
#   repository = github_repository.my_next_project.name
#   topics     = var.repos["MyNextProject"].topics
# }
