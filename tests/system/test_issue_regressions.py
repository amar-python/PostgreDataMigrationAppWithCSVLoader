"""Regression tests for closed issues that had no behavioural test of their own.

One class per issue, each named for the defect it keeps from coming back:

  #183  rate limiter used the (unvalidated) X-API-Key prefix as the caller's identity
  #178  distinct CSV rows silently dropped as "duplicates" (ambiguous hash serialisation)
  #175  uploader could destroy a dataset through overwrite or a mode switch (guarded by outcome)
  #189  T&E database errors reported the wrong source row

Integration classes need a live PostgreSQL, as in CI. Run: pytest tests/system/test_issue_regressions.py
"""

from __future__ import annotations

import csv
import io
import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from starlette.requests import Request

from api.config import settings
from api.db import Conn
from api.main import app
from api.ratelimit import _client_id, limiter
from api.services import accounts
from api.services.accounts import ROLES
from api.tenancy import migrate_tenant, schema_for

_PW = "correct horse battery staple"


def _csv(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


# ── #183 ─────────────────────────────────────────────────────────────────────

def _request(api_key: str, host: str = "203.0.113.9") -> Request:
    return Request({"type": "http", "headers": [(b"x-api-key", api_key.encode())], "client": (host, 4321)})


@pytest.mark.unit
class RateLimiterIdentity(unittest.TestCase):
    """#183: an attacker must not get a fresh rate-limit bucket by changing X-API-Key."""

    def setUp(self):
        limiter.reset()
        self._saved = settings.RATE_LIMIT_WRITES_PER_MINUTE
        self.client = TestClient(app)

    def tearDown(self):
        settings.RATE_LIMIT_WRITES_PER_MINUTE = self._saved
        limiter.reset()

    def test_identity_does_not_depend_on_the_api_key(self):
        keys = [f"rotate{i:02d}-{'x' * i}" for i in range(10)]
        self.assertEqual(len({_client_id(_request(k)) for k in keys}), 1)

    def test_identity_is_the_peer_address(self):
        self.assertNotEqual(_client_id(_request("k", "203.0.113.9")), _client_id(_request("k", "203.0.113.10")))

    def test_rotating_invalid_keys_from_one_client_share_one_budget(self):
        settings.RATE_LIMIT_WRITES_PER_MINUTE = 2
        payload = {"fileName": "x.csv", "content": "a,b\n1,2\n"}
        codes = [
            self.client.post("/api/csv/preview", json=payload, headers={"X-API-Key": f"rotate{i:02d}-aaaa"}).status_code
            for i in range(5)
        ]
        # Whatever auth says to the first two, the budget is spent after them: the third is refused,
        # not the sixth (one bucket per rotated prefix, the old behaviour, would never refuse).
        self.assertEqual(codes[2:], [429, 429, 429], codes)


# ── #178 ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class RowDedupKeepsDistinctRows(unittest.TestCase):
    """#178: two different rows must not be skipped as duplicates because they serialise alike."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def _upload(self, rows: list[list[str]], name: str = "dedup") -> dict:
        body = self.client.post("/api/csv/upload", json={
            "fileName": f"{name}_{self.tag}.csv", "content": _csv([["a", "b", "c"]] + rows)}).json()
        self.assertEqual(body["status"], "ok", body)
        return body

    def test_the_reported_unit_separator_case_keeps_both_rows(self):
        # Row 1 = ("x\x1fy", "z"), row 2 = ("x", "y\x1fz"): the same characters joined by \x1f.
        body = self._upload([["x\x1fy", "z", self.tag], ["x", "y\x1fz", self.tag]])
        self.assertEqual((body["insertedRows"], body["duplicateRowsSkipped"]), (2, 0))

    def test_every_control_character_stays_distinct_as_a_delimiter_candidate(self):
        rows = []
        for code in range(1, 32):  # NUL can't be stored in PostgreSQL text
            ch, marker = chr(code), f"{self.tag}_{code}"
            rows += [[f"a{ch}b", "c", marker], ["a", f"b{ch}c", marker]]
        body = self._upload(rows, "controls")
        self.assertEqual((body["insertedRows"], body["duplicateRowsSkipped"]), (len(rows), 0))

    def test_unicode_empty_quote_comma_and_newline_cells_stay_distinct(self):
        t = self.tag
        pairs = [
            (["héllo", "wörld", t + "1"], ["héllowörld", "", t + "1"]),
            (["", "ab", t + "2"], ["ab", "", t + "2"]),
            (['a"b', "c", t + "3"], ["a", 'b"c', t + "3"]),
            (["a,b", "c", t + "4"], ["a", "b,c", t + "4"]),
            (["a\nb", "c", t + "5"], ["a", "b\nc", t + "5"]),
            (["日本", "語", t + "6"], ["日", "本語", t + "6"]),
        ]
        rows = [r for pair in pairs for r in pair]
        body = self._upload(rows, "mixed")
        self.assertEqual((body["insertedRows"], body["duplicateRowsSkipped"]), (len(rows), 0))

    def test_a_genuinely_repeated_row_is_still_skipped(self):
        body = self._upload([["same", "row", self.tag], ["same", "row", self.tag]], "repeat")
        self.assertEqual((body["insertedRows"], body["duplicateRowsSkipped"]), (1, 1))

    def test_stored_hashes_carry_the_version_marker(self):
        body = self._upload([["v", "2", self.tag]], "hashver")
        table = body["tableName"].split(".")[-1]
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT _row_hash FROM {}.{}").format(
                sql.Identifier(settings.UPLOADS_SCHEMA), sql.Identifier(table)))
            hashes = [r[0] for r in cur.fetchall()]
        self.assertTrue(hashes and all(h.startswith("v2:") for h in hashes), hashes)


# ── #175 / #189 need a signed-in tenant ──────────────────────────────────────

@pytest.mark.integration
class UploadPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        cls.slug = f"issues_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.headers = {}
        with Conn() as conn, conn.cursor() as cur:
            tid = accounts.create_tenant(cur, cls.slug, "Issue regressions")
            for role in ROLES:
                uid = accounts.create_user(cur, f"{cls.slug}_{role}", _PW)
                accounts.add_membership(cur, uid, tid, role)
            conn.commit()
        migrate_tenant(cls.slug)
        for role in ROLES:
            res = cls.client.post("/api/auth/login", json={
                "tenant": cls.slug, "username": f"{cls.slug}_{role}", "password": _PW})
            assert res.status_code == 200, res.text
            cls.headers[role] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(cls.slug))))
            cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(
                sql.Identifier(settings.CONTROL_SCHEMA)), (cls.slug,))
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE username LIKE %s").format(
                sql.Identifier(settings.CONTROL_SCHEMA)), (f"{cls.slug}_%",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = uuid.uuid4().hex[:10]

    def _post(self, role: str, **body):
        return self.client.post("/api/csv/upload", headers=self.headers[role], json=body)

    def _file_names(self, role: str = "tenant_admin") -> list[str]:
        return [f["file_name"] for f in self.client.get("/api/csv/files", headers=self.headers[role]).json()]


@pytest.mark.integration
class UploadCannotDestroyAnExistingDataset(UploadPaths):
    """#175: an uploader (no delete permission) must not be able to destroy a dataset by uploading.

    The mechanism has changed since #175 was fixed: M5 (#109) stores a repeated filename as the next
    version and ignores `overwrite`, so a dynamic upload no longer drops anything. These tests assert the
    outcome that has to hold under either design: the original table and its rows survive. The T&E path
    still replaces a prior load, so it still needs delete permission, and is tested as such.
    """

    def _dynamic(self, name: str) -> dict:
        res = self._post("tenant_admin", fileName=name, content=f"k\n{self.tag}\n").json()
        self.assertEqual(res["status"], "ok", res)
        return res

    def _registered_tables(self) -> set[str]:
        files = self.client.get("/api/csv/files", headers=self.headers["tenant_admin"]).json()
        return {f["table_name"] for f in files}

    def _rows(self, table: str) -> list[str]:
        res = self.client.get(f"/api/csv/tables/{table}/rows", headers=self.headers["tenant_admin"],
                              params={"limit": 50})
        self.assertEqual(res.status_code, 200, res.text)
        return [r["k"] for r in res.json()["rows"]]

    def test_an_uploader_overwrite_leaves_the_existing_dataset_intact(self):
        name = f"gate_{self.tag}.csv"
        original = self._dynamic(name)["tableName"]
        res = self._post("uploader", fileName=name, content=f"k\n{self.tag}_new\n", overwrite=True)
        self.assertIn(res.status_code, (200, 403), res.text)  # refused, or stored as a new version
        self.assertIn(original, self._registered_tables(), "the existing dataset must still be registered")
        self.assertEqual(self._rows(original), [self.tag], "and its rows must be untouched")

    def test_an_uploader_mode_switch_leaves_the_existing_dataset_intact(self):
        name = f"switch_{self.tag}.csv"
        original = self._dynamic(name)["tableName"]
        res = self._post("uploader", fileName=name, mode="te", targetTable="organisations",
                         content=f"name,org_type,country\nORG_{self.tag},government,AU\n")
        self.assertIn(res.status_code, (200, 403), res.text)
        self.assertIn(original, self._registered_tables(), "the existing dataset must still be registered")
        self.assertEqual(self._rows(original), [self.tag], "and its rows must be untouched")

    def test_an_uploader_cannot_replace_a_prior_te_load(self):
        name = f"te_{self.tag}.csv"
        first = self._post("tenant_admin", fileName=name, mode="te", targetTable="organisations",
                           content=f"name,org_type,country\nORG_A_{self.tag},government,AU\n")
        self.assertEqual(first.json()["status"], "ok", first.text)
        again = self._post("uploader", fileName=name, mode="te", targetTable="organisations",
                           content=f"name,org_type,country\nORG_B_{self.tag},government,AU\n")
        self.assertEqual(again.status_code, 403, again.text)

    def test_a_tenant_admin_may_upload_the_same_name_again(self):
        name = f"admin_{self.tag}.csv"
        self._dynamic(name)
        res = self._post("tenant_admin", fileName=name, content=f"k\n{self.tag}_new\n", overwrite=True)
        self.assertEqual((res.status_code, res.json()["status"]), (200, "ok"), res.text)

    def test_an_uploader_can_still_upload_a_new_file(self):
        res = self._post("uploader", fileName=f"fresh_{self.tag}.csv", content=f"k\n{self.tag}\n")
        self.assertEqual((res.status_code, res.json()["status"]), (200, "ok"), res.text)


@pytest.mark.integration
class TeDatabaseErrorsNameTheSourceRow(UploadPaths):
    """#189: a row that fails in the database is reported by its CSV row, not its place among survivors."""

    def test_type_failure_then_foreign_key_failure_report_rows_1_and_2(self):
        content = _csv([
            ["org_id", "program_code", "program_name", "start_date"],
            [str(uuid.uuid4()), f"P1_{self.tag}", "bad date", "not-a-date"],        # row 1: fails the type check
            [str(uuid.uuid4()), f"P2_{self.tag}", "no such org", "2026-01-01"],     # row 2: fails the foreign key
        ])
        res = self._post("tenant_admin", fileName=f"prog_{self.tag}.csv", mode="te",
                         targetTable="test_programs", content=content).json()
        by_row = {e["rowNumber"]: e for e in res["rowErrors"]}
        self.assertEqual(sorted(by_row), [1, 2], res)
        self.assertEqual(by_row[1].get("column"), "start_date")
        self.assertNotIn("column", by_row[2], "row 2 failed in the database, not the type check")
        self.assertIn("foreign key", by_row[2]["reason"].lower())
