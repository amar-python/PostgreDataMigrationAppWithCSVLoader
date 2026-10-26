"""Baseline: csv_files registry and audit_log, as created by the fallback bootstrap.

Uses IF NOT EXISTS so databases already created by api/db.py's fallback
bootstrap adopt this revision without changes.

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from alembic import op

from api.config import settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {s}.csv_files (
            id BIGSERIAL PRIMARY KEY,
            file_name TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            table_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            column_names TEXT[] NOT NULL DEFAULT '{{}}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {s}.audit_log (
            id BIGSERIAL PRIMARY KEY,
            action TEXT NOT NULL,
            file_id BIGINT,
            file_name TEXT,
            table_name TEXT,
            mode TEXT,
            performed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    s = _schema()
    op.execute(f"DROP TABLE IF EXISTS {s}.audit_log")
    op.execute(f"DROP TABLE IF EXISTS {s}.csv_files")
