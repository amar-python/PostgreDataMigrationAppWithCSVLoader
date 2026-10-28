"""Per-request tenant schema routing (M2b, #93, BR-36; decision 6: schema per tenant).

Each tenant's registry, audit log, uploaded tables and T&E tables live in
schema ``tenant_<slug>``. A request signed in to a tenant runs with that schema set
here; ``uploads_schema()`` and ``te_schema()`` read it. A request without a
session (API-key or dev) keeps the deployment's default schemas.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg2 import sql

from api.config import TE_TABLES, settings

_current: ContextVar[str | None] = ContextVar("tenant_schema", default=None)
_migrate_lock = threading.Lock()


def schema_for(slug: str) -> str:
    """Schema name for a tenant slug. The slug CHECK in control.tenants keeps it a safe identifier."""
    return f"tenant_{slug}"


def current_schema() -> str | None:
    return _current.get()


def uploads_schema() -> str:
    return _current.get() or settings.UPLOADS_SCHEMA


def te_schema() -> str:
    return _current.get() or settings.TE_SCHEMA


@contextmanager
def scoped(schema: str):
    token = _current.set(schema)
    try:
        yield
    finally:
        _current.reset(token)


def migrate_tenant(slug: str) -> None:
    """Create or upgrade one tenant's schema to the latest per-tenant migration.

    Swaps settings.UPLOADS_SCHEMA while Alembic runs, so it is serialised and
    must only be called from startup or a CLI, never inside a request.
    """
    from alembic import command
    from alembic.config import Config

    from api.db import alembic_ini_path

    with _migrate_lock:
        original = settings.UPLOADS_SCHEMA
        settings.UPLOADS_SCHEMA = schema_for(slug)
        try:
            cfg = Config(str(alembic_ini_path()))
            cfg.attributes["scope"] = "tenant"
            command.upgrade(cfg, "head")
        finally:
            settings.UPLOADS_SCHEMA = original
    from api.db import grant_runtime, owner_connect

    with owner_connect() as conn:
        with conn.cursor() as cur:
            provision_te_tables(cur, schema_for(slug), settings.TE_SCHEMA)
            conn.commit()
            grant_runtime(cur, schema_for(slug), create=True)


def provision_te_tables(cur, schema: str, template: str) -> int:
    """Give a tenant its own T&E tables, cloned from the deployment's T&E schema (#99).

    ``template`` is the schema build/deploy_all.sh created. Copies columns,
    defaults, checks, indexes and comments, then the foreign keys, the
    updated_at function and its triggers, re-pointed at ``schema``. Keys are
    UUIDs, so no sequence is shared between tenants. Idempotent: only missing
    tables are created. Returns how many were. The caller commits.
    """
    cur.execute("SET LOCAL search_path = pg_catalog")  # makes catalog DDL schema-qualified
    cur.execute("SELECT quote_ident(%s), quote_ident(%s)", (template, schema))
    qt, qs = cur.fetchone()
    cur.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind = 'r' AND c.relname = ANY(%s)", (template, TE_TABLES))
    if {r[0] for r in cur.fetchall()} != set(TE_TABLES):
        raise RuntimeError(f"T&E template schema {template!r} is missing or incomplete; "
                           "deploy it with build/deploy_all.sh first")
    cur.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = ANY(%s)", (schema, TE_TABLES))
    present = {r[0] for r in cur.fetchall()}
    missing = [t for t in TE_TABLES if t not in present]
    if not missing:
        return 0
    for table in missing:
        cur.execute(sql.SQL("CREATE TABLE {}.{} (LIKE {}.{} INCLUDING ALL)").format(
            sql.Identifier(schema), sql.Identifier(table), sql.Identifier(template), sql.Identifier(table)))

    def defs(query: str) -> list[tuple]:
        cur.execute(query, (template, missing))
        return cur.fetchall()

    for table, name, ddl in defs(
            "SELECT r.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace "
            "WHERE n.nspname = %s AND c.contype = 'f' AND r.relname = ANY(%s) ORDER BY c.conname"):
        cur.execute(sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} ").format(
            sql.Identifier(schema), sql.Identifier(table), sql.Identifier(name))
            + sql.SQL(ddl.replace(f"REFERENCES {qt}.", f"REFERENCES {qs}.")))
    cur.execute("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = %s AND p.proname = 'set_updated_at'", (template,))
    for (ddl,) in cur.fetchall():
        cur.execute(sql.SQL(ddl.replace(f"FUNCTION {qt}.", f"FUNCTION {qs}.", 1)))
    for (ddl,) in defs(
            "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class r ON r.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = r.relnamespace "
            "WHERE n.nspname = %s AND NOT t.tgisinternal AND r.relname = ANY(%s)"):
        cur.execute(sql.SQL(ddl.replace(f" ON {qt}.", f" ON {qs}.").replace(f"FUNCTION {qt}.", f"FUNCTION {qs}.")))
    cur.execute("RESET search_path")
    return len(missing)
