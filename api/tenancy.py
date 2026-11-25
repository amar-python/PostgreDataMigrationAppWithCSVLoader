"""Per-request tenant schema routing (M2b, #93, BR-36; decision 6: schema per tenant).

Each tenant's registry, audit log, uploaded tables and T&E tables live in
schema ``tenant_<slug>``. A request signed in to a tenant runs with that schema set
here; ``uploads_schema()`` and ``te_schema()`` read it. A request without a
session (API-key or dev) keeps the deployment's default schemas.

Each tenant also has its own NOLOGIN database role (#297, OIT-012; DECISIONS/2026-11-24-per-tenant-db-roles.md)
with rights only on its own schema. ``tenant()`` sets that role alongside the schema, and every connection a
request borrows runs ``SET ROLE`` to it (``api.db.Conn``), so a query that reaches another tenant's schema
fails at the database instead of returning its rows.
"""

from __future__ import annotations

import hashlib
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from psycopg2 import sql
from psycopg2.errors import InsufficientPrivilege

from api.config import TE_TABLES, settings

_current: ContextVar[str | None] = ContextVar("tenant_schema", default=None)
_role: ContextVar[str | None] = ContextVar("tenant_role", default=None)
_migrate_lock = threading.Lock()


def schema_for(slug: str) -> str:
    """Schema name for a tenant slug. The slug CHECK in control.tenants keeps it a safe identifier."""
    return f"tenant_{slug}"


def role_for(slug: str) -> str:
    """The tenant's database role: ``app_t_<slug>_<8 hex of the database name>`` (#297).

    Roles belong to the whole PostgreSQL cluster, not one database, and several environments often share one
    cluster (#173). Without the database in the name, tenant ``acme`` in Dev and in Prod would be the same role,
    and Dev's runtime role could reach Prod's ``tenant_acme``. A hash keeps the name inside PostgreSQL's 63-byte
    limit for any database name (the slug is at most 41 characters); ``COMMENT ON ROLE`` says which it is.
    """
    return f"app_t_{slug}_{hashlib.sha256(settings.PG_DATABASE.encode()).hexdigest()[:8]}"


def current_schema() -> str | None:
    return _current.get()


def current_role() -> str | None:
    """The database role this request's connections run as, or None for the login role."""
    return _role.get()


def uploads_schema() -> str:
    return _current.get() or settings.UPLOADS_SCHEMA


def te_schema() -> str:
    return _current.get() or settings.TE_SCHEMA


@contextmanager
def scoped(schema: str, role: str | None = None):
    token, role_token = _current.set(schema), _role.set(role)
    try:
        yield
    finally:
        _role.reset(role_token)
        _current.reset(token)


def tenant(slug: str):
    """Route to one tenant: its schema, and its database role for every connection borrowed inside (#297)."""
    return scoped(schema_for(slug), role_for(slug))


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
    from api.db import owner_connect

    with owner_connect() as conn:
        with conn.cursor() as cur:
            migrate_te_schema(conn, cur, schema_for(slug))
            provision_tenant_role(cur, slug)


