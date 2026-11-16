#!/usr/bin/env bash
# =============================================================================
# infra/cloudshell_setup.sh
# =============================================================================
# One-time Azure setup for the Test and Staging stacks (#31), meant to be run in
# Azure Cloud Shell (bash), where `az` and `terraform` already work. The local dev
# machine cannot run either (#32, #34): its security software intercepts TLS in a
# way neither tool accepts, and that was decided against changing. See
# docs/CLOUD_SHELL_SETUP.md for the whole procedure.
#
# What it does (the same steps as "One-time setup" in docs/PROD_DEPLOY.md):
#   1. Resource group rg-tfstate (shared by every environment's state).
#   2. A storage account for this environment's Terraform state, and its `tfstate`
#      container.
#   3. With --with-oidc only: an app registration and service principal for a GitHub
#      Actions pipeline, with a federated credential bound to the GitHub Environment
#      of the same name. Nothing in this repo uses it yet (no Azure workflow was ever
#      committed), so it is off by default.
#
# What it does NOT do: run terraform, edit the repo, or touch GitHub. `terraform
# apply` creates billed resources (about AUD 285-385/month per environment); that
# stays a deliberate step you take after reading the plan.
#
# Safe to run again: the storage account name is derived from the subscription id
# and the environment, so a re-run finds and reuses what exists. Use --dry-run first:
# it prints every change it would make and makes none.
#
# Usage:
#   bash infra/cloudshell_setup.sh <test|staging> [--dry-run] [--region REGION]
#                                  [--subscription ID_OR_NAME]
#                                  [--with-oidc OWNER/REPO]
# =============================================================================
set -euo pipefail

usage() {
    sed -n '/^# Usage:/,/^# ====/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

ENVIRONMENT=""
REGION="australiaeast"
SUBSCRIPTION=""
OIDC_REPO=""
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)      DRY_RUN=1 ;;
        --region)       [ $# -ge 2 ] || { usage >&2; exit 2; }; REGION="$2"; shift ;;
        --subscription) [ $# -ge 2 ] || { usage >&2; exit 2; }; SUBSCRIPTION="$2"; shift ;;
        --with-oidc)    [ $# -ge 2 ] || { usage >&2; exit 2; }; OIDC_REPO="$2"; shift ;;
        -h|--help)      usage; exit 0 ;;
        -*)             echo "ERROR: unknown option $1" >&2; usage >&2; exit 2 ;;
        *)
            [ -z "$ENVIRONMENT" ] || { echo "ERROR: one environment only" >&2; usage >&2; exit 2; }
            ENVIRONMENT="$1"
            ;;
    esac
    shift
done

case "$ENVIRONMENT" in
    test|staging) ;;
    prod)
        echo "ERROR: prod is set up by hand: see 'One-time setup' in docs/PROD_DEPLOY.md." >&2
        exit 2
        ;;
    *)
        echo "ERROR: environment must be 'test' or 'staging'." >&2
        usage >&2
        exit 2
        ;;
esac

if [ -n "$OIDC_REPO" ]; then
    case "$OIDC_REPO" in
        */*/*|/*|*/) echo "ERROR: --with-oidc takes OWNER/REPO, got '$OIDC_REPO'." >&2; exit 2 ;;
    esac
    if ! printf '%s' "$OIDC_REPO" | grep -Eq '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'; then
        echo "ERROR: --with-oidc takes OWNER/REPO, got '$OIDC_REPO'." >&2
        exit 2
    fi
fi

command -v az >/dev/null 2>&1 || die "az was not found. Run this in Azure Cloud Shell (portal.azure.com, Bash)."

# Reading is always allowed, even under --dry-run; only changes go through run().
if [ -n "$SUBSCRIPTION" ]; then
    echo "+ az account set --subscription $SUBSCRIPTION"
    az account set --subscription "$SUBSCRIPTION" || die "could not select subscription '$SUBSCRIPTION'."
fi
SUB_ID=$(az account show --query id -o tsv 2>/dev/null) || die "not signed in to Azure. In Cloud Shell you already are; elsewhere run: az login"
TENANT_ID=$(az account show --query tenantId -o tsv)
[ -n "$SUB_ID" ] || die "could not read the current subscription id."

run() {
    printf '+ %s\n' "$*"
    if [ "$DRY_RUN" = 1 ]; then
        return 0
    fi
    "$@"
}

# Same inputs, same name: a re-run finds the account it made. 9 + 7 + 6 = 22 chars at
# most, inside the 24-character limit for storage account names.
SUFFIX=$(printf '%s' "${SUB_ID}-${ENVIRONMENT}" | sha256sum | cut -c1-6)
RG_STATE="rg-tfstate"
ACCOUNT="sttfstate${ENVIRONMENT}${SUFFIX}"
[ "${#ACCOUNT}" -le 24 ] || die "storage account name '$ACCOUNT' is longer than 24 characters."

echo "== Environment:    $ENVIRONMENT"
echo "== Subscription:   $SUB_ID"
echo "== Region:         $REGION"
echo "== State account:  $ACCOUNT (resource group $RG_STATE)"
if [ "$DRY_RUN" = 1 ]; then
    echo "== DRY RUN: the lines starting with '+' are what a real run would do. Nothing is changed."
fi
echo

# --- 1. Resource group for state ---------------------------------------------
if az group show --name "$RG_STATE" >/dev/null 2>&1; then
    echo "Resource group $RG_STATE exists: reusing it."
