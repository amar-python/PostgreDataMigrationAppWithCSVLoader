"""Issue #5 — "Add an import summary section showing total rows processed,
created, skipped duplicates, and failed counts for the current batch."

Scope of these tests
--------------------
They verify the **API returns the four counts, and that each is correct** —
not merely present. The mapping asserted here is:

    issue term              response field
    ------------------      ----------------------
    total rows processed    totalRows
    created                 insertedRows
    skipped duplicates      duplicateRowsSkipped
    failed                  failedRows

Each count is exercised in a scenario where its expected value is known in
advance, plus an arithmetic invariant that ties them together.

What they do NOT verify: that the CSV Table Hub UI renders a summary section.
The issue says "section", implying UI. Passing here means the data the section
needs is available and accurate; a browser test is needed to confirm it is
displayed.

Run::

    python -m pytest tests/test_issue_05_import_summary.py

Requires a reachable database; per the repository's no-skip policy a missing
prerequisite FAILS with remediation text rather than skipping.
"""
from __future__ import annotations

import os
import unittest

import pytest
from fastapi.testclient import TestClient

from api.main import app

_HELP = ("Start PostgreSQL and ensure api/ can reach it. Most often this means "
         "PGPASSWORD is not set in this shell:\n"
         "    PowerShell:  $env:PGPASSWORD = '<password>'\n"
         "    bash:        export PGPASSWORD='<password>'")

SUMMARY_FIELDS = ("totalRows", "insertedRows", "duplicateRowsSkipped", "failedRows")


@pytest.mark.integration
class ImportSummaryCounts(unittest.TestCase):
    """Issue #5 — the four batch counts are present and accurate."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"Could not start the API — database connection failed.\n"
                f"  {type(exc).__name__}: {str(exc).strip().splitlines()[0]}\n"
                f"{_HELP}"
            ) from None
        if cls.client.get("/api/health").json().get("status") != "ok":
            cls.ctx.__exit__(None, None, None)
            raise AssertionError(f"API reports the database is unreachable. {_HELP}")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.uploaded: list[str] = []
        self.tag = f"issue05_{os.getpid()}_{self._testMethodName}"

    def tearDown(self):
        for f in self.client.get("/api/csv/files").json():
            if f["file_name"] in self.uploaded:
                self.client.delete(f"/api/csv/files/{f['id']}")

    def _upload(self, content: str, suffix: str = "", **extra) -> dict:
        name = f"{self.tag}{suffix}.csv"
        self.uploaded.append(name)
        payload = {"fileName": name, "content": content, **extra}
        r = self.client.post("/api/csv/upload", json=payload)
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r.json()

    # ── presence ─────────────────────────────────────────────────────────────

    def test_all_four_counts_are_returned(self):
        body = self._upload(f"col_a\n{self.tag}\n")
        self.assertEqual(body["status"], "ok", body)
        missing = [f for f in SUMMARY_FIELDS if f not in body]
        self.assertEqual(missing, [], f"summary fields missing: {missing}")
        for field in SUMMARY_FIELDS:
            self.assertIsInstance(body[field], int, f"{field} should be an integer")

    # ── each count, in a scenario with a known answer ────────────────────────

    def test_total_rows_counts_data_rows_not_the_header(self):
        body = self._upload(f"col_a\n{self.tag}-1\n{self.tag}-2\n{self.tag}-3\n")
        self.assertEqual(body["totalRows"], 3,
                         "header row must not be counted as data")

    def test_created_count_matches_rows_actually_inserted(self):
        body = self._upload(f"col_a\n{self.tag}-1\n{self.tag}-2\n")
        self.assertEqual(body["insertedRows"], 2)

        rows = self.client.get(
            f"/api/csv/tables/{body['tableName']}/rows").json()["rows"]
        self.assertEqual(len(rows), body["insertedRows"],
                         "insertedRows must match what is actually in the table")

    def test_duplicate_count_reflects_repeated_rows_in_the_file(self):
        """Two identical rows plus one distinct: 1 duplicate skipped."""
        body = self._upload(f"col_a\n{self.tag}-same\n{self.tag}-same\n{self.tag}-other\n")
        self.assertEqual(body["totalRows"], 3)
        self.assertEqual(body["insertedRows"], 2)
        self.assertEqual(body["duplicateRowsSkipped"], 1)

    def test_failed_count_reflects_rows_that_could_not_be_cast(self):
        """With an int8 column, a non-numeric value must count as failed.

        This is the only count that depends on explicit column types; with the
        default (all text) nothing fails to cast, so the scenario must request
        a type to exercise it.
        """
        body = self._upload(
            "num\n1\nnot_a_number\n3\n",
            types=["int8"],
        )
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(body["failedRows"], 1,
                         f"expected 1 uncastable row, got {body['failedRows']}")
        self.assertEqual(body["insertedRows"], 2)

    def test_failed_rows_are_reported_with_detail(self):
        """A count alone is not actionable — the offending row must be named."""
        body = self._upload("num\n1\nbad_value\n", types=["int8"])
        self.assertTrue(body["rowErrors"], "rowErrors should describe each failure")
        err = body["rowErrors"][0]
        for key in ("rowNumber", "column", "value", "reason"):
            self.assertIn(key, err, f"rowErrors entry missing '{key}'")
        self.assertEqual(err["value"], "bad_value")

    # ── the counts must add up ───────────────────────────────────────────────

    def test_counts_reconcile_for_a_clean_file(self):
        body = self._upload(f"col_a\n{self.tag}-1\n{self.tag}-2\n{self.tag}-3\n")
        self.assertEqual(
            body["totalRows"],
            body["insertedRows"] + body["duplicateRowsSkipped"] + body["failedRows"],
            f"counts do not reconcile: {({k: body[k] for k in SUMMARY_FIELDS})}",
        )

    def test_counts_reconcile_for_a_mixed_file(self):
        """One good row, one in-file duplicate, one uncastable value."""
        body = self._upload("num\n1\n1\nnot_a_number\n", types=["int8"])
        summary = {k: body[k] for k in SUMMARY_FIELDS}
        self.assertEqual(
            body["totalRows"],
            body["insertedRows"] + body["duplicateRowsSkipped"] + body["failedRows"],
            f"counts do not reconcile: {summary}",
        )
        self.assertEqual(body["totalRows"], 3, summary)

    # ── the counts describe this batch only ──────────────────────────────────

    def test_counts_are_per_batch_not_cumulative(self):
        """A second, larger upload must report its own totals, not a running sum."""
        first = self._upload(f"col_a\n{self.tag}-a\n", suffix="_first")
        self.assertEqual(first["totalRows"], 1)

        second = self._upload(
            f"col_a\n{self.tag}-b\n{self.tag}-c\n{self.tag}-d\n", suffix="_second")
        self.assertEqual(second["totalRows"], 3,
                         "the summary must describe the current batch only")
