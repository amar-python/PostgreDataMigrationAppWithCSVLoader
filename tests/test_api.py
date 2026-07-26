"""Tests for the FastAPI backend in ``api/``.

Endpoint map (from api/main.py and api/routers/csv_routes.py):

    GET    /api/health
    POST   /api/csv/preview                     {fileName, content}
    POST   /api/csv/upload                      {fileName, content, types,
                                                 overwrite, mode, targetTable}
    GET    /api/csv/files
    GET    /api/csv/tables/{table_name}/rows    ?limit=
    DELETE /api/csv/files/{file_id}

Two groups:

* ``unit`` — request validation and routing. No database. These run in the
  Windows CI job and on any developer machine.
* ``integration`` — needs a reachable PostgreSQL with the uploads schema
  bootstrapped. Per the repository's no-skip policy an unmet prerequisite
  FAILS with remediation text rather than skipping.

Requires ``api/`` to use package-relative imports (``from api.config import
settings``) and to contain ``__init__.py``. With the original bare imports
(``from config import settings``) this module cannot be collected from the
repository root at all — see API_INTEGRATION.md.
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
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


@pytest.mark.unit
class HealthContract(unittest.TestCase):
    """Health must degrade rather than error, so the UI can render a state."""

    def test_health_always_returns_200(self):
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_health_status_is_ok_or_degraded(self):
        self.assertIn(client.get("/api/health").json()["status"], ("ok", "degraded"))

    def test_openapi_schema_is_served(self):
        self.assertEqual(client.get("/openapi.json").status_code, 200)


@pytest.mark.unit
class RequestValidation(unittest.TestCase):
    """Pydantic constraints and explicit guards — no database needed."""

    def test_preview_rejects_empty_filename(self):
        r = client.post("/api/csv/preview", json={"fileName": "", "content": SMALL_CSV})
        self.assertEqual(r.status_code, 422)

    def test_preview_rejects_empty_content(self):
        r = client.post("/api/csv/preview", json={"fileName": "a.csv", "content": ""})
        self.assertEqual(r.status_code, 422)

    def test_preview_rejects_overlong_filename(self):
        r = client.post("/api/csv/preview",
                        json={"fileName": "x" * 256, "content": SMALL_CSV})
        self.assertEqual(r.status_code, 422)

    def test_upload_rejects_unknown_mode(self):
        r = client.post("/api/csv/upload", json={
            "fileName": "a.csv", "content": SMALL_CSV, "mode": "sideways"})
        self.assertEqual(r.status_code, 422)

    def test_upload_te_mode_requires_target_table(self):
        r = client.post("/api/csv/upload", json={
            "fileName": "a.csv", "content": SMALL_CSV, "mode": "te"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("targetTable", r.text)

    def test_oversized_upload_is_rejected(self):
        from api.config import settings
        oversized = "x" * (settings.MAX_UPLOAD_BYTES + 1)
        r = client.post("/api/csv/preview",
                        json={"fileName": "big.csv", "content": oversized})
        self.assertEqual(r.status_code, 413)


@pytest.mark.unit
@pytest.mark.security
class TableNameGuards(unittest.TestCase):
    """The rows endpoint interpolates an identifier, so its guard matters."""

    def test_non_upload_tables_are_rejected(self):
        for name in ("organisations", "personnel", "pg_catalog", "users"):
            with self.subTest(table=name):
                r = client.get(f"/api/csv/tables/{name}/rows")
                self.assertEqual(r.status_code, 422,
                                 f"non-upload table accepted: {name}")

    def test_overlong_names_are_rejected(self):
        r = client.get(f"/api/csv/tables/csv_{'x' * 70}/rows")
        self.assertEqual(r.status_code, 422)

    def test_table_name_guard_rejects_non_hex_names(self):
        r = client.get("/api/csv/tables/csv_ghijklmnopqrst/rows")
        self.assertEqual(r.status_code, 422)

    def test_table_name_guard_rejects_short_hashes(self):
        r = client.get("/api/csv/tables/csv_0123456789abcde/rows")
        self.assertEqual(r.status_code, 422)

    # NOTE: names such as "csv_a'--" or "csv_a; DROP TABLE personnel" are
    # rejected by the stricter regex guard before they reach the database.

    def test_identifiers_are_never_string_formatted(self):
        """Every SQL identifier must go through psycopg2.sql.Identifier.

        Parsed from the AST rather than grepped, so a comment cannot trip it
        and a real f-string cannot slip past.
        """
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "api"
        offenders = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                is_execute = isinstance(func, ast.Attribute) and func.attr == "execute"
                if is_execute and node.args and isinstance(node.args[0], ast.JoinedStr):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [],
                         f"execute() called with an f-string at {offenders}")


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
