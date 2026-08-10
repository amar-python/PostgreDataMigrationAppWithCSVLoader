"""Additional API coverage — fills gaps not covered by test_api.py.

Gaps addressed:
  1. GET  /api/te/tables            — untested
  2. POST /api/csv/upload mode=te   — no API-level test
  3. POST /api/csv/preview          — teTableMatch field never asserted
  4. DELETE /api/csv/files/{id}     — only used in tearDown, never tested
  5. POST /api/csv/upload overwrite — overwrite=true flag untested
  6. CORS middleware                — headers never checked

Convention: same unittest.TestCase + pytest markers as test_api.py.
"""
from __future__ import annotations

import os
import unittest

import pytest
from fastapi.testclient import TestClient

from api.config import TE_TABLES
from api.main import app

client = TestClient(app)

_HELP = ("Start PostgreSQL and ensure api/ can reach it. Most often this means "
         "PGPASSWORD is not set in this shell:\n"
         "    PowerShell:  $env:PGPASSWORD = '<password>'\n"
         "    bash:        export PGPASSWORD='<password>'\n"
         "Defaults come from api/config.py; see scripts/start-api.ps1.")


class _IntegrationBase(unittest.TestCase):
    """Shared setUp/tearDown for integration classes that need a live DB."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
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
        self.tag = f"coverage_{os.getpid()}_{self._testMethodName}"

    def tearDown(self):
        for f in self.client.get("/api/csv/files").json():
            if self.tag in f["file_name"]:
                self.client.delete(f"/api/csv/files/{f['id']}")

    # -- helpers -------------------------------------------------------------

    def _upload_dynamic(self, content=None, overwrite=False):
        name = f"{self.tag}.csv"
        if content is None:
            content = f"col_a,col_b\n{os.getpid()},{self._testMethodName}\n"
        return self.client.post("/api/csv/upload", json={
            "fileName": name, "content": content, "overwrite": overwrite,
        })

    def _upload_te(self, content, target_table="organisations"):
        name = f"{self.tag}.csv"
        return self.client.post("/api/csv/upload", json={
            "fileName": name, "content": content,
            "mode": "te", "targetTable": target_table,
        })


# ---------------------------------------------------------------------------
# Gap 1a: TE_TABLES whitelist (unit — no DB)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TeTablesConfig(unittest.TestCase):
    """The TE_TABLES whitelist in api/config.py must stay consistent."""

    def test_te_tables_has_twelve_entries(self):
        self.assertEqual(len(TE_TABLES), 12)

    def test_te_tables_are_all_strings(self):
        for t in TE_TABLES:
            self.assertIsInstance(t, str, f"non-string entry: {t!r}")

    def test_te_tables_has_no_duplicates(self):
        self.assertEqual(len(set(TE_TABLES)), len(TE_TABLES))


# ---------------------------------------------------------------------------
# Gap 6: CORS middleware (unit — no DB)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class CorsHeaders(unittest.TestCase):
    """CORS middleware must be active with the configured origins."""

    def test_preflight_returns_cors_headers(self):
        r = client.options("/api/health", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        })
        self.assertIn("access-control-allow-origin", r.headers)

    def test_cors_allows_configured_origin(self):
        r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_cors_rejects_unconfigured_origin(self):
        r = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
        self.assertNotEqual(
            r.headers.get("access-control-allow-origin"), "http://evil.example.com")


# ---------------------------------------------------------------------------
# Gap 1b: GET /api/te/tables (integration — needs deployed T&E schema)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TeTablesEndpoint(_IntegrationBase):
    """GET /api/te/tables must return the 12 fixed T&E tables."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.response = cls.client.get("/api/te/tables")
        cls.data = cls.response.json()

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_returns_list_of_twelve(self):
        self.assertIsInstance(self.data, list)
        self.assertEqual(len(self.data), 12)

    def test_each_entry_has_required_keys(self):
        for entry in self.data:
            for key in ("table", "exists", "rowCount"):
                self.assertIn(key, entry, f"missing key '{key}' in {entry}")

    def test_table_names_match_whitelist(self):
        names = [e["table"] for e in self.data]
        self.assertEqual(names, TE_TABLES)

    def test_all_tables_exist_after_deploy(self):
        for entry in self.data:
            self.assertTrue(
                entry["exists"],
                f"T&E table '{entry['table']}' does not exist — run deploy_all.sh dev")

    def test_row_count_is_non_negative_integer(self):
        for entry in self.data:
            self.assertIsInstance(entry["rowCount"], int)
            self.assertGreaterEqual(entry["rowCount"], 0)


