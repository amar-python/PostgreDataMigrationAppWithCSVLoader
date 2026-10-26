# Roles and permissions (BR-36, #94)

Every member of a tenant has one role (ADR-0003). This table is enforced by `PERMISSIONS` in `api/auth.py`. `tests/test_roles.py` fails if the two disagree, and it tries every role against every route.

| Action | Route | uploader | reviewer | tenant_admin | auditor |
|---|---|---|---|---|---|
| preview | `POST /api/csv/preview` | ✓ | | ✓ | |
| upload | `POST /api/csv/upload` | ✓ | | ✓ | |
| list_files | `GET /api/csv/files` | ✓ | ✓ | ✓ | ✓ |
| read_rows | `GET /api/csv/tables/{table}/rows` | ✓ | ✓ | ✓ | ✓ |
| list_te | `GET /api/te/tables` | ✓ | ✓ | ✓ | ✓ |
| delete_file | `DELETE /api/csv/files/{id}` | | | ✓ | |
| read_audit | `GET /api/audit/log` | | | ✓ | ✓ |

A role that isn't allowed gets **403**. Two kinds of request are outside this table:

- **Sign-in routes** (`/api/auth/*`) are open to anyone, so people can sign in.
- **Requests with no session** use the shared API key, or nothing in `dev`. They keep full access until the shared key is retired.

Approving and editing data arrive with M4 and M6. The reviewer gets those permissions then.
