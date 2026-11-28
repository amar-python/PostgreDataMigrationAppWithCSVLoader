#!/usr/bin/env bash
# #335 (SE-14): static checks for every Terraform root under infra/. Run by .github/workflows/terraform.yml, and
# locally with terraform, tflint and checkov on PATH:  bash scripts/terraform_check.sh
#
#   1. terraform fmt -check  layout, over all of infra/
#   2. terraform validate    per root, after `init -backend=false`: providers are downloaded but no state is read,
#                            so no Azure login is needed and the real state is never touched
#   3. tflint                per root, with infra/.tflint.hcl (the recommended Terraform rules)
#   4. checkov               over infra/; fails on any finding not in infra/.checkov.baseline. The baseline holds
#                            the findings that existed when the check was added; they are triaged under #335.
#                            After fixing one, regenerate the baseline (see infra/README.md) so it cannot hide a
#                            regression of the same kind.
#
# Every root is found, not listed: any directory under infra/ holding a .tf file is checked.
set -euo pipefail

cd "$(dirname "$0")/.."
TF="${TERRAFORM:-terraform}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mapfile -t roots < <(find infra -name '*.tf' -not -path '*/.terraform/*' -printf '%h\n' | sort -u)
if [ "${#roots[@]}" -eq 0 ]; then
  echo "no Terraform roots found under infra/" >&2
  exit 1
fi
echo "Terraform roots: ${roots[*]}"

failed=0
step() { echo; echo "== $*"; }

step "terraform fmt -check"
if ! "$TF" fmt -check -recursive -diff infra; then
  echo "::error::run 'terraform fmt -recursive infra' and commit the result"
  failed=1
fi

for root in "${roots[@]}"; do
  step "terraform validate: $root"
  # A data dir per root, outside the tree, so a local run leaves no .terraform/ behind.
  TF_DATA_DIR="$work/${root//\//_}"
  export TF_DATA_DIR
  if ! "$TF" -chdir="$root" init -backend=false -input=false -no-color >"$work/init.log" 2>&1; then
    cat "$work/init.log"
    echo "::error::terraform init failed in $root"
    failed=1
    continue
  fi
  "$TF" -chdir="$root" validate -no-color || failed=1
done
unset TF_DATA_DIR

for root in "${roots[@]}"; do
  step "tflint: $root"
  tflint --chdir="$root" --config="$PWD/infra/.tflint.hcl" --format=compact || failed=1
done

step "checkov (new findings only; baseline infra/.checkov.baseline)"
checkov -d infra --framework terraform --baseline infra/.checkov.baseline \
  --compact --quiet --skip-download || failed=1

echo
if [ "$failed" -ne 0 ]; then
  echo "Terraform checks FAILED"
  exit 1
fi
echo "All Terraform checks passed."
