"""Deduplication and naming (M5, #109; BR-28..31; decisions 2 and 3).

- A repeated filename is the next version of its dataset (csv_<slug>_v<n>), never an overwrite.
- The same bytes twice in one tenant are refused; another tenant, or a request with no session,
  has its own registry.
- Rows already in an earlier version are loaded but flagged; the user decides per row.
- A new version is compared with the previous one's columns. Nothing destructive happens.

Integration classes need a live PostgreSQL and fail (never skip) without one.
"""

from __future__ import annotations

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
from api.services import accounts
from api.services.dynamic_loader import dataset_slug
from api.tenancy import migrate_tenant, schema_for

_HELP = "Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)."


@pytest.mark.unit
class DatasetSlug(unittest.TestCase):
    def test_slug_is_lower_ascii_without_extension(self):
        self.assertEqual(dataset_slug("Sales Report 2026.CSV"), "sales_report_2026")
        self.assertEqual(dataset_slug("a-b__c.csv"), "a_b_c")

    def test_hostile_names_cannot_escape_the_prefix_or_the_identifier_rules(self):
        self.assertEqual(dataset_slug('../etc/passwd".csv'), "etc_passwd")
        self.assertEqual(dataset_slug("x; DROP TABLE csv_files;--.csv"), "x_drop_table_csv_files")

    def test_empty_or_non_ascii_names_fall_back(self):
        self.assertEqual(dataset_slug("!!!.csv"), "dataset")
        self.assertEqual(dataset_slug("数据.csv"), "dataset")

    def test_long_names_are_truncated_without_a_trailing_underscore(self):
        slug = dataset_slug("a" * 39 + " b" * 10 + ".csv")
        self.assertLessEqual(len(slug), 40)
        self.assertFalse(slug.endswith("_"))
        self.assertLessEqual(len(f"csv_{slug}_v999999"), 63, "must fit a PostgreSQL identifier")


