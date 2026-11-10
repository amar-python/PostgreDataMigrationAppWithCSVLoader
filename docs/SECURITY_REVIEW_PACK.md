# Security review pack: threat model before the first external tenant (#112)

ADR-0003 (Risk) recommends a security review before the first external tenant, now that the platform is multi-tenant and customer-facing. **This pack is preparation, not the review.** It gives the reviewer a map of the system, the controls in each area with the code and tests that back them, the checks that have been run, and the weaknesses the author found while preparing it, so the review can spend its time on judgement instead of orientation.

| | |
|---|---|
| Owner and reviewer | **To be decided by the product owner** (#112). Nothing here has been independently reviewed |
| Prepared | 2026-11-10, at `main` plus the ART milestones M5 to M7 (PRs #226 to #228) |
| Scope (from #112) | Authentication (sessions, lockout, OIDC) · tenant isolation (schema per tenant) · the role matrix · upload handling · deployment secrets |
| Method | Read the code in scope; run the existing negative tests; verify each observation below by calling the API or reading the code. Nothing was exploited against a deployed system |

## 1. Orientation

```
 browser (React, sessionStorage token) ──HTTPS──▶  FastAPI (api/)  ──libpq──▶  PostgreSQL
                                                    │  per-router dependencies:
 scripts / services (X-API-Key) ──────────────────▶ │  tenant_scope → role check (allow) → handler
                                                    │  rate limit middleware (per peer IP)
 IdP (Keycloak / Entra ID), optional ◀── key fetch ─┘
```

- **Trust boundaries:** the internet or intranet to the API; the API to PostgreSQL; the API to the IdP (optional, key fetch only); a tenant to every other tenant.
- **Assets:** uploaded data and its preserved originals; the audit trail; credentials (passwords, session tokens, the shared API key, database roles); tenant separation.
- **Actors:** four tenant roles (`uploader`, `reviewer`, `tenant_admin`, `auditor`, `docs/ROLES.md`); a request with the shared API key and no session (scripts and services; in `dev` with no key set, anyone); an operator with database access.
- **Not exposed over the API, on purpose:** creating tenants, creating users, changing roles. Those are `scripts/create_tenant_admin.py` and database operations.

## 2. Run the evidence

```bash
make security-evidence                 # needs PostgreSQL, like the rest of tests/system
cd csv-table-hub-main && npm test      # the frontend suite (17 files, 171 tests); a CI job now runs it. Includes the print-window HTML escaping
python scripts/check_bundle_egress.py csv-table-hub-main/.output          # after npx vite build
```

Run on 2026-11-10: `make security-evidence` passed (231 tests, 0 failed, about 6 minutes), `pip-audit -r api/requirements.txt` found no known vulnerabilities, and `npm audit --omit=dev` found 0.

## 3. Authentication

**Controls**

| Control | Where |
|---|---|
| Passwords hashed with stdlib scrypt (N=2^14, r=8, p=1), a random salt per hash, constant-time compare; at least 12 characters | `api/services/accounts.py` |
| An unknown user costs the same time as a wrong password (a dummy hash is checked); wrong tenant, unknown user, wrong password, inactive user and locked account all return the same 401 | `accounts.login` |
| Lockout: 10 failed sign-ins in 15 minutes lock the account for 15 minutes (`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`); a wrong current password on a password change counts too | `accounts._record_failure` |
| Session tokens: 256 bits of randomness, returned once, stored only as SHA-256; 12-hour lifetime; logout revokes; a password change ends the other sessions and an admin reset ends all of them | `accounts`, `api/auth.py` |
| Bearer header, not cookies, so there is no CSRF surface. The browser keeps the token in `sessionStorage` (gone when the tab closes) | `csv-table-hub-main/src/lib/session.ts` |
| OIDC: RS256 or ES256 only (`alg: none` refused); signature, issuer, audience, `exp`, `iat` all required; the user must already exist locally and be a member of the tenant (nobody is created from claims); key set over `https://` (5 s timeout) or a `file://` key file; plain `http://` refused at startup | `api/oidc.py` |
| Shared API key: constant-time compare; the API refuses to start outside `dev` without one | `api/auth.py`, `api/main.py` |

**Evidence:** `tests/system/test_accounts.py`, `test_password_reset.py`, `test_oidc.py`, `test_oidc_https.py` (the `https://` fetch, key rotation, an untrusted certificate and an IdP that is down or hangs, against a local TLS server), `tests/unit/test_api_hardening.py` (auth fails closed outside `dev`, rate limiting).

**Not yet evidenced:** one sign-in against the real IdP (#113, `docs/OIDC_REAL_IDP_CHECK.md`).

## 4. Tenant isolation

**Controls**

- Each tenant has its own schema, `tenant_<slug>`, holding its registry, audit log, uploaded tables, T&E tables and workflow tables. The slug is constrained to `^[a-z][a-z0-9_]{1,40}$` in `control.tenants`.
- The signed-in tenant is carried in a context variable set by `tenant_scope` from the session, and every data query takes its schema from `uploads_schema()` or `te_schema()` and quotes it with `sql.Identifier`. There are 36 such uses in `api/` outside `api/tenancy.py` itself. The only direct uses of the default-schema settings are start-up, the health check and migrations (checked by grep, 2026-11-10).
- A request with no session reaches only the default schemas, never a tenant's.
- `migrate_tenant` swaps a global setting while Alembic runs, so it is serialised with a lock; its callers are start-up and command-line scripts, none in a request path.
- Advisory-lock keys include the schema, so one tenant's import can't block another's.

**Evidence:** `tests/system/test_tenant_isolation.py` (the standing cross-tenant negative tests: list, read and delete across tenants, no-session requests, per-tenant duplicate detection, per-tenant audit logs, concurrent requests never seeing another tenant's schema), `test_tenant_te_migrations.py`, `test_versioned_datasets.py` (versions and dedup per tenant and per no-session registry), `test_staged_import.py`.

**Questions for the reviewer**

1. The Milestone 0 design said "schema per tenant, using `SET LOCAL search_path` and **per-tenant roles** inside each request's transaction". What was built is schema-qualified queries with **one** runtime role that holds privileges on every tenant schema (see F7). Is that enough for a customer-facing deployment, or must the database enforce isolation too?
2. `tenant_scope` is an `async` dependency on purpose: the schema is a context variable that only an async dependency sets in the context the endpoint's worker thread copies. Is there any way a new route, or a synchronous dependency added later, could run before the scope is set?

## 5. Role matrix

**Controls**

- `PERMISSIONS` in `api/auth.py` maps each action to roles; `allow(action)` is a dependency on every protected route and returns 403 otherwise. `docs/ROLES.md` is the same table, and a test fails if the two disagree.
- A signed-in member can't approve data they uploaded or submitted unless the tenant allows it (decision 5). Destructive deletes need the `delete_file` permission and `API_ALLOW_DESTRUCTIVE`; every path that drops a table goes through `api/services/destructive_ops.py` (#175).
- Role changes aren't available over the API.

**Evidence:** `tests/system/test_roles.py` tries every role against every route and checks both the document and the allow and deny results; `test_staged_import.py` (`SelfApproval`).

**Questions for the reviewer**

1. `tenant_admin` holds every permission, including upload and approve. Separation rests only on the "not your own upload or submission" rule. Is that acceptable, or should an editor also be barred from approving the rows they edited?
2. `auditor` can read stored rows and download preserved originals (`read_rows`), not only the audit trail. Is that intended?
3. A request with the shared key has no role and is never role-checked. Is that acceptable once there are external tenants (F8)?

## 6. Upload handling

**Controls**

- A file name is never used as a path or a SQL identifier. Tables are named `csv_<slug>_v<n>` where the slug is lower-case ASCII `a-z0-9_`, at most 40 characters; every identifier goes through `sql.Identifier`; values are parameterised or loaded with COPY, quoted; column names are sanitised and validated; column types are a fixed whitelist; the T&E target must be one of `TE_TABLES`.
- Row cap (100,000), error-report cap, header-mapping and type lists are bounded; `contentBase64` is validated.
- The CSV is parsed by our own parser, which never evaluates anything. Exports neutralise spreadsheet formulas, in the browser and on the server (`api/services/reports.py`).
- Originals are kept byte for byte, insert-only, with a SHA-256. Errors return structured JSON, not stack traces.
- The frontend renders values through React. The single hand-built HTML sink is the print window in `src/lib/export.ts` (`document.write`, same origin as the app and its `sessionStorage` token). It escapes all five HTML-significant characters in the title, headers and every cell, and only two callers use it, both through `rowsToHtmlTable`.

**Evidence:** `tests/unit/test_security.py` (static scans), `tests/system/test_ragged_rows.py`, `test_original_bytes.py`, `test_header_mapping.py`, `test_versioned_datasets.py` (hostile file names), `test_reports_and_policy.py` (formula neutralisation), `export.test.ts` (**new**: the print-window HTML escaping had no test; breaking the escaping now fails it).

## 7. Deployment secrets

**Controls**

- The API won't start outside `dev` without `API_KEY`. The runtime database role is made by `scripts/create_app_role.py` with a random password, written to a `0600` file and never printed. `*.tfvars` and `build/config.local.env` are git-ignored.
- In the Azure Terraform, the database passwords are `random_password` resources stored in Key Vault, and the Container App reads them through Key Vault secret references, so they are not in the image.
- `tests/unit/test_security.py` scans for hard-coded credentials and for passwords echoed by scripts.

**Not covered by anything in the repository:** the API's own secrets (`API_KEY`, `APP_DB_PASSWORD`, the `OIDC_*` settings). `infra/` deploys the migration and evals container, not the application (BR-38, #128), so there is no deployment definition to review for them yet (F9).

## 8. Weaknesses the author found

Severities are the author's estimate, for the reviewer to confirm or overrule. "Verified" says how it was confirmed. None has been fixed: whether to fix, accept or defer each is the review's output.

| ID | Area | Finding | Est. | Verified | Suggested fix |
|---|---|---|---|---|---|
| F1 | Upload | **No limit on the request body before it is parsed.** Every size check (`MAX_UPLOAD_BYTES`) runs on the parsed JSON, so a signed-in uploader, or anyone with the key, can make the server buffer an arbitrarily large body first. | Medium (authenticated denial of service) | Code: `api/routers/csv_routes.py` (preview, upload), `import_routes.py` (stage) check `len(req.content)` after Pydantic has parsed the body; nothing earlier limits it | Reject on `Content-Length` in a middleware, and cap streamed bodies; also set the proxy's limit |
| F2 | Deployment | **The unauthenticated health check discloses internals**: database name, `host:port`, the exact PostgreSQL version and the schema name. `/docs`, `/redoc` and `/openapi.json` are open too (the full route map). | Low | Called the API with no credentials: all four returned 200 with those details | `/api/health` returns only `{"status": ...}`; disable the docs or require auth outside `dev` |
| F3 | Authentication | **Rate limiting keys on the peer IP and ignores `X-Forwarded-For`** (deliberately, so it can't be spoofed). Behind a reverse proxy every caller shares the proxy's address, so one client can exhaust the budget for everyone, and the brute-force limit isn't per attacker. Counters are per instance. | Medium (availability) unless the proxy limits per client | Code: `api/ratelimit.py` `_client_id` | Trust `X-Forwarded-For` only from a configured proxy address, or limit at the proxy; say which in the deployment guide |
| F4 | Authentication | **scrypt cost is below current guidance** (N=2^14; OWASP currently suggests N=2^17 with r=8, p=1) and hashes aren't upgraded when a user signs in. | Low to medium | Code: `accounts._N, _R, _P`. The hash string stores its parameters, so an upgrade is possible | Raise N, and re-hash on a successful sign-in when the stored parameters are weaker |
| F5 | Authentication | **Lockout is per username**, so anyone who knows a username can keep it locked (10 bad attempts every 15 minutes). OIDC sign-in ignores the lockout (it never uses the password). | Low | Code: `accounts.login`, `login_trusted` | A product decision: keep, or lock per username and client address |
| F6 | Authentication | **Sessions have a fixed 12-hour life, no idle timeout, and expired or revoked rows are never deleted.** | Low | Code: `accounts._new_session`, `session_for`; no `DELETE FROM ...sessions` anywhere in `api/` or `scripts/` | Add an idle timeout, and purge expired sessions |
| F7 | Tenant isolation | **One runtime role can reach every tenant's schema.** Isolation is application-level (schema-qualified queries, tested), not database-level as the Milestone 0 design described; and the role is cluster-wide (#173, open). A missed schema qualification in future code would be a cross-tenant leak, not a database error. | Medium (design) | Code: no `SET ROLE` or per-tenant grants anywhere; `api/db.py` `grant_runtime` grants on all tenant schemas | Decide whether per-tenant roles (or row-level security) are required before the first external tenant |
| F8 | Role matrix | **The shared API key bypasses tenants and roles**: it reaches the default schemas with full rights, has no per-key identity (every action audits as `api_key`) and one value for everyone. The open item in the VCRM for BR-36. | Medium until it is retired or scoped | Code: `api/auth.py` `tenant_scope`; `docs/ROLES.md` | Per-service keys with scopes and rotation, or retire it for scripts that can use a session |
| F9 | Deployment | (a) Key Vault and the container registry are created with public network access **"temporarily enabled ... flip to false after bootstrap"**, a manual step that can be forgotten. (b) The Terraform state backend holds the generated passwords, so access to that storage account is access to the secrets. (c) The API's own secrets have no deployment definition (#128). | Medium (configuration) | Code: `infra/terraform-prod/main.tf` (`public_network_access_enabled = true` on the vault and registry; `backend "azurerm"`); grep found no `API_KEY` or `OIDC_` in `infra/` or the deploy docs. **The live state of the vault and the state storage account was not checked** | Check the live settings; make the flip part of the pipeline; restrict and encrypt the state account |
| F10 | Deployment | **The start-up log prints the first four characters of the API key** as a "fingerprint". | Low | Code: `api/main.py` | Log a hash prefix instead |
| F11 | Deployment | **`SECURITY.md` names a personal Gmail address** as the vulnerability-report contact, marked as a placeholder (#57). External tenants will expect a real channel. | Low (process) | Read `SECURITY.md` | Replace with a monitored `security@` address |

Reviewed and **not** a finding: the print window's HTML escaping (complete, now tested); tokens in `sessionStorage` rather than `localStorage`; dependency advisories (none today); SQL construction (identifiers always quoted, values always parameterised); the login endpoint's responses (uniform).

## 9. Not covered

No penetration test; no live-environment check (Key Vault and registry network state, the state storage account, TLS termination, the proxy in front of the API); no secret scan of git history; no review of PostgreSQL configuration, backups or monitoring; no check of the browser front end beyond the sinks above; no IRAP or ISM assessment (#49); and OIDC against the real IdP (#113) is still to do.

## 10. Review record

| | |
|---|---|
| Owner | |
| Reviewer | |
| Date | |
| Outcome | |

| Finding | Decision (fix, accept, defer) | Owner | Issue |
|---|---|---|---|
| F1 to F11 | | | |
