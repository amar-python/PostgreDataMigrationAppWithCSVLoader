# variables.tf - input variables for the Prod environment

variable "location" {
  description = "Azure region. Pick the same region you used for Dev to keep latency low."
  type        = string
  default     = "australiaeast"
}

variable "cost_center" {
  description = "Cost-center tag for billing reports."
  type        = string
  default     = "te-platform"
}

variable "vnet_cidr" {
  description = "CIDR for the prod VNet. Default gives ~4k addresses spread across 3 subnets."
  type        = string
  default     = "10.40.0.0/20"
}

variable "pg_version" {
  description = "PostgreSQL major version. 16 matches the Dev container image."
  type        = string
  default     = "16"

  validation {
    condition     = contains(["13", "14", "15", "16"], var.pg_version)
    error_message = "pg_version must be one of: 13, 14, 15, 16."
  }
}

variable "pg_sku" {
  description = <<-EOT
    PostgreSQL Flexible Server SKU. Cheapest realistic prod is GP_Standard_D2s_v3
    (~AUD 180/mo for 2 vCPU, 8 GiB). Heavier options: GP_Standard_D4s_v3 (~AUD 350),
    MO_Standard_E2ds_v4 (memory-optimised, ~AUD 250). Burstable tiers (B1ms,
    B2ms) are cheaper (~AUD 25-60/mo) but not recommended for prod beyond a
    proof-of-concept since CPU credits exhaust under sustained load.
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
  description = "PITR window. Range 7-35 days."
  type        = number
  default     = 14

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35."
  }
}

variable "geo_redundant_backups" {
  description = "Enable geo-redundant backups (adds ~30% to backup storage cost). Recommended for prod disaster recovery."
  type        = bool
  default     = false
}

variable "ha_mode" {
  description = <<-EOT
    PG HA mode:
      Disabled       — single instance, cheapest, ~99.9% SLA
      SameZone       — standby in same zone, adds ~$60/mo, ~99.95% SLA
      ZoneRedundant  — standby in different AZ, adds ~$100/mo, ~99.99% SLA
    Recommend ZoneRedundant for real production; Disabled for cost-constrained early prod.
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
