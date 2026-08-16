# main.tf - Azure Staging environment for PostgreDataMigrationApp
#
# Same architecture tier as Prod (infra/terraform-prod/main.tf) — staging
# exists to validate against prod-like infra before a real prod release, so
# it deliberately does NOT reuse Dev's cheaper Container Apps Postgres:
#   - PG is Azure Database for PostgreSQL Flexible Server (managed)
#   - VNet + delegated subnets so PG and Container Apps are private
#   - Private endpoints for ACR (Premium SKU) and Key Vault
#   - Container Apps Job for managed scheduling (not ACI per-run)
#   - HA optional (ZoneRedundant), backups with PITR + optional geo-redundancy
#   - Diagnostic settings on PG, KV, ACR streaming into Log Analytics
#
# Differences vs Prod: separate resource group/VNet/state file, distinct
# VNet CIDR (10.41.0.0/20 vs Prod's 10.40.0.0/20) so the two never collide if
# ever peered, and defaults sized down where the variable descriptions call
# it out (see variables.tf) — override further via terraform.tfvars.
#
# Cost estimate (australiaeast, defaults): see infra/terraform-prod/main.tf's
# header — same shape, same order of magnitude (~AUD 285-385/mo).

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

  # Staging state MUST be in remote storage, same as Prod. Uncomment after
  # creating the state storage account — follow docs/PROD_DEPLOY.md's
  # "One-time setup" > "1. Create the Terraform state storage" verbatim,
  # substituting "staging" for "prod" (bucket name, key, etc.).
  #
  # backend "azurerm" {
  #   resource_group_name  = "rg-tfstate"
  #   storage_account_name = "sttfstatestagingXXXXXX"  # from the one-time setup script
  #   container_name       = "tfstate"
  #   key                  = "te-staging.tfstate"
  # }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false # Staging: never purge by accident
      recover_soft_deleted_key_vaults = true
    }
  }
}

locals {
  suffix = random_string.suffix.result
  tags = {
    project     = "PostgreDataMigrationApp"
    environment = "staging"
    managed_by  = "terraform"
    cost_center = var.cost_center
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

data "azurerm_client_config" "current" {}

# --- Resource Group -------------------------------------------------------

resource "azurerm_resource_group" "rg" {
  name     = "rg-te-staging-${local.suffix}"
  location = var.location
  tags     = local.tags
}

# --- VNet + subnets -------------------------------------------------------

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-te-staging-${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "pg" {
  name                 = "snet-pg"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 4, 0)] # /20 -> /24 chunk 0

  delegation {
    name = "pg-delegation"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }

  service_endpoints = ["Microsoft.Storage"]
}

resource "azurerm_subnet" "cae" {
  name                 = "snet-cae"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 4, 1)] # /24 chunk 1

  delegation {
    name = "cae-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "endpoints" {
  name                              = "snet-endpoints"
  resource_group_name               = azurerm_resource_group.rg.name
  virtual_network_name              = azurerm_virtual_network.vnet.name
  address_prefixes                  = [cidrsubnet(var.vnet_cidr, 4, 2)] # /24 chunk 2
  private_endpoint_network_policies = "Disabled"
}

# --- Private DNS zones for private endpoints ----------------------------

resource "azurerm_private_dns_zone" "pg" {
  name                = "te-staging-${local.suffix}.private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "pg" {
  name                  = "link-pg"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.pg.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

resource "azurerm_private_dns_zone" "acr" {
  name                = "privatelink.azurecr.io"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  name                  = "link-acr"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.acr.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

resource "azurerm_private_dns_zone" "kv" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "kv" {
  name                  = "link-kv"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.kv.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

# --- Key Vault (Premium, purge-protected) --------------------------------

resource "azurerm_key_vault" "kv" {
  name                          = "kv-te-staging-${local.suffix}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "premium"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  enable_rbac_authorization     = true
  public_network_access_enabled = true # temporarily enabled so Terraform can seed the secret; flip to false after bootstrap
  tags                          = local.tags
}

resource "azurerm_role_assignment" "kv_admin_terraform" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_private_endpoint" "kv" {
  name                = "pe-kv-staging"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-kv"
    private_connection_resource_id = azurerm_key_vault.kv.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.kv.id]
  }
}

resource "random_password" "pg_password" {
  length           = 32
  special          = true
  min_lower        = 4
  min_upper        = 4
  min_numeric      = 4
  override_special = "!@#$%^&*()-_=+"
}

resource "azurerm_key_vault_secret" "pg_password" {
  name         = "pg-postgres-password"
  value        = random_password.pg_password.result
  key_vault_id = azurerm_key_vault.kv.id

  depends_on = [azurerm_role_assignment.kv_admin_terraform]
}

