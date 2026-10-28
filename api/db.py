"""Connection pool + Alembic-driven schema bootstrap for the uploads registry."""

import logging
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


def init_pool(max_attempts: int = 30, base_delay: float = 1.0) -> None:
    """Create the shared pool. Uses ThreadedConnectionPool so parallel FastAPI
    handlers can borrow/return connections without blocking each other's
    getconn() calls (SimpleConnectionPool is not thread-safe).

    BUG-026: on containerised infra Postgres may not accept connections when
    the API starts. Retry with exponential backoff (capped at 10s per attempt)
    instead of dying at boot. Total wait bounded by ``max_attempts`` × cap.
    """
    global _pool, _getconn_executor
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=_MAXCONN,
                host=settings.PG_HOST,
                port=settings.PG_PORT,
                user=settings.APP_DB_USER or settings.PG_USER,
                password=settings.APP_DB_PASSWORD if settings.APP_DB_USER else settings.PG_PASSWORD,
                dbname=settings.PG_DATABASE,
            )
            if attempt > 1:
                logger.info("Connected to Postgres on attempt %d", attempt)
            break
        except psycopg2.OperationalError as exc:
            last_err = exc
            delay = min(base_delay * (2 ** (attempt - 1)), 10.0)
            logger.warning(
                "Postgres not reachable (attempt %d/%d): %s. Retrying in %.1fs.",
                attempt, max_attempts, str(exc).split("\n")[0][:120], delay,
            )
            time.sleep(delay)
    else:
        assert last_err is not None
        raise last_err

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
    """

    def __enter__(self):
        if _pool is None:
            raise RuntimeError("DB pool not initialised — call init_pool() first")
        self._conn = _borrow_with_timeout()
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._conn.rollback()
        _pool.putconn(self._conn)
        return False


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

    alembic_ini = alembic_ini_path()

    if not alembic_ini.exists():
        logger.warning(
            "alembic.ini not found at %s — falling back to hand-written "
            "CREATE TABLE IF NOT EXISTS bootstrap. Add alembic.ini + an "
            "alembic/ versions directory to get real schema-evolution support.",
            alembic_ini,
        )
        _bootstrap_fallback_schema()
        return

    cfg = Config(str(alembic_ini))
    logger.info("Running alembic upgrade head against %s@%s:%s/%s",
                settings.PG_USER, settings.PG_HOST, settings.PG_PORT,
                settings.PG_DATABASE)
    command.upgrade(cfg, "head")
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
    conn = psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                            password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)
    try:
        yield conn
    finally:
        conn.close()


# Tables the runtime role may only read and insert (M3, #107). Triggers also stop the owner.
APPEND_ONLY = ("audit_log", "uploads", "upload_blobs", "source_rows", "row_decisions", "cell_edits",
               "alembic_version")


def grant_runtime(cur, schema: str, create: bool) -> None:
    """Give the runtime role (APP_DB_USER) what requests need in one schema (M3d, #107).

    Read and write on ordinary tables; read and insert only on APPEND_ONLY.
    ``create`` lets it create, and so own and drop, the per-upload csv_* tables;
    ones the owner created before M3d are handed over. Commits. No-op without
    APP_DB_USER or if the schema doesn't exist.
    """
    role = settings.APP_DB_USER
    if not role:
        return
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
