"""Integration tests for mode=te upload — issue #16.

These are the highest-risk untested paths in the API: upload_te() writes
directly into the 12 fixed T&E tables that the 142 SQL assertions validate.
A defect here could silently corrupt the schema the entire test suite depends on.

All tests target the ``organisations`` table because it has no foreign-key
dependencies and minimal required columns (name, org_type, country), making
it safe to insert and clean up without side-effects on other tables.

Per the repository's no-skip policy, an unreachable database FAILS with
remediation text rather than skipping.

Run::

    pytest tests/test_te_loader_integration.py

Requires a provisioned dev environment:
    bash scripts/provision_full_test_env.sh
"""
from __future__ import annotations

import os
import unittest

import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app

_HELP = (
    "Start PostgreSQL, ensure PGPASSWORD is set, and provision the dev "
    "environment:\n"
    "    bash scripts/provision_full_test_env.sh\n"
    "    PowerShell: $env:PGPASSWORD = '<password>'"
)

# organisations columns that upload_te can receive (auto-generated cols excluded)
ORG_HEADER = "name,org_type,country"
ORG_ROW_TPL = "TE_TEST_{pid}_{n},government,AU"

TARGET = "organisations"


@pytest.mark.integration
class TeUploadOrganisations(unittest.TestCase):
    """End-to-end mode=te upload into the organisations T&E table."""

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
        r = cls.client.get("/api/health")
        if r.json().get("status") not in ("ok", "degraded"):
            cls.ctx.__exit__(None, None, None)
            raise AssertionError(f"API reports database unreachable.\n{_HELP}")

        # Store inserted names for teardown cleanup
        cls._inserted: list[str] = []

    @classmethod
    def tearDownClass(cls):
        # Best-effort cleanup — remove rows inserted by these tests
        # so the suite does not pollute the dev seed data
        if cls._inserted:
            try:
                from api.db import Conn
                from psycopg2 import sql
                from api.config import settings
                with Conn() as conn:
                    with conn.cursor() as cur:
                        for name in cls._inserted:
                            cur.execute(
                                sql.SQL(
                                    "DELETE FROM {}.organisations WHERE name = %s"
                                ).format(sql.Identifier(settings.TE_SCHEMA)),
                                (name,),
                            )
                    conn.commit()
            except Exception:  # noqa: BLE001
                pass  # cleanup is best-effort; don't fail teardown
        cls.ctx.__exit__(None, None, None)

    def _make_csv(self, n_rows: int = 1) -> tuple[str, list[str]]:
        """Return (csv_content, list_of_inserted_names)."""
        names = [f"TE_TEST_{os.getpid()}_{i}_{self._testMethodName[:20]}"
                 for i in range(n_rows)]
        rows = "\n".join(f"{n},government,AU" for n in names)
        content = f"{ORG_HEADER}\n{rows}\n"
        return content, names

    def _upload_te(self, content: str, target: str = TARGET,
                   file_name: str | None = None) -> dict:
        name = file_name or f"te_{os.getpid()}_{self._testMethodName[:30]}.csv"
        r = self.client.post(
            "/api/csv/upload",
            json={"fileName": name, "content": content,
                  "mode": "te", "targetTable": target},
        )
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r.json()

    # ── happy path ────────────────────────────────────────────────────────

    def test_valid_te_upload_returns_ok(self):
        """A well-formed T&E CSV must return status=ok."""
        content, names = self._make_csv(1)
        self.__class__._inserted.extend(names)
        body = self._upload_te(content)
        self.assertEqual(body["status"], "ok", body)

    def test_inserted_rows_count_matches_data_rows(self):
        """insertedRows must equal the number of data rows supplied."""
        content, names = self._make_csv(3)
        self.__class__._inserted.extend(names)
        body = self._upload_te(content)
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(body["totalRows"], 3)
        self.assertEqual(body["insertedRows"], 3)

    def test_table_name_in_response_is_schema_qualified(self):
        """tableName must be schema-qualified (e.g. te_dev.organisations)."""
        content, names = self._make_csv(1)
        self.__class__._inserted.extend(names)
        body = self._upload_te(content)
        self.assertEqual(body["status"], "ok", body)
        self.assertIn(".", body.get("tableName", ""),
                      "tableName must be schema-qualified")
        self.assertTrue(body["tableName"].endswith(f".{TARGET}"),
                        f"tableName should end with .{TARGET}, got {body['tableName']}")

    def test_rows_are_queryable_after_upload(self):
        """Inserted rows must appear in the T&E table row count."""
        content, names = self._make_csv(1)
        self.__class__._inserted.extend(names)
        body = self._upload_te(content)
        self.assertEqual(body["status"], "ok", body)
        te_r = self.client.get("/api/te/tables")
        self.assertEqual(te_r.status_code, 200, te_r.text[:200])
        tables = {row["table"]: row for row in te_r.json()}
        self.assertIn(TARGET, tables,
                      f"'{TARGET}' not in /api/te/tables response")
        self.assertGreater(tables[TARGET]["rowCount"], 0,
                           f"T&E table '{TARGET}' has 0 rows after upload")

    def test_core_te_tables_undisturbed_after_upload(self):
        """A T&E upload must not drop or alter the other 11 core tables."""
        content, names = self._make_csv(1)
        self.__class__._inserted.extend(names)
        self._upload_te(content)

        te_r = self.client.get("/api/te/tables")
        self.assertEqual(te_r.status_code, 200, te_r.text[:200])
        tables = {t["table"]: t for t in te_r.json()}
        for tbl in ["requirements", "test_cases", "defect_reports"]:
            self.assertIn(tbl, tables, f"Core table '{tbl}' missing after T&E upload")
            self.assertTrue(tables[tbl]["exists"],
                            f"Core table '{tbl}' no longer exists after T&E upload")

    # ── cleanup on re-upload ──────────────────────────────────────────────

    def test_reupload_cleans_prior_registry_entry(self):
        """Re-uploading the same file name must not duplicate registry entries."""
        content, names = self._make_csv(1)
        self.__class__._inserted.extend(names)
        fname = f"te_reupload_{os.getpid()}.csv"

        first  = self._upload_te(content, file_name=fname)
        second = self._upload_te(content, file_name=fname)

        self.assertEqual(first["status"],  "ok", first)
        self.assertEqual(second["status"], "ok", second)

        files = self.client.get("/api/csv/files").json()
        matches = [f for f in files if f["file_name"] == fname]
        self.assertLessEqual(
            len(matches), 1,
            f"Re-upload left {len(matches)} registry entries for the same file"
        )

    # ── guard rails ───────────────────────────────────────────────────────

    def test_invalid_target_table_is_rejected(self):
        """A targetTable not in TE_TABLES must return status=error."""
        content, _ = self._make_csv(1)
        body = self._upload_te(content, target="not_a_te_table")
        self.assertEqual(body["status"], "error", body)
        self.assertIn("not_a_te_table", body.get("message", "").lower())

    def test_empty_file_is_rejected(self):
        """Empty CSV is rejected — 422 from Pydantic min_length or status=error."""
        r = self.client.post("/api/csv/upload", json={
            "fileName": f"te_{os.getpid()}_empty.csv",
            "content": "", "mode": "te", "targetTable": TARGET})
        if r.status_code == 422:
            pass  # Pydantic min_length=1 guard — valid rejection
        else:
            self.assertEqual(r.status_code, 200, r.text[:300])
            self.assertIn(r.json()["status"], ("error", "invalid_structure"), r.json())

    def test_header_only_file_is_rejected(self):
        """A header-only CSV (no data rows) must return status=invalid_structure."""
        body = self._upload_te(f"{ORG_HEADER}\n")
        self.assertIn(body["status"], ("error", "invalid_structure"), body)

    def test_unknown_columns_are_rejected(self):
        """Columns not in the target table must return status=error."""
        content = "fake_col,another_fake\nval1,val2\n"
        body = self._upload_te(content)
        self.assertEqual(body["status"], "error", body)

    def test_missing_target_table_param_is_rejected(self):
        """mode=te with no targetTable must return 422 from the API layer."""
        r = self.client.post(
            "/api/csv/upload",
            json={"fileName": f"te_{os.getpid()}.csv",
                  "content": f"{ORG_HEADER}\n{ORG_ROW_TPL.format(pid=os.getpid(), n=0)}\n",
                  "mode": "te"},
        )
        self.assertEqual(r.status_code, 422, r.text[:200])


