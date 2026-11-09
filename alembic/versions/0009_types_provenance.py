"""Record whether a dynamic table's column types were confirmed by a person (#195).

Dynamic mode infers column types from the data. Until now nothing recorded
whether anyone checked them, so a mis-typed `clearance` or date column looked the
same as a reviewed one. Each registry row now carries a provenance value:

    user_confirmed        the uploader confirmed or changed the types
    inferred_unconfirmed  the types were inferred and nobody confirmed them

Tables registered before this revision are backfilled `inferred_unconfirmed`:
there is no record that anyone confirmed them, and NULL would hide that. T&E-mode
rows keep NULL; their types come from the T&E schema, not from inference.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09
"""

from alembic import op

from api.config import settings

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    op.execute(
        f"ALTER TABLE {s}.csv_files ADD COLUMN IF NOT EXISTS types_provenance TEXT "
        "CHECK (types_provenance IN ('user_confirmed', 'inferred_unconfirmed'))"
    )
    # s is the dialect-quoted schema name; everything else is a constant.
    op.execute(
        f"UPDATE {s}.csv_files SET types_provenance = 'inferred_unconfirmed' "  # nosec B608
        "WHERE mode = 'dynamic' AND types_provenance IS NULL"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_schema()}.csv_files DROP COLUMN IF EXISTS types_provenance")