else
    run az group create --name "$RG_STATE" --location "$REGION"
fi

# --- 2. State storage account and container ----------------------------------
if az storage account show --name "$ACCOUNT" --resource-group "$RG_STATE" >/dev/null 2>&1; then
    echo "Storage account $ACCOUNT exists: reusing it."
else
    run az storage account create \
        --name "$ACCOUNT" \
        --resource-group "$RG_STATE" \
        --location "$REGION" \
        --sku Standard_LRS \
        --encryption-services blob \
        --min-tls-version TLS1_2 \
        --allow-blob-public-access false
fi
# --auth-mode key: whoever created the account can read its key, so there is no wait
# for a data-plane role assignment to propagate (--auth-mode login needs one).
run az storage container create \
    --account-name "$ACCOUNT" \
    --name tfstate \
    --auth-mode key

# --- 3. Optional: service principal + federated credential for GitHub Actions --
if [ -n "$OIDC_REPO" ]; then
    APP_NAME="sp-te-github-actions-${ENVIRONMENT}"
    CRED_NAME="github-${ENVIRONMENT}"
    SUBJECT="repo:${OIDC_REPO}:environment:${ENVIRONMENT}"
    SCOPE="/subscriptions/${SUB_ID}"

    echo
    echo "-- OIDC: $APP_NAME bound to GitHub Environment '$ENVIRONMENT' of $OIDC_REPO"
    APP_ID=$(az ad app list --display-name "$APP_NAME" --query '[0].appId' -o tsv 2>/dev/null || true)
    if [ -z "$APP_ID" ] || [ "$APP_ID" = "None" ]; then
        if [ "$DRY_RUN" = 1 ]; then
            echo "+ az ad app create --display-name $APP_NAME --query appId -o tsv"
            APP_ID="<new-app-id>"
        else
            echo "+ az ad app create --display-name $APP_NAME --query appId -o tsv"
            APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
        fi
    else
        echo "App registration $APP_NAME exists ($APP_ID): reusing it."
    fi

    if [ "$APP_ID" != "<new-app-id>" ] && az ad sp show --id "$APP_ID" >/dev/null 2>&1; then
        echo "Service principal for $APP_ID exists: reusing it."
    else
        run az ad sp create --id "$APP_ID"
    fi

    for ROLE in "Contributor" "User Access Administrator"; do
        EXISTING=""
        if [ "$APP_ID" != "<new-app-id>" ]; then
            EXISTING=$(az role assignment list --assignee "$APP_ID" --role "$ROLE" --scope "$SCOPE" \
                --query '[0].id' -o tsv 2>/dev/null || true)
        fi
        if [ -n "$EXISTING" ] && [ "$EXISTING" != "None" ]; then
            echo "Role '$ROLE' already assigned: reusing it."
        else
            run az role assignment create --assignee "$APP_ID" --role "$ROLE" --scope "$SCOPE"
        fi
    done

    EXISTING_CRED=""
    if [ "$APP_ID" != "<new-app-id>" ]; then
        EXISTING_CRED=$(az ad app federated-credential list --id "$APP_ID" \
            --query "[?name=='${CRED_NAME}'] | [0].name" -o tsv 2>/dev/null || true)
    fi
    if [ -n "$EXISTING_CRED" ] && [ "$EXISTING_CRED" != "None" ]; then
        echo "Federated credential $CRED_NAME exists: reusing it."
    else
        run az ad app federated-credential create --id "$APP_ID" --parameters \
            "{\"name\": \"${CRED_NAME}\", \"issuer\": \"https://token.actions.githubusercontent.com\", \"subject\": \"${SUBJECT}\", \"audiences\": [\"api://AzureADTokenExchange\"]}"
    fi
fi

# --- What to do next ----------------------------------------------------------
UPPER=$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')
DONE_NOTE=""
if [ "$DRY_RUN" = 1 ]; then
    DONE_NOTE=" (dry run: nothing was changed)"
fi
echo
echo "== Done${DONE_NOTE}."
echo
echo "Next, in infra/terraform-${ENVIRONMENT}/main.tf uncomment the backend block and set:"
echo
echo "  backend \"azurerm\" {"
echo "    resource_group_name  = \"${RG_STATE}\""
echo "    storage_account_name = \"${ACCOUNT}\""
echo "    container_name       = \"tfstate\""
echo "    key                  = \"te-${ENVIRONMENT}.tfstate\""
echo "  }"
echo
echo "Then, still in Cloud Shell: cd infra/terraform-${ENVIRONMENT} && terraform init && terraform plan"
echo "Read the plan and the cost note in main.tf before any 'terraform apply'."
if [ -n "$OIDC_REPO" ]; then
    echo
    echo "GitHub Environment '${ENVIRONMENT}' secrets (repo-level AZURE_TENANT_ID stays as it is):"
    printf '  %-31s = %s\n' "AZURE_${UPPER}_CLIENT_ID" "${APP_ID}"
    printf '  %-31s = %s\n' "AZURE_${UPPER}_SUBSCRIPTION_ID" "${SUB_ID}"
    printf '  %-31s = %s\n' "AZURE_TENANT_ID" "${TENANT_ID}"
    echo "The service principal has Contributor and User Access Administrator on the whole"
    echo "subscription, as in docs/PROD_DEPLOY.md. Narrow that once the resource group exists."
fi
