"""Unit tests for api/db.py, the app-level error handlers in api/main.py and
the database-free guard paths of the loaders. All database access is faked.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import psycopg2
import psycopg2.pool
import pytest
from fastapi.testclient import TestClient

from api import db
from api.config import settings
from api.main import app
from api.services import dynamic_loader, te_loader

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_pool():
    """Swap the module-level pool/executor for test doubles, then restore."""
    saved = (db._pool, db._getconn_executor, settings.POOL_GETCONN_TIMEOUT)
    yield
    if db._getconn_executor is not None and db._getconn_executor is not saved[1]:
        db._getconn_executor.shutdown(wait=False, cancel_futures=True)
    db._pool, db._getconn_executor, settings.POOL_GETCONN_TIMEOUT = saved


class TestConn:
    def test_raises_when_pool_not_initialised(self, isolated_pool):
        """Using Conn before init_pool() fails loudly, not with AttributeError."""
        db._pool = None
        with pytest.raises(RuntimeError, match="not initialised"):
            with db.Conn():
                pass

    def test_returns_connection_on_success(self, isolated_pool):
        """The borrowed connection is always returned to the pool."""
        conn = mock.MagicMock()
        db._pool = mock.MagicMock(getconn=mock.MagicMock(return_value=conn))
        db._getconn_executor = ThreadPoolExecutor(max_workers=1)
        with db.Conn() as c:
            assert c is conn
        db._pool.putconn.assert_called_once_with(conn)
        conn.rollback.assert_not_called()

    def test_rolls_back_and_returns_connection_on_error(self, isolated_pool):
        """An exception inside the block rolls back and still returns the slot."""
        conn = mock.MagicMock()
        db._pool = mock.MagicMock(getconn=mock.MagicMock(return_value=conn))
        db._getconn_executor = ThreadPoolExecutor(max_workers=1)
        with pytest.raises(ValueError):
            with db.Conn():
                raise ValueError("boom")
        conn.rollback.assert_called_once()
        db._pool.putconn.assert_called_once_with(conn)


class TestBorrowWithTimeout:
    def test_hung_getconn_raises_pool_error(self, isolated_pool):
        """BUG-030: a blocking getconn() surfaces as PoolError after the timeout."""
        release = threading.Event()
        db._pool = mock.MagicMock(getconn=mock.MagicMock(side_effect=lambda: release.wait(5)))
        db._getconn_executor = ThreadPoolExecutor(max_workers=1)
        settings.POOL_GETCONN_TIMEOUT = 0.1
        try:
            with pytest.raises(psycopg2.pool.PoolError, match="exhausted"):
                db._borrow_with_timeout()
        finally:
            release.set()

    def test_late_connection_is_returned_to_pool(self, isolated_pool):
        """A getconn() that completes after the timeout gives its slot back."""
        release = threading.Event()
        late_conn = object()

        def slow_getconn():
            release.wait(5)
            return late_conn

        pool = mock.MagicMock(getconn=mock.MagicMock(side_effect=slow_getconn))
        db._pool = pool
        db._getconn_executor = ThreadPoolExecutor(max_workers=1)
        settings.POOL_GETCONN_TIMEOUT = 0.1
        with pytest.raises(psycopg2.pool.PoolError):
            db._borrow_with_timeout()
        release.set()
        db._getconn_executor.shutdown(wait=True)
        pool.putconn.assert_called_once_with(late_conn)


class TestInitPool:
    def test_retries_until_postgres_is_reachable(self, isolated_pool):
        """BUG-026: transient OperationalError is retried with backoff."""
        attempts = []

        def flaky_pool(**kwargs):
            attempts.append(kwargs)
            if len(attempts) < 3:
                raise psycopg2.OperationalError("not yet")
            return mock.MagicMock()

        with mock.patch.object(db.psycopg2.pool, "ThreadedConnectionPool", side_effect=flaky_pool), \
                mock.patch.object(db.time, "sleep") as sleep:
            db.init_pool(max_attempts=5, base_delay=1.0)
        assert len(attempts) == 3
        assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]
        assert attempts[-1]["maxconn"] == db._MAXCONN

    def test_backoff_is_capped_at_ten_seconds(self, isolated_pool):
        """Exponential backoff never sleeps longer than 10s per attempt."""
        with mock.patch.object(db.psycopg2.pool, "ThreadedConnectionPool",
                               side_effect=psycopg2.OperationalError("down")), \
                mock.patch.object(db.time, "sleep") as sleep:
            with pytest.raises(psycopg2.OperationalError):
                db.init_pool(max_attempts=6, base_delay=1.0)
        assert max(c.args[0] for c in sleep.call_args_list) == 10.0

    def test_gives_up_after_max_attempts(self, isolated_pool):
        """The last OperationalError is re-raised once attempts run out."""
        with mock.patch.object(db.psycopg2.pool, "ThreadedConnectionPool",
                               side_effect=psycopg2.OperationalError("down")) as ctor, \
                mock.patch.object(db.time, "sleep"):
            with pytest.raises(psycopg2.OperationalError, match="down"):
                db.init_pool(max_attempts=3)
        assert ctor.call_count == 3


class TestBootstrap:
    def test_falls_back_when_alembic_ini_missing(self, tmp_path):
        """Without alembic.ini the hand-written CREATE IF NOT EXISTS path runs."""
        with mock.patch.object(db, "Path") as path_cls, \
                mock.patch.object(db, "_bootstrap_fallback_schema") as fallback:
            path_cls.return_value.resolve.return_value.parent.parent = tmp_path
            db.bootstrap()
        fallback.assert_called_once()


class TestAppErrorHandling:
    def test_pool_exhaustion_maps_to_503(self):
        """A PoolError anywhere in a handler becomes HTTP 503, not 500."""
        client = TestClient(app)
        with mock.patch("api.routers.csv_routes.Conn",
                        side_effect=psycopg2.pool.PoolError("exhausted")):
            r = client.get("/api/csv/files")
        assert r.status_code == 503
        assert "retry" in r.json()["detail"].lower()

    def test_health_degrades_without_leaking_details(self, isolated_pool):
        """When the DB is unreachable /api/health returns 200 'degraded' with
        no host/user/driver text in the body."""
        db._pool = None
        r = TestClient(app).get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert settings.PG_HOST not in str(body) and "pool" not in str(body).lower()

    def test_preview_parse_crash_returns_structured_error(self):
        """BUG-025: a parser exception never surfaces as a raw 500."""
        with mock.patch("api.routers.csv_routes.build_preview", side_effect=RecursionError("x")):
            r = TestClient(app).post("/api/csv/preview", json={"fileName": "a.csv", "content": "a\n1\n"})
        assert r.status_code == 200
        assert r.json()["status"] == "invalid_structure"

    def test_preview_te_match_is_best_effort(self, isolated_pool):
        """If the T&E lookup fails the preview still succeeds with a null match."""
        db._pool = None  # te_table_columns() will raise RuntimeError
        r = TestClient(app).post("/api/csv/preview", json={"fileName": "a.csv", "content": "a\n1\n"})
        assert r.json()["status"] == "ok"
        assert r.json()["teTableMatch"] is None

    def test_cors_allows_frontend_dev_server_by_default(self):
        """The Vite dev server origin (localhost, port 8080) is allowed by default
        (regression for issue #43)."""
        assert "http://localhost:8080" in settings.CORS_ORIGINS
        r = TestClient(app).options("/api/csv/files", headers={
            "Origin": "http://localhost:8080", "Access-Control-Request-Method": "GET"})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "http://localhost:8080"

    def test_cors_still_refuses_unlisted_origins(self):
        """Adding :8080 did not open CORS up: an unlisted origin is refused (issue #43)."""
        r = TestClient(app).options("/api/csv/files", headers={
            "Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
        assert r.status_code == 400
        assert "access-control-allow-origin" not in r.headers

    def test_cors_methods_are_restricted(self):
        """Only GET/POST/DELETE are advertised to browsers."""
        origin = settings.CORS_ORIGINS[0]
        r = TestClient(app).options("/api/csv/files", headers={
            "Origin": origin, "Access-Control-Request-Method": "PUT"})
        assert "PUT" not in r.headers.get("access-control-allow-methods", "")


class TestLoaderGuardsWithoutDatabase:
    """Structural rejections happen before any database access."""

    @pytest.fixture(autouse=True)
    def _no_db(self, isolated_pool):
        db._pool = None

    @pytest.mark.parametrize(
        "content, reason",
        [("", "empty"), ("a,b\n", "header_only"), (",\n1,2\n", "no_columns")],
    )
    def test_dynamic_structure_errors(self, content, reason):
        """Empty, header-only and blank-header files are rejected with a message."""
        out = dynamic_loader.upload_dynamic("f.csv", content, None, False)
        assert out["status"] == "invalid_structure"
        assert out["reason"] == reason and out["message"]

    def test_dynamic_row_cap(self, monkeypatch):
        """BUG-027: files above MAX_ROWS are rejected up-front."""
        monkeypatch.setattr(settings, "MAX_ROWS", 3)
        out = dynamic_loader.upload_dynamic("f.csv", "a\n1\n2\n3\n4\n", None, False)
        assert out["status"] == "error" and "at most 3" in out["message"]

    def test_dynamic_logs_have_frontend_shape(self):
        """Every processing-log entry carries ts/step/level/message."""
        out = dynamic_loader.upload_dynamic("f.csv", "", None, False)
        assert out["logs"] and all({"ts", "step", "level", "message"} <= set(e) for e in out["logs"])

    def test_te_rejects_unknown_target_table(self):
        """Only the 12 whitelisted T&E tables are accepted."""
        out = te_loader.upload_te("f.csv", "a\n1\n", "pg_authid")
        assert out["status"] == "error" and "not a T&E table" in out["message"]

    @pytest.mark.parametrize("content, reason", [("", "empty"), ("name\n", "header_only")])
    def test_te_structure_errors(self, content, reason):
        """T&E mode needs a header and at least one data row."""
        out = te_loader.upload_te("f.csv", content, "organisations")
        assert out["status"] == "invalid_structure" and out["reason"] == reason

    def test_te_row_cap(self, monkeypatch):
        """BUG-027: the row cap also applies in T&E mode."""
        monkeypatch.setattr(settings, "MAX_ROWS", 1)
        out = te_loader.upload_te("f.csv", "name\na\nb\n", "organisations")
        assert out["status"] == "error" and "at most 1" in out["message"]
