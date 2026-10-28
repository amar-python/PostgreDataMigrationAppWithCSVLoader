"""Keep every upload's original file and parsed rows, insert-only (M3b, #107; BR-23, BR-24).

- ``uploads``: one row per upload attempt. Who uploaded it, when, the file's
  SHA-256 and size, the mode, the outcome (imported, partly_imported, failed,
  duplicate or rejected), the row counts, and the registry row it produced.
- ``upload_blobs``: the file's bytes exactly as received.
- ``source_rows``: the parsed rows as text; row 0 is the header.

All three reject UPDATE, DELETE and TRUNCATE, like audit_log (0006). Deleting
or overwriting a migrated file removes its table and registry row, never its
original. ``csv_file_id`` is a plain value, not a foreign key, for that reason.

Runs per tenant, like 0003.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""

from alembic import op

from api.config import settings

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABLES = ("uploads", "upload_blobs", "source_rows")


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    op.execute(f"""CREATE TABLE {s}.uploads (
        id BIGSERIAL PRIMARY KEY,
        file_name TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL,
        uploader TEXT,
        mode TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN
            ('imported', 'partly_imported', 'failed', 'duplicate', 'rejected')),
        total_rows INTEGER,
        imported_rows INTEGER,
        failed_rows INTEGER,
        csv_file_id BIGINT,
        uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute(f"CREATE INDEX uploads_csv_file_id ON {s}.uploads (csv_file_id)")
    op.execute(f"""CREATE TABLE {s}.upload_blobs (
        upload_id BIGINT PRIMARY KEY REFERENCES {s}.uploads (id),
        content BYTEA NOT NULL)""")
    op.execute(f"""CREATE TABLE {s}.source_rows (
        upload_id BIGINT NOT NULL REFERENCES {s}.uploads (id),
        row_number INTEGER NOT NULL,
        cells TEXT[] NOT NULL,
        PRIMARY KEY (upload_id, row_number))""")
    # One guard function for every insert-only table, naming the table it stopped.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {s}.audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$""")
    for t in _TABLES:
        op.execute(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {s}.{t} "
                   f"FOR EACH ROW EXECUTE FUNCTION {s}.audit_reject_change()")
        op.execute(f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {s}.{t} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {s}.audit_reject_change()")


def downgrade() -> None:
    s = _schema()
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {s}.{t}")
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {s}.audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$""")
