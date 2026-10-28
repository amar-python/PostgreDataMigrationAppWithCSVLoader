"""Review of stored uploads: row decisions and versioned cell edits (M4a, #108; BR-25, BR-26, BR-27).

Decided 28 Oct: review is recorded now and applied by M6's staged import; the
imported table doesn't change. A reason is required.

- ``uploads`` gains ``columns`` and ``column_types``: the sanitised names and
  types the upload used, so every stored row can be validated.
- ``row_decisions``: include or exclude a row, with actor, reason and time.
- ``cell_edits``: one row per edit, with old and new value, actor, reason and
  time. The original stays in ``source_rows``.

Both new tables are insert-only (the latest entry wins; earlier ones are the
history), with the same guard as 0006 and 0007. Runs per tenant.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28
"""

from alembic import op

from api.config import settings

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TABLES = ("row_decisions", "cell_edits")


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    op.execute(f"ALTER TABLE {s}.uploads ADD COLUMN columns TEXT[], ADD COLUMN column_types TEXT[]")
    op.execute(f"""CREATE TABLE {s}.row_decisions (
        id BIGSERIAL PRIMARY KEY,
        upload_id BIGINT NOT NULL REFERENCES {s}.uploads (id),
        row_number INTEGER NOT NULL CHECK (row_number > 0),
        decision TEXT NOT NULL CHECK (decision IN ('include', 'exclude')),
        reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
        actor TEXT,
        decided_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute(f"""CREATE TABLE {s}.cell_edits (
        id BIGSERIAL PRIMARY KEY,
        upload_id BIGINT NOT NULL REFERENCES {s}.uploads (id),
        row_number INTEGER NOT NULL CHECK (row_number > 0),
        column_index INTEGER NOT NULL CHECK (column_index >= 0),
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (btrim(reason) <> ''),
        actor TEXT,
        edited_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    for t in _TABLES:
        op.execute(f"CREATE INDEX {t}_by_row ON {s}.{t} (upload_id, row_number, id)")
        op.execute(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {s}.{t} "
                   f"FOR EACH ROW EXECUTE FUNCTION {s}.audit_reject_change()")
        op.execute(f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {s}.{t} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {s}.audit_reject_change()")


def downgrade() -> None:
    s = _schema()
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {s}.{t}")
    op.execute(f"ALTER TABLE {s}.uploads DROP COLUMN columns, DROP COLUMN column_types")
