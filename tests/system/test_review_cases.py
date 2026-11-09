"""Positive and negative test cases for the review API (M4a, #108).

Each test names its case ID from docs/test-cases/M4-review.md. Cases already
covered elsewhere are mapped in that document; this file holds the rest.

Integration: needs a live PostgreSQL. Fails (never skips) without one. Two
throwaway tenants with one member per role; dropped afterwards.
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
from api.services.accounts import ROLES
from api.tenancy import migrate_tenant, schema_for

_PW = "review case passphrase"


@pytest.mark.integration
class ReviewCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.tenants = {"a": f"rca_{tag}", "b": f"rcb_{tag}"}
        cls.users: dict[tuple[str, str], str] = {}
        with Conn() as conn:
            with conn.cursor() as cur:
                for key, slug in cls.tenants.items():
                    tid = accounts.create_tenant(cur, slug, f"Review cases {key}")
                    for role in ROLES:
                        name = f"{slug}_{role}"
                        accounts.add_membership(cur, accounts.create_user(cur, name, _PW), tid, role)
                        cls.users[(key, role)] = name
            conn.commit()
        cls.headers = {}
        for key, slug in cls.tenants.items():
            migrate_tenant(slug)
            for role in ROLES:
                res = cls.client.post("/api/auth/login", json={
                    "tenant": slug, "username": cls.users[(key, role)], "password": _PW})
                assert res.status_code == 200, res.text
                cls.headers[(key, role)] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        with Conn() as conn:
            with conn.cursor() as cur:
                for slug in cls.tenants.values():
                    cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(slug))))
                    cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(
                        sql.Identifier(settings.CONTROL_SCHEMA)), (slug,))
                    cur.execute(sql.SQL("DELETE FROM {}.users WHERE username LIKE %s").format(
                        sql.Identifier(settings.CONTROL_SCHEMA)), (f"{slug}_%",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    # helpers -------------------------------------------------------------
    def _h(self, role: str = "tenant_admin", tenant: str = "a") -> dict:
        return self.headers[(tenant, role)]

    def _upload(self, content: str, types: list[str], tenant: str = "a") -> dict:
        tag = uuid.uuid4().hex[:10]
        return self.client.post("/api/csv/upload", headers=self._h(tenant=tenant), json={
            "fileName": f"case_{tag}.csv", "content": content.replace("{tag}", tag), "types": types}).json()

    def _three(self, tenant: str = "a") -> str:
        res = self._upload("n,t\n1,{tag}\nx,b\n3,c\n", ["int8", "text"], tenant)
        assert res["status"] == "ok", res
        return res["uploadId"]

    def _get(self, path: str, role: str = "tenant_admin", tenant: str = "a", **params):
        return self.client.get(path, headers=self._h(role, tenant), params=params)

    def _put(self, path: str, body: dict, role: str = "tenant_admin", tenant: str = "a"):
        return self.client.put(path, headers=self._h(role, tenant), json=body)

    def _decide(self, uid, row, decision="exclude", reason="case reason", role="tenant_admin", tenant="a"):
        return self._put(f"/api/csv/uploads/{uid}/rows/{row}/decision",
                         {"decision": decision, "reason": reason}, role, tenant)

    def _edit(self, uid, row, column, value, reason="case reason", role="tenant_admin", tenant="a"):
        return self._put(f"/api/csv/uploads/{uid}/rows/{row}/cells/{column}",
                         {"value": value, "reason": reason}, role, tenant)

    # positive ------------------------------------------------------------
    def test_P02_paging_bounds(self):
        uid = self._three()
        big = self._get(f"/api/csv/uploads/{uid}/rows", limit=10_000).json()
        self.assertEqual((big["limit"], len(big["rows"])), (500, 3))
        self.assertEqual(self._get(f"/api/csv/uploads/{uid}/rows", offset=3).json()["rows"], [])
        neg = self._get(f"/api/csv/uploads/{uid}/rows", offset=-5).json()
        self.assertEqual((neg["offset"], neg["rows"][0]["rowNumber"]), (0, 1))

    def test_P04_ragged_row_is_flagged(self):
        res = self._upload("a,b\n1,{tag}\n2,y,extra\n", ["text", "text"])
        row = self._get(f"/api/csv/uploads/{res['uploadId']}/rows").json()["rows"][1]
        self.assertEqual(row["errors"][0]["column"], "(beyond header)")
        self.assertIn("extra value(s) would be lost", row["errors"][0]["reason"])

    def test_P05_a_failed_upload_can_be_reviewed(self):
        res = self._upload("n\nbad_{tag}\nworse\n", ["int8"])
        self.assertEqual(res["status"], "error", res)
        uid = res["uploadId"]
        page = self._get(f"/api/csv/uploads/{uid}/rows").json()
        self.assertEqual((page["total"], [len(r["errors"]) for r in page["rows"]]), (2, [1, 1]))
        self.assertEqual(self._edit(uid, 1, "n", "1").json()["errors"], [])
        self.assertEqual(self._decide(uid, 2).json()["decision"], "exclude")

    def test_P08_an_edit_to_a_bad_value_is_flagged(self):
        uid = self._three()
        row = self._edit(uid, 1, "n", "one").json()
        self.assertEqual(row["errors"][0]["reason"], '"one" is not a whole number')

    def test_P09_edit_by_column_index_and_to_an_empty_value(self):
        uid = self._three()
        self.assertEqual(self._edit(uid, 1, "1", "renamed").json()["current"][1], "renamed")
        self.assertEqual(self._edit(uid, 3, "t", "").json()["current"], ["3", ""])

    def test_P10_reason_is_stored_trimmed(self):
        uid = self._three()
        self._decide(uid, 1, reason="   needs a second look   ")
        [entry] = self._get(f"/api/csv/uploads/{uid}/rows/1/history").json()
        self.assertEqual(entry["reason"], "needs a second look")

    def test_P11_actor_is_the_signed_in_user(self):
        uid = self._three()
        self._decide(uid, 1, role="reviewer")
        self._edit(uid, 2, "n", "2", role="tenant_admin")
        actors = {h["kind"]: h["actor"] for r in (1, 2)
                  for h in self._get(f"/api/csv/uploads/{uid}/rows/{r}/history").json()}
        self.assertEqual(actors, {"decision": self.users[("a", "reviewer")],
                                  "edit": self.users[("a", "tenant_admin")]})

    def test_P12_every_role_can_view_rows_and_history(self):
        uid = self._three()
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(self._get(f"/api/csv/uploads/{uid}/rows", role).status_code, 200)
                self.assertEqual(self._get(f"/api/csv/uploads/{uid}/rows/1/history", role).status_code, 200)

    # negative ------------------------------------------------------------
    def test_N05_row_numbers_outside_the_upload(self):
        uid = self._three()
        for row in (0, 4):
            with self.subTest(row=row):
                self.assertEqual(self._decide(uid, row).status_code, 404)
                self.assertEqual(self._edit(uid, row, "n", "9").status_code, 404)
                self.assertEqual(self._get(f"/api/csv/uploads/{uid}/rows/{row}/history").status_code, 404)

    def test_N06_column_index_out_of_range(self):
        uid = self._three()
        self.assertEqual(self._edit(uid, 1, "2", "x").status_code, 404)

    def test_N07_unknown_upload_on_every_route(self):
        for res in (self._decide(999_999_999, 1), self._edit(999_999_999, 1, "n", "1"),
                    self._get("/api/csv/uploads/999999999/rows/1/history")):
            with self.subTest(url=str(res.url)):
                self.assertEqual(res.status_code, 404)

    def test_N08_N09_uploader_and_auditor_cannot_change(self):
        uid = self._three()
        for role in ("uploader", "auditor"):
            with self.subTest(role=role):
                self.assertEqual(self._decide(uid, 1, role=role).status_code, 403)
                self.assertEqual(self._edit(uid, 1, "n", "5", role=role).status_code, 403)
        self.assertEqual(self._get(f"/api/csv/uploads/{uid}/rows/1/history").json(), [], "nothing recorded")

    def test_N10_an_invalid_session_is_refused(self):
        uid = self._three()
        bad = {"Authorization": "Bearer not-a-real-token"}
        self.assertEqual(self.client.get(f"/api/csv/uploads/{uid}/rows", headers=bad).status_code, 401)
        self.assertEqual(self.client.put(f"/api/csv/uploads/{uid}/rows/1/decision", headers=bad,
                                         json={"decision": "exclude", "reason": "x"}).status_code, 401)

    def test_N11_another_tenant_cannot_see_or_change_the_upload(self):
        uid = self._three(tenant="a")
        self.assertEqual(self._get(f"/api/csv/uploads/{uid}/rows", tenant="b").status_code, 404)
        self.assertEqual(self._decide(uid, 1, tenant="b").status_code, 404)
        self.assertEqual(self._edit(uid, 1, "n", "7", tenant="b").status_code, 404)
        page = self._get(f"/api/csv/uploads/{uid}/rows").json()
        self.assertEqual((page["excludedRows"], page["editedRows"]), (0, 0), "tenant a's upload is unchanged")

    def test_N12_missing_or_wrong_body_fields(self):
        uid = self._three()
        for path, body in ((f"/api/csv/uploads/{uid}/rows/1/decision", {"decision": "exclude"}),
                           (f"/api/csv/uploads/{uid}/rows/1/decision", {"reason": "r"}),
                           (f"/api/csv/uploads/{uid}/rows/1/cells/n", {"reason": "r"}),
                           (f"/api/csv/uploads/{uid}/rows/1/cells/n", {"value": 5, "reason": "r"})):
            with self.subTest(body=body):
                self.assertEqual(self._put(path, body).status_code, 422)

    def test_N13_review_tables_reject_update_delete_and_truncate(self):
        uid = self._three()
        self._decide(uid, 1)
        self._edit(uid, 2, "n", "2")
        s = sql.Identifier(schema_for(self.tenants["a"]))
        for statement in ("UPDATE {}.row_decisions SET reason = 'x'", "DELETE FROM {}.row_decisions",
                          "TRUNCATE {}.row_decisions", "UPDATE {}.cell_edits SET new_value = 'x'",
                          "DELETE FROM {}.cell_edits", "TRUNCATE {}.cell_edits"):
            with self.subTest(statement=statement), Conn() as conn, conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(sql.SQL(statement).format(s))
                conn.rollback()

    def test_N14_database_rejects_a_blank_reason(self):
        uid = self._three()
        s = sql.Identifier(schema_for(self.tenants["a"]))
        for statement, args in (
                ("INSERT INTO {}.row_decisions (upload_id, row_number, decision, reason) VALUES (%s, 1, 'exclude', ' ')",
                 (int(uid),)),
                ("INSERT INTO {}.cell_edits (upload_id, row_number, column_index, old_value, new_value, reason) "
                 "VALUES (%s, 1, 0, '1', '2', '')", (int(uid),))):
            with self.subTest(statement=statement[:40]), Conn() as conn, conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.CheckViolation):
                    cur.execute(sql.SQL(statement).format(s), args)
                conn.rollback()

    def test_N16_a_non_numeric_upload_id(self):
        self.assertEqual(self._get("/api/csv/uploads/abc/rows").status_code, 422)
