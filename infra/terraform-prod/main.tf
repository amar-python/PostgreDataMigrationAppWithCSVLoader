# main.tf - Azure Prod environment for PostgreDataMigrationApp
#
# Differences vs Dev (infra/terraform/main.tf):
#   - PG is Azure Database for PostgreSQL Flexible Server (managed)
#   - VNet + delegated subnets so PG and Container Apps are private
#   - Private endpoints for ACR (Premium SKU) and Key Vault
#   - Container Apps Job for managed scheduling (not ACI per-run)
#   - Two always-on Container Apps, the API and the Streamlit front end (#256), in the
#     same internal-only environment: reachable from the private network, no public address
#   - HA optional (ZoneRedundant), backups with PITR + optional geo-redundancy
#   - Diagnostic settings on PG, KV, ACR streaming into Log Analytics
#
# Cost estimate (australiaeast, defaults):
#   PG Flexible Server GP_Standard_D2s_v3 + 32GB + HA off + 14d backup .. ~AUD 180/mo
#   With HA ZoneRedundant ........................................... +~AUD 100/mo
#   ACR Premium ..................................................... ~AUD 70/mo
#   VNet, private endpoints, KV, Log Analytics ..................... ~AUD 30/mo
#   Container Apps env + Job (idle) ................................ ~AUD 5/mo
#   API + Streamlit apps, 1 replica each, always on (#256) ......... ~AUD 40-70/mo
#   Total without HA ............................................... ~AUD 325-355/mo
#   Total with HA .................................................. ~AUD 425-455/mo

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
    # Only for what azurerm cannot set yet: sticky sessions on the Streamlit app's ingress (#256).
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.0"
    }
  }

  # Production state MUST be in remote storage. Uncomment after creating the
  # state storage account (see PROD_DEPLOY.md "One-time setup").

  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "sttfstateprod7u8hql"
    container_name       = "tfstate"
    key                  = "te-prod.tfstate"
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false # Prod: never purge by accident
      recover_soft_deleted_key_vaults = true
    }
  }
}

locals {
  suffix = random_string.suffix.result
  tags = {
    project     = "PostgreDataMigrationApp"
    environment = "prod"
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
  name     = "rg-te-prod-${local.suffix}"
  location = var.location
  tags     = local.tags
}

# --- VNet + subnets -------------------------------------------------------

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-te-prod-${local.suffix}"
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
  name                = "te-prod-${local.suffix}.private.postgres.database.azure.com"
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
  name                          = "kv-te-prod-${local.suffix}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "premium"
  soft_delete_retention_days    = 90
  purge_protection_enabled      = true
  enable_rbac_authorization     = true
  public_network_access_enabled = var.bootstrap_public_access # true only for the bootstrap apply (#299)
  tags                          = local.tags
}

resource "azurerm_role_assignment" "kv_admin_terraform" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_private_endpoint" "kv" {
  name                = "pe-kv-prod"
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

# Password for the application role (te_prod_user) that the migration job
# creates. The job reads it as APP_DB_PASSWORD; it is never baked into the image
# or written to a launcher file (#172, #174).
resource "random_password" "app_password" {
  length           = 32
  special          = true
  min_lower        = 4
  min_upper        = 4
  min_numeric      = 4
  override_special = "!@#$%^&*()-_=+"
}

resource "azurerm_key_vault_secret" "app_password" {
  name         = "pg-app-password"
  value        = random_password.app_password.result
  key_vault_id = azurerm_key_vault.kv.id

  depends_on = [azurerm_role_assignment.kv_admin_terraform]
}

# Password for the API's runtime role (te_prod_runtime, M3d #107): the role its request pool
# connects as, which can only read and insert the audit and upload tables. te_prod_user stays
# the owner and runs migrations at start-up. Nothing here creates the role in the database:
# docs/PROD_DEPLOY.md gives the one-time SQL, as scripts/offline/install.sh runs it on-prem.
resource "random_password" "runtime_password" {
  length           = 32
  special          = true
  min_lower        = 4
  min_upper        = 4
  min_numeric      = 4
  override_special = "!@#$%^&*()-_=+"
}

resource "azurerm_key_vault_secret" "runtime_password" {
  name         = "pg-runtime-password"
  value        = random_password.runtime_password.result
  key_vault_id = azurerm_key_vault.kv.id

  depends_on = [azurerm_role_assignment.kv_admin_terraform]
}

