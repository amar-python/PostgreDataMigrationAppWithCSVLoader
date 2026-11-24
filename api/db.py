"""Connection pool + Alembic-driven schema bootstrap for the uploads registry."""

import logging
import re
import sys
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

import psycopg2
import psycopg2.pool
from psycopg2 import sql

from api.config import settings

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
# Dedicated executor for the blocking pool.getconn() call. Kept small — one
# worker per potential concurrent waiter is plenty since getconn returns fast
# in the common case. Sized above maxconn so waiters can queue.
_getconn_executor: ThreadPoolExecutor | None = None
_MAXCONN = 8


class DatabaseConnectError(psycopg2.OperationalError):
    """The database could not be reached. The message already says why and what to check, so the
    scripts print it as it is (see run_cli) instead of showing a traceback."""


# Which connection failures can waiting fix? psycopg2 leaves exc.pgcode / exc.diag.sqlstate as None
# for connection-time errors (checked on 2.9.13: libpq returns a message, not a result), so SQLSTATEs
# such as 28P01 or 3D000 are not available and the classification reads libpq's message instead.
#
# libpq renders an error the server sent as "<SEVERITY>:  <message>" (two spaces; the words are the
# server's own language) and a client-side one (refused, timeout, DNS, dropped) without it. A server
# that answered with an error is up and has said no: a wrong or unknown login, no pg_hba.conf entry,
# a missing database, no CONNECT privilege and so on. That needs no list of texts, so a rejection
# nobody has listed, or one in another language, still fails fast.
_SERVER_SENT = re.compile(r"(?:^|failed: )[^\s:]+:  ")
# The exceptions: the server is up but cannot take the connection yet (SQLSTATE 57P03 and 53300).
_SERVER_BUSY = re.compile(r"the database system is|sorry, too many clients|remaining connection slots"
                          r"|too many connections for|could not fork new process")
# Client-side, but waiting cannot supply a password or add SSL to the server.
_CLIENT_CONFIG = re.compile(r"no password supplied|does not support SSL")
# ponytail: a server whose lc_messages is not English words "starting up" in its own language, so it
# looks like a rejection and fails fast instead of being retried. Ask the server for the SQLSTATE
# (a raw startup packet, as pg_isready does) if such a server is ever started by a container race.


def _is_permanent(exc: Exception) -> bool:
    msg = str(exc)
    return bool(_CLIENT_CONFIG.search(msg)) or (
        bool(_SERVER_SENT.search(msg)) and not _SERVER_BUSY.search(msg))


def _connect_error(exc: Exception, user: str, creds: str, *, attempts: int = 0,
                   permanent: bool = False, purpose: str = "") -> DatabaseConnectError:
    """``purpose`` says what the login was for (e.g. " to run the database migrations"), where the
    login differs from the one the person might expect."""
    msg = f"Could not connect to PostgreSQL at {settings.PG_HOST}:{settings.PG_PORT} as {user}{purpose}"
    if permanent:
        msg += ": the server was reached, but retrying will not help."
    else:
        msg += f" after {attempts} attempts." if attempts else "."
    check = f"Check {creds} (and PGDATABASE, PGHOST, PGPORT)"
    return DatabaseConnectError(
        f"{msg}\n  {str(exc).strip()}\n{check}{'.' if permanent else ' and that the server is running.'}")


def init_pool(max_attempts: int = 30, base_delay: float = 1.0) -> None:
    """Create the shared pool. Uses ThreadedConnectionPool so parallel FastAPI
    handlers can borrow/return connections without blocking each other's
    getconn() calls (SimpleConnectionPool is not thread-safe).

    BUG-026: on containerised infra Postgres may not accept connections when
    the API starts. Retry with exponential backoff (capped at 10s per attempt)
    instead of dying at boot. Total wait bounded by ``max_attempts`` × cap.
    Failures retrying cannot fix (wrong or missing password, no such
    database/role, no pg_hba.conf entry, ...) raise DatabaseConnectError on
    the first attempt; so does running out of attempts.
    """
    global _pool, _getconn_executor
    last_err: Exception | None = None
    user = settings.APP_DB_USER or settings.PG_USER
    creds = "APP_DB_USER / APP_DB_PASSWORD" if settings.APP_DB_USER else "PGUSER / PGPASSWORD"
    for attempt in range(1, max_attempts + 1):
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=_MAXCONN,
                host=settings.PG_HOST,
                port=settings.PG_PORT,
                user=user,
                password=settings.APP_DB_PASSWORD if settings.APP_DB_USER else settings.PG_PASSWORD,
                dbname=settings.PG_DATABASE,
            )
            if attempt > 1:
                logger.info("Connected to Postgres on attempt %d", attempt)
            break
        except psycopg2.OperationalError as exc:
            if _is_permanent(exc):
                raise _connect_error(exc, user, creds, permanent=True) from exc
            last_err = exc
            delay = min(base_delay * (2 ** (attempt - 1)), 10.0)
            logger.warning(
                "Postgres not reachable (attempt %d/%d): %s. Retrying in %.1fs.",
                attempt, max_attempts, str(exc).split("\n")[0][:120], delay,
            )
            time.sleep(delay)
    else:
        assert last_err is not None
        raise _connect_error(last_err, user, creds, attempts=max_attempts) from last_err

    # BUG-030: worker count = maxconn + a few, so a burst of concurrent
    # requests can all queue their getconn() calls without the executor
    # itself becoming the bottleneck.
    _getconn_executor = ThreadPoolExecutor(
        max_workers=_MAXCONN + 4, thread_name_prefix="pool-getconn"
    )


