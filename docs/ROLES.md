# Roles and permissions (BR-36, #94)

Every member of a tenant has one role (ADR-0003). This table is enforced by `PERMISSIONS` in `api/auth.py`. `tests/test_roles.py` fails if the two disagree, and it tries every role against every route.

| Action | Route | uploader | reviewer | tenant_admin | auditor |
|---|---|---|---|---|---|
| preview | `POST /api/csv/preview` | ✓ | | ✓ | |
| upload | `POST /api/csv/upload` | ✓ | | ✓ | |
| list_files | `GET /api/csv/files`, `GET /api/csv/uploads` | ✓ | ✓ | ✓ | ✓ |
| read_rows | `GET /api/csv/tables/{table}/rows`, `GET /api/csv/uploads/{id}/original`, `GET /api/csv/uploads/{id}/rows`, `GET /api/csv/uploads/{id}/rows/{n}/history` | ✓ | ✓ | ✓ | ✓ |
| list_te | `GET /api/te/tables` | ✓ | ✓ | ✓ | ✓ |
| delete_file | `DELETE /api/csv/files/{id}` | | | ✓ | |
| read_audit | `GET /api/audit/log`, `GET /api/audit/verify` | | | ✓ | ✓ |
| reset_password | `POST /api/auth/users/{username}/password` | | | ✓ | |
| review_rows | `PUT /api/csv/uploads/{id}/rows/{n}/decision`, `PUT /api/csv/uploads/{id}/rows/{n}/cells/{column}` | | ✓ | ✓ | |

A role that isn't allowed gets **403**. Two kinds of request are outside this table:

- **Sign-in routes** (`/api/auth/login`, `/oidc`, `/logout`, `/me`) are open to anyone, so people can sign in. Any signed-in user can change their own password (`POST /api/auth/password`).
- **Requests with no session** use the shared API key, or nothing in `dev`. They keep full access until the shared key is retired.

**Password reset (#117).** A tenant admin can reset the password of a member of their own tenant. The reset also unlocks the account, ends all of its sessions, and is written to the tenant's audit log. A user who also belongs to another tenant can't be reset this way (409), because the password is shared across tenants. For that case, or when no admin can sign in, an operator with database access runs `scripts/reset_password.py`. Requests with no session can't reset passwords.

Approving and editing data arrive with M4 and M6. The reviewer gets those permissions then.
