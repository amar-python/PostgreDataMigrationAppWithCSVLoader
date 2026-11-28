# #335 (SE-14): tflint for every root under infra/, run by scripts/terraform_check.sh.
# The bundled Terraform ruleset only: it needs no download, so CI and an offline machine lint the same way.
# The azurerm ruleset (invalid SKUs, regions) would need a plugin fetched from GitHub; add it when that is wanted.
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}
