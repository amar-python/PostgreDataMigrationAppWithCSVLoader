"""Versioned datasets and cross-upload duplicate flags (M5, #109; BR-28..31; decision 2, decision 3).

A repeated filename no longer replaces the earlier upload: it becomes the next
version of that dataset, stored in its own table ``csv_<slug>_v<n>``.

- ``csv_files.dataset`` and ``csv_files.version``: the filename's slug and the
  version number within it. UNIQUE (dataset, version). Existing dynamic rows are
  backfilled, oldest first, so each keeps its table and becomes v1, v2, ... of
  its slug. T&E rows (mode 'te') stay NULL: they aren't versioned.
- UNIQUE (file_name) is dropped for dynamic uploads. T&E loads still replace an
  earlier load of the same file and still rely on the database to settle a race,
  so a partial unique index keeps one row per file name for every other mode.
  UNIQUE (file_hash) stays: exact-file dedup is per registry, one registry per tenant.
- ``row_flags``: rows whose exact content already exists in an earlier version of
  the dataset. Insert-only, like the other review tables (0006..0008). The user
  decides per row through the existing include/exclude decision.

The slug expression here and ``dataset_slug`` in api/services/dynamic_loader.py
must agree.

Runs per tenant, like 0003. (Numbered 0010 after main took 0009 for #195.)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

from alembic import op
from sqlalchemy import text

from api.config import settings

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_SLUG = ("COALESCE(NULLIF(trim(both '_' from left(trim(both '_' from regexp_replace("
         "lower(regexp_replace(file_name, '\\.csv$', '', 'i')), '[^a-z0-9]+', '_', 'g')), 40)), ''), 'dataset')")


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    op.execute(f"ALTER TABLE {s}.csv_files ADD COLUMN dataset TEXT, ADD COLUMN version INTEGER")
    # s is quoted by the dialect and _SLUG is a constant above; no user input reaches this.
    op.execute(f"""UPDATE {s}.csv_files f SET dataset = n.dataset, version = n.version
        FROM (SELECT id, {_SLUG} AS dataset,
                     row_number() OVER (PARTITION BY {_SLUG} ORDER BY id) AS version
              FROM {s}.csv_files WHERE mode = 'dynamic') n
        WHERE f.id = n.id""")  # nosec B608
    op.execute(f"ALTER TABLE {s}.csv_files ADD CONSTRAINT csv_files_dataset_version_key UNIQUE (dataset, version)")
    op.execute(f"ALTER TABLE {s}.csv_files DROP CONSTRAINT csv_files_file_name_key")
    op.execute(f"CREATE UNIQUE INDEX csv_files_non_dynamic_file_name ON {s}.csv_files (file_name) "
               "WHERE mode <> 'dynamic'")
    op.execute(f"""CREATE TABLE {s}.row_flags (
        upload_id BIGINT NOT NULL REFERENCES {s}.uploads (id),
        row_number INTEGER NOT NULL CHECK (row_number > 0),
        kind TEXT NOT NULL CHECK (kind IN ('duplicate_of_earlier_version')),
        matched_file_id BIGINT NOT NULL,
        matched_file_name TEXT NOT NULL,
        matched_version INTEGER NOT NULL,
        PRIMARY KEY (upload_id, row_number, kind))""")
    op.execute(f"CREATE TRIGGER row_flags_no_change BEFORE UPDATE OR DELETE ON {s}.row_flags "
               f"FOR EACH ROW EXECUTE FUNCTION {s}.audit_reject_change()")
    op.execute(f"CREATE TRIGGER row_flags_no_truncate BEFORE TRUNCATE ON {s}.row_flags "
               f"FOR EACH STATEMENT EXECUTE FUNCTION {s}.audit_reject_change()")


def downgrade() -> None:
    s = _schema()
    dupes = op.get_bind().execute(text(
        f"SELECT file_name, count(*) FROM {s}.csv_files GROUP BY file_name HAVING count(*) > 1"  # nosec B608
    )).fetchall()
    if dupes:
        listed = ", ".join(f"{name!r} x{count}" for name, count in dupes[:10])
        raise RuntimeError(
            f"Cannot restore UNIQUE (file_name) on {settings.UPLOADS_SCHEMA}.csv_files: versioned datasets "
            f"share a file name ({listed}). Delete the older versions first, then downgrade.")
    op.execute(f"DROP TABLE IF EXISTS {s}.row_flags")
    op.execute(f"DROP INDEX IF EXISTS {s}.csv_files_non_dynamic_file_name")
    op.execute(f"ALTER TABLE {s}.csv_files ADD CONSTRAINT csv_files_file_name_key UNIQUE (file_name)")
    op.execute(f"ALTER TABLE {s}.csv_files DROP CONSTRAINT csv_files_dataset_version_key")
    op.execute(f"ALTER TABLE {s}.csv_files DROP COLUMN dataset, DROP COLUMN version")
