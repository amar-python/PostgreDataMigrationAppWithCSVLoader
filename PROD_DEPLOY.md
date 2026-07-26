# Production deployment — PostgreDataMigrationApp

Companion to `AZURE_DEPLOY.md` (the Dev guide). This file covers the
Prod variant: Azure Database for PostgreSQL Flexible Server with HA +
backups, private networking, Container Apps Job for managed scheduling,
remote Terraform state, audit logging, and a Dev → Prod data migration
path.

> **Pre-read:** Make sure your Dev environment is working end-to-end
> first. The Prod IaC follows the same shape — provisioning unfamiliar
> production Azure resources is the wrong time to debug Docker.

## What's different vs Dev

| Layer | Dev | Prod |
|---|---|---|
| **PG hosting** | Container Apps + postgres:16-alpine + Azure Files | **Azure Database for PostgreSQL Flexible Server** (managed) |
| **PG SLA** | None (single container) | 99.9% / 99.95% / 99.99% (HA Disabled / SameZone / ZoneRedundant) |
| **Backups** | None | PITR 7-35 days, optional geo-redundant |
| **Networking** | Public ACR + public KV | **Private VNet + private endpoints** for PG, ACR, KV |
| **ACR SKU** | Basic ($7/mo) | Premium ($70/mo) — content trust, retention policy, private link |
| **Compute** | ACI per-run | **Container Apps Job** in the same VNet (managed scheduling) |
| **Image build** | Docker on GitHub runner | **ACR Tasks remote build** (works with private ACR) |
| **State** | Local or single Azure blob | Remote state with state locking required |
| **Audit** | Container logs only | PG/KV/ACR diagnostic settings → Log Analytics (90 days) |
| **CI/CD gate** | None | GitHub `production` Environment with required reviewers |
| **Destroy guard** | One click | Typed `PROD-DESTROY-CONFIRM` + reviewer approval |

## Cost estimate (australiaeast)

| Component | Default | With HA ZoneRedundant + geo-backups |
| --- | --- | --- |
| PG Flexible Server (GP_Standard_D2s_v3, 32 GB) | ~AUD 180/mo | ~AUD 280/mo |
| PG backups (14 days) | ~AUD 5/mo | ~AUD 7/mo (geo) |
| ACR Premium | ~AUD 70/mo | same |
| VNet + private endpoints (3) | ~AUD 25/mo | same |
| Key Vault Premium | ~AUD 1/mo | same |
| Log Analytics (90 d, ~10 GB/mo) | ~AUD 15/mo | same |
| Container Apps env + Job (idle) | ~AUD 5/mo | same |
| **Total** | **~AUD 300/mo** | **~AUD 400/mo** |

Cost dials in `variables.tf`:

- `pg_sku` — drop to `B1ms` for non-production proofs (~AUD 25/mo, no SLA)
- `ha_mode` — `Disabled` saves ~AUD 100/mo; raise only when you're ready
- `geo_redundant_backups` — adds ~30% to backup cost, enables cross-region restore
- `backup_retention_days` — 7 minimum, 35 maximum, linear cost increase

## One-time setup

### 1. Create the Terraform state storage

Production state MUST live in remote Azure storage with state locking.

```bash
# Replace REGION and PROD_SUB with your values.
REGION="australiaeast"
SUFFIX=$(openssl rand -hex 3)

az group create --name rg-tfstate --location $REGION
az storage account create \
    --name "sttfstateprod$SUFFIX" \
    --resource-group rg-tfstate \
    --location $REGION \
    --sku Standard_LRS \
    --encryption-services blob \
    --min-tls-version TLS1_2
az storage container create \
    --account-name "sttfstateprod$SUFFIX" \
    --name tfstate \
    --auth-mode login

echo "Now uncomment the backend block in infra/terraform-prod/main.tf"
echo "Set storage_account_name = 'sttfstateprod$SUFFIX'"
```

Edit `infra/terraform-prod/main.tf` and uncomment the `backend "azurerm"`
block, replacing the placeholder values.

### 2. Create a Prod-only service principal with OIDC

Use a SEPARATE SP from Dev. Scope it tightly.

