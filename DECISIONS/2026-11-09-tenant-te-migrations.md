# Decision: Versioned migrations for tenant T&E tables (#184)

Status:  Decided and applied
Date:    2026-11-09
Review:  When there are live tenants, or when a second T&E schema change is made (does the two-copy cost hold up?)

## Choice

The twelve T&E tables in each tenant schema get their own Alembic chain, `alembic_te/`, with its version table `alembic_version_te` inside the tenant schema. `migrate_tenant` clones a new tenant from the template and stamps it, adopts a tenant from before versioning at a baseline (`te0001`), and upgrades every tenant to head. A parity test proves a migrated tenant equals the template.

Chosen by the owner on 9 Nov from three options:

- **Alembic chain + parity test** (this)
- Apply `te_core_schema.sql` to tenants (one source of truth, but it is a psql script that creates databases and roles, and the API would need psql at run time)
- Reconcile from the template (smallest, but cannot backfill `program_id` or replace foreign keys safely)

## Context

`provision_te_tables` cloned only missing tables, so a template change never reached a tenant that already had them. #177 (composite foreign keys, `program_id`) made that concrete: every tenant created before it kept the old shape and the old protection against cross-program rows.

## Reasoning

- #177 is a data-aware change (backfill, a check that can fail on existing rows, replacing constraints). Only a migration can do that safely and say what it found.
- A tenant needs to know which version it is at. A version table per tenant schema matches how the uploads chain already works.
- The template is still what new tenants are cloned from, so provisioning stays cheap; the chain only has to carry *changes*. The baseline adopts what exists rather than re-creating the tables, so there is no second copy of the original DDL.

## Trade-offs accepted

- **Each T&E change is written twice**: in `te_core_schema.sql` (both copies) and as a migration. The parity test fails on any difference, which is the guard; there is no generator. See `docs/TENANT_SCHEMA_MIGRATIONS.md`.
- A failing tenant stops API start (as the uploads chain does for duplicate registry rows). One tenant's bad data takes the API down until it is fixed. The upgrade rolls back, so nothing is half-applied, and the error names the tenant and the rows. A per-tenant "needs attention" state was not built.
- The "old shape" test fixture comes from the chain's own `downgrade`, not an independent dump of the pre-#177 schema. The test asserts what that shape is, so the downgrade is not taken on trust.
- Tenants cloned by the old provisioning keep default index names on indexes the migrations don't touch (listed in the doc). Only names.

## Also changed, found by the parity test

- `CREATE TABLE ... LIKE ... INCLUDING ALL` names copied indexes and unique constraints by PostgreSQL's defaults, not the template's, so every tenant already differed from its template in index names, and `te0002`'s `uq_*` constraints would have been added a second time beside the default-named ones. Provisioning now renames the copies to the template's names, and `te0002` adopts an equivalent unique constraint instead of adding another.
- The runtime role cannot rewrite `alembic_version_te` (added to `APPEND_ONLY`, like `alembic_version`).
- The template schema carries `COMMENT ON SCHEMA ... 'te_schema_version=te0002'`; a test fails if a migration is added and the stamp is left behind.
