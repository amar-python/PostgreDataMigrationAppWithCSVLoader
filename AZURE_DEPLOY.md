# Deploying to Azure — Dev environment

This guide walks you through deploying the PostgreDataMigrationApp Dev
environment to Azure using Azure Container Instances (compute) +
Azure Container Apps (PostgreSQL). It covers three paths:

1. **Terraform + GitHub Actions** (recommended, reproducible)
2. **Terraform from your laptop** (no CI)
3. **Manual Azure Portal click-through** (no IaC, see `infra/azure-portal-walkthrough.md`)

You can mix and match — many teams provision infra with Terraform once
then run migrations manually via the Portal or `az` CLI.

## Architecture (Dev only)

```text
                      Azure Resource Group
                            (rg-te-dev-<rand>)
       +----------------+
       |  Container     |     internal VNet
       |  Apps Env      |  +------------------+
       |                |  |  PG Container    |
       |                |  |  postgres:16     |
       |                |  |  + Azure Files   |
       |                |  +------------------+
       |                |          ^
       |                |          | port 5432
       +----------------+          |
                                   |
       +-----------------+         |
       | ACI (per-run)   |---------+
       | te-migration    |
       | image from ACR  |
       +-----------------+
              ^
              | image pull
              |
       +-----------------+    +---------------------+
       | Azure Container |    | Storage Account     |
       | Registry        |    |  + pgdata file share|
       |                 |    |  + csv-input blobs  |
       +-----------------+    |  + run-reports blobs|
                              +---------------------+

       +-----------------+
       | Key Vault       |  --> stores PG password
       +-----------------+

       +-----------------+
       | Log Analytics   |  --> Container Apps logs
       +-----------------+
```

## Cost estimate (Dev only, australiaeast)

| Resource | Tier | Approx. monthly cost (AUD) |
| --- | --- | --- |
| Resource group | n/a | $0 |
| ACR Basic | always-on | $7 |
| Container Apps env | scale-to-zero | $0 (only when idle) |
| PG container app | 0.5 vCPU, 1 GiB, always-on | $15-20 |
| Azure Files (50 GB) | Standard LRS | $3 |
| Storage account | LRS, low traffic | $1 |
| Key Vault | Standard | $0.50 |
| Log Analytics | PerGB, ~5 GB/mo | $5-10 |
| ACI runner | $0 idle, $0.005/hr when running | < $1/mo |
| **Total** | | **~AUD 32-42/mo** |

For Prod, migrate PG to Azure Database for PostgreSQL Flexible Server
(adds ~$40-100/mo but gives managed backups + HA).

## Path 1 — Terraform + GitHub Actions (recommended)

### One-time setup

#### Step 1.1 — Create an Azure service principal with federated credentials

```bash
# Pick a name. Replace YOUR_GITHUB_ORG/REPO accordingly.
APP_NAME="sp-te-github-actions"
REPO="YOUR_GITHUB_ORG/Migration-using-ai"   # change me

# Create app and service principal
APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
az ad sp create --id "$APP_ID"

# Grant Contributor on your subscription (or scope down to a single RG later)
SUB_ID=$(az account show --query id -o tsv)
az role assignment create \
    --assignee "$APP_ID" \
    --role Contributor \
    --scope "/subscriptions/$SUB_ID"

# Federated credentials — lets GitHub Actions exchange its OIDC token
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters "{
        \"name\": \"github-main\",
        \"issuer\": \"https://token.actions.githubusercontent.com\",
        \"subject\": \"repo:$REPO:ref:refs/heads/master\",
        \"audiences\": [\"api://AzureADTokenExchange\"]
    }"

# Print the three secrets GitHub needs
echo "AZURE_CLIENT_ID=$APP_ID"
echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID=$SUB_ID"
```

#### Step 1.2 — Add the secrets to GitHub

Go to your repo -> **Settings -> Secrets and variables -> Actions ->
New repository secret** and add:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

#### Step 1.3 — (Optional) Set up Terraform remote state

Local state is fine for solo Dev. For team use, store state in Azure
Blob Storage. See the commented backend block in `infra/terraform/main.tf`.

### Deploy

1. Go to **Actions** in your GitHub repo.
2. Pick **Azure infra — terraform apply (Dev)**.
3. Click **Run workflow** -> action: `plan` -> Run. Review the plan
   in the run summary.
4. Re-run with action: `apply`. Wait ~5 minutes for the resources to
   come up.
5. Pick **Azure migration — build, push, run**.
6. Click **Run workflow** -> action: `full` -> Run. This builds the
   image, pushes it to ACR, and runs the migration end-to-end.
7. Logs stream in the workflow output. Exit code 0 = success.

### Re-running the migration

Use the **Azure migration — build, push, run** workflow with action:

- `deploy` — just the schema
- `load` — just the CSV load
- `evals` — just the eval suite
- `full` — all three

The infrastructure is left in place. Per-run cost is `< $0.10` for
the ACI runtime.

### Tear-down

Run the **Azure infra — terraform apply (Dev)** workflow with action
`destroy`. All resources delete in ~3 minutes.