```bash
APP_NAME="sp-te-github-actions-prod"
REPO="YOUR_GITHUB_ORG/Migration-using-ai"

APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
az ad sp create --id "$APP_ID"

# Grant Contributor scoped to a future RG (replace name after first apply
# OR grant on subscription temporarily, then narrow scope).
SUB_ID=$(az account show --query id -o tsv)
az role assignment create \
    --assignee "$APP_ID" \
    --role Contributor \
    --scope "/subscriptions/$SUB_ID"

# Required additional role to assign roles to the runner identity:
az role assignment create \
    --assignee "$APP_ID" \
    --role "User Access Administrator" \
    --scope "/subscriptions/$SUB_ID"

# Federated credentials for both main branch and PR validation
az ad app federated-credential create \
    --id "$APP_ID" \
    --parameters "{
        \"name\": \"github-main\",
        \"issuer\": \"https://token.actions.githubusercontent.com\",
        \"subject\": \"repo:$REPO:environment:production\",
        \"audiences\": [\"api://AzureADTokenExchange\"]
    }"

echo "AZURE_PROD_CLIENT_ID=$APP_ID"
echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"
echo "AZURE_PROD_SUBSCRIPTION_ID=$SUB_ID"
```

Note the federated credential uses `environment:production` (not a
branch) — this binds the SP to GitHub Environment approval.

### 3. Configure GitHub Environment + secrets

1. Repo -> **Settings -> Environments -> New environment**: name
   `production`.
2. Add **Required reviewers** (at least one other person).
3. Add **Deployment branch rule**: `main` only.
4. In environment secrets, add:
   - `AZURE_PROD_CLIENT_ID`
   - `AZURE_PROD_SUBSCRIPTION_ID`
   (Tenant ID stays in repo-level secrets — same as Dev.)

## Deploy

### Step 1 — Provision infrastructure

1. GitHub -> **Actions -> Azure infra — terraform apply (Prod)**.
2. Click **Run workflow** -> action: `plan` -> Run. Wait for an
   approving reviewer.
3. Review the plan output. Re-run with action: `apply` once reviewed.
4. ~10-15 minutes (PG Flex provisioning + private endpoints are slow).

### Step 2 — First migration run

1. GitHub -> **Actions -> Azure migration — build, push, run (Prod)**.
2. Click **Run workflow**:
   - action: `deploy` (start with just the schema)
   - change_ticket: e.g. `CHG-2026-001` (logged in run summary)
3. Wait for reviewer approval.
4. The workflow:
   - Builds the image via `az acr build` (remote build inside Azure VNet)
   - Updates the Container Apps Job image tag
   - Triggers a single execution of the Job
   - Streams logs from Log Analytics
   - Exits 0 only if the Job status is `Succeeded`

### Step 3 — Verify

```bash
# Get the RG name
RG=$(az group list --tag environment=prod \
       --query "[?starts_with(name, 'rg-te-prod-')].name | [0]" -o tsv)

# Check job execution history
az containerapp job execution list \
    --resource-group "$RG" \
    --name job-migration-prod \
    -o table

# PG sanity check from any VM in the VNet:
psql "host=<pg_fqdn> port=5432 user=pgadmin dbname=te_prod sslmode=require"
\dt te_prod.*
```

## Connecting to private resources

PG, ACR, and KV are all private-endpoint-only. To reach them from your
laptop:

- **Quickest** — Azure Cloud Shell (already in the tenant, can reach
  private endpoints with peering)
- **Standard** — deploy a small VM in `snet-endpoints`, SSH in, then
  `psql` / `az` from there
- **Best for teams** — Azure Bastion to a Linux jump-box in the VNet
- **Persistent** — Site-to-site VPN or ExpressRoute (use existing
  corporate connectivity)

Add the jump-box to `main.tf` if you want it as code; the VNet outputs
the subnet IDs you need.

## Dev → Prod data migration

When you've validated everything in Dev and want to push the schema +
some seed data to Prod for the first time:

### Option A — Schema only (recommended)

```bash
# 1. Dump just the schema from Dev (no data)
pg_dump --schema-only --no-owner --no-privileges \
        "host=<dev_pg> user=postgres dbname=te_dev" \
        > te_schema.sql

# 2. Apply to Prod from a VM inside the Prod VNet
psql "host=<prod_pg> user=pgadmin dbname=te_prod sslmode=require" \
     -v ON_ERROR_STOP=1 -f te_schema.sql

# 3. Trigger the prod migration workflow with action=load to populate
#    via the framework's normal load_input_data.sql path.
```

