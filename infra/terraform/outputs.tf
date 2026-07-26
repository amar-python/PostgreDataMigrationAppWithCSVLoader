# outputs.tf — values that GitHub Actions / docs / the runner need

output "resource_group_name" {
  value       = azurerm_resource_group.rg.name
  description = "Resource group containing all deployed resources."
}

output "acr_login_server" {
  value       = azurerm_container_registry.acr.login_server
  description = "ACR FQDN — used as the image registry."
}

output "acr_name" {
  value       = azurerm_container_registry.acr.name
  description = "ACR short name (for az acr commands)."
}

output "pg_internal_fqdn" {
  value       = azurerm_container_app.pg.latest_revision_fqdn
  description = "Internal FQDN that the migration runner uses as PGHOST."
}

output "pg_container_app_name" {
  value       = azurerm_container_app.pg.name
  description = "PG container app name (for kubectl-style logs / restart)."
}

output "key_vault_name" {
  value       = azurerm_key_vault.kv.name
  description = "Key Vault for PG password."
}

output "key_vault_uri" {
  value       = azurerm_key_vault.kv.vault_uri
  description = "Key Vault URI."
}

output "storage_account_name" {
  value       = azurerm_storage_account.pg_storage.name
  description = "Storage account hosting PG volume + CSV input + run reports."
}

output "runner_identity_id" {
  value       = azurerm_user_assigned_identity.runner.id
  description = "User-assigned managed identity ID for the ACI runner."
}

output "runner_identity_client_id" {
  value       = azurerm_user_assigned_identity.runner.client_id
  description = "Client ID — passed to ACI via --acr-identity."
}

output "log_analytics_workspace_id" {
  value       = azurerm_log_analytics_workspace.logs.workspace_id
  description = "Workspace ID for diagnostic settings."
}

output "container_apps_environment_id" {
  value       = azurerm_container_app_environment.env.id
  description = "Container Apps environment — ACI joins this VNet so it can reach PG."
}

# Sensitive — only emitted in plain text when read explicitly
output "pg_password_kv_secret_name" {
  value       = azurerm_key_vault_secret.pg_password.name
  description = "Name of the Key Vault secret holding the PG password."
}
