"""Program consistency for the T&E tables (#177), applied to existing tenants (#184).

Ports phase 4B of build/te_core_schema.sql, which does the same for a template
schema. A tenant's tables are cloned from the template, so a tenant created before
#177 kept the old shape for good; this brings it across:

- ``program_id`` on test_cases, test_events, vcrm_entries and test_results, backfilled
  from the parent row each already depends on (``updated_at`` triggers paused, so the
  backfill does not look like an edit), then NOT NULL;
- every cross-table foreign key becomes composite ``(<id>, program_id)``, backed by
  UNIQUE (<id>, program_id), so PostgreSQL rejects a row that joins two programs;
- ``te_fill_program_id`` and its BEFORE INSERT triggers fill ``program_id`` from the
  parent when a load omits it.

Idempotent: a tenant cloned after #177 already has all of it, and re-running changes
nothing. The whole upgrade is one transaction. If cross-program rows already exist it
ABORTS, leaving the tenant exactly as it was, and lists them so they can be triaged.

The names below must match phase 4B; tests/system/test_tenant_te_migrations.py compares a
migrated tenant with the template and fails if they drift.

Revision ID: te0002
Revises: te0001
Create Date: 2026-11-09
"""

from alembic import op
from psycopg2 import sql

revision = "te0002"
down_revision = "te0001"
branch_labels = None
depends_on = None

# Body copied byte for byte from phase 4B: pg_get_functiondef must match the template's.
_FILL_FUNCTION_BODY = """$$
-- args: parent table, parent key column, this row's FK column. The parent lives
-- in the row's own schema (TG_TABLE_SCHEMA), never a name baked in at deploy
-- time: api/tenancy.py clones these triggers into per-tenant schemas.
DECLARE
   v_prog UUID;
BEGIN
   IF NEW.program_id IS NULL THEN
      EXECUTE format('SELECT program_id FROM %I.%I WHERE %I = $1',
                     TG_TABLE_SCHEMA, TG_ARGV[0], TG_ARGV[1])
         INTO v_prog USING (to_jsonb(NEW) ->> TG_ARGV[2])::UUID;
      IF v_prog IS NULL THEN
         RAISE EXCEPTION '%.% % not found', TG_ARGV[0], TG_ARGV[1], to_jsonb(NEW) ->> TG_ARGV[2]
            USING ERRCODE = 'foreign_key_violation';
      END IF;
      NEW.program_id := v_prog;
   END IF;
   RETURN NEW;
END;
$$"""

_PROGRAM_TABLES = ("test_cases", "test_events", "vcrm_entries", "test_results")

# (table, constraint, definition) — UNIQUE targets first, then the composite FKs that need them.
_UNIQUES = (
    ("test_phases", "uq_phases_id_program", "UNIQUE (phase_id, program_id)"),
    ("requirements", "uq_requirements_id_program", "UNIQUE (req_id, program_id)"),
    ("test_cases", "uq_testcases_id_program", "UNIQUE (tc_id, program_id)"),
    ("test_events", "uq_events_id_program", "UNIQUE (event_id, program_id)"),
    ("test_results", "uq_results_id_program", "UNIQUE (result_id, program_id)"),
)
# (table, constraint, columns, parent, ON DELETE clause)
_COMPOSITE_FKS = (
    ("test_cases", "fk_testcases_phase_program", "phase_id", "test_phases", " ON DELETE CASCADE"),
    ("test_events", "fk_events_phase_program", "phase_id", "test_phases", " ON DELETE CASCADE"),
    ("vcrm_entries", "fk_vcrm_req_program", "req_id", "requirements", " ON DELETE CASCADE"),
    ("vcrm_entries", "fk_vcrm_tc_program", "tc_id", "test_cases", " ON DELETE CASCADE"),
    ("test_results", "fk_results_event_program", "event_id", "test_events", " ON DELETE CASCADE"),
    ("test_results", "fk_results_tc_program", "tc_id", "test_cases", ""),
    # result_id is nullable; MATCH SIMPLE skips the check when it is NULL
    ("defect_reports", "fk_defects_result_program", "result_id", "test_results", ""),
)
# (table, parent, parent key, this row's FK column) for the fill triggers
_FILL_TRIGGERS = (
    ("test_cases", "test_phases", "phase_id", "phase_id"),
    ("test_events", "test_phases", "phase_id", "phase_id"),
    ("vcrm_entries", "requirements", "req_id", "req_id"),
    ("test_results", "test_events", "event_id", "event_id"),
)
# The single-column FKs the composites replace, and what they were before (for downgrade).
_SINGLE_FKS = (
    ("test_cases", "phase_id", "test_phases", " ON DELETE CASCADE"),
    ("test_events", "phase_id", "test_phases", " ON DELETE CASCADE"),
    ("vcrm_entries", "req_id", "requirements", " ON DELETE CASCADE"),
    ("vcrm_entries", "tc_id", "test_cases", " ON DELETE CASCADE"),
    ("test_results", "event_id", "test_events", " ON DELETE CASCADE"),
    ("test_results", "tc_id", "test_cases", ""),
    ("defect_reports", "result_id", "test_results", ""),
)


