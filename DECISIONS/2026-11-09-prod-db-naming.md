# Decision: Production database name and owner (#172)

Status:  Decided and applied
Date:    2026-11-09
Review:  When the on-prem and Azure targets are unified, or Azure setup (#31, #32, #34) changes the server layout

## Choice

The Azure production database is **`te_prod`, owned by `pgadmin`**. Terraform creates it, and nothing else names it.

- `infra/terraform-prod/main.tf` creates the database `te_prod` on a server whose administrator login is `pgadmin`.
- The migration job receives them as `PGDATABASE` and `PGUSER`. `infra/entrypoint.sh` writes them into the launcher (`env_prod.sql`) it deploys with, as `db_name` and `db_owner`.
- `build/deploy_all.sh` reads `db_name` and `db_owner` from the launcher instead of hard-coding `te_mgmt_<env>` and `postgres`. A launcher that sets neither keeps the old names.

The on-prem installer is unchanged: it still deploys `te_mgmt_prod`, owned by `postgres`, from the committed template. So there are two production names, one per target, and each is set in one place.

## Context

#172: Terraform created `te_prod` owned by `pgadmin`; the deployer created `te_mgmt_prod` owned by `postgres`; the entrypoint expected an `env_prod.sql` that nothing in the image produced. A fresh image failed at the first step (`Environment file not found`), and had it got past that, it would have created a second database on Azure, where no `postgres` role exists.

## Reasoning

- Azure Database for PostgreSQL has no `postgres` superuser. The deployer's `OWNER = postgres` cannot work there; Terraform's `pgadmin` is the only owner available.
- The launcher is already the file that names the database. Reading the name from it makes the deployer agree with whatever the launcher says, rather than with a second copy of the name.
- The launcher holds a credential, so it must not be in the image (#174). Generating it at run time from the container's own settings removes the missing file without baking anything in. The application password is read by psql from `APP_DB_PASSWORD` (`\getenv`), so it never reaches a file.
- Renaming prod to `te_prod` everywhere was considered and rejected for now. `te_mgmt_prod` is used by the offline installer (`scripts/offline/install.sh`, #60 has a 15 Nov deadline), the prod environment tests, the evals runner, CI and several docs. The change would touch about 15 files and a procedure that is meant to ship.

## Also changed, because the first deployment needs it

- Terraform allow-lists `dblink`, `pg_trgm` and `uuid-ossp` (`azure.extensions`). Azure refuses `CREATE EXTENSION` for anything not on that list, and the schema creates all three, so the first deployment would otherwise have failed partway through.
- Terraform creates the application role's password (`pg-app-password` in Key Vault) and passes it to the job as `APP_DB_PASSWORD`. The runner identity already reads secrets from that vault.
- `build/te_core_schema.sql` no longer prints the application password. A `SELECT set_config(..., :'app_password', ...)` echoed it into the deployment output, which a container job sends to its logs. It now uses `\gset`, which keeps the row out of the output.

## Trade-offs accepted

- Two production names exist until the targets are unified.
- `te_prod` is also the schema name inside the database, so the Azure database and schema share a name (`te_prod.te_prod`). It is harmless, and matches what Terraform already created.
- Verified without a Docker daemon: the entrypoint and deployer were run directly against a fresh PostgreSQL 16 whose only role is `pgadmin`. An image build and a run on Azure itself have not been done.

## Escape hatch

Mount a concrete `env_prod.sql` over the generated one; the entrypoint leaves an existing launcher alone.
