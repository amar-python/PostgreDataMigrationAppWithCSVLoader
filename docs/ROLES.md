# Roles and permissions (BR-36, #94)

Every member of a tenant has one role (ADR-0003). This table is enforced by `PERMISSIONS` in `api/auth.py`. `tests/system/test_roles.py` fails if the two disagree, and it tries every role against every route.

| Action | Route | uploader | reviewer | tenant_admin | auditor |
|---|---|---|---|---|---|
| preview | `POST /api/csv/preview` | ✓ | | ✓ | |
| upload | `POST /api/csv/upload`, `POST /api/csv/uploads` | ✓ | | ✓ | |
| list_files | `GET /api/csv/files`, `GET /api/csv/uploads` | ✓ | ✓ | ✓ | ✓ |
| read_rows | `GET /api/csv/tables/{table}/rows`, `GET /api/csv/uploads/{id}/original`, `GET /api/csv/uploads/{id}/rows`, `GET /api/csv/uploads/{id}/rows/{n}/history` | ✓ | ✓ | ✓ | ✓ |
| list_te | `GET /api/te/tables` | ✓ | ✓ | ✓ | ✓ |
| delete_file | `DELETE /api/csv/files/{id}` | | | ✓ | |
| read_audit | `GET /api/audit/log`, `GET /api/audit/events`, `GET /api/audit/verify` | | | ✓ | ✓ |
| reset_password | `POST /api/auth/users/{username}/password` | | | ✓ | |
| review_rows | `PUT /api/csv/uploads/{id}/rows/{n}/decision`, `PUT /api/csv/uploads/{id}/rows/{n}/cells/{column}` | | ✓ | ✓ | |
| submit_import | `POST /api/csv/uploads/{id}/submit` | ✓ | | ✓ | |
| approve_import | `POST /api/csv/uploads/{id}/approval` | | ✓ | ✓ | |
| run_import | `POST /api/csv/uploads/{id}/import` | ✓ | ✓ | ✓ | |

A role that isn't allowed gets **403**. Two kinds of request are outside this table:

- **Sign-in routes** (`/api/auth/login`, `/oidc`, `/logout`, `/me`) are open to anyone, so people can sign in. Any signed-in user can change their own password (`POST /api/auth/password`).
- **Requests with no session** get **401 "Sign in required"**. The shared API key was retired (#298): scripts and services sign in as a named account with the role they need, so their actions are role-checked and audited under that name. The one exception is local development and tests, by explicit opt-in (`API_ALLOW_ANONYMOUS=1` with `API_ENV=dev`): those requests use the default schemas, are not role-checked and audit as `anonymous`. The API refuses to start with the opt-in outside `dev`.

**Password reset (#117).** A tenant admin can reset the password of a member of their own tenant. The reset also unlocks the account, ends all of its sessions, and is written to the tenant's audit log. A user who also belongs to another tenant can't be reset this way (409), because the password is shared across tenants. For that case, or when no admin can sign in, an operator with database access runs `scripts/reset_password.py`. Anonymous local-dev requests can't reset passwords.

**Approval (M6, #110).** An uploader stages a file (`POST /api/csv/uploads`) and submits it. A reviewer reviews it, then approves or rejects. A rejection needs a reason, and the upload can be reviewed again and resubmitted. Approving needs every row that isn't excluded to pass validation. Once approved, rows can't be changed, and the import loads exactly what was approved.

**Self-approval (decision 5).** A signed-in member can't approve data they uploaded or submitted, whatever their role. A tenant with a single user can allow it: `accounts.set_self_approval`, or `scripts/create_tenant_admin.py --allow-self-approval` when creating the tenant. An anonymous local-dev request has no identity to compare, so the rule doesn't apply to it.