## Path 2 — Terraform from your laptop

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai\PostgreDataMigrationApp\infra\terraform"

# Install Terraform first: https://developer.hashicorp.com/terraform/install
# Install Azure CLI:       https://learn.microsoft.com/cli/azure/install-azure-cli

az login                              # opens browser
az account set --subscription "your-sub-name-or-id"

Copy-Item terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars (region etc.) in your editor

terraform init
terraform plan -out tfplan
terraform apply tfplan
```

After `apply`, capture the outputs:

```powershell
terraform output -json | ConvertFrom-Json | Format-List
```

Then build and push the image manually:

```powershell
$ACR = (terraform output -raw acr_name)
$ACR_LOGIN = (terraform output -raw acr_login_server)

Push-Location "$env:USERPROFILE\OneDrive\Desktop\Migration using ai"
az acr login --name $ACR
docker build -f PostgreDataMigrationApp/infra/Dockerfile -t "$ACR_LOGIN/te-migration:dev" .
docker push "$ACR_LOGIN/te-migration:dev"
Pop-Location
```

Run the migration as ACI:

```powershell
$RG = (terraform output -raw resource_group_name)
$KV = (terraform output -raw key_vault_name)
$PG_FQDN = (terraform output -raw pg_internal_fqdn)
$IDENTITY = (terraform output -raw runner_identity_id)
$PG_PASS = (az keyvault secret show --vault-name $KV --name pg-postgres-password --query value -o tsv)

az container create `
    --resource-group $RG `
    --name "aci-migration-once" `
    --image "$ACR_LOGIN/te-migration:dev" `
    --restart-policy Never `
    --acr-identity $IDENTITY `
    --assign-identity $IDENTITY `
    --environment-variables PGHOST=$PG_FQDN PGUSER=postgres PGDATABASE=te_dev TARGET_ENV=dev `
    --secure-environment-variables PGPASSWORD=$PG_PASS `
    --command-line "/opt/migration/entrypoint.sh full"

# Watch logs
az container logs -g $RG -n aci-migration-once --follow

# Cleanup
az container delete -g $RG -n aci-migration-once --yes
```

## Path 3 — Azure Portal click-through (no IaC)

See `infra/azure-portal-walkthrough.md` for the full UI sequence.
Best for one-off testing or learning the Azure resources; not
reproducible.

## Where things end up

| What | Where to find it |
| --- | --- |
| PG password | Key Vault -> Secrets -> `pg-postgres-password` |
| Migration logs | Log Analytics workspace OR ACI container logs |
| Eval reports | `evals/reports/` inside the ACI container before it terminates. To persist them, mount the `run-reports` blob container or have entrypoint.sh upload them via `az storage blob upload` |
| Image versions | ACR -> Repositories -> `te-migration` |
| Schema/data | PG container app, database `te_dev`, schema `te_dev` |

## Connecting to the PG container from your laptop

The PG container is internal-only by default. To connect from outside:

```bash
# Option A: temporary public ingress (cheap test, security risk)
# Re-deploy the container app with external_enabled = true in main.tf

# Option B: use psql from another container in the same env (safer)
az containerapp exec \
    --resource-group rg-te-dev-<rand> \
    --name ca-pg-dev-<rand> \
    --command 'psql -U postgres'

# Option C: jump-box VM in the same VNet (production pattern)
```

## Production hardening — when you're ready

| Concern | Dev current | Prod recommendation |
| --- | --- | --- |
| PG hosting | Container Apps | **Azure Database for PostgreSQL Flexible Server** with HA |
| Networking | Public ACR + KV | Private endpoints + private DNS zones |
| Secrets | Plain KV access | KV with private endpoint + RBAC scoped to RG |
| Image | Pulled from ACR Basic | ACR Standard + image scanning + signed images |
| Compute | ACI per run | Azure Container Apps Jobs (managed scheduling) |
| Backup | Azure Files snapshot (manual) | Managed PG backups (PITR 7-35 days) |
| Monitoring | Log Analytics only | Add Azure Monitor alerts + Application Insights |

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `terraform apply` fails on KV permissions | Subscription doesn't allow the SP to assign roles | Have an Owner run `az role assignment create` once or scope the SP higher |
| ACI hangs in `Waiting` state | ACR pull failing | Check user-assigned identity has `AcrPull` role on ACR |
| `entrypoint.sh: not found` in container | CRLF line endings | Make sure the file is saved with LF endings, then rebuild the image |
| Migration runs but evals all SKIP | PG hostname wrong | Confirm `PGHOST` matches the value of `terraform output pg_internal_fqdn` |
| `pg_isready` timeout (60s) | PG container slow to start | Bump `WAIT_FOR_DB_SECONDS` to 180 in the workflow inputs |

## See also

- `infra/Dockerfile` — image definition
- `infra/entrypoint.sh` — container dispatch
- `infra/terraform/` — Azure resource definitions
- `infra/azure-portal-walkthrough.md` — manual UI walkthrough
- `.github/workflows/azure-*.yml` — CI/CD workflows
- `ARCHITECTURE.md` — overall framework architecture
