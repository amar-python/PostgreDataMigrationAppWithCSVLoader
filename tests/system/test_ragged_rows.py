"""Rows wider than the header are reported, never silently truncated (#82)."""

from __future__ import annotations

import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.csv_parse import extra_cells

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")


@pytest.mark.unit
class ExtraCells(unittest.TestCase):
    def test_non_empty_cells_beyond_the_header_are_returned(self):
        self.assertEqual(extra_cells(["1", "2", "x", ""], 2), ["x"])

    def test_trailing_empty_cells_are_not_extra(self):
        self.assertEqual(extra_cells(["1", "2", "", "  "], 2), [])

    def test_short_rows_have_no_extra_cells(self):
        self.assertEqual(extra_cells(["1"], 2), [])


@pytest.mark.integration
class RaggedRowsOverTheApi(unittest.TestCase):
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

    def _upload(self, content: str, **extra) -> dict:
        body = {"fileName": f"ragged_{self.tag}.csv", "content": content, **extra}
        return self.client.post("/api/csv/upload", json=body).json()

    def test_dynamic_mode_reports_a_row_wider_than_the_header(self):
        res = self._upload(f"a,b\n1,{self.tag}\n2,{self.tag},LOST\n")
        self.assertEqual(res["status"], "ok")
        self.assertEqual((res["insertedRows"], res["failedRows"]), (1, 1))
        err = res["rowErrors"][0]
        self.assertEqual((err["rowNumber"], err["value"]), (2, "LOST"))
        self.assertIn("header has 2", err["reason"])
        # #192: accounting identity — every row is accounted for
        self.assertEqual(
            res["totalRows"],
            res["insertedRows"] + res.get("duplicateRowsSkipped", 0) + res["failedRows"],
            f"Accounting identity violated: {res}",
        )

    def test_dynamic_mode_accepts_a_trailing_empty_cell(self):
        res = self._upload(f"a,b\n1,{self.tag},\n")
        self.assertEqual((res["status"], res["insertedRows"], res["failedRows"]), ("ok", 1, 0))

    def test_te_mode_reports_a_row_wider_than_the_header(self):
        content = (f"name,org_type,country\nRAG_{self.tag}_1,government,AU\n"
                   f"RAG_{self.tag}_2,government,AU,LOST\n")
        res = self._upload(content, mode="te", targetTable="organisations")
        self.assertEqual(res["status"], "ok")
        self.assertEqual((res["insertedRows"], res["failedRows"]), (1, 1))
        self.assertEqual(res["rowErrors"][0]["value"], "LOST")
        # #192: accounting identity
        self.assertEqual(
            res["totalRows"],
            res["insertedRows"] + res.get("duplicateRowsSkipped", 0) + res["failedRows"],
            f"Accounting identity violated: {res}",
        )

    def test_multiple_ragged_rows_each_get_a_reason(self):
        """Every ragged row gets its own entry in rowErrors with a reason."""
        content = (f"a,b\n"
                   f"1,{self.tag}\n"
                   f"2,{self.tag},X1,X2\n"
                   f"3,{self.tag},X3\n")
        res = self._upload(content)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["failedRows"], 2)
        self.assertEqual(res["insertedRows"], 1)
        for err in res["rowErrors"]:
            self.assertIn("rowNumber", err, f"Missing rowNumber: {err}")
            self.assertIn("reason", err, f"Missing reason: {err}")
            self.assertTrue(err["reason"], f"Empty reason: {err}")

    # ── #192: what the tests above don't check — the reason is *stored* with the upload
    # (GET /api/csv/uploads/{id}), not just returned, and T&E mode accounts the same way.
    def _assert_accounted(self, res: dict, ragged_rows: dict[int, str]):
        """total = inserted + duplicates + failed, and every ragged row has a
        reason both in the response and stored with the upload."""
        self.assertEqual(res["status"], "ok")
        self.assertEqual(
            res["totalRows"],
            res["insertedRows"] + res["duplicateRowsSkipped"] + res["failedRows"],
            f"rows went missing: {res}")
        self.assertEqual(res["failedRows"], len(ragged_rows))

        def by_row(errors):
            return {e["rowNumber"]: e for e in errors}

        returned = by_row(res["rowErrors"])
        self.assertEqual(set(returned), set(ragged_rows))
        stored_detail = self.client.get(f"/api/csv/uploads/{res['uploadId']}").json()
        stored = by_row(stored_detail["rowErrors"])
        for row_number, lost in ragged_rows.items():
            for where, err in (("response", returned[row_number]), ("stored", stored[row_number])):
                self.assertEqual(err["value"], lost, f"row {row_number} {where}")
                self.assertIn("would be lost", err["reason"], f"row {row_number} {where}")
        self.assertEqual(stored_detail["failedRows"], len(ragged_rows))

    def test_dynamic_mode_accounts_for_every_row_with_a_stored_reason(self):
        t = self.tag
        res = self._upload(
            f"a,b\n1,{t}\n1,{t}\n2,{t},LOST1\n3,{t}\n4,{t},LOST2,MORE\n")
        self.assertEqual((res["insertedRows"], res["duplicateRowsSkipped"], res["failedRows"]), (2, 1, 2))
        self._assert_accounted(res, {3: "LOST1", 5: "LOST2"})

    def test_te_mode_accounts_for_every_row_with_a_stored_reason(self):
        t = self.tag
        head = "name,org_type,country\n"
        res = self._upload(
            head + f"RAG_{t}_1,government,AU\n"
                   f"RAG_{t}_2,government,AU,LOST1\n"
                   f"RAG_{t}_3,government,AU\n"
                   f"RAG_{t}_4,government,AU,LOST2,MORE\n",
            mode="te", targetTable="organisations")
        self.assertEqual((res["insertedRows"], res["failedRows"]), (2, 2))
        self._assert_accounted(res, {2: "LOST1", 4: "LOST2"})