# ---------------------------------------------------------------------------
# Gap 3: preview teTableMatch (integration — match_te_table queries the DB)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class PreviewTeTableMatch(_IntegrationBase):
    """POST /api/csv/preview must populate teTableMatch when columns fit."""

    def test_preview_returns_te_match_for_matching_columns(self):
        csv = f"name,org_type,country\n{self.tag},government,AU\n"
        r = self.client.post("/api/csv/preview",
                             json={"fileName": f"{self.tag}.csv", "content": csv})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "ok", body)
        self.assertEqual(body.get("teTableMatch"), "organisations")

    def test_preview_returns_null_for_non_matching_columns(self):
        csv = "col_x,col_y\n1,2\n"
        r = self.client.post("/api/csv/preview",
                             json={"fileName": f"{self.tag}.csv", "content": csv})
        body = r.json()
        self.assertEqual(body.get("status"), "ok", body)
        self.assertIsNone(body.get("teTableMatch"))

    def test_te_table_match_key_present_in_ok_response(self):
        csv = "a,b\n1,2\n"
        r = self.client.post("/api/csv/preview",
                             json={"fileName": f"{self.tag}.csv", "content": csv})
        body = r.json()
        if body.get("status") == "ok":
            self.assertIn("teTableMatch", body)


# ---------------------------------------------------------------------------
# Gap 4: DELETE /api/csv/files/{file_id} (integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class DeleteEndpoint(_IntegrationBase):
    """DELETE must return the right shape, 404 on missing, and handle modes."""

    def test_delete_returns_correct_shape(self):
        up = self._upload_dynamic()
        file_id = int(up.json()["fileId"])
        r = self.client.delete(f"/api/csv/files/{file_id}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["deleted"], file_id)

    def test_delete_nonexistent_id_returns_404(self):
        r = self.client.delete("/api/csv/files/999999999")
        self.assertEqual(r.status_code, 404)

    def test_delete_dynamic_drops_backing_table(self):
        up = self._upload_dynamic()
        body = up.json()
        self.assertEqual(body["status"], "ok", body)
        table = body["tableName"]
        file_id = int(body["fileId"])

        self.client.delete(f"/api/csv/files/{file_id}")

        rows = self.client.get(f"/api/csv/tables/{table}/rows")
        self.assertEqual(rows.status_code, 404,
                         "table should be unregistered after delete")

    def test_delete_te_only_removes_registry(self):
        csv = f"name,org_type,country\n{self.tag}_del,government,AU\n"
        up = self._upload_te(csv)
        body = up.json()
        self.assertEqual(body["status"], "ok", body)
        file_id = int(body["fileId"])

        self.client.delete(f"/api/csv/files/{file_id}")

        file_names = [f["file_name"] for f in self.client.get("/api/csv/files").json()]
        self.assertNotIn(f"{self.tag}.csv", file_names,
                         "registry entry should be gone")

        te = self.client.get("/api/te/tables").json()
        org = next(t for t in te if t["table"] == "organisations")
        self.assertTrue(org["exists"], "T&E table itself must still exist")

    def test_deleted_file_no_longer_listed(self):
        up = self._upload_dynamic()
        file_id = int(up.json()["fileId"])
        self.client.delete(f"/api/csv/files/{file_id}")

        ids = [f["id"] for f in self.client.get("/api/csv/files").json()]
        self.assertNotIn(str(file_id), ids)


# ---------------------------------------------------------------------------
# Gap 5: overwrite=true (integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class OverwriteUpload(_IntegrationBase):
    """The overwrite flag must replace, not refuse, a duplicate filename."""

    def test_overwrite_replaces_existing_file(self):
        content_a = f"col_a,col_b\n{self.tag},first\n"
        content_b = f"col_a,col_b\n{self.tag},second\n"
        self._upload_dynamic(content=content_a)
        r = self._upload_dynamic(content=content_b, overwrite=True)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertTrue(body.get("overwritten"))

    def test_overwrite_false_refuses_duplicate(self):
        content = f"col_a,col_b\n{self.tag},val\n"
        self._upload_dynamic(content=content)
        r = self._upload_dynamic(content=content, overwrite=False)
        self.assertEqual(r.json()["status"], "duplicate_file")

    def test_overwrite_creates_new_table(self):
        content_a = f"col_a,col_b\n{self.tag},first\n"
        content_b = f"col_a,col_b\n{self.tag},second\n"
        r1 = self._upload_dynamic(content=content_a)
        table_a = r1.json()["tableName"]
        r2 = self._upload_dynamic(content=content_b, overwrite=True)
        table_b = r2.json()["tableName"]
        self.assertNotEqual(table_a, table_b,
                            "different content should produce a different table hash")

    def test_overwrite_response_has_fields(self):
        content_a = f"col_a,col_b\n{self.tag},first\n"
        content_b = f"col_a,col_b\n{self.tag},second\n"
        self._upload_dynamic(content=content_a)
        r = self._upload_dynamic(content=content_b, overwrite=True)
        body = r.json()
        self.assertIn("overwritten", body)
        self.assertIn("replacedFileName", body)
        self.assertIsInstance(body["overwritten"], bool)
        self.assertIsInstance(body["replacedFileName"], str)


# ---------------------------------------------------------------------------
# Gap 2: T&E mode upload (integration)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TeUploadPipeline(_IntegrationBase):
    """POST /api/csv/upload with mode=te against a deployed T&E schema."""

    def _org_csv(self, name_val, org_type="government", country="AU"):
        return f"name,org_type,country\n{name_val},{org_type},{country}\n"

    def test_successful_upload_to_organisations(self):
        csv = self._org_csv(f"{self.tag}_ok")
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertGreaterEqual(
            body["insertedRows"], 1,
            f"failedRows={body.get('failedRows')}, "
            f"rowErrors={body.get('rowErrors')}")
        self.assertIn("organisations", body["tableName"])

    def test_response_shape_matches_contract(self):
        csv = self._org_csv(f"{self.tag}_shape")
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        for key in ("totalRows", "insertedRows",
                    "duplicateRowsSkipped", "failedRows",
                    "columns", "rowErrors"):
            self.assertIn(key, body, f"missing key '{key}'")
        self.assertEqual(body["duplicateRowsSkipped"], 0)
        self.assertEqual(body["types"], [])

    def test_column_mismatch_returns_error(self):
        csv = "bogus_col,fake_col\nval1,val2\n"
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "error", body)
        self.assertIn("bogus_col", body.get("message", ""))

    def test_row_level_error_reported(self):
        csv = self._org_csv(f"{self.tag}_bad", org_type="X" * 100)
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertGreaterEqual(body["failedRows"], 1)
        self.assertTrue(body["rowErrors"])
        self.assertIn("rowNumber", body["rowErrors"][0])

    def test_te_upload_registers_in_csv_files(self):
        csv = self._org_csv(f"{self.tag}_reg")
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)

        files = self.client.get("/api/csv/files").json()
        match = [f for f in files if f["file_name"] == f"{self.tag}.csv"]
        self.assertTrue(match, "T&E upload should appear in csv_files list")
        self.assertEqual(match[0]["mode"], "te")


    def test_enum_constraint_violation_reported_per_row(self):
        """An invalid enum value must produce a per-row error, not a 500."""
        csv = self._org_csv(f"{self.tag}_enum", org_type="INVALID_ENUM")
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertGreaterEqual(body["failedRows"], 1,
            "Invalid enum value should fail at row level, not crash the endpoint")
        self.assertIn("rowNumber", body["rowErrors"][0])

    def test_null_in_not_null_column_reported_per_row(self):
        """An empty required field sent as NULL must fail per-row, not crash."""
        csv = "name,org_type,country\n,government,AU\n"
        r = self._upload_te(csv)
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertGreaterEqual(body["failedRows"], 1,
            "NULL in a NOT NULL column should fail at row level")
        self.assertIn("rowNumber", body["rowErrors"][0])

    def test_unknown_target_table_returns_error(self):
        """Uploading to a table not in TE_TABLES must return status=error."""
        r = self.client.post("/api/csv/upload", json={
            "fileName": f"{self.tag}.csv",
            "content": "col_a\nval\n",
            "mode": "te",
            "targetTable": "non_existent_table",
        })
        body = r.json()
        self.assertEqual(body["status"], "error", body)
        self.assertIn("non_existent_table", body.get("message", ""))

    def test_te_reupload_same_file_replaces_registry(self):
        """Re-uploading the same CSV in T&E mode replaces the registry entry."""
        csv = self._org_csv(f"{self.tag}_reup")
        r1 = self._upload_te(csv)
        self.assertEqual(r1.json()["status"], "ok", r1.json())
        r2 = self._upload_te(csv)
        self.assertEqual(r2.json()["status"], "ok", r2.json())
        files = self.client.get("/api/csv/files").json()
        matches = [f for f in files if f["file_name"] == f"{self.tag}.csv"]
        self.assertEqual(len(matches), 1,
            "Re-upload should replace the registry entry, not create a duplicate")

    def test_te_client_side_type_validation_reports_column_and_value(self):
        """BUG-028: a bad value on a client-validatable column (BOOLEAN here)
        must be rejected by the pre-insert cast_value() pass, not by the DB.

        The client-side path structures row_errors with column + value + reason
        fields; the server-side SAVEPOINT fallback only produces rowNumber +
        reason. Asserting the extra fields proves the fast path took the row.
        """
        csv = (
            "name,org_type,country,is_active\n"
            f"{self.tag}_ok,government,AU,true\n"
            f"{self.tag}_bad,government,AU,NOT_A_BOOL\n"
        )
        r = self._upload_te(csv, target_table="organisations")
        body = r.json()
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(body["failedRows"], 1)
        self.assertEqual(body["insertedRows"], 1,
            "The valid row should still land while the bad row is skipped.")
        self.assertTrue(body["rowErrors"], "rowErrors must be populated")
        err = body["rowErrors"][0]
        # These two fields are the fingerprint of the client-side path.
        self.assertEqual(err.get("column"), "is_active",
            f"Client-side validator must set column; got {err!r}")
        self.assertEqual(err.get("value"), "NOT_A_BOOL",
            f"Client-side validator must set value; got {err!r}")
        self.assertIn("true/false", err["reason"].lower())

    def test_te_upload_rejects_over_row_cap(self):
        """BUG-027 for T&E mode: a CSV with more than settings.MAX_ROWS data
        rows must be rejected up-front with status=error and never reach the DB.
        """
        from api import config as cfg
        original = cfg.settings.MAX_ROWS
        cfg.settings.MAX_ROWS = 2  # keep the test small
        try:
            csv = "name,org_type,country\n" + "".join(
                f"{self.tag}_row{i},government,AU\n" for i in range(5)
            )
            r = self._upload_te(csv, target_table="organisations")
            body = r.json()
            self.assertEqual(body["status"], "error", body)
            # Message reads "CSV has N data rows, but the API is configured
            # to accept at most M." — assert the identifying phrase.
            self.assertIn("at most", body["message"].lower())
            # Sanity check: no rows leaked to the DB.
            files = self.client.get("/api/csv/files").json()
            matches = [f for f in files if f["file_name"] == f"{self.tag}.csv"]
            self.assertFalse(matches,
                "An over-cap upload must not create a registry entry.")
        finally:
            cfg.settings.MAX_ROWS = original


@pytest.mark.unit
class DeleteGateUnit(unittest.TestCase):
    """DELETE endpoint must honour API_ALLOW_DESTRUCTIVE=false (unit, no DB)."""

    def test_delete_blocked_returns_403(self):
        from api import config as cfg
        original = cfg.settings.allow_destructive
        cfg.settings.allow_destructive = False
        try:
            r = client.delete("/api/csv/files/1")
            self.assertEqual(r.status_code, 403,
                "DELETE must return 403 when API_ALLOW_DESTRUCTIVE=false")
        finally:
            cfg.settings.allow_destructive = original
