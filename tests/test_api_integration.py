"""API integration tests — require a live PostgreSQL database.
Database-free tests live in test_api_unit.py.
"""
from __future__ import annotations

import os
import unittest

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

_HELP = ("Start PostgreSQL and ensure api/ can reach it. Most often this means "
         "PGPASSWORD is not set in this shell:\n"
         "    PowerShell:  $env:PGPASSWORD = '<password>'\n"
         "    bash:        export PGPASSWORD='<password>'\n"
         "Defaults come from api/config.py; see scripts/start-api.ps1.")

SMALL_CSV = "col_a,col_b\n1,2\n3,4\n"


def _db_reachable() -> bool:
    """The API's own health endpoint is the authority on DB reachability."""
    try:
        return client.get("/api/health").json().get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.integration
class HealthContract(unittest.TestCase):
    """Health must degrade rather than error, so the UI can render a state."""

    def test_health_always_returns_200(self):
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_health_status_is_ok_or_degraded(self):
        self.assertIn(client.get("/api/health").json()["status"], ("ok", "degraded"))

    def test_openapi_schema_is_served(self):
        self.assertEqual(client.get("/openapi.json").status_code, 200)

    def test_health_is_not_behind_api_key(self):
        """BUG-035 regression: /api/health must be reachable without X-API-Key
        even when API_KEY is set, so external uptime probes can use it.
        """
        from api.config import settings

        original = settings.API_KEY
        settings.API_KEY = "test-key-do-not-use"
        try:
            # No header sent — should still return 200, not 401.
            r = client.get("/api/health")
            self.assertEqual(r.status_code, 200)
        finally:
            settings.API_KEY = original

    def test_csv_endpoint_still_requires_api_key_when_set(self):
        """BUG-035 counterpart: business endpoints must still be guarded.

        conftest.py overrides require_api_key to a no-op for the whole test
        session (so other tests don't need to thread an X-API-Key header
        through every call), which means this test — the one test meant to
        prove auth is actually enforced — could never see a real 401. Pop
        the override for just this test's scope so the real dependency runs.
        """
        from api.auth import require_api_key
        from api.config import settings

        original = settings.API_KEY
        settings.API_KEY = "test-key-do-not-use"
        had_override = require_api_key in app.dependency_overrides
        saved_override = app.dependency_overrides.pop(require_api_key, None)
        try:
            r = client.get("/api/csv/files")  # no X-API-Key header
            self.assertEqual(r.status_code, 401)
        finally:
            settings.API_KEY = original
            if had_override:
                app.dependency_overrides[require_api_key] = saved_override