@pytest.mark.integration
class VersionedDatasets(unittest.TestCase):
    """Default schema, no session: the same rules apply to a request with no session."""

    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True  # tearDown deletes what each test made
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        settings.allow_destructive = cls._orig_allow_destructive

    def setUp(self):
        self.tag = f"vd_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.headers: dict = {}

    def tearDown(self):
        for f in self.client.get("/api/csv/files", headers=self.headers).json():
            if self.tag in f["file_name"]:
                self.client.delete(f"/api/csv/files/{f['id']}", headers=self.headers)

    def up(self, name: str, content: str, **extra) -> dict:
        res = self.client.post("/api/csv/upload", headers=self.headers,
                               json={"fileName": f"{self.tag}_{name}", "content": content, **extra})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def files(self) -> list[dict]:
        return [f for f in self.client.get("/api/csv/files", headers=self.headers).json() if self.tag in f["file_name"]]

    def rows(self, table: str) -> list[dict]:
        res = self.client.get(f"/api/csv/tables/{table}/rows", headers=self.headers)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["rows"]

    # -- BR-28: exact-file dedup ------------------------------------------------

    def test_repeating_the_same_file_is_refused_and_adds_nothing(self):
        self.assertEqual(self.up("a.csv", "k,v\n1,x\n")["status"], "ok")
        again = self.up("a.csv", "k,v\n1,x\n")
        self.assertEqual(again["status"], "duplicate_file")
        self.assertEqual(again["reason"], "content")
        self.assertEqual(len(self.files()), 1)

    def test_the_same_bytes_under_another_name_are_still_a_duplicate(self):
        self.up("a.csv", "k,v\n1,x\n")
        self.assertEqual(self.up("b.csv", "k,v\n1,x\n")["status"], "duplicate_file")

    # -- BR-30: versioned datasets ---------------------------------------------

    def test_same_name_different_content_becomes_versions_and_keeps_every_table(self):
        v1 = self.up("sales.csv", "k,v\n1,a\n")
        v2 = self.up("sales.csv", "k,v\n1,b\n")
        v3 = self.up("sales.csv", "k,v\n1,c\n")
        self.assertEqual([r["status"] for r in (v1, v2, v3)], ["ok"] * 3)
        self.assertEqual([r["version"] for r in (v1, v2, v3)], [1, 2, 3])
        self.assertEqual(v2["tableName"], f"csv_{dataset_slug(self.tag + '_sales.csv')}_v2")
        self.assertEqual([self.rows(r["tableName"])[0]["v"] for r in (v1, v2, v3)], ["a", "b", "c"],
                         "an earlier version's rows must be exactly what was uploaded")
        self.assertEqual(len(self.files()), 3)

    def test_overwrite_is_never_honoured(self):
        v1 = self.up("o.csv", "k,v\n1,a\n")
        v2 = self.up("o.csv", "k,v\n1,b\n", overwrite=True)
        self.assertEqual(v2["version"], 2)
        self.assertFalse(v2["overwritten"])
        self.assertEqual(self.rows(v1["tableName"])[0]["v"], "a")

    def test_filenames_with_one_slug_are_one_dataset(self):
        a = self.up("My Data.csv", "k\n1\n")
        b = self.up("my_data.csv", "k\n2\n")
        self.assertEqual(a["dataset"], b["dataset"])
        self.assertEqual((a["version"], b["version"]), (1, 2))

    def test_a_filename_cannot_name_a_registry_table(self):
        # A bare slug would collide with the uploads registry; the csv_ prefix and _v<n> suffix prevent it.
        res = self.client.post("/api/csv/upload", headers=self.headers,
                               json={"fileName": "uploads.csv", "content": f"k\n{self.tag}\n"})
        body = res.json()
        self.assertEqual(body["status"], "ok", body)
        self.addCleanup(self.client.delete, f"/api/csv/files/{body['fileId']}", headers=self.headers)
        self.assertEqual(body["tableName"], "csv_uploads_v1")
        self.assertEqual(self.client.get("/api/csv/uploads", headers=self.headers).status_code, 200)

    def test_deleting_one_version_leaves_the_others(self):
        v1 = self.up("d.csv", "k\n1\n")
        v2 = self.up("d.csv", "k\n2\n")
        self.client.delete(f"/api/csv/files/{v1['fileId']}", headers=self.headers)
        self.assertEqual(self.rows(v2["tableName"])[0]["k"], "2")
        self.assertEqual([f["table_name"] for f in self.files()], [v2["tableName"]])

    # -- BR-31: schema compatibility -------------------------------------------

    def test_first_version_has_nothing_to_compare_with(self):
        self.assertIsNone(self.up("s.csv", "a,b\n1,2\n")["schemaCheck"])

    def test_added_column_is_compatible(self):
        self.up("s.csv", "a,b\n1,2\n")
        check = self.up("s.csv", "a,b,c\n1,2,3\n")["schemaCheck"]
        self.assertTrue(check["compatible"], check)
        self.assertEqual((check["added"], check["removed"], check["changed"]), (["c"], [], []))
        self.assertEqual(check["comparedTo"]["version"], 1)

    def test_removed_or_retyped_column_is_reported_and_nothing_is_altered(self):
        v1 = self.up("s.csv", "a,b\n1,2\n", types=["int8", "text"])
        check = self.up("s.csv", "a\nx\n", types=["text"])["schemaCheck"]
        self.assertFalse(check["compatible"])
        self.assertEqual(check["removed"], ["b"])
        self.assertEqual(check["changed"], [{"column": "a", "was": "int8", "now": "text"}])
        self.assertEqual(sorted(k for k in self.rows(v1["tableName"])[0] if not k.startswith("_")), ["a", "b"])

    # -- BR-29: cross-upload duplicate rows ------------------------------------

    def test_rows_in_an_earlier_version_are_loaded_flagged_and_counted(self):
        self.up("r.csv", "k,v\n1,a\n2,b\n")
        v2 = self.up("r.csv", "k,v\n2,b\n3,c\n4,d\n")
        self.assertEqual(v2["insertedRows"], 3, "flag policy: the rows still load")
        self.assertEqual(v2["duplicateRowsAcrossUploads"], 1)
        [flag] = v2["crossUploadDuplicates"]
        self.assertEqual((flag["rowNumber"], flag["matchedVersion"]), (1, 1))
        self.assertNotIn("_duplicateFlags", v2, "the private full list is stored, not returned")

    def test_the_newest_matching_version_is_named(self):
        self.up("n.csv", "k\nx\n")
        self.up("n.csv", "k\nx\ny\n")
        v3 = self.up("n.csv", "k\nx\nz\n")
        self.assertEqual([(f["rowNumber"], f["matchedVersion"]) for f in v3["crossUploadDuplicates"]], [(1, 2)])

    def test_in_file_duplicates_are_not_cross_upload_flags(self):
        self.up("w.csv", "k\n1\n")
        v2 = self.up("w.csv", "k\n9\n9\n")
        self.assertEqual((v2["duplicateRowsSkipped"], v2["duplicateRowsAcrossUploads"]), (1, 0))

    def test_unrelated_datasets_are_never_compared(self):
        self.up("p.csv", "k\n1\n")
        self.assertEqual(self.up("q.csv", "k\n1\nextra\n")["duplicateRowsAcrossUploads"], 0)

    def test_the_user_decides_per_row_through_review(self):
        self.up("rv.csv", "k,v\n1,a\n2,b\n")
        v2 = self.up("rv.csv", "k,v\n2,b\n3,c\n")
        review = f"/api/csv/uploads/{v2['uploadId']}/rows"
        before = self.client.get(review, headers=self.headers).json()["rows"]
        self.assertEqual(before[0]["duplicateOfEarlierVersion"]["version"], 1)
        self.assertIsNone(before[1]["duplicateOfEarlierVersion"])
        self.assertEqual(before[0]["decision"], "include", "a flag does not decide anything by itself")
        res = self.client.put(f"{review[:-5]}/rows/1/decision", headers=self.headers,
                              json={"decision": "exclude", "reason": "already loaded in v1"})
        self.assertEqual(res.status_code, 200, res.text)
        after = self.client.get(review, headers=self.headers).json()["rows"][0]
        self.assertEqual(after["decision"], "exclude")
        self.assertIsNotNone(after["duplicateOfEarlierVersion"])

    def test_flags_are_insert_only(self):
        self.up("io.csv", "k\n1\n")
        v2 = self.up("io.csv", "k\n1\n2\n")
        with Conn() as conn, conn.cursor() as cur:
            for statement in ("UPDATE {}.row_flags SET matched_version = 9 WHERE upload_id = %s",
                              "DELETE FROM {}.row_flags WHERE upload_id = %s"):
                with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(sql.SQL(statement).format(sql.Identifier(settings.UPLOADS_SCHEMA)), (int(v2["uploadId"]),))
                conn.rollback()

    # -- T&E loads share the registry ------------------------------------------

    def test_a_te_load_with_a_datasets_name_does_not_touch_its_versions(self):
        v1 = self.up("t.csv", "k\n1\n")
        v2 = self.up("t.csv", "k\n2\n")
        org = f"{self.tag}_org"
        te = self.client.post("/api/csv/upload", headers=self.headers, json={
            "fileName": f"{self.tag}_t.csv", "mode": "te", "targetTable": "organisations",
            "content": f"name,org_type,country\n{org},government,AU\n"}).json()
        self.assertEqual(te["status"], "ok", te)
        self.addCleanup(self._drop_org, org)
        self.assertEqual(sorted(f["mode"] for f in self.files()), ["dynamic", "dynamic", "te"])
        self.assertEqual(self.rows(v1["tableName"])[0]["k"], "1")
        self.assertEqual(self.rows(v2["tableName"])[0]["k"], "2")

    def _drop_org(self, name: str) -> None:
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}.organisations WHERE name = %s").format(
                sql.Identifier(settings.TE_SCHEMA)), (name,))
            conn.commit()


