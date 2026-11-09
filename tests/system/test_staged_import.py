"""Approval and transactional staged import (M6, #110; BR-32, BR-33, BR-34; ADR-0002; decisions 4 and 5).

Integration classes need a live PostgreSQL and fail (never skip) without one.
"""

from __future__ import annotations

import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings
from api.db import Conn
from api.main import app
from api.services import accounts, staged_import
from api.services.staged_import import _copy_data, derive_state
from api.tenancy import migrate_tenant, schema_for

_HELP = "Start PostgreSQL and ensure api/ can reach it (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)."
_PW = "correct horse battery staple"


@pytest.mark.unit
class Helpers(unittest.TestCase):
    def test_copy_data_quotes_every_value_and_marks_only_none_as_null(self):
        text = _copy_data([(1, "plain", None), (2, 'say "hi", ok', "\\N"), (3, True, "multi\nline")]).read()
        self.assertEqual(text, '"1","plain",\\N\n"2","say ""hi"", ok","\\N"\n"3","true","multi\nline"\n')

    def test_state_is_derived_from_the_events(self):
        self.assertEqual(derive_state("staged", False, None, None), "staged")
        self.assertEqual(derive_state("imported", False, None, None), "legacy")
        self.assertEqual(derive_state("staged", False, 3, None), "submitted")
        self.assertEqual(derive_state("staged", False, 3, "approve"), "approved")
        self.assertEqual(derive_state("staged", False, 3, "reject"), "rejected")
        self.assertEqual(derive_state("staged", True, 3, "approve"), "imported")


class _Base(unittest.TestCase):
    """One tenant with an uploader, a reviewer and a tenant admin, plus the default (no-session) registry."""

    @classmethod
    def setUpClass(cls):
        cls._orig_allow_destructive = settings.allow_destructive
        settings.allow_destructive = True
        cls.ctx = TestClient(app)
        try:
            cls.client = cls.ctx.__enter__()
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"Could not start the API: {type(exc).__name__}: {exc}\n{_HELP}") from None
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.slugs = {"team": f"imp_t_{tag}", "solo": f"imp_s_{tag}"}
        roles = {"team": {"up": "uploader", "rv": "reviewer", "ad": "tenant_admin"}, "solo": {"ad": "tenant_admin"}}
        with Conn() as conn, conn.cursor() as cur:
            for key, slug in cls.slugs.items():
                tid = accounts.create_tenant(cur, slug, f"Import {key}")
                for who, role in roles[key].items():
                    accounts.add_membership(cur, accounts.create_user(cur, f"{slug}_{who}", _PW), tid, role)
            conn.commit()
        for slug in cls.slugs.values():
            migrate_tenant(slug)
        cls.auth: dict[str, dict] = {}
        for key, slug in cls.slugs.items():
            for who in roles[key]:
                res = cls.client.post("/api/auth/login", json={
                    "tenant": slug, "username": f"{slug}_{who}", "password": _PW})
                assert res.status_code == 200, res.text
                cls.auth[f"{key}_{who}"] = {"Authorization": f"Bearer {res.json()['token']}"}

    @classmethod
    def tearDownClass(cls):
        settings.allow_destructive = cls._orig_allow_destructive
        control = sql.Identifier(settings.CONTROL_SCHEMA)
        with Conn() as conn, conn.cursor() as cur:
            for slug in cls.slugs.values():
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(slug))))
                cur.execute(sql.SQL("DELETE FROM {}.tenants WHERE slug = %s").format(control), (slug,))
                cur.execute(sql.SQL("DELETE FROM {}.users WHERE username LIKE %s").format(control), (f"{slug}_%",))
            conn.commit()
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.tag = uuid.uuid4().hex[:10]
        self.one = f"k\n{self.tag}\n"   # content no other test stages: the same bytes twice in a tenant are a duplicate

    # -- API helpers; ``who`` is a key of cls.auth, or None for no session --------------------

    def _h(self, who):
        return self.auth[who] if who else {}

    def stage(self, who, name, content, expect=200, **extra):
        res = self.client.post("/api/csv/uploads", headers=self._h(who),
                               json={"fileName": f"{self.tag}_{name}", "content": content, **extra})
        self.assertEqual(res.status_code, expect, res.text)
        return res.json() if expect == 200 else res.json()["detail"]

    def post(self, who, upload, action, expect=200, **body):
        res = self.client.post(f"/api/csv/uploads/{upload}/{action}", headers=self._h(who), json=body or None)
        self.assertEqual(res.status_code, expect, res.text)
        return res.json() if expect == 200 else res.json()["detail"]

    def imp(self, who, upload, key="k1", expect=200):
        res = self.client.post(f"/api/csv/uploads/{upload}/import", headers={**self._h(who), "Idempotency-Key": key})
        self.assertEqual(res.status_code, expect, res.text)
        return res.json() if expect == 200 else res.json()["detail"]

    def state(self, who, upload) -> str:
        return self.client.get(f"/api/csv/uploads/{upload}/workflow", headers=self._h(who)).json()["state"]

    def decide(self, who, upload, row, decision="exclude", expect=200):
        res = self.client.put(f"/api/csv/uploads/{upload}/rows/{row}/decision", headers=self._h(who),
                              json={"decision": decision, "reason": "test"})
        self.assertEqual(res.status_code, expect, res.text)

    def edit(self, who, upload, row, column, value, expect=200):
        res = self.client.put(f"/api/csv/uploads/{upload}/rows/{row}/cells/{column}", headers=self._h(who),
                              json={"value": value, "reason": "test"})
        self.assertEqual(res.status_code, expect, res.text)

    def approved(self, content, name="a.csv", **extra) -> str:
        """An upload staged by the uploader, submitted, and approved by the reviewer."""
        up = self.stage("team_up", name, content, **extra)["uploadId"]
        self.post("team_up", up, "submit")
        self.post("team_rv", up, "approval", decision="approve")
        return up

    def registry(self, who, name_part=None) -> list[dict]:
        files = self.client.get("/api/csv/files", headers=self._h(who)).json()
        return [f for f in files if self.tag in f["file_name"]]

    def team_sql(self, query: str, params=()) -> list[tuple]:
        schema = schema_for(self.slugs["team"])
        with Conn() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL(query).format(s=sql.Identifier(schema)), params)
            return cur.fetchall()