def _schema() -> str:
    return op.get_context().opts["version_table_schema"]


def _cursor():
    return op.get_bind().connection.cursor()


def _tbl(schema: str, table: str) -> sql.Composable:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def _has_constraint(cur, schema: str, table: str, name: str) -> bool:
    cur.execute(sql.SQL("SELECT 1 FROM pg_constraint WHERE conrelid = {}::regclass AND conname = %s").format(
        sql.Literal(f'"{schema}"."{table}"')), (name,))
    return cur.fetchone() is not None


def _add_constraint(cur, schema: str, table: str, name: str, definition: sql.Composable | str) -> None:
    if _has_constraint(cur, schema, table, name):
        return
    if isinstance(definition, str) and definition.startswith("UNIQUE"):
        # A tenant cloned after #177 but before provisioning kept the template's names has this
        # constraint under a default name. Adopt it; a second copy would be a redundant index.
        cur.execute("SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'u' "
                    "AND pg_get_constraintdef(oid) = %s", (f'"{schema}"."{table}"', definition))
        row = cur.fetchone()
        if row:
            cur.execute(sql.SQL("ALTER TABLE {} RENAME CONSTRAINT {} TO {}").format(
                _tbl(schema, table), sql.Identifier(row[0]), sql.Identifier(name)))
            return
    cur.execute(sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} {}").format(
        _tbl(schema, table), sql.Identifier(name),
        definition if isinstance(definition, sql.Composable) else sql.SQL(definition)))


def _drop_constraint(cur, schema: str, table: str, name: str, if_exists: bool = False) -> None:
    cur.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}{}").format(
        _tbl(schema, table), sql.SQL("IF EXISTS " if if_exists else ""), sql.Identifier(name)))


def _toggle_updated_at(cur, schema: str, tables: tuple[str, ...], action: str) -> None:
    for table in tables:
        cur.execute(sql.SQL("SELECT 1 FROM pg_trigger WHERE tgrelid = {}::regclass AND tgname = 'trg_updated_at'")
                    .format(sql.Literal(f'"{schema}"."{table}"')))
        if cur.fetchone():
            statement = sql.SQL("ALTER TABLE {} {} TRIGGER trg_updated_at")
            cur.execute(statement.format(_tbl(schema, table), sql.SQL(action)))


