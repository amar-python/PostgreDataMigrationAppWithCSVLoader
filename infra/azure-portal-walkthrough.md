# Azure Portal manual walkthrough — Dev environment

Use this when you want to provision the Azure resources by hand, without
Terraform or CI. Best for one-off testing or learning what the resources
do. Not reproducible — every click-through is slightly different.

**Total time:** about 30-45 minutes.
**Cost:** ~AUD 30-40/mo if left running. Delete the resource group when
you're done to stop charges.

## What you'll create

1. Resource group
2. Azure Container Registry (ACR)
3. Storage account + file share (PG persistent volume)
4. Key Vault (PG password)
5. Log Analytics workspace
6. Container Apps environment
7. PostgreSQL container app
8. User-assigned managed identity
9. Azure Container Instance (per-run migration runner)

## Step 1 — Resource group

1. Go to <https://portal.azure.com>.
2. Top search bar -> **Resource groups** -> **+ Create**.
3. Subscription: your sub. Name: `rg-te-dev-manual`. Region:
   `Australia East` (or your nearest).
4. **Review + create** -> **Create**.

## Step 2 — Azure Container Registry

1. Top search bar -> **Container registries** -> **+ Create**.
2. Resource group: `rg-te-dev-manual`. Name: `acrtedevmanual<XXXX>`
   (must be globally unique — append a 4-digit suffix).
3. SKU: **Basic**.
4. **Review + create** -> **Create**.
5. Open the new ACR -> **Access keys** -> toggle **Admin user** to
   **Enabled**. Note the **Login server** and **Username** + **password**.

## Step 3 — Storage account + file share

1. Top search bar -> **Storage accounts** -> **+ Create**.
2. Resource group: `rg-te-dev-manual`. Name: `stpgtedevmanual<XXXX>`.
   Performance: **Standard**. Redundancy: **LRS**.
3. **Review + create** -> **Create**.
4. Open the new account -> **File shares** -> **+ File share**.
5. Name: `pgdata`. Quota: `50 GiB`. Tier: **Hot**. Create.
6. (Optional) Same account -> **Containers** -> **+ Container** -> `csv-input`
   and `run-reports` (for input CSVs and run outputs).

## Step 4 — Key Vault

1. Top search bar -> **Key vaults** -> **+ Create**.
2. RG: `rg-te-dev-manual`. Name: `kv-te-dev-manual-<XXXX>`. Region: same.
3. Permission model: **Azure role-based access control**.
4. **Review + create** -> **Create**.
5. Open the new vault -> **Access control (IAM)** -> **+ Add ->
   Add role assignment** -> role **Key Vault Administrator** ->
   member **your own user** -> Review + assign. Wait 30 seconds.
6. **Secrets** -> **+ Generate/Import** -> Name: `pg-postgres-password`.
   Value: invent a strong 24-char password. Note it - you'll paste it
   into the PG container app shortly.

## Step 5 — Log Analytics workspace

1. Top search bar -> **Log Analytics workspaces** -> **+ Create**.
2. RG: `rg-te-dev-manual`. Name: `law-te-dev-manual`. Region: same.
3. **Review + create** -> **Create**.

## Step 6 — Container Apps environment