def close_pool() -> None:
    global _pool, _getconn_executor
    if _pool is not None:
        _pool.closeall()
        _pool = None
    if _getconn_executor is not None:
        _getconn_executor.shutdown(wait=False, cancel_futures=True)
        _getconn_executor = None


def _borrow_with_timeout():
    """Wrap pool.getconn() so a hung/exhausted pool raises PoolError instead
    of blocking the request thread forever.

    ThreadedConnectionPool.getconn() has no built-in timeout parameter, so we
    dispatch the blocking call to a worker thread and enforce the deadline
    with Future.result(timeout=...). On timeout we raise psycopg2.pool.PoolError,
    which the pool_exhausted_handler in api/main.py maps to HTTP 503.
    """
    assert _pool is not None and _getconn_executor is not None
    future = _getconn_executor.submit(_pool.getconn)
    try:
        return future.result(timeout=settings.POOL_GETCONN_TIMEOUT)
    except FuturesTimeout as exc:
        # Best-effort: if the getconn eventually succeeds, return it to the
        # pool so we don't permanently lose a slot. cancel() only works if
        # the task hasn't started yet; getconn is a blocking call that
        # started immediately, so we can't cancel it — but adding a done
        # callback returns the connection if it arrives late.
        def _return_late_conn(fut):
            try:
                conn = fut.result(timeout=0)
                _pool.putconn(conn)
                logger.warning(
                    "getconn() succeeded after the %.1fs timeout; returning "
                    "the connection to the pool.",
                    settings.POOL_GETCONN_TIMEOUT,
                )
            except Exception:  # noqa: BLE001 — timeout retry: best-effort
                pass
        future.add_done_callback(_return_late_conn)
        raise psycopg2.pool.PoolError(
            f"Could not obtain a database connection within "
            f"{settings.POOL_GETCONN_TIMEOUT}s (pool of {_MAXCONN} exhausted)."
        ) from exc


class Conn:
    """Context manager that borrows a pooled connection and always returns it.

    BUG-030: getconn() is now bounded by POOL_GETCONN_TIMEOUT. If the pool is
    exhausted for longer than that, this raises psycopg2.pool.PoolError which
    api/main.py surfaces as HTTP 503 (Server busy, please retry shortly).

    #297: borrowed inside a tenant's scope (``api.tenancy.tenant``), the connection switches to that tenant's
    database role first, in a transaction of its own, so a later rollback by the caller cannot undo it. On the way
    back to the pool it always returns to the login role, error or not; a connection that cannot is closed, never
    pooled, so no request inherits another tenant's role.
    """

    def __enter__(self):
        if _pool is None:
            raise RuntimeError("DB pool not initialised — call init_pool() first")
        self._conn = _borrow_with_timeout()
        from api.tenancy import current_role

        role = current_role()
        if role:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
                self._conn.commit()
            except Exception:
                _pool.putconn(self._conn, close=True)
                raise
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        conn, close = self._conn, False
        try:
            # Rolling back first discards what the caller left uncommitted (putconn would anyway) and means the
            # RESET below is committed on its own: a RESET inside an open transaction would be undone by its rollback.
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
            conn.commit()
        except Exception:  # noqa: BLE001 — a connection whose role is unknown must not go back to the pool
            close = True
        _pool.putconn(conn, close=close or conn.closed != 0)
        return False


