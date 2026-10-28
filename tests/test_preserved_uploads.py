"""Every upload keeps its original file and parsed rows, insert-only (M3b, #107; BR-23, BR-24).

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import hashlib
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
class PreservedUploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.name = f"orig_{self.tag}.csv"

    def tearDown(self):
        for f in self.client.get("/api/csv/files").json():
            if f["file_name"] == self.name:
                self.client.delete(f"/api/csv/files/{f['id']}")

    def _upload(self, content: str, types: list[str] | None = None, overwrite: bool = False) -> dict:
        body = {"fileName": self.name, "content": content, "overwrite": overwrite}
        if types:
            body["types"] = types
        return self.client.post("/api/csv/upload", json=body).json()

    def _upload_row(self, upload_id: str) -> dict:
        return next(u for u in self.client.get("/api/csv/uploads").json() if u["id"] == upload_id)

    def _source_rows(self, upload_id: str) -> list[list[str]]:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT cells FROM {}.source_rows WHERE upload_id = %s ORDER BY row_number")
                        .format(sql.Identifier(settings.UPLOADS_SCHEMA)), (int(upload_id),))
            return [r[0] for r in cur.fetchall()]

    def test_original_bytes_and_rows_are_kept_with_the_outcome(self):
        content = f'name,note\n{self.tag},"a, b"\nsecond,"line\nbreak"\n'
        res = self._upload(content)
        self.assertEqual(res["status"], "ok", res)
        row = self._upload_row(res["uploadId"])
        self.assertEqual((row["status"], row["uploader"], row["total_rows"], row["imported_rows"]),
                         ("imported", "api_key", 2, 2))
        self.assertEqual(row["csv_file_id"], res["fileId"])
        original = self.client.get(f"/api/csv/uploads/{res['uploadId']}/original")
        self.assertEqual(original.content, content.encode("utf-8"))
        self.assertEqual(original.headers["x-content-sha256"], hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(self._source_rows(res["uploadId"]),
                         [["name", "note"], [self.tag, "a, b"], ["second", "line\nbreak"]])
        [listed] = [f for f in self.client.get("/api/csv/files").json() if f["file_name"] == self.name]
        self.assertEqual((listed["uploader"], listed["upload_id"]), ("api_key", res["uploadId"]))

    def test_a_failed_upload_still_keeps_its_original(self):
        content = f"Date,Ref\n27 Oct 26,{self.tag}\n"
        res = self._upload(content, ["timestamptz", "text"])
        self.assertEqual(res["status"], "error", res)
        row = self._upload_row(res["uploadId"])
        self.assertEqual((row["status"], row["csv_file_id"], row["failed_rows"]), ("failed", None, 1))
        self.assertEqual(self.client.get(f"/api/csv/uploads/{res['uploadId']}/original").content, content.encode())

    def test_partly_failed_and_duplicate_outcomes(self):
        res = self._upload(f"n,t\n1,{self.tag}\nx,{self.tag}\n", ["int8", "text"])
        self.assertEqual(self._upload_row(res["uploadId"])["status"], "partly_imported")
        again = self._upload(f"n,t\n1,{self.tag}\nx,{self.tag}\n", ["int8", "text"])
        self.assertEqual(again["status"], "duplicate_file", again)
        self.assertEqual(self._upload_row(again["uploadId"])["status"], "duplicate")

    def test_overwrite_keeps_the_replaced_original(self):
        first = self._upload(f"v\nold_{self.tag}\n")
        second = self._upload(f"v\nnew_{self.tag}\n", overwrite=True)
        self.assertEqual(second["status"], "ok", second)
        self.assertEqual(self.client.get(f"/api/csv/uploads/{first['uploadId']}/original").content,
                         f"v\nold_{self.tag}\n".encode())
        self.assertEqual(self._source_rows(first["uploadId"]), [["v"], [f"old_{self.tag}"]])

    def test_preserved_tables_reject_update_and_delete(self):
        res = self._upload(f"v\n{self.tag}\n")
        uid = int(res["uploadId"])
        for table, column in (("uploads", "file_name"), ("upload_blobs", "content"), ("source_rows", "cells")):
            for statement in (f"UPDATE {{}}.{table} SET {column} = {column} WHERE {'id' if table == 'uploads' else 'upload_id'} = %s",
                              f"DELETE FROM {{}}.{table} WHERE {'id' if table == 'uploads' else 'upload_id'} = %s"):
                with self.subTest(statement=statement), Conn() as conn, conn.cursor() as cur:
                    with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                        cur.execute(sql.SQL(statement).format(sql.Identifier(settings.UPLOADS_SCHEMA)), (uid,))
                    conn.rollback()

    def test_unknown_upload_is_404(self):
        self.assertEqual(self.client.get("/api/csv/uploads/999999999/original").status_code, 404)
