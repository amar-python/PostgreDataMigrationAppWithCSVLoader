"""Idle timeout and purge support for sign-in sessions (#296, BR-36).

Shared-only, like 0004: sessions live in the control schema, not in each tenant.

``last_seen_at`` is when the session was last used. It starts at now() for rows that already exist, so the upgrade
signs nobody out. The two indexes serve the purge, which looks for rows by ``expires_at`` and ``revoked_at``.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-23
"""

from alembic import context, op
from api.config import settings

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _skip() -> bool:
    return context.config.attributes.get("scope") == "tenant"


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.CONTROL_SCHEMA)


def upgrade() -> None:
    if _skip():
        return
    sessions = f"{_schema()}.sessions"
    op.execute(f"ALTER TABLE {sessions} ADD COLUMN last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute(f"CREATE INDEX sessions_expires_at_idx ON {sessions} (expires_at)")
    op.execute(f"CREATE INDEX sessions_revoked_at_idx ON {sessions} (revoked_at) WHERE revoked_at IS NOT NULL")


def downgrade() -> None:
    if _skip():
        return
    op.execute(f"DROP INDEX IF EXISTS {_schema()}.sessions_revoked_at_idx")
    op.execute(f"DROP INDEX IF EXISTS {_schema()}.sessions_expires_at_idx")
    op.execute(f"ALTER TABLE {_schema()}.sessions DROP COLUMN last_seen_at")
