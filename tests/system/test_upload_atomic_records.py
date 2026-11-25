"""#288 (OIT-003, BR-45, BR-52): a direct upload's load, registry row, original and audit row commit together.

Before the fix ``POST /api/csv/upload`` committed the load first, then stored the original
(``record_upload``) and the audit row (``record_audit``) in separate transactions that swallowed
their own errors. A failure in either left a committed load with no ``uploads`` row or no audit
row, and the request still answered "ok".

Faults are injected into the writer of each record. With the fix nothing from the load commits
(no registry row, no new dataset table, no T&E rows, no imported ``uploads`` row, no ``upload``
audit row) and the response is not "ok". When the injected fault is in the original's writer, the
best-effort record of the failed attempt fails too, which exercises that path's error branch.

Integration: needs a live PostgreSQL with the dev schema deployed, as in CI.
"""

from __future__ import annotations

import contextlib
import unittest
import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app
from api.routers import csv_routes
from api.services import audit, originals


def _boom(*_args, **_kwargs):
    raise RuntimeError("injected fault (#288)")


@contextlib.contextmanager
def _fail(name: str):
    """Make ``name`` raise wherever the upload path can reach it: its home module and the route's import."""
    home = originals if name == "store_upload" else audit
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(home, name, _boom))
        if hasattr(csv_routes, name):
            stack.enter_context(mock.patch.object(csv_routes, name, _boom))
        yield


@pytest.mark.integration
class DirectUploadRecordsAreAtomic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app, raise_server_exceptions=False)
        cls.client = cls.ctx.__enter__()
        cls.schema = settings.UPLOADS_SCHEMA
        cls.te_schema = settings.TE_SCHEMA

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = uuid.uuid4().hex[:10]
        self.name = f"atomic_{self.tag}.csv"

    # -- helpers ---------------------------------------------------------------------------------

    def _q(self, query: str, *params):
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL(query).format(s=sql.Identifier(self.schema), t=sql.Identifier(self.te_schema)), params)
            return cur.fetchall()

    def _registry(self):
        return self._q("SELECT id, table_name FROM {s}.csv_files WHERE file_name = %s", self.name)

    def _uploads(self):
        return self._q("SELECT status, csv_file_id FROM {s}.uploads WHERE file_name = %s ORDER BY id", self.name)

    def _upload_audit(self):
        return self._q(
            "SELECT file_id, table_name FROM {s}.audit_log WHERE action = 'upload' AND file_name = %s", self.name
        )

    def _dataset_tables(self) -> int:
        return self._q(
            "SELECT count(*) FROM pg_tables WHERE schemaname = %s AND tablename LIKE 'csv\\_%%'", self.schema
        )[0][0]

    def _te_rows(self, org: str) -> int:
        return self._q("SELECT count(*) FROM {t}.organisations WHERE name = %s", org)[0][0]

    def _cleanup(self, org: str | None = None):
        for f in self.client.get("/api/csv/files").json():
            if f["file_name"] == self.name and f["mode"] == "dynamic":
                with mock.patch.object(settings, "allow_destructive", True):
                    self.client.delete(f"/api/csv/files/{f['id']}")
        with Conn() as conn, conn.cursor() as cur:
            if org:
                cur.execute(
                    sql.SQL("DELETE FROM {}.organisations WHERE name = %s").format(sql.Identifier(self.te_schema)),
                    (org,),
                )
            cur.execute(
                sql.SQL("DELETE FROM {}.csv_files WHERE file_name = %s AND mode = 'te'").format(
                    sql.Identifier(self.schema)
                ),
                (self.name,),
            )
            conn.commit()

    def _dynamic(self):
        return self.client.post(
            "/api/csv/upload",
            json={"fileName": self.name, "content": f"k,v\n{self.tag},1\nsecond,2\n", "mode": "dynamic"},
        )

    def _te(self, org: str):
        return self.client.post(
            "/api/csv/upload",
            json={
                "fileName": self.name,
                "content": f"name,org_type,country\n{org},government,AU\n",
                "mode": "te",
                "targetTable": "organisations",
            },
        )

    def _assert_nothing_committed(self, res, tables_before: int, org: str | None = None):
        body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        self.assertFalse(
            res.status_code == 200 and body.get("status") == "ok",
            f"a load whose records could not be written must not report success: {res.status_code} {res.text}",
        )
        self.assertEqual(self._registry(), [], "the load's registry row committed without its records")
        self.assertEqual(
            self._dataset_tables(), tables_before, "the load's dataset table committed without its records"
        )
        if org:
            self.assertEqual(self._te_rows(org), 0, "the load's T&E rows committed without its records")
        self.assertEqual(self._upload_audit(), [], "no upload audit row may exist for a load that did not commit")
        self.assertTrue(
            all(status == "failed" and file_id is None for status, file_id in self._uploads()),
            f"only a failed attempt may be recorded: {self._uploads()}",
        )

    # -- faults ----------------------------------------------------------------------------------

    def test_dynamic_load_rolls_back_when_the_original_cannot_be_stored(self):
        self.addCleanup(self._cleanup)
        before = self._dataset_tables()
        with _fail("store_upload"):
            res = self._dynamic()
        self._assert_nothing_committed(res, before)
        self.assertEqual(self._uploads(), [], "the fault also blocks the failed-attempt record")

    def test_dynamic_load_rolls_back_when_the_audit_row_cannot_be_written(self):
        self.addCleanup(self._cleanup)
        before = self._dataset_tables()
        with _fail("write_audit"):
            res = self._dynamic()
        self._assert_nothing_committed(res, before)
        self.assertEqual([s for s, _ in self._uploads()], ["failed"], "the failed attempt is still recorded (BR-23)")

    def test_te_load_rolls_back_when_the_original_cannot_be_stored(self):
        org = f"ORG_{self.tag}"
        self.addCleanup(self._cleanup, org)
        before = self._dataset_tables()
        with _fail("store_upload"):
            res = self._te(org)
        self._assert_nothing_committed(res, before, org)

    def test_te_load_rolls_back_when_the_audit_row_cannot_be_written(self):
        org = f"ORG_{self.tag}"
        self.addCleanup(self._cleanup, org)
        before = self._dataset_tables()
        with _fail("write_audit"):
            res = self._te(org)
        self._assert_nothing_committed(res, before, org)

    # -- the normal path still writes all three --------------------------------------------------

    def _assert_all_three_recorded(self, res):
        body = res.json()
        self.assertEqual((res.status_code, body["status"]), (200, "ok"), body)
        file_id = int(body["fileId"])
        self.assertEqual(self._registry(), [(file_id, body["tableName"])])
        self.assertEqual(self._uploads(), [("imported", file_id)])
        self.assertIsNotNone(body["uploadId"])
        self.assertEqual(self._upload_audit(), [(file_id, body["tableName"])])
        self.assertNotIn("_duplicateFlags", body)

    def test_successful_dynamic_upload_writes_registry_original_and_audit(self):
        self.addCleanup(self._cleanup)
        self._assert_all_three_recorded(self._dynamic())

    def test_successful_te_upload_writes_registry_original_and_audit(self):
        org = f"ORG_{self.tag}"
        self.addCleanup(self._cleanup, org)
        self._assert_all_three_recorded(self._te(org))


if __name__ == "__main__":
    unittest.main()
