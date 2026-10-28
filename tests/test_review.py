"""Review of stored uploads: paging, row decisions and versioned cell edits (M4a, #108; BR-25..27).

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import os
import unittest
import uuid

import psycopg2.errors
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app


@pytest.mark.integration
class Review(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def _upload(self, content: str, types: list[str]) -> dict:
        return self.client.post("/api/csv/upload", json={
            "fileName": f"rev_{self.tag}.csv", "content": content, "types": types}).json()

    def _three_rows(self) -> str:
        res = self._upload(f"n,t\n1,{self.tag}\nx,b\n3,c\n", ["int8", "text"])
        self.assertEqual(res["status"], "ok", res)
        return res["uploadId"]

    def _rows(self, uid: str, **params) -> dict:
        res = self.client.get(f"/api/csv/uploads/{uid}/rows", params=params)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _decide(self, uid: str, row: int, decision: str, reason: str = "checked with the owner"):
        return self.client.put(f"/api/csv/uploads/{uid}/rows/{row}/decision",
                               json={"decision": decision, "reason": reason})

    def _edit(self, uid: str, row: int, column: str, value: str, reason: str = "typo in source"):
        return self.client.put(f"/api/csv/uploads/{uid}/rows/{row}/cells/{column}",
                               json={"value": value, "reason": reason})

    def test_pages_through_every_row_with_validation(self):
        uid = self._three_rows()
        page = self._rows(uid)
        self.assertEqual((page["total"], page["columns"], page["types"]), (3, ["n", "t"], ["int8", "text"]))
        self.assertEqual([r["rowNumber"] for r in page["rows"]], [1, 2, 3])
        self.assertEqual([len(r["errors"]) for r in page["rows"]], [0, 1, 0])
        self.assertEqual(page["rows"][1]["errors"][0]["reason"], '"x" is not a whole number')
        self.assertEqual([r["rowNumber"] for r in self._rows(uid, offset=2, limit=2)["rows"]], [3])

    def test_validates_rows_beyond_the_reported_error_cap(self):
        n = settings.MAX_ROW_ERRORS_REPORTED + 50
        res = self._upload("n\n" + "".join(f"bad{i}_{self.tag}\n" for i in range(n)), ["int8"])
        self.assertEqual(res["status"], "error", res)
        self.assertEqual(len(res["rowErrors"]), settings.MAX_ROW_ERRORS_REPORTED)
        last = self._rows(res["uploadId"], offset=n - 1, limit=1)["rows"][0]
        self.assertEqual((last["rowNumber"], len(last["errors"])), (n, 1))

    def test_row_decisions_record_actor_and_reason_and_the_latest_wins(self):
        uid = self._three_rows()
        self.assertEqual(self._decide(uid, 2, "exclude").status_code, 200)
        page = self._rows(uid)
        self.assertEqual((page["rows"][1]["decision"], page["excludedRows"]), ("exclude", 1))
        self.assertEqual(self._decide(uid, 2, "include", "fixed upstream").json()["decision"], "include")
        self.assertEqual(self._rows(uid)["excludedRows"], 0)
        history = self.client.get(f"/api/csv/uploads/{uid}/rows/2/history").json()
        self.assertEqual([(h["decision"], h["actor"], h["reason"]) for h in history],
                         [("exclude", "api_key", "checked with the owner"), ("include", "api_key", "fixed upstream")])

    def test_cell_edits_are_versions_over_the_unchanged_original(self):
        uid = self._three_rows()
        row = self._edit(uid, 2, "n", "2").json()
        self.assertEqual((row["original"], row["current"], row["editedColumns"], row["errors"]),
                         (["x", "b"], ["2", "b"], [0], []))
        self.assertEqual(self._edit(uid, 2, "0", "20", "second look").json()["current"], ["20", "b"])
        edits = [h for h in self.client.get(f"/api/csv/uploads/{uid}/rows/2/history").json() if h["kind"] == "edit"]
        self.assertEqual([(e["column"], e["oldValue"], e["newValue"], e["reason"]) for e in edits],
                         [("n", "x", "2", "typo in source"), ("n", "2", "20", "second look")])
        with Conn() as conn, conn.cursor() as cur:   # M3's original is untouched
            cur.execute(sql.SQL("SELECT cells FROM {}.source_rows WHERE upload_id = %s AND row_number = 2")
                        .format(sql.Identifier(settings.UPLOADS_SCHEMA)), (int(uid),))
            self.assertEqual(cur.fetchone()[0], ["x", "b"])
        listed = [f for f in self.client.get("/api/csv/files").json() if f["upload_id"] == uid]
        self.assertEqual(listed[0]["row_count"], 2, "decision 1: the imported table doesn't change until M6")

    def test_refusals(self):
        uid = self._three_rows()
        for res, code in ((self._decide(uid, 2, "exclude", "  "), 422), (self._edit(uid, 2, "n", "5", ""), 422),
                          (self._decide(uid, 2, "maybe"), 422), (self._edit(uid, 2, "n", "x"), 422),
                          (self._decide(uid, 4, "exclude"), 404), (self._edit(uid, 1, "nope", "1"), 404),
                          (self.client.get("/api/csv/uploads/999999999/rows"), 404)):
            with self.subTest(body=res.text):
                self.assertEqual(res.status_code, code)
        self.assertEqual(self.client.get(f"/api/csv/uploads/{uid}/rows/2/history").json(), [])

    def test_changes_are_audited_and_insert_only(self):
        uid = self._three_rows()
        self._decide(uid, 3, "exclude")
        self._edit(uid, 2, "n", "2")
        with Conn() as conn, conn.cursor() as cur:
            s = sql.Identifier(settings.UPLOADS_SCHEMA)
            cur.execute(sql.SQL("SELECT action, before_value, after_value FROM {}.audit_log "
                                "WHERE after_value->>'upload' = %s ORDER BY id").format(s), (uid,))
            [(a1, b1, f1), (a2, b2, f2)] = cur.fetchall()
            self.assertEqual((a1, b1["decision"], f1["decision"]), ("row_decision", "include", "exclude"))
            self.assertEqual((a2, b2["value"], f2["value"], f2["column"]), ("cell_edit", "x", "2", "n"))
            for table in ("row_decisions", "cell_edits"):
                with self.subTest(table=table), self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(sql.SQL("DELETE FROM {}.{} WHERE upload_id = %s").format(s, sql.Identifier(table)),
                                (int(uid),))
                conn.rollback()
        self.assertTrue(self.client.get("/api/audit/verify").json()["intact"])