# --- PostgreSQL Flexible Server (managed, HA-capable) -------------------

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "psql-te-prod-${local.suffix}"
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

# The production database on Azure is te_prod, owned by the server's admin login
# (pgadmin). The migration job receives both as PGDATABASE and PGUSER, and its
# entrypoint writes them into the launcher it deploys with (infra/entrypoint.sh),
# so this resource is the only place the name is set. The on-prem installer keeps
# its own name, te_mgmt_prod (DECISIONS/2026-11-09-prod-db-naming.md).
resource "azurerm_postgresql_flexible_server_database" "te_prod" {
  name      = "te_prod"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# The schema needs uuid-ossp, pg_trgm and dblink. Azure refuses CREATE EXTENSION
# for anything not allow-listed here, so without this the first deployment fails
# partway through creating the schema.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.pg.id
  value     = "dblink,pg_trgm,uuid-ossp"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_statement" {
  name      = "log_statement"
  server_id = azurerm_postgresql_flexible_server.pg.id
  value     = "ddl" # Audit DDL changes; "all" for stricter audit, costs IO
}

# --- Azure Container Registry (Premium, private endpoint) ---------------

resource "azurerm_container_registry" "acr" {
  name                          = "acrteprod${local.suffix}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  sku                           = "Premium"
  admin_enabled                 = false                       # Use managed identity
  public_network_access_enabled = var.bootstrap_public_access # true only for the bootstrap apply (#299)
  tags                          = local.tags

  retention_policy_in_days = 30
  # trust_policy removed — Azure Content Trust is deprecated and unsupported
  # for new registries. Use ACR image signing or Notary v2 when required.
}

resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-prod"
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
  name                = "law-te-prod-${local.suffix}"
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
  name                           = "cae-te-prod-${local.suffix}"
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
  name                = "id-runner-prod-${local.suffix}"
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
  name                         = "job-migration-prod"
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
      image  = "${azurerm_container_registry.acr.login_server}/te-migration:prod-initial"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "TARGET_ENV"
        value = "prod"
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
        value = azurerm_postgresql_flexible_server_database.te_prod.name
      }
      env {
        name        = "PGPASSWORD"
        secret_name = "pg-password"
      }
      env {
        name        = "APP_DB_PASSWORD"
        secret_name = "app-password"
      }
    }
  }

  secret {
    name                = "pg-password"
    identity            = azurerm_user_assigned_identity.runner.id
    key_vault_secret_id = azurerm_key_vault_secret.pg_password.id
  }

  secret {
    name                = "app-password"
    identity            = azurerm_user_assigned_identity.runner.id
    key_vault_secret_id = azurerm_key_vault_secret.app_password.id
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [
      # Image tag is updated by the migration-run workflow; don't fight it.
      template[0].container[0].image,
    ]
  }
}

# --- API and Streamlit apps (#256) ---------------------------------------
#
# Owner decision, 24 Nov (DECISIONS/2026-11-16-streamlit-migration-plan.md, "Azure host"):
# two always-on apps in the internal-only environment above, from the same registry, with the
# same managed identity, Key Vault and Log Analytics as the migration job.
#
# Reachability. The environment has internal_load_balancer_enabled = true, so it has no public
# address at all. Inside it:
#   - the API's ingress is internal to the environment (external_enabled = false): only other
#     apps in it, the Streamlit app, can call it. Browsers never call the API directly;
#   - the Streamlit app's ingress is "external", which in an internal environment means the
#     VNet and what is joined to it (VPN, ExpressRoute, a peered network or a jump host).
# Not verified (test both before the cutover, #257): that WebSockets stay open through the
# ingress for a long review session, and that a 50 MiB upload passes it.

locals {
  api_app_name       = "ca-te-api-prod"
  streamlit_app_name = "ca-te-streamlit-prod"
  # The API's internal address, as the Streamlit app calls it, server to server.
  api_internal_url = var.web_apps_enabled ? "https://${azurerm_container_app.api[0].ingress[0].fqdn}" : ""
}

