# Database Environments

Quick reference for the 4 environments this project manages, and the exact
commands to create, update, or delete each one's database. Source of truth
for names: `build/config.env.example` (template) / `build/config.local.env`
(your generated local values) / `build/deploy_all.sh`.

---

## Quick reference

| Environment | Database | Schema | App user | Conn limit | Seeded? |
|---|---|---|---|---|---|
| **dev** | `te_mgmt_dev` | `te_dev` | `te_dev_user` | 10 | yes (`SEED_DEV=true`) |
| **test** | `te_mgmt_test` | `te_test` | `te_test_user` | 15 | yes (`SEED_TEST=true`) |
| **staging** | `te_mgmt_staging` | `te_staging` | `te_stg_user` | 25 | no (`SEED_STAGING=false`) |
| **prod** | `te_mgmt_prod` | `te_prod` | `te_prod_user` | 50 | no (`SEED_PROD=false`) |

Every environment also gets a `csv_uploads` schema in its own database
(same name across environments — no collision, since each environment is a
separate database). Controlled by `CSV_UPLOADS_SCHEMA` (default
`csv_uploads`), not environment-suffixed like the others above.

Connection limits/seed flags come from `build/config.local.env` (generated,
gitignored — your actual local values). The template
(`build/config.env.example`) may show slightly different defaults (e.g.
staging conn limit 20 vs 25) — `config.local.env` is what's actually in
effect once generated; edit it directly to change a running local setup.

---

## Where each environment actually lives

All 4 are **database-level** environments — separate databases on whatever
Postgres server `PGHOST`/`PGPORT` point at. Locally (this machine,
`localhost:5433`), all 4 typically live on the *same* local Postgres
instance as 4 separate databases.

All 4 additionally have dedicated cloud infrastructure under `infra/` — one
Terraform stack per environment, each with its own state file and Azure
resource group so they can never collide:

- `infra/terraform/` — **Dev** cloud target: Postgres as an Azure Container
  App (`postgres:16-alpine` + Azure Files), no HA/backups. See
  `docs/AZURE_DEPLOY.md`.
- `infra/terraform-test/` and `infra/terraform-staging/` — **Test** and
  **Staging** cloud targets: same tier as Prod (managed Flexible Server,
  private VNet, private endpoints, Container Apps Job), sized down on
  backup retention/HA by default. They exist to validate against prod-like
  infra before a real prod release, not to run cheap like Dev. Distinct
  VNet CIDRs (`10.42.0.0/20` test, `10.41.0.0/20` staging, vs Prod's
  `10.40.0.0/20`) so none collide if ever peered. No dedicated deploy guide
  yet — follow `docs/PROD_DEPLOY.md`'s structure (One-time setup, GitHub
  Environment + OIDC, etc.), substituting `test`/`staging` for `prod`
  throughout; each stack's `main.tf` header has the specific substitutions
  called out (state storage account name, backend key).
- `infra/terraform-prod/` — **Prod** cloud target: Azure Database for
  PostgreSQL Flexible Server (managed, HA, PITR backups, private VNet). See
  `docs/PROD_DEPLOY.md`.

Test and Staging's Terraform state storage hasn't been created yet (that's
a one-time, per-environment manual step — see the `backend "azurerm"` block
comment in each stack's `main.tf`), so their `terraform init`/`apply` won't
work until that's done. The `.tf` files themselves are ready to review.

---

## Create / update a database

`build/deploy_all.sh` is idempotent: it creates the database if missing
(`CREATE DATABASE` — skipped if it already exists) and always (re-)applies
the environment's `.sql` file (schema + seed data per the flags above), so
it's also how you push schema changes to an existing environment.

```bash
# One environment
PGHOST=localhost PGPORT=5433 PGUSER=postgres PGPASSWORD=<password> \
  bash build/deploy_all.sh dev

# Several at once (space-separated)
PGHOST=localhost PGPORT=5433 PGUSER=postgres PGPASSWORD=<password> \
  bash build/deploy_all.sh test staging prod

# All 4, plus regenerates env_<env>.sql from templates and config.local.env
# if not already present (see script header for details)
bash scripts/provision_full_test_env.sh
```

For a cloud target (dev or prod), see `docs/AZURE_DEPLOY.md` /
`docs/PROD_DEPLOY.md` instead — those go through Terraform + CI, not this
script.

## Delete a database

There's no dedicated script for this — `build/deploy_all.sh` only ever
creates/updates, never drops. To remove a local environment's database
entirely:

```bash
psql -U postgres -h localhost -p 5433 -d postgres \
  -c 'DROP DATABASE IF EXISTS te_mgmt_<env>;'
```

Then delete the matching `PG_APP_USER_<ENV>` role too, if you want a full
teardown (check nothing else owns objects under it first):

```bash
psql -U postgres -h localhost -p 5433 -d postgres \
  -c 'DROP ROLE IF EXISTS te_<env>_user;'   -- name per table above
```

**Never run this against staging/prod's cloud databases directly** — those
are Terraform-managed. Deleting the *database* out from under Terraform
state will desync infra from reality. To tear down cloud infra, use
`terraform destroy` in the relevant stack; prod additionally requires the
typed `PROD-DESTROY-CONFIRM` + reviewer approval described in
`docs/PROD_DEPLOY.md`.

---

## See also

- `docs/QUICKSTART.md` — first-time local dev setup
- `docs/ENV_VARIABLES.md` — every environment variable, per scenario
- `docs/AZURE_DEPLOY.md` — Dev cloud deployment
- `docs/PROD_DEPLOY.md` — Prod cloud deployment, including the destroy guard