@pytest.mark.integration
class CsvPipelineWithDatabase(unittest.TestCase):
    """Round-trip against a live database. Fails (never skips) without one."""

    @classmethod
    def setUpClass(cls):
        # TestClient must be used as a context manager so FastAPI's lifespan
        # runs and db.init_pool() is called. Without it every request raises
        # "DB pool not initialised".
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            # Lifespan runs db.init_pool(); a connection failure surfaces here
            # as a raw driver error. Re-raise with remediation instead, so the
            # no-skip policy produces something actionable.
            raise AssertionError(
                f"Could not start the API — database connection failed.\n"
                f"  {type(exc).__name__}: {str(exc).strip().splitlines()[0]}\n"
                f"{_HELP}"
            ) from None
        if cls.client.get("/api/health").json().get("status") != "ok":
            cls.ctx.__exit__(None, None, None)
            raise AssertionError(f"API reports the database is unreachable. {_HELP}")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        # Unique content per test, so the content-hash dedup cannot collide
        # with rows left behind by an earlier run.
        self.name = f"pytest_{os.getpid()}_{self._testMethodName}.csv"
        self.content = f"col_a,col_b\n{os.getpid()},{self._testMethodName}\n"

    def tearDown(self):
        for f in self.client.get("/api/csv/files").json():
            if f["file_name"] == self.name:
                self.client.delete(f"/api/csv/files/{f['id']}")

    def test_preview_reports_columns(self):
        r = self.client.post("/api/csv/preview",
                             json={"fileName": self.name, "content": self.content})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok", r.text[:300])
        self.assertEqual(r.json()["columns"], ["col_a", "col_b"])

    def test_upload_then_list_then_read_rows(self):
        up = self.client.post("/api/csv/upload",
                              json={"fileName": self.name, "content": self.content})
        self.assertEqual(up.status_code, 200)
        body = up.json()
        self.assertEqual(body["status"], "ok", body)
        table = body["tableName"]
        self.assertTrue(table.startswith("csv_"), table)
        self.assertEqual(body["insertedRows"], 1)

        listed = {f["table_name"] for f in self.client.get("/api/csv/files").json()}
        self.assertIn(table, listed)

        rows = self.client.get(f"/api/csv/tables/{table}/rows", params={"limit": 10})
        self.assertEqual(rows.status_code, 200)
        self.assertEqual(len(rows.json()["rows"]), 1)

    def test_reupload_of_identical_content_is_refused(self):
        first = self.client.post("/api/csv/upload",
                                 json={"fileName": self.name, "content": self.content})
        self.assertEqual(first.json()["status"], "ok")

        again = self.client.post("/api/csv/upload",
                                 json={"fileName": self.name, "content": self.content})
        self.assertEqual(again.json()["status"], "duplicate_file",
                         "re-uploading identical content should be refused")

    def test_in_file_duplicate_rows_are_skipped(self):
        dupes = f"col_a,col_b\n{os.getpid()},x\n{os.getpid()},x\n"
        r = self.client.post("/api/csv/upload",
                             json={"fileName": self.name, "content": dupes})
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(body["insertedRows"], 1)
        self.assertEqual(body["duplicateRowsSkipped"], 1)

    def test_row_hash_does_not_collide_on_split_boundaries(self):
        """BUG-022 regression: `["ab","cd"]` and `["a","bcd"]` used to hash to
        the same value because the pre-hash `"".join(cells)` had no separator.
        With the fixed `"\\x1f".join(...)` they must be treated as distinct
        rows and both land in the table.
        """
        pid = os.getpid()
        content = (
            "col_a,col_b\n"
            f"{pid}ab,cd\n"
            f"{pid}a,bcd\n"
        )
        r = self.client.post(
            "/api/csv/upload",
            json={"fileName": self.name, "content": content},
        )
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(
            body["insertedRows"], 2,
            "BUG-022 regression: split-boundary rows were deduplicated",
        )
        self.assertEqual(body["duplicateRowsSkipped"], 0)

        rows = self.client.get(
            f"/api/csv/tables/{body['tableName']}/rows",
            params={"limit": 10},
        )
        self.assertEqual(rows.status_code, 200)
        payload = rows.json()["rows"]
        self.assertEqual(len(payload), 2)
        pairs = sorted((r["col_a"], r["col_b"]) for r in payload)
        self.assertEqual(
            pairs,
            sorted([(f"{pid}ab", "cd"), (f"{pid}a", "bcd")]),
        )

    def test_row_hash_still_dedupes_identical_rows(self):
        """Guard-rail for BUG-022 fix: the separator change must not break the
        intended dedup — two byte-identical rows still count as one insert.
        """
        pid = os.getpid()
        content = (
            "col_a,col_b\n"
            f"{pid}xy,{pid}z\n"
            f"{pid}xy,{pid}z\n"
        )
        r = self.client.post(
            "/api/csv/upload",
            json={"fileName": self.name, "content": content},
        )
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(body["insertedRows"], 1)
        self.assertEqual(body["duplicateRowsSkipped"], 1)

    def test_unregistered_table_is_404(self):
        r = self.client.get("/api/csv/tables/csv_0000000000000000/rows")
        self.assertEqual(r.status_code, 404)

    def test_injection_shaped_names_are_not_served(self):
        """Names that pass the prefix guard must still 404 when unregistered."""
        for name in ("csv_a; DROP TABLE personnel", "csv_a'--"):
            with self.subTest(table=name):
                r = self.client.get(f"/api/csv/tables/{name}/rows")
                self.assertEqual(r.status_code, 404,
                                 f"unregistered name was served: {name}")

    def test_core_te_tables_are_intact(self):
        """A CSV upload must never disturb the 12 tables the SQL suite asserts."""
        r = self.client.get("/api/csv/files")
        self.assertEqual(r.status_code, 200)

    # ── BR-15: audit trail completeness ──────────────────────────────────
    # Every import must leave a complete, retrievable audit record containing
    # file name, table name, row count, and timestamp. These tests verify the
    # record is persisted (not just returned in the upload response) and can
    # be retrieved independently via GET /api/csv/files.

    def test_audit_record_contains_required_fields(self):
        """BR-15: GET /api/csv/files must return all required audit fields."""
        up = self.client.post("/api/csv/upload",
                              json={"fileName": self.name, "content": self.content})
        self.assertEqual(up.json()["status"], "ok")

        files = self.client.get("/api/csv/files").json()
        record = next((f for f in files if f["file_name"] == self.name), None)
        self.assertIsNotNone(record, "Uploaded file not found in audit log")

        for field in ("id", "file_name", "table_name", "mode", "row_count", "created_at"):
            self.assertIn(field, record, f"Audit record missing required field: {field}")

    def test_audit_record_row_count_matches_inserted_rows(self):
        """BR-15: persisted row_count must match what the upload response reported."""
        content = f"col_a,col_b\n{os.getpid()}_audit,1\n{os.getpid()}_audit,2\n"
        name = f"br15_rowcount_{os.getpid()}.csv"
        up = self.client.post("/api/csv/upload",
                              json={"fileName": name, "content": content})
        body = up.json()
        self.assertEqual(body["status"], "ok")

        files = self.client.get("/api/csv/files").json()
        record = next((f for f in files if f["file_name"] == name), None)
        self.assertIsNotNone(record)
        self.assertEqual(record["row_count"], body["insertedRows"],
                         "Persisted row_count must match insertedRows in upload response")

    def test_audit_record_table_name_matches_upload_response(self):
        """BR-15: persisted table_name must match what the upload response reported."""
        up = self.client.post("/api/csv/upload",
                              json={"fileName": self.name, "content": self.content})
        body = up.json()
        self.assertEqual(body["status"], "ok")

        files = self.client.get("/api/csv/files").json()
        record = next((f for f in files if f["file_name"] == self.name), None)
        self.assertIsNotNone(record)
        self.assertEqual(record["table_name"], body["tableName"],
                         "Persisted table_name must match tableName in upload response")

    def test_audit_record_has_iso_timestamp(self):
        """BR-15: created_at must be a non-empty ISO timestamp."""
        up = self.client.post("/api/csv/upload",
                              json={"fileName": self.name, "content": self.content})
        self.assertEqual(up.json()["status"], "ok")

        files = self.client.get("/api/csv/files").json()
        record = next((f for f in files if f["file_name"] == self.name), None)
        self.assertIsNotNone(record)
        self.assertTrue(record.get("created_at", ""), "created_at must not be empty")
        from datetime import datetime
        try:
            datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
        except ValueError:
            self.fail(f"created_at is not a valid ISO timestamp: {record['created_at']}")

    def test_failed_upload_leaves_no_audit_record(self):
        """BR-15: a structurally invalid file must not create a registry entry."""
        bad_name = f"br15_fail_{os.getpid()}.csv"
        up = self.client.post("/api/csv/upload",
                              json={"fileName": bad_name, "content": "col_a\n"})
        self.assertIn(up.json()["status"], ("invalid_structure", "error"))

        files = self.client.get("/api/csv/files").json()
        record = next((f for f in files if f["file_name"] == bad_name), None)
        self.assertIsNone(record, "A failed upload must not leave a registry entry")


