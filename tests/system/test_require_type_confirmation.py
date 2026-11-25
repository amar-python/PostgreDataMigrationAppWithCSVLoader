"""A server can refuse a dynamic-mode upload whose column types nobody confirmed (#242, option B).

API_REQUIRE_TYPE_CONFIRMATION is off by default, so existing callers are unchanged. When it is on,
both dynamic entry points (POST /api/csv/upload and the staged POST /api/csv/uploads) answer 422 unless
the request carries `types` and `typesConfirmed: true`, and nothing is created. T&E mode is not affected.

Integration: needs a live PostgreSQL. Fails (never skips) without one.
"""

from __future__ import annotations

import os
import unittest
import uuid

import pytest
from fastapi.testclient import TestClient

from api.config import settings
from api.main import app

CONFIRMED = {"types": ["int8", "text"], "typesConfirmed": True}


@pytest.mark.integration
class RequireTypeConfirmation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self._saved = settings.REQUIRE_TYPE_CONFIRMATION
        self.tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        settings.REQUIRE_TYPE_CONFIRMATION = self._saved

    def _body(self, name: str, **extra) -> dict:
        return {"fileName": f"req_{name}_{self.tag}.csv", "content": f"n,label\n1,{self.tag}{name}\n", **extra}

    def _upload(self, name: str, **extra):
        return self.client.post("/api/csv/upload", json=self._body(name, **extra))

    def _stage(self, name: str, **extra):
        return self.client.post("/api/csv/uploads", json=self._body(name, **extra))

    def _counts(self) -> tuple[int, int]:
        files = len(self.client.get("/api/csv/files").json())
        attempts = len(self.client.get("/api/csv/uploads", params={"limit": 500}).json())
        return files, attempts

    # ── the setting is off: nothing changes ───────────────────────────────────────

    def test_off_by_default(self):
        if "API_REQUIRE_TYPE_CONFIRMATION" not in os.environ:  # the default, unless this run was configured otherwise
            self.assertIs(self._saved, False)

    def test_off_still_accepts_an_upload_without_confirmed_types(self):
        settings.REQUIRE_TYPE_CONFIRMATION = False
        res = self._upload("off")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["typesProvenance"], "inferred_unconfirmed")
        staged = self._stage("offstaged")
        self.assertEqual(staged.status_code, 200, staged.text)
        self.assertEqual(staged.json()["typesProvenance"], "inferred_unconfirmed")

    # ── the setting is on: both entry points refuse, and leave nothing behind ─────

    def test_on_refuses_each_kind_of_unconfirmed_request_on_both_endpoints(self):
        settings.REQUIRE_TYPE_CONFIRMATION = True
        cases = {
            "no types, no flag": {},
            "types but not confirmed": {"types": ["int8", "text"]},
            "confirmed flag, no types": {"typesConfirmed": True},
            "confirmed false": {"types": ["int8", "text"], "typesConfirmed": False},
        }
        for label, extra in cases.items():
            for endpoint in (self._upload, self._stage):
                with self.subTest(case=label, endpoint=endpoint.__name__):
                    before = self._counts()
                    res = endpoint(f"refused{abs(hash((label, endpoint.__name__))) % 10000}", **extra)
                    self.assertEqual(res.status_code, 422, res.text)
                    self.assertEqual(self._counts(), before, "a refused request must create nothing")

    def test_the_refusal_says_what_to_send(self):
        settings.REQUIRE_TYPE_CONFIRMATION = True
        for endpoint in (self._upload, self._stage):
            with self.subTest(endpoint=endpoint.__name__):
                detail = str(endpoint("msg").json()["detail"])
                self.assertIn("typesConfirmed", detail)
                self.assertIn("types", detail)

    def test_on_accepts_confirmed_types_on_both_endpoints(self):
        settings.REQUIRE_TYPE_CONFIRMATION = True
        for name, endpoint in (("up", self._upload), ("st", self._stage)):
            with self.subTest(endpoint=endpoint.__name__):
                res = endpoint(name, **CONFIRMED)
                self.assertEqual(res.status_code, 200, res.text)
                self.assertEqual(res.json()["typesProvenance"], "user_confirmed")

    def test_on_does_not_touch_te_mode(self):
        settings.REQUIRE_TYPE_CONFIRMATION = True
        res = self.client.post(
            "/api/csv/upload",
            json={
                "fileName": f"req_te_{self.tag}.csv",
                "mode": "te",
                "targetTable": "organisations",
                "content": f"name,org_type,country\nREQ_{self.tag},government,AU\n",
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["status"], "ok", res.text)

    def test_the_old_rule_still_applies_when_on(self):
        # typesConfirmed without types was already a 422; the new rule must not change its meaning.
        settings.REQUIRE_TYPE_CONFIRMATION = True
        res = self._upload("old", typesConfirmed=True)
        self.assertEqual(res.status_code, 422)