def upgrade() -> None:
    schema, cur = _schema(), _cursor()
    t = {name: _tbl(schema, name) for name in
         ("test_phases", "requirements", "test_cases", "vcrm_entries", "test_events", "test_results",
          "defect_reports")}

    cur.execute(sql.SQL("CREATE OR REPLACE FUNCTION {}.te_fill_program_id() RETURNS TRIGGER LANGUAGE plpgsql AS ")
                .format(sql.Identifier(schema)) + sql.SQL(_FILL_FUNCTION_BODY))

    # 1. program_id columns, nullable until backfilled
    for table in _PROGRAM_TABLES:
        cur.execute(sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS program_id UUID").format(t[table]))

    # 2. backfill from the parent each row already depends on
    _toggle_updated_at(cur, schema, ("test_cases", "test_events"), "DISABLE")
    for child, parent, key in (("test_cases", "test_phases", "phase_id"),
                               ("test_events", "test_phases", "phase_id"),
                               ("vcrm_entries", "requirements", "req_id"),
                               ("test_results", "test_events", "event_id")):
        cur.execute(sql.SQL("UPDATE {c} c SET program_id = p.program_id FROM {p} p "
                            "WHERE c.{k} = p.{k} AND c.program_id IS NULL").format(
                                c=t[child], p=t[parent], k=sql.Identifier(key)))
    _toggle_updated_at(cur, schema, ("test_cases", "test_events"), "ENABLE")

    # 3. refuse to constrain data that already violates BR-07, and say which rows to triage
    cur.execute(sql.SQL("""
        SELECT string_agg(msg, E'\\n') FROM (
           SELECT 'vcrm_entries ' || v.vcrm_id || ': requirement in program ' || v.program_id
                  || ', test case in program ' || c.program_id AS msg
           FROM {vc} v JOIN {tc} c ON c.tc_id = v.tc_id WHERE c.program_id <> v.program_id
           UNION ALL
           SELECT 'test_results ' || x.result_id || ': event in program ' || x.program_id
                  || ', test case in program ' || c.program_id
           FROM {rs} x JOIN {tc} c ON c.tc_id = x.tc_id WHERE c.program_id <> x.program_id
           UNION ALL
           SELECT 'defect_reports ' || d.defect_id || ': defect in program ' || d.program_id
                  || ', result in program ' || x.program_id
           FROM {df} d JOIN {rs} x ON x.result_id = d.result_id WHERE x.program_id <> d.program_id
           LIMIT 50
        ) m""").format(vc=t["vcrm_entries"], tc=t["test_cases"], rs=t["test_results"], df=t["defect_reports"]))
    (bad,) = cur.fetchone()
    if bad:
        raise RuntimeError(f"Tenant schema {schema!r}: cross-program references found (BR-07). "
                           f"Nothing was changed. Fix or remove these rows, then re-run:\n{bad}")

    # 4. NOT NULL, composite-key targets, composite FKs
    for table in _PROGRAM_TABLES:
        cur.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN program_id SET NOT NULL").format(t[table]))

    # drop the single-column FKs the composites replace, whatever they are called
    for table, column, _parent, _action in _SINGLE_FKS:
        cur.execute(
            "SELECT c.conname FROM pg_constraint c JOIN pg_attribute a "
            "ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
            "WHERE c.contype = 'f' AND cardinality(c.conkey) = 1 AND c.conrelid = %s::regclass "
            "AND a.attname = %s", (f'"{schema}"."{table}"', column))
        for (conname,) in cur.fetchall():
            _drop_constraint(cur, schema, table, conname)

    for table, name, definition in _UNIQUES:
        _add_constraint(cur, schema, table, name, definition)
    for table, name, column, parent, on_delete in _COMPOSITE_FKS:
        _add_constraint(cur, schema, table, name, sql.SQL(
            "FOREIGN KEY ({col}, program_id) REFERENCES {parent}({col}, program_id){action}").format(
                col=sql.Identifier(column), parent=_tbl(schema, parent), action=sql.SQL(on_delete)))

    # 5. fill program_id from the parent on INSERT when the caller omitted it
    for table, parent, key, fk in _FILL_TRIGGERS:
        cur.execute(sql.SQL("DROP TRIGGER IF EXISTS trg_fill_program_id ON {}").format(t[table]))
        cur.execute(sql.SQL("CREATE TRIGGER trg_fill_program_id BEFORE INSERT ON {} FOR EACH ROW "
                            "EXECUTE FUNCTION {}.te_fill_program_id({}, {}, {})").format(
                                t[table], sql.Identifier(schema), sql.Literal(parent), sql.Literal(key),
                                sql.Literal(fk)))


def downgrade() -> None:
    """Back to the shape before #177. Used by tests, and to roll back a bad release."""
    schema, cur = _schema(), _cursor()
    for table, *_ in _FILL_TRIGGERS:
        cur.execute(sql.SQL("DROP TRIGGER IF EXISTS trg_fill_program_id ON {}").format(_tbl(schema, table)))
    for table, name, *_ in _COMPOSITE_FKS:
        _drop_constraint(cur, schema, table, name, if_exists=True)
    for table, column, parent, on_delete in _SINGLE_FKS:
        cur.execute(sql.SQL("ALTER TABLE {} ADD FOREIGN KEY ({}) REFERENCES {}({}){}").format(
            _tbl(schema, table), sql.Identifier(column), _tbl(schema, parent), sql.Identifier(column),
            sql.SQL(on_delete)))
    for table, name, _definition in _UNIQUES:
        _drop_constraint(cur, schema, table, name, if_exists=True)
    for table in _PROGRAM_TABLES:
        cur.execute(sql.SQL("ALTER TABLE {} DROP COLUMN IF EXISTS program_id").format(_tbl(schema, table)))
    cur.execute(sql.SQL("DROP FUNCTION IF EXISTS {}.te_fill_program_id()").format(sql.Identifier(schema)))
