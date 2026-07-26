# main.tf - Azure Dev environment for PostgreDataMigrationApp
#
# Provisions:
#   - Resource Group
#   - Azure Container Registry (ACR) for the migration runner image
#   - Storage Account + Azure Files share (PG data persistence)
#   - Key Vault (PG password)
#   - Log Analytics workspace (Container Apps requires it)
#   - Container Apps Environment + a PG container app (single replica, mounted volume)
#   - User-assigned managed identity (ACI -> ACR pull, KV secret read)
#
# The migration runner itself (ACI) is NOT provisioned by Terraform - it's launched
# per-run by the GitHub Actions workflow. That keeps cost at near-zero between runs.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
}

# --- Inputs ---------------------------------------------------------------

locals {
  # Resource suffix avoids global-name collisions on ACR/storage/KV
  suffix = random_string.suffix.result
  tags = {
    project     = "PostgreDataMigrationApp"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

# --- Resource Group -------------------------------------------------------

resource "azurerm_resource_group" "rg" {
  name     = "rg-te-${var.environment}-${local.suffix}"
  location = var.location
  tags     = local.tags
}

# --- Azure Container Registry --------------------------------------------

resource "azurerm_container_registry" "acr" {
  name                = "acrte${var.environment}${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true # Required for ACI image pull without managed identity
  tags                = local.tags
}

# --- Storage for PG persistent volume ------------------------------------

resource "azurerm_storage_account" "pg_storage" {
  name                     = "stpgte${var.environment}${local.suffix}"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.tags
}

resource "azurerm_storage_share" "pg_data" {
  name                 = "pgdata"
  storage_account_id   = azurerm_storage_account.pg_storage.id
  quota                = 50 # GB
}

# --- Storage for CSV input + run reports ---------------------------------

resource "azurerm_storage_container" "csv_input" {
  name                  = "csv-input"
  storage_account_id    = azurerm_storage_account.pg_storage.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "run_reports" {
  name                  = "run-reports"
  storage_account_id    = azurerm_storage_account.pg_storage.id
  container_access_type = "private"
}

# --- Key Vault for PG password -------------------------------------------

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "kv" {
  name                       = "kv-te-${var.environment}-${local.suffix}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  rbac_authorization_enabled = true
  tags                       = local.tags
}

resource "random_password" "pg_password" {
  length      = 24
  special     = true
  min_lower   = 2
  min_upper   = 2
  min_numeric = 2
  override_special = "!@#$%^&*()-_=+"
}

resource "azurerm_role_assignment" "kv_admin_terraform" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "pg_password" {
  name         = "pg-postgres-password"
  value        = random_password.pg_password.result
  key_vault_id = azurerm_key_vault.kv.id

  depends_on = [azurerm_role_assignment.kv_admin_terraform]
}

# --- Log Analytics (required by Container Apps) --------------------------

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "law-te-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

# --- Container Apps Environment ------------------------------------------

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-te-${var.environment}-${local.suffix}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  tags                       = local.tags
}

resource "azurerm_container_app_environment_storage" "pg_data_mount" {
  name                         = "pgdata"
  container_app_environment_id = azurerm_container_app_environment.env.id
  account_name                 = azurerm_storage_account.pg_storage.name
  share_name                   = azurerm_storage_share.pg_data.name
  access_key                   = azurerm_storage_account.pg_storage.primary_access_key
  access_mode                  = "ReadWrite"
}

# --- PostgreSQL Container App --------------------------------------------
#
# WARNING: Container Apps with persistent volumes is acceptable for Dev only.
# For Prod, migrate to Azure Database for PostgreSQL Flexible Server.

resource "azurerm_container_app" "pg" {
  name                         = "ca-pg-${var.environment}-${local.suffix}"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  tags                         = local.tags

  ingress {
    external_enabled           = false # Internal only - migration runner connects on the env's internal network
    target_port                = 5432
    exposed_port               = 5432
    transport                  = "tcp"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    volume {
      name         = "pgdata"
      storage_name = azurerm_container_app_environment_storage.pg_data_mount.name
      storage_type = "AzureFile"
    }

    container {
      name   = "postgres"
      image  = "postgres:16-alpine"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "POSTGRES_USER"
        value = "postgres"
      }

      env {
        name        = "POSTGRES_PASSWORD"
        secret_name = "pg-password"
      }

      env {
        name  = "POSTGRES_DB"
        value = "te_${var.environment}"
      }

      env {
        name  = "PGDATA"
        value = "/var/lib/postgresql/data/pgdata"
      }

      volume_mounts {
        name = "pgdata"
        path = "/var/lib/postgresql/data"
      }
    }
  }

  secret {
    name  = "pg-password"
    value = random_password.pg_password.result
  }
}

# --- User-assigned managed identity for the ACI runner -------------------

resource "azurerm_user_assigned_identity" "runner" {
  name                = "id-runner-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "runner_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.runner.principal_id
}

resource "azurerm_role_assignment" "runner_kv_secrets" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.runner.principal_id
}

resource "azurerm_role_assignment" "runner_storage_contributor" {
  scope                = azurerm_storage_account.pg_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.runner.principal_id
}
