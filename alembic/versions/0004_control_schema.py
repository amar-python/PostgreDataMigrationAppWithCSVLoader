"""Control schema: tenants, users, memberships and sessions (M2a, #92, BR-36).

Shared by every tenant. Roles are the four from ADR-0003. Session tokens are
stored only as SHA-256 hashes, so a database read does not yield usable tokens.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from alembic import op

from api.config import settings

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.CONTROL_SCHEMA)


def upgrade() -> None:
    s = _schema()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
    op.execute(f"""
        CREATE TABLE {s}.tenants (
            id BIGSERIAL PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z][a-z0-9_]{{1,40}}$'),
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute(f"""
        CREATE TABLE {s}.users (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute(f"""
        CREATE TABLE {s}.memberships (
            user_id BIGINT NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
            tenant_id BIGINT NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('uploader', 'reviewer', 'tenant_admin', 'auditor')),
            PRIMARY KEY (user_id, tenant_id)
        )""")
    op.execute(f"""
        CREATE TABLE {s}.sessions (
            token_hash TEXT PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
            tenant_id BIGINT NOT NULL REFERENCES {s}.tenants(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ
        )""")


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {_schema()} CASCADE")
