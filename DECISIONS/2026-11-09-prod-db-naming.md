# Decision: Azure databases are `te_<env>`, owned by `pgadmin`

Status:  Decided and applied
Date:    2026-11-09
Review:  On trigger (see below)

## Choice

The production database is **`te_prod`** and its owner is **`pgadmin`**, in all three
artefacts that describe it: `infra/terraform-prod/main.tf`, `build/deploy_all.sh` and
`infra/entrypoint.sh`. Option (a) of #172. The schema inside it stays `te_prod`.

**Extended to test and staging (9 Nov 2026, same day):** `te_test` and `te_staging`, also
owned by `pgadmin`, matching `infra/terraform-test` and `infra/terraform-staging`. Dev
stays `te_mgmt_dev` owned by `postgres`: it is local-only and has no stack.

`build/environments/env_prod.example.sql` is the single place that states the name and
owner (`db_name`, `db_owner`). The deployer reads them from the launcher it is about to
run instead of keeping its own copy.

## Context

#172 (RV-S1) found three artefacts disagreeing: Terraform created `te_prod` for `pgadmin`;
the deployer created `te_mgmt_prod` for `postgres`; the entrypoint needed an
`env_prod.sql` that a freshly built image does not contain. Nothing was deployed yet, so
nothing was broken; the first Azure deploy would have failed at the entrypoint with a
cryptic error. The fix had to land before Azure plumbing (#31, #32, #34) resumed.

The 3 Nov decision was to fix all three together in one PR. The product owner chose the
canonical name on 9 Nov 2026.

## Reasoning

- Terraform is the source of truth for the Azure database; matching it is the
  conventional direction for infrastructure-as-code.
- `postgres` owning an application database is poor practice on its own, and
  `te_mgmt_prod` would have kept it.
- The hardcoded copies in the deployer were what drifted. Reading the launcher removes the
  second copy rather than aligning two values by hand.

## Trade-offs accepted

- The Azure environments (`te_<env>`, owner `pgadmin`) now differ from dev
  (`te_mgmt_dev`, owner `postgres`). The reading code does not care; the asymmetry is in
  the data, and it is the difference between a local database and a managed one.
- Where `pgadmin` does not exist (CI, a dev server, the offline install), `deploy_all.sh`
  creates it as `NOLOGIN`. It owns the database and nothing else, so it adds no credential,
  but a stray role appears on those servers.
- The offline installer (`scripts/offline/install.sh`) follows: its prod database is now
  `te_prod`, not `te_mgmt_prod`. Its #60 dry run (due 15 Nov) has not exercised this change.
- A database that already exists with a different owner is reported, not altered.
- `deploy` now requires `APP_USER_PASSWORD`. Without it the application role would be
  created with the template's placeholder password.

## Test and staging

`infra/terraform-test` and `infra/terraform-staging` already created `te_test` and
`te_staging`, while the deployer built `te_mgmt_test` and `te_mgmt_staging`: the same
disagreement as prod. Those stacks are code only (#31), so nothing was deployed. They are
aligned now, before #31 resumes, with the same launcher-driven deployer and the same
`APP_USER_PASSWORD` wiring as prod.

## Reopen trigger

Reconsider if dev is given an Azure stack (then it should follow `te_dev`/`pgadmin` and the
`te_mgmt_` prefix can go), or if the application is ever to run as a role other than the
database owner in Azure.
