"""Issue #4 — "I need a UI frontend to allow customers to upload any number of
csv files as they like."

Scope of these tests
--------------------
They verify the **API contract** that makes the requirement satisfiable:

* several files can be uploaded in one session, each landing in its own table;
* each is registered and independently listable and readable;
* CSV *shape* is not constrained — narrow, wide, one-row and many-row files all
  load;
* nothing in the API imposes a per-session upload limit.

What they do NOT verify: that the CSV Table Hub UI renders any of this. That is
frontend behaviour and needs a browser test. Passing here means the backend
does not block the requirement, not that the feature is visibly complete.

Run::

    python -m pytest tests/test_issue_04_multi_file_upload.py

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

# How many files to push through in the "any number" test. Kept modest so the
# suite stays fast; the point is that the API imposes no limit, not throughput.
BATCH_SIZE = 5


@pytest.mark.integration
class MultipleFileUpload(unittest.TestCase):
    """Issue #4 — several files, arbitrary shapes, all independently readable."""

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
        self.tag = f"issue04_{os.getpid()}_{self._testMethodName}"

    def tearDown(self):
        """Remove only the files this test created."""
        for f in self.client.get("/api/csv/files").json():
            if f["file_name"] in self.uploaded:
                self.client.delete(f"/api/csv/files/{f['id']}")

    def _upload(self, name: str, content: str) -> dict:
        self.uploaded.append(name)
        r = self.client.post("/api/csv/upload",
                             json={"fileName": name, "content": content})
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r.json()

    # ── the core requirement ─────────────────────────────────────────────────

    def test_many_files_upload_in_one_session(self):
        """Uploading several files in sequence must all succeed."""
        tables = []
        for i in range(BATCH_SIZE):
            body = self._upload(f"{self.tag}_{i}.csv",
                                f"col_a,col_b\n{self.tag},{i}\n")
            self.assertEqual(body["status"], "ok", body)
            tables.append(body["tableName"])

        self.assertEqual(len(set(tables)), BATCH_SIZE,
                         f"each file needs its own table, got {tables}")

    def test_every_uploaded_file_is_listed(self):
        """All uploads appear in /api/csv/files — this drives 'Migrated files'."""
        for i in range(BATCH_SIZE):
            self._upload(f"{self.tag}_{i}.csv", f"col_a\n{self.tag}-{i}\n")

        listed = {f["file_name"] for f in self.client.get("/api/csv/files").json()}
        missing = [n for n in self.uploaded if n not in listed]
        self.assertEqual(missing, [], f"uploaded but not listed: {missing}")

    def test_each_file_is_independently_readable(self):
        """Rows from one upload must not leak into another's table."""
        first = self._upload(f"{self.tag}_first.csv", f"col_a\n{self.tag}-first\n")
        second = self._upload(f"{self.tag}_second.csv",
                              f"col_a\n{self.tag}-s1\n{self.tag}-s2\n")

        self.assertNotEqual(first["tableName"], second["tableName"])

        r1 = self.client.get(f"/api/csv/tables/{first['tableName']}/rows").json()
        r2 = self.client.get(f"/api/csv/tables/{second['tableName']}/rows").json()
        self.assertEqual(len(r1["rows"]), 1)
        self.assertEqual(len(r2["rows"]), 2)

    # ── "as they like" — shape is not constrained ────────────────────────────

    def test_narrow_and_wide_files_both_load(self):
        """One column and many columns must both be accepted."""
        narrow = self._upload(f"{self.tag}_narrow.csv", f"only_col\n{self.tag}\n")
        self.assertEqual(narrow["status"], "ok", narrow)
        self.assertEqual(len(narrow["columns"]), 1)

        headers = ",".join(f"c{i}" for i in range(40))
        values = ",".join(f"{self.tag}-{i}" for i in range(40))
        wide = self._upload(f"{self.tag}_wide.csv", f"{headers}\n{values}\n")
        self.assertEqual(wide["status"], "ok", wide)
        self.assertEqual(len(wide["columns"]), 40)

    def test_files_with_different_schemas_coexist(self):
        """Unrelated column sets must not collide — no shared fixed schema."""
        a = self._upload(f"{self.tag}_shape_a.csv",
                         f"name,email\n{self.tag},a@example.com\n")
        b = self._upload(f"{self.tag}_shape_b.csv",
                         f"sku,qty,price\n{self.tag},3,9.99\n")

        self.assertEqual(a["columns"], ["name", "email"])
        self.assertEqual(b["columns"], ["sku", "qty", "price"])
        self.assertNotEqual(a["tableName"], b["tableName"])

    def test_a_larger_file_loads_completely(self):
        """Row count is not silently truncated."""
        rows = "\n".join(f"{self.tag},{i}" for i in range(250))
        body = self._upload(f"{self.tag}_bulk.csv", f"col_a,col_b\n{rows}\n")
        self.assertEqual(body["status"], "ok", body)
        self.assertEqual(body["totalRows"], 250)
        self.assertEqual(body["insertedRows"], 250,
                         "all distinct rows should load")
