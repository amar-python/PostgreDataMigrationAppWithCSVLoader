"""Persist each import's row counts on its registry row (BR-34, part).

Until now only the inserted count (row_count) was stored; total, duplicate
and failed counts were returned to the caller and then lost. Rows registered
before this revision keep NULL in the new columns: their counts were never
recorded, and NULL says so rather than inventing a zero.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from alembic import op

from api.config import settings

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_COLUMNS = ("total_rows", "duplicate_rows_skipped", "failed_rows")


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    for c in _COLUMNS:
        op.execute(f"ALTER TABLE {s}.csv_files ADD COLUMN IF NOT EXISTS {c} INTEGER")


def downgrade() -> None:
    s = _schema()
    for c in _COLUMNS:
        op.execute(f"ALTER TABLE {s}.csv_files DROP COLUMN IF EXISTS {c}")
