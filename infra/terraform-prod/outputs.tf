# outputs.tf - prod outputs consumed by the prod migration workflow

output "resource_group_name" {
  value       = azurerm_resource_group.rg.name
  description = "Prod resource group."
}

output "acr_login_server" {
  value       = azurerm_container_registry.acr.login_server
  description = "Private ACR FQDN. Pushes must originate from the VNet (or a self-hosted runner)."
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "pg_fqdn" {
  value       = azurerm_postgresql_flexible_server.pg.fqdn
  description = "PG private DNS name. Reachable only from the VNet."
}

output "pg_admin_login" {
  value       = azurerm_postgresql_flexible_server.pg.administrator_login
  description = "PG admin login name."
}

output "pg_database_name" {
  value = azurerm_postgresql_flexible_server_database.te_prod.name
}

output "key_vault_name" {
  value = azurerm_key_vault.kv.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.kv.vault_uri
}

output "container_apps_environment_name" {
  value = azurerm_container_app_environment.env.name
}

output "container_apps_job_name" {
  value       = azurerm_container_app_job.migration.name
  description = "Name of the prod migration job. Trigger with az containerapp job start."
}

output "runner_identity_id" {
  value = azurerm_user_assigned_identity.runner.id
}

output "runner_identity_client_id" {
  value = azurerm_user_assigned_identity.runner.client_id
}

output "vnet_id" {
  value       = azurerm_virtual_network.vnet.id
  description = "VNet ID — needed if you peer with another VNet or add a jump-box."
}

output "log_analytics_workspace_name" {
  value = azurerm_log_analytics_workspace.logs.name
}

output "api_internal_url" {
  value       = local.api_internal_url
  description = "The API's address inside the Container Apps environment (#256). Not reachable from the VNet; the Streamlit app calls it. Empty when web_apps_enabled is false."
}

output "streamlit_url" {
  value       = var.web_apps_enabled ? "https://${azurerm_container_app.streamlit[0].ingress[0].fqdn}" : ""
  description = "Where people open the Streamlit app, from the private network only (#256). It resolves through the environment's private DNS; see docs/PROD_DEPLOY.md."
}

output "api_app_name" {
  value = var.web_apps_enabled ? azurerm_container_app.api[0].name : ""
}

output "streamlit_app_name" {
  value = var.web_apps_enabled ? azurerm_container_app.streamlit[0].name : ""
}
