"""#289 (OIT-004, BR-33, BR-34, M0 decision 4): a T&E upload imports every row or none.

"Partial imports are not permitted" (M0 decision 4). The T&E direct path used to commit the rows that
loaded and skip the ones that failed, as long as one row landed: a file with a bad row was partly imported
without review, and the registry recorded the partial count. Asserted here, through the API:

  * a file with one row that fails the client-side type check imports nothing;
  * a file with one row that fails in the database (a constraint) imports nothing;
  * both kinds in one file are all reported, by their CSV row number, and still nothing is imported;
  * a failed re-upload keeps the earlier load (its registry row and rows);
  * a clean file still imports every row (control).

Needs a live PostgreSQL with the dev schema deployed, as in CI.
"""

from __future__ import annotations

import unittest
import uuid

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app

HEADER = "name,org_type,country,is_active"


@pytest.mark.integration
class TeImportIsAllOrNothing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"AON_{uuid.uuid4().hex[:10]}"
        self.file_name = f"{self.tag}.csv"
        self.addCleanup(self._cleanup)

    # -- helpers ---------------------------------------------------------------------------------

    def _org(self, suffix: str, *, org_type: str = "government", is_active: str = "true") -> str:
        return f"{self.tag}_{suffix},{org_type},AU,{is_active}"

    def _csv(self, *rows: str) -> str:
        return "\n".join([HEADER, *rows]) + "\n"

    def _upload(self, content: str, file_name: str | None = None) -> dict:
        res = self.client.post(
            "/api/csv/upload",
            json={
                "fileName": file_name or self.file_name,
                "content": content,
                "mode": "te",
                "targetTable": "organisations",
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def _org_names(self) -> list[str]:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT name FROM {}.organisations WHERE name LIKE %s ORDER BY name").format(
                    sql.Identifier(settings.TE_SCHEMA)
                ),
                (f"{self.tag}\\_%",),
            )
            return [r[0] for r in cur.fetchall()]

    def _registered(self) -> list[dict]:
        res = self.client.get("/api/csv/files")
        self.assertEqual(res.status_code, 200, res.text)
        return [f for f in res.json() if f["file_name"] == self.file_name]

    def _cleanup(self) -> None:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {}.organisations WHERE name LIKE %s").format(sql.Identifier(settings.TE_SCHEMA)),
                (f"{self.tag}\\_%",),
            )
            cur.execute(
                sql.SQL("DELETE FROM {}.csv_files WHERE file_name = %s AND mode = 'te'").format(
                    sql.Identifier(settings.UPLOADS_SCHEMA)
                ),
                (self.file_name,),
            )
            conn.commit()

    def _assert_nothing_imported(self, body: dict) -> None:
        self.assertEqual(body["status"], "error", body)
        self.assertEqual(body["insertedRows"], 0, "the response must not claim rows that were rolled back")
        self.assertIn("nothing was saved", body["message"], body)
        self.assertEqual(self._org_names(), [], "no row of a file with a failing row may land")
        self.assertEqual(self._registered(), [], "no registry row for a load that imported nothing")

    # -- the policy ------------------------------------------------------------------------------

    def test_one_row_failing_the_type_check_imports_nothing(self):
        body = self._upload(self._csv(self._org("a"), self._org("b", is_active="NOT_A_BOOL"), self._org("c")))
        self._assert_nothing_imported(body)
        self.assertEqual((body["totalRows"], body["failedRows"]), (3, 1), body)
        [err] = body["rowErrors"]
        self.assertEqual((err["rowNumber"], err["column"], err["value"]), (2, "is_active", "NOT_A_BOOL"), err)

    def test_one_row_failing_in_the_database_imports_nothing(self):
        body = self._upload(self._csv(self._org("a"), self._org("b", org_type="INVALID_ENUM"), self._org("c")))
        self._assert_nothing_imported(body)
        self.assertEqual((body["totalRows"], body["failedRows"]), (3, 1), body)
        self.assertEqual([e["rowNumber"] for e in body["rowErrors"]], [2], body)

    def test_both_kinds_of_failure_are_all_reported_and_nothing_is_imported(self):
        body = self._upload(
            self._csv(
                self._org("a", is_active="NOT_A_BOOL"),  # row 1: type check
                self._org("b", org_type="INVALID_ENUM"),  # row 2: database
                self._org("c"),
            )
        )  # row 3: fine, but it must not land either
        self._assert_nothing_imported(body)
        self.assertEqual((body["totalRows"], body["failedRows"]), (3, 2), body)
        self.assertEqual(sorted(e["rowNumber"] for e in body["rowErrors"]), [1, 2], body)

    def test_the_message_names_the_first_problem_and_how_many_rows_failed(self):
        body = self._upload(self._csv(self._org("a"), self._org("b", is_active="NOT_A_BOOL")))
        self.assertIn("1 of the 2 rows", body["message"], body)
        self.assertIn("row 2", body["message"], body)

    def test_a_failed_reupload_keeps_the_earlier_load(self):
        first = self._upload(self._csv(self._org("first")))
        self.assertEqual(first["status"], "ok", first)
        [registered] = self._registered()
        again = self._upload(self._csv(self._org("second"), self._org("bad", is_active="NOT_A_BOOL")))
        self.assertEqual(again["status"], "error", again)
        self.assertEqual(self._org_names(), [f"{self.tag}_first"], "the second file's good row must not land")
        self.assertEqual(
            [f["id"] for f in self._registered()],
            [registered["id"]],
            "the earlier load's registry row must be untouched",
        )

    def test_a_clean_file_still_imports_every_row(self):
        body = self._upload(self._csv(self._org("a"), self._org("b"), self._org("c")))
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual((body["totalRows"], body["insertedRows"], body["failedRows"]), (3, 3, 0), body)
        self.assertEqual(len(self._org_names()), 3)
        [entry] = self._registered()
        self.assertEqual((entry["total_rows"], entry["row_count"], entry["failed_rows"]), (3, 3, 0))
