"""Connection pool + Alembic-driven schema bootstrap for the uploads registry."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

import psycopg2
import psycopg2.pool

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
                user=settings.PG_USER,
                password=settings.PG_PASSWORD,
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

    repo_root = Path(__file__).resolve().parent.parent
    alembic_ini = repo_root / "alembic.ini"

    if not alembic_ini.exists():
        logger.warning(
            "alembic.ini not found at %s — skipping Alembic migration. "
            "Schema must be provisioned manually (bash scripts/provision_full_test_env.sh).",
            alembic_ini,
        )
        return

    cfg = Config(str(alembic_ini))
    logger.info("Running alembic upgrade head against %s@%s:%s/%s",
                settings.PG_USER, settings.PG_HOST, settings.PG_PORT,
                settings.PG_DATABASE)
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations complete")