# --- PostgreSQL Flexible Server (managed, HA-capable) -------------------

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "psql-te-staging-${local.suffix}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = var.pg_version
  delegated_subnet_id           = azurerm_subnet.pg.id
  private_dns_zone_id           = azurerm_private_dns_zone.pg.id
  public_network_access_enabled = false

  administrator_login    = "pgadmin"
  administrator_password = random_password.pg_password.result

  sku_name   = var.pg_sku
  storage_mb = var.pg_storage_mb

  backup_retention_days        = var.backup_retention_days
  geo_redundant_backup_enabled = var.geo_redundant_backups

  zone = "1"

  dynamic "high_availability" {
    for_each = var.ha_mode == "Disabled" ? [] : [1]
    content {
      mode                      = var.ha_mode
      standby_availability_zone = var.ha_mode == "ZoneRedundant" ? "2" : "1"
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_private_dns_zone_virtual_network_link.pg,
  ]

  lifecycle {
    ignore_changes = [
      zone, # Azure may move it
      high_availability[0].standby_availability_zone,
    ]
  }
}

resource "azurerm_postgresql_flexible_server_database" "te_staging" {
  name      = "te_staging"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_statement" {
  name      = "log_statement"
  server_id = azurerm_postgresql_flexible_server.pg.id
  value     = "ddl" # Audit DDL changes; "all" for stricter audit, costs IO
}

# --- Azure Container Registry (Premium, private endpoint) ---------------

resource "azurerm_container_registry" "acr" {
  name                          = "acrtestaging${local.suffix}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  sku                           = "Premium"
  admin_enabled                 = false # Use managed identity
  public_network_access_enabled = true  # temporarily enabled so az acr build can push; flip to false after bootstrap
  tags                          = local.tags

  retention_policy_in_days = 30
  # trust_policy removed — Azure Content Trust is deprecated and unsupported
  # for new registries. Use ACR image signing or Notary v2 when required.
}

resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-staging"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "psc-acr"
    private_connection_resource_id = azurerm_container_registry.acr.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr.id]
  }
}

# --- Log Analytics + diagnostic settings ---------------------------------

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "law-te-staging-${local.suffix}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 90 # Longer than Dev for audit
  tags                = local.tags
}

resource "azurerm_monitor_diagnostic_setting" "pg" {
  name                       = "diag-pg"
  target_resource_id         = azurerm_postgresql_flexible_server.pg.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log {
    category = "PostgreSQLLogs"
  }

  enabled_log {
    category = "PostgreSQLFlexSessions"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "acr" {
  name                       = "diag-acr"
  target_resource_id         = azurerm_container_registry.acr.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log {
    category = "ContainerRegistryLoginEvents"
  }

  enabled_log {
    category = "ContainerRegistryRepositoryEvents"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "kv" {
  name                       = "diag-kv"
  target_resource_id         = azurerm_key_vault.kv.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log {
    category = "AuditEvent"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# --- Container Apps Environment (workload-profile + VNet-injected) ------

resource "azurerm_container_app_environment" "env" {
  name                           = "cae-te-staging-${local.suffix}"
  resource_group_name            = azurerm_resource_group.rg.name
  location                       = azurerm_resource_group.rg.location
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.logs.id
  infrastructure_subnet_id       = azurerm_subnet.cae.id
  internal_load_balancer_enabled = true
  zone_redundancy_enabled        = var.cae_zone_redundant
  tags                           = local.tags
}

# --- Managed identity for the Container Apps Job ------------------------

resource "azurerm_user_assigned_identity" "runner" {
  name                = "id-runner-staging-${local.suffix}"
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

# --- Container Apps Job — managed scheduled migrations ------------------

resource "azurerm_container_app_job" "migration" {
  name                         = "job-migration-staging"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  container_app_environment_id = azurerm_container_app_environment.env.id

  replica_timeout_in_seconds = 1800 # 30 min
  replica_retry_limit        = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runner.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.runner.id
  }

  # Manual trigger - launched on demand via GitHub Actions / az CLI.
  # Switch to schedule_trigger_config (cron) for periodic auto-runs.
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "migration"
      image  = "${azurerm_container_registry.acr.login_server}/te-migration:staging-initial"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "TARGET_ENV"
        value = "staging"
      }
      env {
        name  = "PGHOST"
        value = azurerm_postgresql_flexible_server.pg.fqdn
      }
      env {
        name  = "PGPORT"
        value = "5432"
      }
      env {
        name  = "PGUSER"
        value = "pgadmin"
      }
      env {
        name  = "PGDATABASE"
        value = azurerm_postgresql_flexible_server_database.te_staging.name
      }
      env {
        name        = "PGPASSWORD"
        secret_name = "pg-password"
      }
    }
  }

  secret {
    name                = "pg-password"
    identity            = azurerm_user_assigned_identity.runner.id
    key_vault_secret_id = azurerm_key_vault_secret.pg_password.id
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [
      # Image tag is updated by the migration-run workflow; don't fight it.
      template[0].container[0].image,
    ]
  }
}
