# variables.tf - input variables for the Test environment

variable "location" {
  description = "Azure region. Pick the same region you used for Dev/Prod to keep latency low."
  type        = string
  default     = "australiaeast"
}

variable "cost_center" {
  description = "Cost-center tag for billing reports."
  type        = string
  default     = "te-platform"
}

variable "vnet_cidr" {
  description = "CIDR for the test VNet. Distinct from Prod's 10.40.0.0/20 and Staging's 10.41.0.0/20 so none collide if ever peered."
  type        = string
  default     = "10.42.0.0/20"
}

variable "pg_version" {
  description = "PostgreSQL major version. 16 matches Dev, Staging, and Prod."
  type        = string
  default     = "16"

  validation {
    condition     = contains(["13", "14", "15", "16"], var.pg_version)
    error_message = "pg_version must be one of: 13, 14, 15, 16."
  }
}

variable "pg_sku" {
  description = <<-EOT
    PostgreSQL Flexible Server SKU. Same default as Prod
    (GP_Standard_D2s_v3, ~AUD 180/mo) — same tier options and tradeoffs;
    see infra/terraform-prod/variables.tf for the full cost breakdown.
    Lower this in terraform.tfvars if test doesn't need Prod-equivalent
    headroom.
  EOT
  type        = string
  default     = "GP_Standard_D2s_v3"
}

variable "pg_storage_mb" {
  description = "PG storage in MB. Minimum 32768 (32 GiB), grows by doubling. Storage is irreversible — only goes up."
  type        = number
  default     = 32768
}

variable "backup_retention_days" {
  description = "PITR window. Range 7-35 days. Same default as Prod (14); lower it in terraform.tfvars if test data is disposable enough not to need it."
  type        = number
  default     = 14

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35."
  }
}

variable "geo_redundant_backups" {
  description = "Enable geo-redundant backups (adds ~30% to backup storage cost). Not usually needed for test."
  type        = bool
  default     = false
}

variable "ha_mode" {
  description = <<-EOT
    PG HA mode:
      Disabled       — single instance, cheapest, ~99.9% SLA
      SameZone       — standby in same zone, adds ~$60/mo, ~99.95% SLA
      ZoneRedundant  — standby in different AZ, adds ~$100/mo, ~99.99% SLA
    Test exists to validate against Prod-like infra, not to be highly
    available itself — leave Disabled unless specifically testing HA failover.
  EOT
  type        = string
  default     = "Disabled"

  validation {
    condition     = contains(["Disabled", "SameZone", "ZoneRedundant"], var.ha_mode)
    error_message = "ha_mode must be one of: Disabled, SameZone, ZoneRedundant."
  }
}

variable "cae_zone_redundant" {
  description = "Container Apps environment zone-redundancy. Costs no extra if region supports it; adds resilience."
  type        = bool
  default     = true
}
