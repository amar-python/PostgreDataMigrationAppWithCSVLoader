"""Dynamic-mode tables are created from confirmed types, and the registry says whether they were (#195).

Decided 4 Nov: preview creates nothing; the table appears only when the upload is made, with the
types sent; the registry records ``user_confirmed`` or ``inferred_unconfirmed``; and a dynamic
table can never be the source of a T&E import.

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import hashlib
import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.db import Conn
from api.main import app

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")


def _column_types(table: str) -> dict[str, str]:
    with Conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s", (settings.UPLOADS_SCHEMA, table))
        return dict(cur.fetchall())


@pytest.mark.integration
class TypeConfirmationAndProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.name = f"prov_{self.tag}.csv"
        self.content = f"n,label\n1,{self.tag}\n"

    def _upload(self, **extra) -> dict:
        body = {"fileName": self.name, "content": self.content, **extra}
        return self.client.post("/api/csv/upload", json=body).json()

    def _registered(self) -> dict | None:
        return next((f for f in self.client.get("/api/csv/files").json() if f["file_name"] == self.name), None)

    def test_preview_proposes_types_but_creates_no_table_and_no_registry_row(self):
        preview = self.client.post("/api/csv/preview", json={"fileName": self.name, "content": self.content}).json()
        self.assertEqual(preview["status"], "ok", preview)
        self.assertEqual(len(preview["inferredTypes"]), 2)
        table = f"csv_{hashlib.sha256(self.content.encode()).hexdigest()[:16]}"
        self.assertEqual(_column_types(table), {}, "preview must not create the table")
        self.assertIsNone(self._registered())

    def test_confirming_creates_the_table_with_the_confirmed_types(self):
        res = self._upload(types=["int8", "text"], typesConfirmed=True)
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(res["typesProvenance"], "user_confirmed")
        self.assertEqual(_column_types(res["tableName"]).get("n"), "bigint")
        self.assertEqual(self._registered()["types_provenance"], "user_confirmed")

    def test_the_confirmed_types_can_differ_from_what_was_inferred(self):
        res = self._upload(types=["text", "text"], typesConfirmed=True)
        self.assertEqual(_column_types(res["tableName"]).get("n"), "text")

    def test_types_sent_without_confirmation_are_applied_but_not_marked_confirmed(self):
        res = self._upload(types=["int8", "text"])
        self.assertEqual(res["typesProvenance"], "inferred_unconfirmed")
        self.assertEqual(_column_types(res["tableName"]).get("n"), "bigint")
        self.assertEqual(self._registered()["types_provenance"], "inferred_unconfirmed")

    def test_no_types_at_all_is_unconfirmed(self):
        res = self._upload()
        self.assertEqual((res["status"], res["typesProvenance"]), ("ok", "inferred_unconfirmed"))
        self.assertEqual(self._registered()["types_provenance"], "inferred_unconfirmed")

    def test_confirmation_without_the_confirmed_types_is_rejected_and_loads_nothing(self):
        resp = self.client.post("/api/csv/upload", json={
            "fileName": self.name, "content": self.content, "typesConfirmed": True})
        self.assertEqual(resp.status_code, 422)
        self.assertIsNone(self._registered())

    def test_te_mode_rejects_types_confirmed(self):
        resp = self.client.post("/api/csv/upload", json={
            "fileName": self.name, "content": self.content, "mode": "te",
            "targetTable": "organisations", "typesConfirmed": True})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("dynamic", resp.json()["detail"])

    def test_te_import_rejects_a_dynamic_table_as_its_target(self):
        dynamic = self._upload(types=["int8", "text"], typesConfirmed=True)
        self.assertEqual(dynamic["status"], "ok", dynamic)
        res = self.client.post("/api/csv/upload", json={
            "fileName": f"te_{self.name}", "content": self.content, "mode": "te",
            "targetTable": dynamic["tableName"]}).json()
        self.assertEqual(res["status"], "error", res)
        self.assertIn(dynamic["tableName"], res["message"].lower())
        self.assertFalse([f for f in self.client.get("/api/csv/files").json() if f["file_name"] == f"te_{self.name}"])
