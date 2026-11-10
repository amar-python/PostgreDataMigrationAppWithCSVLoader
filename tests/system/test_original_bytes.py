"""The preserved original is the uploaded bytes, not a UTF-8 re-encoding of decoded text (#185; BR-24).

A BOM or an invalid byte changes the retained bytes and the digest if the original is
rebuilt from the decoded text. When the client sends the raw bytes alongside the text,
the stored original and its sha256 must match the uploader's own copy.

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import base64
import hashlib
import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")


def _browser_decode(raw: bytes) -> str:
    """What FileReader.readAsText hands the client for UTF-8 input: BOM dropped, bad bytes -> U+FFFD."""
    text = raw.decode("utf-8", errors="replace")
    return text[1:] if text.startswith("﻿") else text


@pytest.mark.integration
class OriginalBytesAreKept(unittest.TestCase):
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

    def _upload_bytes(self, raw: bytes, **extra) -> dict:
        body = {
            "fileName": f"bytes_{self.tag}.csv",
            "content": _browser_decode(raw),
            "contentBase64": base64.b64encode(raw).decode("ascii"),
            **extra,
        }
        return self.client.post("/api/csv/upload", json=body).json()

    def _assert_round_trips(self, raw: bytes, res: dict):
        original = self.client.get(f"/api/csv/uploads/{res['uploadId']}/original")
        self.assertEqual(original.content, raw)
        self.assertEqual(original.headers["x-content-sha256"], hashlib.sha256(raw).hexdigest())
        stored = next(u for u in self.client.get("/api/csv/uploads").json() if u["id"] == res["uploadId"])
        self.assertEqual((stored["sha256"], stored["byte_size"]), (hashlib.sha256(raw).hexdigest(), len(raw)))

    def test_bom_prefixed_csv_round_trips_byte_identical(self):
        raw = b"\xef\xbb\xbf" + f"a,b\n1,{self.tag}\n".encode()
        res = self._upload_bytes(raw)
        self.assertEqual(res["status"], "ok", res)
        self._assert_round_trips(raw, res)
        self.assertEqual(res["columns"], ["a", "b"], "the BOM must not leak into the first column name")

    def test_csv_with_an_invalid_utf8_byte_round_trips_byte_identical(self):
        raw = b"a,b\n1," + self.tag.encode() + b"\x80\n"
        res = self._upload_bytes(raw)
        self.assertEqual(res["status"], "ok", res)
        self._assert_round_trips(raw, res)

    def test_the_decoded_view_still_feeds_the_loader_and_source_rows(self):
        raw = b"\xef\xbb\xbf" + f"a,b\n1,{self.tag}\n".encode()
        res = self._upload_bytes(raw)
        rows = self.client.get(f"/api/csv/tables/{res['tableName']}/rows").json()["rows"]
        self.assertEqual([r["b"] for r in rows], [self.tag])

    def test_a_failed_upload_keeps_the_raw_original_too(self):
        raw = b"\xef\xbb\xbf" + f"n,t\nx,{self.tag}\n".encode()
        res = self._upload_bytes(raw, types=["int8", "text"])
        self.assertEqual(res["status"], "error", res)
        self._assert_round_trips(raw, res)

    def test_without_contentbase64_the_utf8_encoding_of_content_is_kept_as_before(self):
        content = f"a,b\n1,{self.tag}\n"
        res = self.client.post("/api/csv/upload", json={
            "fileName": f"bytes_plain_{self.tag}.csv", "content": content}).json()
        self._assert_round_trips(content.encode(), res)

    def test_invalid_base64_is_rejected_before_anything_loads(self):
        resp = self.client.post("/api/csv/upload", json={
            "fileName": f"bytes_bad_{self.tag}.csv", "content": "a\n1\n", "contentBase64": "not base64!!"})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("base64", resp.json()["detail"])
