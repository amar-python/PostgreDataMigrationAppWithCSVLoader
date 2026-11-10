"""Filtered audit reports, upload failure reasons, and data classification (M7, #111; BR-35, BR-37; decision 7).

Integration classes need a live PostgreSQL and fail (never skip) without one.
"""

from __future__ import annotations

import csv
import io
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api import policy
from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts
from api.services.reports import csv_cell, csv_text, like_pattern
from api.tenancy import migrate_tenant, schema_for

_HELP = "Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)."
_PW = "correct horse battery staple"


@pytest.mark.unit
class CsvHelpers(unittest.TestCase):
    def test_formulas_are_neutralised_but_plain_numbers_and_text_are_not(self):
        for cell in ("=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tx", "\rx", '=HYPERLINK("http://x")'):
            self.assertEqual(csv_cell(cell), "'" + cell, cell)
        for cell in ("-5", "+3.2", "42", "plain", "a=b", "", None):
            self.assertEqual(csv_cell(cell), "" if cell is None else cell, cell)

    def test_csv_text_quotes_and_neutralises_every_cell(self):
        text = csv_text(["a", "b"], [["=x", 'say "hi", ok'], [None, 7]])
        self.assertEqual(list(csv.reader(io.StringIO(text))), [["a", "b"], ["'=x", 'say "hi", ok'], ["", "7"]])

    def test_like_pattern_matches_percent_and_underscore_literally(self):
        self.assertEqual(like_pattern("a_b%c\\d"), "%a\\_b\\%c\\\\d%")


@pytest.mark.unit
class PolicyConfig(unittest.TestCase):
    def test_the_design_target_and_seven_years_are_the_defaults(self):
        self.assertEqual((settings.DATA_CLASSIFICATION, settings.AUDIT_RETENTION_YEARS), ("OFFICIAL: Sensitive", 7))
        policy.check_config(settings.DATA_CLASSIFICATION, settings.AUDIT_RETENTION_YEARS)

    def test_a_deployment_can_lower_the_classification_or_lengthen_retention(self):
        for classification in ("UNOFFICIAL", "OFFICIAL", "OFFICIAL: Sensitive"):
            policy.check_config(classification, 10)

    def test_protected_is_refused_with_the_reason(self):
        with self.assertRaisesRegex(RuntimeError, "PROTECTED.*IRAP"):
            policy.check_config("PROTECTED", 7)

    def test_unknown_classifications_and_short_retention_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "must be one of"):
            policy.check_config("secret", 7)
        with self.assertRaisesRegex(RuntimeError, "at least 1"):
            policy.check_config("OFFICIAL", 0)


@pytest.mark.integration
class StartupRefusesBadPolicy(unittest.TestCase):
    def test_the_api_will_not_start_with_protected(self):
        with patch.object(settings, "DATA_CLASSIFICATION", "PROTECTED"):
            with self.assertRaisesRegex(RuntimeError, "PROTECTED"):
                with TestClient(app):
                    pass


