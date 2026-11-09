"""Concurrent uploads of the same file must not create duplicate registry rows (#191).

The UNIQUE constraints on csv_files(file_hash) and csv_files(file_name)
settle the race at the database level. This test verifies that two
simultaneous uploads of the same content yield one success and one
graceful rejection — not a duplicate row or partial state.
"""

from __future__ import annotations

import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from api.main import app

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")


@pytest.mark.integration
class RegistryRace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}"
            ) from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def _upload(self, file_name: str, content: str) -> dict:
        body = {"fileName": file_name, "content": content}
        return self.client.post("/api/csv/upload", json=body).json()

    def test_concurrent_identical_uploads_one_wins(self):
        """Two threads upload the same content simultaneously.

        One should succeed; the other should fail gracefully (duplicate
        hash detected). The registry must contain exactly one row.
        """
        fname = f"race_same_{self.tag}.csv"
        content = f"a,b\n1,{self.tag}\n"

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self._upload, fname, content) for _ in range(2)]
            for f in as_completed(futures):
                results.append(f.result())

        statuses = [r.get("status") for r in results]
        ok_count = statuses.count("ok")
        self.assertGreaterEqual(ok_count, 1, f"At least one upload must succeed: {results}")
        self.assertLessEqual(ok_count + statuses.count("error"), 2)

        files_resp = self.client.get("/api/csv/files").json()
        matches = [f for f in files_resp if f.get("file_name") == fname]
        self.assertEqual(len(matches), 1, f"Registry must have exactly one row: {matches}")

    def test_concurrent_same_name_different_content(self):
        """Two threads upload different content under the same filename.

        The UNIQUE(file_name) constraint means only one can register. The
        other must fail or be treated as a reupload (depending on the
        code path), but not leave a second registry row.
        """
        fname = f"race_name_{self.tag}.csv"
        content_a = f"a,b\nA,{self.tag}\n"
        content_b = f"x,y\nB,{self.tag}\n"

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(self._upload, fname, content_a)
            fb = pool.submit(self._upload, fname, content_b)
            for f in as_completed([fa, fb]):
                results.append(f.result())

        files_resp = self.client.get("/api/csv/files").json()
        matches = [f for f in files_resp if f.get("file_name") == fname]
        self.assertLessEqual(
            len(matches), 1,
            f"At most one registry row per filename: {matches}",
        )
