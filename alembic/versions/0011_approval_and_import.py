"""Approval and staged import (M6, #110; BR-32, BR-33, BR-34; ADR-0002; decisions 4 and 5).

Workflow state is derived from insert-only event tables, because ``uploads`` can't be updated:

- ``uploads.status`` gains ``staged``: stored for review, nothing imported yet. ``uploads.types_provenance``
  keeps whether the uploader confirmed the column types (#195), for the import to record in the registry.
- ``submissions``: someone submitted the upload for approval (actor, note, time).
- ``approvals``: one approve or reject decision per submission, with the approver, a reason
  (required to reject), and ``decisions_upto`` / ``edits_upto``: the newest row decision and
  cell edit at that moment. An import applies exactly those, so what was approved is what
  gets imported.
- ``imports``: one row per successful import, written in the import's own transaction, so
  it exists only if the data does. UNIQUE (upload_id) and UNIQUE (approval_id): an upload is
  imported once. Counts reconcile: rows_in = rows_excluded + rows_duplicate + rows_imported.
  rows_edited counts imported-or-skipped rows that had edits; it isn't part of that sum.

All three are insert-only, with the same guard as 0006..0009.

Control schema (runs once, not per tenant): ``tenants.allow_self_approval``. Off by default, so
the person who uploaded data can't approve it (decision 5); a tenant with one user turns it on.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from alembic import context, op
from sqlalchemy import text

from api.config import settings

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_TABLES = ("submissions", "approvals", "imports")
_STATUSES = "'staged', 'imported', 'partly_imported', 'failed', 'duplicate', 'rejected'"
_OLD_STATUSES = "'imported', 'partly_imported', 'failed', 'duplicate', 'rejected'"


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def _tenants() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.CONTROL_SCHEMA) + ".tenants"


def _tenant_run() -> bool:
    return context.config.attributes.get("scope") == "tenant"


def upgrade() -> None:
    s = _schema()
    if not _tenant_run():
        op.execute(f"ALTER TABLE {_tenants()} ADD COLUMN allow_self_approval BOOLEAN NOT NULL DEFAULT false")
    op.execute(f"ALTER TABLE {s}.uploads DROP CONSTRAINT uploads_status_check")
    op.execute(f"ALTER TABLE {s}.uploads ADD CONSTRAINT uploads_status_check CHECK (status IN ({_STATUSES}))")
    op.execute(f"ALTER TABLE {s}.uploads ADD COLUMN types_provenance TEXT "
               "CHECK (types_provenance IN ('inferred_unconfirmed', 'user_confirmed'))")
    op.execute(f"""CREATE TABLE {s}.submissions (
        id BIGSERIAL PRIMARY KEY,
        upload_id BIGINT NOT NULL REFERENCES {s}.uploads (id),
        submitter TEXT,
        note TEXT,
        submitted_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute(f"""CREATE TABLE {s}.approvals (
        id BIGSERIAL PRIMARY KEY,
        submission_id BIGINT NOT NULL UNIQUE REFERENCES {s}.submissions (id),
        upload_id BIGINT NOT NULL REFERENCES {s}.uploads (id),
        decision TEXT NOT NULL CHECK (decision IN ('approve', 'reject')),
        reason TEXT CHECK (decision = 'approve' OR btrim(reason) <> ''),
        approver TEXT,
        decisions_upto BIGINT NOT NULL,
        edits_upto BIGINT NOT NULL,
        decided_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute(f"""CREATE TABLE {s}.imports (
        id BIGSERIAL PRIMARY KEY,
        upload_id BIGINT NOT NULL UNIQUE REFERENCES {s}.uploads (id),
        approval_id BIGINT NOT NULL UNIQUE REFERENCES {s}.approvals (id),
        idempotency_key TEXT NOT NULL,
        rows_in INTEGER NOT NULL,
        rows_excluded INTEGER NOT NULL,
        rows_edited INTEGER NOT NULL,
        rows_duplicate INTEGER NOT NULL,
        rows_imported INTEGER NOT NULL,
        csv_file_id BIGINT NOT NULL,
        table_name TEXT NOT NULL,
        importer TEXT,
        imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT imports_reconcile CHECK (rows_in = rows_excluded + rows_duplicate + rows_imported))""")
    for t in ("submissions", "approvals"):
        op.execute(f"CREATE INDEX {t}_by_upload ON {s}.{t} (upload_id, id)")
    for t in _TABLES:
        op.execute(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {s}.{t} "
                   f"FOR EACH ROW EXECUTE FUNCTION {s}.audit_reject_change()")
        op.execute(f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {s}.{t} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {s}.audit_reject_change()")


def downgrade() -> None:
    s = _schema()
    # Staged uploads have no home in the old status list, and uploads can't be edited. Refuse
    # rather than rewrite an insert-only table; nothing has been dropped yet.
    staged = op.get_bind().execute(text(f"SELECT count(*) FROM {s}.uploads WHERE status = 'staged'")).scalar()  # nosec B608
    if staged:
        raise RuntimeError(f"Cannot downgrade {settings.UPLOADS_SCHEMA}: {staged} upload(s) are staged. "
                           "Import them or leave the schema at 0011.")
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {s}.{t}")
    op.execute(f"ALTER TABLE {s}.uploads DROP COLUMN types_provenance")
    op.execute(f"ALTER TABLE {s}.uploads DROP CONSTRAINT uploads_status_check")
    op.execute(f"ALTER TABLE {s}.uploads ADD CONSTRAINT uploads_status_check CHECK (status IN ({_OLD_STATUSES}))")
    if not _tenant_run():
        op.execute(f"ALTER TABLE {_tenants()} DROP COLUMN allow_self_approval")
