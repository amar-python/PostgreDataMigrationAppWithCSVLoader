"""Lock accounts after repeated failed sign-ins (#102, BR-36).

Shared-only, like 0004: users live in the control schema, not in each tenant.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from alembic import context, op

from api.config import settings

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _skip() -> bool:
    return context.config.attributes.get("scope") == "tenant"


def _users() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.CONTROL_SCHEMA) + ".users"


def upgrade() -> None:
    if _skip():
        return
    op.execute(f"""ALTER TABLE {_users()}
        ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN first_failed_at TIMESTAMPTZ,
        ADD COLUMN locked_until TIMESTAMPTZ""")


def downgrade() -> None:
    if _skip():
        return
    op.execute(f"""ALTER TABLE {_users()}
        DROP COLUMN failed_logins, DROP COLUMN first_failed_at, DROP COLUMN locked_until""")