@pytest.mark.integration
class ApprovalWorkflow(_Base):
    def test_stage_imports_nothing_and_the_whole_flow_reconciles(self):
        content = "k,v\n1,a\nx,b\n3,c\n4,d\n1,a\n6,e\n"
        staged_name = f"{self.tag}_flow.csv"
        staged = self.stage("team_up", "flow.csv", content, types=["int8", "text"])
        up = staged["uploadId"]
        self.assertEqual((staged["status"], staged["state"], staged["totalRows"]), ("staged", "staged", 6))
        self.assertEqual(self.registry("team_up"), [], "staging must not import anything")
        self.assertEqual(self.team_sql("SELECT count(*) FROM {s}.csv_files WHERE file_name LIKE %s",
                                       (f"{self.tag}%",))[0][0], 0)

        self.post("team_up", up, "submit", note="please review")
        self.assertEqual(self.state("team_up", up), "submitted")
        # Row 2 is invalid, so approval is refused until the reviewer deals with it.
        refused = self.post("team_rv", up, "approval", expect=422, decision="approve")
        self.assertEqual((refused["invalidRows"], refused["rowErrors"][0]["rowNumber"]), (1, 2))
        self.edit("team_rv", up, 2, "k", "2")        # fix an invalid cell
        self.decide("team_rv", up, 3)                # exclude a row
        self.edit("team_rv", up, 6, "v", "E")        # change a valid one
        approved = self.post("team_rv", up, "approval", decision="approve")
        self.assertEqual(approved["state"], "approved")
        self.assertEqual(self.registry("team_up"), [], "approving doesn't import either")

        result = self.imp("team_up", up)
        self.assertEqual(result["reconciliation"], {"rowsIn": 6, "excluded": 1, "edited": 2, "duplicate": 1, "imported": 4})
        self.assertEqual(self.state("team_up", up), "imported")
        self.assertEqual((result["dataset"], result["version"]), (staged["dataset"], 1))

        # The data: edits applied, exclusion dropped, duplicate skipped; lineage points back to source rows.
        rows = self.team_sql('SELECT k, v, _source_row_id, _import_id FROM {s}."' + result["tableName"] + '" ORDER BY _id')
        self.assertEqual([r[:3] for r in rows], [(1, "a", 1), (2, "b", 2), (4, "d", 4), (6, "E", 6)])
        self.assertEqual({r[3] for r in rows}, {int(result["importId"])})
        # The original is untouched, and the review page still shows both.
        page = self.client.get(f"/api/csv/uploads/{up}/rows", headers=self._h("team_up")).json()["rows"]
        self.assertEqual((page[5]["original"], page[5]["current"]), (["6", "e"], ["6", "E"]))
        # It is registered like any other file, with the uploader known.
        [entry] = self.registry("team_up")
        self.assertEqual((entry["uploader"], entry["row_count"], entry["total_rows"], entry["duplicate_rows_skipped"]),
                         (f"{self.slugs['team']}_up", 4, 6, 1))
        # Every step is in the audit log, in the same chain.
        actions = self.team_sql("SELECT action, actor FROM {s}.audit_log WHERE file_name = %s "
                                "AND action IN ('submit','approve','import') ORDER BY id", (staged_name,))
        self.assertEqual(actions, [("submit", f"{self.slugs['team']}_up"), ("approve", f"{self.slugs['team']}_rv"),
                                   ("import", f"{self.slugs['team']}_up")])
        self.assertTrue(self.client.get("/api/audit/verify", headers=self._h("team_ad")).json()["intact"])

    def test_reject_then_resubmit(self):
        up = self.stage("team_up", "rr.csv", "k\n1\nnot a number\n3\n", types=["int8"])["uploadId"]
        self.post("team_rv", up, "approval", expect=409, decision="approve")      # nothing submitted yet
        self.post("team_up", up, "submit")
        self.post("team_up", up, "submit", expect=409)                            # already submitted
        self.post("team_rv", up, "approval", expect=422, decision="reject")       # a reason is required
        rejected = self.post("team_rv", up, "approval", decision="reject", reason="row 2 is not a number")
        self.assertEqual(rejected["state"], "rejected")
        self.imp("team_up", up, expect=409)                                       # a rejected upload can't import
        self.decide("team_rv", up, 2)                                             # review reopens
        self.post("team_up", up, "submit", note="row 2 excluded")
        self.assertEqual(self.state("team_up", up), "submitted")
        self.post("team_rv", up, "approval", decision="approve")
        result = self.imp("team_up", up)
        self.assertEqual(result["reconciliation"]["imported"], 2)
        history = self.client.get(f"/api/csv/uploads/{up}/workflow", headers=self._h("team_up")).json()["history"]
        self.assertEqual([h["event"] for h in history], ["submitted", "rejected", "submitted", "approved", "imported"])

    def test_nothing_changes_once_approved(self):
        up = self.approved(f"k,v\n1,a\n2,{self.tag}\n")
        self.decide("team_rv", up, 1, expect=409)
        self.edit("team_rv", up, 1, "v", "z", expect=409)
        self.imp("team_up", up)
        self.decide("team_rv", up, 1, expect=409)

    def test_import_needs_an_approval_and_a_key(self):
        up = self.stage("team_up", "gate.csv", self.one)["uploadId"]
        self.imp("team_up", up, expect=409)
        self.post("team_up", up, "submit")
        self.imp("team_up", up, expect=409)
        self.post("team_rv", up, "approval", decision="approve")
        res = self.client.post(f"/api/csv/uploads/{up}/import", headers=self._h("team_up"))
        self.assertEqual(res.status_code, 422, res.text)
        self.assertEqual(self.registry("team_up"), [])

    def test_a_direct_upload_has_no_workflow(self):
        res = self.client.post("/api/csv/upload", headers=self._h("team_up"),
                               json={"fileName": f"{self.tag}_legacy.csv", "content": self.one}).json()
        self.assertEqual(self.state("team_up", res["uploadId"]), "legacy")
        self.post("team_up", res["uploadId"], "submit", expect=409)
        # ...and review of it still works as before M6.
        self.decide("team_rv", res["uploadId"], 1)

    def test_uploads_list_shows_the_workflow_state(self):
        up = self.stage("team_up", "list.csv", self.one)["uploadId"]
        listing = {u["id"]: u["state"] for u in self.client.get("/api/csv/uploads", headers=self._h("team_up")).json()}
        self.assertEqual(listing[up], "staged")
        self.assertEqual(self.client.get(f"/api/csv/uploads/{up}", headers=self._h("team_up")).json()["state"], "staged")

    def test_bad_files_are_recorded_and_refused(self):
        bad = self.stage("team_up", "bad.csv", "only,a,header\n", expect=422)
        self.assertEqual((bad["status"], bad["reason"]), ("invalid_structure", "header_only"))
        recorded = {u["id"]: u["status"] for u in self.client.get("/api/csv/uploads", headers=self._h("team_up")).json()}
        self.assertEqual(recorded[bad["uploadId"]], "rejected", "every attempt gets an uploads row (BR-23)")
        self.stage("team_up", "types.csv", self.one, expect=422, types=["int8", "text"])


