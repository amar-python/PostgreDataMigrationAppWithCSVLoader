"""Confirmed header renames reach the database column names (#186)."""

from __future__ import annotations

import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.csv_parse import apply_header_mapping

_HELP = ("Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/"
         "PGPASSWORD/PGDATABASE). See scripts/start-api.ps1.")


@pytest.mark.unit
class ApplyHeaderMapping(unittest.TestCase):
    def test_no_mapping_returns_headers_unchanged(self):
        self.assertEqual(apply_header_mapping(["a", "b"], None), (["a", "b"], None))
        self.assertEqual(apply_header_mapping(["a", "b"], []), (["a", "b"], None))

    def test_rename_replaces_only_the_named_header(self):
        out, err = apply_header_mapping(["foo", "baz"], [{"original": "foo", "renamed": "bar"}])
        self.assertEqual((out, err), (["bar", "baz"], None))

    def test_blank_rename_keeps_the_original(self):
        out, err = apply_header_mapping(
            ["foo", "baz"],
            [{"original": "foo", "renamed": ""}, {"original": "baz", "renamed": "  "}],
        )
        self.assertEqual((out, err), (["foo", "baz"], None))

    def test_unknown_original_is_rejected(self):
        out, err = apply_header_mapping(["foo"], [{"original": "nope", "renamed": "bar"}])
        self.assertEqual(out, ["foo"])
        self.assertIn('"nope"', err)

    def test_original_listed_twice_is_rejected(self):
        _, err = apply_header_mapping(
            ["foo"], [{"original": "foo", "renamed": "a"}, {"original": "foo", "renamed": "b"}])
        self.assertIn("more than once", err)

    def test_rename_colliding_with_an_untouched_column_is_rejected(self):
        out, err = apply_header_mapping(["foo", "bar"], [{"original": "foo", "renamed": "bar"}])
        self.assertEqual(out, ["foo", "bar"])
        self.assertIn('"bar"', err)

    def test_collision_is_judged_after_sanitising(self):
        _, err = apply_header_mapping(["foo", "bar"], [{"original": "foo", "renamed": "BAR!"}])
        self.assertIsNotNone(err)

    def test_swapping_two_names_is_allowed(self):
        out, err = apply_header_mapping(
            ["a", "b"], [{"original": "a", "renamed": "b"}, {"original": "b", "renamed": "a"}])
        self.assertEqual((out, err), (["b", "a"], None))


@pytest.mark.integration
class HeaderMappingOverTheApi(unittest.TestCase):
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
        body = {"fileName": f"hdrmap_{self.tag}.csv", "content": content, **extra}
        return self.client.post("/api/csv/upload", json=body).json()

    def test_renamed_header_becomes_the_database_column(self):
        res = self._upload(
            f"foo,baz\n1,{self.tag}\n",
            headerMapping=[{"original": "foo", "renamed": "bar"}, {"original": "baz", "renamed": ""}],
        )
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(res["columns"], ["bar", "baz"])

        rows = self.client.get(f"/api/csv/tables/{res['tableName']}/rows").json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertIn("bar", rows[0])
        self.assertNotIn("foo", rows[0])
        self.assertEqual(rows[0]["bar"], "1")

        files = self.client.get("/api/csv/files").json()
        registered = next(f for f in files if f["table_name"] == res["tableName"])
        self.assertEqual(registered["column_names"], ["bar", "baz"])

    def test_upload_without_a_mapping_keeps_csv_headers(self):
        res = self._upload(f"foo,baz\n1,{self.tag}\n")
        self.assertEqual((res["status"], res["columns"]), ("ok", ["foo", "baz"]))

    def test_mapping_for_a_header_not_in_the_file_is_an_error_and_loads_nothing(self):
        res = self._upload(
            f"foo,baz\n1,{self.tag}\n",
            headerMapping=[{"original": "missing", "renamed": "bar"}],
        )
        self.assertEqual((res["status"], res["reason"]), ("error", "invalid_header_mapping"))
        files = self.client.get("/api/csv/files").json()
        self.assertFalse([f for f in files if f["file_name"] == f"hdrmap_{self.tag}.csv"])

    def test_rename_that_collides_with_another_column_is_an_error(self):
        res = self._upload(
            f"foo,bar\n1,{self.tag}\n",
            headerMapping=[{"original": "foo", "renamed": "bar"}],
        )
        self.assertEqual((res["status"], res["reason"]), ("error", "invalid_header_mapping"))

    def test_te_mode_rejects_a_header_mapping_instead_of_ignoring_it(self):
        resp = self.client.post("/api/csv/upload", json={
            "fileName": f"hdrmap_te_{self.tag}.csv",
            "content": "a,b\n1,2\n",
            "mode": "te",
            "targetTable": "organisations",
            "headerMapping": [{"original": "a", "renamed": "b"}],
        })
        self.assertEqual(resp.status_code, 422)
        self.assertIn("dynamic", resp.json()["detail"])
