"""Append-only, hash-chained audit_log (M3a, #107; BR-24, BR-35).

Decided 28 Oct: upgrade the existing per-tenant ``audit_log`` rather than add
an ``audit_events`` table.

- New columns: ``actor``, ``tenant_schema``, ``before_value``, ``after_value``,
  ``prev_hash``, ``row_hash``.
- A BEFORE INSERT trigger serialises writers with an advisory lock, gives the
  row its id under that lock (so id order is chain order), and sets
  ``prev_hash`` to the previous row's ``row_hash``.
- Triggers reject UPDATE, DELETE and TRUNCATE for every role, owner included.
  The owner can still disable a trigger; the hash chain is what exposes that,
  and M3d adds a runtime role that can't.
- Rows written before this revision are chained in id order during upgrade.

Runs per tenant, like 0003.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""

from alembic import op

from api.config import settings

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _schema() -> str:
    return op.get_bind().dialect.identifier_preparer.quote(settings.UPLOADS_SCHEMA)


def upgrade() -> None:
    s = _schema()
    t = f"{s}.audit_log"
    op.execute(f"""ALTER TABLE {t}
        ADD COLUMN actor TEXT,
        ADD COLUMN tenant_schema TEXT,
        ADD COLUMN before_value JSONB,
        ADD COLUMN after_value JSONB,
        ADD COLUMN prev_hash TEXT,
        ADD COLUMN row_hash TEXT""")
    # The hash covers every column except row_hash. Times are hashed in UTC so
    # the result doesn't depend on the session's TimeZone.
    op.execute(f"""
        CREATE FUNCTION {s}.audit_row_hash(prev TEXT, r {t}) RETURNS TEXT
        LANGUAGE sql IMMUTABLE AS $$
          SELECT encode(sha256(convert_to(coalesce(prev, '') || jsonb_build_object(
            'id', r.id, 'action', r.action, 'file_id', r.file_id, 'file_name', r.file_name,
            'table_name', r.table_name, 'mode', r.mode,
            'performed_at', to_char(r.performed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
            'actor', r.actor, 'tenant_schema', r.tenant_schema,
            'before_value', r.before_value, 'after_value', r.after_value)::text, 'UTF8')), 'hex')
        $$""")
    # Chain the rows that already exist, oldest first.
    op.execute(f"""DO $$
        DECLARE r RECORD; prev TEXT := NULL;
        BEGIN
          FOR r IN SELECT * FROM {t} ORDER BY id LOOP
            UPDATE {t} SET tenant_schema = TG_SCHEMA_PLACEHOLDER, prev_hash = prev
             WHERE id = r.id;
            SELECT {s}.audit_row_hash(prev, a) INTO prev FROM {t} a WHERE a.id = r.id;
            UPDATE {t} SET row_hash = prev WHERE id = r.id;
          END LOOP;
        END $$""".replace("TG_SCHEMA_PLACEHOLDER", f"'{settings.UPLOADS_SCHEMA}'"))
    op.execute(f"""
        CREATE FUNCTION {s}.audit_chain() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtext(TG_TABLE_SCHEMA || '.audit_log'));
          NEW.id := nextval(pg_get_serial_sequence(quote_ident(TG_TABLE_SCHEMA) || '.audit_log', 'id'));
          NEW.tenant_schema := TG_TABLE_SCHEMA;
          EXECUTE format('SELECT row_hash FROM %I.audit_log ORDER BY id DESC LIMIT 1', TG_TABLE_SCHEMA)
            INTO NEW.prev_hash;
          NEW.row_hash := {s}.audit_row_hash(NEW.prev_hash, NEW);
          RETURN NEW;
        END $$""")
    op.execute(f"""
        CREATE FUNCTION {s}.audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$""")
    # The trigger takes the id under its lock; the column default would take a second one.
    op.execute(f"ALTER TABLE {t} ALTER COLUMN id DROP DEFAULT")
    op.execute(f"CREATE TRIGGER audit_chain BEFORE INSERT ON {t} "
               f"FOR EACH ROW EXECUTE FUNCTION {s}.audit_chain()")
    op.execute(f"CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON {t} "
               f"FOR EACH ROW EXECUTE FUNCTION {s}.audit_reject_change()")
    op.execute(f"CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON {t} "
               f"FOR EACH STATEMENT EXECUTE FUNCTION {s}.audit_reject_change()")


def downgrade() -> None:
    s = _schema()
    t = f"{s}.audit_log"
    for trig in ("audit_no_truncate", "audit_no_change", "audit_chain"):
        op.execute(f"DROP TRIGGER IF EXISTS {trig} ON {t}")
    seq = f"pg_get_serial_sequence('{t}', 'id')"
    op.execute(f"ALTER TABLE {t} ALTER COLUMN id SET DEFAULT nextval({seq}::regclass)")
    op.execute(f"DROP FUNCTION IF EXISTS {s}.audit_reject_change()")
    op.execute(f"DROP FUNCTION IF EXISTS {s}.audit_chain()")
    op.execute(f"DROP FUNCTION IF EXISTS {s}.audit_row_hash(TEXT, {t})")
    op.execute(f"""ALTER TABLE {t}
        DROP COLUMN actor, DROP COLUMN tenant_schema, DROP COLUMN before_value,
        DROP COLUMN after_value, DROP COLUMN prev_hash, DROP COLUMN row_hash""")