@pytest.mark.integration
class VersionsArePerTenant(unittest.TestCase):
    """Versions and exact-file dedup live in each tenant's own registry."""

    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None
        cls.slug = f"ver_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        pw = "correct horse battery staple"
        with Conn() as conn, conn.cursor() as cur:
            tid = accounts.create_tenant(cur, cls.slug, "Versions")
            uid = accounts.create_user(cur, f"{cls.slug}_user", pw)
            accounts.add_membership(cur, uid, tid, "tenant_admin")
            conn.commit()
        migrate_tenant(cls.slug)
        res = cls.client.post("/api/auth/login", json={"tenant": cls.slug, "username": f"{cls.slug}_user", "password": pw})
        assert res.status_code == 200, res.text
        cls.auth = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(cls.slug))))
            control = sql.Identifier(settings.CONTROL_SCHEMA)
            cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(control), (cls.slug,))
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE username = %s").format(control), (f"{cls.slug}_user",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def up(self, name: str, content: str, auth: bool) -> dict:
        res = self.client.post("/api/csv/upload", headers=self.auth if auth else {},
                               json={"fileName": name, "content": content})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_versions_and_dedup_are_independent_per_tenant_and_without_a_session(self):
        name = f"pt_{uuid.uuid4().hex[:8]}.csv"
        self.addCleanup(self._purge_default_registry, name)
        body = f"k,v\n1,{uuid.uuid4().hex}\n"
        tenant_v1 = self.up(name, body, auth=True)
        self.assertEqual(tenant_v1["version"], 1)
        self.assertEqual(self.up(name, body, auth=True)["status"], "duplicate_file")
        # The same file with no session is a different registry: not a duplicate, and its own v1.
        nosession = self.up(name, body, auth=False)
        self.assertEqual((nosession["status"], nosession["version"]), ("ok", 1), nosession)
        # ...where a repeat of the same bytes is refused too.
        self.assertEqual(self.up(name, body, auth=False)["status"], "duplicate_file")
        # A new version in the tenant doesn't move the other registry's numbering.
        self.assertEqual(self.up(name, body + "2,x\n", auth=True)["version"], 2)
        self.assertEqual(self.up(name, body + "3,y\n", auth=False)["version"], 2)

    def _purge_default_registry(self, name: str) -> None:
        for f in self.client.get("/api/csv/files").json():
            if f["file_name"] == name:
                self.client.delete(f"/api/csv/files/{f['id']}")