@pytest.mark.integration
class SelfApproval(_Base):
    def setUp(self):
        super().setUp()
        with Conn() as conn, conn.cursor() as cur:
            accounts.set_self_approval(cur, self.slugs["solo"], False)
            conn.commit()

    def test_a_member_cannot_approve_what_they_uploaded_or_submitted(self):
        up = self.stage("team_ad", "own.csv", self.one)["uploadId"]
        self.post("team_ad", up, "submit")
        refused = self.post("team_ad", up, "approval", expect=403, decision="approve")
        self.assertIn("another member must approve", refused["message"])
        self.post("team_rv", up, "approval", decision="approve")      # someone else can
        self.assertEqual(self.state("team_ad", up), "approved")

    def test_the_submitter_cannot_approve_even_if_someone_else_uploaded(self):
        up = self.stage("team_up", "sub.csv", self.one)["uploadId"]
        self.post("team_ad", up, "submit")
        self.post("team_ad", up, "approval", expect=403, decision="approve")

    def test_a_tenant_can_allow_self_approval(self):
        up = self.stage("solo_ad", "solo.csv", self.one)["uploadId"]
        self.post("solo_ad", up, "submit")
        self.post("solo_ad", up, "approval", expect=403, decision="approve")
        with Conn() as conn, conn.cursor() as cur:
            accounts.set_self_approval(cur, self.slugs["solo"], True)
            conn.commit()
        self.post("solo_ad", up, "approval", decision="approve")
        self.assertEqual(self.imp("solo_ad", up)["reconciliation"]["imported"], 1)

    def test_the_setting_is_per_tenant(self):
        with Conn() as conn, conn.cursor() as cur:
            accounts.set_self_approval(cur, self.slugs["solo"], True)
            conn.commit()
            with self.assertRaises(ValueError):
                accounts.set_self_approval(cur, "no_such_tenant", True)
        up = self.stage("team_ad", "other.csv", self.one)["uploadId"]
        self.post("team_ad", up, "submit")
        self.post("team_ad", up, "approval", expect=403, decision="approve")

    def test_a_request_with_no_session_has_no_identity_to_compare(self):
        up = self.stage(None, "nosession.csv", self.one)["uploadId"]
        self.post(None, up, "submit")
        self.post(None, up, "approval", decision="approve")
        result = self.imp(None, up)
        self.assertEqual(result["reconciliation"]["imported"], 1)
        self.client.delete(f"/api/csv/files/{result['fileId']}")


