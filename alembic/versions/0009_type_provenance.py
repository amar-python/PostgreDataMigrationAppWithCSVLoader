"""Record whether a dynamic table's column types were confirmed by a person (#195).

Decided 4 Nov: a dynamic-mode table is created from types a person confirmed,
and the registry says which. ``types_provenance`` is ``user_confirmed`` or
``inferred_unconfirmed``. T&E rows keep NULL: their columns are the fixed
schema's, so there are no inferred types to confirm.

Dynamic rows registered before this revision are marked ``inferred_unconfirmed``:
nothing recorded whether anyone confirmed their types, and the flag must not
claim a confirmation that can't be shown. Runs per tenant.

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
    op.execute(f"ALTER TABLE {s}.csv_files ADD COLUMN IF NOT EXISTS types_provenance TEXT "
               "CHECK (types_provenance IN ('inferred_unconfirmed', 'user_confirmed'))")
    # s is the dialect-quoted schema identifier from settings, never request input.
    op.execute(f"UPDATE {s}.csv_files SET types_provenance = 'inferred_unconfirmed' "  # nosec B608
               "WHERE mode = 'dynamic' AND types_provenance IS NULL")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_schema()}.csv_files DROP COLUMN IF EXISTS types_provenance")
