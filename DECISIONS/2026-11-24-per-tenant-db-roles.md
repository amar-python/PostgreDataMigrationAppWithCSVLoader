# Decision: One database role per tenant, switched to per request (#297, OIT-012)

Status:  Decided; code in the #297 pull request
Date:    2026-11-24
Review:  Before the first external tenant, and if the number of tenants reaches the hundreds (one role each)

## Choice

Each tenant gets its own PostgreSQL role, with rights only on its own schema (`tenant_<slug>`). Every database connection a signed-in request borrows runs `SET ROLE` to that tenant's role, and returns to the login role when it goes back to the pool. A query that reaches another tenant's schema is refused by PostgreSQL (`InsufficientPrivilege`). Before this change it returned the other tenant's rows.

The owner chose this on 24 Nov from the three options in the 20 Nov fix plan on #297:

- **(a) A role per tenant, `SET ROLE` per request** (this one)
- (b) Row-level security keyed on a `tenant_id` session variable. Not chosen: tenants have a schema each, not shared tables with a tenant column, so it would mean policies on every table in every tenant schema, and isolation would rest on a session variable the application sets.
- (c) Accept the risk, with compensating controls (schema-qualified queries and the standing tests). Not chosen: a missed qualification in future code would leak data instead of failing.

This supersedes the open question in `docs/SECURITY_REVIEW_PACK.md` §4 and finding F7. It is the "per-tenant roles" that the Milestone 0 design (section 5) described and M2b left out.

## How it works

| Piece | Where |
|---|---|
| Role name `app_t_<slug>_<8 hex of the database name>`, NOLOGIN, with a `COMMENT ON ROLE` saying which tenant and database it serves | `api/tenancy.py` `role_for` |
| Created or updated after every tenant migration: USAGE and CREATE on the tenant's schema, read and write on its tables, read and insert only on the append-only ones, default privileges for tables a later migration adds | `api/tenancy.py` `provision_tenant_role`, called from `migrate_tenant` |
| The runtime role (`APP_DB_USER`) is a member `WITH INHERIT FALSE, SET TRUE`, and its own rights on tenant schemas are revoked. Without `SET ROLE` it reaches no tenant's data | same |
| `tenant_scope` routes a signed-in request with `tenant(slug)`, which sets the schema and the role | `api/auth.py` (one line changed) |
| `Conn` runs `SET ROLE` on borrow, committed on its own so a later rollback cannot undo it. On return it always rolls back, runs `RESET ROLE` and commits, error or not. A connection that cannot be reset is closed, not pooled | `api/db.py` `Conn` |

### Decisions inside the decision

- **The name includes the database.** The fix plan said `app_t_<slug>`. Roles belong to the whole cluster, and environments often share one (#173, RV-S3). With the plain name, tenant `acme` in Dev and in Prod would be the same role, and Dev's runtime role could connect to the Prod database (CONNECT is granted to PUBLIC by default) and `SET ROLE` into Prod's tenant. The suffix is a hash, not the database name itself, so the name stays inside PostgreSQL's 63-byte limit for any database name (the slug is at most 41 characters).
- **Who owns the tables the loader makes at run time.** The per-upload `csv_*` tables are created during a request, so the tenant role creates them and owns them. It can then drop them on delete, as the runtime role could before. Tables the owner or the runtime role made before this change are handed to the tenant role on the next migration. Tables from migrations stay owned by the owner (PG_USER).
- **Existing tenants need no separate migration step.** API start already runs `migrate_tenant` for every tenant (`_migrate_existing_tenants`), and that now provisions the role. Nothing is dropped or rewritten. On the first start after the upgrade, the runtime role loses its direct rights on tenant schemas and gains membership of each tenant role. No Alembic revision was added: roles are cluster objects, not part of one schema's shape.
- **Shared and control schemas.**
  - Login, session lookup, logout and password changes run before a tenant is known, so they run as the runtime role. Tenant roles have no rights on the control schema (`users`, `sessions`, `tenants`, `memberships`), the deployment's default schemas, or the T&E template.
  - The one control read inside a tenant request, the tenant's `allow_self_approval` flag, now comes with the session (`accounts.session_for`), so the tenant role needs no rights on `control.tenants`.
  - Each tenant's audit log lives in its own schema and is written as the tenant role.
  - The admin password reset changes `control.users` as the runtime role, then writes the tenant's audit entry as the tenant role in the same transaction (`api.db.acting_role`).
- **Dev without `APP_DB_USER`.** The API then connects as the owner. The owner is a member of every tenant role, so requests still switch to the tenant role and are refused in the same way. CI runs this way, so the whole suite runs signed-in requests as tenant roles.
- **Anonymous and API-key requests** keep the deployment's default schemas and the runtime role, as before. #298 is changing that path separately. This change does not touch it.

## Trade-offs accepted

- **One role per tenant per database.** Roles are cheap, but a deployment with hundreds of tenants has hundreds of roles to list and audit. Dropping a tenant must now also drop its role, as the owner, after the schema: `api.tenancy.drop_tenant_role` runs `DROP OWNED BY` and then `DROP ROLE`. No tenant-deletion command exists yet. The tests, the e2e fixtures and `scripts/perf_import.py` call the helper.
- **The environment owner (`te_<env>_user`, PG_USER) now has CREATEROLE.**
  - `build/te_core_schema.sql` (both copies) creates it with CREATEROLE, and adds it on a re-deploy. On PostgreSQL 16 and later, CREATEROLE only lets a role manage roles it created itself, so the owner cannot touch other environments' roles or make a superuser.
  - An owner without CREATEROLE stops API start at the first tenant migration. The error names the role and the fix (`ALTER ROLE <owner> CREATEROLE`, run as a superuser or the server administrator), and nothing is half-applied.
  - **Upgrade step for an existing environment:** re-run `build/deploy_all.sh <env>`, or run that one `ALTER ROLE`, before starting the new release. It is reversible (`NOCREATEROLE`). It changes a real database, so it is the owner's to run, not CI's.
  - Found by CI's container install jobs, whose owner is `te_prod_user`, not a superuser.
- **Two extra round trips per borrowed connection** (`SET ROLE` on borrow, `RESET ROLE` on return). Negligible next to the queries.
- **The runtime role can still switch into any tenant of its own database.** That is inherent to (a): one API process serves all tenants. What changes is that it must name the tenant to do so. Code that forgets to switch reaches no tenant at all, and code that switches to tenant A cannot read tenant B.
- PostgreSQL 16 or later is needed for `WITH INHERIT FALSE, SET TRUE`. That is already the supported minimum (README).

## Evidence

- `tests/system/test_tenant_isolation.py`:
  - `test_a_query_as_tenant_a_on_tenant_bs_schema_fails_at_the_database` is the #297 acceptance test. As tenant A's role, reading tenant B's registry, audit log, upload and T&E tables, and a `csv_*` table B's upload created afterwards, raises `InsufficientPrivilege`. So do the control schema, the default uploads schema and the T&E template.
  - Also: the tenant role's rights end at its own schema; a signed-in upload's table is owned by the tenant role, so the request ran as it; a pooled connection is back to the login role after use, with and without an error.
- `tests/system/test_runtime_role.py` `test_a_signed_in_tenant_works_through_its_own_role`: logged in as the real runtime role, upload, row review, history, audit log and verify, and a staged import all work. The runtime role on its own cannot read the tenant's schema, and its membership is `INHERIT FALSE, SET TRUE`.
- With `SET ROLE` disabled in `Conn`, the acceptance test and the request-role test fail. Checked once by hand on 24 Nov.