@contextmanager
def acting_role(cur):
    """Switch an open connection to the current tenant's role for a block, then back to the login role (#297).

    For the rare request that borrowed its connection before the tenant was known and then writes to the tenant's
    schema in the same transaction (a password reset and its audit entry). On an error the block's transaction is
    rolled back, which undoes the SET ROLE, and ``Conn`` resets the role again on return.
    """
    from api.tenancy import current_role

    role = current_role()
    if not role:
        raise RuntimeError("acting_role needs a tenant scope (api.tenancy.tenant)")
    cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
    yield
    cur.execute("RESET ROLE")


def bootstrap() -> None:
    """Bring the uploads schema to head via Alembic.

    BUG-032: previously this function ran hand-written CREATE TABLE IF NOT EXISTS
    statements. That was idempotent for the initial deploy but did nothing on
    schema evolution — an ALTER TABLE added in a later release wouldn't ever
    run on an existing deployment.

    Now this function invokes `alembic upgrade head` in-process against the
    same database the API pool is configured for (see alembic/env.py, which
    reads the same api.config.settings values). Every startup checks the
    current schema version and applies any pending migrations transactionally.

    Idempotent: if the DB is already at head, this is a no-op that costs one
    `SELECT version_num FROM alembic_version` query.

    Safe to call after init_pool() — Alembic opens its own SQLAlchemy engine
    with a NullPool and doesn't share connections with the API pool.
    """
    # Deferred imports so pytest collection of api/ doesn't pull in Alembic
    # unless bootstrap() is actually called (e.g. in the lifespan handler,
    # which is only invoked by tests using TestClient as a context manager).
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

    alembic_ini = alembic_ini_path()

    if not alembic_ini.exists():
        # #317 (BR-35): the hand-written fallback schema has no hash chain and no append-only triggers,
        # so a deployment with a packaging mistake would run without the audit protections, silently.
        # Only dev may use it; anywhere else the API refuses to start.
        if settings.API_ENV != "dev":
            raise RuntimeError(
                f"alembic.ini not found at {alembic_ini}; refusing to start without migrations "
                f"(API_ENV is '{settings.API_ENV}', and the audit triggers would be missing). "
                "Check that alembic.ini, alembic/ and alembic_te/ are in the deployment, "
                "or set API_ENV=dev for local development."
            )
        logger.error(
            "alembic.ini not found at %s: falling back to the hand-written schema, which has NO audit "
            "hash chain and NO append-only triggers. Tolerated only because API_ENV=dev. Add alembic.ini "
            "and the alembic/ versions directory to get the real schema.",
            alembic_ini,
        )
        _bootstrap_fallback_schema()
        return

    cfg = Config(str(alembic_ini))
    logger.info("Running alembic upgrade head against %s@%s:%s/%s",
                settings.PG_USER, settings.PG_HOST, settings.PG_PORT,
                settings.PG_DATABASE)
    try:
        command.upgrade(cfg, "head")
    except SQLAlchemyOperationalError as exc:
        # SQLAlchemy wraps psycopg2's error; classify and show the original, so the server's
        # own words are not buried in SQLAlchemy's "(Background on this error at ...)" text.
        orig = getattr(exc, "orig", None) or exc
        if not _is_permanent(orig):
            raise
        # The migrations log in as the owner (PGUSER), not as the runtime role the pool
        # uses, so a pool that connected fine can still stop here. Raise the short, named
        # error instead of SQLAlchemy's chained traceback (~70 lines on Windows).
        raise _connect_error(orig, settings.PG_USER, "PGUSER / PGPASSWORD", permanent=True,
                             purpose=" to run the database migrations") from None
    with owner_connect() as conn, conn.cursor() as cur:
        for schema, create in ((settings.UPLOADS_SCHEMA, True), (settings.CONTROL_SCHEMA, False),
                               (settings.TE_SCHEMA, False)):
            grant_runtime(cur, schema, create=create)
    _migrate_existing_tenants()
    logger.info("Alembic migrations complete")
    if not settings.APP_DB_USER:
        logger.warning("APP_DB_USER is not set: the API connects as the owner %r, so the database "
                       "doesn't stop it changing the audit log (M3d). See docs/QUICKSTART.md.",
                       settings.PG_USER)


@contextmanager
def owner_connect():
    """A connection as the owner (PG_USER): for migrations, provisioning and grants, never requests.
    Closed on exit; the caller commits."""
    try:
        conn = psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                                password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)
    except psycopg2.OperationalError as exc:
        raise _connect_error(exc, settings.PG_USER, "PGUSER / PGPASSWORD", permanent=_is_permanent(exc)) from exc
    try:
        yield conn
    finally:
        conn.close()


def run_cli(main) -> int:
    """Run a script's main(). A connection failure prints its message and returns 1, not a traceback."""
    try:
        return main()
    except DatabaseConnectError as exc:
        print(exc, file=sys.stderr)
        return 1