@pytest.mark.integration
class DynamicOverwriteOfTeOriginFile(unittest.TestCase):
    """Issue #27 — a dynamic-mode overwrite of a TE-origin registry entry must
    not attempt to DROP the shared T&E table (table_name is "schema.table" for
    TE-mode rows, not a bare csv_<hash> identifier this schema owns)."""

    @classmethod
    def setUpClass(cls):
        # DELETE cleanup below needs this — see BUG-040 / test_api_coverage.py's
        # _IntegrationBase for the same pattern.
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"Could not start the API — database connection failed.\n"
                f"  {type(exc).__name__}: {str(exc).strip().splitlines()[0]}\n"
                f"{_HELP}"
            ) from None
        r = cls.client.get("/api/health")
        if r.json().get("status") not in ("ok", "degraded"):
            cls.ctx.__exit__(None, None, None)
            raise AssertionError(f"API reports database unreachable.\n{_HELP}")
        cls._inserted: list[str] = []

    @classmethod
    def tearDownClass(cls):
        if cls._inserted:
            try:
                from api.db import Conn
                from psycopg2 import sql
                with Conn() as conn:
                    with conn.cursor() as cur:
                        for name in cls._inserted:
                            cur.execute(
                                sql.SQL(
                                    "DELETE FROM {}.organisations WHERE name = %s"
                                ).format(sql.Identifier(settings.TE_SCHEMA)),
                                (name,),
                            )
                    conn.commit()
            except Exception:  # noqa: BLE001
                pass
        cls.ctx.__exit__(None, None, None)
        settings.allow_destructive = cls._orig_allow_destructive

    def test_dynamic_overwrite_of_te_origin_entry_succeeds(self):
        """A dynamic-mode overwrite of a filename previously registered in
        TE mode must succeed (not crash, not silently no-op) and the registry
        must reflect the new dynamic-mode table, not a stale TE reference."""
        pid = os.getpid()
        org_name = f"TE_TEST_{pid}_overwrite_origin"
        self.__class__._inserted.append(org_name)
        fname = f"cross_mode_{pid}.csv"

        te_body = self.client.post(
            "/api/csv/upload",
            json={
                "fileName": fname,
                "content": f"{ORG_HEADER}\n{org_name},government,AU\n",
                "mode": "te",
                "targetTable": TARGET,
            },
        ).json()
        self.assertEqual(te_body["status"], "ok", te_body)

        dynamic_body = self.client.post(
            "/api/csv/upload",
            json={
                "fileName": fname,
                "content": "col_a\nsome_value\n",
                "overwrite": True,
            },
        ).json()
        self.assertEqual(
            dynamic_body["status"], "ok",
            f"dynamic-mode overwrite of a TE-origin file must succeed: {dynamic_body}",
        )
        self.assertTrue(dynamic_body["tableName"].startswith("csv_"), dynamic_body)

        files = self.client.get("/api/csv/files").json()
        matches = [f for f in files if f["file_name"] == fname]
        self.assertEqual(
            len(matches), 1,
            f"expected exactly one registry entry for {fname!r}, found {matches}",
        )
        self.assertEqual(
            matches[0]["mode"], "dynamic",
            "registry entry must reflect the new dynamic-mode table, not the stale TE entry",
        )

        # Clean up the dynamic table this test created.
        self.client.delete(f"/api/csv/files/{matches[0]['id']}")
