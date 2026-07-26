# Reconstruct PostgreDataMigrationApp from scratch

A single-document guide to rebuild the **PostgreDataMigrationApp T&E framework**
from nothing, driving a fresh Claude session with the
**`te-framework-prompts` v1.1** skill. Covers three target environments and
bakes in the architectural corrections learned during the first Azure
deployment.

At the end you'll have:

- A working CSV → PostgreSQL T&E framework with build / tests / evals layers
- 22 business requirements traced via VCRM
- Per-run gap reports
- An Azure Dev environment that actually runs the migration
- All of it in a clean GitHub repo

Estimated wall-clock: **6-10 hours** spread across 9 phases.

## Who this is for

Pick the column that matches your situation. The steps are the same; the
prerequisites differ.

| | Local Windows dev | Fresh Azure tenant | New team member |
|---|---|---|---|
| **Goal** | Rebuild on the same laptop | Brand-new sub, no infra | Onboard onto an existing repo |
| **Has Python 3.10+** | check | install | install |
| **Has PostgreSQL** | local install | use Azure Flex Server | local install or skip |
| **Has Azure sub** | optional | required | check with team |
| **Has GitHub repo** | yes (clone) | create new | clone team's |
| **Has Claude with skill** | yes | install Claude + skill | install Claude + skill |

## Prerequisites

Run the matching set ONCE before starting.

### Local Windows dev

```powershell
# Open PowerShell as admin
winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
winget install PostgreSQL.PostgreSQL.17 --accept-source-agreements --accept-package-agreements
winget install Git.Git --accept-source-agreements --accept-package-agreements
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements

# Close admin PowerShell, open a normal one, verify:
python --version    # >= 3.10
psql --version      # >= 14
git --version
node --version      # for markdownlint
```

### Fresh Azure tenant

In addition to the local-dev prereqs above:

```powershell
winget install Microsoft.AzureCLI --accept-source-agreements --accept-package-agreements
# Verify:
az --version
az login   # browser pops up; sign in
az account list -o table   # confirm subscription is visible
```

You do NOT need Terraform or Docker on your laptop. We'll use Azure Cloud
Shell which has both pre-installed.

### New team member

Install the local-dev prereqs, then clone the existing repo:

```powershell
cd $env:USERPROFILE\source\repos
git clone https://github.com/<your-org>/PostgreDataMigrationApp.git
cd PostgreDataMigrationApp
```

Then skip to **Phase 8** (verification + first run) — the build phases were
already done by whoever set up the repo.

### Install the skill that drives this rebuild

The `te-framework-prompts` v1.1 skill catalogs all 33 prompts used to
build, validate, document, and deploy this framework. Install once per
Claude install:

1. Get `te-framework-prompts.skill` from the project owner (or your own
   archive at `C:\Users\User\AppData\Roaming\Claude\local-agent-mode-sessions\<...>\outputs\`).
2. In Claude Desktop / Cowork, click **Save skill** on the file card.
3. Verify: ask Claude `What skills do I have?` — `te-framework-prompts`
   should appear.

## Phase 0 — Create the empty project

```powershell
$Root = "$env:USERPROFILE\OneDrive\Desktop\PostgreDataMigrationApp-rebuild"
New-Item -ItemType Directory -Path $Root -Force
cd $Root
git init
git config user.name "Your Name"
git config user.email "you@example.com"
```

Add a minimal `.gitignore` so we don't accidentally commit secrets later:

```powershell
@'
# Python
__pycache__/
*.py[cod]
.venv/

# Environment
.env
.env.*
!.env.example

# Test caches
.pytest_cache/

# IDE
.vscode/
.idea/

# Terraform
**/.terraform/
**/terraform.tfstate*
**/terraform.tfvars
**/*.tfplan

# Per-run reports
evals/reports/

# OS
Thumbs.db
.DS_Store
'@ | Set-Content -Path .gitignore -NoNewline
```

Commit the empty shell:

```powershell
git add .gitignore
git commit -m "Initial commit: empty project shell"
```

## Phase 1 — Framework scaffold

In a fresh Claude Cowork session pointed at the new folder, paste:

> Walk me through reproducing PostgreDataMigrationApp. Start with Phase 1
> using prompts/01-03 from the te-framework-prompts skill.

Claude will load the skill and apply prompts 01, 02, 03:

| Prompt | Produces |
|---|---|
| 01_initial_framework_build | `src/` modules (validator, ingestion, schema, integrity, reporting, migrator, watcher), `tests/conftest.py`, CLI entry points |
| 02_pytest_suite | `tests/test_*.py` — target ~70 unit tests |
| 03_sample_data_and_cli | `sample_data/users.csv`, edge-case CSVs, `auto_migrate.py`, `run_tests.py` |

### Verify Phase 1

```powershell
cd $Root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -m unit
```

Pass criteria: 70+ tests pass, exit 0.

```powershell
git add .
git commit -m "Phase 1: framework scaffold + pytest suite (Tier P offline)"
```

## Phase 2 — Bug audit and fixes

In Claude:

> Apply prompts 04 (exhaustive bug audit) and 05 (fix all bugs) to the
> scaffold from Phase 1.

Expect Claude to:

1. Produce `BUG_REPORT.md` cataloguing ~20 bugs across modules
2. Pause for your approval before fixing
3. Apply fixes module-by-module, adding a test per bug
4. Produce `FIXES_APPLIED.md` tracking each fix

### Verify Phase 2

```powershell
pytest -m unit       # 75+ tests now passing (added bug-reproducer tests)
```

```powershell
git add .
git commit -m "Phase 2: 20 bugs catalogued and fixed, +5 reproducer tests"
```

## Phase 3 — External-agent review (optional)

Skip this phase if you don't have a second-opinion review document. If
you do (e.g. from ChatGPT or another reviewer), apply prompt 07 to plan
fixes, then prompt 08 to catalogue failure modes you discovered.

Output: `PLAN.md` (claims classified AGREED/DISAGREED/PARTIALLY-AGREED)
and `evals/FAILURE_MODES.md` (29-row catalogue).

## Phase 4 — T&E pivot and evals

This is the conceptual shift from "generic CSV migration" to "T&E
framework". Apply prompts 09, 10, 11:

| Prompt | Produces |
|---|---|
| 09_evals_creation | `evals/runner.py`, 23 Tier P scenarios, 1 Tier I, 1 Tier S |
| 10_failure_modes_catalogue | `evals/FAILURE_MODES.md` |
| 11_complete_all_tasks_first | Process-control prompt (use when Claude races ahead) |

### Verify Phase 4

```powershell
python evals\runner.py --tiers p
```

Pass criteria: `total: 23, passed: 23, failed: 0` and exit 0. Tier I and S
will SKIP cleanly since no PG yet.

```powershell
git add .
git commit -m "Phase 4: evals package - Tier P green (23/23)"
```

## Phase 5 — Data loading and verification

Only run this phase if you have your own input CSVs to load. Apply
prompts 12 and 13:

| Prompt | Produces |
|---|---|
| 12_populate_all_tables | `input_data/*.csv`, `load_input_data.sql`, `load_input_data.ps1` |
| 13_verification_steps_in_log | Appended verification block to `load_input_data.sql` |

### Verify Phase 5

```powershell
$env:PGHOST="localhost"
$env:PGPORT="5432"
$env:PGUSER="postgres"
$env:PGPASSWORD="<your password>"
$env:PGDATABASE="migration_test"
.\input_data\load_input_data.ps1
```

Pass criteria: 5 verification sections print at the end (sample rows,
aggregates, reconciliation, duplicates, NULL audit) and no errors.

## Phase 6 — Documentation refresh

After major changes, sync docs with code:

> Apply prompt 15 to audit and update all markdown docs against the
> current code.

Output: refreshed README.md, ARCHITECTURE.md, etc., with stale references
fixed.

## Phase 7 — Layer segregation + VCRM

Apply prompts 18-22 in order. These convert the framework into a
properly-layered T&E system with full traceability.

| Prompt | Produces |
|---|---|
| 18_segregate_build_tests_evals | Physical move into `build/`, `tests/`, `evals/` + `ARCHITECTURE.md` |
| 19_top_level_navigation_readme | The big root README |
| 20_test_conditions_catalogue | `TEST_CONDITIONS.md` |
| 21_map_to_business_requirements | `VCRM.md` Section 1 (22 BRs catalogued) |
| 22_vcrm_traceability_matrix | `VCRM.md` Section 2 (BR-to-test-condition matrix) |

### Verify Phase 7

```powershell
python evals\runner.py --tiers p   # must still be 23/23
```

```powershell
git add .
git commit -m "Phase 7: build/tests/evals split + VCRM with 77% coverage"
```

## Phase 8 — Gap report + lint cleanup

Apply prompts 14, 23, 24, 26:

| Prompt | Produces |
|---|---|
| 14_per_run_gap_report | `evals/gap_report.py` + hook in runner.py |
| 23_gap_analysis_uncovered | `VCRM_GAPS.md` |
| 26_markdown_lint_cleanup | `.markdownlint.json`, `.markdownlintignore`, blank-line + code-language fixes across all docs |

### Verify Phase 8

```powershell
# Re-run evals — VCRM_GAPS_<run_id>.md should auto-generate
python evals\runner.py --tiers p

# Lint should be clean
npx markdownlint-cli "**/*.md"
echo "Lint exit: $LASTEXITCODE"   # should be 0
```

```powershell
git add .
git commit -m "Phase 8: per-run gap report + lint cleanup (0 errors)"
git push origin main
```

**Stop here if you don't need Azure deployment.** You have a working,
locally-runnable T&E framework with full evals, VCRM, and clean docs.

---

## Phase 9 — Azure deployment (with the corrected architecture)

> **IMPORTANT**: Today's first deploy attempt used **Container App PG**
> for the database, which failed at runtime because **TCP ingress between
> apps in a default Container Apps Environment does not route reliably**.
> The migration job could not reach PG even with the static FQDN.
>
> **The fix:** use **Azure Database for PostgreSQL Flexible Server**
> (Burstable B1ms tier ≈ AUD 25/mo). Costs about the same as the broken
> Container App setup, but uses ordinary public DNS + firewall rules, so
> the migration job connects first try.
>
> The prompts below incorporate this correction.

### Phase 9.1 — Containerize (prompt 27, with corrections)

> Apply prompt 27. NOTE these corrections from today's lessons:
>
> 1. Use `postgresql-client` (meta-package), NOT `postgresql-client-15` —
>    Debian Trixie removed v15
> 2. Build the image from the PostgreDataMigrationApp repo root —
>    `COPY build/`, NOT `COPY PostgreDataMigrationApp/build/`
> 3. Make `input_data/` optional — guard the `load` step with a file-exists
>    check so the container doesn't fail when running without local CSVs

Produces: `infra/Dockerfile`, `infra/entrypoint.sh`, `infra/.dockerignore`.

### Phase 9.2 — Terraform Dev (corrected to use Flex Server)

> Apply prompt 28 with this CORRECTION: replace the
> `azurerm_container_app` for PG with `azurerm_postgresql_flexible_server`
> using SKU `B_Standard_B1ms` (Burstable, AUD ~25/mo). Keep the
> `azurerm_container_app_environment` for the migration JOB but drop the
> PG container app and the pgdata volume share. Add an
> `azurerm_postgresql_flexible_server_firewall_rule` allowing the job's
> outbound IP plus your own laptop IP.

Produces: `infra/terraform/main.tf`, `variables.tf`, `outputs.tf`,
`terraform.tfvars.example`, `.gitignore`. Outputs will include
`pg_fqdn` (public FQDN, e.g. `psql-te-dev-<rand>.postgres.database.azure.com`).

### Phase 9.3 — CI/CD workflows (prompt 29)

Apply prompt 29 as-is — the GitHub Actions logic doesn't change with the
PG swap, only the env vars it reads from terraform output (PGHOST is now
the Flex Server FQDN).

Produces: `.github/workflows/azure-infra-deploy.yml` and
`azure-migration-run.yml`.

### Phase 9.4 — Provision and verify (in Azure Cloud Shell)

Don't deploy from your laptop. Use <https://shell.azure.com>:

```bash
# Clone the repo (replace with your URL)
git clone https://github.com/<your-org>/PostgreDataMigrationApp.git
cd PostgreDataMigrationApp/infra/terraform

# Plan + apply
terraform init
terraform plan -out tfplan
terraform apply tfplan   # ~10-15 min for Flex Server provisioning

# Build the image via ACR Tasks (no local Docker needed)
RG=$(terraform output -raw resource_group_name)
ACR=$(terraform output -raw acr_name)
ACR_LOGIN=$(terraform output -raw acr_login_server)
cd ../..   # back to repo root
az acr build --registry "$ACR" --image te-migration:dev --file infra/Dockerfile .

# Create the Container Apps Job
cd infra/terraform
PG_FQDN=$(terraform output -raw pg_fqdn)
PG_USER=$(terraform output -raw pg_admin_login)
PG_PASS=$(az keyvault secret show --vault-name "$(terraform output -raw key_vault_name)" \
            --name pg-postgres-password --query value -o tsv)
CAE=$(terraform output -raw container_apps_environment_name)

az containerapp job create \
  -g "$RG" -n job-migration \
  --environment "$CAE" \
  --image "${ACR_LOGIN}/te-migration:dev" \
  --registry-server "$ACR_LOGIN" \
  --registry-username "$(az acr credential show --name "$ACR" --query username -o tsv)" \
  --registry-password "$(az acr credential show --name "$ACR" --query 'passwords[0].value' -o tsv)" \
  --cpu 1.0 --memory 2.0Gi \
  --replica-timeout 1800 --replica-retry-limit 0 \
  --trigger-type Manual \
  --secrets pg-password="$PG_PASS" \
  --command "/opt/migration/entrypoint.sh" --args "full"

az containerapp job update -g "$RG" -n job-migration --set-env-vars \
  PGHOST="$PG_FQDN" PGPORT=5432 PGUSER="$PG_USER" PGDATABASE=te_dev \
  TARGET_ENV=dev PGSSLMODE=require PGPASSWORD=secretref:pg-password

# Trigger and tail
EXEC=$(az containerapp job start -g "$RG" -n job-migration --query name -o tsv)
echo "Exec: $EXEC"
sleep 30
az containerapp job logs show -g "$RG" -n job-migration --container job-migration --follow true
```

Press Ctrl+C when you see `Done: full`. Exit code 0 = success.

### Verify Phase 9

```bash
# Confirm tables exist
psql "host=$PG_FQDN user=$PG_USER dbname=te_dev sslmode=require" -c "\dt te_dev.*"
# Prompts for the password — paste $PG_PASS
```

Should list all 12 tables.

### Tear-down when done

```bash
cd ~/PostgreDataMigrationApp/infra/terraform
terraform destroy -auto-approve   # ~5 min
```

Stops all charges.

---

## Appendix A — Lessons learned (the corrections folded into Phase 9)

These came up in today's first deploy and informed the Flex-Server
architectural switch:

| # | Lesson | Where it bit us | Permanent fix |
|---|---|---|---|
| 1 | Debian Trixie has `postgresql-client-17`, not `-15` | `apt-get install postgresql-client-15` failed | Use the meta-package `postgresql-client` |
| 2 | Dockerfile build context is the repo root | `COPY PostgreDataMigrationApp/build/` failed when built from the PostgreDataMigrationApp repo | Strip the `PostgreDataMigrationApp/` prefix from COPY paths |
| 3 | `input_data/` may not be in the image | `COPY input_data/` fails if the dir isn't tracked | Drop the COPY; make load step check file-exists before running |
| 4 | `az container create` needs explicit `--os-type Linux` + `--location` + `--cpu` + `--memory` (newer versions) | InvalidOsType and ResourceRequestsNotSpecified errors | Always specify all four |
| 5 | `--acr-identity` + admin-enabled ACR is fragile | Authentication path errors | Use plain `--registry-username` + `--registry-password` instead |
| 6 | Bash line-continuations in az `--env-vars` swallow values | All env vars showed as `{ "name": "X" }` with no value | Use `--set-env-vars` as a follow-up, all on one line |
| 7 | TCP ingress between Container Apps in a default env doesn't route | Job's `wait_for_pg` timed out for 60 s every run | **Don't use Container App PG**. Use Flex Server (public FQDN + firewall) |
| 8 | Static FQDN (no revision suffix) didn't help either | Same TCP timeout | Same fix as #7 |
| 9 | `--follow true` for job logs requires installing the `containerapp` CLI extension | First `logs show` call returned only warnings | Accept the `Y` install prompt; takes 30 s |

## Appendix B — Common pitfalls and how to recognise them

| Symptom | What it usually means | Fix |
|---|---|---|
| `psql: command not found` (Windows) | PG bin folder not on PATH | Add `C:\Program Files\PostgreSQL\17\bin` to System PATH |
| pytest finds 0 tests | Wrong dir or missing `__init__.py` | `pytest --collect-only` to see what's discovered |
| `validate_csv()` import error | Stale `__pycache__` | `Get-ChildItem -Recurse -Filter __pycache__ \| Remove-Item -Recurse -Force` |
| `npx markdownlint-cli` returns thousands of errors | Missing `.markdownlint.json` | Re-run Phase 8 prompt 26 |
| `terraform apply` hangs on PG Flex Server | First-time provisioning genuinely takes ~10-15 min | Wait. Tail `az postgres flexible-server show -g "$RG" -n "<name>" --query "state"` |
| ACI / Job container can't reach PG | Firewall rule missing for your egress IP | `az postgres flexible-server firewall-rule create` with your IP |
| GitHub Actions OIDC fails with `AADSTS70021` | Federated credential subject mismatch | Subject must be `repo:<org/repo>:ref:refs/heads/<branch>`, not just the branch name |

## Appendix C — Skill prompt index (v1.1)

The skill at `te-framework-prompts.skill` contains all 33 prompts. Phase
references in this doc map to:

| Phase | Prompts used |
|---|---|
| 1 | 01, 02, 03 |
| 2 | 04, 05 (06 if doc drift) |
| 3 | 07, 08 (optional) |
| 4 | 09, 10, 11 |
| 5 | 12, 13 |
| 6 | 15, 16, 17 (15 most common) |
| 7 | 18, 19, 20, 21, 22 |
| 8 | 14, 23, 24, 26 |
| 9 | 27, 28, 29, 30, 31, 32, 33 (with corrections from Appendix A) |

To see any individual prompt's full text, extract the skill zip:

```powershell
Expand-Archive -Path te-framework-prompts.skill `
                -DestinationPath $env:USERPROFILE\Desktop\te-prompts-extracted `
                -Force
explorer $env:USERPROFILE\Desktop\te-prompts-extracted\te-framework-prompts\prompts
```

## Appendix D — Decision tree: which DB to use in Azure

```text
                       Need PG in Azure?
                            |
            +---------------+----------------+
            |                                |
        Dev only?                       Prod-grade?
            |                                |
    Burstable Flex Server              GP Flex Server
    (B_Standard_B1ms)                  (GP_Standard_D2s_v3)
       ~AUD 25/mo                         ~AUD 180/mo
    public DNS + FW rule              VNet + private endpoint
            |                                |
            +---------------+----------------+
                            |
                  Container Apps Job
                  reads PGHOST = the FQDN
                            |
                  Migration runs cleanly
                  (no internal TCP routing issues)
```

**Do not use** `azurerm_container_app` with `transport = "tcp"` and
`external_enabled = false` for the database tier. It looks reachable but
client-to-client TCP between apps in a default Container Apps Environment
isn't routable. This is the architectural correction that defines
Phase 9.2.

## Where to go next

Once Phase 8 (local) or Phase 9 (cloud) is green:

- **Close the BR-15 gap** — the conn_limit assertion script we wrote
  today (`tests/suites/test_05_*.sql` S09 + S10) catches typos in the
  per-env `\set conn_limit` values. Run the full suite after deploy to
  verify Dev shows `rolconnlimit = 10`.
- **Push the te-framework-prompts skill v1.2** — add this RECONSTRUCT.md
  as prompt 34 so future reconstructions reference the corrections
  inline.
- **Wire up Tier X cross-engine evals** — see VCRM_GAPS BR-02. Start with
  SQLite (file-based, zero infra).
- **Move to Prod** — the `infra/terraform-prod/` folder already has the
  Flex Server + VNet + private endpoint pattern. Read `PROD_DEPLOY.md`.

## See also

- `te-framework-prompts.skill` — the 33-prompt catalogue this guide
  drives
- `ARCHITECTURE.md` — the build/tests/evals three-layer model
- `VCRM.md` — the 22 business requirements and their verification
- `AZURE_DEPLOY.md` — the original (pre-correction) Azure guide
- `PROD_DEPLOY.md` — the Flex Server + VNet + private endpoints prod
  recipe (always correct)