resource "azurerm_container_app" "api" {
  count                        = var.web_apps_enabled ? 1 : 0
  name                         = local.api_app_name
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runner.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.runner.id
  }

  ingress {
    external_enabled           = false # environment only: the Streamlit app is its one caller
    target_port                = 8000
    transport                  = "http"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1 # always on
    max_replicas = 1 # rate limits and the import limit are per process (api/ratelimit.py, #307)

    container {
      name   = "api"
      image  = "${azurerm_container_registry.acr.login_server}/te-api:${var.api_image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "API_ENV"
        value = "prod"
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
        name  = "PGSSLMODE"
        value = "require"
      }
      env {
        name  = "PGDATABASE"
        value = azurerm_postgresql_flexible_server_database.te_prod.name
      }
      # The owner role the migration job creates (build/environments/env_prod.example.sql,
      # app_user) with CREATEROLE (#400), so the API can give each tenant its own role.
      env {
        name  = "PGUSER"
        value = "te_prod_user"
      }
      env {
        name        = "PGPASSWORD"
        secret_name = "app-password"
      }
      env {
        name  = "APP_DB_USER"
        value = "te_prod_runtime"
      }
      env {
        name        = "APP_DB_PASSWORD"
        secret_name = "runtime-password"
      }
      env {
        name  = "TE_SCHEMA"
        value = "te_prod"
      }
      env {
        name  = "MAX_UPLOAD_BYTES"
        value = tostring(var.max_upload_bytes)
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/api/health"
      }

      liveness_probe {
        transport     = "HTTP"
        port          = 8000
        path          = "/api/health"
        initial_delay = 10
      }
    }
  }

  secret {
    name                = "app-password"
    identity            = azurerm_user_assigned_identity.runner.id
    key_vault_secret_id = azurerm_key_vault_secret.app_password.id
  }

  secret {
    name                = "runtime-password"
    identity            = azurerm_user_assigned_identity.runner.id
    key_vault_secret_id = azurerm_key_vault_secret.runtime_password.id
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.runner_acr_pull,
    azurerm_role_assignment.runner_kv_secrets,
  ]
}

resource "azurerm_container_app" "streamlit" {
  count                        = var.web_apps_enabled ? 1 : 0
  name                         = local.streamlit_app_name
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single" # sticky sessions need single-revision mode

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runner.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.runner.id
  }

  ingress {
    external_enabled           = true # the VNet only: this environment has no public address
    target_port                = 8501
    transport                  = "auto" # HTTP/1.1 with WebSocket upgrade, which Streamlit needs
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1 # never scale to zero: that drops every session and adds a cold start
    max_replicas = var.streamlit_max_replicas

    container {
      name   = "streamlit"
      image  = "${azurerm_container_registry.acr.login_server}/te-streamlit:${var.streamlit_image_tag}"
      cpu    = 1.0 # an upload is held as bytes, text and base64 before it is sent
      memory = "2Gi"

      env {
        name  = "API_URL"
        value = local.api_internal_url
      }
      env {
        name  = "MAX_UPLOAD_BYTES"
        value = tostring(var.max_upload_bytes)
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8501
        path      = "/_stcore/health"
      }

      liveness_probe {
        transport     = "HTTP"
        port          = 8501
        path          = "/_stcore/health"
        initial_delay = 10
      }
    }
  }

  tags = local.tags

  depends_on = [azurerm_role_assignment.runner_acr_pull]
}

# Name resolution from the VNet. An internal environment gets no DNS of its own: its apps'
# names (<app>.<default_domain>) resolve only once a private zone for the default domain points
# at the environment's internal load balancer. Linked to the prod VNet here; a peered or VPN
# network needs its own link or DNS forwarding to this zone.
resource "azurerm_private_dns_zone" "cae" {
  name                = azurerm_container_app_environment.env.default_domain
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "cae" {
  name                  = "link-cae"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.cae.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

resource "azurerm_private_dns_a_record" "cae_wildcard" {
  name                = "*"
  zone_name           = azurerm_private_dns_zone.cae.name
  resource_group_name = azurerm_resource_group.rg.name
  ttl                 = 300
  records             = [azurerm_container_app_environment.env.static_ip_address]
}

# Sticky sessions: a Streamlit session lives in one replica's memory, so a browser must keep
# reaching the same one once there is more than one. azurerm (4.x) has no argument for it, so it
# is set on the resource through the ARM API. It costs nothing with one replica, so it is always on.
# An azurerm change to the ingress can drop it; the next plan then shows this resource to re-apply.
resource "azapi_update_resource" "streamlit_sticky_sessions" {
  count       = var.web_apps_enabled ? 1 : 0
  type        = "Microsoft.App/containerApps@2024-03-01"
  resource_id = azurerm_container_app.streamlit[0].id

  body = {
    properties = {
      configuration = {
        ingress = {
          stickySessions = {
            affinity = "sticky"
          }
        }
      }
    }
  }
}
