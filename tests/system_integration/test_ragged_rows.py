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