@pytest.mark.integration
class AllOrNothing(_Base):
    """Failure injected at each step of the import leaves nothing behind (decision 4, ADR-0002)."""

    def _leftovers(self, table_like: str) -> dict:
        return {
            "files": self.registry("team_up"),
            "imports": self.team_sql("SELECT count(*) FROM {s}.imports")[0][0],
            "imported_audit": self.team_sql("SELECT count(*) FROM {s}.audit_log WHERE action = 'import'")[0][0],
            "tables": [r[0] for r in self.team_sql(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_name LIKE %s",
                (schema_for(self.slugs["team"]), table_like))],
        }

    def test_failure_at_every_step_changes_nothing_and_a_retry_then_succeeds(self):
        for step in ("registered", "staged", "promoted"):
            with self.subTest(step=step):
                name = f"fail_{step}.csv"
                up = self.approved(f"k,v\n1,a\n2,b\n3,{step}\n", name=name)
                like = "csv_%" + step + "%"

                def boom(at, step=step):
                    if at == step:
                        raise RuntimeError("injected failure")

                with patch.object(staged_import, "_checkpoint", boom):
                    with self.assertRaises(RuntimeError):
                        self.client.post(f"/api/csv/uploads/{up}/import",
                                         headers={**self._h("team_up"), "Idempotency-Key": "retry-me"})
                left = self._leftovers(like)
                self.assertEqual(([f for f in left["files"] if step in f["file_name"]], left["tables"]), ([], []))
                self.assertEqual(self.state("team_up", up), "approved", "still approved and importable")
                imports_before = left["imports"]
                audit_before = left["imported_audit"]

                result = self.imp("team_up", up, key="retry-me")        # the retry, same key
                self.assertEqual((result["replayed"], result["reconciliation"]["imported"]), (False, 3))
                after = self._leftovers(like)
                self.assertEqual((after["imports"], after["imported_audit"]), (imports_before + 1, audit_before + 1))
                self.assertEqual(len(after["tables"]), 1)

    def test_a_retry_after_success_returns_the_original_and_adds_nothing(self):
        up = self.approved("k\n1\n2\n")
        first = self.imp("team_up", up, key="same")
        again = self.imp("team_up", up, key="same")
        self.assertEqual((again["replayed"], again["importId"], again["tableName"]),
                         (True, first["importId"], first["tableName"]))
        self.assertEqual(self.team_sql('SELECT count(*) FROM {s}."' + first["tableName"] + '"')[0][0], 2)
        other = self.imp("team_up", up, key="different", expect=409)
        self.assertEqual(other["importId"], first["importId"])
        self.assertEqual(self.team_sql("SELECT count(*) FROM {s}.imports WHERE upload_id = %s", (int(up),))[0][0], 1)

    def test_concurrent_imports_of_one_upload_import_it_once(self):
        up = self.approved("k\n1\n2\n3\n")

        def run(key):
            return self.client.post(f"/api/csv/uploads/{up}/import",
                                    headers={**self._h("team_up"), "Idempotency-Key": key})

        with ThreadPoolExecutor(max_workers=2) as pool:
            different = sorted(r.status_code for r in pool.map(run, ["a", "b"]))
        self.assertEqual(different, [200, 409])
        self.assertEqual(len(self.registry("team_up")), 1)
        self.assertEqual(self.team_sql("SELECT count(*) FROM {s}.imports WHERE upload_id = %s", (int(up),))[0][0], 1)

        up2 = self.approved("k\n7\n8\n", name="same_key.csv")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.client.post(
                f"/api/csv/uploads/{up2}/import", headers={**self._h("team_up"), "Idempotency-Key": "z"}), range(2)))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual(sorted(r.json()["replayed"] for r in results), [False, True])
        self.assertEqual(self.team_sql("SELECT count(*) FROM {s}.imports WHERE upload_id = %s", (int(up2),))[0][0], 1)

    def test_the_same_bytes_staged_twice_import_once(self):
        first = self.stage("team_up", "twice.csv", "k\nsame\n")["uploadId"]
        second = self.stage("team_up", "twice_copy.csv", "k\nsame\n")["uploadId"]    # not in the registry yet
        for up in (first, second):
            self.post("team_up", up, "submit")
            self.post("team_rv", up, "approval", decision="approve")
        self.imp("team_up", first)
        refused = self.imp("team_up", second, expect=409)
        self.assertEqual(refused["state"], "duplicate_file")
        self.assertEqual(self.state("team_up", second), "approved")
        self.assertEqual(len(self.registry("team_up")), 1)
        # Staging the same bytes after the import is refused up front, and still recorded.
        dup = self.stage("team_up", "twice_again.csv", "k\nsame\n", expect=409)
        self.assertEqual(dup["status"], "duplicate_file")


