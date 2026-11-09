# Changing the T&E tables for tenants

Each tenant has its own copy of the twelve T&E tables in schema `tenant_<slug>`
(`api/tenancy.py`). The deployment's template schema (`te_dev`, `te_prod`, ...) is
built by `build/te_core_schema.sql`. A tenant's copy is made from the template once;
after that, **a change to the template does not reach it by itself**. Tenant T&E
migrations (#184) are what carry a change across.

## How a tenant's T&E schema is kept current

`migrate_tenant(slug)` runs at API start for every tenant, and from
`scripts/create_tenant_admin.py`. For the T&E tables it does one of three things,
serialised per tenant by an advisory lock:

| Tenant state | What happens |
|---|---|
| No T&E tables | Cloned from the template, stamped at the template's version, then upgraded to head |
| Tables, no version table (made before this existed) | Stamped at the baseline `te0001`, then upgraded to head |
| Version table present | Upgraded to head |

The version lives in `alembic_version_te`, inside the tenant schema. The migrations
are in `alembic_te/versions/`; they are a separate chain from `alembic/`, which
versions the uploads objects (`csv_files`, `audit_log`, ...).

An upgrade is one transaction. If it fails, that tenant is left exactly as it was and
the error says why. `te0002` (program consistency, #177) refuses to run if a tenant
already has rows that join two programs, and lists up to 50 of them: fix or remove
those rows, then restart.

## Making a change to the T&E tables

Every change is made in three places, and a test fails if one is missed:

1. **Template**: edit `build/te_core_schema.sql` **and** its identical copy
   `build/schema/postgresql/te_core_schema.sql`. For existing databases, make the
   change idempotent (see phase 4B for the pattern).
2. **Migration**: add `alembic_te/versions/te000N_<name>.py` (revises the previous
   head) doing the same to a tenant schema. Read the schema with
   `op.get_context().opts["version_table_schema"]`. Make `upgrade()` idempotent, and
   write a `downgrade()`.
3. **Stamp**: change the `COMMENT ON SCHEMA ... IS 'te_schema_version=...'` line in
   both schema files to the new revision id.

`tests/system/test_tenant_te_migrations.py` then checks that a tenant reached by any route
(cloned, upgraded from the baseline, adopted from before versioning, cloned from an
older template) has the same columns, constraints, indexes, triggers and functions as
the template, and that both schema files carry the head's stamp. A change made in
the template only, or in the migration only, fails the comparison.

Index and unique-constraint names matter: provisioning renames the cloned ones to the
template's names, so a migration can drop or rename them by name.

## Deploying

- **New template, old tenants.** Deploy the API; tenants are upgraded at start. The
  template schema does not have to be redeployed first, because a tenant upgrade does
  not read it.
- **New tenants.** The template must carry a version stamp. A template deployed by an
  older `te_core_schema.sql` has none, and provisioning a tenant says so and asks you
  to redeploy it with `build/deploy_all.sh`. A template *behind* the API is fine: the
  new tenant is cloned, stamped at the template's version, and brought forward. A
  template *ahead* of the API (stamped with a revision this release doesn't know) is
  refused.
- **Rolling back.** `alembic_te` supports `downgrade`; tests use it to build the
  pre-#177 shape. It is not run automatically.

## Known limits

- Tenants cloned by provisioning before #184 keep PostgreSQL's default **index** names
  (for example `test_cases_phase_id_idx`) on indexes the migrations don't touch. Their
  unique constraints are renamed by `te0002`. New tenants have the template's names.
- The migration SQL and `te_core_schema.sql` are two copies of the same change. The
  comparison test is what keeps them agreeing; there is no generator.