class _Base(unittest.TestCase):
    """One tenant with an uploader, a tenant admin and an auditor."""

    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None
        cls.slug = f"rep_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        roles = {"up": "uploader", "ad": "tenant_admin", "au": "auditor"}
        with Conn() as conn, conn.cursor() as cur:
            tid = accounts.create_tenant(cur, cls.slug, "Reports")
            for who, role in roles.items():
                accounts.add_membership(cur, accounts.create_user(cur, f"{cls.slug}_{who}", _PW), tid, role)
            conn.commit()
        migrate_tenant(cls.slug)
        cls.auth = {}
        for who in roles:
            res = cls.client.post("/api/auth/login", json={
                "tenant": cls.slug, "username": f"{cls.slug}_{who}", "password": _PW})
            assert res.status_code == 200, res.text
            cls.auth[who] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        control = sql.Identifier(settings.CONTROL_SCHEMA)
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(cls.slug))))
            cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(control), (cls.slug,))
            cur.execute(sql.SQL("DELETE FROM {}.users WHERE username LIKE %s").format(control), (f"{cls.slug}_%",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]

    def upload(self, who, name, content, **extra):
        res = self.client.post("/api/csv/upload", headers=self.auth[who],
                               json={"fileName": f"{self.tag}_{name}", "content": content, **extra})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def events(self, who="au", **params):
        res = self.client.get("/api/audit/events", headers=self.auth[who], params={"file": self.tag, **params})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()


@pytest.mark.integration
class FilteredAuditReport(_Base):
    def setUp(self):
        super().setUp()
        a = self.upload("up", "first.csv", f"k\n{self.tag}1\n")
        self.upload("ad", "second.csv", f"k\n{self.tag}2\n")
        self.client.delete(f"/api/csv/files/{a['fileId']}", headers=self.auth["ad"])

    def test_filters_by_actor_and_action_and_combines_them(self):
        up = f"{self.slug}_up"
        self.assertEqual({e["actor"] for e in self.events(actor=up)["entries"]}, {up})
        self.assertEqual({e["action"] for e in self.events(action="delete")["entries"]}, {"delete"})
        both = self.events(actor=f"{self.slug}_ad", action="upload")["entries"]
        self.assertEqual([(e["actor"], e["action"]) for e in both], [(f"{self.slug}_ad", "upload")])

    def test_file_filter_is_a_case_insensitive_contains_with_literal_wildcards(self):
        self.assertEqual(len(self.events(file=f"{self.tag}_SECOND")["entries"]), 1)
        # "_" and "%" in the filter match themselves, not "any character".
        self.assertEqual(self.events(file=f"{self.tag}%")["total"], 0)
        self.assertEqual(self.events(file=f"{self.tag}_firs_")["total"], 0)

    def test_time_window_is_from_inclusive_to_exclusive_and_accepts_a_date(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self.events(**{"from": (now + timedelta(hours=1)).isoformat()})["total"], 0)
        self.assertEqual(self.events(**{"to": (now - timedelta(hours=1)).isoformat()})["total"], 0)
        everything = self.events(**{"from": (now - timedelta(hours=1)).isoformat(),
                                    "to": (now + timedelta(hours=1)).isoformat()})["total"]
        self.assertEqual(everything, 3)
        self.assertEqual(self.events(**{"from": "2020-01-01"})["total"], 3)

    def test_entries_are_newest_first_with_before_and_after_and_paginate(self):
        page = self.events()
        self.assertEqual((page["total"], [e["action"] for e in page["entries"]]), (3, ["delete", "upload", "upload"]))
        self.assertEqual(page["entries"][0]["before"] is None, page["entries"][0]["after"] is None)
        second = self.events(limit=1, offset=1)
        self.assertEqual((second["total"], second["limit"], len(second["entries"])), (3, 1, 1))
        self.assertEqual(second["entries"][0]["id"], page["entries"][1]["id"])

    def test_an_unknown_action_is_a_422_not_an_empty_report(self):
        res = self.client.get("/api/audit/events", headers=self.auth["au"], params={"action": "nope"})
        self.assertEqual(res.status_code, 422, res.text)

    def test_only_roles_that_may_read_the_audit_log_can_read_the_report(self):
        self.assertEqual(self.client.get("/api/audit/events", headers=self.auth["up"]).status_code, 403)
        self.assertEqual(self.client.get("/api/audit/events", headers=self.auth["ad"]).status_code, 200)

    def test_a_tenant_sees_only_its_own_events(self):
        no_session = self.client.get("/api/audit/events", params={"file": self.tag}).json()
        self.assertEqual(no_session["total"], 0)

    def test_csv_export_matches_the_filter_and_carries_the_marking(self):
        res = self.client.get("/api/audit/events", headers=self.auth["au"],
                              params={"file": self.tag, "action": "upload", "format": "csv"})
        self.assertEqual((res.status_code, res.headers["content-type"].split(";")[0]), (200, "text/csv"))
        self.assertEqual(res.headers["x-data-classification"], settings.DATA_CLASSIFICATION)
        self.assertEqual(res.headers["x-total-count"], "2")
        rows = list(csv.DictReader(io.StringIO(res.text)))
        self.assertEqual([r["action"] for r in rows], ["upload", "upload"])
        self.assertEqual(list(rows[0]), ["id", "performed_at", "actor", "action", "file_id", "file_name", "table_name",
                                         "mode", "before_value", "after_value"])

    def test_csv_export_neutralises_formulas_in_user_supplied_names(self):
        name = f'={self.tag}_HYPERLINK("http://example.invalid")'
        res = self.client.post("/api/csv/upload", headers=self.auth["ad"], json={
            "fileName": name, "content": f"k\n{self.tag}3\n"})
        self.assertEqual(res.json()["status"], "ok", res.text)
        report = self.client.get("/api/audit/events", headers=self.auth["au"],
                                 params={"file": f"{self.tag}_HYPERLINK", "format": "csv"})
        [row] = list(csv.DictReader(io.StringIO(report.text)))
        self.assertEqual(row["file_name"], "'" + name)


@pytest.mark.integration
class UploadFailureReasons(_Base):
    def test_every_outcome_can_be_filtered_and_failures_say_why(self):
        self.upload("up", "good.csv", f"k\n{self.tag}\n")
        self.upload("up", "dup.csv", f"k\n{self.tag}\n")                                    # duplicate
        self.upload("up", "bad.csv", f"n\nx{self.tag}\n", types=["int8"])                   # every row fails
        self.upload("ad", "empty.csv", "only,a,header\n")                                   # rejected
        res = self.client.get("/api/csv/uploads", headers=self.auth["au"], params={"file": self.tag})
        self.assertEqual(res.status_code, 200, res.text)
        by_status = {u["status"]: u for u in res.json()}
        self.assertEqual(set(by_status), {"imported", "duplicate", "failed", "rejected"})
        self.assertIsNone(by_status["imported"]["failure_reason"])
        self.assertIn("None of the 1 rows could be imported", by_status["failed"]["failure_reason"])
        self.assertIn("matches existing file", by_status["duplicate"]["failure_reason"])
        self.assertIn("no data rows", by_status["rejected"]["failure_reason"])

    def test_filters_combine(self):
        self.upload("up", "a.csv", f"k\n{self.tag}a\n")
        self.upload("ad", "b.csv", f"k\n{self.tag}b\n")
        listing = lambda **p: self.client.get("/api/csv/uploads", headers=self.auth["au"],  # noqa: E731
                                              params={"file": self.tag, **p}).json()
        self.assertEqual(len(listing()), 2)
        self.assertEqual([u["uploader"] for u in listing(uploader=f"{self.slug}_ad")], [f"{self.slug}_ad"])
        self.assertEqual(len(listing(status="imported")), 2)
        self.assertEqual(listing(status="failed"), [])
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.assertEqual(listing(**{"from": future}), [])
        self.assertEqual(len(listing(**{"to": future})), 2)
        self.assertEqual(self.client.get("/api/csv/uploads", headers=self.auth["au"],
                                         params={"status": "bogus"}).status_code, 422)


@pytest.mark.integration
class ClassificationMarking(_Base):
    def test_the_policy_is_readable_by_every_role_and_without_a_session(self):
        for headers in (self.auth["up"], self.auth["au"], {}):
            res = self.client.get("/api/policy", headers=headers)
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json(), {"classification": "OFFICIAL: Sensitive", "auditRetentionYears": 7})

    def test_every_api_area_marks_its_responses(self):
        up = self.upload("up", "mark.csv", f"k\n{self.tag}\n")
        calls = [
            self.client.get("/api/policy", headers=self.auth["up"]),
            self.client.get("/api/csv/files", headers=self.auth["up"]),
            self.client.get("/api/csv/uploads", headers=self.auth["up"]),
            self.client.get(f"/api/csv/uploads/{up['uploadId']}/rows", headers=self.auth["up"]),
            self.client.get(f"/api/csv/uploads/{up['uploadId']}/workflow", headers=self.auth["up"]),
            self.client.get("/api/te/tables", headers=self.auth["up"]),
            self.client.get("/api/audit/log", headers=self.auth["au"]),
            self.client.get("/api/audit/events", headers=self.auth["au"]),
            self.client.get(f"/api/csv/uploads/{up['uploadId']}/original", headers=self.auth["up"]),  # own Response
        ]
        for res in calls:
            with self.subTest(url=str(res.url)):
                self.assertEqual(res.status_code, 200, res.text)
                self.assertEqual(res.headers[policy.HEADER], "OFFICIAL: Sensitive")

    def test_the_marking_follows_the_deployment_setting(self):
        with patch.object(settings, "DATA_CLASSIFICATION", "OFFICIAL"), patch.object(settings, "AUDIT_RETENTION_YEARS", 10):
            res = self.client.get("/api/policy", headers=self.auth["up"])
            self.assertEqual((res.headers[policy.HEADER], res.json()["auditRetentionYears"]), ("OFFICIAL", 10))
            self.assertEqual(self.client.get("/api/audit/events", headers=self.auth["au"]).json()["classification"],
                             "OFFICIAL")

    def test_a_browser_can_read_the_marking(self):
        res = self.client.get("/api/policy", headers={"Origin": "http://localhost:5173"})
        self.assertIn("x-data-classification", res.headers["access-control-expose-headers"].lower())
