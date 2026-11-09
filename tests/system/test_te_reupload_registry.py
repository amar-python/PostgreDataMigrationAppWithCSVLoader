"""#215: a T&E re-upload that fails every row must leave the earlier load alone.

The registry (``csv_files``, what "Migrated files" shows) is the ledger a
reconciliation reads. Before the fix, re-uploading a file whose rows all failed
still deleted the earlier load's registry record and replaced it with "0 loaded",
while the earlier load's rows stayed in the table.

Needs a live PostgreSQL with the dev schema deployed (see tests/test_api_integration.py).
"""
from __future__ import annotations

import os
import unittest

import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.db import Conn
from api.main import app

HEADER = "name,org_type,country"


@pytest.mark.integration
class TeReuploadRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True  # tearDown deletes its tagged files
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API (is PostgreSQL up, is PGPASSWORD set?): {exc}") from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        settings.allow_destructive = cls._orig_allow_destructive

    def setUp(self):
        self.tag = f"reup215_{os.getpid()}_{self._testMethodName}"
        self.file_name = f"{self.tag}.csv"

    def tearDown(self):
        for f in self.client.get("/api/csv/files").json():
            if self.tag in f["file_name"]:
                self.client.delete(f"/api/csv/files/{f['id']}")
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {settings.TE_SCHEMA}.organisations WHERE name LIKE %s", (self.tag + "%",))
            conn.commit()

    # -- helpers -------------------------------------------------------------

    def _upload_te(self, content: str):
        return self.client.post("/api/csv/upload", json={
            "fileName": self.file_name, "content": content, "mode": "te", "targetTable": "organisations",
        }).json()

    def _registry(self) -> list[dict]:
        return [f for f in self.client.get("/api/csv/files").json() if f["file_name"] == self.file_name]

    def _loaded_orgs(self) -> int:
        with Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {settings.TE_SCHEMA}.organisations WHERE name LIKE %s",
                            (self.tag + "%",))
                return cur.fetchone()[0]

    # -- the bug -------------------------------------------------------------

    def test_all_failed_reupload_keeps_the_earlier_registry_record(self):
        """A T&E re-upload that fails every row leaves the earlier load's registry record alone."""
        # Two valid rows and one that the check constraint rejects.
        csv = f"{HEADER}\n{self.tag}_a,government,AU\n{self.tag}_b,prime,AU\n{self.tag}_bad,not_a_type,AU\n"
        first = self._upload_te(csv)
        self.assertEqual((first["status"], first["insertedRows"], first["failedRows"]), ("ok", 2, 1), first)
        before = self._registry()
        self.assertEqual([(r["row_count"], r["failed_rows"]) for r in before], [(2, 1)])

        # The same file again: both valid rows now collide on the unique name, so every row fails.
        second = self._upload_te(csv)
        self.assertEqual(second["status"], "error", second)
        self.assertEqual(second["insertedRows"], 0, second)

        after = self._registry()
        self.assertEqual([(r["id"], r["row_count"], r["failed_rows"]) for r in after],
                         [(before[0]["id"], 2, 1)],
                         "the earlier load's registry record must survive an all-failed re-upload")
        self.assertEqual(self._loaded_orgs(), 2, "registry and table must still agree")

    # -- guard against over-correcting ---------------------------------------

    def test_reupload_that_inserts_rows_still_replaces_the_registry_record(self):
        """A T&E re-upload that loads at least one row still replaces the registry record."""
        first = self._upload_te(f"{HEADER}\n{self.tag}_a,government,AU\n")
        self.assertEqual(first["status"], "ok", first)
        old_id = self._registry()[0]["id"]

        second = self._upload_te(f"{HEADER}\n{self.tag}_b,prime,AU\n{self.tag}_bad,not_a_type,AU\n")
        self.assertEqual((second["status"], second["insertedRows"], second["failedRows"]), ("ok", 1, 1), second)

        reg = self._registry()
        self.assertEqual(len(reg), 1, "a re-upload replaces the record, it does not add a second")
        self.assertNotEqual(reg[0]["id"], old_id)
        self.assertEqual((reg[0]["row_count"], reg[0]["failed_rows"]), (1, 1))

    # -- #170's original scenario, in the same place -------------------------

    def test_all_failed_te_upload_keeps_a_prior_dynamic_table_of_the_same_name(self):
        """An all-failed T&E upload does not drop a dynamic table registered under the same filename (#170)."""
        dyn = self.client.post("/api/csv/upload", json={
            "fileName": self.file_name, "content": "col_a,col_b\n1,2\n", "mode": "dynamic",
        }).json()
        self.assertEqual(dyn["status"], "ok", dyn)
        table = dyn["tableName"]

        te = self._upload_te(f"{HEADER}\n{self.tag}_bad,not_a_type,AU\n")
        self.assertEqual(te["status"], "error", te)

        reg = self._registry()
        self.assertEqual([(r["mode"], r["table_name"]) for r in reg], [("dynamic", table)])
        self.assertEqual(self.client.get(f"/api/csv/tables/{table}/rows").status_code, 200,
                         "the prior dynamic table must not have been dropped")
