# variables.tf — input variables for the Dev environment

variable "environment" {
  description = "Environment name (dev, test, staging, prod). For now only 'dev' is parameterised."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "uat", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, uat, staging, prod."
  }
}

variable "location" {
  description = "Azure region. Pick one close to you: australiaeast, australiasoutheast, eastus, westeurope, etc."
  type        = string
  default     = "australiaeast"
}

variable "subscription_id" {
  description = "Azure subscription ID. Can also be set via ARM_SUBSCRIPTION_ID env var."
  type        = string
  default     = null
}