1. Top search bar -> **Container Apps** -> **+ Create -> Container Apps environment**.
   (If you don't see this option directly, create a Container App first
   and it'll prompt you to create the environment.)
2. RG: `rg-te-dev-manual`. Name: `cae-te-dev-manual`. Region: same.
3. Logs destination: **Azure Log Analytics**. Workspace:
   `law-te-dev-manual`.
4. **Review + create** -> **Create**.
5. After it's deployed: open it -> **Azure Files** -> **+ Add**.
   - Name: `pgdata`
   - Storage account: `stpgtedevmanual<XXXX>`
   - File share: `pgdata`
   - Access mode: **Read/Write**

## Step 7 — PostgreSQL Container App

1. Top search bar -> **Container Apps** -> **+ Create**.
2. RG: `rg-te-dev-manual`. Name: `ca-pg-dev-manual`. Region: same.
3. Container Apps environment: `cae-te-dev-manual`.
4. **Container** tab:
   - Image source: **Docker Hub or other registries**
   - Image type: **Public**
   - Registry login server: `docker.io`
   - Image and tag: `postgres:16-alpine`
   - Environment variables:
     - `POSTGRES_USER` = `postgres`
     - `POSTGRES_PASSWORD` = (the password from Step 4)
     - `POSTGRES_DB` = `te_dev`
     - `PGDATA` = `/var/lib/postgresql/data/pgdata`
   - CPU / Memory: `0.5 / 1.0 Gi`
5. **Ingress** tab:
   - Ingress: **Enabled**
   - Ingress traffic: **Limited to Container Apps Environment**
   - Target port: `5432`
   - Transport: **TCP**
6. **Review + create** -> **Create**.
7. After it's deployed: open it -> **Volume mounts** -> **+ Add**:
   - Volume name: `pgdata`
   - Storage type: **Azure Files**
   - Storage name: `pgdata`
   - Mount path: `/var/lib/postgresql/data`
   - Save -> Create new revision.
8. Note the **Application URL** / internal FQDN — that's your `PGHOST`.

## Step 8 — User-assigned managed identity

1. Top search bar -> **Managed Identities** -> **+ Create -> User assigned**.
2. RG: `rg-te-dev-manual`. Name: `id-runner-dev-manual`. Region: same.
3. **Review + create** -> **Create**.
4. After it's deployed: open it -> **Azure role assignments** -> **+ Add**:
   - Scope: **Resource**. Resource: `acrtedevmanual<XXXX>`. Role: **AcrPull**.
   - Add a second: Scope: **Resource**. Resource: `kv-te-dev-manual-<XXXX>`.
     Role: **Key Vault Secrets User**.

## Step 9 — Build & push the image

From your laptop (PowerShell):

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\Migration using ai"

# Login to ACR
az login
az account set --subscription "your-sub-id"
$ACR_NAME = "acrtedevmanual<XXXX>"
$ACR_LOGIN = "$ACR_NAME.azurecr.io"
az acr login --name $ACR_NAME

# Build & push
docker build -f PostgreDataMigrationApp/infra/Dockerfile -t "$ACR_LOGIN/te-migration:dev" .
docker push "$ACR_LOGIN/te-migration:dev"
```

## Step 10 — Run the migration as ACI

1. Top search bar -> **Container instances** -> **+ Create**.
2. RG: `rg-te-dev-manual`. Name: `aci-migration-once`. Region: same.
3. Image source: **Azure Container Registry**. Registry: your ACR.
   Image: `te-migration`. Tag: `dev`.
4. **Networking** tab: **Private**. None — connection is internal.
5. **Advanced** tab:
   - Restart policy: **Never**
   - Environment variables:
     - `PGHOST` = PG internal FQDN from Step 7
     - `PGPORT` = `5432`
     - `PGUSER` = `postgres`
     - `PGPASSWORD` = the password (mark as **secure**)
     - `PGDATABASE` = `te_dev`
     - `TARGET_ENV` = `dev`
   - Command override:
     `["/opt/migration/entrypoint.sh", "full"]`
6. **Identity** tab: **User assigned** -> select `id-runner-dev-manual`.
7. **Review + create** -> **Create**.

Watch the logs:

1. Open the ACI -> **Containers** -> **Logs** tab.
2. You should see the entrypoint banner, the PG ready check, schema
   deploy, CSV load, then eval suite output.
3. When State shows **Terminated** with exit code 0, the run succeeded.

Delete the ACI when done:

```powershell
az container delete -g rg-te-dev-manual -n aci-migration-once --yes
```

## Step 11 — Tear-down

The cheapest way to stop charges: delete the resource group.

1. Top search bar -> **Resource groups** -> `rg-te-dev-manual`.
2. **Delete resource group**. Type the name to confirm. Wait ~3 minutes.

That removes everything in one shot, including the Key Vault (which has
a 7-day soft-delete retention).

## Common mistakes

| Mistake | Symptom | Fix |
| --- | --- | --- |
| Forgot to assign yourself the KV Administrator role before creating the secret | "You do not have permission" when creating `pg-postgres-password` | Add the role in IAM, wait 60 seconds, retry |
| PG ingress set to Accept traffic from anywhere | Public IP exposed; security risk | Re-create the container app with ingress limited to environment |
| ACI uses wrong image tag | Container exits immediately with `manifest unknown` | Verify the tag exists: `az acr repository show-tags --name <acr> --repository te-migration` |
| Volume mount path doesn't match PGDATA | PG keeps reinitialising on restart | `PGDATA` must point inside the mounted folder, e.g. `/var/lib/postgresql/data/pgdata` |
| ACI managed identity missing AcrPull | Container stays in `Waiting -> ImagePullFailure` | Add the role assignment, then re-create the ACI |