### Option B — Schema + reference data

```bash
# 1. Dump schema + only the reference tables (not transactional data)
pg_dump --schema-only "..." > schema.sql
pg_dump --data-only --table=te_dev.organisations \
        --table=te_dev.programs \
        --table=te_dev.classifications \
        "..." > reference.sql

# 2. Rename te_dev schema references to te_prod in both files
sed -i 's/te_dev/te_prod/g' schema.sql reference.sql

# 3. Apply both, in order
psql "..." -v ON_ERROR_STOP=1 -f schema.sql
psql "..." -v ON_ERROR_STOP=1 -f reference.sql
```

### Option C — Full Dev clone (rarely the right move)

For early prod proof-of-concept only. Real prod should have its own data.

```bash
pg_dump "host=<dev_pg> ..." > full_dev.sql
sed -i 's/te_dev/te_prod/g' full_dev.sql
psql "host=<prod_pg> ..." -f full_dev.sql
```

## Backup and restore

PG Flex backups run automatically (PITR). To restore:

```bash
# 1. Take note of the point in time you want to restore to
# 2. Create a new server from the backup
az postgres flexible-server restore \
    --resource-group "$RG" \
    --name "psql-te-prod-restored-$(date +%Y%m%d)" \
    --source-server psql-te-prod-<suffix> \
    --restore-time "2026-06-15T14:30:00Z"

# 3. Update DNS / connection strings to point at the new server
# 4. (Optional) Delete the original server once you're sure
```

If `geo_redundant_backups = true`, you can also `--restore-time` in a
paired region for region-failure DR.

## Rollback

The cleanest rollback for a bad migration:

1. **Code-level** — re-run the workflow with the previous image tag:

   ```text
   Action: deploy
   Image tag: <previous-7-char-sha>
   Change ticket: ROLLBACK-CHG-<original>
   ```

2. **Data-level** — PITR restore to a moment before the change.
3. **Infra-level** — `terraform apply` on the previous commit reverts
   IaC changes. Use `terraform refresh` first to capture drift.

For schema changes, the framework's `ON CONFLICT DO NOTHING` discipline
means re-running an older deploy is generally safe. New columns added
by the bad migration will linger until you DROP them explicitly.

## Monitoring

Prod ships logs/metrics to Log Analytics for:

- **PG queries**: `AzureDiagnostics | where Category == "PostgreSQLLogs"`
- **PG sessions**: `AzureDiagnostics | where Category == "PostgreSQLFlexSessions"`
- **KV access**: `AzureDiagnostics | where Category == "AuditEvent"`
- **ACR pulls/pushes**: `ContainerRegistryRepositoryEvents | order by TimeGenerated desc`
- **Job runs**: `ContainerAppConsoleLogs_CL | where ContainerJobName_s == "job-migration-prod"`

Suggested alerts (add via `azurerm_monitor_metric_alert`):

- PG CPU > 80% for 15 minutes
- PG storage > 85%
- PG failed connections > 10/min
- Migration job failed
- KV secret read failure

## Production hardening checklist

- [ ] Remote Terraform state with state locking enabled
- [ ] Separate Prod service principal, scoped to the prod RG
- [ ] GitHub `production` environment with ≥ 1 required reviewer
- [ ] `ha_mode = "ZoneRedundant"` once budget permits
- [ ] `geo_redundant_backups = true` if DR matters
- [ ] Backups tested via a real restore at least once
- [ ] Diagnostic settings retention ≥ 90 days
- [ ] Azure Monitor alerts for PG health
- [ ] Jump-box VM or Bastion documented for break-glass access
- [ ] Runbook for "PG password rotation" (rotate the KV secret, restart Job)
- [ ] Quarterly review of role assignments — drop anyone who's left

## See also

- `AZURE_DEPLOY.md` — Dev deployment guide
- `infra/terraform-prod/` — Prod IaC
- `infra/terraform-prod/variables.tf` — cost/HA dials
- `.github/workflows/azure-prod-*.yml` — Prod CI/CD
- `ARCHITECTURE.md` — overall framework architecture
- `VCRM.md` — verification cross-reference m