# Tables the runtime role may only read and insert (M3, #107). Triggers also stop the owner.
APPEND_ONLY = ("audit_log", "uploads", "upload_blobs", "source_rows", "row_decisions", "cell_edits",
               "row_flags", "submissions", "approvals", "imports", "alembic_version", "alembic_version_te")


def grant_runtime(cur, schema: str, create: bool) -> None:
    """Give the runtime role (APP_DB_USER) what requests need in one of the deployment's own schemas (M3d, #107).

    For the default, control and T&E template schemas only. A tenant's schema is granted to the tenant's own role
    instead (``api.tenancy.provision_tenant_role``, #297). Commits. No-op without APP_DB_USER.
    """
    if settings.APP_DB_USER:
        grant_schema(cur, schema, settings.APP_DB_USER, create)


def grant_schema(cur, schema: str, role: str, create: bool) -> None:
    """Give ``role`` what requests need in one schema (M3d, #107).

    Read and write on ordinary tables; read and insert only on APPEND_ONLY.
    ``create`` lets it create, and so own and drop, the per-upload csv_* tables;
    ones someone else created are handed over. Commits. No-op if the schema doesn't exist.
    """
    cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
    if cur.fetchone() is None:
        return
    s, r = sql.Identifier(schema), sql.Identifier(role)
    cur.execute(sql.SQL("GRANT USAGE{} ON SCHEMA {} TO {}").format(
        sql.SQL(", CREATE") if create else sql.SQL(""), s, r))
    cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(s, r))
    cur.execute(sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {} TO {}").format(s, r))
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = %s::regnamespace AND relname = ANY(%s)",
                (schema, list(APPEND_ONLY)))
    for (table,) in cur.fetchall():
        cur.execute(sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {}.{} FROM {}").format(
            s, sql.Identifier(table), r))
    cur.execute("SELECT to_regclass(%s)", (f'"{schema}".csv_files',))
    if create and cur.fetchone()[0] is not None:
        cur.execute(sql.SQL(
            "SELECT c.relname FROM {}.csv_files f JOIN pg_class c ON c.relname = f.table_name "
            "AND c.relnamespace = %s::regnamespace WHERE f.mode = 'dynamic' "
            "AND pg_get_userbyid(c.relowner) <> %s").format(s), (schema, role))
        for (table,) in cur.fetchall():
            cur.execute(sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(s, sql.Identifier(table), r))
    cur.connection.commit()


def alembic_ini_path() -> Path:
    return Path(__file__).resolve().parent.parent / "alembic.ini"


def _migrate_existing_tenants() -> None:
    """Bring every tenant schema to head too (decision 6: migrations run across N schemas)."""
    from api.tenancy import migrate_tenant

    with owner_connect() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT slug FROM {}.tenants ORDER BY id").format(
            sql.Identifier(settings.CONTROL_SCHEMA)))
        slugs = [r[0] for r in cur.fetchall()]
    for slug in slugs:
        migrate_tenant(slug)
    if slugs:
        logger.info("Migrated %d tenant schema(s)", len(slugs))


def _bootstrap_fallback_schema() -> None:
    """Idempotent CREATE TABLE IF NOT EXISTS bootstrap used when Alembic isn't
    wired up (see bootstrap() above). Mirrors the columns every INSERT/SELECT
    in api/services/*.py and api/routers/*.py already assumes exist.

    This does not track schema versions — any future column addition needs a
    real Alembic migration (or a manual ALTER) to reach already-bootstrapped
    databases. It only guarantees the schema exists at all on a fresh DB.
    """
    schema = settings.UPLOADS_SCHEMA
    with Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.csv_files (
                        id BIGSERIAL PRIMARY KEY,
                        file_name TEXT NOT NULL UNIQUE,
                        file_hash TEXT NOT NULL UNIQUE,
                        table_name TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        row_count INTEGER NOT NULL DEFAULT 0,
                        column_names TEXT[] NOT NULL DEFAULT '{{}}',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        total_rows INTEGER,
                        duplicate_rows_skipped INTEGER,
                        failed_rows INTEGER
                    )
                    """
                ).format(sql.Identifier(schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.audit_log (
                        id BIGSERIAL PRIMARY KEY,
                        action TEXT NOT NULL,
                        file_id BIGINT,
                        file_name TEXT,
                        table_name TEXT,
                        mode TEXT,
                        performed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                ).format(sql.Identifier(schema))
            )
        conn.commit()
    logger.info("Fallback bootstrap complete: schema %s ready (csv_files, audit_log)", schema)