@pytest.mark.integration
class DataFidelityAndVersions(_Base):
    def test_values_survive_the_copy_exactly(self):
        content = 'k,v\n1,"he said ""hi"", ok"\n2,\\N\n3,\n4,héllo ✓\n5,"two\nlines"\n'
        up = self.approved(content, name="fidelity.csv", types=["int8", "text"])
        table = self.imp("team_up", up)["tableName"]
        rows = self.team_sql('SELECT k, v FROM {s}."' + table + '" ORDER BY k')
        self.assertEqual(rows, [(1, 'he said "hi", ok'), (2, "\\N"), (3, None), (4, "héllo ✓"), (5, "two\nlines")])

    def test_typed_columns_are_loaded_as_their_types(self):
        content = "n,d,t,b,x\n12,2026-01-31,2026-01-31T10:00:00Z,true,1.50\n"
        up = self.approved(content, name="types.csv", types=["int8", "date", "timestamptz", "boolean", "numeric"])
        table = self.imp("team_up", up)["tableName"]
        [row] = self.team_sql("SELECT n, d::text, (t AT TIME ZONE 'UTC')::text, b, x::text FROM {s}." + f'"{table}"')
        self.assertEqual(row, (12, "2026-01-31", "2026-01-31 10:00:00", True, "1.50"))

    def test_the_registry_records_whether_the_types_were_confirmed(self):
        confirmed = self.approved(f"n\n{self.tag}1\n", name="c.csv", types=["text"], typesConfirmed=True)
        guessed = self.approved(f"n\n{self.tag}2\n", name="g.csv", types=["text"])
        unsent = self.approved(f"n\n{self.tag}3\n", name="u.csv")
        for up in (confirmed, guessed, unsent):
            self.imp("team_up", up, key=f"k{up}")
        found = {f["file_name"].split("_", 1)[1]: f["types_provenance"] for f in self.registry("team_up")}
        self.assertEqual(found, {"c.csv": "user_confirmed", "g.csv": "inferred_unconfirmed",
                                 "u.csv": "inferred_unconfirmed"})
        self.stage("team_up", "bad.csv", f"n\n{self.tag}4\n", expect=422, typesConfirmed=True)  # no types sent

    def test_a_second_file_with_the_same_name_is_version_two_and_flags_are_known_before_approval(self):
        v1 = self.approved(f"k,v\n1,a\n2,{self.tag}\n", name="series.csv")
        self.assertEqual(self.imp("team_up", v1)["version"], 1)
        staged = self.stage("team_up", "series.csv", f"k,v\n2,{self.tag}\n3,c\n")
        self.assertEqual(staged["duplicateRowsAcrossUploads"], 1, "flagged at staging, so the reviewer sees it")
        page = self.client.get(f"/api/csv/uploads/{staged['uploadId']}/rows", headers=self._h("team_rv")).json()["rows"]
        self.assertEqual(page[0]["duplicateOfEarlierVersion"]["version"], 1)
        up = staged["uploadId"]
        self.post("team_up", up, "submit")
        self.decide("team_rv", up, 1)                              # the reviewer drops the repeated row
        self.post("team_rv", up, "approval", decision="approve")
        result = self.imp("team_up", up)
        self.assertEqual((result["version"], result["reconciliation"]["imported"]), (2, 1))
        self.assertTrue(result["schemaCheck"]["compatible"])
        self.assertTrue(result["tableName"].endswith("_v2"))

    def test_staged_uploads_keep_every_attempt_even_when_never_imported(self):
        up = self.stage("team_up", "abandoned.csv", self.one)["uploadId"]
        [row] = self.team_sql("SELECT status, byte_size FROM {s}.uploads WHERE id = %s", (int(up),))
        self.assertEqual(row, ("staged", len(self.one.encode())))
        res = self.client.get(f"/api/csv/uploads/{up}/original", headers=self._h("team_rv"))
        self.assertEqual(res.content, self.one.encode())


