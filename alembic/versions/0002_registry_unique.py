"""Registry uniqueness: one row per file hash and per file name (#81).

dynamic_loader.py relies on these constraints to settle concurrent identical
uploads, but they were never created. If a database already holds duplicates
(possible because of that race), the upgrade stops and lists them instead of
deleting anything.

Note: UNIQUE (file_name) matches today's behaviour (a repeated filename is
refused or replaced). ART decision 2 (versioned datasets) revisits it in M5.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from alembic import op
from sqlalchemy import text

from api.config import settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    bind = op.get_bind()
    for column in ("file_hash", "file_name"):
        dupes = bind.execute(
            # column comes from the fixed tuple above; s is quoted by the dialect.
            text(f"SELECT {column}, count(*) FROM {s}.csv_files GROUP BY {column} HAVING count(*) > 1")  # nosec B608
        ).fetchall()
        if dupes:
            listed = ", ".join(f"{value!r} x{count}" for value, count in dupes[:10])
            raise RuntimeError(
                f"Cannot add UNIQUE ({column}) to {settings.UPLOADS_SCHEMA}.csv_files: "
                f"{len(dupes)} duplicated value(s): {listed}. Remove the duplicate registry "
                f"rows (keep the one whose table_name still exists), then restart the API."
            )
    op.execute(f"ALTER TABLE {s}.csv_files ADD CONSTRAINT csv_files_file_hash_key UNIQUE (file_hash)")
    op.execute(f"ALTER TABLE {s}.csv_files ADD CONSTRAINT csv_files_file_name_key UNIQUE (file_name)")


def downgrade() -> None:
    s = _schema()
    op.execute(f"ALTER TABLE {s}.csv_files DROP CONSTRAINT IF EXISTS csv_files_file_name_key")
    op.execute(f"ALTER TABLE {s}.csv_files DROP CONSTRAINT IF EXISTS csv_files_file_hash_key")