def provision_tenant_role(cur, slug: str) -> str:
    """Create or update the tenant's own role and give it its schema, and only that (#297). Returns the role.

    Run as the owner after every migration of the tenant (``migrate_tenant``), so it is also how tenants that
    existed before #297 get their role: the next API start migrates every tenant. Idempotent.

    - the role is NOLOGIN: the runtime role reaches it only through ``SET ROLE``;
    - the same rights the runtime role had (``grant_schema``): read and write, read and insert only on the
      append-only tables, and CREATE, so the per-upload ``csv_*`` tables the loader makes at run time are created
      by, and owned by, the tenant role. Ones made earlier by the owner or the runtime role are handed to it;
    - default privileges, so tables a later migration creates (as the owner) are granted too, before
      ``grant_schema`` runs again and takes UPDATE and DELETE back from the append-only ones;
    - the runtime role (APP_DB_USER) becomes a member WITH INHERIT FALSE: it may ``SET ROLE`` to the tenant role
      but has none of its rights without doing so, and its own rights on the schema are revoked. A pooled
      connection that has not switched role therefore reaches no tenant's data at all;
    - the owner becomes a member too, so it can hand tables over and, when APP_DB_USER is unset (dev), the API
      connecting as the owner still switches to the tenant role per request.
    Commits.
    """
    from api.db import grant_schema

    schema, role = schema_for(slug), role_for(slug)
    s, r = sql.Identifier(schema), sql.Identifier(role)
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    if cur.fetchone() is None:
        try:
            cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(r))
        except InsufficientPrivilege as exc:
            cur.connection.rollback()
            raise RuntimeError(
                f"Tenant {slug!r}: the owner {settings.PG_USER!r} may not create the tenant's database role {role!r} "
                f"(#297). Give it CREATEROLE, as a superuser or the server administrator: ALTER ROLE "
                f"{settings.PG_USER} CREATEROLE; (build/deploy_all.sh does this for the environments it deploys). "
                "See DECISIONS/2026-11-24-per-tenant-db-roles.md.") from exc
    cur.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(r, sql.Literal(
        f"Tenant {slug} in database {settings.PG_DATABASE}: rights on schema {schema} only (#297)")))
    cur.execute(sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE").format(r))
    grant_schema(cur, schema, role, create=True)
    cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT, INSERT, UPDATE, DELETE "
                        "ON TABLES TO {}").format(s, r))
    cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT USAGE, SELECT, UPDATE "
                        "ON SEQUENCES TO {}").format(s, r))
    runtime = settings.APP_DB_USER
    if runtime and runtime != settings.PG_USER:
        rt = sql.Identifier(runtime)
        cur.execute(sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(r, rt))
        # Tables the runtime role created before #297 (it owned them, so a REVOKE alone would not stop it).
        cur.execute("SELECT relname FROM pg_class WHERE relnamespace = %s::regnamespace AND relkind IN ('r', 'p') "
                    "AND pg_get_userbyid(relowner) = %s", (schema, runtime))
        for (table,) in cur.fetchall():
            cur.execute(sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(s, sql.Identifier(table), r))
        cur.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(s, rt))
        cur.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM {}").format(s, rt))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(s, rt))
    cur.connection.commit()
    return role


def drop_tenant_role(cur, slug: str) -> None:
    """Drop the tenant's role, after its schema is gone (#297). As the owner; the caller commits.

    ``DROP OWNED BY`` first removes what is left in this database: default privileges and any grants.
    """
    role = role_for(slug)
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    if cur.fetchone() is not None:
        cur.execute(sql.SQL("DROP OWNED BY {r}; DROP ROLE {r}").format(r=sql.Identifier(role)))


TE_VERSION_TABLE = "alembic_version_te"
TE_BASELINE = "te0001"
_TE_VERSION_COMMENT = re.compile(r"te_schema_version=(\w+)")


def _te_config(schema: str):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic_te"))
    cfg.attributes["schema"] = schema
    return cfg


def te_head() -> str:
    """The newest T&E migration this release knows (build/te_core_schema.sql must stamp the same)."""
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(_te_config("unused")).get_current_head()
    if head is None:
        raise RuntimeError("alembic_te has no migrations, so there is no T&E head revision")
    return head


def template_te_version(cur, template: str) -> str | None:
    """The T&E migration the template schema is at, as build/te_core_schema.sql stamped it."""
    cur.execute("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = %s", (template,))
    row = cur.fetchone()
    m = _TE_VERSION_COMMENT.search(row[0] or "") if row else None
    return m.group(1) if m else None


def _te_tables_present(cur, schema: str) -> set[str]:
    cur.execute("SELECT c.relname FROM pg_class c WHERE c.relnamespace = to_regnamespace(%s) "
                "AND c.relkind = 'r' AND c.relname = ANY(%s)", (schema, TE_TABLES))
    return {r[0] for r in cur.fetchall()}


