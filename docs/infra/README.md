# Infrastructure overview

Terraform configs under `infra/` provision the Azure resources for the
PostgreDataMigrationAppWithCSVLoader platform.

## Folder structure

- `infra/terraform/` — shared config. The authoritative resource definitions
  live here. Currently used by dev; adapted into per-environment folders as
  each environment is spun up.
- `infra/terraform-{prod,staging,test}/` — per-environment overrides. Each
  carries its own `backend` block pointing at an environment-specific state
  storage account.
  - `terraform-prod/main.tf` — state in `sttfstateprod7u8hql`
  - `terraform-staging/main.tf` — state account name placeholder (filled in
    via the one-time setup script when the environment is provisioned, #31)
  - `terraform-test/main.tf` — same pattern

## Storage account inventory

| Account | Purpose | Status |
|---|---|---|
| `stpgte{env}{suffix}` (via `pg_storage`) | Postgres `pgdata` file share (50 GB); plus `csv-input` and `run-reports` blob containers | Account active (pgdata is live); the two blob containers are provisioned but unused |
| `sttfstateprod7u8hql` | Terraform state backend for prod | Active |
| staging / test state backends | Terraform state backends for those environments | Not yet provisioned (names will be filled in by the one-time setup script, #31) |

## Where application file storage lives

Not in Azure Blob. Per D4
(`DECISIONS/2026-11-02-file-storage-backend.md`), uploaded CSV file bodies
and row-level import records live in Postgres: BYTEA on
`upload_blobs.content`, written in the same transaction as the audit entry.

The `csv-input` and `run-reports` blob containers in `pg_storage` are
provisioned but not wired to any Python code. See the comment above those
resources in `infra/terraform/main.tf` for the review triggers that would
reopen D4.

## Related

- D4 decision record: `DECISIONS/2026-11-02-file-storage-backend.md`
- Storage audit issue: #151 (closed 2026-11-03)
- One-time cloud setup: #31