@pytest.mark.integration
class WorkflowTablesAreInsertOnly(_Base):
    def test_no_update_or_delete_on_submissions_approvals_imports(self):
        import psycopg2.errors

        up = self.approved(self.one)
        self.imp("team_up", up)
        schema = sql.Identifier(schema_for(self.slugs["team"]))
        with Conn() as conn, conn.cursor() as cur:
            for table, update in (("submissions", "note = 'x'"), ("approvals", "reason = 'x'"),
                                  ("imports", "rows_in = 0")):
                for statement in (f"UPDATE {{}}.{table} SET {update}", f"DELETE FROM {{}}.{table}",
                                  f"TRUNCATE {{}}.{table}"):
                    with self.subTest(statement=statement):
                        # The trigger refuses it; for a table other tables reference, PostgreSQL's own
                        # foreign-key check refuses TRUNCATE first. Either way nothing changes.
                        try:
                            with self.assertRaises((psycopg2.errors.InsufficientPrivilege,
                                                    psycopg2.errors.FeatureNotSupported)):
                                cur.execute(sql.SQL(statement).format(schema))
                        finally:
                            conn.rollback()
        self.assertEqual(self.team_sql("SELECT count(*) FROM {s}.imports WHERE upload_id = %s", (int(up),))[0][0], 1)