def migrate_te_schema(conn, cur, schema: str) -> str:
    """Bring one tenant's T&E tables to the newest migration (#184). Returns what was done.

    - no T&E tables: clone them from the template (#99), stamp the tenant at the template's
      version, and upgrade from there;
    - tables but no version table (a tenant from before versioned migrations): stamp the
      baseline, then upgrade;
    - otherwise: upgrade.

    Each tenant's migrations are one transaction; one that fails (for instance on
    cross-program rows, which te0002 lists) leaves that tenant as it was. Serialised per
    tenant across processes by an advisory lock, so two API workers starting together
    cannot both provision or upgrade the same schema. Commits.
    """
    from alembic import command
    from alembic.util import CommandError

    cfg, template = _te_config(schema), settings.TE_SCHEMA
    cur.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (f"te_schema:{schema}",))
    try:
        present = _te_tables_present(cur, schema)
        cur.execute("SELECT to_regclass(%s)", (f'"{schema}"."{TE_VERSION_TABLE}"',))
        versioned = cur.fetchone()[0] is not None
        conn.commit()
        if versioned and len(present) == len(TE_TABLES):
            action, stamp = "upgraded", None
        elif not present:
            template_version = template_te_version(cur, template)
            if template_version is None:
                raise RuntimeError(
                    f"T&E template schema {template!r} has no te_schema_version stamp; it was deployed by an "
                    "older build/te_core_schema.sql. Redeploy it with build/deploy_all.sh first.")
            provision_te_tables(cur, schema, template)
            conn.commit()
            action, stamp = "provisioned", template_version
        else:
            if len(present) < len(TE_TABLES):
                provision_te_tables(cur, schema, template)
                conn.commit()
            action, stamp = "adopted", None if versioned else TE_BASELINE
        try:
            with _migrate_lock:  # Alembic's op/context are process-global; the advisory lock covers other processes
                if stamp:
                    command.stamp(cfg, stamp)
                command.upgrade(cfg, "head")
        except CommandError as exc:
            raise RuntimeError(f"Tenant schema {schema!r}: {exc}. If the template is newer than this release, "
                               "deploy the matching release; if older, redeploy it with "
                               "build/deploy_all.sh.") from exc
        return action
    finally:
        conn.rollback()
        cur.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (f"te_schema:{schema}",))
        conn.commit()


def _use_template_names(cur, schema: str, template: str, tables: list[str]) -> None:
    """Give the cloned indexes and unique constraints the template's names (#184).

    ``CREATE TABLE ... LIKE ... INCLUDING ALL`` names them by PostgreSQL's default rules
    (``test_cases_phase_id_idx``), not the template's (``idx_testcases_phase``). A migration
    that drops or renames an index by name would then work on the template and fail on every
    tenant. Matched on what each index is (table, columns, method), since the names differ.
    """
    def listing(sch: str) -> list[tuple]:
        cur.execute(
            "SELECT t.relname, i.relname, pg_get_indexdef(i.oid), c.conname FROM pg_index x "
            "JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid "
            "LEFT JOIN pg_constraint c ON c.conindid = x.indexrelid AND c.contype = 'u' "
            "WHERE t.relnamespace = %s::regnamespace AND t.relname = ANY(%s) AND NOT x.indisprimary",
            (sch, tables))
        return [(t, i, re.sub(r"^CREATE (UNIQUE )?INDEX \S+ ON \S+ ", r"\1", d), con)
                for t, i, d, con in cur.fetchall()]

    mine = {(t, tail): (i, con) for t, i, tail, con in listing(schema)}
    for table, name, tail, constraint in listing(template):
        have = mine.get((table, tail))
        if have is None or have[0] == name:
            continue
        if constraint and have[1]:  # renaming a unique constraint renames its index too
            cur.execute(sql.SQL("ALTER TABLE {}.{} RENAME CONSTRAINT {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(table), sql.Identifier(have[1]), sql.Identifier(constraint)))
        elif not constraint and not have[1]:
            cur.execute(sql.SQL("ALTER INDEX {}.{} RENAME TO {}").format(
                sql.Identifier(schema), sql.Identifier(have[0]), sql.Identifier(name)))


def provision_te_tables(cur, schema: str, template: str) -> int:
    """Give a tenant its own T&E tables, cloned from the deployment's T&E schema (#99).

    ``template`` is the schema build/deploy_all.sh created. Copies columns,
    defaults, checks, indexes and comments, then the foreign keys, the
    updated_at and program_id-fill functions and their triggers, re-pointed at ``schema``. Keys are
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
    _use_template_names(cur, schema, template, missing)

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
                "WHERE n.nspname = %s AND p.proname IN ('set_updated_at', 'te_fill_program_id')", (template,))
    for (ddl,) in cur.fetchall():
        cur.execute(sql.SQL(ddl.replace(f"FUNCTION {qt}.", f"FUNCTION {qs}.", 1)))
    for (ddl,) in defs(
            "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class r ON r.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = r.relnamespace "
            "WHERE n.nspname = %s AND NOT t.tgisinternal AND r.relname = ANY(%s)"):
        cur.execute(sql.SQL(ddl.replace(f" ON {qt}.", f" ON {qs}.").replace(f"FUNCTION {qt}.", f"FUNCTION {qs}.")))
    cur.execute("RESET search_path")
    return len(missing)