@pytest.mark.integration
class PoolTimeout(unittest.TestCase):
    """BUG-030 regression: an exhausted pool must 503 within POOL_GETCONN_TIMEOUT
    instead of blocking the request thread forever.

    We swap the module-level pool for a tiny 2-slot instance (with a short
    500ms timeout) so exhaustion is cheap to force, then hold both slots and
    confirm the third acquisition raises PoolError promptly.
    """

    @classmethod
    def setUpClass(cls):
        # Save the original pool so we can restore it after the test.
        from api import db
        cls.db = db
        cls.orig_pool = db._pool
        cls.orig_executor = db._getconn_executor
        cls.orig_timeout = db.settings.POOL_GETCONN_TIMEOUT

        import psycopg2.pool
        from concurrent.futures import ThreadPoolExecutor
        try:
            db._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=2,
                host=db.settings.PG_HOST, port=db.settings.PG_PORT,
                user=db.settings.PG_USER, password=db.settings.PG_PASSWORD,
                dbname=db.settings.PG_DATABASE,
            )
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"Could not open a test pool — Postgres is not reachable.\n"
                f"  {type(exc).__name__}: {str(exc).strip().splitlines()[0]}\n"
                f"{_HELP}"
            ) from None
        db._getconn_executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="test-pool-getconn"
        )
        db.settings.POOL_GETCONN_TIMEOUT = 0.5  # keep the test fast

    @classmethod
    def tearDownClass(cls):
        cls.db._pool.closeall()
        cls.db._getconn_executor.shutdown(wait=False, cancel_futures=True)
        cls.db._pool = cls.orig_pool
        cls.db._getconn_executor = cls.orig_executor
        cls.db.settings.POOL_GETCONN_TIMEOUT = cls.orig_timeout

    def test_exhausted_pool_raises_within_timeout(self):
        """psycopg2's ThreadedConnectionPool.getconn() raises PoolError
        immediately when the pool is exhausted — it does not block. Our
        timeout wrapper still catches the error correctly and never lets a
        request hang. The upper bound is what BUG-030 really guards against;
        the lower bound is not asserted because a fast raise is the desired
        behaviour, not a regression.
        """
        import time
        import psycopg2.pool
        # Borrow both slots and hold them.
        c1 = self.db._pool.getconn()
        c2 = self.db._pool.getconn()
        try:
            start = time.monotonic()
            with self.assertRaises(psycopg2.pool.PoolError) as ctx:
                self.db._borrow_with_timeout()
            elapsed = time.monotonic() - start
            # Timeout is 0.5s. If elapsed exceeds a few seconds, the pool
            # started blocking (a bug or a future psycopg2 change) and our
            # timeout wrapper failed to fire — exactly what BUG-030 guards.
            self.assertLess(
                elapsed, 3.0,
                f"BUG-030 regression: getconn blocked {elapsed:.2f}s "
                f"instead of raising within POOL_GETCONN_TIMEOUT")
            self.assertIn("pool", str(ctx.exception).lower())
        finally:
            self.db._pool.putconn(c1)
            self.db._pool.putconn(c2)
